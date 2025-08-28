# services/professions.py
# Registro global de profissões + merge com perfil do profissional (overrides)
import re
from typing import Dict, Any, List, Optional

# Firestore helpers tolerantes
try:
    from services.db import get_db, get_doc
except Exception:
    get_db = None
    def get_doc(_): return None

def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s\-]", "", s, flags=re.U)
    s = re.sub(r"\s+", "-", s, flags=re.U)
    s = re.sub(r"-{2,}", "-", s)
    return s[:60] or "profissao"

def _list_collection(col_path: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Lista rápida sem depender de helper externo."""
    try:
        db = get_db()
        col = db.collection(col_path).limit(limit).stream()
        out = []
        for d in col:
            obj = d.to_dict() or {}
            obj["_id"] = d.id
            out.append(obj)
        return out
    except Exception:
        return []

def get_profession_doc(slug: str) -> Dict[str, Any]:
    doc = get_doc(f"professions/{slug}") or {}
    # defaults mínimo
    doc.setdefault("title", slug.replace("-", " ").title())
    doc.setdefault("version", 1)
    doc.setdefault("defaultAliases", {})
    doc.setdefault("defaultCopyBank", {})
    doc.setdefault("defaultFaqKeys", ["endereco","horarios","telefone","pix"])
    return doc

def ensure_profession(slug_or_name: str) -> str:
    """Garante doc base em professions/<slug>. Retorna slug."""
    try:
        from services.db import set_doc
    except Exception:
        set_doc = None
    slug = _slugify(slug_or_name)
    existing = get_doc(f"professions/{slug}")
    if existing is None and set_doc:
        set_doc(f"professions/{slug}", {
            "title": slug_or_name,
            "version": 1,
            "defaultAliases": {},
            "defaultCopyBank": {},
            "defaultFaqKeys": ["endereco","horarios","telefone","pix"],
        })
    return slug

def list_professions(limit: int = 200) -> List[Dict[str, Any]]:
    return _list_collection("professions", limit=limit)

def resolve_professional_context(uid: str) -> Dict[str, Any]:
    """Merge do global (professions/<slug>) com overrides do profissional (profissionais/{uid})."""
    pro = get_doc(f"profissionais/{uid}") or {}
    slug = pro.get("profissao") or ""
    slug = _slugify(slug)
    base = get_profession_doc(slug) if slug else {"defaultAliases":{}, "defaultCopyBank":{}}
    ctx: Dict[str, Any] = {
        "profissao": slug,
        "especializacoes": pro.get("especializacoes") or [pro.get("especializacao1"), pro.get("especializacao2")],
        "aliases": dict(base.get("defaultAliases") or {}),
        "copy_bank_defaults": dict(base.get("defaultCopyBank") or {}),
        "faq_keys": list(base.get("defaultFaqKeys") or []),
    }
    # overrides do profissional
    if isinstance(pro.get("aliases"), dict):
        ctx["aliases"].update(pro["aliases"])
    return ctx
