from datetime import datetime, timezone
from .db import db

COL_CUPONS = "cuponsAtivacao"

def criar_cupom(body: dict, criado_por: str):
    import random, string
    codigo = (body.get("codigo") or
              "".join(random.choices(string.ascii_uppercase, k=5)) + "-" +
              "".join(random.choices(string.digits, k=4)))

    cupom = {
        "codigo": codigo.upper(),
        "tipo": body.get("tipo", "trial"),  # trial | desconto
        "valor": body.get("valor"),
        "expiraEm": body.get("expiraEm"),   # ISO8601 ou None
        "usosMax": int(body.get("usosMax", 1)),
        "usos": 0,
        "ativo": True,
        "criadoPorUid": criado_por,
        "escopo": body.get("escopo", "global"),  # global | uid
        "uidDestino": body.get("uidDestino"),
        "createdAt": datetime.now(timezone.utc).isoformat()
    }
    db.collection(COL_CUPONS).document().set(cupom)
    return cupom

def find_cupom_by_codigo(codigo: str):
    if not codigo:
        return None
    qs = db.collection(COL_CUPONS).where("codigo", "==", codigo.upper()).limit(1).stream()
    for d in qs:
        c = d.to_dict()
        c["_id"] = d.id
        return c
    return None

def validar_consumir_cupom(cupom: dict, uid: str):
    if not cupom or not cupom.get("ativo"):
        return False, "Cupom inválido ou inativo.", None

    exp = cupom.get("expiraEm")
    if exp:
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_dt:
                return False, "Cupom expirado.", None
        except Exception:
            return False, "Formato de expiração inválido.", None

    if cupom.get("escopo") == "uid" and cupom.get("uidDestino") != uid:
        return False, "Este cupom não é destinado a este usuário.", None

    if cupom.get("usos", 0) >= int(cupom.get("usosMax", 1)):
        return False, "Limite de usos atingido.", None

    # Consome 1 uso
    db.collection(COL_CUPONS).document(cupom["_id"]).update({
        "usos": cupom.get("usos", 0) + 1
    })

    plano = {
        "status": "ativo",
        "origem": "cupom",
        "expiraEm": exp,
        "quotaMensal": 10000
    }
    return True, "ok", plano
