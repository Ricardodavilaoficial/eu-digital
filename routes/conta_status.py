# routes/conta_status.py
from flask import Blueprint, jsonify
import os

bp_conta = Blueprint("bp_conta", __name__)

# Limiar de autopass (pode ajustar por ENV; default 75)
AUTOPASS_LIMIAR = int(os.getenv("AUTOPASS_LIMIAR", "75"))

def _snapshot_empresa():
    """
    Snapshot mínimo pro pós-pagamento (ativar-config).
    Pode trocar depois pra buscar do Firestore/receita/etc.
    Também aceita ENV para facilitar testes.
    """
    return {
        "cnpj": os.getenv("SNAP_CNPJ", "00000000000000"),
        "razaoSocial": os.getenv("SNAP_RAZAO", "Nome Ltda"),
        "nomeFantasia": os.getenv("SNAP_FANTASIA", "Nome"),
        "endereco": {
            "municipio": os.getenv("SNAP_MUNICIPIO", "Cidade"),
            "uf": os.getenv("SNAP_UF", "UF"),
        },
        "cnaePrincipal": {
            "codigo": os.getenv("SNAP_CNAE_COD", "9602-5/01"),
            "descricao": os.getenv("SNAP_CNAE_DESC", "Cabeleireiros..."),
        },
    }

def _vinculo_dict(score: int):
    ok = score >= AUTOPASS_LIMIAR
    # Regra de negócio simples: se não passou no limiar => precisa docs
    return {
        "stripe_enabled": ok,
        "needs_docs": not ok,
        "pending_review": False,  # pode ligar depois conforme seu fluxo
    }

@bp_conta.get("/api/stripe/gate")
def stripe_gate():
    score = int(os.getenv("SCORE_VINCULO", "82"))  # default 82 para liberar
    out = _vinculo_dict(score)
    out["scoreVinculo"] = score
    return jsonify(out), 200

@bp_conta.get("/api/conta/status")
def conta_status():
    score = int(os.getenv("SCORE_VINCULO", "82"))
    empresa = _snapshot_empresa()
    vinculo = _vinculo_dict(score)
    return jsonify({
        "empresa": empresa,
        "vinculo": vinculo
    }), 200
