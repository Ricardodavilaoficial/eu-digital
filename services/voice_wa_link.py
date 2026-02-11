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

from services.firebase_admin_init import ensure_firebase_admin

from services.phone_utils import normalize_e164_br, phone_variants_br

def _db():
    """Firestore canônico: sempre via firebase-admin."""
    ensure_firebase_admin()
    # Firestore client (firebase_admin) — evita NameError em runtime
    from firebase_admin import firestore as fb_firestore
    return fb_firestore.client()

def _now():
    return datetime.now(timezone.utc)


def generate_link_code(length: int = 6) -> str:
    return "".join(random.choice(string.digits) for _ in range(max(4, length)))

def save_link_code(uid: str, code: str, ttl_seconds: int = 3600) -> None:
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("empty_code")

    ensure_firebase_admin()
    from firebase_admin import firestore as fb_firestore  # type: ignore

    expires_at = _now() + timedelta(seconds=int(ttl_seconds or 3600))
    doc = {
        "uid": uid,
        "code": code,
        "createdAt": fb_firestore.SERVER_TIMESTAMP,
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
    variants = phone_variants_br(from_e164)
    if not variants:
        raise ValueError("empty_sender")
    canon = variants[0]

    ensure_firebase_admin()
    from firebase_admin import firestore as fb_firestore  # type: ignore

    expires_at = _now() + timedelta(seconds=int(ttl_seconds or 3600))
    doc = {
        "uid": uid,
        "fromE164": canon,
        "method": method,
        "createdAt": fb_firestore.SERVER_TIMESTAMP,
        "expiresAt": expires_at,
        "ttlSeconds": int(ttl_seconds or 3600),
    }
    for key in variants:
        _db().collection("voice_links").document(key).set(doc, merge=True)

def delete_sender_link(from_e164: str) -> None:
    from_e164 = normalize_e164_br(from_e164)
    if not from_e164:
        return
    _db().collection("voice_links").document(from_e164).delete()

def get_uid_for_sender(from_e164: str) -> Optional[str]:
    variants = phone_variants_br(from_e164)
    if not variants:
        return None
    col = _db().collection("voice_links")
    snap = None
    ref = None
    for key in variants:
        ref = col.document(key)
        snap = ref.get()
        if snap.exists:
            break
    if not snap or not snap.exists:
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
