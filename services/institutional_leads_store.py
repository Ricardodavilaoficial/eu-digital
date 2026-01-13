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

# Coleção CANÔNICA (durável) de perfil de lead (sem TTL)
# - doc_id = waKey (somente dígitos)
# - objetivo: reconhecimento do lead meses depois + base para marketing/segmentação futura
COLL_LEAD_PROFILES = os.getenv("PLATFORM_LEAD_PROFILES_COLL", "platform_lead_profiles")

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

def _clean_name(s: str) -> str:
    """Normaliza nome simples (lead). Mantém curto e humano."""
    s = (s or "").strip()
    if not s:
        return ""
    s = " ".join(s.split())
    if len(s) > 60:
        s = s[:60].rstrip()
    return s

def br_wa_key_candidates(raw_sender: str) -> List[str]:
    """
    Gera chaves candidatas estáveis para BR, tolerante ao dígito 9.
    Retorna lista de waKeys (somente dígitos), ex: '5551985648608'
    """
    d = _normalize_digits(raw_sender)
    if not d:
        return []

    candidates: List[str] = []
    if d.startswith("55"):
        candidates.append(d)
        if len(d) == 13:
            candidates.append(d[:4] + d[5:])
        if len(d) == 12:
            candidates.append(d[:4] + "9" + d[4:])
    else:
        if len(d) in (10, 11):
            d2 = "55" + d
            candidates.append(d2)
            if len(d2) == 13:
                candidates.append(d2[:4] + d2[5:])
            if len(d2) == 12:
                candidates.append(d2[:4] + "9" + d2[4:])
        else:
            candidates.append(d)

    seen = set()
    out = []
    for x in candidates:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out

def get_session(raw_sender: str) -> Tuple[Optional[Dict[str, Any]], str]:
    keys = br_wa_key_candidates(raw_sender)
    if not keys:
        return None, ""

    db = _db()
    for k in keys:
        snap = db.collection(COLL_SESSIONS).document(k).get()
        if snap.exists:
            data = snap.to_dict() or {}
            exp = float(data.get("expiresAt") or 0.0)
            if exp and exp < now_ts():
                continue
            return data, k

        doc_id_legacy = _sha1_id(k)
        snap2 = db.collection(COLL_SESSIONS).document(doc_id_legacy).get()
        if snap2.exists:
            data = snap2.to_dict() or {}
            exp = float(data.get("expiresAt") or 0.0)
            if exp and exp < now_ts():
                continue
            try:
                data2 = dict(data)
                data2["waKey"] = k
                db.collection(COLL_SESSIONS).document(k).set(data2, merge=True)
            except Exception:
                pass
            return data, k

    return None, keys[0]

# -----------------------------
# PERFIL CANÔNICO (SEM TTL)
# -----------------------------
def get_lead_profile(raw_sender: str) -> Tuple[Optional[Dict[str, Any]], str]:
    keys = br_wa_key_candidates(raw_sender)
    if not keys:
        return None, ""
    db = _db()
    for k in keys:
        snap = db.collection(COLL_LEAD_PROFILES).document(k).get()
        if snap.exists:
            data = snap.to_dict() or {}
            data = dict(data)
            data.setdefault("waKey", k)
            data.setdefault("resolvedWaKey", k)
            return data, k
    return None, keys[0]

def upsert_lead_profile(wa_key: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    db = _db()
    now = now_ts()
    payload = dict(patch or {})

    if "displayName" in payload:
        payload["displayName"] = _clean_name(str(payload.get("displayName") or ""))
    if "name" in payload and not payload.get("displayName"):
        payload["displayName"] = _clean_name(str(payload.get("name") or ""))
        payload.pop("name", None)

    payload.setdefault("waKey", wa_key)
    payload["lastSeenAt"] = now
    payload.setdefault("firstSeenAt", now)
    payload["updatedAt"] = now

    db.collection(COLL_LEAD_PROFILES).document(wa_key).set(payload, merge=True)

    out = dict(payload)
    out.setdefault("resolvedWaKey", wa_key)
    out.setdefault("profileDocId", wa_key)
    return out

def set_session(wa_key: str, session: Dict[str, Any], ttl_seconds: Optional[int] = None) -> None:
    ttl = int(ttl_seconds) if ttl_seconds is not None else SESS_TTL_SECONDS
    exp = now_ts() + max(60, ttl)
    db = _db()
    payload = dict(session or {})
    payload.update({
        "waKey": wa_key,
        "updatedAt": now_ts(),
        "expiresAt": exp,
    })
    db.collection(COLL_SESSIONS).document(wa_key).set(payload, merge=True)

def get_lead(raw_sender: str) -> Tuple[Optional[Dict[str, Any]], str]:
    keys = br_wa_key_candidates(raw_sender)
    if not keys:
        return None, ""

    db = _db()
    for k in keys:
        snap = db.collection(COLL_LEADS).document(k).get()
        if snap.exists:
            data = snap.to_dict() or {}
            exp = float(data.get("expiresAt") or 0.0)
            if exp and exp < now_ts():
                continue
            data = dict(data or {})
            data.setdefault("resolvedWaKey", k)
            data.setdefault("leadDocId", k)
            return data, k

        doc_id_legacy = _sha1_id(k)
        snap2 = db.collection(COLL_LEADS).document(doc_id_legacy).get()
        if snap2.exists:
            data = snap2.to_dict() or {}
            exp = float(data.get("expiresAt") or 0.0)
            if exp and exp < now_ts():
                continue
            data = dict(data)
            data.setdefault("resolvedWaKey", k)
            data.setdefault("leadDocId", k)
            try:
                data2 = dict(data)
                data2["waKey"] = k
                db.collection(COLL_LEADS).document(k).set(data2, merge=True)
            except Exception:
                pass
            return data, k

    return None, keys[0]
# -----------------------------
# COMPAT: UPSERT LEAD / SESSION
# (para alinhar com imports do sales_lead.py)
# -----------------------------

def upsert_lead(wa_key: str, patch: Dict[str, Any], ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
    """
    Upsert no lead de funil (TTL), usado para estado de conversa institucional.
    doc_id = wa_key (somente dígitos)
    """
    db = _db()
    now = now_ts()

    ttl = int(ttl_seconds) if ttl_seconds is not None else LEAD_TTL_SECONDS
    exp = now + max(300, ttl)  # mínimo 5min pra não expirar no meio

    payload = dict(patch or {})
    payload.setdefault("waKey", wa_key)
    payload["updatedAt"] = now
    payload.setdefault("createdAt", now)
    payload["expiresAt"] = exp

    # Se vier nome por alias, normaliza
    if "displayName" in payload:
        payload["displayName"] = _clean_name(str(payload.get("displayName") or ""))
    if "name" in payload and not payload.get("displayName"):
        payload["displayName"] = _clean_name(str(payload.get("name") or ""))
        payload.pop("name", None)

    db.collection(COLL_LEADS).document(wa_key).set(payload, merge=True)

    out = dict(payload)
    out.setdefault("resolvedWaKey", wa_key)
    out.setdefault("leadDocId", wa_key)
    return out


def upsert_session(wa_key: str, patch: Dict[str, Any], ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
    """
    Upsert de session (TTL curto) — compat com código legado.
    """
    # Reaproveita o set_session existente (mantém comportamento)
    current = dict(patch or {})
    set_session(wa_key, current, ttl_seconds=ttl_seconds)

    out = dict(current)
    out.setdefault("waKey", wa_key)
    out.setdefault("resolvedWaKey", wa_key)
    out.setdefault("sessionDocId", wa_key)
    return out

