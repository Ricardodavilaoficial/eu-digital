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
import logging
from datetime import timedelta

from flask import Blueprint, request, jsonify
from firebase_admin import firestore
from services.db import db  # mesmo db usado em outras rotas

from services.auth import auth_required, current_uid
from services.gcs_handler import get_storage_client
from routes.media import _resolve_bucket_from_env  # reaproveita a resolução de bucket

servicos_foto_bp = Blueprint("servicos_foto_bp", __name__)

logger = logging.getLogger("servicos_foto")

_EXPIRES_MINUTES = int(os.getenv("SIGNED_URL_EXPIRES_MIN", "15"))

_IMAGE_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

def _safe_id(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", (s or "").strip())[:64]

@servicos_foto_bp.route("/api/servicos/foto", methods=["POST"])
@auth_required
def servico_foto_signed_url():
    uid = current_uid()
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # 1) Tenta ler JSON normalmente
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}

    # 2) Se vier como form-data ou x-www-form-urlencoded, pega request.form
    if not data:
        try:
            if request.form:
                data = request.form.to_dict()
        except Exception:
            data = {}

    # 3) Fallback: também olha a query-string (?servicoId=...)
    qs = request.args or {}

    # Aceita vários jeitos de vir do front: servicoId, id, slug, nomeSlug, nome
    raw_id = (
        data.get("servicoId")
        or data.get("id")
        or data.get("slug")
        or data.get("nomeSlug")
        or data.get("nome")
        or qs.get("servicoId")
        or qs.get("id")
        or qs.get("slug")
        or ""
    )

    servico_id = _safe_id(raw_id)
    content_type = (data.get("contentType") or qs.get("contentType") or "").strip().lower()

    if not servico_id:
        # Log só pra nós, pra entender se vier outro formato
        try:
            print(
                "[servicos_foto] missing_servico_id "
                "data_keys=", list(data.keys()),
                "qs_keys=", list(qs.keys()),
                "raw_id=", raw_id,
                flush=True,
            )
        except Exception:
            pass
        return jsonify({"ok": False, "error": "missing_servico_id"}), 400

    if content_type not in _IMAGE_MIME:
        return jsonify({"ok": False, "error": "content_type_not_allowed"}), 400

    ext = _IMAGE_MIME[content_type]

    bucket_name = _resolve_bucket_from_env()
    client = get_storage_client()
    if client is None:
        return jsonify({"ok": False, "error": "storage_client_unavailable"}), 500

    bucket = client.bucket(bucket_name)
    path = f"profissionais/{uid}/produtosEServicos/{servico_id}/foto{ext}"
    blob = bucket.blob(path)

    upload_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=_EXPIRES_MINUTES),
        method="PUT",
        content_type=content_type,
    )

    download_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=_EXPIRES_MINUTES),
        method="GET",
    )

    # Atualiza o documento do serviço com a URL da foto
    try:
        svc_ref = (
            db.collection("profissionais")
            .document(uid)
            .collection("produtosEServicos")
            .document(servico_id)
        )

        svc_ref.set(
            {
                "fotoUrl": download_url,
                "fotoUpdatedAt": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        logger.info(
            "[servicos_foto] fotoUrl atualizada uid=%s servicoId=%s",
            uid,
            servico_id,
        )
    except Exception as e:
        logger.warning(
            "[servicos_foto] falha ao gravar fotoUrl no serviço uid=%s servicoId=%s err=%r",
            uid,
            servico_id,
            e,
        )

    return jsonify({
        "ok": True,
        "uploadUrl": upload_url,
        "downloadUrl": download_url,
        "fotoUrl": download_url,
        "path": path,
        "bucket": bucket_name,
        "expiresInSeconds": _EXPIRES_MINUTES * 60,
        "contentType": content_type,
    }), 200


