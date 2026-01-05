# routes/ycloud_tasks_bp.py
from __future__ import annotations

import os
import time
import hashlib
import logging
from typing import Any, Dict

from flask import Blueprint, request, jsonify

from services.phone_utils import digits_only as _digits_only_c, to_plus_e164 as _to_plus_e164_c
from google.cloud import firestore  # type: ignore

logger = logging.getLogger("mei_robo.ycloud_tasks")

ycloud_tasks_bp = Blueprint("ycloud_tasks_bp", __name__)


def _db():
    return firestore.Client()


def _sha1_id(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


def _digits_only(s: str) -> str:
    return _digits_only_c(s)


def _to_plus_e164(raw: str) -> str:
    return _to_plus_e164_c(raw)


def _idempotency_once(event_key: str, ttl_seconds: int = 86400) -> bool:
    """
    Retorna True se é primeira vez. False se já processou.
    (Idempotência hard em Firestore)
    """
    doc_id = _sha1_id(event_key)
    ref = _db().collection("platform_tasks_dedup").document(doc_id)
    snap = ref.get()
    if snap.exists:
        return False
    now = time.time()
    ref.set({
        "eventKey": event_key,
        "createdAt": now,
        "expiresAt": now + max(3600, int(ttl_seconds or 86400)),
    }, merge=False)
    return True


@ycloud_tasks_bp.route("/tasks/ycloud-inbound", methods=["POST"])
def ycloud_inbound_worker():
    # Auth simples via secret (modo Render)
    secret = (os.environ.get("CLOUD_TASKS_SECRET") or "").strip()
    got = (request.headers.get("X-MR-Tasks-Secret") or "").strip()
    if not secret or got != secret:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    event_key = (data.get("eventKey") or "").strip()
    payload = data.get("payload") or {}

    if not event_key or not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad_request"}), 400
    # ==========================================================
    # FILTRO DE EVENTO (anti-eco / anti-loop)
    # Worker só processa inbound real do usuário.
    # ==========================================================
    ev_type = (payload.get("eventType") or "").strip()
    if ev_type != "whatsapp.inbound_message.received":
        return jsonify({"ok": True, "ignored": True, "eventType": ev_type}), 200


    dedup_ttl = int(os.environ.get("CLOUD_TASKS_DEDUP_TTL_SECONDS", "86400") or "86400")
    if not _idempotency_once(event_key, ttl_seconds=dedup_ttl):
        return jsonify({"ok": True, "deduped": True}), 200

    try:
        # --- normalização mínima do evento ---
        msg_type = (payload.get("messageType") or "").strip().lower()
        from_raw = (payload.get("from") or "").strip()
        to_raw = (payload.get("to") or "").strip()
        wamid = (payload.get("wamid") or "").strip()
        text_in = (payload.get("text") or "").strip()
        media = payload.get("media") or {}

        from_e164 = _to_plus_e164(from_raw)
        to_e164 = _to_plus_e164(to_raw)

        # --- resolve UID quando aplicável (voz do cliente) ---
        uid = ""
        try:
            from services.voice_wa_link import get_uid_for_sender  # type: ignore
            uid = (get_uid_for_sender(from_e164) or "").strip()
        except Exception:
            uid = ""

        # --- 1) ÁUDIO: se tem UID -> trata como fluxo de VOZ (ingest) ---
        if uid and msg_type in ("audio", "voice", "ptt"):
            try:
                from services.voice_wa_download import download_media_bytes  # type: ignore
                from services.voice_wa_storage import upload_voice_bytes  # type: ignore
                from services.voice_wa_link import upsert_sender_link  # type: ignore
                from services.firebase_admin_init import ensure_firebase_admin  # type: ignore

                ensure_firebase_admin()

                url = ""
                try:
                    url = (media.get("url") or "").strip()
                except Exception:
                    url = ""

                if not url:
                    logger.warning("[tasks] voice: sem media.url uid=%s wamid=%s", uid, wamid)
                    return jsonify({"ok": True, "voice": "no_url"}), 200

                b, info = download_media_bytes(url=url)
                storage_path = upload_voice_bytes(uid=uid, audio_bytes=b, ext_hint=(info.get("ext") or "ogg"))

                # status em doc do profissional (compat com o que já existe no webhook)
                try:
                    _db().collection("profissionais").document(uid).set(
                        {
                            "vozClonada": {
                                "status": "uploaded",
                                "object_key": storage_path,
                                "updatedAt": time.time(),
                                "lastError": "",
                            }
                        },
                        merge=True,
                    )
                except Exception:
                    pass

                # renova vínculo (from -> uid), tolerante ao 9 via store já existente
                try:
                    ttl_seconds = int(os.environ.get("VOICE_LINK_TTL_SECONDS", "86400") or "86400")
                    upsert_sender_link(from_e164, uid, ttl_seconds=ttl_seconds, method="audio_auto")
                except Exception:
                    pass

                # ACK opcional (mesmo comportamento do webhook antigo)
                if os.environ.get("VOICE_WA_ACK", "0") == "1":
                    try:
                        from providers.ycloud import ycloud_send_text  # type: ignore
                        ycloud_send_text(
                            from_e164,
                            "✅ Áudio recebido com sucesso.\nAgora volte para a tela de configuração e clique em Continuar."
                        )
                    except Exception:
                        pass

                return jsonify({"ok": True, "voice": "stored"}), 200

            except Exception:
                logger.exception("[tasks] voice: falha ingest uid=%s", uid)
                return jsonify({"ok": True, "voice": "failed"}), 200

        # --- 2) LEAD / TEXTO: chama WA_BOT (vendas se uid vazio) ---
        reply_text = ""
        audio_url = ""
        audio_debug = {}

        try:
            from services import wa_bot as wa_bot_entry  # lazy import
            route_hint = "sales" if not uid else "customer"

            if msg_type in ("audio", "voice", "ptt") and not text_in:
                # Áudio de lead: mantém o cérebro único sem exigir STT agora
                text_in = "Lead enviou um áudio."

            wa_out = None
            if hasattr(wa_bot_entry, "reply_to_text"):
                wa_out = wa_bot_entry.reply_to_text(
                    uid=uid,
                    text=text_in,
                    ctx={
                        "channel": "whatsapp",
                        "from_e164": from_e164,
                        "to_e164": to_e164,
                        "msg_type": msg_type,
                        "wamid": wamid,
                        "route_hint": route_hint,
                        "event_key": event_key,
                    },
                )

            reply_text = ""
        except Exception as e:
            # Best-effort: não derruba o worker se o wa_bot falhar/import quebrar
            reply_text = ""
            audio_url = ""
            audio_debug = {"err": str(e)}

if isinstance(wa_out, dict):
    reply_text = (
        wa_out.get("replyText")
        or wa_out.get("text")
        or wa_out.get("reply")
        or wa_out.get("message")
        or ""
    )
    audio_url = (wa_out.get("audioUrl") or wa_out.get("audio_url") or "").strip()
    audio_debug = wa_out.get("audioDebug") or {}
elif wa_out:
    reply_text = str(wa_out)

# Não sobrescrever resposta do wa_bot com "texto pronto".
# Fallback mínimo só quando for lead/VENDAS (uid ausente).
reply_text = (reply_text or "").strip()[:1200]
if not reply_text:
    if not uid:
        logger.warning(
            '[tasks] route=tasks_empty_reply reason=empty_reply from=%s to=%s wamid=%s eventKey=%s',
            from_e164, to_e164, wamid, event_key
        )
        reply_text = "Entendi 🙂 Me diz rapidinho o que você quer agora: pedidos, agenda, orçamento ou conhecer?"
    else:
        # Preserva o comportamento atual para usuário autenticado
        reply_text = "Entendi 🙂 Me diz teu nome rapidinho e teu ramo?"

# envia resposta: se lead mandou áudio, tentamos áudio (se veio audioUrl), senão texto
sent_ok = False
allow_audio = os.environ.get("YCLOUD_TEXT_REPLY_AUDIO", "1") not in ("0", "false", "False")

try:
    from providers.ycloud import send_text, send_audio  # type: ignore
except Exception:
    send_text = None  # type: ignore
    send_audio = None  # type: ignore

if allow_audio and msg_type in ("audio", "voice", "ptt") and audio_url and send_audio:
    try:
        sent_ok, _ = send_audio(from_e164, audio_url)
    except Exception:
        logger.exception("[tasks] lead: falha send_audio")

if (not sent_ok) and send_text:
    try:
        sent_ok, _ = send_text(from_e164, reply_text)
    except Exception:
        logger.exception("[tasks] lead: falha send_text")

# log leve (auditoria). Precisa ocorrer antes do return.
try:
    _db().collection("platform_wa_outbox_logs").add({
        "createdAt": time.time(),
        "from": from_e164,
        "to": to_e164,
        "wamid": wamid,
        "msgType": msg_type,
        "route": "sales" if not uid else "customer",
        "replyText": reply_text[:400],
        "audioUrl": audio_url[:300],
        "audioDebug": audio_debug,
        "eventKey": event_key,
        "sentOk": bool(sent_ok),
    })
except Exception:
    pass

return jsonify({"ok": True, "sent": bool(sent_ok)}), 200


        except Exception:
            logger.exception("[tasks] wa_bot/send: falha")
            return jsonify({"ok": True, "sent": False}), 200

    except Exception:
        logger.exception("[tasks] fatal: erro inesperado")
        return jsonify({"ok": True}), 200




