# routes/ycloud_tasks_bp.py
from __future__ import annotations

import os
import time
import hashlib
import logging
from typing import Any, Dict

import requests

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
        msg_type = (payload.get("messageType") or payload.get("msgType") or "").strip().lower()
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

        # --- 1) ÁUDIO: fluxo de VOZ (ingest) SOMENTE se onboarding estiver "waiting" ---
        voice_waiting = False
        try:
            prof = _db().collection("profissionais").document(uid).get()
            prof_data = prof.to_dict() or {}
            voz = prof_data.get("voz") or {}
            wa = voz.get("whatsapp") or {}
            # regra saudável: só é onboarding de voz se estiver explicitamente aguardando áudio
            voice_waiting = (str(wa.get("status") or "").strip().lower() == "waiting")
        except Exception:
            voice_waiting = False

        if uid and msg_type in ("audio", "voice", "ptt") and voice_waiting:
            try:
                from services.voice_wa_download import download_media_bytes  # type: ignore
                from services.voice_wa_storage import upload_voice_bytes  # type: ignore
                from services.voice_wa_link import upsert_sender_link  # type: ignore
                from services.firebase_admin_init import ensure_firebase_admin  # type: ignore

                ensure_firebase_admin()

                provider = (payload.get("provider") or "ycloud")

                # Baixa bytes + mime do provedor (ycloud)
                b, mime = download_media_bytes(provider, media)

                ext_hint = "ogg"
                try:
                    from services.voice_wa_download import sniff_extension  # type: ignore
                    ext_hint = sniff_extension(mime or "", fallback="ogg")
                except Exception:
                    pass

                # Caminho padrão já usado no projeto (não muda contrato)
                storage_path = f"profissionais/{uid}/voz/original/whatsapp_{int(time.time())}.{ext_hint}"

                # Assinatura correta: (storage_path, content_type, data)
                storage_path = upload_voice_bytes(storage_path, (mime or "audio/ogg"), b)
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


                # ✅ IMPORTANTÍSSIMO: encerra o modo "waiting" após receber 1 áudio válido.
                # Isso destrava SUPORTE imediatamente, sem precisar esperar TTL.
                try:
                    _db().collection("profissionais").document(uid).set(
                        {
                            "voz": {
                                "whatsapp": {
                                    "status": "received",
                                    "lastError": "",
                                    "lastAudioGcsPath": storage_path,
                                    "lastAudioMime": (mime or "audio/ogg"),
                                    "lastInboundAt": firestore.SERVER_TIMESTAMP,
                                    "updatedAt": firestore.SERVER_TIMESTAMP,
                                    "waFromE164": from_e164,
                                }
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
                        from providers.ycloud import send_text  # type: ignore
                        send_text(
                            to_e164=from_e164,
                            text="✅ Áudio recebido com sucesso.\nAgora volte para a tela de configuração e clique em Continuar."
                        )
                    except Exception:
                        logger.exception("[tasks] voice: falha ao enviar ACK via WhatsApp")

                try:
                    _db().collection("platform_wa_outbox_logs").add({
                        "createdAt": firestore.SERVER_TIMESTAMP,
                        "from": from_e164,
                        "to": to_e164,
                        "wamid": wamid,
                        "msgType": msg_type,
                        "route": "voice_ingest",
                        "replyText": "ACK: voz recebida (configuração)",
                        "audioUrl": "",
                        "audioDebug": {},
                        "eventKey": event_key,
                        "sentOk": True,
                    })
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
        wa_out = None

        try:
            from services.firebase_admin_init import ensure_firebase_admin  # type: ignore
            ensure_firebase_admin()

            from services import wa_bot as wa_bot_entry  # lazy import
            route_hint = "sales" if not uid else "customer"

            skip_wa_bot = False

            if msg_type in ("audio", "voice", "ptt") and not text_in:
                # Áudio de lead: baixar mídia e transcrever (STT) antes da IA
                transcript = ""
                stt_err = ""

                try:
                    url = ""
                    try:
                        url = (media.get("url") or "").strip()
                    except Exception:
                        url = ""

                    if not url:
                        stt_err = "no_media_url"
                    else:
                        # Preferir o downloader já usado no fluxo de voz (tende a lidar melhor com headers/auth)
                        audio_bytes = b""
                        ctype = ""

                        try:
                            from services.voice_wa_download import download_media_bytes  # type: ignore
                            provider = (payload.get("provider") or "ycloud")
                            audio_bytes, mime = download_media_bytes(provider, media)
                            ctype = (mime or "audio/ogg").split(";")[0].strip() or "audio/ogg"
                        except Exception:
                            # Fallback: download direto
                            r = requests.get(url, timeout=12)
                            r.raise_for_status()
                            audio_bytes = r.content
                            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()

                        if not audio_bytes or len(audio_bytes) < 200:
                            stt_err = "empty_audio_bytes"
                        else:
                            # Chama STT interno via HTTP (mesmo serviço)
                            try:
                                base = (os.environ.get("BACKEND_BASE") or "").strip().rstrip("/")
                                if not base:
                                    # tenta inferir pelo request atual
                                    base = (request.host_url or "").strip().rstrip("/")
                                stt_url = f"{base}/api/voz/stt"

                                headers = {"Content-Type": ctype or "audio/ogg"}
                                rr = requests.post(stt_url, data=audio_bytes, headers=headers, timeout=25)
                                if rr.status_code == 200:
                                    try:
                                        j = rr.json() or {}
                                    except Exception:
                                        j = {}
                                    if j.get("ok"):
                                        transcript = (j.get("transcript") or "").strip()
                                        if not transcript:
                                            # 200 ok, mas transcript vazio => falha real (áudio curto/silêncio/decoder)
                                            stt_err = "empty_transcript"
                                    else:
                                        stt_err = f"stt_not_ok:{j.get('error')}"
                                else:
                                    stt_err = f"stt_http_{rr.status_code}"
                            except Exception as e:
                                stt_err = f"stt_exc:{e}"

                except Exception as e:
                    stt_err = f"stt_outer_exc:{e}"

                if transcript:
                    text_in = transcript
                    # opcional: dá um debug leve no outbox
                    audio_debug = dict(audio_debug or {})
                    audio_debug["stt"] = {"ok": True}
                else:
                    # STT falhou (ou transcript vazio): ainda assim, deixamos a IA responder com fallback humano/curto.
                    logger.warning("[tasks] stt_failed from=%s wamid=%s reason=%s", from_e164, wamid, stt_err)
                    audio_debug = dict(audio_debug or {})
                    audio_debug["stt"] = {"ok": False, "reason": stt_err}
                    # Importante: não inventar contexto quando STT falha. Pedir reenvio (áudio) ou texto.
                    text_in = (
                        "⚠️ O usuário enviou um áudio no WhatsApp, mas não foi possível transcrever (falha de STT). "
                        "Responda de forma curta e humana pedindo para reenviar o áudio com mais clareza (ou mandar em texto). "
                        "Não invente detalhes do negócio nem assuma intenção."
                    )
                    skip_wa_bot = False

            if hasattr(wa_bot_entry, "reply_to_text"):
                if skip_wa_bot:
                    wa_out = {"replyText": reply_text, "audioUrl": "", "audioDebug": audio_debug}
                else:
                    ctx_for_bot = {
                        "channel": "whatsapp",
                        "from_e164": from_e164,
                        "to_e164": to_e164,
                        "msg_type": msg_type,
                        "wamid": wamid,
                        "route_hint": route_hint,
                        "event_key": event_key,
                    }
                    # Contexto extra (sem regras): ajuda o wa_bot a decidir fallback sem inventar.
                    try:
                        ctx_for_bot["audio"] = {
                            "input_was_audio": msg_type in ("audio", "voice", "ptt"),
                            "stt": (audio_debug or {}).get("stt") or {},
                        }
                    except Exception:
                        pass
                    # PATCH A (obrigatório): garantir msg_type no ctx do wa_bot
                    ctx_for_bot["msg_type"] = msg_type  # "audio" | "voice" | "ptt" | "text"
    
                    wa_out = wa_bot_entry.reply_to_text(
                        uid=uid,
                        text=text_in,
                        ctx=ctx_for_bot,
                    )

        except Exception as e:
            # Best-effort: não derruba o worker se o wa_bot falhar/import quebrar
            logger.exception("[tasks] wa_bot_failed route_hint=%s from=%s wamid=%s", ("sales" if not uid else "customer"), from_e164, wamid)
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
                reply_text = "Não consegui entender direitinho 🙂 Você quer: conhecer a plataforma, ver preços/planos, ou falar de um uso no seu negócio?"
            else:
                logger.warning(
                    "[tasks] customer_empty_reply from=%s wamid=%s",
                    from_e164, wamid
                )
                reply_text = "Não consegui responder agora 😕 Pode tentar de novo ou me explicar um pouco melhor?"

        # ==========================================================
        # TTS automático (universal): se entrou por áudio, deve sair por áudio.
        # Se o wa_bot não devolveu audioUrl, geramos via /api/voz/tts.
        #
        # - customer (uid): usa vozClonada.voiceId se existir
        # - sales (uid vazio): usa INSTITUTIONAL_VOICE_ID (ENV) se existir
        # ==========================================================
        if msg_type in ("audio", "voice", "ptt") and (not audio_url) and reply_text:
            try:
                base = (os.environ.get("BACKEND_BASE") or "").strip().rstrip("/")
                if not base:
                    base = (request.host_url or "").strip().rstrip("/")
                tts_url = f"{base}/api/voz/tts"

                voice_id = ""
                if uid:
                    # voz do próprio MEI (se existir)
                    try:
                        prof = _db().collection("profissionais").document(uid).get()
                        prof_data = prof.to_dict() or {}
                        vc = prof_data.get("vozClonada") or {}
                        voice_id = (vc.get("voiceId") or "").strip()
                    except Exception:
                        voice_id = ""
                else:
                    # voz institucional para VENDAS (defina esta ENV)
                    voice_id = (os.environ.get("INSTITUTIONAL_VOICE_ID") or "").strip()
                # Fallback de voice_id: mesmo sem voz clonada pronta, tentamos responder em áudio.
                # - customer (uid): SUPPORT_FALLBACK_VOICE_ID (se existir) senão INSTITUTIONAL_VOICE_ID
                # - sales (uid vazio): INSTITUTIONAL_VOICE_ID (se existir) senão SUPPORT_FALLBACK_VOICE_ID
                if not voice_id:
                    if uid:
                        voice_id = (os.environ.get("SUPPORT_FALLBACK_VOICE_ID") or "").strip()
                        if not voice_id:
                            voice_id = (os.environ.get("INSTITUTIONAL_VOICE_ID") or "").strip()
                    else:
                        voice_id = (os.environ.get("INSTITUTIONAL_VOICE_ID") or "").strip()
                        if not voice_id:
                            voice_id = (os.environ.get("SUPPORT_FALLBACK_VOICE_ID") or "").strip()
                if voice_id:
                    rr = requests.post(
                        tts_url,
                        headers={"Accept": "application/json"},
                        json={"text": reply_text, "voice_id": voice_id},
                        timeout=35,
                    )

                    if rr.status_code == 200:
                        try:
                            j = rr.json() or {}
                        except Exception:
                            j = {}

                        got = (j.get("audioUrl") or j.get("audio_url") or "").strip()
                        if j.get("ok") and got:
                            audio_url = got
                            audio_debug = dict(audio_debug or {})
                            audio_debug["tts"] = {"ok": True, "voice_id": voice_id}
                        else:
                            # se veio 200 mas não veio JSON/ok/audioUrl, registra motivo sem quebrar
                            reason = j.get("error") if isinstance(j, dict) else None
                            if not reason:
                                # ajuda debug: corta corpo enorme, mas dá uma pista
                                body_hint = (rr.text or "").strip()
                                if len(body_hint) > 200:
                                    body_hint = body_hint[:200] + "..."
                                reason = f"tts_not_ok_or_nonjson:{body_hint or 'empty_body'}"

                            audio_debug = dict(audio_debug or {})
                            audio_debug["tts"] = {"ok": False, "reason": reason}
                    else:
                        audio_debug = dict(audio_debug or {})
                        audio_debug["tts"] = {"ok": False, "reason": f"tts_http_{rr.status_code}"}
                else:
                    audio_debug = dict(audio_debug or {})
                    audio_debug["tts"] = {"ok": False, "reason": "missing_voice_id"}
                    
            except Exception as e:
                logger.exception("[tasks] tts_failed uid=%s wamid=%s", uid, wamid)
                audio_debug = dict(audio_debug or {})
                audio_debug["tts"] = {"ok": False, "reason": f"tts_exc:{e}"}
                    
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
        "createdAt": firestore.SERVER_TIMESTAMP,
        "from": from_e164,
        "to": to_e164,
        "wamid": wamid,
        "msgType": msg_type,
        "route": "sales" if not uid else "customer",
        "replyText": (reply_text or "")[:400],
        "audioUrl": (audio_url or "")[:300],
        "audioDebug": audio_debug,
        "eventKey": event_key,
        "sentOk": bool(sent_ok),
            })
        except Exception:
            logger.warning("[tasks] outbox_log_failed from=%s to=%s wamid=%s eventKey=%s", from_e164, to_e164, wamid, event_key, exc_info=True)

        return jsonify({"ok": True, "sent": bool(sent_ok)}), 200

    except Exception:
        logger.exception("[tasks] fatal: erro inesperado")
        return jsonify({"ok": True}), 200
