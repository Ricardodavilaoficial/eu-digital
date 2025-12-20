# routes/ycloud_webhook_bp.py
# Webhook oficial YCloud (GLOBAL) — ingress seguro + normalização + log
# Rota: POST /integracoes/ycloud/webhook
# - NÃO depende de frontend
# - NÃO escreve em profissionais/*
# - Apenas valida assinatura (opcional), normaliza e registra em Firestore (coleção global)

from __future__ import annotations

import os, json, time, hmac, hashlib
from typing import Any, Dict, Optional, Tuple

import logging

from flask import Blueprint, request, jsonify
from google.cloud import firestore  # type: ignore

from services.firebase_admin_init import ensure_firebase_admin
from providers.ycloud import send_text as ycloud_send_text  # sender oficial (já validado)
from services.voice_wa_link import get_uid_for_sender
from services.voice_wa_download import download_media_bytes
from services.voice_wa_storage import upload_voice_bytes

ycloud_webhook_bp = Blueprint("ycloud_webhook_bp", __name__)

logger = logging.getLogger(__name__)

def _db():
    ensure_firebase_admin()
    return firestore.Client()

def _voice_status_ref(uid: str):
    # Single source of truth (não inventar outro path)
    return _db().collection('profissionais').document(uid).collection('voz').document('whatsapp')

def _now_ts():
    return firestore.SERVER_TIMESTAMP  # type: ignore

# ============================================================
# PATCH A — DEDUPE Firestore (mínimo e cirúrgico)
# ============================================================
def _dedupe_once(key: str, ttl_seconds: int = 3600) -> bool:
    """
    Retorna True se for a primeira vez que vemos esta chave (pode responder).
    Retorna False se já foi processado (não responde de novo).
    """
    try:
        if not key:
            return True  # sem chave, não bloqueia
        db = _db()
        ref = db.collection("platform_wa_dedupe").document(key)
        snap = ref.get()
        if snap.exists:
            return False
        ref.set({
            "createdAt": _now_ts(),
            "ttlSeconds": int(ttl_seconds),
        })
        return True
    except Exception:
        # se Firestore falhar, melhor NÃO spammar => bloqueia
        return False

def _safe_str(x: Any, limit: int = 180) -> str:
    s = "" if x is None else str(x)
    s = s.replace("\n", " ").replace("\r", " ").strip()
    return s[:limit]

def _get_sig_header() -> str:
    # YCloud usa header "YCloud-Signature"
    return (request.headers.get("YCloud-Signature") or "").strip()

def _parse_sig(sig: str) -> Tuple[Optional[int], Optional[str]]:
    # Formato: t=1654084800,s=<hex>
    try:
        parts = [p.strip() for p in sig.split(",") if p.strip()]
        kv = {}
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                kv[k.strip()] = v.strip()
        ts = int(kv.get("t") or "0") if kv.get("t") else None
        s = kv.get("s")
        if not ts or not s:
            return None, None
        return ts, s
    except Exception:
        return None, None

def _verify_signature_if_enabled(raw_body: bytes) -> bool:
    secret = (os.environ.get("YCLOUD_WEBHOOK_SIGNING_SECRET") or "").strip()
    if not secret:
        # Sem secret => não valida (modo permissivo), mas ainda loga
        return True

    sig = _get_sig_header()
    ts, sig_hex = _parse_sig(sig)
    if not ts or not sig_hex:
        return False

    tol = int(os.environ.get("YCLOUD_WEBHOOK_TOLERANCE_SECONDS", "300") or "300")
    now = int(time.time())
    if abs(now - ts) > tol:
        return False

    signed_payload = f"{ts}.".encode("utf-8") + raw_body
    mac = hmac.new(secret.encode("utf-8"), msg=signed_payload, digestmod=hashlib.sha256).hexdigest()

    # comparação constante
    try:
        return hmac.compare_digest(mac, sig_hex)
    except Exception:
        return False

def _normalize_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza o payload YCloud para um envelope canônico GLOBAL.
    Baseado no evento whatsapp.inbound_message.received e whatsapp.message.updated.
    """
    ev_type = _safe_str(payload.get("type"))
    ev_id = _safe_str(payload.get("id"))
    api_version = _safe_str(payload.get("apiVersion"))
    create_time = _safe_str(payload.get("createTime"))

    # Inbound messages
    msg = payload.get("whatsappInboundMessage") or {}
    msg_type = _safe_str(msg.get("type"))
    from_msisdn = _safe_str(msg.get("from"))
    to_msisdn = _safe_str(msg.get("to"))
    wamid = _safe_str(msg.get("wamid") or msg.get("context", {}).get("wamid") or msg.get("context", {}).get("id"))

    text = ""
    media: Dict[str, Any] = {}

    if msg_type == "text":
        text = _safe_str((msg.get("text") or {}).get("body") or msg.get("text") or "" , 2000)

    elif msg_type in ("audio", "voice", "ptt"):
        a = (msg.get("audio") or msg.get("voice") or msg.get("ptt") or {})
        media = {
            "kind": "audio",
            "url": _safe_str(a.get("link") or a.get("url") or a.get("downloadUrl") or a.get("download_url"), 500),
            "mimeType": _safe_str(a.get("mimeType") or a.get("mime_type") or ""),
            "sha256": _safe_str(a.get("sha256") or ""),
            "id": _safe_str(a.get("id") or ""),
        }

    elif msg_type in ("image", "video", "document", "sticker"):
        obj = msg.get(msg_type) or {}
        media = {
            "kind": msg_type,
            "url": _safe_str(obj.get("url"), 500),
            "caption": _safe_str(obj.get("caption") or "", 500),
            "mimeType": _safe_str(obj.get("mimeType") or obj.get("mime_type") or ""),
            "sha256": _safe_str(obj.get("sha256") or ""),
            "id": _safe_str(obj.get("id") or ""),
            "filename": _safe_str(obj.get("filename") or "", 160),
        }

    # Status updates (outbound)
    st = payload.get("whatsappMessage") or {}
    status = _safe_str(st.get("status"))
    error_code = _safe_str(st.get("errorCode"))
    error_msg = _safe_str(st.get("errorMessage"), 500)
    st_wamid = _safe_str(st.get("wamid"))
    st_id = _safe_str(st.get("id"))

    kind = "event"
    if ev_type == "whatsapp.inbound_message.received":
        kind = "inbound"
    elif ev_type == "whatsapp.message.updated":
        kind = "status"

    return {
        "provider": "ycloud",
        "kind": kind,
        "eventId": ev_id,
        "eventType": ev_type,
        "apiVersion": api_version,
        "createTime": create_time,

        "from": from_msisdn,
        "to": to_msisdn,
        "wamid": wamid or st_wamid,
        "messageId": st_id or _safe_str(msg.get("id")),

        "messageType": msg_type,
        "text": text,
        "media": media,

        "status": status,
        "errorCode": error_code,
        "errorMessage": error_msg,
    }

def _log_global(envelope: Dict[str, Any], raw_body: Optional[str] = None):
    try:
        db = _db()
        doc: Dict[str, Any] = {
            "createdAt": _now_ts(),
            "provider": "ycloud",
            "kind": envelope.get("kind"),
            "eventType": envelope.get("eventType"),
            "from": envelope.get("from"),
            "to": envelope.get("to"),
            "wamid": envelope.get("wamid"),
            "messageType": envelope.get("messageType"),
            "status": envelope.get("status"),
            "errorCode": envelope.get("errorCode"),
            "errorMessage": envelope.get("errorMessage"),
            "envelope": envelope,
        }
        if raw_body is not None:
            doc["raw"] = raw_body[:12000]  # corta pra não explodir Firestore
        db.collection("platform_wa_logs").add(doc)
    except Exception:
        pass

@ycloud_webhook_bp.route("/integracoes/ycloud/webhook", methods=["POST"])
def ycloud_webhook_ingress():
    raw = request.get_data(cache=False) or b""

    # ============================================================
    # PATCH 1 — Log do JSON Bruto (sempre)  [mantido como estava]
    # - Captura o corpo bruto antes de qualquer validação/parse
    # - Grava em platform_wa_raw_logs como texto (UTF-8 com replace)
    # ============================================================
    try:
        raw_txt = raw.decode("utf-8", errors="replace")
    except Exception:
        raw_txt = None

    if raw_txt:
        try:
            db = _db()
            db.collection("platform_wa_raw_logs").add({
                "createdAt": _now_ts(),
                "rawData": raw_txt
            })
        except Exception:
            pass

    if not _verify_signature_if_enabled(raw):
        # Segurança: responde 200 “ok” pra não virar DoS por retry,
        # mas ignora e registra que falhou verificação.
        env = {
            "provider": "ycloud",
            "kind": "ignored",
            "eventType": "signature_invalid",
            "from": "",
            "to": "",
            "messageType": "",
            "text": "",
            "media": {},
            "status": "",
            "errorCode": "sig_invalid",
            "errorMessage": "signature_invalid_or_expired",
        }
        _log_global(env, raw_body=None)
        return jsonify({"ok": True, "ignored": True}), 200

    # ============================================================
    # PATCH 1 — Parse robusto do body (JSON + payload= + data=)
    # ============================================================
    # tenta JSON pelo Flask; se falhar, faz parse manual do body cru (inclui payload=...)
    payload = request.get_json(silent=True) or {}

    if not payload and raw:
        try:
            raw_txt_try = raw.decode("utf-8", errors="replace").strip()

            # caso comum: "payload={...}" (form-urlencoded)
            if raw_txt_try.startswith("payload="):
                from urllib.parse import parse_qs
                qs = parse_qs(raw_txt_try, keep_blank_values=True)
                cand = (qs.get("payload") or [""])[0]
                payload = json.loads(cand) if cand else {}

            # caso comum: "data={...}"
            elif raw_txt_try.startswith("data="):
                from urllib.parse import parse_qs
                qs = parse_qs(raw_txt_try, keep_blank_values=True)
                cand = (qs.get("data") or [""])[0]
                payload = json.loads(cand) if cand else {}

            # caso comum: JSON puro como texto
            else:
                payload = json.loads(raw_txt_try)

        except Exception:
            payload = {}

    # se vier embrulhado (muito comum em webhooks): {"data": {...}}
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]

    # ============================================================
    # PATCH 2 — Logar o RAW automaticamente quando o parse falhar
    # + garante env normalizado DEPOIS do parse robusto
    # ============================================================
    log_raw = (os.environ.get("YCLOUD_WEBHOOK_LOG_RAW", "0").strip() == "1")

    raw_txt2 = None
    # loga raw se: (a) flag ligada OU (b) payload veio vazio (sinal de parse quebrado)
    if log_raw or not payload:
        try:
            raw_txt2 = raw.decode("utf-8", errors="replace")
        except Exception:
            raw_txt2 = None

    env = _normalize_event(payload)    # ============================================================
    # Ingestão de VOZ (áudio) — mínimo v1 (salva no Storage + status no Firestore)
    # - Não responde no WhatsApp (por enquanto)
    # - Resolve uid pelo vínculo do invite (services.voice_wa_link)
    # ============================================================
    try:
        if env.get("eventType") == "whatsapp.inbound_message.received" and env.get("messageType") in ("audio", "voice", "ptt"):
            from_e164 = (env.get("from") or "").strip()
            media = env.get("media") or {}

            # Normaliza chaves esperadas pelo downloader
            media_for_dl = {
                "url": (media.get("url") or "").strip(),
                "mimeType": (media.get("mimeType") or media.get("mime") or "").strip(),
                "id": (media.get("id") or "").strip(),
                "sha256": (media.get("sha256") or "").strip(),
                "filename": (media.get("filename") or "").strip(),
            }

            uid = get_uid_for_sender(from_e164) if from_e164 else ""
            if not uid:
                logger.info("[ycloud_webhook] voice: sem uid (ignore). from=%s", from_e164)
                _log_global(env, raw_body=raw_txt2)
                return jsonify({"ok": True, "ignored": True}), 200

            if not media_for_dl["url"]:
                logger.info("[ycloud_webhook] voice: sem media_url. uid=%s from=%s", uid, from_e164)
                _voice_status_ref(uid).set({
                    "status": "failed",
                    "lastError": "missing_media_url",
                    "updatedAt": _now_ts(),
                    "source": "whatsapp",
                    "waFromE164": from_e164,
                }, merge=True)
                _log_global(env, raw_body=raw_txt2)
                return jsonify({"ok": True}), 200

            # Baixa bytes (usa token/headers internamente conforme implementação)
            voice_bytes, mime = download_media_bytes(provider="ycloud", media=media_for_dl)

            # Define path raw no Storage (single source of truth do arquivo)
            ext = "ogg"
            m2 = (mime or media_for_dl["mimeType"] or "").lower()
            if "mpeg" in m2 or "mp3" in m2:
                ext = "mp3"
            elif "wav" in m2:
                ext = "wav"
            elif "ogg" in m2 or "opus" in m2:
                ext = "ogg"

            storage_path = f"profissionais/{uid}/voz/original/whatsapp_{int(time.time())}.{ext}"
            upload_voice_bytes(storage_path=storage_path, content_type=(mime or media_for_dl["mimeType"] or "application/octet-stream"), data=voice_bytes)

            _voice_status_ref(uid).set({
                "status": "received",
                "updatedAt": _now_ts(),
                "source": "whatsapp",
                "waFromE164": from_e164,
                "lastAudioGcsPath": storage_path,
                "lastAudioMime": (mime or media_for_dl["mimeType"] or ""),
                "lastInboundAt": _now_ts(),
                "lastError": "",
            }, merge=True)

            logger.info("[ycloud_webhook] voice: salvo uid=%s path=%s", uid, storage_path)
            _log_global(env, raw_body=raw_txt2)
            return jsonify({"ok": True}), 200
    except Exception as e:
        # Não quebra o webhook; registra falha no status se der pra resolver uid
        try:
            from_e164 = (env.get("from") or "").strip()
            uid = get_uid_for_sender(from_e164) if from_e164 else ""
            if uid:
                _voice_status_ref(uid).set({
                    "status": "failed",
                    "lastError": f"ingest_failed:{type(e).__name__}",
                    "updatedAt": _now_ts(),
                    "source": "whatsapp",
                    "waFromE164": from_e164,
                }, merge=True)
        except Exception:
            pass
        logger.exception("[ycloud_webhook] voice: falha ingest")

    # ============================================================
    # Auto-reply simples (MVP): só para inbound TEXT (dedupe)
    # - Mantém comportamento anterior, mas sem derrubar o webhook
    # ============================================================
    try:
        if env.get("eventType") == "whatsapp.inbound_message.received" and env.get("messageType") == "text":
            from_e164 = (env.get("from") or "").strip()
            if from_e164:
                reply = "Recebi 👍 Digite: 1 Voz | 2 Suporte | 3 Planos"

                msg_id = (env.get("messageId") or env.get("wamid") or "").strip()
                if not msg_id or _dedupe_once(msg_id):
                    ycloud_send_text(from_e164, reply)
    except Exception:
        pass
    _log_global(env, raw_body=raw_txt2)

    # Atividade 1: só ingress + log.
    return jsonify({"ok": True}), 200


    # ============================================================
    # PATCH 3 — (Opcional) Stub compat do endpoint legado
    # Evita retry infinito de integrações antigas.
    # ============================================================



