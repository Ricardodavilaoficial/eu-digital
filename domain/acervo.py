# domain/acervo.py
# Engine do Acervo do MEI Robô (v1)
#
# Responsabilidade:
# - Ler itens do acervo do MEI (profissionais/{uid}/acervo)
# - Rankear com base em titulo/tags/resumoCurto (+ opcionalmente embeddings)
# - Montar contexto e chamar GPT-mini para gerar resposta curta
#
# Função principal:
#   query_acervo_for_uid(uid: str, pergunta: str, max_tokens: int = 120) -> dict
#
# Resposta esperada:
#   {
#     "answer": str | None,
#     "usedDocs": [
#       {"id": "...", "titulo": "...", "tags": [...], "prioridade": 1, ...}
#     ],
#     "reason": "ok" | "no_docs" | "no_relevant_docs" | "no_llm_available" | "llm_error"
#   }

from __future__ import annotations

from typing import List, Dict, Any, Optional
import logging
import math
import re

# Firestore client compartilhado do projeto
try:
    from services.db import db  # type: ignore
except Exception:  # pragma: no cover
    db = None  # type: ignore

# LLM mini (GPT-mini) – pode não existir em todos os ambientes
try:
    from services.llm import gpt_mini_complete  # type: ignore
except Exception:  # pragma: no cover
    gpt_mini_complete = None  # type: ignore

# Embeddings mini – opcional
try:
    from services.embeddings import get_mini_embedding  # type: ignore
except Exception:  # pragma: no cover
    get_mini_embedding = None  # type: ignore


# Limites de sanidade
_MAX_DOCS = 50
_MAX_CHARS_CONTEXT_PER_DOC = 900


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9áéíóúâêôãõç]+", text.lower()) if t]


def _score_candidate(pergunta: str, item: Dict[str, Any]) -> float:
    """
    Score simples baseado em overlap de tokens entre pergunta e:
      - titulo
      - tags
      - resumoCurto (quando houver)

    Ajustes:
      - prioridade: prioridade 1 ganha bônus, prioridade alta (ex.: 3) perde um pouco
      - habilitado=False → score 0 (ignora)
    """
    if not item.get("habilitado", True):
        return 0.0

    q_tokens = set(_tokenize(pergunta))
    bag: List[str] = []

    titulo = str(item.get("titulo") or "")
    bag.extend(_tokenize(titulo))

    tags = item.get("tags") or []
    if isinstance(tags, list):
        for t in tags:
            bag.extend(_tokenize(str(t)))

    resumo = str(item.get("resumoCurto") or "")
    if resumo:
        bag.extend(_tokenize(resumo))

    if not bag:
        return 0.0

    b_tokens = set(bag)
    inter = q_tokens.intersection(b_tokens)
    base_score = float(len(inter))

    # prioridade (1 = mais importante)
    try:
        prioridade = int(item.get("prioridade", 1))
    except Exception:
        prioridade = 1

    if prioridade == 1:
        base_score *= 1.4
    elif prioridade >= 3:
        base_score *= 0.8

    return base_score


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _build_magrinho_for_item(item: Dict[str, Any]) -> str:
    """
    Versão "magrinha" do item em texto:
      - usa resumoCurto, se existir
      - senão, monta com titulo + tags de forma simples
    """
    resumo = str(item.get("resumoCurto") or "").strip()
    if resumo:
        return resumo

    titulo = str(item.get("titulo") or "").strip()
    tags = item.get("tags") or []
    tags_txt = ", ".join(str(t) for t in tags if str(t).strip())

    parts: List[str] = []
    if titulo:
        parts.append(f"{titulo}")
    if tags_txt:
        parts.append(f"Tags: {tags_txt}")
    if not parts:
        return "Item do acervo do MEI (ainda sem resumo configurado)."

    return "\n\n".join(parts)


def _load_acervo_docs(uid: str) -> List[Dict[str, Any]]:
    """
    Carrega até _MAX_DOCS itens do acervo do MEI em:
      profissionais/{uid}/acervo
    """
    if db is None:
        logging.warning("domain.acervo: Firestore (db) não configurado.")
        return []

    col = db.collection("profissionais").document(uid).collection("acervo")

    try:
        # Ordena por prioridade asc (1 primeiro), depois por criadoEm desc, quando existir
        docs_stream = (
            col.order_by("prioridade")
               .order_by("criadoEm", direction="DESCENDING")
               .limit(_MAX_DOCS)
               .stream()
        )
    except Exception:
        # Se não conseguir ordenar, faz um stream simples
        logging.exception("domain.acervo: erro ao ordenar acervo, usando fallback simples.")
        docs_stream = col.limit(_MAX_DOCS).stream()

    items: List[Dict[str, Any]] = []
    for d in docs_stream:
        data = d.to_dict() or {}
        data["id"] = d.id
        # default básicos
        data.setdefault("habilitado", True)
        data.setdefault("prioridade", 1)
        data.setdefault("tags", [])
        items.append(data)

    return items


def query_acervo_for_uid(uid: str, pergunta: str, max_tokens: int = 120) -> Dict[str, Any]:
    """
    Mini-RAG em cima do acervo do MEI.

    Passos:
      1) Carrega até N docs de profissionais/{uid}/acervo (habilitado=True).
      2) Score simples por tokens (titulo, tags, resumoCurto).
      3) Se houver embeddings, ajusta o score pelo coseno.
      4) Seleciona top K (até 4) relevantes.
      5) Monta contexto e chama GPT-mini com resposta curta.

    Retorno:
      ver docstring do módulo.
    """
    pergunta = (pergunta or "").strip()
    if not pergunta:
        return {
            "answer": None,
            "usedDocs": [],
            "reason": "empty_question",
        }

    items = _load_acervo_docs(uid)
    if not items:
        return {
            "answer": None,
            "usedDocs": [],
            "reason": "no_docs",
        }

    # Embedding da pergunta (opcional)
    q_emb: Optional[List[float]] = None
    if get_mini_embedding is not None:
        try:
            q_emb = get_mini_embedding(pergunta)
        except Exception:
            logging.exception("domain.acervo: falha ao gerar embedding da pergunta.")
            q_emb = None

    scored: List[tuple[float, Dict[str, Any]]] = []
    for it in items:
        base_score = _score_candidate(pergunta, it)
        if base_score <= 0:
            scored.append((0.0, it))
            continue

        score = base_score
        # Ajuste por embedding, se existir
        if q_emb is not None and "embedding" in it and isinstance(it["embedding"], list):
            try:
                score += 2.0 * _cosine(q_emb, [float(x) for x in it["embedding"]])
            except Exception:
                pass

        scored.append((score, it))

    # Ordena por score desc e filtra quem tem score > 0
    scored.sort(key=lambda x: x[0], reverse=True)
    scored = [s for s in scored if s[0] > 0]

    if not scored:
        return {
            "answer": None,
            "usedDocs": [],
            "reason": "no_relevant_docs",
        }

    top_k = scored[:4]
    used_docs = [it for _, it in top_k]

    # Monta contexto magrinho
    context_parts: List[str] = []
    for it in used_docs:
        titulo = str(it.get("titulo") or "Item do acervo")
        magrinho = _build_magrinho_for_item(it)
        snippet = magrinho[:_MAX_CHARS_CONTEXT_PER_DOC]
        context_parts.append(f"# {titulo}\n\n{snippet}")

    context = "\n\n---\n\n".join(context_parts)

    # Se não tiver GPT-mini, devolve só contexto/usedDocs
    if gpt_mini_complete is None:
        return {
            "answer": None,
            "usedDocs": [
                {
                    "id": it["id"],
                    "titulo": it.get("titulo"),
                    "tags": it.get("tags", []),
                    "prioridade": it.get("prioridade", 1),
                }
                for it in used_docs
            ],
            "context": context,
            "reason": "no_llm_available",
        }

    prompt = f"""
Você é o assistente interno do MEI Robô. Use SOMENTE as informações abaixo,
que são materiais criados pelo próprio MEI (acervo interno), para responder
de forma curta e prática à pergunta.

Se não encontrar nada realmente útil, responda que ainda não há material
suficiente no acervo para responder com segurança.

CONTEÚDO DO ACERVO:
{context}

PERGUNTA:
\"\"\"{pergunta}\"\"\"

Responda em no máximo {max_tokens} tokens, em português simples, direto, sem citar
"modelo de linguagem" nem "documento".
""".strip()

    try:
        answer = gpt_mini_complete(prompt, max_tokens=max_tokens)
    except Exception:
        logging.exception("domain.acervo: falha ao chamar GPT-mini.")
        answer = None

    return {
        "answer": (answer or "").strip() or None,
        "usedDocs": [
            {
                "id": it["id"],
                "titulo": it.get("titulo"),
                "tags": it.get("tags", []),
                "prioridade": it.get("prioridade", 1),
            }
            for it in used_docs
        ],
        "reason": "ok" if answer else "llm_error",
    }
