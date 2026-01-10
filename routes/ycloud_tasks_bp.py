# routes/ycloud_tasks_bp.py
from __future__ import annotations

import os
import time
import re
import hashlib
import logging
import uuid
import datetime
from google.cloud import storage as gcs_storage  # type: ignore
from typing import Any, Dict, Optional, Tuple

import requests

from flask import Blueprint, request, jsonify

from services.phone_utils import digits_only as _digits_only_c, to_plus_e164 as _to_plus_e164_c
from google.cloud import firestore  # type: ignore

logger = logging.getLogger("mei_robo.ycloud_tasks")

ycloud_tasks_bp = Blueprint("ycloud_tasks_bp", __name__)


_IDENTITY_MODE = (os.environ.get("IDENTITY_MODE") or "on").strip().lower()  # on|off


def _db():
    project_id = (os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip() or None
    return firestore.Client(project=project_id)


def _db_admin():
    try:
        from firebase_admin import firestore as admin_fs  # type: ignore
        return admin_fs.client()
    except Exception:
        return None


def _sha1_id(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


def _digits_only(s: str) -> str:
    return _digits_only_c(s)


def _to_plus_e164(raw: str) -> str:
    return _to_plus_e164_c(raw)


_NAME_OVERRIDE_TTL = int(os.environ.get("SUPPORT_NAME_OVERRIDE_TTL_SECONDS", "3600") or "3600")  # 1h



# ==========================================================
# IDENTIDADE PREMIUM (interlocutor ativo por waKey)
# - Filtro econômico por gatilhos (barato)
# - IA só quando necessário (curta, JSON)
# - Estado persistido garante 2ª mensagem certa
# ==========================================================
_SPEAKER_TTL = int(os.environ.get("SUPPORT_SPEAKER_TTL_SECONDS", "21600") or "21600")  # 6h
_SPEAKER_COLL = (os.environ.get("SPEAKER_STATE_COLL") or "platform_speaker_state").strip()

def _speaker_db():
    return _db_admin() or _db()

def _get_owner_name(uid: str) -> str:
    """Tenta inferir nome do MEI (dono da conta) para permitir 'voltei / sou o Ricardo' etc."""
    if not uid:
        return ""
    try:
        prof = _db().collection("profissionais").document(uid).get()
        data = prof.to_dict() or {}
        # tenta chaves comuns no teu projeto
        for k in ("display_name", "displayName", "nome", "name"):
            v = (data.get(k) or "").strip()
            if v:
                return v
    except Exception:
        pass
    return ""

def _get_active_speaker(wa_key: str) -> str:
    if not wa_key:
        return ""
    try:
        snap = _speaker_db().collection(_SPEAKER_COLL).document(wa_key).get()
        if not snap.exists:
            return ""
        data = snap.to_dict() or {}
        exp = float(data.get("expiresAt") or 0.0)
        if exp and time.time() > exp:
            return ""
        nm = str(data.get("displayName") or "").strip()
        return nm
    except Exception:
        return ""

def _set_active_speaker(wa_key: str, display_name: str, source: str, confidence: float = 0.0) -> None:
    if not wa_key or not display_name:
        return
    now = time.time()
    try:
        _speaker_db().collection(_SPEAKER_COLL).document(wa_key).set(
            {
                "displayName": display_name,
                "source": source,
                "confidence": float(confidence or 0.0),
                "updatedAt": now,
                "expiresAt": now + _SPEAKER_TTL,
            },
            merge=True,
        )
    except Exception as e:
        logger.warning("[speaker] falha ao salvar waKey=%s err=%s", wa_key, str(e)[:120])

def _looks_like_identity_signal(text: str) -> bool:
    """Filtro econômico: só chama IA quando tem cheiro de troca/auto-identificação."""
    t = (text or "").strip().lower()
    if not t:
        return False
    # sinais fortes e baratos
    signals = (
        "meu nome é",
        "aqui é",
        "quem fala é",
        "sou o",
        "sou a",
        "prazer",
        "voltei",
        "sou eu",
        "de novo",
        "me chama de",
        "pode me chamar",
        "fala com",
        "passa pro",
        "agora é",
        "agora sou",
        "é o",
        "é a",
    )
    return any(s in t for s in signals)

def _openai_extract_speaker(text: str, owner_name: str = "", active_name: str = "") -> Tuple[str, float, str]:
    """
    IA focada: decide nome do interlocutor ativo.
    Retorna: (name, confidence, reason) — name vazio = não identificou.
    """
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return ("", 0.0, "missing_api_key")

    # Modelo: barato e suficiente
    model = (os.environ.get("IDENTITY_LLM_MODEL") or "gpt-4o-mini").strip()
    t = (text or "").strip()
    if not t:
        return ("", 0.0, "empty_text")

    # prompt curto e objetivo (JSON-only)
    sys = """You extract the ACTIVE speaker name from a single WhatsApp message in Portuguese.
    Return ONLY valid JSON.
    Rules:
    - If the message is self-identification, return that name.
    - If the message indicates returning to the owner (e.g., \"voltei\", \"agora sou eu de novo\") and owner_name is known, return owner_name.
    - Avoid third-person mentions (e.g., \"o papo é com o José\") unless it\'s clearly the speaker.
    - Name can be nickname (e.g., \"Banana\", \"Zé\").
    JSON schema:
    { "identified": true|false, "name": "...", "confidence": 0..1, "reason": "..." }
    """
    user = {
        "text": t[:300],
        "owner_name": (owner_name or "")[:60],
        "current_active_name": (active_name or "")[:60],
    }

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.0,
                "max_tokens": 120,
                "messages": [
                    {"role": "system", "content": sys},
                    {"role": "user", "content": str(user)},
                ],
            },
            timeout=18,
        )
        if r.status_code != 200:
            return ("", 0.0, f"http_{r.status_code}")
        j = r.json() or {}
        content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        content = (content or "").strip()
        # parse JSON safely
        try:
            import json as _json
            data = _json.loads(content)
        except Exception:
            # tenta extrair bloco {...}
            m = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not m:
                return ("", 0.0, "non_json")
            import json as _json
            data = _json.loads(m.group(0))

        identified = bool(data.get("identified"))
        name = str(data.get("name") or "").strip()
        conf = float(data.get("confidence") or 0.0)
        reason = str(data.get("reason") or "").strip()[:120]
        if not identified or not name:
            return ("", conf, reason or "not_identified")
        # hard cap: evita string gigante
        name = name[:40]
        return (name, conf, reason or "ok")
    except Exception as e:
        return ("", 0.0, f"exc:{type(e).__name__}")


def _detect_name_override(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    patterns = [
        r"\bmeu nome é\s+(?:o|a|os|as)?\s*([A-Za-zÀ-ÿ]{2,}(?:\s+[A-Za-zÀ-ÿ]{2,}){0,2})\b",
        r"\baqui é\s+(?:o|a|os|as)?\s*([A-Za-zÀ-ÿ]{2,}(?:\s+[A-Za-zÀ-ÿ]{2,}){0,2})\b",
        r"\baqui quem fala é\s+([A-Za-zÀ-ÿ]{2,})\b",
        r"\bnão é\s+[A-Za-zÀ-ÿ]{2,}\s*,?\s*é\s+([A-Za-zÀ-ÿ]{2,})\b",
        r"\bnão sou\s+[A-Za-zÀ-ÿ]{2,}\s*,?\s*sou\s+([A-Za-zÀ-ÿ]{2,})\b",
    ]
    for p in patterns:
        m = re.search(p, t, flags=re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip()
    return ""

def _set_name_override(wa_key: str, name: str) -> None:
    if not wa_key or not name:
        return
    now = time.time()
    db = _db_admin()
    if not db:
        logger.warning("[nameOverride] admin firestore indisponível; não salvou waKey=%s", wa_key)
        return
    try:
        db.collection("platform_name_overrides").document(wa_key).set({
            "name": name,
            "updatedAt": now,
            "expiresAt": now + _NAME_OVERRIDE_TTL,
        }, merge=True)
    except Exception as e:
        logger.warning("[nameOverride] falha ao salvar waKey=%s err=%s", wa_key, str(e)[:120])


def _get_name_override(wa_key: str) -> str:
    if not wa_key:
        return ""
    db_read = _db_admin() or _db()
    try:
        doc = db_read.collection("platform_name_overrides").document(wa_key).get()
        if not doc.exists:
            return ""
        data = doc.to_dict() or {}
        exp = float(data.get("expiresAt") or 0.0)
        if exp and time.time() <= exp:
            return str(data.get("name") or "").strip()
    except Exception:
        pass
    return ""

def _apply_name_override(reply_text: str, override_name: str) -> str:
    if not override_name:
        return reply_text
    s = (reply_text or "").strip()

    # Só troca saudação no começo (não mexe no corpo)
    # "Oi, Edson!" / "Olá Edson!" / "Olá, Edson!"
    s2 = re.sub(
        r"^(oi|olá)\s*,?\s*[^!?.\n]{1,60}([!?.])",
        rf"\1, {override_name}\2",
        s,
        flags=re.IGNORECASE,
    )
    return s2


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
        to_e164 = _to_plus_e164(to_raw)        # --- resolve UID (identidade) ---
        # 1) Índice permanente: sender_uid_links/{waKey} -> uid
        uid = ""
        wa_key = ""
        try:
            from services.sender_uid_links import canonical_wa_key, get_uid_for_wa_key  # type: ignore
            wa_key = (canonical_wa_key(from_e164) or "").strip()
            uid = (get_uid_for_wa_key(wa_key) or "").strip()
        except Exception:
            wa_key = ""
            uid = ""

        # 2) Fallback legado (TTL): voice_links (fluxo de voz)
        if not uid:
            try:
                from services.voice_wa_link import get_uid_for_sender  # type: ignore
                uid = (get_uid_for_sender(from_e164) or "").strip()
            except Exception:
                uid = ""

        
        # wa_key_effective: chave canônica para memória por remetente (override etc.)
        wa_key_effective = (wa_key or _digits_only(from_e164)).strip()
        owner_name = _get_owner_name(uid) if uid else ""

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
                                from subprocess import Popen, PIPE

                                def normalize_audio_for_stt(raw: bytes) -> bytes:
                                    p = Popen(
                                        [
                                            "ffmpeg",
                                            "-i", "pipe:0",
                                            "-ac", "1",
                                            "-ar", "16000",
                                            "-f", "wav",
                                            "pipe:1",
                                        ],
                                        stdin=PIPE,
                                        stdout=PIPE,
                                        stderr=PIPE,
                                    )
                                    out, _ = p.communicate(raw)
                                    return out if out else raw

                                audio_bytes = normalize_audio_for_stt(audio_bytes)
                                headers = {"Content-Type": "audio/wav"}

                                rr = requests.post(stt_url, data=audio_bytes, headers=headers, timeout=25)
                                stt_payload = {}
                                try:
                                    if rr.status_code == 200:
                                        # tenta JSON (sem explodir)
                                        try:
                                            stt_payload = rr.json() if rr.headers.get("content-type","").startswith("application/json") else {}
                                        except Exception:
                                            stt_payload = {}

                                        ok_flag = bool(stt_payload.get("ok"))
                                        transcript = (stt_payload.get("transcript") or "").strip() if ok_flag else ""
                                        if ok_flag and transcript:
                                            text_in = transcript
                                            audio_debug["stt"] = {
                                                "ok": True,
                                                "confidence": stt_payload.get("confidence"),
                                                "transcriptLen": len(transcript),
                                                "preview": transcript[:120],
                                            }
                                        else:
                                            # motivo real (ex.: empty_transcript / stt_failed)
                                            err_code = (stt_payload.get("error") or "").strip() or f"http_{rr.status_code}"
                                            detail = (stt_payload.get("detail") or "").strip()
                                            stt_err = f"stt_not_ok:{err_code}" + (f":{detail[:80]}" if detail else "")
                                            audio_debug["stt"] = {
                                                "ok": False,
                                                "error": err_code,
                                                "detail": detail[:160],
                                                "http": rr.status_code,
                                                "bodyHint": (rr.text or "")[:160],
                                            }
                                            logger.warning(
                                                "[tarefas] stt_not_ok from=%s wamid=%s err=%s detail=%s",
                                                from_e164, wamid, err_code, detail[:120]
                                            )
                                    else:
                                        stt_err = f"stt_http_{rr.status_code}"
                                        audio_debug["stt"] = {"ok": False, "http": rr.status_code, "bodyHint": (rr.text or "")[:160]}
                                except Exception as e:
                                    stt_err = f"stt_exc:{type(e).__name__}"
                                    audio_debug["stt"] = {"ok": False, "reason": stt_err}
                            except Exception as e:
                                stt_err = f"stt_exc:{e}"

                except Exception as e:
                    stt_err = f"stt_outer_exc:{e}"

                if transcript:
                    text_in = transcript
                    # mantém detalhes do STT (não sobrescreve)
                    audio_debug = dict(audio_debug or {})
                    audio_debug.setdefault("stt", {"ok": True})
                else:
                    # PATCH 1 (worker): se STT não trouxe transcript, NÃO chama IA.
                    logger.warning("[tasks] lead: stt_failed from=%s wamid=%s reason=%s", from_e164, wamid, stt_err)
                    reply_text = "Não consegui entender esse áudio. Pode mandar em texto ou repetir rapidinho?"
                    skip_wa_bot = True
                    audio_debug = dict(audio_debug or {})
                    audio_debug.setdefault("stt", {"ok": False, "reason": stt_err})


                        # ==========================================================
            # IDENTIDADE PREMIUM (interlocutor ativo)
            # - Primeiro tenta override por regex (barato)
            # - Se não tiver, e houver gatilho, chama IA (curta) e persiste
            # ==========================================================
            try:
                nm = _detect_name_override(text_in)
                if nm and wa_key_effective:
                    _set_name_override(wa_key_effective, nm)
                    # também seta interlocutor ativo (garante 2ª mensagem)
                    if _IDENTITY_MODE != "off":
                        _set_active_speaker(wa_key_effective, nm, source="regex", confidence=0.70)
                    audio_debug = dict(audio_debug or {})
                    audio_debug["nameOverrideProbe_set"] = {"waKey": wa_key_effective, "name": nm}
            except Exception:
                pass

            # IA: só quando tem sinal de troca/apresentação e ainda não temos speaker bom
            try:
                if _IDENTITY_MODE != "off" and wa_key_effective and text_in:
                    active_now = _get_active_speaker(wa_key_effective)
                    # se já temos active speaker e não há sinal, não gasta IA
                    if _looks_like_identity_signal(text_in) and (not active_now):
                        name_ai, conf_ai, reason_ai = _openai_extract_speaker(
                            text_in,
                            owner_name=owner_name,
                            active_name=active_now,
                        )
                        audio_debug = dict(audio_debug or {})
                        audio_debug["speakerAI"] = {
                            "triggered": True,
                            "ownerName": owner_name,
                            "activeBefore": active_now,
                            "identifiedName": name_ai,
                            "confidence": conf_ai,
                            "reason": reason_ai,
                        }
                        # Persistir se confiança razoável
                        if name_ai and conf_ai >= 0.65:
                            _set_active_speaker(wa_key_effective, name_ai, source="ai", confidence=conf_ai)
                            # mantém override antigo também (compat)
                            _set_name_override(wa_key_effective, name_ai)
                            audio_debug["speakerAI"]["persisted"] = True
                        else:
                            audio_debug["speakerAI"]["persisted"] = False
                    else:
                        # debug leve (sem custo)
                        audio_debug = dict(audio_debug or {})
                        audio_debug["speakerAI"] = {
                            "triggered": False,
                            "activeBefore": active_now,
                            "hasSignal": bool(_looks_like_identity_signal(text_in)),
                        }
            except Exception:
                pass

            if hasattr(wa_bot_entry, "reply_to_text"):
                if skip_wa_bot:
                    wa_out = {"replyText": reply_text, "audioUrl": "", "audioDebug": audio_debug}
                else:
                    ctx_for_bot = {
                        "channel": "whatsapp",
                        "from_e164": from_e164,
                        "waKey": wa_key_effective,
                        "to_e164": to_e164,
                        "msg_type": msg_type,
                        "wamid": wamid,
                        "route_hint": route_hint,
                        "event_key": event_key,
                    }
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

        # PATCH B: respeitar prefersText / displayName vindo do wa_bot
        prefers_text = False
        display_name = ""
        if isinstance(wa_out, dict):
            prefers_text = bool(wa_out.get("prefersText"))
            display_name = (wa_out.get("displayName") or "").strip()
        # Se entrou por áudio, nunca preferir texto (mantém "entra áudio → sai áudio")
        if msg_type in ("audio", "voice", "ptt"):
            prefers_text = False


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
        # Guardrail (customer): suporte NÃO pede CNPJ.
        # Se algum caminho legado tentar validar identidade, trocamos
        # por um pedido humano de "como te chamo" (sem números).
        # ==========================================================
        def _looks_like_cnpj_request(s: str) -> bool:
            t = (s or "").strip().lower()
            if "cnpj" not in t:
                return False
            # padrões comuns do texto problemático
            bad = (
                "me informar seu cnpj",
                "me informar o cnpj",
                "poderia me informar seu cnpj",
                "poderia me informar o cnpj",
                "preciso confirmar",
                "confirmar se você é",
            )
            return any(k in t for k in bad)

        if uid and _looks_like_cnpj_request(reply_text):
            # mantém humanização (nome do MEI é ok), mas sem pedir CNPJ
            reply_text = (
                "Entendi 🙂 Eu não preciso do teu CNPJ pra te ajudar aqui. "
                "Só pra eu te chamar certinho: você é o Edson mesmo ou é outra pessoa falando por este WhatsApp?"
            )
            audio_debug = dict(audio_debug or {})
            audio_debug["identity_guard"] = {"applied": True, "reason": "removed_cnpj_request_for_customer"}


        # Aplica override de nome (se existir) para manter consistência na conversa
        try:
            override = ""
            try:
                # 1) Preferir interlocutor ativo (premium)
                if _IDENTITY_MODE != "off" and wa_key_effective:
                    override = _get_active_speaker(wa_key_effective) or ""

                # 2) Fallback: override legado (compat)
                if wa_key_effective:
                    override = override or _get_name_override(wa_key_effective)

                # Probe só para debug (não decide comportamento)
                if wa_key_effective:
                    db_read = _db_admin() or _db()
                    snap = db_read.collection("platform_name_overrides").document(wa_key_effective).get()
                    data = snap.to_dict() or {}
                    name_probe = str(data.get("name") or "").strip()
                    exp = float(data.get("expiresAt") or 0.0)
                    audio_debug = dict(audio_debug or {})
                    audio_debug["nameOverrideProbe_get"] = {
                        "waKey": wa_key_effective,
                        "docExists": bool(snap.exists),
                        "name": name_probe,
                        "expiresAt": exp,
                        "now": time.time(),
                    }

                    # speaker state probe
                    try:
                        sp = _speaker_db().collection(_SPEAKER_COLL).document(wa_key_effective).get()
                        spd = sp.to_dict() or {}
                        audio_debug["speakerStateProbe_get"] = {
                            "docExists": bool(sp.exists),
                            "displayName": str(spd.get("displayName") or "").strip(),
                            "expiresAt": float(spd.get("expiresAt") or 0.0),
                            "source": str(spd.get("source") or "").strip(),
                            "confidence": float(spd.get("confidence") or 0.0),
                            "now": time.time(),
                        }
                    except Exception:
                        pass
                    if exp and time.time() > exp:
                        override = ""
            except Exception as e:
                audio_debug = dict(audio_debug or {})
                audio_debug["nameOverrideProbe_get_err"] = str(e)[:120]
                override = ""

            if override:
                reply_text_before_override = reply_text
                reply_text = _apply_name_override(reply_text, override)
                audio_debug = dict(audio_debug or {})
                audio_debug["nameOverride"] = {"applied": True, "name": override}

                # 🔥 CRÍTICO: se já tinha áudio pronto (ex.: vindo do wa_bot),
                # mas o texto mudou por override, invalida áudio pra regenerar com o nome certo.
                if audio_url and reply_text != reply_text_before_override:
                    audio_debug["ttsRegen"] = {"forced": True, "reason": "name_override_changed_text"}
                    audio_url = ""
        except Exception:
            pass

        # ==========================================================
        # Se o usuário pediu "somente texto", respeita.
        if prefers_text and msg_type in ("audio", "voice", "ptt"):
            audio_debug = dict(audio_debug or {})
            audio_debug["mode"] = "text_only_requested"
            audio_url = ""  # garante que não envia áudio

        # ==========================================================
        # TTS automático (universal): se entrou por áudio, deve sair por áudio.
        # Se o wa_bot não devolveu audioUrl, geramos via /api/voz/tts.
        #
        # - customer (uid): usa vozClonada.voiceId se existir
        # - sales (uid vazio): usa INSTITUTIONAL_VOICE_ID (ENV) se existir
        # ==========================================================
        if msg_type in ("audio", "voice", "ptt") and (not audio_url) and reply_text and (not prefers_text):
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

                # Fallback universal: se entrou por áudio e não há voiceId do MEI, usa voz institucional
                if not voice_id:
                    voice_id = (os.environ.get("INSTITUTIONAL_VOICE_ID") or "").strip()
                    if uid and voice_id:
                        audio_debug = dict(audio_debug or {})
                        audio_debug["ttsVoiceFallback"] = "institutional_for_customer_no_voiceId"

                # se não há voice_id, não forçamos TTS (cai para texto, nunca mudo)
                if voice_id:
                    rr = requests.post(
                        tts_url,
                        headers={"Accept": "application/json"},
                        json={"text": reply_text, "voice_id": voice_id},
                        timeout=35,
                    )

                    if rr.status_code == 200:
                        # 1) Tentativa normal: JSON com audioUrl
                        try:
                            j = rr.json()
                            if isinstance(j, dict) and j.get("ok") is True and (j.get("audioUrl") or ""):
                                audio_url = (j.get("audioUrl") or "").strip()
                                audio_debug = dict(audio_debug or {})
                                audio_debug["tts"] = {"ok": True, "mode": "json_audioUrl"}
                            else:
                                raise ValueError("json_missing_audioUrl")
                        except Exception:
                            # 2) Fallback premium: MP3 bytes (ex.: começa com ID3)
                            try:
                                b = rr.content or b""
                                head = b[:3]
                                ct = (rr.headers.get("content-type") or "").lower()

                                is_mp3 = (head == b"ID3") or ("audio" in ct) or b.startswith(b"\xff\xfb")
                                if not is_mp3 or len(b) < 256:
                                    raise ValueError("not_mp3_bytes")

                                bucket_name = (os.environ.get("STORAGE_BUCKET") or "").strip()
                                if not bucket_name:
                                    raise ValueError("missing_STORAGE_BUCKET")

                                # upload em um caminho estável (não conflita)
                                now = datetime.datetime.utcnow()
                                obj = f"sandbox/institutional_tts/{now:%Y/%m/%d}/{uuid.uuid4().hex}.mp3"

                                client = gcs_storage.Client()
                                bucket = client.bucket(bucket_name)
                                blob = bucket.blob(obj)
                                blob.upload_from_string(b, content_type="audio/mpeg")

                                exp_s = int(os.environ.get("SIGNED_URL_EXPIRES_SECONDS", "900") or "900")
                                audio_url = blob.generate_signed_url(
                                    expiration=datetime.timedelta(seconds=exp_s),
                                    method="GET",
                                )

                                audio_debug = dict(audio_debug or {})
                                audio_debug["tts"] = {"ok": True, "mode": "bytes_upload_signed", "bytes": len(b), "ct": ct[:40]}
                            except Exception as e2:
                                # erro real: não conseguimos obter uma URL pra mandar ao WhatsApp
                                audio_debug = dict(audio_debug or {})
                                audio_debug["tts"] = {"ok": False, "reason": f"tts_bytes_fail:{type(e2).__name__}:{str(e2)[:80]}"}
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

        # PATCH B: se prefersText, manda direto texto e não tenta áudio
        if prefers_text and send_text:
            try:
                sent_ok, _ = send_text(from_e164, reply_text)
            except Exception:
                logger.exception("[tasks] lead: falha send_text (prefersText)")
        
        if (not prefers_text) and allow_audio and msg_type in ("audio", "voice", "ptt") and audio_url and send_audio:
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
