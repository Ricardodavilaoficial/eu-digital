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
    from_msisdn = _safe_str(msg.get("from"))
    to_msisdn = _safe_str(msg.get("to"))
    wamid = _safe_str(msg.get("wamid") or msg.get("context", {}).get("wamid") or msg.get("context", {}).get("id"))

    text = ""
    media: Dict[str, Any] = {}

    if msg_type == "text":
        # YCloud pode variar o formato: {"text":{"body":"..."}} | {"text":"..."} | {"text":{"content":"..."}} etc.
        t = msg.get("text")
        candidate = ""
        try:
            if isinstance(t, dict):
                candidate = t.get("body") or t.get("content") or t.get("text") or ""
            elif isinstance(t, str):
                candidate = t
        except Exception:
            candidate = ""

        # alguns payloads trazem o texto em campos alternativos
        if not candidate:
            for k in ("body", "content", "message", "textBody", "text_body"):
                v = msg.get(k)
                if isinstance(v, str) and v.strip():
                    candidate = v
                    break
                if isinstance(v, dict):
                    vv = v.get("body") or v.get("content") or v.get("text")
                    if isinstance(vv, str) and vv.strip():
                        candidate = vv
                        break

        text = _safe_str(candidate or "", 2000)
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
        from services.voice_wa_link import get_uid_for_sender  # type: ignore
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
            uid = _resolve_uid_for_sender(from_e164) if from_e164 else ""

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
                        ok_send, _resp_send = ycloud_send_text(from_e164, "Áudio recebido 👍 Agora estamos preparando sua voz.")
                    except Exception:
                        pass

            return jsonify({"ok": True}), 200

    except Exception:
        logger.exception("[ycloud_webhook] voice: falha ingest")
        return jsonify({"ok": True}), 200

    # ===================== TEXTO (BOT) =====================
    # Safe mode: responder texto/áudio sem mexer no fluxo de voz.
    # Default ON; rollback instantâneo com YCLOUD_TEXT_REPLY=0
    #
    # Política (v1):
    # - Se houver voz "ready" (voiceId) para o uid → responder em ÁUDIO (voz do MEI).
    # - Caso contrário → responder em TEXTO.
    # - O webhook não inventa intent/fallback: só chama o wa_bot e entrega a resposta.
    try:
        if os.environ.get("YCLOUD_TEXT_REPLY", "1") not in ("0", "false", "False"):
            if env.get("eventType") == "whatsapp.inbound_message.received" and env.get("messageType") == "text":
                from_e164 = (env.get("from") or "").strip()
                text_in = (env.get("text") or "").strip()

                if not from_e164 or not text_in:
                    return jsonify({"ok": True}), 200

                # resolve uid do remetente (mesma regra do fluxo de voz)
                uid = _resolve_uid_for_sender(from_e164) or None

                # fallback conservador (não responde se não conseguir resolver uid)
                if not uid:
                    logger.info("[ycloud_webhook] text: uid não resolvido p/ from=%s (ignore)", _safe_str(from_e164))
                    return jsonify({"ok": True}), 200

                # chama wa_bot para obter a resposta em texto (source of truth)
                reply_text = "Certo."
                wa_out = None
                try:
                    from services import wa_bot as wa_bot_entry  # lazy import
                    if hasattr(wa_bot_entry, "reply_to_text"):
                        wa_out = wa_bot_entry.reply_to_text(uid=uid, text=text_in, ctx={
                            "channel": "whatsapp",
                            "from_e164": from_e164,
                            "wamid": env.get("wamid"),
                        })
                except Exception:
                    logger.exception("[ycloud_webhook] text: falha ao chamar wa_bot uid=%s", uid)

                # normaliza retorno do wa_bot (ele retorna dict)
                try:
                    if isinstance(wa_out, dict):
                        reply_text = (
                            wa_out.get("replyText")
                            or wa_out.get("text")
                            or wa_out.get("reply")
                            or wa_out.get("message")
                            or wa_out.get("out")
                            or reply_text
                        )
                    elif wa_out:
                        reply_text = str(wa_out)
                except Exception:
                    reply_text = "Certo."

                reply_text = (reply_text or "").strip()[:1200] or "Certo."

                # tenta responder em áudio se a voz estiver pronta (vozClonada.status == ready e voiceId presente)
                sent_mode = "text"
                ok_send = None
                _resp_send = None
                try:
                    prof = _db().collection("profissionais").document(uid).get()
                    voz = (prof.to_dict() or {}).get("vozClonada") or {}
                    voice_status = (voz.get("status") or "").strip().lower()
                    voice_id = (voz.get("voiceId") or "").strip()

                    want_audio = (voice_status == "ready") and bool(voice_id) and os.environ.get("YCLOUD_TEXT_REPLY_AUDIO", "1") not in ("0", "false", "False")
                except Exception:
                    want_audio = False
                    voice_id = ""
                    voice_status = ""

                if want_audio:
                    try:
                        from services import text_to_speech  # type: ignore
                        from services import storage_gcs  # type: ignore
                        from providers.ycloud import send_audio as ycloud_send_audio  # type: ignore

                        tts_out = text_to_speech.speak_bytes(reply_text, voice=voice_id, format="audio/ogg")
                        if tts_out and isinstance(tts_out, tuple) and len(tts_out) == 2:
                            audio_bytes, mime_type = tts_out
                            ext = ".ogg" if str(mime_type).startswith("audio/ogg") else ".mp3"
                            filename = f"tts_reply_{int(time.time())}{ext}"

                            url, bucket_name, gcs_path, access_mode = storage_gcs.upload_bytes_and_get_url(
                                uid=uid,
                                filename=filename,
                                buf=audio_bytes,
                                mimetype=str(mime_type),
                            )

                            ok, resp = ycloud_send_audio(from_e164, url)
                            sent_mode = "audio" if ok else "text"

                            # se falhar enviar áudio, cai para texto (sem quebrar)
                            if not ok:
                                ok_send, _resp_send = ycloud_send_text(from_e164, reply_text)
                                sent_mode = "text"
                        else:
                            ok_send, _resp_send = ycloud_send_text(from_e164, reply_text)
                            sent_mode = "text"
                    except Exception:
                        logger.exception("[ycloud_webhook] text: falha ao responder em áudio; caindo para texto uid=%s", uid)
                        try:
                            ok_send, _resp_send = ycloud_send_text(from_e164, reply_text)
                            sent_mode = "text"
                        except Exception:
                            logger.exception("[ycloud_webhook] text: falha ao enviar texto (fallback) uid=%s", uid)
                else:
                    # Envia resposta via YCloud (texto)
                    try:
                        ok_send, _resp_send = ok_send, _resp_send = ycloud_send_text(from_e164, reply_text)
                        sent_mode = "text"
                    except Exception:
                        logger.exception("[ycloud_webhook] text: falha ao enviar resposta via ycloud (texto) uid=%s", uid)

                # Log mínimo de outbound pra debug (best-effort)
                try:
                    _db().collection("platform_wa_outbox_logs").add({
                        "createdAt": _now_ts(),
                        "eventType": env.get("eventType"),
                        "messageType": "text",
                        "fromE164": from_e164,
                        "uid": uid,
                        "wamid": env.get("wamid"),
                        "inTextPreview": text_in[:180],
                        "outTextPreview": str(reply_text)[:180],
                        "sentMode": sent_mode,
                        "sendOk": ok_send,
                        "sendResp": _resp_send if isinstance(_resp_send, dict) else None,
                    })
                except Exception:
                    pass

                return jsonify({"ok": True}), 200
    except Exception:
        logger.exception("[ycloud_webhook] text: falha inesperada (ignore)")
    return jsonify({"ok": True}), 200



