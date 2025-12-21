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
from services import wa_bot  # porta de entrada do bot (fachada estável)
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
    # Single source of truth
    return _db().collection('profissionais').document(uid).collection('voz').document('whatsapp')


def _outbox_log(doc: Dict[str, Any]) -> None:
    try:
        db = _db()
        db.collection("platform_wa_outbox_logs").add({
            **doc,
            "createdAt": _now_ts(),
        })
    except Exception:
        # nunca travar webhook por log
        pass

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
    from_msisdn = _safe_str(msg.get("from"))
    to_msisdn = _safe_str(msg.get("to"))
    wamid = _safe_str(msg.get("wamid") or msg.get("context", {}).get("wamid") or msg.get("context", {}).get("id"))

    text = ""
    media: Dict[str, Any] = {}

    if msg_type == "text":
        text = _safe_str((msg.get("text") or {}).get("body") or msg.get("text") or "", 2000)
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

@ycloud_webhook_bp.route("/integracoes/ycloud/webhook", methods=["POST"])
def ycloud_webhook_ingress():
    raw = request.get_data(cache=False) or b""

    if not _verify_signature_if_enabled(raw):
        return jsonify({"ok": True, "ignored": True}), 200

    payload = request.get_json(silent=True) or {}
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]

    env = _normalize_event(payload)

    # ===================== INGESTÃO DE VOZ =====================
    try:
        if env.get("eventType") == "whatsapp.inbound_message.received" and env.get("messageType") in ("audio", "voice", "ptt"):
            from_e164 = (env.get("from") or "").strip()
            media = env.get("media") or {}
            uid = get_uid_for_sender(from_e164) if from_e164 else ""

            if not uid:
                logger.info("[ycloud_webhook] voice: sem uid (ignore). from=%s", from_e164)
                return jsonify({"ok": True, "ignored": True}), 200

            if not (media.get("url") or "").strip():
                logger.info("[ycloud_webhook] voice: sem media_url. uid=%s from=%s", uid, from_e164)
                _voice_status_ref(uid).set({
                    "status": "failed",
                    "lastError": "missing_media_url",
                    "updatedAt": _now_ts(),
                    "source": "whatsapp",
                    "waFromE164": from_e164,
                }, merge=True)
                return jsonify({"ok": True}), 200

            voice_bytes, mime = download_media_bytes(provider="ycloud", media=media)

            ext = "ogg"
            m2 = (mime or media.get("mimeType") or "").lower()
            if "mpeg" in m2 or "mp3" in m2:
                ext = "mp3"
            elif "wav" in m2:
                ext = "wav"
            elif "ogg" in m2 or "opus" in m2:
                ext = "ogg"

            storage_path = f"profissionais/{uid}/voz/original/whatsapp_{int(time.time())}.{ext}"
            upload_voice_bytes(
                storage_path=storage_path,
                content_type=(mime or media.get("mimeType") or "application/octet-stream"),
                data=voice_bytes
            )

            _voice_status_ref(uid).set({
                "status": "received",
                "updatedAt": _now_ts(),
                "source": "whatsapp",
                "waFromE164": from_e164,
                "lastAudioGcsPath": storage_path,
                "lastAudioMime": (mime or media.get("mimeType") or ""),
                "lastInboundAt": _now_ts(),
                "lastError": "",
            }, merge=True)

            logger.info("[ycloud_webhook] voice: salvo uid=%s path=%s", uid, storage_path)

            # ===================== ACK (FLAGADO) =====================
            if os.environ.get("VOICE_WA_ACK", "0") == "1":
                msg_key = (env.get("wamid") or "").strip()
                if _dedupe_once(msg_key):
                    try:
                        ycloud_send_text(from_e164, "Áudio recebido 👍 Agora estamos preparando sua voz.")
                    except Exception:
                        pass

            return jsonify({"ok": True}), 200

    except Exception:
        logger.exception("[ycloud_webhook] voice: falha ingest")
        return jsonify({"ok": True}), 200


    # ===================== MENSAGEM DE TEXTO (BOT) =====================
    try:
        if env.get("eventType") == "whatsapp.inbound_message.received" and env.get("messageType") == "text":
            if os.environ.get("YCLOUD_TEXT_REPLY", "1") == "1":
                from_e164 = (env.get("from") or "").strip()
                text_in = (env.get("text") or "").strip()
                msg_key = (env.get("wamid") or "").strip() or f"text:{from_e164}:{hash(text_in)}"
                if from_e164 and text_in and _dedupe_once(msg_key):
                    uid = get_uid_for_sender(from_e164) if from_e164 else ""
                    if not uid:
                        logger.info("[ycloud_webhook] text: sem uid (ignore). from=%s", from_e164)
                        return jsonify({"ok": True, "ignored": True}), 200

                    # chama o bot (fachada) — sem estourar webhook
                    ctx = {
                        "channel": "whatsapp",
                        "provider": "ycloud",
                        "from_e164": from_e164,
                        "to_e164": (env.get("to") or "").strip(),
                        "wamid": (env.get("wamid") or "").strip(),
                    }
                    bot_res = wa_bot.reply_to_text(uid, text_in, ctx=ctx)

                    # normaliza saída para texto (mantemos simples e seguro aqui)
                    reply_text = ""
                    if isinstance(bot_res, dict):
                        reply_text = (bot_res.get("text") or bot_res.get("message") or bot_res.get("reply") or "").strip()
                        if not reply_text and bot_res.get("ok") is False:
                            reply_text = "Tive um probleminha aqui. Pode tentar de novo em alguns segundos?"
                    else:
                        reply_text = str(bot_res or "").strip()

                    if reply_text:
                        try:
                            ycloud_send_text(from_e164, reply_text)
                            _outbox_log({
                                "ok": True,
                                "uid": uid,
                                "to": from_e164,
                                "kind": "text",
                                "wamid": (env.get("wamid") or "").strip(),
                                "preview": reply_text[:180],
                            })
                        except Exception as e:
                            logger.exception("[ycloud_webhook] text: falha ao enviar. uid=%s to=%s", uid, from_e164)
                            _outbox_log({
                                "ok": False,
                                "uid": uid,
                                "to": from_e164,
                                "kind": "text",
                                "wamid": (env.get("wamid") or "").strip(),
                                "error": str(e)[:220],
                            })
                return jsonify({"ok": True}), 200
    except Exception:
        logger.exception("[ycloud_webhook] text: falha")
        return jsonify({"ok": True}), 200

    return jsonify({"ok": True}), 200


