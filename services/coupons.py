# services/coupons.py — v1.0-hardening (compat) — transacional + idempotência + fair-use + auditoria
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any
from .db import db

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
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.***"
    return ip[:3] + "***"

def _ua_short(ua: Optional[str]) -> str:
    if not ua:
        return ""
    # Reduz para algo curto
    ua = ua.replace("Mozilla/", "").replace("AppleWebKit/", "").replace("Gecko/", "")
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
        # Auditoria não deve quebrar o fluxo
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
# Mantém assinatura de retorno: (ok: bool, msg: str, plano|None)
# ctx: info opcional p/ auditoria {"ip": "...", "ua":"..."}
# ====================================================
def validar_consumir_cupom(cupom: dict, uid: str, ctx: Optional[Dict[str, Any]] = None) -> Tuple[bool, str, Optional[dict]]:
    """
    Transação Firestore compatível (context manager):
      - revalida (ativo/expiração/escopo/limite) dentro da transação;
      - idempotência: redeems/{codigo}-{uid} evita duplo clique;
      - fair-use trial: profissionais/{uid}.trialRedeemed=true;
      - incrementa usos apenas uma vez.
    """
    client = db()  # Firestore client (lazy)

    codigo = (cupom or {}).get("codigo", "").upper()
    cupom_id = (cupom or {}).get("_id")
    if not codigo:
        _audit(False, uid, None, "nao_encontrado", ctx)
        return False, "Cupom inválido ou não encontrado.", None

    # Se _id não foi propagado por quem chamou, resolvemos aqui
    if not cupom_id:
        found = find_cupom_by_codigo(codigo)
        if not found:
            _audit(False, uid, None, "nao_encontrado", ctx)
            return False, "Cupom inválido ou não encontrado.", None
        cupom_id = found.get("_id")

    cupom_ref = client.collection(COL_CUPONS).document(cupom_id)
    redeem_id = f"{codigo}-{uid}"
    redeem_ref = client.collection(COL_REDEEMS).document(redeem_id)
    prof_ref = client.collection(COL_PROFISSIONAIS).document(uid)

    try:
        # ===== transação compatível (context manager) =====
        with client.transaction() as transaction:
            snap = transaction.get(cupom_ref)
            if not snap.exists:
                _audit(False, uid, codigo, "nao_encontrado", ctx)
                return False, "Cupom inválido ou não encontrado.", None

            doc = snap.to_dict() or {}
            doc["_id"] = cupom_id

            # Validações
            if not doc.get("ativo"):
                _audit(False, uid, codigo, "inativo", ctx)
                return False, "Cupom inválido ou inativo.", None

            exp_dt = _parse_exp(doc.get("expiraEm"))
            if doc.get("expiraEm") and not exp_dt:
                _audit(False, uid, codigo, "expiracao_invalida", ctx)
                return False, "Formato de expiração inválido.", None
            if exp_dt and datetime.now(timezone.utc) > exp_dt:
                _audit(False, uid, codigo, "expirado", ctx)
                return False, "Cupom expirado.", None

            if doc.get("escopo") == "uid" and doc.get("uidDestino") != uid:
                _audit(False, uid, codigo, "escopo_invalido", ctx)
                return False, "Este cupom não é destinado a este usuário.", None

            # Idempotência (redeem já existe)
            redeem_snap = transaction.get(redeem_ref)
            if redeem_snap.exists:
                plano = _mk_plano_from_cupom(doc)
                _audit(True, uid, codigo, "idempotente_ok", ctx)
                return True, "ok", plano

            # Fair-use trial (1 por usuário)
            if (doc.get("tipo") == "trial"):
                prof_snap = transaction.get(prof_ref)
                prof_doc = prof_snap.to_dict() if prof_snap.exists else {}
                if prof_doc and prof_doc.get("trialRedeemed") is True:
                    _audit(False, uid, codigo, "trial_ja_usado", ctx)
                    return False, "Você já utilizou um cupom de teste (trial) neste usuário.", None

            # Limite de usos
            usos = int(doc.get("usos", 0))
            usosMax = int(doc.get("usosMax", 1))
            if usos >= usosMax:
                _audit(False, uid, codigo, "sem_usos_restantes", ctx)
                return False, "Limite de usos atingido.", None

            # Efetiva (mesmo commit)
            now_iso = _now_iso_utc()
            transaction.set(redeem_ref, {
                "uid": uid,
                "codigo": codigo,
                "cupomId": cupom_id,
                "tipo": doc.get("tipo"),
                "ok": True,
                "ts": now_iso,
                "status": "ok",
            }, merge=False)

            transaction.update(cupom_ref, {"usos": usos + 1})

            if (doc.get("tipo") == "trial"):
                transaction.set(prof_ref, {
                    "trialRedeemed": True,
                    "trialRedeemedAt": now_iso
                }, merge=True)

        # commit foi feito ao sair do with
        plano = _mk_plano_from_cupom(doc)
        _audit(True, uid, codigo, "ok", ctx)
        return True, "ok", plano

    except Exception as e:
        # Auditoria de exceção sem PII
        _audit(False, uid, codigo, f"exception:{type(e).__name__}", ctx)
        return False, "Falha ao validar cupom (transação).", None
