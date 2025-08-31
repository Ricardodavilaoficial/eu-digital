# domain/pricing.py
"""
MEI Robô — Domínio de preços (V1.0 pré-produção)

Contrato estável:
    get_price(slug: str, uid: Optional[str] = None) -> {"valor": Any, "origem": str}

- Não altera comportamento atual (não é plugado no wa_bot ainda).
- Apenas leitura de dados. Sem efeitos colaterais.
- Busca preço a partir de 3 fontes (quando disponíveis):
    (A) profissionais/{uid} campo 'precos' (mapa ou itens[])
    (B) profissionais/{uid}/precos (coleção)
    (C) profissionais/{uid}/produtosEServicos (coleção)
      Esperado (produtosEServicos): slug, nome, sinonimos[], duracaoMin, precoBase, variacoes[].

Regras de matching (na ordem):
  1) slug exato (campo 'slug')
  2) slug presente em 'variacoes' ou 'sinonimos'
  3) slug contido no nome (nomeLower contém)
Primeiro hit define o resultado. Retorna {"valor": <preco|precoBase|valor>, "origem": "map|precos|produtosEServicos|not_found"}.
"""

from typing import Optional, Dict, Any, List, Tuple
import logging
import unicodedata
import re
import os

# ========== Firestore client (imports tolerantes) ==========
_DB_CLIENT = None
_LAST_ERR = None

try:
    from services import db as _dbsvc_abs  # type: ignore
    _DB_CLIENT = getattr(_dbsvc_abs, "db", None)
except Exception as e_abs:
    _LAST_ERR = f"abs:{e_abs}"
    _dbsvc_abs = None  # type: ignore

if _DB_CLIENT is None:
    try:
        from ..services import db as _dbsvc_rel  # type: ignore
        _DB_CLIENT = getattr(_dbsvc_rel, "db", None)
    except Exception as e_rel:
        _LAST_ERR = (_LAST_ERR or "") + f" | rel:{e_rel}"
        _dbsvc_rel = None  # type: ignore

def _strip_accents_lower(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()

def _get_doc_ref(path: str):
    if _DB_CLIENT is None:
        return None
    parts = [p for p in (path or "").split("/") if p]
    if not parts or len(parts) % 2 != 0:
        return None  # precisa ser documento (número PAR de segmentos)
    ref = _DB_CLIENT
    for i, part in enumerate(parts):
        if i % 2 == 0:
            ref = ref.collection(part)
        else:
            ref = ref.document(part)
    return ref

def _get_col_ref(path: str):
    if _DB_CLIENT is None:
        return None
    parts = [p for p in (path or "").split("/") if p]
    if not parts or len(parts) % 2 != 1:
        return None  # precisa ser coleção (número ÍMPAR de segmentos)
    ref = _DB_CLIENT
    for i, part in enumerate(parts):
        if i % 2 == 0:
            ref = ref.collection(part)
        else:
            ref = ref.document(part)
    return ref

def _get_doc(path: str) -> Optional[Dict[str, Any]]:
    ref = _get_doc_ref(path)
    if ref is None:
        return None
    try:
        snap = ref.get()
        return snap.to_dict() if getattr(snap, "exists", False) else None
    except Exception as e:
        logging.info("[pricing] get doc falhou: %s", e)
        return None

def _list_col(path: str, limit: int = 500) -> List[Dict[str, Any]]:
    col = _get_col_ref(path)
    out: List[Dict[str, Any]] = []
    if col is None:
        return out
    try:
        for d in col.limit(int(limit)).stream():  # type: ignore
            obj = d.to_dict() or {}
            obj["_id"] = d.id
            out.append(obj)
    except Exception as e:
        logging.info("[pricing] list col falhou: %s", e)
    return out

def _normalize_item(it: Dict[str, Any]) -> Dict[str, Any]:
    """Gera visão padronizada: nome, nomeLower, preco, duracaoMin, slug, sinonimos/variacoes."""
    nome = it.get("nome") or it.get("nomeLower") or it.get("_id") or "serviço"
    preco = it.get("preco", it.get("valor", it.get("precoBase")))
    dur = it.get("duracaoMin", it.get("duracaoPadraoMin", it.get("duracao")))
    slug = it.get("slug")
    sinonimos = it.get("sinonimos") or it.get("sinônimos") or []
    variacoes = it.get("variacoes") or []
    out = {**it}
    out["nome"] = str(nome)
    out["nomeLower"] = _strip_accents_lower(out["nome"])
    out["preco"] = preco
    if dur is not None:
        out["duracaoMin"] = dur
    if slug:
        out["slug"] = str(slug).strip()
    if isinstance(sinonimos, list):
        out["sinonimos"] = [str(x).strip() for x in sinonimos if x]
    if isinstance(variacoes, list):
        out["variacoes"] = [str(x).strip() for x in variacoes if x]
    return out

def _load_all_items(uid: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Carrega e normaliza itens de preço de todas as fontes (A, B, C)."""
    items: List[Dict[str, Any]] = []
    counts = {"map": 0, "precos": 0, "ps": 0}

    # (A) profissionais/{uid}.precos
    prof = _get_doc(f"profissionais/{uid}") or {}
    precos = prof.get("precos")
    if isinstance(precos, dict):
        if "itens" in precos and isinstance(precos["itens"], list):
            for it in precos["itens"]:
                if not isinstance(it, dict):
                    continue
                if it.get("ativo", True):
                    items.append(_normalize_item(it))
            counts["map"] = len(precos["itens"])
        else:
            for nome, valor in precos.items():
                items.append(_normalize_item({"nome": nome, "preco": valor, "ativo": True}))
            counts["map"] = len(precos)

    # (B) profissionais/{uid}/precos
    col_b = _list_col(f"profissionais/{uid}/precos", limit=500)
    for it in col_b:
        if it.get("ativo", True):
            items.append(_normalize_item(it))
    counts["precos"] = len(col_b)

    # (C) profissionais/{uid}/produtosEServicos
    col_c = _list_col(f"profissionais/{uid}/produtosEServicos", limit=500)
    for it in col_c:
        if it.get("ativo", True):
            items.append(_normalize_item(it))
    counts["ps"] = len(col_c)

    # dedup por nomeLower (primeiro vence)
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for it in items:
        key = (it.get("nomeLower") or "").strip()
        if not key or it.get("ativo") is False:
            continue
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    return uniq, counts

def _match_item(items: List[Dict[str, Any]], slug: str) -> Optional[Tuple[Dict[str, Any], str]]:
    """Retorna (item, origem) se encontrar, senão None."""
    t = _strip_accents_lower(slug)

    # 1) slug exato
    for it in items:
        if (it.get("slug") or "").strip().lower() == t:
            origem = it.get("_origem") or it.get("origem") or "desconhecida"
            return it, origem

    # 2) slug nas listas 'variacoes' / 'sinonimos'
    for it in items:
        var = [ _strip_accents_lower(x) for x in (it.get("variacoes") or []) ]
        sin = [ _strip_accents_lower(x) for x in (it.get("sinonimos") or []) ]
        if t in var or t in sin:
            origem = it.get("_origem") or it.get("origem") or "desconhecida"
            return it, origem

    # 3) trecho no nome
    for it in items:
        if t and t in (it.get("nomeLower") or ""):
            origem = it.get("_origem") or it.get("origem") or "desconhecida"
            return it, origem

    return None

def get_price(slug: str, uid: Optional[str] = None) -> Dict[str, Any]:
    """
    Retorna um dicionário {"valor": Any, "origem": str}.
    'origem' ∈ {"map","precos","produtosEServicos","not_found"}.
    """
    if not slug or not str(slug).strip():
        return {"valor": None, "origem": "bad_request"}

    uid_final = (uid or os.getenv("UID_DEFAULT") or "").strip()
    if not uid_final:
        # Sem UID não conseguimos ler os caminhos do profissional
        return {"valor": None, "origem": "not_found"}

    # Sem cliente de DB → not_found (não falha o contrato)
    if _DB_CLIENT is None:
        logging.info("[pricing] DB client indisponível: %s", _LAST_ERR)
        return {"valor": None, "origem": "not_found"}

    items, counts = _load_all_items(uid_final)

    # anotar origem por fonte com heurística simples (pela presença de campos típicos)
    for it in items:
        if "precoBase" in it or "sinonimos" in it or "variacoes" in it or "slug" in it:
            it["_origem"] = "produtosEServicos"
        elif "_id" in it:
            it["_origem"] = "precos"   # veio de coleção
        else:
            it["_origem"] = "map"      # veio do mapa do doc principal

    hit = _match_item(items, slug)
    if not hit:
        return {"valor": None, "origem": "not_found"}

    item, origem = hit
    valor = item.get("preco")
    if valor in (None, ""):
        valor = item.get("precoBase", item.get("valor"))
    return {"valor": valor, "origem": origem}
