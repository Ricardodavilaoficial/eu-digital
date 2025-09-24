# routes/conta_status.py
from flask import Blueprint, jsonify, make_response
import os

bp_conta = Blueprint("bp_conta", __name__)

# -------- helpers seguros --------
def _env_int(name: str, default: int) -> int:
    """Lê int de ENV com fallback seguro (sem quebrar o boot)."""
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default

def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

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

def _vinculo_dict(score: int, limiar: int):
    ok = score >= limiar
    return {
        "stripe_enabled": ok,
        "needs_docs": not ok,
        "pending_review": False,     # encaixe futuro
        "reason": "ok" if ok else "needs_docs",
        "scoreVinculo": score,
        "limiar": limiar,
    }

# -------- endpoints --------
@bp_conta.get("/api/stripe/gate")
def stripe_gate():
    limiar = _env_int("AUTOPASS_LIMIAR", 75)
    score = _env_int("SCORE_VINCULO", 82)  # default 82 para liberar
    out = _vinculo_dict(score, limiar)
    resp = make_response(jsonify(out), 200)
    return _no_store(resp)

@bp_conta.get("/api/conta/status")
def conta_status():
    limiar = _env_int("AUTOPASS_LIMIAR", 75)
    score = _env_int("SCORE_VINCULO", 82)
    empresa = _snapshot_empresa()
    vinculo = _vinculo_dict(score, limiar)
    resp = make_response(jsonify({
        "empresa": empresa,
        "vinculo": vinculo
    }), 200)
    return _no_store(resp)
