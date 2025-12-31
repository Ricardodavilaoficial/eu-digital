# services/storage_quota.py
# Controle de quota de armazenamento por UID (best-effort, seguro por padrão)
#
# Objetivo:
# - Manter Storage Rules fechadas (sem read/write direto do browser)
# - Sempre que o BACKEND fizer upload/overwrite, ajustar usedBytes do MEI
# - Bloquear aumentos que ultrapassem maxBytes (default: 2GB) e devolver erro claro
#
# Observação:
# - Não é transação "atômica" entre GCS e Firestore; fazemos o melhor possível:
#   (1) calcula delta estimado, (2) reserva quota (txn), (3) faz upload,
#   (4) reconcilia com delta real e/ou desfaz reserva se falhar.
#
# Documento meta:
#   profissionais/{uid}/storage/meta
# Campos:
#   usedBytes (int), maxBytes (int), byCategory (map), updatedAt (server time)

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any

from services.db import db


@dataclass
class QuotaExceeded(Exception):
    used_bytes: int
    max_bytes: int
    delta_bytes: int
    category: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": "quota_exceeded",
            "usedBytes": int(self.used_bytes),
            "maxBytes": int(self.max_bytes),
            "deltaBytes": int(self.delta_bytes),
            "category": self.category,
        }


def _default_max_bytes() -> int:
    # 2GB por padrão (Starter)
    raw = os.environ.get("DEFAULT_STORAGE_MAX_BYTES", "2147483648") or "2147483648"
    try:
        v = int(raw)
        return v if v > 0 else 2147483648
    except Exception:
        return 2147483648


def _meta_ref(uid: str):
    return db.collection("profissionais").document(uid).collection("storage").document("meta")


def get_quota(uid: str) -> Dict[str, int]:
    ref = _meta_ref(uid)
    snap = ref.get()
    if not snap.exists:
        max_b = _default_max_bytes()
        return {"usedBytes": 0, "maxBytes": max_b}
    d = snap.to_dict() or {}
    return {
        "usedBytes": int(d.get("usedBytes") or 0),
        "maxBytes": int(d.get("maxBytes") or _default_max_bytes()),
    }


def reserve_bytes(uid: str, delta_bytes: int, category: str) -> None:
    """Reserva quota (somente delta > 0). Lança QuotaExceeded se estourar."""
    if not uid or delta_bytes <= 0:
        return

    ref = _meta_ref(uid)

    @db.transactional
    def _txn(txn):
        snap = ref.get(transaction=txn)
        d = snap.to_dict() if snap.exists else {}
        used = int((d or {}).get("usedBytes") or 0)
        max_b = int((d or {}).get("maxBytes") or _default_max_bytes())

        new_used = used + int(delta_bytes)
        if new_used > max_b:
            raise QuotaExceeded(used_bytes=used, max_bytes=max_b, delta_bytes=delta_bytes, category=category)

        by_cat = dict((d or {}).get("byCategory") or {})
        by_cat[category] = int(by_cat.get(category) or 0) + int(delta_bytes)

        txn.set(ref, {
            "usedBytes": new_used,
            "maxBytes": max_b,
            "byCategory": by_cat,
            "updatedAt": db.SERVER_TIMESTAMP,
        }, merge=True)

    _txn(db.transaction())


def adjust_bytes(uid: str, delta_bytes: int, category: str) -> None:
    """Ajuste pós-upload/rollback (delta pode ser negativo)."""
    if not uid or delta_bytes == 0:
        return

    ref = _meta_ref(uid)

    @db.transactional
    def _txn(txn):
        snap = ref.get(transaction=txn)
        d = snap.to_dict() if snap.exists else {}
        used = int((d or {}).get("usedBytes") or 0)
        max_b = int((d or {}).get("maxBytes") or _default_max_bytes())

        new_used = used + int(delta_bytes)
        if new_used < 0:
            new_used = 0

        # Se for ajuste positivo, também não deixa passar do máximo
        if delta_bytes > 0 and new_used > max_b:
            raise QuotaExceeded(used_bytes=used, max_bytes=max_b, delta_bytes=delta_bytes, category=category)

        by_cat = dict((d or {}).get("byCategory") or {})
        by_cat[category] = int(by_cat.get(category) or 0) + int(delta_bytes)
        if by_cat[category] < 0:
            by_cat[category] = 0

        txn.set(ref, {
            "usedBytes": new_used,
            "maxBytes": max_b,
            "byCategory": by_cat,
            "updatedAt": db.SERVER_TIMESTAMP,
        }, merge=True)

    _txn(db.transaction())
