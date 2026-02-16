# services/contact_memory_store.py
# Store de Memória por Contato: dedupe + lastEvent + prune
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from services.db import db  # type: ignore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha12(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def _make_dedupe_key(ev_type: str, text: str, wa_key: str) -> str:
    base = f"{ev_type}|{text.strip().lower()}|{wa_key}"
    return _sha12(base)


def _get_contact_mem(data: Dict[str, Any]) -> Dict[str, Any]:
    mem = data.get("memory")
    return mem if isinstance(mem, dict) else {}


def _timeline_col(contact_ref):
    return contact_ref.collection("timeline")


def _is_duplicate(contact_ref, dedupe_key: str) -> bool:
    if not dedupe_key:
        return False
    try:
        q = _timeline_col(contact_ref).where("dedupeKey", "==", dedupe_key).limit(1).stream()
        for _ in q:
            return True
        return False
    except Exception:
        # se a query falhar, não bloqueia; segue
        return False


def _prune_timeline(contact_ref, keep_recent: int = 20) -> Tuple[int, int]:
    """
    Mantém:
      - até keep_recent itens (por recência)
      - + preserva todos importance=3 (mesmo se antigos)
    Retorna (scanned, deleted)
    """
    try:
        docs = list(_timeline_col(contact_ref).order_by("createdAt", direction="DESCENDING").limit(80).stream())
    except Exception:
        return (0, 0)

    keep_ids = set()
    deleted = 0

    # 1) mantém os N mais recentes
    for d in docs[:keep_recent]:
        keep_ids.add(d.id)

    # 2) preserva importance=3
    for d in docs:
        data = d.to_dict() or {}
        if int(data.get("importance") or 0) >= 3:
            keep_ids.add(d.id)

    # 3) apaga o resto (do lote lido)
    for d in docs:
        if d.id in keep_ids:
            continue
        try:
            d.reference.delete()
            deleted += 1
        except Exception:
            pass

    return (len(docs), deleted)


def save_event_for_contact(
    contact_ref,
    wa_key: str,
    ev_type: str,
    text: str,
    importance: int = 0,
    dedupe_key: str = "",
) -> Dict[str, Any]:
    """
    Idempotente na prática:
      - se dedupeKey existir e já existir doc com ela -> não grava
      - se dedupeKey vazio -> cria um dedupeKey determinístico
    Atualiza doc do contato:
      memory.lastEvent, memory.updatedAt
    """
    try:
        dedupe = (dedupe_key or "").strip() or _make_dedupe_key(ev_type, text, wa_key)
        if _is_duplicate(contact_ref, dedupe):
            return {"ok": True, "saved": False, "duplicate": True, "dedupeKey": dedupe}

        now = _now_iso()
        ev = {
            "createdAt": now,
            "type": ev_type[:32],
            "text": text[:260],
            "importance": max(0, min(3, int(importance or 0))),
            "dedupeKey": dedupe[:64],
            "source": "bot",
        }

        # grava evento
        _timeline_col(contact_ref).document().set(ev, merge=False)

        # atualiza ponteiro econômico no doc principal
        contact_ref.set({
            "memory": {
                "lastEvent": ev,
                "updatedAt": now,
            }
        }, merge=True)

        scanned, deleted = _prune_timeline(contact_ref, keep_recent=20)

        return {
            "ok": True,
            "saved": True,
            "dedupeKey": dedupe,
            "prune": {"scanned": scanned, "deleted": deleted},
        }
    except Exception as e:
        return {"ok": False, "error": "save_failed", "detail": str(e)[:180]}
