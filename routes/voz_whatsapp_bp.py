# routes/voz_whatsapp_bp.py
# NOVO (v1.1 + hotfix v2) — Voz via WhatsApp (inbound + convite outbound opcional)

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional

from flask import Blueprint, request, jsonify
from firebase_admin import auth as fb_auth
from firebase_admin import firestore as fb_firestore  # type: ignore
from services.firebase_admin_init import ensure_firebase_admin

from services.voice_wa_link import (
    generate_link_code,
    save_link_code,
    consume_link_code,
    upsert_sender_link,
    delete_sender_link,
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
from services.voice_wa_storage import upload_voice_bytes
from services.wa_send import send_template

voz_whatsapp_bp = Blueprint("voz_whatsapp_bp", __name__)

def _db():
    """Firestore canônico: sempre via firebase-admin."""
    ensure_firebase_admin()
    return fb_firestore.client()

def _now_ts():
    return fb_firestore.SERVER_TIMESTAMP

def _get_profile_telefone_candidates(uid: str) -> list[str]:
    """Busca possíveis telefones do MEI no Firestore (por UID).

    Mantém compat com várias chaves antigas/novas. Retorna lista (pode vir vazia).
    """
    try:
        doc = _db().collection("profissionais").document(uid).get()
        if not doc.exists:
            return []
        data = doc.to_dict() or {}
    except Exception:
        return []

    out: list[str] = []

    # formato atual: profissionais/{uid}.dadosBasicos.telefone / telefoneE164
    dados = (data.get("dadosBasicos") or {}) if isinstance(data.get("dadosBasicos"), dict) else {}
    for k in ("telefoneE164", "whatsE164", "phoneE164", "telefone", "whatsapp", "whats"):
        v = dados.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())

    # compat: campos no topo
    for k in ("telefoneE164", "whatsE164", "phoneE164", "telefone", "whatsapp", "whats"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())

    # de-dup mantendo ordem
    seen = set()
    uniq: list[str] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def _resolve_to_e164(uid: str, body: dict) -> str:
    """Resolve telefone destino (toE164) a partir do body ou do perfil no Firestore."""
    raw = (body.get("toE164") or body.get("phoneE164") or body.get("whatsE164") or "")
    to_e164 = normalize_e164_br(raw)

    if to_e164:
        return to_e164

    # fallback: buscar no perfil do usuário logado
    for cand in _get_profile_telefone_candidates(uid):
        to_e164 = normalize_e164_br(cand)
        if to_e164:
            return to_e164

    return ""
def _mode_on() -> bool:
    return (os.environ.get("VOICE_WA_MODE", "off").strip().lower() == "on")

def _outbound_on() -> bool:
    return (os.environ.get("VOICE_WA_OUTBOUND_MODE", "off").strip().lower() == "on")

def _get_auth_uid() -> str:
    authz = request.headers.get("Authorization", "")
    if not authz.lower().startswith("bearer "):
        raise PermissionError("missing_bearer")
    token = authz.split(" ", 1)[1].strip()
    if not token:
        raise PermissionError("missing_token")
    try:
        ensure_firebase_admin()
        decoded = fb_auth.verify_id_token(token)
    except Exception:
        raise PermissionError("auth_unavailable")
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

def _log(uid: Optional[str], payload: Dict[str, Any], note: str = ""):
    try:
        db = _db()
        doc = {"createdAt": _now_ts(), "note": (note or "")[:200], "payload": payload}
        if uid:
            db.collection("profissionais").document(uid).collection("voz_whatsapp_logs").add(doc)
        else:
            db.collection("voice_wa_logs").add(doc)
    except Exception:
        pass

@voz_whatsapp_bp.route("/api/voz/whatsapp/config", methods=["GET"])
def voice_wa_config():
    try:
        _ = _get_auth_uid()
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 401
    except Exception as e:
        return jsonify({"ok": False, "error": "server_error", "detail": str(e)[:160]}), 500

    wa_number = (os.environ.get("VOICE_WA_NUMBER_E164") or os.environ.get("VOICE_WA_TEMP_NUMBER_E164") or "").strip()
    return jsonify({
        "ok": True,
        "mode": "on" if _mode_on() else "off",
        "outboundMode": "on" if _outbound_on() else "off",
        "waNumberE164": wa_number,
        "linkTtlSeconds": int(os.environ.get("VOICE_WA_LINK_TTL_SECONDS", "3600") or "3600"),
    }), 200

@voz_whatsapp_bp.route("/api/voz/whatsapp/status", methods=["GET"])
def voice_wa_status():
    try:
        uid = _get_auth_uid()
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 401
    except Exception as e:
        return jsonify({"ok": False, "error": "server_error", "detail": str(e)[:160]}), 500

    snap = _status_doc_ref(uid).get()
    if not snap.exists:
        return jsonify({"ok": True, "status": "idle", "source": "whatsapp"}), 200
    data = snap.to_dict() or {}
    data["ok"] = True
    return jsonify(data), 200

@voz_whatsapp_bp.route("/api/voz/whatsapp/link", methods=["POST"])
def voice_wa_link():
    try:
        uid = _get_auth_uid()
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 401
    except Exception as e:
        return jsonify({"ok": False, "error": "server_error", "detail": str(e)[:160]}), 500

    ttl = int(os.environ.get("VOICE_WA_LINK_TTL_SECONDS", "3600") or "3600")
    code = generate_link_code()
    save_link_code(uid=uid, code=code, ttl_seconds=ttl)
    _status_update(uid, {"status": "waiting", "source": "whatsapp", "lastError": ""})
    return jsonify({"ok": True, "code": code, "ttlSeconds": ttl}), 200

@voz_whatsapp_bp.route("/api/voz/whatsapp/invite", methods=["POST"])
def voice_wa_invite():
    if not _mode_on():
        return jsonify({"ok": True, "ignored": True, "mode": "off"}), 200

    try:
        uid = _get_auth_uid()
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 401
    except Exception as e:
        return jsonify({"ok": False, "error": "server_error", "detail": str(e)[:160]}), 500

    data = request.get_json(silent=True) or {}
    to_e164 = _resolve_to_e164(uid, data)
    if not to_e164:
        return jsonify({
            "ok": False,
            "error": "missing_toE164",
            "message": "Não achei seu WhatsApp salvo. Volte e confira seu número (com DDD) e tente de novo.",
            "hint": "Ex.: +55 51 99999-9999",
        }), 400
    if not sender_allowed(to_e164):
        return jsonify({"ok": False, "error": "unauthorized_sender"}), 403

    ttl = int(os.environ.get("VOICE_WA_LINK_TTL_SECONDS", "3600") or "3600")
    upsert_sender_link(from_e164=to_e164, uid=uid, ttl_seconds=ttl, method="invite")

    _status_update(uid, {
        "status": "waiting",
        "source": "whatsapp",
        "inviteToE164": to_e164,
        "inviteSentAt": _now_ts(),
        "lastError": "",
    })

    # ✅ Canoniza o estado para o worker (voice_waiting confiável)
    try:
        _db().collection("profissionais").document(uid).set({
            "vozClonada": {
                "status": "invited",
                "invitedAt": _now_ts(),
            }
        }, merge=True)
    except Exception:
        pass

    # ✅ Compat legado (opcional): voz.whatsapp.status
    try:
        _db().collection("profissionais").document(uid).set({
            "voz": {
                "whatsapp": {
                    "status": "invited",
                    "invitedAt": _now_ts(),
                }
            }
        }, merge=True)
    except Exception:
        pass


    # Invite sempre via template (Meta/YCloud happy)
    codigo_convite = generate_link_code()
    save_link_code(uid=uid, code=codigo_convite, ttl_seconds=ttl)

    ok, out = send_template(
        to=to_e164,
        template_name="mei_robo_convite_voz_v1",
        params=[
            codigo_convite  # {{1}} do template
        ],
    )

    if not ok:
        return jsonify({"ok": False, "error": "template_send_failed", "detail": out}), 500

    return jsonify({
        "ok": True,
        "sent": True,
        "channel": "template",
        "provider": "ycloud",
        "toE164": to_e164,
    }), 200

@voz_whatsapp_bp.route("/api/voz/whatsapp/reset", methods=["POST"])
def voice_wa_reset():
    try:
        uid = _get_auth_uid()
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 401
    except Exception as e:
        return jsonify({"ok": False, "error": "server_error", "detail": str(e)[:160]}), 500

    snap = _status_doc_ref(uid).get()
    from_e164 = ""
    if snap.exists:
        d = snap.to_dict() or {}
        from_e164 = normalize_e164_br(d.get("fromE164") or d.get("inviteToE164") or "")

    if from_e164:
        try:
            delete_sender_link(from_e164)
        except Exception:
            pass

    _status_update(uid, {
        "status": "idle",
        "lastError": "",
        "fromE164": "",
        "messageId": "",
        "provider": "",
        "mimeType": "",
        "durationSec": None,
        "storagePath": "",
        "originalFilename": "",
    })
    return jsonify({"ok": True, "status": "idle"}), 200

@voz_whatsapp_bp.route("/webhooks/voice-wa", methods=["POST"])
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

    if kind == "text":
        text = (event.get("text") or "").strip()
        m = re.match(r"(?i)^\s*MEIROBO\s+VOZ\s+([A-Z0-9]{4,10})\s*$", text)
        if not m:
            return jsonify({"ok": True}), 200

        code = m.group(1).upper()
        consume = consume_link_code(code)
        if not consume:
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

    uid = get_uid_for_sender(from_e164)
    if not uid:
        _log(None, payload, note=f"no_link_for_sender sender={from_e164}")
        return jsonify({"ok": True}), 200

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

        _status_update(uid, {
            "status": "saved",
            "storagePath": storage_path,
            "mimeType": mime or "",
            "originalFilename": media.get("filename") or "",
        })
        _log(uid, payload, note=f"saved path={storage_path}")
        return jsonify({"ok": True}), 200

    except Exception:
        _status_set_failed(uid, "download_or_storage_failed")
        _log(uid, payload, note="failed")
        return jsonify({"ok": True}), 200
