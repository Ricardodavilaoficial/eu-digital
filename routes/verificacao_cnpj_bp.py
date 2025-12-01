from flask import Blueprint, request, jsonify
from services.verificacao_cnpj import verificar_cnpj_basico, verificar_autoridade

verificacao_cnpj_bp = Blueprint("verificacao_cnpj_bp", __name__)

@verificacao_cnpj_bp.route("/api/cnpj/verificar", methods=["POST"])
def verificar_cnpj():
    payload = request.get_json() or {}
    cnpj = payload.get("cnpj", "")
    nome_usuario = payload.get("nomeUsuario", "")

    dados = verificar_cnpj_basico(cnpj)

    if not dados.get("ok"):
        return jsonify({
            "ok": False,
            "motivo": dados["motivo"],
            "mensagem": dados["mensagem"]
        }), 200

    autoridade = verificar_autoridade(nome_usuario, dados["raw"])

    return jsonify({
        "ok": True,
        "empresa": {
            "cnpj": dados["cnpj"],
            "razaoSocial": dados["razaoSocial"],
            "nomeFantasia": dados["nomeFantasia"],
            "cnae": dados["cnae"],
            "cnaeDescricao": dados["cnaeDescricao"],
            "ehMEI": dados["ehMEI"],
        },
        "autoridade": autoridade,
    }), 200
