# routes/cupons.py — geração (somente admin) e ativação de cupom (legado + alias moderno)
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, g

# Regras de segurança / auth
from services.auth import admin_required, auth_required

# Camada de domínio p/ cupons
from services.coupons import (
    criar_cupom,
    find_cupom_by_codigo,
    validar_consumir_cupom,
)

# Firestore lazy via wrapper do projeto
from services.db import db

cupons_bp = Blueprint("cupons_bp", __name__)


# --------------------------------------------------------------------
# PRE-FLIGHT (OPTIONS) — evita 405 em CORS para front-ends modernos
# --------------------------------------------------------------------
@cupons_bp.route("/gerar-cupom", methods=["OPTIONS"])
def _preflight_gerar():
    return ("", 204)


@cupons_bp.route("/ativar-cupom", methods=["OPTIONS"])
def _preflight_ativar_cupom():
    return ("", 204)


# Alias moderno usado pela UI atual (/api/cupons/ativar)
@cupons_bp.route("/ativar", methods=["OPTIONS"])
def _preflight_ativar_alias():
    return ("", 204)


# --------------------------------------------------------------------
# GERAR CUPOM — SOMENTE ADMIN
# Mantém rota legado "/gerar-cupom" porém protegida por admin_required.
# /admin/cupons também existe em routes/core_api.py e é admin_required.
# --------------------------------------------------------------------
@cupons_bp.route("/gerar-cupom", methods=["POST"])
@admin_required
def gerar_cupom_admin():
    """
    Gera um cupom. Apenas administradores.

    Body aceito (campos flexíveis):
      - diasValidade | validadeDias : soma N dias (gera expiraEm ISO)
      - prefixo (opcional)
      - tipo, valor, usosMax, escopo, uidDestino, expiraEm (ISO) etc.

    Retorna: 201 + JSON do cupom criado.
    """
    body = request.get_json(silent=True) or {}

    # Normalizações leves de entrada
    try:
        dias_raw = body.get("diasValidade") or body.get("validadeDias") or 0
        dias = int(dias_raw) if str(dias_raw).strip() != "" else 0
    except Exception:
        dias = 0

    if dias > 0 and not body.get("expiraEm"):
        body["expiraEm"] = (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()

    # Identidade do admin criador (g.user setado pelo admin_required)
    criado_por = getattr(getattr(g, "user", None), "uid", None) or os.getenv("DEV_FAKE_UID") or "admin-cupons"

    try:
        cupom = criar_cupom(body, criado_por=criado_por)
        return jsonify(cupom), 201
    except Exception:
        # Erro discreto (não vaza detalhes sensíveis)
        return jsonify({"erro": "Falha ao criar cupom"}), 500


# --------------------------------------------------------------------
# ATIVAR CUPOM — LEGADO (exige codigo + uid no body)
# Mantém compat com clientes que ainda chamam "/ativar-cupom".
# Obs: fluxo novo também existe em /licencas/ativar-cupom (core_api).
# --------------------------------------------------------------------
@cupons_bp.route("/ativar-cupom", methods=["POST"])
def ativar_cupom_legacy():
    """
    Ativa o plano do profissional a partir de um cupom (legado).
    Body: { "codigo": "ABC-123", "uid": "<uid_profissional>" }
    """
    data = request.get_json(silent=True) or {}
    codigo = (data.get("codigo") or "").strip()
    uid = (data.get("uid") or "").strip()

    if not codigo or not uid:
        return jsonify({"erro": "Código do cupom e UID são obrigatórios"}), 400

    return _ativar_cupom_impl(codigo=codigo, uid=uid)


# --------------------------------------------------------------------
# ATIVAR CUPOM — ALIAS MODERNO (/api/cupons/ativar)
# Usa o UID do token (g.user.uid). Body: { "codigo": "ABC-123" }
# --------------------------------------------------------------------
@cupons_bp.route("/ativar", methods=["POST"])
@auth_required
def ativar_cupom_alias_moderno():
    data = request.get_json(silent=True) or {}
    codigo = (data.get("codigo") or "").strip()

    if not codigo:
        return jsonify({"erro": "Código do cupom é obrigatório"}), 400

    uid = getattr(getattr(g, "user", None), "uid", "") or ""
    if not uid:
        return jsonify({"erro": "Não autenticado"}), 401

    return _ativar_cupom_impl(codigo=codigo, uid=uid)


# --------------------------------------------------------------------
# Implementação comum (domínio) — evita duplicação de lógica
# --------------------------------------------------------------------
def _ativar_cupom_impl(*, codigo: str, uid: str):
    # Busca e valida/consome cupom via camada de domínio
    try:
        cupom = find_cupom_by_codigo(codigo)
        ok, msg, plano = validar_consumir_cupom(cupom, uid)
    except Exception:
        return jsonify({"erro": "Falha ao validar cupom"}), 500

    if not ok:
        # msg vem padronizada da camada de domínio (ex.: "Cupom expirado", "Cupom já utilizado", etc.)
        return jsonify({"erro": msg}), 400

    # Atualiza plano do profissional com merge seguro
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        prof_ref = db.collection("profissionais").document(uid)
        prof_ref.set(
            {
                "plan": plano or "start",
                "licenca": {
                    "origem": "cupom",
                    "codigo": codigo,
                    "activatedAt": now_iso,
                },
                "updatedAt": now_iso,
            },
            merge=True,
        )
    except Exception:
        return jsonify({"erro": "Falha ao aplicar plano"}), 500

    return jsonify({"mensagem": "Plano ativado com sucesso pelo cupom!", "plano": (plano or "start")}), 200
