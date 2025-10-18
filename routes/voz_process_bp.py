# routes/voz_process_bp.py
# -*- coding: utf-8 -*-
import os
import io
import time
import json
import logging
from typing import Optional

import requests
from flask import Blueprint, request, jsonify
from google.cloud import storage, firestore

# -----------------------------------------------------------------------------
# Blueprint: exportamos com o NOME que o app.py espera importar
# -----------------------------------------------------------------------------
voz_process_bp = Blueprint("voz_process_bp", __name__)  # <- nome exportado

# -----------------------------------------------------------------------------
# ENVs e defaults
# -----------------------------------------------------------------------------
# Chave ElevenLabs
ELEVEN = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")

# Nome do bucket (prioriza FIREBASE_STORAGE_BUCKET; depois STORAGE_BUCKET)
BUCKET = (
    os.environ.get("FIREBASE_STORAGE_BUCKET")
    or os.environ.get("STORAGE_BUCKET")
    or "mei-robo-prod.firebasestorage.app"  # fallback seguro p/ projetos modernos
)

# Projeto (opcional)
GCP_PROJECT = os.environ.get("FIREBASE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")

# Expiração de URL assinada
SIGNED_SECS = int(os.environ.get("SIGNED_URL_EXPIRES_SECONDS", "900"))

# -----------------------------------------------------------------------------
# Clients
# -----------------------------------------------------------------------------
# Se a SA estiver configurada via GOOGLE_APPLICATION_CREDENTIALS ou FIREBASE_SERVICE_ACCOUNT_JSON,
# o Client() já pega as credenciais via ADC.
db = firestore.Client(project=GCP_PROJECT) if GCP_PROJECT else firestore.Client()
gcs = storage.Client(project=GCP_PROJECT) if GCP_PROJECT else storage.Client()
bucket = gcs.bucket(BUCKET)

logging.getLogger().setLevel(logging.INFO)
logging.info(f"[voz_process] Using bucket: {BUCKET} | project={GCP_PROJECT or 'auto'}")

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _normalize_object(body: dict, qs: dict) -> Optional[str]:
    """
    Aceita várias chaves e normaliza o caminho do objeto dentro do bucket:
      - body['object']            (preferido)
      - body['object_path']
      - body['gcsPath']          (pode vir com prefixo gs://<bucket>/... -> recorta)
      - qs['object'], qs['object_path'], qs['gcsPath']
    """
    obj = body.get("object") or qs.get("object")
    if not obj:
        obj = body.get("object_path") or qs.get("object_path")
    if not obj:
        obj = body.get("gcsPath") or qs.get("gcsPath")

    if not obj:
        return None

    # Se veio "gs://<bucket>/profissionais/.../voz.mp3", recorta o prefixo
    if obj.startswith("gs://"):
        try:
            # gs://bucket-name/path/to/file
            _, rest = obj.split("gs://", 1)
            parts = rest.split("/", 1)
            if len(parts) == 2:
                _bucket_from_gcs, path = parts
                return path
        except Exception:
            pass

    # Remove uma eventual / inicial
    return obj[1:] if obj.startswith("/") else obj


def _normalize_content_type(body: dict, qs: dict) -> Optional[str]:
    return body.get("contentType") or body.get("content_type") or qs.get("contentType") or qs.get("content_type")


def _is_truthy(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "y", "on")


def _signed_url(object_path: str, content_type: Optional[str] = None) -> str:
    blob = bucket.blob(object_path)
    if not blob.exists():
        raise FileNotFoundError(f"Objeto nao encontrado: gs://{BUCKET}/{object_path}")

    # response_disposition para “inline; filename=...”
    params = {
        "expiration": SIGNED_SECS,
        "method": "GET",
        "version": "v4",
        "response_disposition": f'inline; filename="{os.path.basename(object_path)}"',
    }
    # Se quiser forçar o content-type de resposta
    if content_type:
        params["response_type"] = content_type  # type: ignore

    return blob.generate_signed_url(**params)  # type: ignore


def _eleven_add_voice(name: str, audio_bytes: bytes) -> str:
    files = [("files", ("sample.mp3", io.BytesIO(audio_bytes), "audio/mpeg"))]
    headers = {"xi-api-key": ELEVEN}
    resp = requests.post(
        "https://api.elevenlabs.io/v1/voices/add",
        headers=headers,
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


def _save_pending(uid: str, url: Optional[str]):
    doc = {
        "vozClonada": {
            "status": "pendente",
            "provider": "elevenlabs",
            "arquivoUrl": url,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
    }
    db.collection("configuracao").document(uid).set(doc, merge=True)


# -----------------------------------------------------------------------------
# Rota principal
# -----------------------------------------------------------------------------
@voz_process_bp.route("/api/voz/process", methods=["POST"])
def process_voz():
    """
    Payloads aceitos (mistos):
    {
      "uid": "...",
      "provider": "elevenlabs",
      "object": "profissionais/<uid>/voz/arquivo.mp3",     # preferido
      "object_path": "...",                                # também aceito
      "gcsPath": "gs://bucket/path/arquivo.mp3",           # também aceito
      "contentType": "audio/mpeg",                         # ou content_type
      "mode": "sync",                                      # OU
      "sync": true,                                        # qualquer um vale
      "force": true,
      "arquivoUrl": "https://..."                          # opcional (se já tiver link)
    }
    Ou via querystring com os mesmos nomes.
    """
    # 0) Chave da ElevenLabs
    if not ELEVEN:
        logging.error("ELEVENLABS_API_KEY ausente")
        return jsonify({"ok": False, "error": "ELEVENLABS_API_KEY ausente"}), 500

    # 1) Body + Query
    body = request.get_json(silent=True) or {}
    qs = request.args or {}

    uid = body.get("uid") or qs.get("uid")
    prov = (body.get("provider") or qs.get("provider") or "elevenlabs").lower()
    content_type = _normalize_content_type(body, qs) or "audio/mpeg"

    # aceita "mode=sync" OU "sync=true"
    mode = (body.get("mode") or qs.get("mode") or "").lower()
    sync_flag = body.get("sync", qs.get("sync", False))
    is_sync = (mode == "sync") or _is_truthy(sync_flag)

    force_flag = body.get("force", qs.get("force", False))
    is_force = _is_truthy(force_flag)

    obj = _normalize_object(body, qs)

    link = (
        body.get("arquivoUrl")
        or body.get("url")
        or qs.get("arquivoUrl")
        or qs.get("url")
    )

    logging.info(
        json.dumps(
            {
                "uid": uid,
                "prov": prov,
                "bucket": BUCKET,
                "object": obj,
                "is_sync": is_sync,
                "is_force": is_force,
                "has_link": bool(link),
            }
        )
    )

    # 2) Sanity mínima
    if prov != "elevenlabs" or not uid or not obj:
        # comportamento legado: não erro, apenas mantem pendente
        _save_pending(uid or "unknown", link)
        return jsonify({"ok": True, "status": "pendente", "voiceId": None})

    # Sem sync/force explícitos? Mantém pendente (comportamento anterior)
    if not is_sync or not is_force:
        _save_pending(uid, link)
        return jsonify({"ok": True, "status": "pendente", "voiceId": None})

    # 3) Execução síncrona
    try:
        # 3.1) Link: usa o fornecido ou gera URL assinada
        if not link:
            link = _signed_url(obj, content_type)

        # 3.2) Baixar bytes do áudio
        r = requests.get(link, timeout=300)
        if r.status_code != 200:
            raise RuntimeError(f"Falha ao ler audio: {r.status_code}")
        audio_bytes = r.content
        if not audio_bytes or len(audio_bytes) < 1024:
            raise RuntimeError("Audio vazio/pequeno")

        # 3.3) Chamar ElevenLabs
        name = f"cliente-{uid}-{int(time.time())}"
        voice_id = _eleven_add_voice(name, audio_bytes)

        # 3.4) Persistir pronto
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
