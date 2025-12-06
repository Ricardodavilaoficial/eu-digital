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
from typing import List, Dict, Any, Optional

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

# Storage helper oficial do projeto (acervo)
try:
    from services.storage_gcs import upload_acervo_bytes_and_get_url  # type: ignore
except Exception:  # pragma: no cover
    upload_acervo_bytes_and_get_url = None  # type: ignore

# Engine de consulta do acervo (mini-RAG)
try:
    from domain.acervo import query_acervo_for_uid  # type: ignore
except Exception:  # pragma: no cover
    query_acervo_for_uid = None  # type: ignore


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


def _get_uid() -> Optional[str]:
    """
    Recupera o uid do dono do acervo.

    Preferência:
      1) Authorization: Bearer <idToken Firebase> (mesma lógica do restante do projeto)
      2) X-Debug-UID, se ALLOW_DEBUG_UID=1 (para testes internos)
    """
    # 1) Bearer (usa o helper oficial, tentando as duas assinaturas possíveis)
    if get_uid_from_bearer is not None:
        auth_header = request.headers.get("Authorization", "")
        uid: Optional[str] = None

        try:
            # alguns módulos usam get_uid_from_bearer(request)
            uid = get_uid_from_bearer(request)  # type: ignore[arg-type]
        except TypeError:
            # outros usam get_uid_from_bearer("Bearer ...")
            try:
                uid = get_uid_from_bearer(auth_header)  # type: ignore[arg-type]
            except Exception:
                uid = None
        except Exception:
            uid = None

        if uid:
            return uid

    # 2) Debug header (modo laboratório)
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


def _total_limit_bytes() -> int:
    """
    Limite total de bytes do acervo por MEI.
    Usa ACERVO_MAX_TOTAL_BYTES ou padrão de 2 GB.
    """
    return _env_int("ACERVO_MAX_TOTAL_BYTES", 2 * 1024 * 1024 * 1024)


def _acervo_meta_doc(uid: str):
    """
    Documento de meta do acervo:
      profissionais/{uid}/acervoMeta/meta
    """
    if db is None:
        raise RuntimeError("Firestore (services.db) não está configurado.")
    return (
        db.collection("profissionais")
        .document(uid)
        .collection("acervoMeta")
        .document("meta")
    )


def _get_acervo_meta(uid: str) -> Dict[str, Any]:
    """
    Recupera (ou cria) o resumo de uso do acervo do MEI:
      - totalBytes: soma de tamanhoBytes de todos os itens
      - maxBytes: limite permitido (puxado da ENV, com upgrade automático)
    """
    from google.cloud import firestore  # type: ignore

    ref = _acervo_meta_doc(uid)
    snap = ref.get()
    limit_bytes = _total_limit_bytes()

    if not snap.exists:
        # cria meta inicial com o limite atual e re-lê do Firestore
        meta = {
            "uid": uid,
            "totalBytes": 0,
            "maxBytes": limit_bytes,
            "updatedEm": firestore.SERVER_TIMESTAMP,
        }
        ref.set(meta)
        snap = ref.get()

    data = snap.to_dict() or {}

    # Se o doc antigo tiver um maxBytes menor que o limite atual da ENV,
    # fazemos um "upgrade" para o novo limite (ex.: 100MB → 2GB).
    current_max = int(data.get("maxBytes", 0) or 0)
    if current_max < limit_bytes:
        try:
            ref.update({"maxBytes": limit_bytes})
            data["maxBytes"] = limit_bytes
        except Exception:
            # se der erro no update, ainda devolvemos algo razoável
            logging.exception("Falha ao atualizar maxBytes do acervoMeta; seguindo com valor antigo.")
            if current_max <= 0:
                data["maxBytes"] = limit_bytes
    else:
        # garante que exista chave maxBytes
        data.setdefault("maxBytes", limit_bytes)

    return data


def _update_acervo_meta(uid: str, delta_bytes: int) -> None:
    """
    Atualiza totalBytes do acervo do MEI com segurança de transação.
    delta_bytes pode ser positivo (upload) ou negativo (delete).
    """
    from google.cloud import firestore  # type: ignore

    ref = _acervo_meta_doc(uid)

    def _txn(transaction, ref=ref):
        snap = ref.get(transaction=transaction)
        base = snap.to_dict() or {
            "uid": uid,
            "totalBytes": 0,
            "maxBytes": _total_limit_bytes(),
        }
        total = int(base.get("totalBytes", 0)) + int(delta_bytes)
        if total < 0:
            total = 0
        base["totalBytes"] = total
        base["updatedEm"] = firestore.SERVER_TIMESTAMP
        transaction.set(ref, base)

    if db is None:
        logging.warning("Firestore não configurado ao atualizar meta do acervo.")
        return

    # usa o helper oficial de transação do cliente Firestore
    db.run_transaction(_txn)


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

        # inclui meta de quota na resposta
        meta = _get_acervo_meta(uid)

        return _no_store(jsonify({
            "items": itens,
            "meta": meta,
        })), 200
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

    if upload_acervo_bytes_and_get_url is None:
        return _no_store(jsonify({"error": "storage_not_configured"})), 500

    if "file" not in request.files:
        return _no_store(jsonify({"error": "missing_file"})), 400

    file = request.files["file"]
    if file.filename is None or file.filename.strip() == "":
        return _no_store(jsonify({"error": "empty_filename"})), 400

    # Limite de tamanho por arquivo (ex.: até 2 GB via ENV)
    max_bytes = _env_int("ACERVO_MAX_FILE_BYTES", 2 * 1024 * 1024 * 1024)
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > max_bytes:
        return _no_store(jsonify({
            "error": "file_too_large",
            "max_bytes": max_bytes,
            "size": size
        })), 413

    # Quota total do acervo (2 GB padrão, via _total_limit_bytes)
    try:
        meta = _get_acervo_meta(uid)
        total_bytes = int(meta.get("totalBytes", 0))
        max_bytes_total = int(meta.get("maxBytes", _total_limit_bytes()))
    except Exception as e:
        logging.exception("Erro ao ler meta do acervo")
        return _no_store(jsonify({"error": "meta_error", "details": str(e)})), 500

    if total_bytes + size > max_bytes_total:
        return _no_store(jsonify({
            "error": "quota_exceeded",
            "totalBytes": total_bytes,
            "maxBytes": max_bytes_total,
            "incomingBytes": size
        })), 409

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

        # caminho relativo dentro de acervo/original
        ext = ""
        if "." in file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
        rel_path = f"original/{acervo_id}"
        if ext:
            rel_path = f"{rel_path}.{ext}"

        # upload para GCS: helper específico de acervo
        public_url, bucket_name, gcs_path, access_mode = upload_acervo_bytes_and_get_url(
            uid,
            rel_path,
            raw_bytes,
            content_type,
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
            "storageOriginalPath": gcs_path,
            "storageOriginalUrl": public_url,
            "storageConsultaPath": None,
            "storageConsultaUrl": None,
            "resumoCurto": None,
            "ultimaIndexacao": None,
            "criadoEm": now,
            "atualizadoEm": now,
        }

        doc_ref.set(doc_data)

        # atualiza meta de quota (somatório de bytes do acervo)
        try:
            _update_acervo_meta(uid, size)
        except Exception:
            logging.exception("Falha ao atualizar meta do acervo (upload)")

        # reidrata do Firestore para remover Sentinels (SERVER_TIMESTAMP)
        try:
            snap = doc_ref.get()
            out = snap.to_dict() or {}
            out["id"] = acervo_id
        except Exception:
            logging.exception("Falha ao reidratar doc de acervo (upload); usando doc_data em memória")
            out = {**doc_data, "id": acervo_id}

        return _no_store(jsonify({"item": out})), 201

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

    if upload_acervo_bytes_and_get_url is None:
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
        raw_bytes = corpo.encode("utf-8")
    except Exception:
        return _no_store(jsonify({"error": "encode_error"})), 400

    size = len(raw_bytes)

    # Quota total do acervo (2 GB padrão, via _total_limit_bytes)
    try:
        meta = _get_acervo_meta(uid)
        total_bytes = int(meta.get("totalBytes", 0))
        max_bytes_total = int(meta.get("maxBytes", _total_limit_bytes()))
    except Exception as e:
        logging.exception("Erro ao ler meta do acervo (texto)")
        return _no_store(jsonify({"error": "meta_error", "details": str(e)})), 500

    if total_bytes + size > max_bytes_total:
        return _no_store(jsonify({
            "error": "quota_exceeded",
            "totalBytes": total_bytes,
            "maxBytes": max_bytes_total,
            "incomingBytes": size
        })), 409

    try:
        col_ref = _acervo_collection(uid)
        doc_ref = col_ref.document()
        acervo_id = doc_ref.id

        # caminho relativo da versão de consulta (.md)
        rel_path = f"consulta/{acervo_id}.md"

        public_url, bucket_name, gcs_path, access_mode = upload_acervo_bytes_and_get_url(
            uid,
            rel_path,
            raw_bytes,
            "text/markdown",
        )

        from google.cloud import firestore  # type: ignore

        now = firestore.SERVER_TIMESTAMP

        doc_data: Dict[str, Any] = {
            "titulo": titulo,
            "tipo": "texto",
            "tags": tags,
            "habilitado": habilitado,
            "prioridade": prioridade,
            "tamanhoBytes": size,
            "fonte": "texto_livre",
            "storageOriginalPath": None,  # aqui pode ficar só a consulta
            "storageOriginalUrl": None,
            "storageConsultaPath": gcs_path,
            "storageConsultaUrl": public_url,
            "resumoCurto": None,        # pode ser gerado depois, se quisermos
            "ultimaIndexacao": None,    # ex.: quando for para índice do Google
            "criadoEm": now,
            "atualizadoEm": now,
        }

        doc_ref.set(doc_data)

        # atualiza meta de quota
        try:
            _update_acervo_meta(uid, size)
        except Exception:
            logging.exception("Falha ao atualizar meta do acervo (texto)")

        # reidrata do Firestore para remover Sentinels (SERVER_TIMESTAMP)
        try:
            snap = doc_ref.get()
            out = snap.to_dict() or {}
            out["id"] = acervo_id
        except Exception:
            logging.exception("Falha ao reidratar doc de acervo (texto); usando doc_data em memória")
            out = {**doc_data, "id": acervo_id}

        return _no_store(jsonify({"item": out})), 201

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


@bp_acervo.route("/api/acervo/query", methods=["POST"])
def consultar_acervo():
    """
    Consulta o acervo do MEI usando o mini-RAG.

    Espera JSON:
      {
        "pergunta": "como explico o meu atendimento de barba?",
        "maxTokens": 120  // opcional
      }

    Resposta (v1, via domain.acervo.query_acervo_for_uid):
      {
        "answer": "...",
        "usedDocs": [ { "id": "...", "titulo": "...", ... } ],
        "reason": "ok" | "no_docs" | "no_relevant_docs" | "llm_error"
      }
    """
    uid = _get_uid()
    if not uid:
        return _no_store(jsonify({"error": "unauthenticated"})), 401

    if query_acervo_for_uid is None:
        # domínio ainda não plugado
        return _no_store(jsonify({"error": "rag_not_configured"})), 503

    data = request.get_json(silent=True) or {}
    pergunta = (data.get("pergunta") or data.get("question") or "").strip()
    if not pergunta:
        return _no_store(jsonify({
            "error": "missing_field",
            "field": "pergunta"
        })), 400

    try:
        max_tokens = int(data.get("maxTokens") or 120)
    except Exception:
        max_tokens = 120

    try:
        result = query_acervo_for_uid(
            uid=uid,
            pergunta=pergunta,
            max_tokens=max_tokens
        )
        return _no_store(jsonify(result)), 200
    except Exception as e:
        logging.exception("Erro ao consultar acervo (mini-RAG)")
        return _no_store(jsonify({"error": "internal_error", "details": str(e)})), 500
