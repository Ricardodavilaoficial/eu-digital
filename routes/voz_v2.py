# routes/voz_v2.py
from flask import Blueprint, request, jsonify
import time, logging, os

from services.voice_validation import (
    ensure_audio_present,
    validate_mime,
    validate_size,
    probe_duration,
    sanitize_filename,
)
from services.storage_gcs import upload_bytes_and_get_url
from services.voice_metadata import record_last_voice_url

voz_v2_bp = Blueprint("voz_v2", __name__)

# V2 — Upload de amostra de voz (PRIVADO + Signed URL) 
# POST /api/voz/upload   (multipart: voz, uid)
@voz_v2_bp.route("/api/voz/upload", methods=["POST"])
def voz_upload():
    req_id = f"cfg-voz-{int(time.time() * 1000)}"

    f = ensure_audio_present(request.files.get("voz"))
    mimetype = validate_mime(f.mimetype)

    raw = f.read()
    validate_size(len(raw))

    duration = probe_duration(raw, mimetype)
    if duration < 30:  # mínimo V2: 30s (recomendado ≥60s)
        return jsonify({
            "ok": False,
            "error": "too_short",
            "message": "Áudio muito curto. Grave ao menos 30 segundos."
        }), 422

    uid = (request.form.get("uid") or "").strip() or "sem_uid"
    filename = sanitize_filename(f.filename)

    # Upload (preferência: privado + Signed URL)
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

    # Persistência leve (não bloqueante)
    try:
        record_last_voice_url(uid, url, mimetype, len(raw), int(round(duration)))
    except Exception as e:
        logging.warning("(%s) Firestore vozClonada set warning: %s", req_id, e)

    logging.info(
        "[voz-upload] req_id=%s uid=%s mime=%s bytes=%d duration=%.2f bucket=%s path=%s access=%s",
        req_id, uid, mimetype, len(raw), duration, bucket, gcs_path, access
    )

    return jsonify({
        "ok": True,
        "status": "ok",
        "uid": uid,
        "vozUrl": url,
        "meta": {"mime": mimetype, "bytes": len(raw), "duration_sec": int(round(duration))}
    }), 200
