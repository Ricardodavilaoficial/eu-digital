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


# =============================================================================
# INCREMENTO: Webhook Voice-WA (auto-reply simples)
# Rota: POST /webhooks/voice-wa
# =============================================================================

def _mode_on() -> bool:
    # liga/desliga via VOICE_WA_MODE=on|1|true
    v = (os.environ.get("VOICE_WA_MODE") or "").strip().lower()
    return v in ("1", "true", "on", "enabled", "yes")

def normalize_e164_br(x: str) -> str:
    s = (x or "").strip()
    if not s:
        return ""
    # mantém + e dígitos
    if s.startswith("+"):
        digits = "+" + "".join([c for c in s[1:] if c.isdigit()])
    else:
        digits = "".join([c for c in s if c.isdigit()])
        if digits.startswith("55"):
            digits = "+" + digits
        else:
            # assume BR quando vier “solto”
            digits = "+55" + digits
    # mínimo: +55DD... (sem validação pesada aqui)
    return digits

def sender_allowed(from_e164: str) -> bool:
    # allowlist opcional: VOICE_WA_ALLOWLIST_E164="+5551999999999,+5551888888888"
    allow = (os.environ.get("VOICE_WA_ALLOWLIST_E164") or "").strip()
    if not allow:
        return True
    allowed = {normalize_e164_br(p.strip()) for p in allow.split(",") if p.strip()}
    return normalize_e164_br(from_e164) in allowed

def _log(uid: Optional[str], payload: Dict[str, Any], note: str = ""):
    # log global, sem escrever em profissionais/*
    env = {
        "provider": payload.get("provider") or "voice-wa",
        "kind": "voice-wa",
        "eventType": "voice_wa_webhook",
        "from": payload.get("fromE164") or payload.get("from") or "",
        "to": payload.get("toE164") or payload.get("to") or "",
        "messageType": payload.get("kind") or payload.get("messageType") or "",
        "text": payload.get("text") or "",
        "media": payload.get("media") or {},
        "status": "",
        "errorCode": "",
        "errorMessage": _safe_str(note, 500),
        "wamid": payload.get("messageId") or payload.get("wamid") or "",
    }
    _log_global(env, raw_body=None)

def resolve_incoming_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Aceita dois formatos:
    1) Formato "simplificado" já no padrão do voice-wa:
       { provider, kind: text|audio, fromE164, messageId, ... }
    2) Payload YCloud bruto (whatsapp.inbound_message.received / etc):
       converte usando _normalize_event().
    """
    # já veio “pronto”
    if payload.get("fromE164") or payload.get("kind"):
        ev = dict(payload)
        ev["provider"] = (ev.get("provider") or "unknown").strip()
        ev["kind"] = (ev.get("kind") or "").strip()
        ev["fromE164"] = ev.get("fromE164") or ev.get("from") or ""
        ev["messageId"] = ev.get("messageId") or ev.get("wamid") or ""
        return ev

    # tenta interpretar como YCloud
    try:
        env = _normalize_event(payload)
        kind = "event"
        if env.get("kind") == "inbound":
            if env.get("messageType") == "text":
                kind = "text"
            elif env.get("messageType") in ("audio", "voice"):
                kind = "audio"
            else:
                kind = (env.get("messageType") or "event")
        ev = {
            "provider": "ycloud",
            "kind": kind,
            "fromE164": env.get("from") or "",
            "toE164": env.get("to") or "",
            "messageId": env.get("wamid") or env.get("messageId") or "",
            "text": env.get("text") or "",
            "media": env.get("media") or {},
        }
        return ev
    except Exception:
        return {
            "provider": "unknown",
            "kind": "event",
            "fromE164": "",
            "toE164": "",
            "messageId": "",
        }

def send_text(to_e164: str, text: str) -> bool:
    """
    Envia mensagem via YCloud (se ENVs existirem). Se não existirem, só loga e retorna False.
    ENVs esperadas (best effort):
      - YCLOUD_API_BASE (ex.: https://api.ycloud.com/v2)
      - YCLOUD_API_TOKEN (Bearer)
      - YCLOUD_WABA_FROM (opcional: número/remetente default)
    """
    base = (os.environ.get("YCLOUD_API_BASE") or "").strip().rstrip("/")
    token = (os.environ.get("YCLOUD_API_TOKEN") or "").strip()
    from_id = (os.environ.get("YCLOUD_WABA_FROM") or "").strip()

    to_e164 = normalize_e164_br(to_e164)
    text = (text or "").strip()
    if not to_e164 or not text:
        return False

    if not base or not token:
        _log(None, {"provider":"voice-wa", "kind":"send_text_skipped", "fromE164":"", "toE164":to_e164, "text":text},
             note="send_text skipped: missing YCLOUD_API_BASE or YCLOUD_API_TOKEN")
        return False

    try:
        import requests  # type: ignore
        url = f"{base}/whatsapp/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body: Dict[str, Any] = {
            "to": to_e164,
            "type": "text",
            "text": {"body": text},
        }
        if from_id:
            body["from"] = from_id

        r = requests.post(url, headers=headers, json=body, timeout=10)
        ok = (200 <= r.status_code < 300)
        _log(None, {
            "provider":"voice-wa",
            "kind":"send_text",
            "fromE164": from_id,
            "toE164": to_e164,
            "messageId": "",
            "text": text
        }, note=f"ycloud send_text status={r.status_code} ok={ok}")
        return ok
    except Exception as e:
        _log(None, {
            "provider":"voice-wa",
            "kind":"send_text_error",
            "fromE164": from_id,
            "toE164": to_e164,
            "messageId": "",
            "text": text
        }, note=f"send_text exception: {_safe_str(e, 240)}")
        return False

@ycloud_webhook_bp.route("/webhooks/voice-wa", methods=["POST"])
def voice_wa_webhook():
    if not _mode_on():
        return jsonify({"ok": True, "ignored": True}), 200

    secret_env = (os.environ.get("VOICE_WA_WEBHOOK_SECRET") or "").strip()
    if secret_env:
        got = (request.headers.get("X-Voice-WA-Secret") or request.args.get("secret") or "").strip()
        if not got or got != secret_env:
            return jsonify({"ok": True, "ignored": True}), 200

    payload = request.get_json(silent=True) or {}
    event = resolve_incoming_event(payload)
    _log(None, payload, note=f"ingress kind={event.get('kind')} provider={event.get('provider')}")

    from_e164 = normalize_e164_br((event.get("fromE164") or "").strip())
    provider = (event.get("provider") or "unknown").strip()
    message_id = (event.get("messageId") or "").strip()
    kind = (event.get("kind") or "").strip()

    if not sender_allowed(from_e164):
        _log(None, payload, note=f"blocked sender={from_e164}")
        return jsonify({"ok": True, "ignored": True}), 200

    # Verifica tipo de mensagem e responde
    if kind == "text":
        response_text = "Olá, qual serviço você precisa? 1 - Voz / 2 - Suporte / 3 - Vendas"
        send_text(from_e164, response_text)
    elif kind == "audio":
        response_text = "Áudio recebido, processando..."
        send_text(from_e164, response_text)

    return jsonify({"ok": True}), 200
