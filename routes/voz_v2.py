# routes/voz_v2.py
# Voz V2 — upload de amostra de voz para clonagem
# Endpoints:
#   POST /api/voz/upload      (multipart: voz, uid)
#   POST /api/voz/upload/     (mesma função; evita redirect 308/405)
#   GET  /api/voz/ping        (sanidade)
#   GET  /api/voz/diag        (diagnóstico rápido)
#   GET  /api/voz/last        (retorna vozClonada do Firestore, SEMPRE reassinando a URL de leitura)
#   POST /api/voz/gcs_diag_write  (teste de escrita no bucket)

from flask import Blueprint, request, jsonify
import time, logging, importlib, os, re
from urllib.parse import urlparse

from services.voice_validation import (
    ensure_audio_present,
    validate_mime,
    validate_size,
    probe_duration,
    sanitize_filename,
)

# upload util (já existente)
from services.storage_gcs import upload_bytes_and_get_url

# assinatura V4 de leitura (util canônico; deve existir no projeto)
from services.storage_gcs import sign_v4_read_url

from services.voice_metadata import record_last_voice_url

voz_upload_bp = Blueprint("voz_upload_v2", __name__)

_MIN_SECONDS = 30  # recomendado (>=60s ideal)

# ---------------------------------------
# Helpers locais para o /api/voz/last
# ---------------------------------------

_BUCKET_FALLBACK = "mei-robo-prod.firebasestorage.app"

def _bucket_literal():
    # Nunca converter para .appspot.com
    return os.environ.get("STORAGE_BUCKET", _BUCKET_FALLBACK)

def _extract_object_key_from_url(url: str) -> str | None:
    """
    Extrai o object_key a partir de uma URL completa do GCS:
    Ex.: https://storage.googleapis.com/mei-robo-prod.firebasestorage.app/voices/UID/voz.mp3?X-Goog-...
          -> voices/UID/voz.mp3
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        path = parsed.path or ""
        if path.startswith("/"):
            path = path[1:]
        parts = path.split("/", 1)
        if len(parts) == 2 and parts[0] == _bucket_literal():
            key = parts[1]
        else:
            token = _bucket_literal() + "/"
            if token in url:
                key = url.split(token, 1)[-1]
            else:
                return None
        key = key.split("?", 1)[0]
        return key or None
    except Exception:
        return None

def _best_content_type(meta: dict | None) -> str:
    if not meta:
        return "audio/mpeg"
    mt = (meta.get("mime") or meta.get("contentType") or "").strip().lower()
    return mt or "audio/mpeg"

# ---------------------------------------
# Upload
# ---------------------------------------

def _do_upload():
    req_id = f"cfg-voz-{int(time.time()*1000)}"

    # 1) Arquivo obrigatório
    f = ensure_audio_present(request.files.get("voz"))

    # Normaliza mimetype para aceitar OPUS e variantes
    raw_mime = (getattr(f, "mimetype", None) or "").lower()

    # Alguns browsers mandam .opus como audio/opus ou application/ogg etc.
    if raw_mime in ("audio/opus", "audio/x-opus+ogg", "application/ogg"):
        raw_mime = "audio/ogg"

    mimetype = validate_mime(raw_mime)

    # 2) Tamanho
    raw = f.read()
    validate_size(len(raw))

    # 3) Duração
    duration = probe_duration(raw, mimetype)
    if (duration is not None) and (duration > 0) and (duration < _MIN_SECONDS):
        return jsonify({
            "ok": False,
            "error": "too_short",
            "message": f"Áudio muito curto. Grave ao menos {_MIN_SECONDS} segundos."
        }), 422

    # 4) UID + nome seguro
    uid = (request.form.get("uid") or "").strip() or "sem_uid"
    filename = sanitize_filename(f.filename)

    # 5) Upload
    try:
        url, bucket, gcs_path, access = upload_bytes_and_get_url(uid, filename, raw, mimetype)
    except Exception as e:
        logging.exception("(%s) GCS upload failed: %s", req_id, e)
        return jsonify({
            "ok": False,
            "error": "upload_error",
            "message": "Falha ao salvar o áudio. Tente novamente.",
            "request_id": req_id
        }), 500

    # 6) Persistência leve
    try:
        dur_sec = int(round(duration)) if (duration and duration > 0) else None
        record_last_voice_url(uid, url, mimetype, len(raw), dur_sec)
    except Exception as e:
        logging.warning("(%s) Firestore vozClonada set warning: %s", req_id, e)

    logging.info(
        "[voz-upload] req_id=%s uid=%s mime=%s bytes=%d duration=%.2f bucket=%s path=%s access=%s",
        req_id, uid, mimetype, len(raw), (duration or -1), bucket, gcs_path, access
    )

    return jsonify({
        "ok": True,
        "status": "ok",
        "uid": uid,
        "vozUrl": url,
        "meta": {
            "mime": mimetype,
            "bytes": len(raw),
            "duration_sec": (int(round(duration)) if (duration and duration > 0) else None),
            "duration_known": bool(duration and duration > 0)
        }
    }), 200


# ===== Rotas =====

@voz_upload_bp.route("/api/voz/upload", methods=["POST", "OPTIONS"])
def voz_upload_no_slash():
    if request.method == "OPTIONS":
        return ("", 204)
    return _do_upload()

@voz_upload_bp.route("/api/voz/upload/", methods=["POST", "OPTIONS"])
def voz_upload_with_slash():
    if request.method == "OPTIONS":
        return ("", 204)
    return _do_upload()

@voz_upload_bp.route("/api/voz/ping", methods=["GET"])
def voz_ping():
    return jsonify({"ok": True, "service": "voz_v2"}), 200

@voz_upload_bp.route("/api/voz/diag", methods=["GET"])
def voz_diag():
    mutagen_ok = False
    mutagen_ver = None
    try:
        m = importlib.import_module("mutagen")
        mutagen_ok = True
        mutagen_ver = getattr(m, "__version__", None)
    except Exception:
        mutagen_ok = False
    return jsonify({
        "ok": True,
        "mutagen": {"available": mutagen_ok, "version": mutagen_ver},
        "min_seconds": _MIN_SECONDS
    }), 200

@voz_upload_bp.route("/api/voz/last", methods=["GET"])
def voz_last():
    uid = (request.args.get("uid") or "").strip()
    if not uid:
        return jsonify({"ok": False, "error": "missing_uid"}), 400
    try:
        from services.gcp_creds import get_firestore_client
        db = get_firestore_client()

        doc_cfg = db.collection("configuracao").document(uid).get()
        if doc_cfg.exists:
            data = doc_cfg.to_dict() or {}
        else:
            doc_prof = db.collection("profissionais").document(uid).get()
            data = (doc_prof.to_dict() or {}) if doc_prof.exists else {}

        voz = dict(data.get("vozClonada") or {})
        status = voz.get("status") or "pending"
        provider = voz.get("provider")
        voice_id = voz.get("voiceId") or voz.get("voice_id")
        mime = _best_content_type(voz)

        object_key = (voz.get("object_key") or voz.get("objectKey") or "").strip()
        if not object_key:
            legacy_url = (voz.get("arquivoUrl") or "").strip()
            extracted = _extract_object_key_from_url(legacy_url)
            if extracted:
                object_key = extracted
                try:
                    db.collection("configuracao").document(uid).set({
                        "vozClonada": {
                            **voz,
                            "object_key": object_key
                        }
                    }, merge=True)
                except Exception as _e:
                    logging.warning("[voz-last] upsert object_key failed (uid=%s): %s", uid, _e)

        arquivo_url = None
        if object_key:
            try:
                bucket = _bucket_literal()
                expires = int(os.getenv("SIGNED_URL_EXPIRES_SECONDS", "900"))
                arquivo_url = sign_v4_read_url(
                    bucket_name=bucket,
                    object_key=object_key,
                    expires_seconds=expires,
                    inline=True,
                )
            except Exception as e:
                logging.warning("[voz-last] sign_v4_read_url failed (uid=%s, key=%s): %s", uid, object_key, e)
                arquivo_url = None

        payload = {
            "provider": provider,
            "status": status,
            "voiceId": voice_id,
            "object_key": object_key or None,
            "arquivoUrl": arquivo_url,
            "mime": mime,
            "updatedAt": voz.get("updatedAt") or time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
        }

        return jsonify({
            "ok": True,
            "uid": uid,
            "vozClonada": payload
        }), 200

    except Exception as e:
        logging.exception("[voz-last] firestore_error: %s", e)
        return jsonify({"ok": False, "error": "firestore_error", "detail": str(e)}), 500

@voz_upload_bp.route("/api/voz/gcs_diag_write", methods=["POST"])
def gcs_diag_write():
    uid = (request.form.get("uid") or "diag")
    try:
        url, bucket, path, access = upload_bytes_and_get_url(uid, "diag.txt", b"ok", "text/plain")
        return jsonify({"ok": True, "bucket": bucket, "path": path, "url": url, "access": access}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
