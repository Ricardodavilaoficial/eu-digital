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

# Reset de turnos por inatividade (evita LEAD “carregar” turns por dias e cair cedo no Módulo 2)
# - LEAD (sem uid_owner): default 24h
# - CUSTOMER FINAL (com uid_owner): default 7 dias
_LEAD_RESET_SECONDS = int(os.environ.get("LEAD_AI_TURNS_RESET_SECONDS") or "86400")
_CUSTOMER_RESET_SECONDS = int(os.environ.get("CUSTOMER_AI_TURNS_RESET_SECONDS") or "604800")

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

def _apply_inactivity_reset(
    did: str,
    data: Dict[str, Any],
    now: float,
    uid_owner: Optional[str],
    db,
) -> Dict[str, Any]:
    """
    Regra de produto:
    - LEAD (uid_owner vazio): a conversa “recomeça” após janela de inatividade (default 24h).
      -> zera ai_turns e limpa force_operational (para não cair no Módulo 2 por “histórico antigo”).
    - CUSTOMER FINAL (uid_owner presente): janela maior (default 7 dias).
    """
    try:
        if not isinstance(data, dict) or not data:
            return data or {}

        u = (uid_owner or "").strip()
        reset_after = _CUSTOMER_RESET_SECONDS if u else _LEAD_RESET_SECONDS
        if reset_after <= 0:
            return data

        last = data.get("updatedAtEpoch")
        try:
            last_ts = float(last) if last is not None else 0.0
        except Exception:
            last_ts = 0.0

        # Se não tem updatedAtEpoch, não inventa reset.
        if last_ts <= 0:
            return data

        stale = (now - last_ts) > float(reset_after)
        if not stale:
            return data

        # Reset efetivo
        new_row = dict(data)
        new_row["ai_turns"] = 0
        new_row["force_operational"] = False
        new_row["force_operational_reason"] = ""
        new_row["updatedAtEpoch"] = now  # marca “novo ciclo”

        # best-effort writeback (pra não resetar toda hora)
        if _db_ready(db):
            try:
                db.collection(_SPEAKER_COLL).document(did).set(
                    {
                        "ai_turns": 0,
                        "force_operational": False,
                        "force_operational_reason": "",
                        "updatedAtEpoch": now,
                    },
                    merge=True,
                )
            except Exception:
                pass

        return new_row
    except Exception:
        return data




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
            out = dict(row)
            db = _fs_client()
            out = _apply_inactivity_reset(did, out, now, uid_owner, db)
            _mem[did] = (dict(out), now + _TTL_SECONDS)
            return dict(out)
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
            # ✅ Reset por inatividade (LEAD vs CUSTOMER)
            data = _apply_inactivity_reset(did, dict(data), now, uid_owner, db)

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


# ===============================
# RUNTIME FLAGS (Módulo 1 → Módulo 2)
# ===============================

def set_force_operational(wa_key: str, value: bool = True, reason: str = "", uid_owner: Optional[str] = None):
    """Força pular o Conversational Front (Módulo 1) e ir direto ao operacional (Módulo 2)."""
    wa_key = (wa_key or "").strip()
    if not wa_key:
        return

    did = _doc_id(wa_key, uid_owner=uid_owner)
    now = _now()

    cur = get_speaker_state(wa_key, uid_owner=uid_owner) or {}
    row = dict(cur)
    row["force_operational"] = bool(value)
    if reason:
        row["force_operational_reason"] = str(reason)[:200]
    row["updatedAtEpoch"] = now
    if "createdAtEpoch" not in row:
        row["createdAtEpoch"] = now

    _mem[did] = (dict(row), now + _TTL_SECONDS)

    db = _fs_client()
    if _db_ready(db):
        try:
            db.collection(_SPEAKER_COLL).document(did).set(
                {
                    "force_operational": bool(value),
                    "force_operational_reason": str(reason)[:200] if reason else "",
                    "updatedAtEpoch": now,
                },
                merge=True,
            )
        except Exception:
            pass


def is_force_operational(wa_key: str, uid_owner: Optional[str] = None) -> bool:
    st = get_speaker_state(wa_key, uid_owner=uid_owner) or {}
    try:
        return bool(st.get("force_operational"))
    except Exception:
        return False

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
