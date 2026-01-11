# routes/servicos_foto.py
# Gera Signed URL V4 específico para FOTO de serviço
# Rota:
#   POST /api/servicos/foto
#
# Fluxo:
#  - front manda: multipart/form-data com:
#       - file        → arquivo da foto (obrigatório)
#       - servicoId   → id do doc em produtosEServicos (obrigatório)
#       - contentType → MIME type (image/jpeg, image/png...) (opcional, mas recomendado)
#  - backend valida UID + conteúdo
#  - gera path CANÔNICO:
#       profissionais/<uid>/produtosEServicos/<servicoId>/foto.<ext>
#  - faz upload para o bucket configurado em STORAGE_BUCKET / STORAGE_GCS_BUCKET
#  - salva fotoPath + fotoUrl (legado) no Firestore
#  - devolve JSON com:
#       { ok: true, fotoPath, fotoUrl }
#
# Observação importante:
#  - O /media/signed-url usa o MESMO bucket e o MESMO path (fotoPath),
#    então o NoSuchKey some assim que o objeto existir nesse caminho.

from __future__ import annotations

import os
from datetime import timedelta, datetime

from flask import Blueprint, request, jsonify
from services.storage_quota import reserve_bytes, adjust_bytes, QuotaExceeded
from firebase_admin import firestore  # Firestore Admin

from services.auth import auth_required, current_uid
from services.gcs_handler import get_storage_client
from routes.media import _resolve_bucket_from_env  # reaproveita a resolução de bucket

servicos_foto_bp = Blueprint("servicos_foto_bp", __name__)

# Mesma lógica de expiração das outras signed URLs (minutos)
_EXPIRES_MINUTES = int(os.getenv("SIGNED_URL_EXPIRES_MIN", "15"))

# Só aceitamos imagem aqui (foto por serviço)
_IMAGE_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _sanitize_content_type(ct: str | None) -> str:
    ct = (ct or "").strip().lower()
    # Aceita só image/*; se não bater, força image/jpeg
    if not ct.startswith("image/"):
        return "image/jpeg"
    return ct


def _ext_for_content_type(ct: str) -> str:
    return _IMAGE_MIME.get(ct, ".jpg")


@servicos_foto_bp.route("/api/servicos/foto", methods=["POST"])
@auth_required
def upload_foto_servico():
    """
    Upload de foto de serviço para GCS + atualização do Firestore.
    """
    uid = current_uid()
    if not uid:
        return jsonify({"ok": False, "error": "UID ausente na sessão"}), 401

    # ---- Validar multipart ----
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Arquivo (file) não enviado"}), 400

    file = request.files["file"]
    servico_id = request.form.get("servicoId") or request.form.get("servico_id")
    content_type_raw = request.form.get("contentType") or file.mimetype

    if not servico_id:
        return jsonify({"ok": False, "error": "servicoId é obrigatório"}), 400

    if not file.filename:
        return jsonify({"ok": False, "error": "Arquivo sem nome"}), 400

    # Blindagem básica de tamanho (2 MB, alinhado com o front)
    max_bytes = 2 * 1024 * 1024
    file.stream.seek(0, 2)  # vai para o fim
    size = file.stream.tell()
    file.stream.seek(0)
    if size > max_bytes:
        return jsonify({"ok": False, "error": "Arquivo muito grande (máx. 2 MB)."}), 400

    # ---- Content-Type + extensão ----
    content_type = _sanitize_content_type(content_type_raw)
    ext = _ext_for_content_type(content_type)

    # Caminho CANÔNICO (deve bater com o que o front espera em fotoPath)
    # Ex.: profissionais/<uid>/produtosEServicos/<servicoId>/foto.jpg
    object_path = f"profissionais/{uid}/produtosEServicos/{servico_id}/foto{ext}"

    # ---- Upload para o bucket correto ----
    bucket_name = _resolve_bucket_from_env()
    client = get_storage_client()
    bucket = client.bucket(bucket_name)


    blob = bucket.blob(object_path)

    # ---- QUOTA (best-effort) ----
    # Overwrite no mesmo path: reserva apenas o aumento (new_size - old_size)
    old_size = 0
    try:
        if blob.exists(client):
            blob.reload()
            old_size = int(blob.size or 0)
    except Exception:
        old_size = 0

    new_size = 0
    try:
        file.stream.seek(0, 2)
        new_size = int(file.stream.tell() or 0)
        file.stream.seek(0)
    except Exception:
        new_size = 0

    reserved = 0
    delta_est = int(new_size) - int(old_size)
    if delta_est > 0:
        try:
            reserve_bytes(uid, delta_est, category="servicos_foto")
            reserved = delta_est
        except QuotaExceeded as qe:
            return jsonify(qe.to_dict()), 409

    try:
        blob.cache_control = "private, max-age=0, no-transform"
        blob.upload_from_file(file.stream, content_type=content_type)
        blob.patch()
    except Exception:
        # rollback da reserva (best-effort)
        try:
            if reserved:
                adjust_bytes(uid, -int(reserved), category="servicos_foto")
        except Exception:
            pass
        return jsonify({"ok": False, "error": "upload_failed"}), 500

    # Reconcilia delta real (se diferir do reservado)
    try:
        blob.reload()
        real_new = int(blob.size or 0)
        real_delta = int(real_new) - int(old_size)
        if reserved != real_delta:
            adjust_bytes(uid, int(real_delta) - int(reserved), category="servicos_foto")
    except Exception:
        pass

    # ---- Gerar Signed URL de leitura (conveniência) ----
    expires = timedelta(minutes=_EXPIRES_MINUTES)
    foto_url = blob.generate_signed_url(
        version="v4",
        expiration=expires,
        method="GET",
    )

    # ---- Atualizar Firestore: fotoPath + fotoUrl (legado) ----
    db = firestore.client()
    doc_ref = (
        db.collection("profissionais")
        .document(uid)
        .collection("produtosEServicos")
        .document(servico_id)
    )

    now = datetime.utcnow()

    doc_ref.set(
        {
            "fotoPath": object_path,   # <- NOVO CAMPO CANÔNICO
            "fotoUrl": foto_url,       # legado/apoio — front novo usa fotoPath
            "fotoUpdatedAt": now.isoformat() + "Z",
        },
        merge=True,
    )

    # Log simplificado (ajuda nos testes)
    print(
        f"[servicos_foto] foto atualizada uid={uid} servicoId={servico_id} "
        f"bucket={bucket_name} path={object_path}",
        flush=True,
    )

    return (
        jsonify(
            {
                "ok": True,
                "fotoPath": object_path,
                "fotoUrl": foto_url,
                "contentType": content_type,
            }
        ),
        200,
    )

