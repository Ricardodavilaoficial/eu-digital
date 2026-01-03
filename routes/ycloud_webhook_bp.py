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
from providers.ycloud import send_text as ycloud_send_text

try:
    from providers.ycloud import send_audio as ycloud_send_audio  # opcional
except Exception:
    ycloud_send_audio = None  # type: ignore

from services.voice_wa_link import get_uid_for_sender, upsert_sender_link
from services.voice_wa_download import download_media_bytes
from services.voice_wa_storage import upload_voice_bytes

ycloud_webhook_bp = Blueprint("ycloud_webhook_bp", __name__)
logger = logging.getLogger(__name__)

@ycloud_webhook_bp.route("/integracoes/ycloud/ping", methods=["GET"])
def ycloud_ping():
    return jsonify({"ok": True, "ping": "ycloud_webhook_bp", "code": "ycloud_webhook_v2026-01-02a"}), 200
    
def _db():
    ensure_firebase_admin()
    return firestore.Client()

def _voice_status_ref(uid: str):
    # Single source of truth
    return _db().collection('profissionais').document(uid).collection('voz').document('whatsapp')

def _now_ts():
    return firestore.SERVER_TIMESTAMP  # type: ignore

# ============================================================
# DEDUPE simples (não responder duas vezes)
# ============================================================
def _dedupe_once(key: str, ttl_seconds: int = 3600) -> bool:
    try:
        if not key:
            return True
        db = _db()
        ref = db.collection("platform_wa_dedupe").document(key)
        if ref.get().exists:
            return False
        ref.set({"createdAt": _now_ts(), "ttlSeconds": int(ttl_seconds)})
        return True
    except Exception:
        return False

def _safe_str(x: Any, limit: int = 180) -> str:
    s = "" if x is None else str(x)
    s = s.replace("\n", " ").replace("\r", " ").strip()
    return s[:limit]

def _get_sig_header() -> str:
    return (request.headers.get("YCloud-Signature") or "").strip()

def _parse_sig(sig: str) -> Tuple[Optional[int], Optional[str]]:
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
        return True
    sig = _get_sig_header()
    ts, sig_hex = _parse_sig(sig)
    if not ts or not sig_hex:
        return False
    tol = int(os.environ.get("YCLOUD_WEBHOOK_TOLERANCE_SECONDS", "300") or "300")
    if abs(int(time.time()) - ts) > tol:
        return False
    mac = hmac.new(secret.encode("utf-8"), msg=f"{ts}.".encode("utf-8") + raw_body, digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sig_hex)

def _normalize_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    ev_type = _safe_str(payload.get("type"))
    msg = payload.get("whatsappInboundMessage") or {}
    msg_type = _safe_str(msg.get("type"))
    
    # YCloud às vezes não envia whatsappInboundMessage.type.
    # Inferimos pelo conteúdo (seguro e retrocompatível).
    if not msg_type:
        if "text" in msg and msg.get("text") is not None:
            msg_type = "text"
        elif any(k in msg and msg.get(k) for k in ("audio", "voice", "ptt")):
            msg_type = "audio"
    
    from_msisdn = _safe_str(msg.get("from"))
    to_msisdn = _safe_str(msg.get("to"))
    wamid = _safe_str(msg.get("wamid") or msg.get("context", {}).get("wamid") or msg.get("context", {}).get("id"))

    text = ""
    media: Dict[str, Any] = {}

    if msg_type == "text":
        t = msg.get("text")
        if isinstance(t, dict):
            text = _safe_str(t.get("body") or t.get("text") or t.get("message") or "", 2000)
        else:
            # string ou algo simples
            text = _safe_str(t or msg.get("body") or msg.get("message") or "", 2000)
    elif msg_type in ("audio", "voice", "ptt"):
        a = (msg.get("audio") or msg.get("voice") or msg.get("ptt") or {})
        media = {
            "kind": "audio",
            "url": _safe_str(a.get("link") or a.get("url") or a.get("downloadUrl") or a.get("download_url"), 500),
            "mimeType": _safe_str(a.get("mimeType") or a.get("mime_type") or ""),
            "sha256": _safe_str(a.get("sha256") or ""),
            "id": _safe_str(a.get("id") or ""),
        }

    return {
        "eventType": ev_type,
        "from": from_msisdn,
        "to": to_msisdn,
        "wamid": wamid,
        "messageType": msg_type,
        "text": text,
        "media": media,
    }



# =========================
# Phone helpers (BR): tolera dígito 9 (mobile) e variações comuns
# =========================
def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _phone_variants(e164: str) -> list[str]:
    """Gera variações do telefone para lookup (com/sem '9' após DDD no Brasil)."""
    s = (e164 or "").strip()
    if not s:
        return []
    # mantém + no começo se existir
    plus = "+" if s.startswith("+") else ""
    digits = _digits_only(s)
    if not digits:
        return [s]
    # normaliza para +<digits>
    base = plus + digits
    out = []
    def add(x):
        if x and x not in out:
            out.append(x)
    add(base)

    # heurística BR: +55 DDD (2) + número (8/9)
    if digits.startswith("55") and len(digits) in (12, 13):
        # depois do '55' vem DDD (2)
        ddd = digits[2:4]
        num = digits[4:]
        # se veio com 8 dígitos (sem 9) → tenta inserir 9
        if len(num) == 8:
            add("+" + "55" + ddd + "9" + num)
        # se veio com 9 dígitos e começa com 9 → tenta remover 9
        if len(num) == 9 and num.startswith("9"):
            add("+" + "55" + ddd + num[1:])

    return out

def _resolve_uid_for_sender(from_e164: str) -> str:
    """Resolve uid tentando variações de telefone. Retorna '' se não achar."""
    try:
        from services.voice_wa_link import get_uid_for_sender, upsert_sender_link  # type: ignore
    except Exception:
        return ""
    for cand in _phone_variants(from_e164):
        try:
            uid = get_uid_for_sender(cand)
            if uid:
                return uid
        except Exception:
            continue
    return ""


@ycloud_webhook_bp.route("/integracoes/ycloud/webhook", methods=["POST"])
@ycloud_webhook_bp.route("/integracoes/ycloud/webhook/", methods=["POST"])

def ycloud_webhook_ingress():
    # PATCH 0: aceitar GET para evitar 405 no painel do provider (healthcheck/ping)
    if request.method == "GET":
        return jsonify({"ok": True, "method": "GET"}), 200

    raw = request.get_data(cache=True) or b""  # <-- cache=True (importante)

    if not _verify_signature_if_enabled(raw):
        return jsonify({"ok": True, "ignored": True}), 200

    payload = None
    try:
        payload = request.get_json(silent=True)
    except Exception:
        payload = None

    # =========================
    # NOVO: webhook MAGRO (Cloud Tasks)
    # =========================

    # alguns providers embrulham em {"data": {...}}
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]

    env = _normalize_event(payload or {})

    # chave idempotente (preferir wamid)
    from_raw = (env.get("from") or "").strip()
    wamid = (env.get("wamid") or "").strip()
    ev_type = (env.get("eventType") or "").strip()
    msg_type = (env.get("messageType") or "").strip()

    # fallback: se não tem wamid, usa hash do raw
    if not wamid:
        wamid = hashlib.sha1(raw).hexdigest()[:24]

    event_key = f"ycloud:{ev_type}:{msg_type}:{from_raw}:{wamid}"

    # enfileira e sai (best-effort, nunca quebra o webhook)
    try:
        from services.cloud_tasks import enqueue_ycloud_inbound  # lazy import
        enqueue_ycloud_inbound(env, event_key=event_key)

        # DEBUG inbound (best-effort): provar o que chegou normalizado
        try:
            logger.info(
                "[ycloud_webhook] enqueued: type=%s msgType=%s from=%s wamid=%s textLen=%s",
                _safe_str(env.get("eventType")),
                _safe_str(env.get("messageType")),
                _safe_str(env.get("from")),
                _safe_str(env.get("wamid")),
                len(_safe_str(env.get("text"), 2000) or ""),
            )
        except Exception:
            pass

        # Observabilidade mínima (best-effort): inbound audit log
        try:
            _db().collection("platform_wa_logs").add(
                {
                    "createdAt": _now_ts(),
                    "kind": "inbound",
                    "eventType": env.get("eventType"),
                    "messageType": env.get("messageType"),
                    "from": env.get("from"),
                    "to": env.get("to"),
                    "wamid": env.get("wamid"),
                    "textPreview": (env.get("text") or "")[:120],
                }
            )
        except Exception:
            pass

        return jsonify({"ok": True, "enqueued": True}), 200

    # IMPORTANTE:
    # O webhook é MAGRO. Ele só normaliza + enfileira e retorna 200 rápido.
    # Qualquer processamento pesado (roteamento, IA, envio de texto/áudio, etc.)
    # acontece no worker: routes/ycloud_tasks_bp.py

