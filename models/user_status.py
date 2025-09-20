# -*- coding: utf-8 -*-
"""
Model helpers (stub v1 PREVIEW) para status de verificação.
Trocar por Firestore/DB nas próximas fases.
"""
from __future__ import annotations
from enum import Enum
from datetime import datetime
from typing import Tuple, Dict, Any

class StatusConta(str, Enum):
    guest_unverified = "guest_unverified"
    verified_basic = "verified_basic"
    verified_owner = "verified_owner"

# Estado em memória (PREVIEW). Em produção trocar por Firestore.
_STATE: Dict[str, Dict[str, Any]] = {}
_LOGS: Dict[str, list] = {}

def get_user_status(user_id: str) -> Tuple[StatusConta, datetime|None]:
    u = _STATE.get(user_id)
    if not u:
        return StatusConta.guest_unverified, None
    return StatusConta(u.get("statusConta", StatusConta.guest_unverified)), u.get("statusContaExpireAt")

def set_user_status(user_id: str, status: StatusConta, expire_at: datetime|None = None):
    u = _STATE.setdefault(user_id, {})
    u["statusConta"] = status
    u["statusContaExpireAt"] = expire_at

def log_autorizacao(user_id: str, entry: Dict[str, Any]):
    logs = _LOGS.setdefault(user_id, [])
    logs.append(entry)

def get_logs(user_id: str):
    return list(_LOGS.get(user_id, []))

def get_user_meta(user_id: str) -> Dict[str, Any]:
    u = _STATE.setdefault(user_id, {})
    return u.setdefault("meta", {})

def set_user_meta(user_id: str, meta_updates: Dict[str, Any]):
    u = _STATE.setdefault(user_id, {})
    meta = u.setdefault("meta", {})
    meta.update(meta_updates)
    u["meta"] = meta
