# services/sender_uid_links.py
# Índice canônico e PERMANENTE: waKey -> uid (+ displayName)
# - Não usa TTL (identidade não expira)
# - Resolve o "lead vira cliente": quando uid existir aqui, roteia para suporte
#
# DocID: waKey canônico (somente dígitos), ex: "555185648608" (55 + DDD + 8 dígitos)
#
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from services.phone_utils import digits_only, normalize_e164_br

# Coleção fixa (pode virar ENV depois se quiser)
COLL = "sender_uid_links"

def _db():
    # Usa o mesmo padrão do projeto (services.db.db é um firestore.Client já inicializado)
    try:
        from services.db import db  # type: ignore
        return db
    except Exception:
        # fallback (se alguém importar isso fora do app)
        from firebase_admin import firestore  # type: ignore
        return firestore.client()

def canonical_wa_key(raw_phone_or_e164: str) -> str:
    """
    Converte qualquer telefone (com ou sem '+') em waKey canônico (somente dígitos),
    tolerante ao '9' após DDD (BR).
    - Retorno típico: "55DDXXXXXXXX" (12 dígitos) para BR.
    """
    e164 = normalize_e164_br(raw_phone_or_e164 or "")
    d = digits_only(e164)
    if not d:
        d = digits_only(raw_phone_or_e164 or "")
    # garante BR: se vier nacional (10/11) prefixa 55
    if d and not d.startswith("55") and len(d) in (10, 11):
        d = "55" + d
    # se ainda está com 9 (13 dígitos): remove o 9 logo após DDD
    if d.startswith("55") and len(d) == 13:
        # 55 D D 9 XXXXXXXX
        d = d[:4] + d[5:]
    # se vier 12 dígitos já é canônico
    return d

def get_link(wa_key: str) -> Optional[Dict[str, Any]]:
    wa_key = (wa_key or "").strip()
    if not wa_key:
        return None
    try:
        snap = _db().collection(COLL).document(wa_key).get()
        if snap and snap.exists:
            return snap.to_dict() or {}
    except Exception:
        return None
    return None

def get_uid_for_wa_key(wa_key: str) -> Optional[str]:
    d = get_link(wa_key) or {}
    uid = (d.get("uid") or "").strip()
    return uid or None

def upsert_lead(wa_key: str, display_name: str = "", source: str = "lead") -> bool:
    wa_key = (wa_key or "").strip()
    if not wa_key:
        return False
    now = float(time.time())
    patch: Dict[str, Any] = {
        "waKey": wa_key,
        "kind": "lead",
        "lastSeenAt": now,
        "updatedAt": now,
        "source": (source or "lead"),
    }
    dn = (display_name or "").strip()
    if dn:
        patch["displayName"] = dn
        patch.setdefault("firstNamedAt", now)
    # não sobrescreve uid aqui
    try:
        _db().collection(COLL).document(wa_key).set(patch, merge=True)
        return True
    except Exception:
        return False

def upsert_customer(wa_key: str, uid: str, display_name: str = "", source: str = "signup") -> bool:
    wa_key = (wa_key or "").strip()
    uid = (uid or "").strip()
    if not wa_key or not uid:
        return False
    now = float(time.time())
    patch: Dict[str, Any] = {
        "waKey": wa_key,
        "uid": uid,
        "kind": "customer",
        "linkedAt": now,
        "lastSeenAt": now,
        "updatedAt": now,
        "source": (source or "signup"),
    }
    dn = (display_name or "").strip()
    if dn:
        patch["displayName"] = dn
    try:
        _db().collection(COLL).document(wa_key).set(patch, merge=True)
        return True
    except Exception:
        return False
