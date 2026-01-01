# services/institutional_leads_store.py
from __future__ import annotations

import os
import time
import hashlib
from typing import Any, Dict, Optional, Tuple, List

# Coleções (institucional)
COLL_SESSIONS = os.getenv("INSTITUTIONAL_SESSIONS_COLL", "institutional_sessions")
COLL_LEADS = os.getenv("INSTITUTIONAL_LEADS_COLL", "institutional_leads")

# TTL default
SESS_TTL_SECONDS = int(os.getenv("INSTITUTIONAL_SESSION_TTL_SECONDS", "3600") or "3600")  # 1h
LEAD_TTL_SECONDS = int(os.getenv("INSTITUTIONAL_LEAD_TTL_SECONDS", "2592000") or "2592000")  # 30d (opcional)

def _db():
    # Usa firebase_admin (padrão mais comum em backends Firebase/Firestore)
    from firebase_admin import firestore  # type: ignore
    return firestore.client()

def _sha1_id(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8", errors="ignore")).hexdigest()

def now_ts() -> float:
    return float(time.time())

def _normalize_digits(raw: str) -> str:
    # mantém só dígitos
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return digits

def br_wa_key_candidates(raw_sender: str) -> List[str]:
    """
    Gera chaves candidatas estáveis para BR, tolerante ao dígito 9.
    Retorna lista de waKeys (somente dígitos), ex: '5551985648608'
    """
    d = _normalize_digits(raw_sender)
    if not d:
        return []

    # Alguns providers mandam 'from' sem +, outros com.
    # Vamos assumir BR se começa com 55 ou se parece BR (DDD + 8/9 dígitos)
    candidates: List[str] = []
    if d.startswith("55"):
        candidates.append(d)
        # Tolerância ao 9: se 55 DDD 9 XXXXXXXX (13 dígitos) -> tenta remover o 9
        # Ex: 55 51 9 8564-8608 -> remove o '9' na posição 4 (0-index: 4)
        if len(d) == 13:
            maybe = d[:4] + d[5:]
            candidates.append(maybe)
        # Se 55 DDD XXXXXXXX (12 dígitos) -> tenta inserir 9
        if len(d) == 12:
            maybe = d[:4] + "9" + d[4:]
            candidates.append(maybe)
    else:
        # Se não começa com 55, tenta prefixar
        if len(d) in (10, 11):  # DDD + número
            candidates.append("55" + d)
            d2 = "55" + d
            if len(d2) == 13:
                candidates.append(d2[:4] + d2[5:])
            if len(d2) == 12:
                candidates.append(d2[:4] + "9" + d2[4:])
        else:
            candidates.append(d)

    # remove duplicados preservando ordem
    seen = set()
    out = []
    for x in candidates:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out

def get_session(raw_sender: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Busca sessão por candidatos (tolerante ao 9).
    Retorna (session_dict or None, waKey_escolhida).
    """
    keys = br_wa_key_candidates(raw_sender)
    if not keys:
        return None, ""

    db = _db()
    for k in keys:
        doc_id = _sha1_id(k)
        snap = db.collection(COLL_SESSIONS).document(doc_id).get()
        if snap.exists:
            data = snap.to_dict() or {}
            # Expiração lógica
            exp = float(data.get("expiresAt") or 0.0)
            if exp and exp < now_ts():
                # expirou: trata como não existente
                continue
            return data, k

    return None, keys[0]

def set_session(wa_key: str, session: Dict[str, Any], ttl_seconds: Optional[int] = None) -> None:
    ttl = int(ttl_seconds) if ttl_seconds is not None else SESS_TTL_SECONDS
    exp = now_ts() + max(60, ttl)  # mínimo 60s
    db = _db()
    doc_id = _sha1_id(wa_key)
    payload = dict(session or {})
    payload.update({
        "waKey": wa_key,
        "updatedAt": now_ts(),
        "expiresAt": exp,
    })
    db.collection(COLL_SESSIONS).document(doc_id).set(payload, merge=True)

def delete_session(wa_key: str) -> None:
    db = _db()
    doc_id = _sha1_id(wa_key)
    db.collection(COLL_SESSIONS).document(doc_id).delete()

def get_lead(raw_sender: str) -> Tuple[Optional[Dict[str, Any]], str]:
    keys = br_wa_key_candidates(raw_sender)
    if not keys:
        return None, ""

    db = _db()
    for k in keys:
        doc_id = _sha1_id(k)
        snap = db.collection(COLL_LEADS).document(doc_id).get()
        if snap.exists:
            data = snap.to_dict() or {}
            # TTL opcional para lead (se tu quiser limpar “curiosos” depois)
            exp = float(data.get("expiresAt") or 0.0)
            if exp and exp < now_ts():
                continue
            return data, k
    return None, keys[0]

def upsert_lead(wa_key: str, lead: Dict[str, Any], ttl_seconds: Optional[int] = None) -> None:
    ttl = int(ttl_seconds) if ttl_seconds is not None else LEAD_TTL_SECONDS
    exp = now_ts() + max(3600, ttl)  # mínimo 1h
    db = _db()
    doc_id = _sha1_id(wa_key)
    payload = dict(lead or {})
    payload.update({
        "waKey": wa_key,
        "updatedAt": now_ts(),
        "expiresAt": exp,  # se tu quiser lead “semi-ephemeral”; se não quiser, pode remover esse campo depois
    })
    # firstSeenAt se não existir
    payload.setdefault("firstSeenAt", now_ts())
    db.collection(COLL_LEADS).document(doc_id).set(payload, merge=True)
