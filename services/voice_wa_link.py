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
    """Normaliza para algo tipo E164 (+<digits>), com heurística BR.

    - Aceita: +55..., 55..., 00..., (51) 9xxxx-xxxx, etc.
    - Para BR com DDI 55:
        * Se tiver DDD + 9 + 8 dígitos (celular 11 dígitos nacionais), remove o '9' móvel e
          canonicaliza para +55DDXXXXXXXX.
        * Se tiver DDD + 8 dígitos (fixo), mantém.
    """
    s = re.sub(r"[^\d+]", "", (e164 or "").strip())
    if not s:
        return ""

    # 00xx... -> +xx...
    if s.startswith("00"):
        s = "+" + s[2:]

    # se veio sem '+', tenta inferir BR
    if not s.startswith("+"):
        digits = re.sub(r"\D+", "", s)
        if digits.startswith("55"):
            s = "+" + digits
        elif len(digits) in (10, 11):  # DDD + (8|9) dígitos
            s = "+55" + digits
        else:
            s = "+" + digits

    # garante só dígitos após '+'
    s = "+" + re.sub(r"\D+", "", s)

    # Heurística BR: canonicalizar removendo o '9' móvel (DDD + 9 + 8)
    digits = s[1:]
    if digits.startswith("55"):
        national = digits[2:]  # tudo após 55
        if len(national) == 11:
            ddd = national[:2]
            num = national[2:]
            if num.startswith("9") and len(num) == 9:
                s = "+55" + ddd + num[1:]
    return s

def _br_sender_variants(e164: str) -> list[str]:
    """Gera variantes BR (com/sem 9) para compatibilidade no vínculo."""
    base = normalize_e164_br(e164)
    if not base:
        return []
    out = {base}

    digits = base[1:]
    if digits.startswith("55"):
        national = digits[2:]
        if len(national) == 10:
            ddd = national[:2]
            num = national[2:]
            out.add("+55" + ddd + "9" + num)
        elif len(national) == 11:
            ddd = national[:2]
            num = national[2:]
            if num.startswith("9") and len(num) == 9:
                out.add("+55" + ddd + num[1:])
    return [x for x in out if x]


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
    variants = _br_sender_variants(from_e164)
    if not variants:
        raise ValueError("empty_sender")
    canon = variants[0]
    expires_at = _now() + timedelta(seconds=int(ttl_seconds or 3600))
    doc = {
        "uid": uid,
        "fromE164": canon,
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
    variants = _br_sender_variants(from_e164)
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


