# services/voice_wa_link.py
# NOVO — vínculo temporário "waSenderE164 -> uid" (com TTL)
#
# Coleções:
# - voice_wa_codes/{CODE}      (uid + expiresAt)  (usado no modo por código)
# - voice_links/{waSenderE164} (uid + expiresAt)  (usado no modo por código ou convite direto)
#
# Allowlist opcional:
# - VOICE_WA_FROM_ALLOWLIST="+55..., +55..."

from __future__ import annotations

import os
import re
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from google.cloud import firestore  # type: ignore

def _db():
    return firestore.Client()

def _now():
    return datetime.now(timezone.utc)

def normalize_e164_br(e164: str) -> str:
    s = re.sub(r"[^\d+]", "", (e164 or "").strip())
    if not s:
        return ""
    if s.startswith("00"):
        s = "+" + s[2:]
    if not s.startswith("+"):
        digits = re.sub(r"\D+", "", s)
        if digits.startswith("55"):
            s = "+" + digits
        elif len(digits) in (10, 11):
            s = "+55" + digits
        else:
            s = "+" + digits
    s = "+" + re.sub(r"\D+", "", s)
    return s

def generate_link_code(length: int = 6) -> str:
    return "".join(random.choice(string.digits) for _ in range(max(4, length)))

def save_link_code(uid: str, code: str, ttl_seconds: int = 3600) -> None:
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("empty_code")
    expires_at = _now() + timedelta(seconds=int(ttl_seconds or 3600))
    doc = {
        "uid": uid,
        "code": code,
        "createdAt": firestore.SERVER_TIMESTAMP,  # type: ignore
        "expiresAt": expires_at,
        "ttlSeconds": int(ttl_seconds or 3600),
    }
    _db().collection("voice_wa_codes").document(code).set(doc, merge=False)

def consume_link_code(code: str) -> Optional[Dict[str, Any]]:
    code = (code or "").strip().upper()
    if not code:
        return None
    ref = _db().collection("voice_wa_codes").document(code)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    expires_at = data.get("expiresAt")
    if expires_at and hasattr(expires_at, "to_datetime"):
        expires_at = expires_at.to_datetime()
    if expires_at and isinstance(expires_at, datetime):
        if expires_at.replace(tzinfo=timezone.utc) < _now():
            try:
                ref.delete()
            except Exception:
                pass
            return None
    try:
        ref.delete()
    except Exception:
        pass
    return {"uid": data.get("uid"), "ttlSeconds": int(data.get("ttlSeconds") or 3600)}

def upsert_sender_link(from_e164: str, uid: str, ttl_seconds: int = 3600, method: str = "code") -> None:
    from_e164 = normalize_e164_br(from_e164)
    if not from_e164:
        raise ValueError("empty_sender")
    expires_at = _now() + timedelta(seconds=int(ttl_seconds or 3600))
    doc = {
        "uid": uid,
        "fromE164": from_e164,
        "method": method,
        "createdAt": firestore.SERVER_TIMESTAMP,  # type: ignore
        "expiresAt": expires_at,
        "ttlSeconds": int(ttl_seconds or 3600),
    }
    _db().collection("voice_links").document(from_e164).set(doc, merge=True)

def delete_sender_link(from_e164: str) -> None:
    from_e164 = normalize_e164_br(from_e164)
    if not from_e164:
        return
    _db().collection("voice_links").document(from_e164).delete()

def get_uid_for_sender(from_e164: str) -> Optional[str]:
    from_e164 = normalize_e164_br(from_e164)
    if not from_e164:
        return None
    ref = _db().collection("voice_links").document(from_e164)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    expires_at = data.get("expiresAt")
    if expires_at and hasattr(expires_at, "to_datetime"):
        expires_at = expires_at.to_datetime()
    if expires_at and isinstance(expires_at, datetime):
        if expires_at.replace(tzinfo=timezone.utc) < _now():
            try:
                ref.delete()
            except Exception:
                pass
            return None
    return data.get("uid")

def sender_allowed(from_e164: str) -> bool:
    allow = (os.environ.get("VOICE_WA_FROM_ALLOWLIST") or "").strip()
    if not allow:
        return True
    allowed = set()
    for part in allow.split(","):
        p = normalize_e164_br(part)
        if p:
            allowed.add(p)
    return normalize_e164_br(from_e164) in allowed
