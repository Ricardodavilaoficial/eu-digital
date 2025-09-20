# -*- coding: utf-8 -*-
"""
Blueprint: Verificação de Autoridade (Fase 1)
- Opt-in por flag de ambiente VERIFICACAO_AUTORIDADE
- Política v1 (automática):
  * declaracao  -> verified_basic (90 dias)
  * upload tipo="cracha" -> reprova automática (mantém guest_unverified; loga motivo)
  * upload tipo!=cracha -> pendente (mantém guest_unverified; loga pendente + metadados)
  * convite -> pendente (gera token; aceite implementado na v1.1)
- Armazena logs e estado em memória (stub) para PREVIEW.
  Trocar por Firestore/DB no rollout v1.1+.
"""
from __future__ import annotations
import os, time, uuid
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, TooManyRequests

from models.user_status import (
    StatusConta, get_user_status, set_user_status, log_autorizacao,
    get_user_meta, set_user_meta
)

verificacao_bp = Blueprint("verificacao_autoridade", __name__)

# ------ Anti-abuso (bem simples; trocar por Redis/Firestore em produção) ------
_RATE_BUCKET = {}
_RATE_LIMIT = int(os.getenv("VERIF_AUT_MAX_PER_MINUTE", "20"))
_RATE_WINDOW = 60  # seconds

def _rate_guard(key: str):
    now = time.time()
    bucket = _RATE_BUCKET.setdefault(key, [])
    # remove antigos
    while bucket and now - bucket[0] > _RATE_WINDOW:
        bucket.pop(0)
    if len(bucket) >= _RATE_LIMIT:
        raise TooManyRequests("Limite de tentativas atingido, tente mais tarde.")
    bucket.append(now)

# ------ Helpers ------
def _user_id_from_headers() -> str:
    # Para PREVIEW: permite identificar usuário pelo cabeçalho (ex.: curl)
    # Em produção, trocar por auth real (session/JWT).
    return request.headers.get("X-Debug-User", "guest")

def _flag_on() -> bool:
    return os.getenv("VERIFICACAO_AUTORIDADE", "false").lower() == "true"

def _now_utc():
    return datetime.now(timezone.utc)

def _in_90_days(dt: datetime):
    return dt + timedelta(days=90)

# ------ Rotas ------

@verificacao_bp.get("/conta/status")
def conta_status():
    """
    GET /conta/status -> { statusConta, expiracao?, motivos: [] }
    """
    uid = _user_id_from_headers()
    status, exp = get_user_status(uid)
    meta = get_user_meta(uid)
    motivos = meta.get("motivos", [])
    payload = {
        "statusConta": status.value,
        "expiracao": exp.isoformat() if exp else None,
        "motivos": motivos,
        "flagAtiva": _flag_on()
    }
    return jsonify(payload), 200

@verificacao_bp.post("/verificacao/autoridade")
def post_verificacao_autoridade():
    """
    POST /verificacao/autoridade -> { metodo, resultado, statusConta, expiracao?, detalhes }
    Body: { "metodo": "declaracao"|"upload"|"convite", "dados": {...} }
    """
    uid = _user_id_from_headers()
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
        return jsonify({
            "metodo": metodo,
            "resultado": "aprovado",
            "statusConta": novo_status.value,
            "expiracao": exp.isoformat(),
            "detalhes": {"janelaDias": 90}
        }), 200

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
            # adiciona motivo e mantém status como está (provavelmente guest_unverified)
            meta = get_user_meta(uid)
            motivos = meta.get("motivos", [])
            motivos.append("Upload de 'crachá' não é aceito na política v1.")
            set_user_meta(uid, {"motivos": motivos})
            return jsonify({
                "metodo": metodo,
                "resultado": "reprovado",
                "statusConta": status_atual.value,
                "detalhes": {"motivo": "cracha_nao_aceito_v1"}
            }), 200

        # outros tipos: pendente
        token_pendente = str(uuid.uuid4())
        pendentes = get_user_meta(uid).get("pendentes", [])
        pendentes.append({
            "token": token_pendente,
            "tipo": tipo,
            "arquivo": nome_arquivo,
            "ts": now.isoformat(),
            "situacao": "pendente_review"
        })
        meta = get_user_meta(uid)
        meta["pendentes"] = pendentes
        set_user_meta(uid, meta)
        log_autorizacao(uid, {
            "ts": now.isoformat(),
            "acao": "upload_pendente",
            "tipo": tipo,
            "arquivo": nome_arquivo,
            "token": token_pendente
        })
        return jsonify({
            "metodo": metodo,
            "resultado": "pendente",
            "statusConta": status_atual.value,
            "detalhes": {"token": token_pendente}
        }), 202

    if metodo == "convite":
        # gera token de convite (aceite futuro v1.1)
        token = str(uuid.uuid4())
        convites = get_user_meta(uid).get("convites", [])
        convites.append({
            "token": token,
            "socioNome": dados.get("socioNome"),
            "contato": dados.get("contato"),
            "ts": now.isoformat(),
            "status": "pendente"
        })
        meta = get_user_meta(uid)
        meta["convites"] = convites
        set_user_meta(uid, meta)
        log_autorizacao(uid, {
            "ts": now.isoformat(),
            "acao": "convite_gerado",
            "token": token,
            "socioNome": dados.get("socioNome"),
            "contato": dados.get("contato")
        })
        return jsonify({
            "metodo": metodo,
            "resultado": "pendente",
            "statusConta": status_atual.value,
            "detalhes": {"token": token, "urlAceiteStub": f"/verificacao/convite/{token}"}
        }), 202

    # fallback
    raise BadRequest("Requisição inválida.")

@verificacao_bp.get("/verificacao/convite/<token>")
def get_convite_stub(token: str):
    """
    GET /verificacao/convite/:token -> v1 stub (sempre pendente)
    """
    uid = _user_id_from_headers()
    now = _now_utc()
    log_autorizacao(uid, {
        "ts": now.isoformat(),
        "acao": "convite_stub_visita",
        "token": token
    })
    return jsonify({
        "token": token,
        "status": "pendente",
        "mensagem": "Fluxo de aceite do convite será implementado na versão 1.1."
    }), 200
