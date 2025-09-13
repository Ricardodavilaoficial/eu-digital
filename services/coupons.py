# services/coupons.py — v1.0-hardening (estável) — transacional + idempotência + fair-use + auditoria
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any

from .db import db
# Usamos o decorator oficial do Firestore para transação (sem commit manual)
from google.cloud import firestore as gcfs  # faz parte do firebase_admin

COL_CUPONS = "cuponsAtivacao"
COL_REDEEMS = "redeems"
COL_ATTEMPTS = "coupon_attempts"
COL_PROFISSIONAIS = "profissionais"

# ===============================
# Utilidades leves (sem depend.)
# ===============================
def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _parse_exp(exp: Optional[str]) -> Optional[datetime]:
    if not exp:
        return None
    try:
        # Suporta "Z" ao final
        return datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except Exception:
        return None

def _mask_ip(ip: Optional[str]) -> str:
    if not ip:
        return ""
    parts = str(ip).split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.***"
    return str(ip)[:3] + "***"

def _ua_short(ua: Optional[str]) -> str:
    if not ua:
        return ""
    ua = str(ua).replace("Mozilla/", "").replace("AppleWebKit/", "").replace("Gecko/", "")
    return ua[:80]

# ==============
# Helpers internos
# ==============
def _mk_plano_from_cupom(cupom: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "ativo",
        "origem": "cupom",
        "expiraEm": cupom.get("expiraEm"),
        "quotaMensal": 10000
    }

def _audit(ok: bool, uid: Optional[str], codigo: Optional[str], reason: str, ctx: Optional[Dict[str, Any]]):
    try:
        client = db()
        doc = {
            "ts": _now_iso_utc(),
            "ok": bool(ok),
            "uid": uid or None,
            "codigo": (codigo or "").upper() or None,
            "reason": reason,
        }
        if ctx:
            ip = ctx.get("ip")
            ua = ctx.get("ua")
            if ip:
                doc["ipMasked"] = _mask_ip(ip)
            if ua:
                doc["uaShort"] = _ua_short(ua)
        client.collection(COL_ATTEMPTS).document().set(doc)
    except Exception:
        # Auditoria nunca deve quebrar o fluxo
        pass

# =====================
# CRUD util (existente)
# =====================
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
        "createdAt": _now_iso_utc()
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

# ====================================================
# Núcleo: validação + consumo TRANSACIONAL e seguro
# Mantém assinatura: (ok: bool, msg: str, plano|None)
# ctx opcional p/ auditoria {"ip": "...", "ua":"..."}
# ====================================================
def validar_consumir_cupom(cupom: dict, uid: str, ctx: Optional[Dict[str, Any]] = None) -> Tuple[bool, str, Optional[dict]]:
    """
    Transação com decorator oficial (@transactional) — sem commit manual.
      - Revalida tudo dentro da transação;
      - Idempotência (redeems/{codigo}-{uid});
      - Fair-use trial (profissionais/{uid}.trialRedeemed=true).
    """
    client = db()

    codigo = (cupom or {}).get("codigo", "").upper()
    cupom_id = (cupom or {}).get("_id")

    if not codigo:
        _audit(False, uid, None, "nao_encontrado", ctx)
        return False, "Cupom inválido ou não encontrado.", None

    if not cupom_id:
        found = find_cupom_by_codigo(codigo)
        if not found:
            _audit(False, uid, None, "nao_encontrado", ctx)
            return False, "Cupom inválido ou não encontrado.", None
        cupom_id = found.get("_id")

    cupom_ref  = client.collection(COL_CUPONS).document(cupom_id)
    redeem_id  = f"{codigo}-{uid}"
    redeem_ref = client.collection(COL_REDEEMS).document(redeem_id)
    prof_ref   = client.collection(COL_PROFISSIONAIS).document(uid)

    @gcfs.transactional
    def _apply(tx: gcfs.Transaction):
        # Leituras
        cupom_snap = cupom_ref.get(transaction=tx)
        if not cupom_snap.exists:
            return False, "nao_encontrado", None, None

        doc = cupom_snap.to_dict() or {}
        doc["_id"] = cupom_id

        # Validações
        if not doc.get("ativo"):
            return False, "inativo", None, doc

        exp_dt = _parse_exp(doc.get("expiraEm"))
        if doc.get("expiraEm") and not exp_dt:
            return False, "expiracao_invalida", None, doc
        if exp_dt and datetime.now(timezone.utc) > exp_dt:
            return False, "expirado", None, doc

        if doc.get("escopo") == "uid" and doc.get("uidDestino") != uid:
            return False, "escopo_invalido", None, doc

        # Idempotência
        redeem_snap = redeem_ref.get(transaction=tx)
        if redeem_snap.exists:
            plano = _mk_plano_from_cupom(doc)
            return True, "idempotente_ok", plano, doc

        # Fair-use (trial por UID)
        if doc.get("tipo") == "trial":
            prof_snap = prof_ref.get(transaction=tx)
            prof_doc = prof_snap.to_dict() if prof_snap.exists else {}
            if prof_doc and prof_doc.get("trialRedeemed") is True:
                return False, "trial_ja_usado", None, doc

        # Limite de usos
        usos = int(doc.get("usos", 0))
        usos_max = int(doc.get("usosMax", 1))
        if usos >= usos_max:
            return False, "sem_usos_restantes", None, doc

        # Escritas atômicas
        now_iso = _now_iso_utc()
        tx.set(redeem_ref, {
            "uid": uid,
            "codigo": codigo,
            "cupomId": cupom_id,
            "tipo": doc.get("tipo"),
            "ok": True,
            "ts": now_iso,
            "status": "ok",
        }, merge=False)

        tx.update(cupom_ref, {"usos": usos + 1})

        if doc.get("tipo") == "trial":
            # merge=True é suportado em transação
            tx.set(prof_ref, {"trialRedeemed": True, "trialRedeemedAt": now_iso}, merge=True)

        plano = _mk_plano_from_cupom(doc)
        return True, "ok", plano, doc

    try:
        ok, reason, plano, _doc_used = _apply(client.transaction())
    except Exception as e:
        _audit(False, uid, codigo, f"exception:{type(e).__name__}", ctx)
        return False, "Falha ao validar cupom (transação).", None

    # Auditoria fora da transação
    _audit(ok, uid, codigo, reason, ctx)

    if ok:
        return True, "ok", plano

    msg_map = {
        "nao_encontrado": "Cupom inválido ou não encontrado.",
        "inativo": "Cupom inválido ou inativo.",
        "expiracao_invalida": "Formato de expiração inválido.",
        "expirado": "Cupom expirado.",
        "escopo_invalido": "Este cupom não é destinado a este usuário.",
        "sem_usos_restantes": "Limite de usos atingido.",
        "trial_ja_usado": "Você já utilizou um cupom de teste (trial) neste usuário.",
        "exception": "Falha ao validar cupom (transação).",
    }
    return False, msg_map.get(reason, "Não foi possível aplicar este cupom."), None
