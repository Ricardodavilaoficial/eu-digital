# routes/cupons.py
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta  # pode ser útil em respostas/validações
# usamos os serviços centralizados, que já lidam com credenciais/env
from services.db import db
from services.coupons import criar_cupom, find_cupom_by_codigo, validar_consumir_cupom

cupons_bp = Blueprint("cupons_bp", __name__)

@cupons_bp.route("/ativar-cupom", methods=["POST"])
def ativar_cupom():
    dados = request.get_json(silent=True) or {}
    codigo = (dados.get("codigo") or "").strip()
    uid = (dados.get("uid") or "").strip()

    if not codigo or not uid:
        return jsonify({"erro": "Código do cupom e UID são obrigatórios"}), 400

    try:
        # Usa helpers centralizados
        cupom = find_cupom_by_codigo(codigo)
        ok, msg, plano = validar_consumir_cupom(cupom, uid)
        if not ok:
            return jsonify({"erro": msg}), 400

        # Atualiza plano do profissional via services.db
        prof_ref = db.collection("profissionais").document(uid)
        try:
            prof_ref.update({"plan": plano or "start"})
        except Exception:
            # fallback: cria doc se não existir
            prof_ref.set({"plan": plano or "start"}, merge=True)

        return jsonify({"mensagem": "Plano ativado com sucesso pelo cupom!"}), 200
    except Exception as e:
        return jsonify({"erro": "falha_ativar_cupom", "detalhe": str(e)[:300]}), 500


@cupons_bp.route("/gerar-cupom", methods=["POST"])
def gerar_cupom():
    dados = request.get_json(silent=True) or {}

    # normaliza nomes vindos do front
    dias_validade = int(dados.get("diasValidade") or dados.get("validadeDias") or 3)
    prefixo = (dados.get("prefixo") or "").strip() or None

    body = {"diasValidade": dias_validade}
    if prefixo:
        body["prefixo"] = prefixo

    try:
        # Usa o serviço central — mesmo formato do /admin/cupons
        cupom = criar_cupom(body, criado_por="admin-cupons-public")
        return jsonify(cupom), 201
    except Exception as e:
        return jsonify({"erro": "falha_gerar_cupom", "detalhe": str(e)[:300]}), 500
