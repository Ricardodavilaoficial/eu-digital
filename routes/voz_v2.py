# routes/voz_v2.py
# Voz V2 — upload de amostra de voz para clonagem
# Endpoints:
#   POST /api/voz/upload      (multipart: voz, uid)
#   POST /api/voz/upload/     (mesma função; evita redirect 308/405)
#   GET  /api/voz/ping        (sanidade)
#   GET  /api/voz/diag        (diagnóstico rápido)

from flask import Blueprint, request, jsonify
import time, logging
import importlib

from services.voice_validation import (
    ensure_audio_present,
    validate_mime,
    validate_size,
    probe_duration,
    sanitize_filename,
)
from services.storage_gcs import upload_bytes_and_get_url
from services.voice_metadata import record_last_voice_url

voz_upload_bp = Blueprint("voz_upload_v2", __name__)

_MIN_SECONDS = 30  # recomendado (>=60s ideal)

def _do_upload():
    req_id = f"cfg-voz-{int(time.time()*1000)}"

    # 1) Arquivo obrigatório
    f = ensure_audio_present(request.files.get("voz"))
    mimetype = validate_mime(f.mimetype)

    # 2) Tamanho
    raw = f.read()
    validate_size(len(raw))

    # 3) Duração
    duration = probe_duration(raw, mimetype)
    # Aceita quando for desconhecida (<=0). Só barra se for conhecida e < 30s.
    if (duration is not None) and (duration > 0) and (duration < _MIN_SECONDS):
        return jsonify({
            "ok": False,
            "error": "too_short",
            "message": f"Áudio muito curto. Grave ao menos {_MIN_SECONDS} segundos."
        }), 422

    # 4) UID + nome seguro
    uid = (request.form.get("uid") or "").strip() or "sem_uid"
    filename = sanitize_filename(f.filename)

    # 5) Upload (público ou Signed URL, conforme storage_gcs)
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

    # 6) Persistência leve (não bloqueante)
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
    # diagnóstico rápido do ambiente de voz
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
