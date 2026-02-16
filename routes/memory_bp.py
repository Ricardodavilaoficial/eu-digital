# routes/memory_bp.py
# Memória Inteligente por Contato — produção, econômica e idempotente
#
# - Não salva chat
# - Não cresce infinito
# - lastEvent no doc do contato (1 read)
# - timeline em subcoleção com prune e dedupe

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, request, jsonify, g

from services.auth import auth_required  # type: ignore
from services.db import db  # type: ignore

memory_bp = Blueprint("memory_bp", __name__, url_prefix="/api/memory")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _wa_key_digits(wa_key: str) -> str:
    # waKey canônico do seu projeto (BR): cc+ddd+local8, remove 9
    d = _only_digits(wa_key)
    if d.startswith("55") and len(d) == 13:
        d = d[:4] + d[5:]
    # pega cc+ddd+local8
    if d.startswith("55") and len(d) >= 12:
        cc = d[:2]
        ddd = d[2:4]
        local8 = d[-8:]
        return f"{cc}{ddd}{local8}"
    return d


def _resolve_contact_ref(uid: str, wa_key: str):
    """
    Resolve contato em profissionais/{uid}/clientes pelo campo:
      telefone_v2.waKey == <waKeyDigits>
    Fallback: waKey == <waKeyDigits> e telefone == <digits>
    """
    if not uid or not wa_key:
        return None, None

    key = _wa_key_digits(wa_key)
    col = db.collection("profissionais").document(uid).collection("clientes")

    # 1) canônico
    try:
        q = col.where("telefone_v2.waKey", "==", key).limit(1).stream()
        for doc in q:
            return doc.reference, (doc.to_dict() or {})
    except Exception:
        pass

    # 2) compat: waKey flat
    try:
        q = col.where("waKey", "==", key).limit(1).stream()
        for doc in q:
            return doc.reference, (doc.to_dict() or {})
    except Exception:
        pass

    # 3) compat: telefone digits
    try:
        tel = _only_digits(wa_key)
        if tel:
            q = col.where("telefone", "==", tel).limit(1).stream()
            for doc in q:
                return doc.reference, (doc.to_dict() or {})
    except Exception:
        pass

    return None, None


@memory_bp.get("/contact-last")
@auth_required
def memory_contact_last():
    """
    GET /api/memory/contact-last?waKey=...
    1 read: doc do contato -> memory.lastEvent/memory.summary/memory.flags
    """
    uid = getattr(getattr(g, "user", None), "uid", None)

    wa_key = (request.args.get("waKey") or "").strip()
    if not uid or not wa_key:
        return jsonify({"ok": False, "error": "missing_uid_or_waKey"}), 400

    ref, data = _resolve_contact_ref(uid, wa_key)
    if not ref:
        return jsonify({"ok": True, "found": False}), 200

    mem = (data.get("memory") or {}) if isinstance(data, dict) else {}
    out = {
        "ok": True,
        "found": True,
        "contactId": ref.id,
        "memory": {
            "lastEvent": mem.get("lastEvent"),
            "summary": mem.get("summary") or "",
            "flags": mem.get("flags") or {},
            "updatedAt": mem.get("updatedAt"),
        }
    }
    return jsonify(out), 200


@memory_bp.post("/contact-event")
@auth_required
def memory_contact_event():
    """
    POST /api/memory/contact-event
    Body:
      {
        "waKey": "...",
        "type": "info_cliente|andamento|documento|alteracao_dado|...",
        "text": "resumo curto",
        "importance": 0-3,
        "dedupeKey": "hash curto (opcional)"
      }
    Regras:
    - grava só se tiver contato resolvido
    - dedupe por dedupeKey (se vier)
    - atualiza memory.lastEvent (doc principal)
    - prune: mantém 20 recentes + preserva importance=3
    """
    uid = getattr(getattr(g, "user", None), "uid", None)
    if not uid:
        return jsonify({"ok": False, "error": "unauthenticated"}), 401

    body = request.get_json(silent=True) or {}
    wa_key = (body.get("waKey") or "").strip()
    ev_type = (body.get("type") or "").strip()[:32]
    text = (body.get("text") or "").strip()
    try:
        importance = int(body.get("importance") or 0)
    except Exception:
        importance = 0
    importance = max(0, min(3, importance))
    dedupe_key = (body.get("dedupeKey") or "").strip()[:64]

    if not wa_key or not ev_type or not text:
        return jsonify({"ok": False, "error": "missing_fields", "need": ["waKey", "type", "text"]}), 400
    if len(text) > 260:
        text = text[:257].rstrip() + "..."

    ref, _ = _resolve_contact_ref(uid, wa_key)
    if not ref:
        return jsonify({"ok": True, "saved": False, "reason": "contact_not_found"}), 200

    # delega pro store (mantém rota limpa)
    from services.contact_memory_store import save_event_for_contact  # type: ignore
    res = save_event_for_contact(
        contact_ref=ref,
        wa_key=wa_key,
        ev_type=ev_type,
        text=text,
        importance=importance,
        dedupe_key=dedupe_key,
    )
    return jsonify(res), (200 if res.get("ok") else 500)
