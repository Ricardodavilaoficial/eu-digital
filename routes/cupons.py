from flask import Blueprint, request, jsonify
from google.cloud import firestore
from datetime import datetime

cupons_bp = Blueprint("cupons_bp", __name__)

@cupons_bp.route("/ativar-cupom", methods=["POST"])
def ativar_cupom():
    dados = request.json
    codigo = dados.get("codigo")  # ex: TESTE-MEIROBO-25
    uid = dados.get("uid")        # UID do profissional (usuário autenticado)

    if not codigo or not uid:
        return jsonify({"erro": "Código do cupom e UID são obrigatórios"}), 400

    db = firestore.Client()
    
    # 1. Buscar o cupom no Firestore
    cupom_ref = db.collection("cuponsAtivacao").document(codigo)
    cupom_doc = cupom_ref.get()

    if not cupom_doc.exists:
        return jsonify({"erro": "Cupom não encontrado"}), 404

    cupom = cupom_doc.to_dict()

    if cupom.get("used"):
        return jsonify({"erro": "Cupom já foi usado"}), 400

    # 2. Atualizar o plano do profissional
    prof_ref = db.collection("profissionais").document(uid)
    prof_ref.update({
        "plan": cupom.get("planActivated", "start")
    })

    # 3. Atualizar o status do cupom como usado
    cupom_ref.update({
        "used": True,
        "redeemedBy": uid,
        "redeemedAt": datetime.utcnow()
    })

    return jsonify({"mensagem": "Plano ativado com sucesso pelo cupom!"})
