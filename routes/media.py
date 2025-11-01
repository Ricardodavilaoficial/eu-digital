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

# Usamos o client do GCS centralizado no app
from services.gcs_handler import get_storage_client

media_bp = Blueprint("media_bp", __name__)

# Config e limites
_SANDBOX_UID = os.getenv("SANDBOX_UID", "demo_uid")
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

def _normalize_bucket(name: str) -> str:
    """
    Mantém o bucket exatamente como informado.
    Aceita *.firebasestorage.app ou *.appspot.com sem conversão.
    """
    return (name or "").strip()

def _resolve_bucket_from_env() -> str:
    """
    Resolve o bucket GCS a partir do ambiente, sem converter domínios.
      Ordem:
        1) STORAGE_GCS_BUCKET
        2) FIREBASE_STORAGE_BUCKET ou STORAGE_BUCKET
        3) FIREBASE_PROJECT_ID/GOOGLE_CLOUD_PROJECT -> <proj>.firebasestorage.app
    """
    b = (os.getenv("STORAGE_GCS_BUCKET") or "").strip()
    if b:
        return _normalize_bucket(b)
    b2 = (os.getenv("FIREBASE_STORAGE_BUCKET") or os.getenv("STORAGE_BUCKET") or "").strip()
    if b2:
        return _normalize_bucket(b2)
    proj = (os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    if proj:
        return f"{proj}.firebasestorage.app"
    raise RuntimeError("Bucket não configurado. Defina STORAGE_GCS_BUCKET ou FIREBASE_STORAGE_BUCKET/STORAGE_BUCKET ou FIREBASE_PROJECT_ID.")

def _safe_filename(name: str) -> str:
    # limpa tudo que não for [a-z0-9._-]
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "").strip())[:128]

def _infer_ext_from_content_type(ct: str) -> Optional[str]:
    ct = (ct or "").lower().strip()
    return _ALLOWED_MIME.get(ct)

@media_bp.route("/media/signed-url", methods=["POST"])
@auth_required
def create_signed_url():
    """
    Solicita uma dupla de URLs assinadas (V4):
      - uploadUrl (PUT) para o cliente enviar o arquivo
      - downloadUrl (GET) para leitura temporária após upload

    Body JSON aceito:
      {
        "contentType": "audio/mpeg",              # obrigatório e dentro da allowlist
        "filename": "voz_teste.mp3",              # opcional se "path" for enviado
        "path": "profissionais/<uid>/voz/...",    # opcional; se ausente, geramos um canônico em sandbox/
        "bucket": "<proj>.firebasestorage.app",   # opcional; usado literalmente, sem conversão de domínio
        "public": true                            # (ignorado aqui; upload assinado não precisa)
      }

    Resposta:
      { ok, uploadUrl, downloadUrl, path, bucket, expiresInSeconds, contentType }
    """
    try:
        user_uid = current_uid()
        if not user_uid:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        content_type = (data.get("contentType") or "").strip().lower()
        if content_type not in _ALLOWED_MIME:
            return jsonify({"ok": False, "error": "content_type_not_allowed"}), 400

        # Bucket: do body (pass-through) OU do ambiente (pass-through)
        requested_bucket = (data.get("bucket") or "").strip()
        if requested_bucket:
            bucket_name = _normalize_bucket(requested_bucket)
        else:
            bucket_name = _resolve_bucket_from_env()

        # Caminho:
        # - Se o cliente mandou "path", usamos como está (depois sanitizamos o nome final se quiser)
        # - Caso contrário, geramos um canônico em sandbox/<SANDBOX_UID>/<uid>/YYYY/MM/DD/<uuid>.<ext>
        provided_path = (data.get("path") or "").strip()
        filename = _safe_filename(data.get("filename") or "")
        ext = _infer_ext_from_content_type(content_type)
        if not ext:
            return jsonify({"ok": False, "error": "cannot_map_extension"}), 400

        if provided_path:
            # Garantir que termina com a extensão correta (se não terminar, acrescenta)
            # e evitar path vazio.
            p = provided_path
            if not re.search(r"\.[A-Za-z0-9]{1,8}$", p):
                p = f"{p.rstrip('/')}/{uuid.uuid4().hex}{ext}"
            path = p.lstrip("/")  # path do GCS não deve começar com '/'
        else:
            now = datetime.utcnow()
            key = f"{uuid.uuid4().hex}{ext}"
            if filename and not filename.lower().endswith(ext):
                # Se mandaram filename sem extensão coerente, usamos key com ext certa.
                key_name = key
            else:
                key_name = key
            path = f"sandbox/{_SANDBOX_UID}/{user_uid}/{now:%Y/%m/%d}/{key_name}"

        client = get_storage_client()
        if client is None:
            return jsonify({"ok": False, "error": "storage_client_unavailable"}), 500

        bucket = client.bucket(bucket_name)
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
            "bucket": bucket_name,
            "expiresInSeconds": _EXPIRES_MINUTES * 60,
            "contentType": content_type,
        }
        return jsonify(out), 200

    except Exception as e:
        # Evite vazar detalhes demais em produção; aqui mantemos mensagem útil para diagnóstico.
        return jsonify({"ok": False, "error": f"internal_error: {e}"}), 500