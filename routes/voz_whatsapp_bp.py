# routes/voz_whatsapp_bp.py
# NOVO (v1.0) — Captura de voz via WhatsApp (webhook) + status read-only
# Regras:
# - NÃO altera rotas existentes /api/voz/*
# - NÃO chama ElevenLabs (processamento fica p/ outro passo)
# - Tudo protegido por feature flag: VOICE_WA_MODE=off|on
#
# Rotas:
# - POST /webhooks/voice-wa                (webhook inbound, responde 200 sempre)
# - POST /api/voz/whatsapp/link            (auth) cria código curto p/ vincular
# - GET  /api/voz/whatsapp/status          (auth) status atual (profissionais/{uid}/voz/whatsapp)

from __future__ import annotations

import os
import re
import time
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests
from flask import Blueprint, request, jsonify

import firebase_admin
from firebase_admin import auth as fb_auth
from google.cloud import firestore  # type: ignore

from services.voice_wa_link import (
    generate_link_code,
    save_link_code,
    consume_link_code,
    upsert_sender_link,
    get_uid_for_sender,
    sender_allowed,
    normalize_e164_br,
)
from services.voice_wa_download import (
    resolve_incoming_event,
    download_media_bytes,
    sniff_extension,
    basic_audio_validate,
)
from services.voice_wa_storage import (
    upload_voice_bytes,
)

voz_whatsapp_bp = Blueprint("voz_whatsapp_bp", __name__)

STATUS_DOC_REL_PATH = "voz/whatsapp"  # dentro de profissionais/{uid}/...

def _now_ts() -> firestore.SERVER_TIMESTAMP:  # type: ignore
    return firestore.SERVER_TIMESTAMP

def _db():
    # assume Firebase Admin já inicializado em app.py (canônico)
    return firestore.Client()

def _mode_on() -> bool:
    return (os.environ.get("VOICE_WA_MODE", "off").strip().lower() == "on")

def _get_auth_uid() -> str:
    authz = request.headers.get("Authorization", "")
    if not authz.lower().startswith("bearer "):
        raise PermissionError("missing_bearer")
    token = authz.split(" ", 1)[1].strip()
    if not token:
        raise PermissionError("missing_token")
    decoded = fb_auth.verify_id_token(token)
    uid = decoded.get("uid")
    if not uid:
        raise PermissionError("no_uid")
    return uid

def _status_doc_ref(uid: str):
    return _db().collection("profissionais").document(uid).collection("voz").document("whatsapp")

def _status_update(uid: str, patch: Dict[str, Any]):
    ref = _status_doc_ref(uid)
    patch = dict(patch or {})
    patch["updatedAt"] = _now_ts()
    ref.set(patch, merge=True)

def _status_set_failed(uid: str, err: str, extra: Optional[Dict[str, Any]] = None):
    payload: Dict[str, Any] = {"status": "failed", "lastError": (err or "unknown_error")[:120]}
    if extra:
        payload.update(extra)
    _status_update(uid, payload)

def _log(uid: Optional[str], event: Dict[str, Any], note: str = ""):
    try:
        db = _db()
        doc = {
            "createdAt": _now_ts(),
            "note": (note or "")[:200],
            "event": event,
        }
        if uid:
            db.collection("profissionais").document(uid).collection("voz_whatsapp_logs").add(doc)
        else:
            db.collection("voice_wa_logs").add(doc)
    except Exception:
        # logs nunca podem derrubar o webhook
        pass

@voz_whatsapp_bp.route("/api/voz/whatsapp/status", methods=["GET"])
def voice_wa_status():
    """Read-only status atual (exige Firebase idToken)."""
    try:
        uid = _get_auth_uid()
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 401

    ref = _status_doc_ref(uid)
    snap = ref.get()
    if not snap.exists:
        # default explícito p/ UX
        return jsonify({"ok": True, "status": "idle", "source": "whatsapp"}), 200

    data = snap.to_dict() or {}
    data["ok"] = True
    return jsonify(data), 200

@voz_whatsapp_bp.route("/api/voz/whatsapp/link", methods=["POST"])
def voice_wa_link():
    """Cria código curto que o MEI vai usar no WhatsApp: 'MEIROBO VOZ <CODIGO>'."""
    try:
        uid = _get_auth_uid()
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 401

    ttl = int(os.environ.get("VOICE_WA_LINK_TTL_SECONDS", "3600") or "3600")
    code = generate_link_code()
    save_link_code(uid=uid, code=code, ttl_seconds=ttl)
    # status passa p/ waiting (frontend pode orientar o próximo passo)
    _status_update(uid, {"status": "waiting", "source": "whatsapp", "lastError": ""})
    return jsonify({"ok": True, "code": code, "ttlSeconds": ttl}), 200

@voz_whatsapp_bp.route("/webhooks/voice-wa", methods=["POST"])
def voice_wa_webhook():
    """Webhook inbound (Meta/YCloud). Responde 200 sempre.
    Se VOICE_WA_MODE=off, devolve ok/ignored.
    """
    # sempre 200 p/ não quebrar provedor
    if not _mode_on():
        return jsonify({"ok": True, "ignored": True}), 200

    # segredo simples (se configurado)
    secret_env = (os.environ.get("VOICE_WA_WEBHOOK_SECRET") or "").strip()
    if secret_env:
        got = (request.headers.get("X-Voice-WA-Secret") or request.args.get("secret") or "").strip()
        if not got or got != secret_env:
            # não vaza info: só ignora
            return jsonify({"ok": True, "ignored": True}), 200

    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}

    # resolve event -> (kind, fromE164, messageId, provider, mediaInfo, text)
    event = resolve_incoming_event(payload)
    _log(None, payload, note=f"ingress kind={event.get('kind')} provider={event.get('provider')}")

    from_e164 = (event.get("fromE164") or "").strip()
    provider = (event.get("provider") or "unknown").strip()
    message_id = (event.get("messageId") or "").strip()
    kind = (event.get("kind") or "").strip()  # "text" | "audio" | "unknown"

    if from_e164:
        from_e164 = normalize_e164_br(from_e164) or from_e164

    # allowlist opcional (só bloqueia se ENV presente)
    if not sender_allowed(from_e164):
        _log(None, payload, note=f"blocked sender={from_e164}")
        # ainda 200, mas ignora
        return jsonify({"ok": True, "ignored": True}), 200

    if kind == "text":
        text = (event.get("text") or "").strip()
        # Comando: MEIROBO VOZ <CODE>
        m = re.match(r"(?i)^\s*MEIROBO\s+VOZ\s+([A-Z0-9]{4,10})\s*$", text)
        if not m:
            return jsonify({"ok": True}), 200

        code = m.group(1).upper()
        consume = consume_link_code(code)
        if not consume:
            # sem uid -> não tem como atualizar status específico
            _log(None, payload, note=f"link invalid/expired code={code} from={from_e164}")
            return jsonify({"ok": True}), 200

        uid = consume["uid"]
        ttl = consume["ttlSeconds"]
        upsert_sender_link(from_e164=from_e164, uid=uid, ttl_seconds=ttl, method="code")
        _status_update(uid, {
            "status": "received",
            "source": "whatsapp",
            "provider": provider,
            "fromE164": from_e164,
            "messageId": message_id,
            "lastError": "",
        })
        _log(uid, payload, note=f"linked sender={from_e164}")
        return jsonify({"ok": True}), 200

    if kind != "audio":
        return jsonify({"ok": True}), 200

    # áudio chegou: resolve uid por mapping
    uid = get_uid_for_sender(from_e164)
    if not uid:
        _log(None, payload, note=f"no_link_for_sender sender={from_e164}")
        # nada p/ atualizar no doc do usuário (não sabemos quem é). Ainda 200.
        return jsonify({"ok": True}), 200

    # marca recebido + baixando
    _status_update(uid, {
        "status": "received",
        "source": "whatsapp",
        "provider": provider,
        "fromE164": from_e164,
        "messageId": message_id,
        "lastError": "",
        "mimeType": event.get("mimeType") or "",
        "durationSec": event.get("durationSec"),
    })
    _status_update(uid, {"status": "downloading"})

    try:
        media = event.get("media") or {}
        raw_bytes, mime = download_media_bytes(provider=provider, media=media)
        ok, reason = basic_audio_validate(raw_bytes, mime_type=mime)
        if not ok:
            _status_set_failed(uid, reason or "audio_invalid", {"mimeType": mime or ""})
            return jsonify({"ok": True}), 200

        ext = sniff_extension(mime_type=mime, fallback="ogg")
        storage_path = f"profissionais/{uid}/voz/original/whatsapp_{int(time.time())}.{ext}"

        _status_update(uid, {"status": "saving"})
        upload_voice_bytes(storage_path=storage_path, content_type=mime or "application/octet-stream", data=raw_bytes)

        # salva status final
        _status_update(uid, {
            "status": "saved",
            "storagePath": storage_path,
            "mimeType": mime or "",
            "originalFilename": media.get("filename") or "",
            # signedUrl opcional: deixe o front pedir via /media/signed-url
        })
        _log(uid, payload, note=f"saved path={storage_path}")
        return jsonify({"ok": True}), 200

    except Exception as e:
        _status_set_failed(uid, "download_or_storage_failed")
        _log(uid, payload, note=f"failed err={type(e).__name__}")
        return jsonify({"ok": True}), 200
