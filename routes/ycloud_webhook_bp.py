# routes/ycloud_webhook_bp.py
# Webhook oficial YCloud (GLOBAL) — ingress seguro + normalização + log
# Rota: POST /integracoes/ycloud/webhook
# - NÃO depende de frontend
# - NÃO escreve em profissionais/*
# - Apenas valida assinatura (opcional), normaliza e registra em Firestore (coleção global)

from __future__ import annotations

import os, json, time, hmac, hashlib
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, request, jsonify
from google.cloud import firestore  # type: ignore

from services.firebase_admin_init import ensure_firebase_admin
from providers.ycloud import send_text as ycloud_send_text  # sender oficial (já validado)

ycloud_webhook_bp = Blueprint("ycloud_webhook_bp", __name__)

def _db():
    ensure_firebase_admin()
    return firestore.Client()

def _now_ts():
    return firestore.SERVER_TIMESTAMP  # type: ignore

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

    elif msg_type in ("audio", "voice"):
        a = msg.get("audio") or {}
        media = {
            "kind": "audio",
            "url": _safe_str(a.get("url"), 500),
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

    payload = request.get_json(silent=True) or {}
    env = _normalize_event(payload)

    # ============================================================
    # Auto-reply simples (MVP): só para inbound TEXT
    # - Não depende de VOICE_WA_MODE
    # - Não escreve em profissionais/*
    # - Responde apenas se vier whatsapp.inbound_message.received (text)
    # ============================================================

    try:
        if env.get("eventType") == "whatsapp.inbound_message.received" and env.get("messageType") == "text":
            from_e164 = (env.get("from") or "").strip()
            if from_e164:
                reply = "Recebi 👍 Digite: 1 Voz | 2 Suporte | 3 Planos"
                # usa sender oficial (providers/ycloud.py)
                ycloud_send_text(from_e164, reply)
    except Exception:
        # não quebra o webhook por causa de resposta
        pass

    log_raw = (os.environ.get("YCLOUD_WEBHOOK_LOG_RAW", "0").strip() == "1")
    raw_txt = None
    if log_raw:
        try:
            raw_txt = raw.decode("utf-8", errors="replace")
        except Exception:
            raw_txt = None

    _log_global(env, raw_body=raw_txt)

    # Atividade 1: só ingress + log.
    return jsonify({"ok": True}), 200


# (OPCIONAL) compat: endpoint legado /webhooks/voice-wa
# Evita retry infinito de integrações antigas.
@ycloud_webhook_bp.route("/webhooks/voice-wa", methods=["POST"])
def voice_wa_compat_stub():
    # compat legado: responde ok e não faz nada
    return jsonify({"ok": True, "ignored": True, "reason": "deprecated_endpoint"}), 200
