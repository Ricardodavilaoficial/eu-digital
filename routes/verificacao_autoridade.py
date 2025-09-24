# -*- coding: utf-8 -*-
"""
Blueprint: Verificação de Autoridade (Fase 1)
- Mantém rotas antigas:
    GET  /conta/status
    POST /verificacao/autoridade         (JSON: {metodo, dados})
    GET  /verificacao/convite/<token>
- Adiciona rotas usadas pelo frontend:
    GET  /api/verificacao/autoridade/status
    POST /api/verificacao/autoridade/upload  (multipart FormData)
    OPTIONS preflight para as duas acima
"""
from __future__ import annotations

import os, time, uuid
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, request, make_response
from werkzeug.exceptions import BadRequest, TooManyRequests

# Auth (suave): tenta Firebase ID Token; se falhar, usa header de debug
try:
    from services.auth import get_verified_uid_from_request
except Exception:
    get_verified_uid_from_request = lambda: None  # fallback seguro

from models.user_status import (
    StatusConta, get_user_status, set_user_status, log_autorizacao,
    get_user_meta, set_user_meta
)

verificacao_bp = Blueprint("verificacao_autoridade", __name__)

# -------------------- Config & helpers --------------------
_ALLOWED_ORIGIN = os.getenv("FRONTEND_BASE", "").rstrip("/") or "*"
_RATE_BUCKET: dict[str, list[float]] = {}
_RATE_LIMIT = int(os.getenv("VERIF_AUT_MAX_PER_MINUTE", "20"))
_RATE_WINDOW = 60  # seconds

def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = _ALLOWED_ORIGIN
    resp.headers["Vary"] = "Origin"
    return resp

def _preflight_allow(methods: str = "GET, POST, OPTIONS", headers: str = "Authorization, Content-Type"):
    resp = make_response("", 204)
    resp.headers["Access-Control-Allow-Origin"] = _ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Methods"] = methods
    resp.headers["Access-Control-Allow-Headers"] = headers
    resp.headers["Access-Control-Max-Age"] = "600"
    resp.headers["Vary"] = "Origin"
    return resp

def _rate_guard(key: str):
    now = time.time()
    bucket = _RATE_BUCKET.setdefault(key, [])
    # purge antigos
    while bucket and now - bucket[0] > _RATE_WINDOW:
        bucket.pop(0)
    if len(bucket) >= _RATE_LIMIT:
        raise TooManyRequests("Limite de tentativas atingido, tente mais tarde.")
    bucket.append(now)

def _now_utc():
    return datetime.now(timezone.utc)

def _in_90_days(dt: datetime):
    return dt + timedelta(days=90)

def _flag_on() -> bool:
    return os.getenv("VERIFICACAO_AUTORIDADE", "false").lower() == "true"

def _current_uid() -> str:
    # 1) tenta Firebase ID Token (se vier Authorization: Bearer ...)
    uid = get_verified_uid_from_request() or None
    if uid:
        return uid
    # 2) fallback debug (dev tools / curl)
    return request.headers.get("X-Debug-User", "guest")

# -------------------- Rotas antigas (mantidas) --------------------
@verificacao_bp.get("/conta/status")
def conta_status_legacy():
    """
    GET /conta/status -> { statusConta, expiracao?, motivos: [], flagAtiva }
    Mantida para compatibilidade.
    """
    uid = _current_uid()
    status, exp = get_user_status(uid)
    meta = get_user_meta(uid)
    motivos = meta.get("motivos", [])
    payload = {
        "statusConta": status.value,
        "expiracao": exp.isoformat() if exp else None,
        "motivos": motivos,
        "flagAtiva": _flag_on()
    }
    resp = make_response(jsonify(payload), 200)
    return _cors(_no_store(resp))

@verificacao_bp.post("/verificacao/autoridade")
def post_verificacao_autoridade():
    """
    POST /verificacao/autoridade -> { metodo, resultado, statusConta, expiracao?, detalhes }
    Body (JSON): { "metodo": "declaracao"|"upload"|"convite", "dados": {...} }
    Mantido para compatibilidade.
    """
    uid = _current_uid()
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "0.0.0.0")
    _rate_guard(f"{uid}:{ip}")

    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise BadRequest("JSON inválido.")

    metodo = (body or {}).get("metodo")
    dados = (body or {}).get("dados", {}) or {}

    if metodo not in ("declaracao", "upload", "convite"):
        raise BadRequest("Campo 'metodo' obrigatório: declaracao|upload|convite.")

    now = _now_utc()
    status_atual, _exp = get_user_status(uid)

    if metodo == "declaracao":
        novo_status = StatusConta.verified_basic
        exp = _in_90_days(now)
        set_user_status(uid, novo_status, exp)
        log_autorizacao(uid, {
            "ts": now.isoformat(),
            "acao": "declaracao_aprovada",
            "expiraEm": exp.isoformat(),
            "nota": dados.get("texto", "")
        })
        set_user_meta(uid, {"motivos": []})  # limpa motivos
        resp = make_response(jsonify({
            "metodo": metodo,
            "resultado": "aprovado",
            "statusConta": novo_status.value,
            "expiracao": exp.isoformat(),
            "detalhes": {"janelaDias": 90}
        }), 200)
        return _cors(_no_store(resp))

    if metodo == "upload":
        tipo = (dados.get("tipo") or "").strip().lower()
        nome_arquivo = dados.get("nomeArquivo")
        if not tipo:
            raise BadRequest("Campo 'dados.tipo' é obrigatório para upload.")

        if tipo == "cracha":
            # reprovação automática v1
            log_autorizacao(uid, {
                "ts": now.isoformat(),
                "acao": "upload_reprovado",
                "motivo": "cracha_nao_aceito_v1",
                "arquivo": nome_arquivo
            })
            meta = get_user_meta(uid)
            motivos = meta.get("motivos", [])
            motivos.append("Upload de 'crachá' não é aceito na política v1.")
            set_user_meta(uid, {"motivos": motivos})
            resp = make_response(jsonify({
                "metodo": metodo,
                "resultado": "reprovado",
                "statusConta": status_atual.value,
                "detalhes": {"motivo": "cracha_nao_aceito_v1"}
            }), 200)
            return _cors(_no_store(resp))

        # outros tipos: pendente
        token_pendente = str(uuid.uuid4())
        meta = get_user_meta(uid)
        pendentes = meta.get("pendentes", [])
        pendentes.append({
            "token": token_pendente,
            "tipo": tipo,
            "arquivo": nome_arquivo,
            "ts": now.isoformat(),
            "situacao": "pendente_review"
        })
        meta["pendentes"] = pendentes
        set_user_meta(uid, meta)
        log_autorizacao(uid, {
            "ts": now.isoformat(),
            "acao": "upload_pendente",
            "tipo": tipo,
            "arquivo": nome_arquivo,
            "token": token_pendente
        })
        resp = make_response(jsonify({
            "metodo": metodo,
            "resultado": "pendente",
            "statusConta": status_atual.value,
            "detalhes": {"token": token_pendente}
        }), 202)
        return _cors(_no_store(resp))

    if metodo == "convite":
        token = str(uuid.uuid4())
        meta = get_user_meta(uid)
        convites = meta.get("convites", [])
        convites.append({
            "token": token,
            "socioNome": dados.get("socioNome"),
            "contato": dados.get("contato"),
            "ts": now.isoformat(),
            "status": "pendente"
        })
        meta["convites"] = convites
        set_user_meta(uid, meta)
        log_autorizacao(uid, {
            "ts": now.isoformat(),
            "acao": "convite_gerado",
            "token": token,
            "socioNome": dados.get("socioNome"),
            "contato": dados.get("contato")
        })
        resp = make_response(jsonify({
            "metodo": metodo,
            "resultado": "pendente",
            "statusConta": status_atual.value,
            "detalhes": {"token": token, "urlAceiteStub": f"/verificacao/convite/{token}"}
        }), 202)
        return _cors(_no_store(resp))

    raise BadRequest("Requisição inválida.")

@verificacao_bp.get("/verificacao/convite/<token>")
def get_convite_stub(token: str):
    """
    GET /verificacao/convite/:token -> v1 stub (sempre pendente)
    """
    uid = _current_uid()
    now = _now_utc()
    log_autorizacao(uid, {
        "ts": now.isoformat(),
        "acao": "convite_stub_visita",
        "token": token
    })
    resp = make_response(jsonify({
        "token": token,
        "status": "pendente",
        "mensagem": "Fluxo de aceite do convite será implementado na versão 1.1."
    }), 200)
    return _cors(_no_store(resp))

# -------------------- Novas rotas /api usadas pelo frontend --------------------
@verificacao_bp.route("/api/verificacao/autoridade/status", methods=["OPTIONS"])
def preflight_status():
    return _preflight_allow(methods="GET, OPTIONS")

@verificacao_bp.route("/api/verificacao/autoridade/upload", methods=["OPTIONS"])
def preflight_upload():
    # aceita multipart
    return _preflight_allow(methods="POST, OPTIONS", headers="Authorization, Content-Type")

@verificacao_bp.get("/api/verificacao/autoridade/status")
def api_status():
    """
    GET /api/verificacao/autoridade/status
    -> { needs_docs, pending_review, stripe_enabled, reason }
    """
    uid = _current_uid()
    # Reusa a mesma régua simples: se tem verified_basic e não expirou => stripe_enabled
    status, exp = get_user_status(uid)
    now = _now_utc()
    valid = (exp is not None and exp > now) and (status == StatusConta.verified_basic)
    # pendências
    meta = get_user_meta(uid)
    has_pend = bool(meta.get("pendentes"))
    out = {
        "needs_docs": not valid and not has_pend,
        "pending_review": has_pend,
        "stripe_enabled": bool(valid),
        "reason": "ok" if valid else ("pending_review" if has_pend else "needs_docs"),
    }
    resp = make_response(jsonify(out), 200)
    return _cors(_no_store(resp))

@verificacao_bp.post("/api/verificacao/autoridade/upload")
def api_upload():
    """
    POST /api/verificacao/autoridade/upload (multipart)
    Aceita múltiplos arquivos: files[].
    Política v1:
      - Se nome/tipo indicar 'cracha' => reprova automática
      - Senão, cria pendência para revisão manual
    """
    uid = _current_uid()
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "0.0.0.0")
    _rate_guard(f"{uid}:{ip}")

    # Deve ser multipart/form-data
    if not request.files:
        raise BadRequest("Envie arquivos em multipart/form-data (campo files[]).")

    now = _now_utc()
    meta = get_user_meta(uid)
    pendentes = meta.get("pendentes", [])
    motivos = meta.get("motivos", [])

    files = request.files.getlist("files[]") or request.files.getlist("files") or []
    if not files:
        raise BadRequest("Nenhum arquivo recebido (use files[]).")

    # Processa arquivos (sem persistir binário na v1; apenas log/meta)
    for f in files:
        nome = f.filename or "sem_nome"
        nome_lower = nome.lower()
        if "crach" in nome_lower:  # crachá / cracha
            log_autorizacao(uid, {
                "ts": now.isoformat(),
                "acao": "upload_reprovado",
                "motivo": "cracha_nao_aceito_v1",
                "arquivo": nome
            })
            motivos.append("Upload de 'crachá' não é aceito na política v1.")
            # não cria pendente para crachá
            continue

        token_pendente = str(uuid.uuid4())
        pendentes.append({
            "token": token_pendente,
            "tipo": "doc",
            "arquivo": nome,
            "ts": now.isoformat(),
            "situacao": "pendente_review"
        })
        log_autorizacao(uid, {
            "ts": now.isoformat(),
            "acao": "upload_pendente",
            "tipo": "doc",
            "arquivo": nome,
            "token": token_pendente
        })

    meta["pendentes"] = pendentes
    meta["motivos"] = motivos
    set_user_meta(uid, meta)

    # resposta:
    # - se houve qualquer reprovação de crachá, mantemos 202 (processado) e informamos
    any_rejected = any("crachá" in m.lower() or "cracha" in m.lower() for m in motivos)
    body = {
        "ok": True,
        "pendentes": len(pendentes),
        "rejeitados": 1 if any_rejected else 0
    }
    resp = make_response(jsonify(body), 202)
    return _cors(_no_store(resp))
