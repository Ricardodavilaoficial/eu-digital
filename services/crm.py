# services/crm.py
# CRM leve (clientes, mídia pessoal, interações) apoiado em Firestore + Storage
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

_SP = timezone(timedelta(hours=-3))

# Firestore
try:
    from services.db import get_db
except Exception:
    get_db = None

# Storage
try:
    from services.storage_mgr import upload_bytes, sign_url
except Exception:
    upload_bytes = None
    sign_url = None

def _now_iso() -> str:
    return datetime.now(_SP).isoformat()

def _year_month() -> (str, str):
    now = datetime.now(_SP)
    return now.strftime("%Y"), now.strftime("%m")

def _sanitize_id(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\-]", "_", s, flags=re.U)
    return s[:80] or "id"

# ---------- Clientes ----------
def create_or_get_client(uid: str, *, waId: Optional[str] = None, phone: Optional[str] = None, name: Optional[str] = None, tags: Optional[List[str]] = None) -> str:
    db = get_db()
    base = db.collection(f"profissionais/{uid}/clientes")
    # busca por waId
    if waId:
        q = base.where("waId", "==", waId).limit(1).stream()
        for d in q:
            return d.id
    # busca por phone
    if phone and not waId:
        q = base.where("phone", "==", phone).limit(1).stream()
        for d in q:
            return d.id
    # cria
    ref = base.document()
    ref.set({
        "name": name or "",
        "waId": waId or "",
        "phone": phone or "",
        "tags": tags or [],
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
    })
    return ref.id

# ---------- Mídia (pessoal/relacionamento) ----------
def add_media_from_bytes(uid: str, cliente_id: str, data: bytes, *, content_type: str, caption: str = "", tags: Optional[List[str]] = None, source: str = "whatsapp") -> Dict[str, Any]:
    if upload_bytes is None:
        raise RuntimeError("storage_mgr indisponível")
    y, m = _year_month()
    gs_prefix = f"profissionais/{uid}/clientes/{_sanitize_id(cliente_id)}/media/{y}/{m}"
    up = upload_bytes(gs_prefix, data, content_type=content_type, metadata={"ownerUid": uid, "clienteId": cliente_id, "source": source})
    # salva metadado
    db = get_db()
    ref = db.collection(f"profissionais/{uid}/clientes/{cliente_id}/media").document()
    doc = {
        "filePath": up["gs_path"],
        "contentType": up["contentType"],
        "bytes": up["size"],
        "sha256": up["sha256"],
        "caption": caption or "",
        "tags": tags or [],
        "source": source,
        "createdAt": _now_iso(),
        "signedUrlCache": {
            "url": up["signedUrl"],
            "expiresAt": None  # opcional: podemos armazenar TTL se quisermos renovar depois
        }
    }
    ref.set(doc)
    doc["_id"] = ref.id
    return doc

# ---------- Interações (texto/nota) ----------
def log_interaction(uid: str, cliente_id: str, *, type: str, text: str, meta: Optional[Dict[str, Any]] = None) -> str:
    db = get_db()
    ref = db.collection(f"profissionais/{uid}/interactions").document()
    ref.set({
        "clienteId": cliente_id,
        "type": type,
        "text": (text or "")[:2000],
        "meta": meta or {},
        "createdAt": _now_iso(),
    })
    return ref.id
