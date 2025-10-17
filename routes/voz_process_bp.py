# routes/voz_process_bp.py
import os, io, time, json, logging
import requests
from flask import Blueprint, request, jsonify
from google.cloud import storage, firestore

bp = Blueprint("voz_process_bp", __name__)  # se já existe, reuse o existente

# ENVs esperadas
ELEVEN = os.environ.get("ELEVENLABS_API_KEY")
BUCKET = os.environ.get("STORAGE_BUCKET", "mei-robo-prod.appspot.com")
SIGNED_SECS = int(os.environ.get("SIGNED_URL_EXPIRES_SECONDS", "900"))

db = firestore.Client()
gcs = storage.Client()
bucket = gcs.bucket(BUCKET)

def _signed_url(object_path: str) -> str:
    blob = bucket.blob(object_path)
    if not blob.exists():
        raise FileNotFoundError(f"Objeto nao encontrado: gs://{BUCKET}/{object_path}")
    return blob.generate_signed_url(
        expiration=SIGNED_SECS, method="GET", version="v4",
        response_disposition=f'inline; filename="{os.path.basename(object_path)}"'
    )

def _eleven_add_voice(name: str, audio_bytes: bytes) -> str:
    files = [("files", ("sample.mp3", io.BytesIO(audio_bytes), "audio/mpeg"))]
    resp = requests.post(
        "https://api.elevenlabs.io/v1/voices/add",
        headers={"xi-api-key": ELEVEN},
        data={"name": name},
        files=files,
        timeout=180,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"ElevenLabs add failed: {resp.status_code} {resp.text}")
    data = resp.json()
    vid = data.get("voice_id")
    if not vid:
        raise RuntimeError(f"ElevenLabs no voice_id: {data}")
    return vid

def _save_ready(uid: str, voice_id: str, url: str):
    doc = {
        "vozClonada": {
            "status": "ready",
            "provider": "elevenlabs",
            "voiceId": voice_id,
            "arquivoUrl": url,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
    }
    db.collection("configuracao").document(uid).set(doc, merge=True)

def _save_pending(uid: str, url: str | None):
    doc = {
        "vozClonada": {
            "status": "pendente",
            "provider": "elevenlabs",
            "arquivoUrl": url,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
    }
    db.collection("configuracao").document(uid).set(doc, merge=True)

@bp.route("/api/voz/process", methods=["POST"])
def process_voz():
    """
    Payload aceito:
    {
      "uid": "...",
      "object": "voz/<uid>/voz_teste.mp3",
      "provider": "elevenlabs",
      "contentType": "audio/mpeg",
      "arquivoUrl": "...", "url": "...",
      "mode": "sync", "force": true
    }
    Querystring também aceita: uid, object, arquivoUrl/url, mode, sync, force.
    """
    if not ELEVEN:
        return jsonify({"ok": False, "error": "ELEVENLABS_API_KEY ausente"}), 500

    # Merge body + query
    body = request.get_json(silent=True) or {}
    qs = request.args or {}
    uid = body.get("uid") or qs.get("uid")
    obj = body.get("object") or qs.get("object")
    prov = (body.get("provider") or qs.get("provider") or "elevenlabs").lower()
    link = body.get("arquivoUrl") or body.get("url") or qs.get("arquivoUrl") or qs.get("url")
    mode = (body.get("mode") or qs.get("mode") or "").lower()
    sync = qs.get("sync", body.get("sync", "false"))
    force = qs.get("force", body.get("force", "false"))

    is_sync = str(sync).lower() in ("1","true","yes","y")
    is_force = str(force).lower() in ("1","true","yes","y")

    # sanity
    if not uid or not obj or prov != "elevenlabs":
        return jsonify({"ok": True, "status": "pendente", "voiceId": None})

    # Se não for sync explícito, comporta como antes (marca pendente e sai)
    if not is_sync or not is_force:
        _save_pending(uid, link)
        return jsonify({"ok": True, "status": "pendente", "voiceId": None})

    # --- SYNC de verdade ---
    try:
        # 1) resolver URL de áudio
        if not link:
            link = _signed_url(obj)

        # 2) baixar bytes
        r = requests.get(link, timeout=180)
        if r.status_code != 200:
            raise RuntimeError(f"Falha ao ler audio: {r.status_code}")

        # 3) chamar ElevenLabs
        name = f"cliente-{uid}-{int(time.time())}"
        voice_id = _eleven_add_voice(name, r.content)

        # 4) persistir pronto
        _save_ready(uid, voice_id, link)

        return jsonify({"ok": True, "status": "ready", "voiceId": voice_id})

    except FileNotFoundError as e:
        logging.exception("Objeto nao encontrado")
        _save_pending(uid, link)
        return jsonify({"ok": False, "status": "pendente", "error": str(e)}), 404
    except Exception as e:
        logging.exception("Erro no sync da voz")
        _save_pending(uid, link)
        return jsonify({"ok": False, "status": "pendente", "error": str(e)}), 502
