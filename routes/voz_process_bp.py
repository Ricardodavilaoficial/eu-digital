
from flask import Blueprint, request, jsonify
import os, time, hashlib
from google.cloud import firestore

voz_process_bp = Blueprint("voz_process_bp", __name__)

def _get_fs_client():
    return firestore.Client()

@voz_process_bp.route("/api/voz/process", methods=["POST", "OPTIONS"])
def api_voz_process():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    uid = request.args.get("uid") or data.get("uid")
    if not uid:
        return jsonify({"ok": False, "error": "missing_uid"}), 400

    fs = _get_fs_client()
    doc_ref = fs.collection("profissionais").document(uid)
    snap = doc_ref.get()
    if not snap.exists:
        return jsonify({"ok": False, "error": "uid_not_found"}), 404

    data_now = snap.to_dict() or {}
    voz_info = data_now.get("vozClonada") or {}
    arquivo_url = voz_info.get("arquivoUrl") or data_now.get("arquivoUrl")

    if not arquivo_url:
        voice_id = None
        status = "pendente"
    else:
        h = hashlib.sha1((arquivo_url + str(time.time())).encode("utf-8")).hexdigest()[:16]
        voice_id = f"voice_{h}"
        status = "ready"

    new_vox = {
        "status": status,
        "provider": voz_info.get("provider") or "elevenlabs",
        "arquivoUrl": arquivo_url,
        "voiceId": voice_id,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    doc_ref.set({"vozClonada": new_vox}, merge=True)

    return jsonify({"ok": True, "status": status, "voiceId": voice_id})
