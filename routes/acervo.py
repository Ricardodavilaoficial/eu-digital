# routes/acervo.py
# Módulo: Acervo do MEI Robô
#
# Endpoints principais:
# - GET  /api/acervo                → lista itens do acervo do MEI logado
# - POST /api/acervo/upload         → cria item a partir de upload de arquivo
# - POST /api/acervo/texto          → cria item a partir de texto livre (.md direto)
# - PATCH /api/acervo/<acervo_id>   → atualiza metadados (titulo, tags, habilitado, prioridade, resumoCurto)
#
# Notas importantes:
# - Não processa PDF/áudio/vídeo aqui ainda; só registra e guarda original.
# - Versão "consulta" (.md) será responsabilidade de outro serviço/job (a combinar).
# - Respeita limite básico de tamanho por arquivo via ENV (ACERVO_MAX_FILE_BYTES).
# - Acervo SEMPRE isolado por uid (profissionais/{uid}/acervo).

from flask import Blueprint, request, jsonify
import os
import logging
from typing import List, Dict, Any

bp_acervo = Blueprint("bp_acervo", __name__)

# Firestore
try:
    from services.db import db  # type: ignore
except Exception:  # pragma: no cover
    db = None  # type: ignore

# Auth helper (mesmo padrão do projeto)
try:
    from services.auth import get_uid_from_bearer  # type: ignore
except Exception:  # pragma: no cover
    get_uid_from_bearer = None  # type: ignore

# Storage helper oficial do projeto
try:
    from services.storage_gcs import upload_bytes_and_get_url  # type: ignore
except Exception:  # pragma: no cover
    upload_bytes_and_get_url = None  # type: ignore


# -------- helpers gerais --------

def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _allow_debug_uid() -> bool:
    return os.getenv("ALLOW_DEBUG_UID", "0").strip() == "1"


def _get_uid() -> str | None:
    """
    Recupera o uid do dono do acervo.
    Preferência:
      1) Authorization: Bearer <idToken Firebase>
      2) X-Debug-UID, se ALLOW_DEBUG_UID=1 (para testes internos)
    """
    # 1) Bearer
    if get_uid_from_bearer is not None:
        uid = get_uid_from_bearer(request.headers.get("Authorization", ""))
        if uid:
            return uid

    # 2) Debug header
    if _allow_debug_uid():
        debug_uid = request.headers.get("X-Debug-UID") or request.args.get("debug_uid")
        if debug_uid:
            return debug_uid

    return None


def _acervo_collection(uid: str):
    """
    Retorna a referência da coleção profissionais/{uid}/acervo.
    """
    if db is None:
        raise RuntimeError("Firestore (services.db) não está configurado.")
    return db.collection("profissionais").document(uid).collection("acervo")


def _parse_tags(raw: str | None) -> List[str]:
    if not raw:
        return []
    # aceita vírgula ou ponto-e-vírgula
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _safe_bool(val, default: bool) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("1", "true", "sim", "yes", "y", "on"):
            return True
        if v in ("0", "false", "nao", "não", "no", "off"):
            return False
    return default


# -------- endpoints --------

@bp_acervo.route("/api/acervo", methods=["GET"])
def listar_acervo():
    """
    Lista itens de acervo do MEI logado.
    Filtro v1: todos; no futuro podemos filtrar por tag, tipo, habilitado etc.
    """
    uid = _get_uid()
    if not uid:
        return _no_store(jsonify({"error": "unauthenticated"})), 401

    try:
        col_ref = _acervo_collection(uid)
        # limite simples para não explodir em uma conta maluca;
        # depois dá pra paginar.
        docs = col_ref.order_by("criadoEm").limit(100).stream()
        itens: List[Dict[str, Any]] = []
        for d in docs:
            data = d.to_dict() or {}
            data["id"] = d.id
            # sanity mínima: alguns campos default
            data.setdefault("habilitado", True)
            data.setdefault("prioridade", 1)
            data.setdefault("tags", [])
            itens.append(data)

        return _no_store(jsonify({"items": itens})), 200
    except Exception as e:
        logging.exception("Erro ao listar acervo")
        return _no_store(jsonify({"error": "internal_error", "details": str(e)})), 500


@bp_acervo.route("/api/acervo/upload", methods=["POST"])
def criar_acervo_upload():
    """
    Cria item de acervo a partir de upload de arquivo.
    Espera multipart/form-data:
      - file: arquivo
      - titulo: opcional (fallback para nome do arquivo)
      - tags: opcional ("tag1, tag2; tag3")
      - prioridade: opcional (int)
      - habilitado: opcional (bool-like)
    """
    uid = _get_uid()
    if not uid:
        return _no_store(jsonify({"error": "unauthenticated"})), 401

    if upload_bytes_and_get_url is None:
        return _no_store(jsonify({"error": "storage_not_configured"})), 500

    if "file" not in request.files:
        return _no_store(jsonify({"error": "missing_file"})), 400

    file = request.files["file"]
    if file.filename is None or file.filename.strip() == "":
        return _no_store(jsonify({"error": "empty_filename"})), 400

    # Limite de tamanho por arquivo (ex.: 50 MB) para não explodir.
    max_bytes = _env_int("ACERVO_MAX_FILE_BYTES", 50 * 1024 * 1024)
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > max_bytes:
        return _no_store(jsonify({
            "error": "file_too_large",
            "max_bytes": max_bytes,
            "size": size
        })), 413

    raw_bytes = file.read()
    content_type = file.mimetype or "application/octet-stream"

    # título e tags
    titulo = (request.form.get("titulo") or file.filename).strip()
    tags = _parse_tags(request.form.get("tags"))
    prioridade_raw = request.form.get("prioridade")
    try:
        prioridade = int(prioridade_raw) if prioridade_raw is not None else 1
    except Exception:
        prioridade = 1

    habilitado = _safe_bool(request.form.get("habilitado"), True)

    try:
        col_ref = _acervo_collection(uid)
        doc_ref = col_ref.document()  # id automático
        acervo_id = doc_ref.id

        # destino no bucket, seguindo padrão combinado
        ext = ""
        if "." in file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
        dest_path = f"profissionais/{uid}/acervo/original/{acervo_id}"
        if ext:
            dest_path = f"{dest_path}.{ext}"

        # upload para GCS: helper já existente
        public_url = upload_bytes_and_get_url(
            raw_bytes,
            dest_path,
            content_type=content_type
        )

        from google.cloud import firestore  # type: ignore

        now = firestore.SERVER_TIMESTAMP  # manter padrão do projeto

        doc_data: Dict[str, Any] = {
            "titulo": titulo,
            "tipo": ext or "arquivo",
            "tags": tags,
            "habilitado": habilitado,
            "prioridade": prioridade,
            "tamanhoBytes": size,
            "fonte": "upload",
            "storageOriginalPath": dest_path,
            "storageOriginalUrl": public_url,
            "storageConsultaPath": None,
            "resumoCurto": None,
            "ultimaIndexacao": None,
            "criadoEm": now,
            "atualizadoEm": now,
        }

        doc_ref.set(doc_data)

        # resposta com o doc básico
        doc_data["id"] = acervo_id
        return _no_store(jsonify({"item": doc_data})), 201

    except Exception as e:
        logging.exception("Erro ao criar item de acervo via upload")
        return _no_store(jsonify({"error": "internal_error", "details": str(e)})), 500


@bp_acervo.route("/api/acervo/texto", methods=["POST"])
def criar_acervo_texto():
    """
    Cria item de acervo a partir de texto livre.
    Espera JSON:
      {
        "titulo": "Como faço manutenção de portões",
        "corpo":  "Texto em markdown ou texto puro",
        "tags":   ["portões", "manutenção"],
        "prioridade": 1,
        "habilitado": true
      }
    Na v1, já grava o corpo diretamente em acervo/consulta/{id}.md
    """
    uid = _get_uid()
    if not uid:
        return _no_store(jsonify({"error": "unauthenticated"})), 401

    if upload_bytes_and_get_url is None:
        return _no_store(jsonify({"error": "storage_not_configured"})), 500

    data = request.get_json(silent=True) or {}
    titulo = (data.get("titulo") or "").strip()
    corpo = (data.get("corpo") or "").strip()

    if not titulo:
        return _no_store(jsonify({"error": "missing_field", "field": "titulo"})), 400
    if not corpo:
        return _no_store(jsonify({"error": "missing_field", "field": "corpo"})), 400

    tags_raw = data.get("tags")
    if isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    else:
        tags = _parse_tags(str(tags_raw)) if tags_raw is not None else []

    prioridade_raw = data.get("prioridade")
    try:
        prioridade = int(prioridade_raw) if prioridade_raw is not None else 1
    except Exception:
        prioridade = 1

    habilitado = _safe_bool(data.get("habilitado"), True)

    try:
        col_ref = _acervo_collection(uid)
        doc_ref = col_ref.document()
        acervo_id = doc_ref.id

        # destino da versão de consulta (.md)
        dest_path = f"profissionais/{uid}/acervo/consulta/{acervo_id}.md"
        raw_bytes = corpo.encode("utf-8")

        public_url = upload_bytes_and_get_url(
            raw_bytes,
            dest_path,
            content_type="text/markdown"
        )

        from google.cloud import firestore  # type: ignore

        now = firestore.SERVER_TIMESTAMP

        doc_data: Dict[str, Any] = {
            "titulo": titulo,
            "tipo": "texto",
            "tags": tags,
            "habilitado": habilitado,
            "prioridade": prioridade,
            "tamanhoBytes": len(raw_bytes),
            "fonte": "texto_livre",
            "storageOriginalPath": None,  # aqui pode ficar só a consulta
            "storageOriginalUrl": None,
            "storageConsultaPath": dest_path,
            "storageConsultaUrl": public_url,
            "resumoCurto": None,        # pode ser gerado depois, se quisermos
            "ultimaIndexacao": None,    # ex.: quando for para índice do Google
            "criadoEm": now,
            "atualizadoEm": now,
        }

        doc_ref.set(doc_data)

        doc_data["id"] = acervo_id
        return _no_store(jsonify({"item": doc_data})), 201

    except Exception as e:
        logging.exception("Erro ao criar item de acervo via texto")
        return _no_store(jsonify({"error": "internal_error", "details": str(e)})), 500


@bp_acervo.route("/api/acervo/<acervo_id>", methods=["PATCH"])
def atualizar_acervo(acervo_id: str):
    """
    Atualiza metadados de um item do acervo:
      - titulo
      - tags
      - habilitado
      - prioridade
      - resumoCurto
    Não mexe em arquivos no Storage (original/consulta) nesta rota.
    """
    uid = _get_uid()
    if not uid:
        return _no_store(jsonify({"error": "unauthenticated"})), 401

    data = request.get_json(silent=True) or {}
    if not data:
        return _no_store(jsonify({"error": "empty_body"})), 400

    try:
        col_ref = _acervo_collection(uid)
        doc_ref = col_ref.document(acervo_id)
        snap = doc_ref.get()
        if not snap.exists:
            return _no_store(jsonify({"error": "not_found"})), 404

        updates: Dict[str, Any] = {}

        if "titulo" in data:
            titulo = (data.get("titulo") or "").strip()
            if not titulo:
                return _no_store(jsonify({"error": "invalid_titulo"})), 400
            updates["titulo"] = titulo

        if "tags" in data:
            tags_val = data.get("tags")
            if isinstance(tags_val, list):
                tags = [str(t).strip() for t in tags_val if str(t).strip()]
            else:
                tags = _parse_tags(str(tags_val)) if tags_val is not None else []
            updates["tags"] = tags

        if "habilitado" in data:
            updates["habilitado"] = _safe_bool(data.get("habilitado"), True)

        if "prioridade" in data:
            try:
                updates["prioridade"] = int(data.get("prioridade"))
            except Exception:
                return _no_store(jsonify({"error": "invalid_prioridade"})), 400

        if "resumoCurto" in data:
            resumo = data.get("resumoCurto")
            if resumo is not None:
                resumo = str(resumo).strip()
            updates["resumoCurto"] = resumo

        if not updates:
            return _no_store(jsonify({"error": "nothing_to_update"})), 400

        from google.cloud import firestore  # type: ignore
        updates["atualizadoEm"] = firestore.SERVER_TIMESTAMP

        doc_ref.update(updates)

        # devolve o doc reidratado
        snap = doc_ref.get()
        out = snap.to_dict() or {}
        out["id"] = snap.id

        return _no_store(jsonify({"item": out})), 200

    except Exception as e:
        logging.exception("Erro ao atualizar item de acervo")
        return _no_store(jsonify({"error": "internal_error", "details": str(e)})), 500
