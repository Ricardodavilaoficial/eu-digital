# -*- coding: utf-8 -*-
"""
Model helpers (stub v1 PREVIEW) para status de verificação.
Trocar por Firestore/DB nas próximas fases.

Compatível com as rotas atuais. Acrescenta:
- Normalização para StatusConta
- Auto-expiração em leitura
- Locks para minimizar condições de corrida em gthread
"""
from __future__ import annotations
from enum import Enum
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional
import threading

class StatusConta(str, Enum):
    guest_unverified = "guest_unverified"
    verified_basic   = "verified_basic"
    verified_owner   = "verified_owner"

# Estado em memória (PREVIEW). Em produção trocar por Firestore.
_STATE: Dict[str, Dict[str, Any]] = {}
_LOGS: Dict[str, list] = {}

_LOCK = threading.RLock()

def _to_enum(v: Any) -> StatusConta:
    if isinstance(v, StatusConta):
        return v
    try:
        return StatusConta(str(v))
    except Exception:
        return StatusConta.guest_unverified

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def get_user_status(user_id: str) -> Tuple[StatusConta, Optional[datetime]]:
    with _LOCK:
        u = _STATE.get(user_id)
        if not u:
            return StatusConta.guest_unverified, None
        status = _to_enum(u.get("statusConta", StatusConta.guest_unverified))
        exp: Optional[datetime] = u.get("statusContaExpireAt")
        # Auto-expira (fail-safe): se expirado, volta a guest_unverified
        if exp is not None and isinstance(exp, datetime) and exp.tzinfo is not None:
            if exp <= _now_utc():
                u["statusConta"] = StatusConta.guest_unverified
                u["statusContaExpireAt"] = None
                return StatusConta.guest_unverified, None
        return status, exp

def set_user_status(user_id: str, status: StatusConta, expire_at: Optional[datetime] = None):
    with _LOCK:
        u = _STATE.setdefault(user_id, {})
        u["statusConta"] = _to_enum(status)
        u["statusContaExpireAt"] = expire_at

def log_autorizacao(user_id: str, entry: Dict[str, Any]):
    with _LOCK:
        logs = _LOGS.setdefault(user_id, [])
        logs.append(entry)

def get_logs(user_id: str):
    with _LOCK:
        return list(_LOGS.get(user_id, []))

def get_user_meta(user_id: str) -> Dict[str, Any]:
    with _LOCK:
        u = _STATE.setdefault(user_id, {})
        return u.setdefault("meta", {})

def set_user_meta(user_id: str, meta_updates: Dict[str, Any]):
    with _LOCK:
        u = _STATE.setdefault(user_id, {})
        meta = u.setdefault("meta", {})
        meta.update(meta_updates)
        u["meta"] = meta
