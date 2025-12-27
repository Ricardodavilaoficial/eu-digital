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
from providers.ycloud import send_text as ycloud_send_text, send_audio as ycloud_send_audiofrom services.voice_wa_link import get_uid_for_sender, upsert_sender_link
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


@ycloud_webhook_bp.route("/integracoes/ycloud/webhook", methods=["POST", "GET"])
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

    if not isinstance(payload, dict) or not payload:
        # fallback: parse manual do raw
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}

    # alguns providers embrulham em {"data": {...}}
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]

    env = _normalize_event(payload)

    # DEBUG inbound (best-effort): provar o que chegou normalizado
    try:
        logger.info(
            "[ycloud_webhook] inbound normalized: type=%s msgType=%s from=%s wamid=%s textLen=%s",
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

    # ===================== INGESTÃO DE VOZ =====================
    # (pipeline de voz já funcional — NÃO alterar comportamento)
    try:
        if env.get("eventType") == "whatsapp.inbound_message.received" and env.get("messageType") in ("audio", "voice", "ptt"):
            from_e164 = (env.get("from") or "").strip()
            media = env.get("media") or {}
            uid = _resolve_uid_for_sender(from_e164) if from_e164 else ""
            ttl_seconds = int(os.environ.get("VOICE_LINK_TTL_SECONDS", "86400") or "86400")

            # Opção B: áudio de número desconhecido vira VENDAS (wa_bot decide).
            if not uid:
                logger.info("[ycloud_webhook] voice: uid não resolvido p/ from=%s (route=sales)", _safe_str(from_e164))

                # Encaminhar como lead/vendas (wa_bot decide). Não tocar em Firestore de voz.
                reply_text = "Oi! Sou o MEI Robô. Quer conhecer os planos?"
                wa_out = None
                try:
                    from services import wa_bot as wa_bot_entry  # lazy import
                    if hasattr(wa_bot_entry, "reply_to_text"):
                        wa_out = wa_bot_entry.reply_to_text(
                            uid="",
                            text="[áudio recebido]",
                            ctx={"channel": "whatsapp", "from_e164": from_e164, "msg_type": "audio", "wamid": env.get("wamid")},
                        )
                except Exception:
                    logger.exception("[ycloud_webhook] voice: falha ao chamar wa_bot (lead audio)")

                # normaliza replyText
                try:
                    if isinstance(wa_out, dict):
                        reply_text = (
                            wa_out.get("replyText")
                            or wa_out.get("text")
                            or wa_out.get("reply")
                            or wa_out.get("message")
                            or reply_text
                        )
                    elif wa_out:
                        reply_text = str(wa_out)
                except Exception:
                    pass

                reply_text = (reply_text or "").strip()[:1200] or "Oi! Sou o MEI Robô. Quer conhecer os planos?"

                # se tiver audioUrl, tenta enviar áudio; se falhar, cai no texto
                audio_url = ""
                try:
                    if isinstance(wa_out, dict):
                        audio_url = (wa_out.get("audioUrl") or wa_out.get("audio_url") or "").strip()
                except Exception:
                    audio_url = ""

                allow_audio = os.environ.get("YCLOUD_TEXT_REPLY_AUDIO", "1") not in ("0", "false", "False")
                sent_ok = False

                if allow_audio and audio_url:
                    try:
                        sent_ok, _ = ycloud_send_audio(from_e164, audio_url)
                    except Exception:
                        logger.exception("[ycloud_webhook] voice: falha ao enviar áudio via ycloud (lead)")

                if not sent_ok:
                    try:
                        ycloud_send_text(from_e164, reply_text)
                    except Exception:
                        pass

                return jsonify({"ok": True}), 200

            if not (media.get("url") or "").strip():
                logger.info("[ycloud_webhook] voice: sem media_url. uid=%s from=%s", uid, from_e164)
                _voice_status_ref(uid).set(
                    {
                        "status": "failed",
                        "lastError": "missing_media_url",
                        "updatedAt": _now_ts(),
                        "source": "whatsapp",
                        "waFromE164": from_e164,
                    },
                    merge=True,
                )
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
                data=voice_bytes,
            )

            _voice_status_ref(uid).set(
                {
                    "status": "received",
                    "updatedAt": _now_ts(),
                    "source": "whatsapp",
                    "waFromE164": from_e164,
                    "lastAudioGcsPath": storage_path,
                    "lastAudioMime": (mime or media.get("mimeType") or ""),
                    "lastInboundAt": _now_ts(),
                    "lastError": "",
                },
                merge=True,
            )

            logger.info("[ycloud_webhook] voice: salvo uid=%s path=%s", uid, storage_path)

            # Renova vínculo from→uid por um TTL curto (safe)
            try:
                upsert_sender_link(from_e164, uid, ttl_seconds=ttl_seconds, method="audio_auto")
            except Exception:
                pass

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

    # ===================== TEXTO (BOT) =====================
    # Default ON; rollback instantâneo com YCLOUD_TEXT_REPLY=0
    try:
        if os.environ.get("YCLOUD_TEXT_REPLY", "1") not in ("0", "false", "False"):
            if env.get("eventType") == "whatsapp.inbound_message.received" and env.get("messageType") == "text":
                from_e164 = (env.get("from") or "").strip()
                text_in = (env.get("text") or "").strip()

                if not from_e164 or not text_in:
                    return jsonify({"ok": True}), 200

                msg_key = (env.get("wamid") or "").strip()
                if msg_key and not _dedupe_once("text:" + msg_key):
                    return jsonify({"ok": True, "deduped": True}), 200

                # resolve uid do remetente (mesma regra do fluxo de voz)
                uid = _resolve_uid_for_sender(from_e164) or ""
                ttl_seconds = int(os.environ.get("VOICE_LINK_TTL_SECONDS", "86400") or "86400")

                # Opção B: uid ausente vira VENDAS (wa_bot decide). Não ignorar.
                if not uid:
                    logger.info("[ycloud_webhook] text: uid não resolvido p/ from=%s (route=sales)", _safe_str(from_e164))
                    # NÃO renova link quando uid é vazio (evita sujeira/risco bobo)
                else:
                    try:
                        upsert_sender_link(from_e164, uid, ttl_seconds=ttl_seconds, method="text_renew")
                    except Exception:
                        pass


                # chama wa_bot para obter a resposta (source of truth)
                reply_text = "Certo."
                wa_out = None
                try:
                    from services import wa_bot as wa_bot_entry  # lazy import
                    if hasattr(wa_bot_entry, "reply_to_text"):
                        wa_out = wa_bot_entry.reply_to_text(
                            uid=uid,
                            text=text_in,
                            ctx={
                                "channel": "whatsapp",
                                "from_e164": from_e164,
                                "wamid": env.get("wamid"),
                            },
                        )
                except Exception:
                    logger.exception("[ycloud_webhook] text: falha ao chamar wa_bot uid=%s", uid)

                # normaliza retorno do wa_bot
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

                # envia áudio somente se o bot devolveu URL; senão texto
                sent_mode = "text"
                send_ok = False
                send_resp: Dict[str, Any] = {}

                def _pick_audio_url(x: Any) -> str:
                    try:
                        if not isinstance(x, dict):
                            return ""
                        u = (x.get("audioUrl") or x.get("audio_url") or "").strip()
                        if u:
                            return u
                        a = x.get("audio") or {}
                        if isinstance(a, dict):
                            return (a.get("url") or a.get("link") or "").strip()
                        return ""
                    except Exception:
                        return ""

                audio_url = _pick_audio_url(wa_out)
                allow_audio = os.environ.get("YCLOUD_TEXT_REPLY_AUDIO", "1") not in ("0", "false", "False")

                if allow_audio and audio_url:
                    try:
                        try:
                            from providers.ycloud import send_audio as _ycloud_send_audio  # import local
                        except Exception:
                            _ycloud_send_audio = None  # type: ignore

                        if _ycloud_send_audio is not None:
                            send_ok, send_resp = _ycloud_send_audio(from_e164, audio_url)
                            if send_ok:
                                sent_mode = "audio"
                        else:
                            send_ok, send_resp = False, {"error": "send_audio_unavailable"}
                    except Exception:
                        logger.exception("[ycloud_webhook] text: falha ao enviar áudio via ycloud uid=%s", uid)
                        send_ok, send_resp = False, {"error": "send_audio_exception"}

                if not send_ok:
                    try:
                        send_ok, send_resp = ycloud_send_text(from_e164, reply_text)
                        sent_mode = "text"
                    except Exception:
                        logger.exception("[ycloud_webhook] text: falha ao enviar resposta via ycloud (texto) uid=%s", uid)
                        send_ok, send_resp = False, {"error": "send_text_exception"}

                # Log outbound somente quando tentar enviar resposta
                try:
                    _db().collection("platform_wa_outbox_logs").add(
                        {
                            "createdAt": _now_ts(),
                            "eventType": env.get("eventType"),
                            "messageType": "text",
                            "fromE164": from_e164,
                            "uid": uid,
                            "wamid": env.get("wamid"),
                            "inTextPreview": text_in[:180],
                            "outTextPreview": str(reply_text)[:180],
                            "sentMode": sent_mode,
                            "sendOk": bool(send_ok),
                            "audioUrl": (audio_url or "")[:500],
                        }
                    )
                except Exception:
                    pass

                return jsonify({"ok": True}), 200
    except Exception:
        logger.exception("[ycloud_webhook] text: falha inesperada (ignore)")

    return jsonify({"ok": True}), 200

