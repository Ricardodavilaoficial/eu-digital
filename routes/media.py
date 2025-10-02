# routes/media.py
# Blueprint: geração de Signed URL v4 (upload/download) em sandbox seguro
# Rotas:
#   POST /media/signed-url
#
# Requer auth (ID Token Firebase). Perspectiva v1.0 (Render/Flask).
from __future__ import annotations

import os
import re
import uuid
from datetime import timedelta, datetime
from typing import Optional

from flask import Blueprint, request, jsonify
from services.auth import auth_required, current_uid

# Usaremos o client do gcs_handler para manter coerência com o restante do app
from services.gcs_handler import get_storage_client

media_bp = Blueprint("media_bp", __name__)

# Config e limites
_SANDBOX_UID = os.getenv("SANDBOX_UID", "demo_uid")
_BUCKET_NAME = os.getenv("GCS_BUCKET", "eu-digital-ricardo")
_EXPIRES_MINUTES = int(os.getenv("SIGNED_URL_EXPIRES_MIN", "15"))

# MIME allowlist básica (pode expandir depois)
_ALLOWED_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
}

def _safe_filename(name: str) -> str:
    # limpa tudo que não for [a-z0-9._-]
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "").strip())[:128]

@media_bp.route("/media/signed-url", methods=["POST"])
@auth_required
def create_signed_url():
    """
    Solicita uma dupla de URLs assinadas:
      - uploadUrl (PUT) para o cliente enviar o arquivo
      - downloadUrl (GET) para leitura temporária após upload
    Body JSON esperado (parcial):
      { "contentType": "image/jpeg", "filename": "foto.jpg" }
    Resposta: { ok, uploadUrl, downloadUrl, path, expiresInSeconds }
    """
    try:
        user_uid = current_uid()
        if not user_uid:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        content_type = (data.get("contentType") or "").strip().lower()
        filename = _safe_filename(data.get("filename") or "")

        if content_type not in _ALLOWED_MIME:
            return jsonify({"ok": False, "error": "content_type_not_allowed"}), 400

        # Extensão por MIME (ignora extensão enviada pelo cliente)
        ext = _ALLOWED_MIME[content_type]
        # Caminho canônico: sandbox/<SANDBOX_UID>/<uid>/<YYYY>/<MM>/<DD>/<uuid>.<ext>
        now = datetime.utcnow()
        key = f"{uuid.uuid4().hex}{ext}"
        path = f"sandbox/{_SANDBOX_UID}/{user_uid}/{now:%Y/%m/%d}/{key}"

        client = get_storage_client()
        if client is None:
            return jsonify({"ok": False, "error": "storage_client_unavailable"}), 500
        bucket = client.bucket(_BUCKET_NAME)
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

        out = {
            "ok": True,
            "uploadUrl": upload_url,
            "downloadUrl": download_url,
            "path": path,
            "bucket": _BUCKET_NAME,
            "expiresInSeconds": _EXPIRES_MINUTES * 60,
            "contentType": content_type,
        }
        return jsonify(out), 200
    except Exception as e:
        return jsonify({"ok": False, "error": f"internal_error: {e}"}), 500
