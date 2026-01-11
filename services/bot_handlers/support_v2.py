# services/bot_handlers/support_v2.py
# Suporte V2 — Action Map + Artigo magrinho (Firestore-first, cache/TTL)
# Objetivo: responder "como faço X" com passos canônicos sem LLM quando possível.
# Fallback seguro: retorna None para cair no legacy.

from __future__ import annotations

import os
import time
import logging
import re
from typing import Any, Dict, Optional, Tuple

_SUPPORT_TTL_SECONDS = int(os.getenv("SUPPORT_KB_TTL_SECONDS", "600") or "600")

# Coleções (como você criou)
COL_ACTION_MAPS = os.getenv("SUPPORT_ACTION_MAPS_COLL", "platform_kb_action_maps")
COL_ARTICLES = os.getenv("SUPPORT_ARTICLES_COLL", "platform_kb_support_articles")

# Cache simples em memória (por page)
_ACTION_CACHE: Dict[str, Dict[str, Any]] = {}
_ACTION_CACHE_AT: Dict[str, float] = {}

_ARTICLE_CACHE: Dict[str, str] = {}
_ARTICLE_CACHE_AT: Dict[str, float] = {}

def _fs_client():
    try:
        from firebase_admin import firestore  # type: ignore
        return firestore.client()
    except Exception as e:
        logging.warning("[support_v2] firestore indisponível: %s", e)
        return None

def _get_action_map(page: str) -> Dict[str, Any]:
    now = time.time()
    if page in _ACTION_CACHE and (now - _ACTION_CACHE_AT.get(page, 0.0)) < _SUPPORT_TTL_SECONDS:
        return _ACTION_CACHE.get(page) or {}

    db = _fs_client()
    if not db:
        return {}

    try:
        doc = db.collection(COL_ACTION_MAPS).document(page).get()
        data = doc.to_dict() or {}
    except Exception as e:
        logging.warning("[support_v2] falha ao ler action_map %s: %s", page, e)
        data = {}

    _ACTION_CACHE[page] = data
    _ACTION_CACHE_AT[page] = now
    return data

def _get_article(page: str) -> str:
    now = time.time()
    if page in _ARTICLE_CACHE and (now - _ARTICLE_CACHE_AT.get(page, 0.0)) < _SUPPORT_TTL_SECONDS:
        return _ARTICLE_CACHE.get(page) or ""

    db = _fs_client()
    if not db:
        return ""

    try:
        doc = db.collection(COL_ARTICLES).document(page).get()
        data = doc.to_dict() or {}
        body = str(data.get("body") or "").strip()
    except Exception as e:
        logging.warning("[support_v2] falha ao ler artigo %s: %s", page, e)
        body = ""

    _ARTICLE_CACHE[page] = body
    _ARTICLE_CACHE_AT[page] = now
    return body

def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _speakable_compact_from_article(body: str, max_chars: int = 520) -> str:
    """
    Compacta o artigo para fala (TTS): 15–30s.
    Não é "resumo perfeito", é um 'jeito humano' curto.
    Mantém compatibilidade: se o resto do sistema só usa replyText,
    ele já melhora bastante sem virar audiobook.
    """
    if not body:
        return ""

    # limpar excesso (linhas vazias, bullets longos)
    txt = re.sub(r"\n{3,}", "\n\n", body.strip())
    # pega os 1–2 primeiros parágrafos (normalmente definem o conceito)
    parts = [p.strip() for p in txt.split("\n\n") if p.strip()]
    head = " ".join(parts[:2]).strip()

    # corta em uma janela segura e fecha frase
    head = re.sub(r"\s+", " ", head).strip()
    if len(head) > max_chars:
        head = head[:max_chars].rsplit(" ", 1)[0].strip()

    # garantir final "falável"
    if head and head[-1] not in ".!?":
        head += "."

    return head


def _compose_conceptual_reply(q: str, body: str) -> str:
    """
    Resposta falada canônica (curta).
    Estrutura: o que é / pra que serve / como usa / pergunta de fechamento.
    """
    base = _speakable_compact_from_article(body, max_chars=520)
    if not base:
        return ""

    # Fechamento curto (evita monólogo e puxa conversa)
    close = "Se tu me disser teu objetivo (ex.: organizar contatos, anexar arquivos ou importar CSV), eu te digo o caminho mais rápido."
    return f"{base} {close}"


def _user_wants_text(text: str) -> bool:
    t = _norm(text)
    triggers = (
        "só texto", "somente texto", "apenas texto",
        "manda por texto", "me manda por texto", "por texto",
        "manda por escrito", "por escrito", "me manda escrito",
        "detalha por texto", "detalhe por texto", "passo a passo por texto",
        "me manda a mensagem", "me manda a instrução"
    )
    return any(k in t for k in triggers)


def _get_profile_name_from_ctx(uid: str, ctx: Optional[Dict[str, Any]]) -> str:
    if not ctx:
        return ""
    wa_key = str(ctx.get("waKey") or "").strip()
    if not wa_key:
        return ""
    db = _fs_client()
    if not db:
        return ""
    try:
        doc = db.collection("platform_support_profiles").document(wa_key).get()
        data = doc.to_dict() or {}
        name = str(data.get("displayName") or "").strip()
        return name.split()[0].strip() if name else ""
    except Exception:
        return ""


def _maybe_update_name_from_text(ctx: Optional[Dict[str, Any]], text: str) -> str:
    if not ctx:
        return ""
    wa_key = str(ctx.get("waKey") or "").strip()
    if not wa_key:
        return ""
    t = (text or "").strip()

    # padrões comuns:
    # "meu nome é Miguel"
    # "aqui é Miguel"
    # "não é João, é Miguel"
    patterns = [
        r"\bmeu nome é\s+([A-Za-zÀ-ÿ]{2,})\b",
        r"\baqui é\s+([A-Za-zÀ-ÿ]{2,})\b",
        r"\bnão é\s+[A-Za-zÀ-ÿ]{2,}\s*,?\s*é\s+([A-Za-zÀ-ÿ]{2,})\b",
        r"\bnão sou\s+[A-Za-zÀ-ÿ]{2,}\s*,?\s*sou\s+([A-Za-zÀ-ÿ]{2,})\b",
    ]
    new_name = ""
    for p in patterns:
        mm = re.search(p, t, flags=re.IGNORECASE)
        if mm:
            new_name = (mm.group(1) or "").strip()
            break

    if not new_name:
        return ""

    db = _fs_client()
    if not db:
        return new_name

    try:
        db.collection("platform_support_profiles").document(wa_key).set(
            {"displayName": new_name, "updatedAt": time.time()},
            merge=True,
        )
    except Exception:
        pass
    return new_name

def _detect_page(text: str) -> Optional[str]:
    t = _norm(text)
    # Comece com poucas páginas (Contatos primeiro).
    if any(k in t for k in ("contato", "contatos", "acervo", "autorização", "autorizacao", "csv")):
        return "contatos"
    return None

def _detect_action_for_contatos(text: str) -> Optional[str]:
    t = _norm(text)

    # "foto no contato" (não existe)
    if any(k in t for k in ("foto", "imagem no contato", "foto de perfil", "perfil do contato", "avatar")):
        return "foto_no_contato"

    # criar contato
    if any(k in t for k in ("novo contato", "criar contato", "cadastrar contato", "lançar contato", "adicionar contato")):
        return "criar_contato"

    # acervo
    if any(k in t for k in ("acervo", "anexar", "anexo", "pdf", "arquivo", "imagem", "enviar arquivo")):
        return "abrir_acervo"

    # autorização whatsapp
    if any(k in t for k in ("autorização", "autorizacao", "optin", "whatsapp", "janela 24")):
        return "autorizacao_whatsapp"

    # importar csv
    if "csv" in t or "import" in t:
        return "importar_csv"

    return None

def _render_steps(goal: str, steps: Any, notes: Any, required: Any) -> str:
    lines = []
    if goal:
        lines.append(f"{goal}.")
    if required and isinstance(required, list) and required:
        req = ", ".join([str(x) for x in required if str(x).strip()])
        if req:
            lines.append(f"Pra salvar, o mínimo é: {req}.")
    if steps and isinstance(steps, list) and steps:
        # Passos 1..N
        for i, s in enumerate(steps, start=1):
            ss = str(s).strip()
            if ss:
                lines.append(f"{i}) {ss}")
    if notes and isinstance(notes, list) and notes:
        # Uma dica final curta
        tip = str(notes[0]).strip() if notes else ""
        if tip:
            lines.append(tip)
    return "\n".join(lines).strip()

def _try_answer_from_action_map(page: str, text: str) -> Optional[str]:
    am = _get_action_map(page)
    how_to = am.get("how_to") if isinstance(am, dict) else None
    if not isinstance(how_to, dict):
        return None

    action = None
    if page == "contatos":
        action = _detect_action_for_contatos(text)

    if not action:
        return None

    entry = how_to.get(action)
    if not isinstance(entry, dict):
        return None

    # Caso negativo (exists=false)
    if entry.get("exists") is False:
        ans = str(entry.get("answer") or "").strip()
        return ans or None

    goal = str(entry.get("goal") or "").strip()
    steps = entry.get("steps")
    notes = entry.get("notes")
    required = entry.get("required")
    out = _render_steps(goal, steps, notes, required)
    return out or None

def _looks_conceptual(text: str) -> bool:
    t = _norm(text)
    return any(k in t for k in (
        "pra que serve", "para que serve", "o que é", "como funciona", "qual a diferença", "diferença"
    ))

def _try_answer_from_article(page: str, text: str) -> Optional[str]:
    body = _get_article(page)
    if not body:
        return None
    # Resposta curta: para começar, devolve o corpo inteiro (magrinho).
    # Depois podemos fazer recorte por trechos/embeddings sem mudar contrato.
    if _looks_conceptual(text):
        return _compose_conceptual_reply(text, body)
    return None

def generate_reply(uid: str, text: str, ctx: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Retorna dict {replyText, route} ou None para cair no legacy.
    Sem LLM por padrão: usa Action Map e Artigo magrinho.
    """
    uid = (uid or "").strip()
    if not uid:
        return None

    q = (text or "").strip()
    if not q:
        return None

    # Preferência explícita do usuário + memória simples de nome (por waKey)
    learned_name = _maybe_update_name_from_text(ctx, q)
    prefers_text = _user_wants_text(q)
    display_name = learned_name or _get_profile_name_from_ctx(uid, ctx)

    page = _detect_page(q)
    if not page:
        return None

    # 1) Action Map
    ans = _try_answer_from_action_map(page, q)
    if ans:
        return {"ok": True, "route": f"support_v2:{page}:action_map", "replyText": ans, "prefersText": bool(prefers_text), "displayName": display_name}

    # 2) Artigo (conceitual)
    ans2 = _try_answer_from_article(page, q)
    if ans2:
        # kbContext é o artigo completo (cérebro). replyText é fala curta (boca).
        return {
            "ok": True,
            "route": f"support_v2:{page}:article",
            "replyText": ans2,
            "kbContext": _get_article(page),  # corpo completo
            "kind": "conceptual",
            "prefersText": bool(prefers_text),
            "displayName": display_name,
            "nameToSay": display_name,  # sugestão; decisão final fica no layer do áudio
        }

    # 3) Sem match: pedir 1 clarificação (curta) OU cair no legacy.
    # Aqui vamos cair no legacy para manter comportamento e qualidade.
    return None
