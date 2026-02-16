# services/speaker_state.py
# Persistência leve de estado por contato (turnos IA, gates de nome, etc.)
# Fonte de verdade: Firestore (coleção SPEAKER_STATE_COLL, default: platform_speaker_state)
# Safe-by-default: se Firestore não estiver pronto, usa memória local (processo) e não quebra fluxo.

from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional, Tuple

_SPEAKER_COLL = (os.environ.get("SPEAKER_STATE_COLL") or "platform_speaker_state").strip()
_TTL_SECONDS = int(os.environ.get("SPEAKER_STATE_TTL_SECONDS") or "21600")  # 6h

_mem: Dict[str, Tuple[Dict[str, Any], float]] = {}


def _now() -> float:
    return time.time()


def _only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _doc_id(wa_key: str, uid_owner: Optional[str] = None) -> str:
    # Multi-tenant: separa por uid_owner quando disponível
    wk = _only_digits(wa_key)
    u = (uid_owner or "").strip()
    if u:
        return f"{u}__{wk}"[:480]
    return wk[:480]


def _fs_client():
    try:
        from firebase_admin import firestore  # type: ignore
        return firestore.client()
    except Exception:
        return None


def _db_ready(db) -> bool:
    # Mesmo padrão do cache/kv: só considera se FIREBASE_PROJECT_ID estiver setado
    try:
        return bool(db) and bool((os.environ.get("FIREBASE_PROJECT_ID") or "").strip())
    except Exception:
        return False


def get_speaker_state(wa_key: str, uid_owner: Optional[str] = None) -> Dict[str, Any]:
    wa_key = (wa_key or "").strip()
    if not wa_key:
        return {}

    did = _doc_id(wa_key, uid_owner=uid_owner)
    now = _now()

    # 1) memória
    try:
        row, exp = _mem.get(did, ({}, 0.0))
        if exp and exp > now and isinstance(row, dict):
            return dict(row)
    except Exception:
        pass

    # 2) Firestore
    db = _fs_client()
    if _db_ready(db):
        try:
            snap = db.collection(_SPEAKER_COLL).document(did).get()
            data = (snap.to_dict() or {}) if snap else {}
            # compat: normaliza chaves
            if isinstance(data, dict):
                # last name used
                if "last_name_used_at" not in data:
                    v = (
                        data.get("lastNameUsedAtEpoch")
                        or data.get("last_name_used_at")
                        or data.get("last_name_used_at_epoch")
                    )
                    if v is not None:
                        try:
                            data["last_name_used_at"] = float(v)
                        except Exception:
                            pass
                if "ai_turns" in data:
                    try:
                        data["ai_turns"] = int(data.get("ai_turns") or 0)
                    except Exception:
                        data["ai_turns"] = 0
            # cache local
            _mem[did] = (dict(data), now + _TTL_SECONDS)
            return dict(data)
        except Exception as e:
            logging.debug("[speaker_state] firestore get falhou: %s", e)

    return {}


def bump_ai_turns(wa_key: str, uid_owner: Optional[str] = None) -> int:
    wa_key = (wa_key or "").strip()
    if not wa_key:
        return 0

    did = _doc_id(wa_key, uid_owner=uid_owner)
    now = _now()

    cur = get_speaker_state(wa_key, uid_owner=uid_owner) or {}
    try:
        n = int(cur.get("ai_turns") or 0) + 1
    except Exception:
        n = 1

    new_row = dict(cur)
    new_row["ai_turns"] = n
    new_row["updatedAtEpoch"] = now
    if "createdAtEpoch" not in new_row:
        new_row["createdAtEpoch"] = now

    # 1) memória
    _mem[did] = (dict(new_row), now + _TTL_SECONDS)

    # 2) Firestore (best-effort)
    db = _fs_client()
    if _db_ready(db):
        try:
            db.collection(_SPEAKER_COLL).document(did).set(new_row, merge=True)
        except Exception as e:
            logging.debug("[speaker_state] firestore set falhou: %s", e)

    return n


# ===============================
# BOOKING PENDENTE (Customer Final)
# ===============================

def set_pending_booking(wa_key: str, data: Dict[str, Any], uid_owner: Optional[str] = None):
    state = get_speaker_state(wa_key, uid_owner=uid_owner) or {}
    state["pending_booking"] = data
    did = _doc_id(wa_key, uid_owner=uid_owner)
    _mem[did] = (dict(state), _now() + _TTL_SECONDS)

    db = _fs_client()
    if _db_ready(db):
        try:
            db.collection(_SPEAKER_COLL).document(did).set(
                {"pending_booking": data},
                merge=True,
            )
        except Exception:
            pass


def get_pending_booking(wa_key: str, uid_owner: Optional[str] = None) -> Dict[str, Any]:
    state = get_speaker_state(wa_key, uid_owner=uid_owner) or {}
    return state.get("pending_booking") or {}


# ===============================
# ÚLTIMA COTAÇÃO (PREÇO/SERVIÇO) — Orçamentos
# ===============================

def set_last_quote(wa_key: str, data: Dict[str, Any], uid_owner: Optional[str] = None):
    """
    Guarda a última cotação inferida/confirmada na conversa:
      data = {"service": str, "price": float, "obs": str, "updatedAtEpoch": float}
    Safe-by-default: best-effort (memória + Firestore).
    """
    wa_key = (wa_key or "").strip()
    if not wa_key or not isinstance(data, dict):
        return

    now = _now()
    row = get_speaker_state(wa_key, uid_owner=uid_owner) or {}
    q = dict(data)
    if "updatedAtEpoch" not in q:
        q["updatedAtEpoch"] = now

    row["last_quote"] = q
    did = _doc_id(wa_key, uid_owner=uid_owner)
    _mem[did] = (dict(row), now + _TTL_SECONDS)

    db = _fs_client()
    if _db_ready(db):
        try:
            db.collection(_SPEAKER_COLL).document(did).set({"last_quote": q}, merge=True)
        except Exception:
            pass


def get_last_quote(wa_key: str, uid_owner: Optional[str] = None) -> Dict[str, Any]:
    """
    Retorna a última cotação salva (ou {}).
    """
    wa_key = (wa_key or "").strip()
    if not wa_key:
        return {}
    st = get_speaker_state(wa_key, uid_owner=uid_owner) or {}
    q = st.get("last_quote")
    return q if isinstance(q, dict) else {}
