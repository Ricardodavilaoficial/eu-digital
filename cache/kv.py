# cache/kv.py
"""
MEI Robô — KV Cache com TTL (Firestore + memória) — V1.0

Uso:
    from cache.kv import make_key, put, get
    k = make_key(uid, intent="precos", slug="corte-masculino")
    put(uid, k, {"texto": "Corte: R$ 40"}, ttl_sec=3600)
    v = get(uid, k)  # -> {"texto": "Corte: R$ 40"} ou None se expirado

Backend:
  - Firestore quando disponível (_db_ready() = True)
      Doc: profissionais/{uid}/cache/{docId}
      Campos: value (qualquer JSON), expAt (ISO), createdAt, updatedAt
  - Memória (processo) quando sem Firebase → TTL local
"""

from __future__ import annotations
from typing import Any, Optional, Dict, Tuple
from datetime import datetime, timedelta, timezone
import threading
import re
import os
import json
import logging

# ================== TZ/tempo ==================
UTC = timezone.utc

def _now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)

def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")

# ================== Firestore (tolerante) ==================
_DB = None
_LAST_ERR = None
try:
    from services import db as _db_abs  # type: ignore
    _DB = getattr(_db_abs, "db", None)
except Exception as e_abs:
    _LAST_ERR = f"abs:{e_abs}"
    _db_abs = None  # type: ignore

if _DB is None:
    try:
        from ..services import db as _db_rel  # type: ignore
        _DB = getattr(_db_rel, "db", None)
    except Exception as e_rel:
        _LAST_ERR = (_LAST_ERR or "") + f" | rel:{e_rel}"
        _db_rel = None  # type: ignore

def _db_ready() -> bool:
    """Firestore só é usado se houver client E FIREBASE_PROJECT_ID definido."""
    if os.getenv("CACHE_BACKEND", "").lower() == "memory":
        return False
    return (_DB is not None) and bool(os.getenv("FIREBASE_PROJECT_ID"))

# ================== Chaves ==================
_DOC_ID_MAX = 1400  # margem para limites do Firestore

def _sanitize_doc_id(s: str) -> str:
    s = re.sub(r"[^\w\-\.@:+=, ]+", "_", s)  # remove caracteres problemáticos
    if len(s) > _DOC_ID_MAX:
        s = s[:_DOC_ID_MAX]
    return s

def make_key(uid: str, intent: str, slug: str) -> str:
    """Chave normalizada para (uid,intent,slug)."""
    uid = (uid or "").strip()
    intent = (intent or "").strip().lower()
    slug = (slug or "").strip().lower()
    # espaço → hífen, remove acentos simples
    def _norm(t: str) -> str:
        try:
            import unicodedata
            t = unicodedata.normalize("NFKD", t)
            t = "".join(ch for ch in t if not unicodedata.combining(ch))
        except Exception:
            pass
        t = re.sub(r"\s+", "-", t)
        return t
    return _sanitize_doc_id(f"{_norm(uid)}::{_norm(intent)}::{_norm(slug)}")

# ================== Memória (fallback) ==================
_mem: Dict[str, Tuple[Any, float]] = {}
_mem_lock = threading.Lock()
_MEM_MAX = 5000  # limite simples

def _mem_put(doc_id: str, value: Any, ttl_sec: int) -> bool:
    exp_ts = (_now_utc() + timedelta(seconds=max(1, int(ttl_sec)))).timestamp()
    with _mem_lock:
        if len(_mem) >= _MEM_MAX:
            # política simples: drop de itens expirados, senão FIFO
            expired = [k for k, (_, ts) in _mem.items() if ts <= _now_utc().timestamp()]
            for k in expired[:1000]:
                _mem.pop(k, None)
            if len(_mem) >= _MEM_MAX:
                # remove um item arbitrário
                _mem.pop(next(iter(_mem)), None)
        _mem[doc_id] = (value, exp_ts)
    return True

def _mem_get(doc_id: str) -> Optional[Any]:
    with _mem_lock:
        row = _mem.get(doc_id)
        if not row:
            return None
        value, exp_ts = row
        if exp_ts <= _now_utc().timestamp():
            _mem.pop(doc_id, None)
            return None
        return value

def _mem_del(doc_id: str) -> bool:
    with _mem_lock:
        return _mem.pop(doc_id, None) is not None

def _mem_cleanup(limit: int = 200) -> int:
    removed = 0
    now_ts = _now_utc().timestamp()
    with _mem_lock:
        for k in list(_mem.keys())[: max(10, limit)]:
            _, exp_ts = _mem.get(k, (None, 0))
            if exp_ts <= now_ts:
                _mem.pop(k, None)
                removed += 1
    return removed

# ================== Firestore helpers ==================
def _cache_doc(uid: str, doc_id: str):
    return _DB.collection(f"profissionais/{uid}/cache").document(doc_id)

# ================== API pública ==================
def put(uid: str, key: str, value: Any, ttl_sec: int = 3600) -> bool:
    """
    Salva um valor com TTL (segundos). Retorna True em caso de sucesso.
    """
    uid = (uid or "").strip()
    if not uid or not key:
        return False
    doc_id = _sanitize_doc_id(key)

    if not _db_ready():
        return _mem_put(doc_id, value, ttl_sec)

    try:
        now = _now_utc()
        body = {
            "value": value,
            "expAt": _iso(now + timedelta(seconds=max(1, int(ttl_sec)))),
            "createdAt": _iso(now),
            "updatedAt": _iso(now),
        }
        _cache_doc(uid, doc_id).set(body)
        return True
    except Exception as e:
        logging.info("[cache.kv][put] fallback to memory: %s", e)
        return _mem_put(doc_id, value, ttl_sec)

def get(uid: str, key: str) -> Optional[Any]:
    """
    Lê um valor respeitando TTL. Expirado → None (e apaga no backend quando possível).
    """
    uid = (uid or "").strip()
    if not uid or not key:
        return None
    doc_id = _sanitize_doc_id(key)

    if not _db_ready():
        return _mem_get(doc_id)

    try:
        snap = _cache_doc(uid, doc_id).get()
        if not getattr(snap, "exists", False):
            return None
        obj = snap.to_dict() or {}
        exp_s = obj.get("expAt")
        if not exp_s:
            return None
        try:
            exp_dt = datetime.fromisoformat(str(exp_s).replace("Z", "+00:00"))
        except Exception:
            return None
        if exp_dt <= _now_utc():
            # expirado → remove
            try:
                _cache_doc(uid, doc_id).delete()
            except Exception:
                pass
            return None
        return obj.get("value")
    except Exception as e:
        logging.info("[cache.kv][get] fallback to memory: %s", e)
        return _mem_get(doc_id)

def delete(uid: str, key: str) -> bool:
    uid = (uid or "").strip()
    if not uid or not key:
        return False
    doc_id = _sanitize_doc_id(key)

    if not _db_ready():
        return _mem_del(doc_id)

    try:
        _cache_doc(uid, doc_id).delete()
        return True
    except Exception as e:
        logging.info("[cache.kv][delete] fallback to memory: %s", e)
        return _mem_del(doc_id)

def cleanup_expired(uid: Optional[str] = None, limit: int = 200) -> int:
    """
    Remove chaves expiradas. Em memória: remove até `limit`. Em Firestore: best-effort (somente memória).
    Retorna quantidade removida.
    """
    if not _db_ready():
        return _mem_cleanup(limit=limit)
    # Para Firestore, manteremos cleanup manual/externo (query por expAt < now requer índice).
    # Aqui retornamos 0 e deixamos a remoção preguiçosa do `get()` fazer o serviço.
    return 0
