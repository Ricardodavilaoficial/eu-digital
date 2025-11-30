# routes/servicos_foto.py
# Gera Signed URL V4 específico para FOTO de serviço
# Rota:
#   POST /api/servicos/foto
#
# Fluxo:
#  - front manda: { servicoId, contentType }
#  - backend valida UID + conteúdo
#  - gera path: profissionais/<uid>/produtosEServicos/<servicoId>/foto.<ext>
#  - devolve uploadUrl (PUT) + downloadUrl (GET)
#
# Firestore continua sendo atualizado pelo frontend (precos.html).

from __future__ import annotations

import os
import re
from datetime import timedelta

from flask import Blueprint, request, jsonify

from services.auth import auth_required, current_uid
from services.gcs_handler import get_storage_client
from routes.media import _resolve_bucket_from_env  # reaproveita a resolução de bucket

servicos_foto_bp = Blueprint("servicos_foto_bp", __name__)

# Mesma lógica de expiração das outras signed URLs
_EXPIRES_MINUTES = int(os.getenv("SIGNED_URL_EXPIRES_MIN", "15"))

# Só aceitamos imagem aqui (foto por serviço)
_IMAGE_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _safe_id(s: str) -> str:
    """Sanitiza o ID do serviço para evitar path estranho."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", (s or "").strip())[:64]


@servicos_foto_bp.route("/api/servicos/foto", methods=["POST"])
@auth_required
def servico_foto_signed_url():
    """
    Cria uma dupla de URLs assinadas para foto de serviço:
      - uploadUrl (PUT)
      - downloadUrl (GET)

    Body esperado (JSON):
      {
        "servicoId": "<id do documento em produtosEServicos>",
        "contentType": "image/jpeg" | "image/png" | "image/webp"
      }

    Resposta:
      {
        "ok": true,
        "uploadUrl": "...",
        "downloadUrl": "...",
        "path": "profissionais/<uid>/produtosEServicos/<servicoId>/foto.jpg",
        "bucket": "<bucket em uso>",
        "expiresInSeconds": 900,
        "contentType": "image/jpeg"
      }
    """
    uid = current_uid()
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    servico_id = _safe_id(data.get("servicoId") or data.get("id") or "")
    content_type = (data.get("contentType") or "").strip().lower()

    if not servico_id:
        return jsonify({"ok": False, "error": "missing_servico_id"}), 400

    if content_type not in _IMAGE_MIME:
        return jsonify({"ok": False, "error": "content_type_not_allowed"}), 400

    ext = _IMAGE_MIME[content_type]

    # Bucket canônico (respeita STORAGE_BUCKET / FIREBASE_* como no media.py)
    bucket_name = _resolve_bucket_from_env()
    client = get_storage_client()
    if client is None:
        return jsonify({"ok": False, "error": "storage_client_unavailable"}), 500

    bucket = client.bucket(bucket_name)

    # Um arquivo por serviço: foto.jpg / foto.png / foto.webp
    path = f"profissionais/{uid}/produtosEServicos/{servico_id}/foto{ext}"
    blob = bucket.blob(path)

    # URL de upload (PUT) — V4
    upload_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=_EXPIRES_MINUTES),
        method="PUT",
        content_type=content_type,
    )

    # URL de download (GET) — V4
    download_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=_EXPIRES_MINUTES),
        method="GET",
    )

    return jsonify({
        "ok": True,
        "uploadUrl": upload_url,
        "downloadUrl": download_url,
        "path": path,
        "bucket": bucket_name,
        "expiresInSeconds": _EXPIRES_MINUTES * 60,
        "contentType": content_type,
    }), 200
