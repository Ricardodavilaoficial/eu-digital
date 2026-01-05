# services/bot_handlers/sales_lead.py
# Handler isolado: Vendas (lead) — Opção B (2025-12-26)
# - Conteúdo público (sem dados privados)
# - Sem ações irreversíveis
# - Webhook deve ser "burro": este handler vive no wa_bot

from __future__ import annotations

import os
import time
import json
import re
import hashlib
import requests
from typing import Any, Callable, Dict, Optional

# =========================
# Conteúdo CANÔNICO (VENDAS)
# =========================

SITE_URL = os.getenv("MEI_ROBO_SITE_URL", "www.meirobo.com.br")

# Mensagem mínima de entrada (mantida local por segurança operacional)
OPENING_ASK_NAME = (
    "Oi! 👋 Eu sou o MEI Robô 🙂\n\n"
    "Antes de te explicar direitinho,\n"
    "me diz teu nome?"
)

# Fallback humano mínimo (nunca vazio; sem marketing longo)
def _fallback_min_reply(name: str = "") -> str:
    name = (name or "").strip()
    if name:
        return f"{name}, perfeito. Você quer falar de pedidos, agenda, orçamento ou só conhecer?"
    return "Show 🙂 Me diz teu nome e o que você quer resolver: pedidos, agenda, orçamento ou conhecer?"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_SALES_NLU_MODEL = os.getenv("OPENAI_SALES_NLU_MODEL", os.getenv("OPENAI_NLU_MODEL", "gpt-4o-mini"))
OPENAI_SALES_MODEL = os.getenv("OPENAI_SALES_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
SALES_NLU_TIMEOUT = 20

# Sales KB (Firestore-first)
# Fonte de verdade: platform_kb/sales (doc único)
_SALES_KB_CACHE: Optional[Dict[str, Any]] = None
_SALES_KB_CACHE_AT: float = 0.0
_SALES_KB_TTL_SECONDS: int = int(os.getenv("SALES_KB_TTL_SECONDS", "600"))

def _get_sales_kb() -> Dict[str, Any]:
    """Carrega KB de vendas do Firestore com cache/TTL. Best-effort."""
    global _SALES_KB_CACHE, _SALES_KB_CACHE_AT
    now = time.time()
    if _SALES_KB_CACHE and (now - _SALES_KB_CACHE_AT) < _SALES_KB_TTL_SECONDS:
        return _SALES_KB_CACHE

    kb: Dict[str, Any] = {}
    try:
        # Lazy import para não quebrar em ambientes sem Firestore libs
        from google.cloud import firestore  # type: ignore
        client = firestore.Client()
        doc = client.collection("platform_kb").document("sales").get()
        if doc and doc.exists:
            kb = doc.to_dict() or {}
    except Exception:
        kb = {}

    # KB mínimo neutro (sem marketing e sem números) — só pra não quebrar o prompt
    if not isinstance(kb, dict) or not kb:
        kb = {
            "tone_rules": [
                "Curto, humano, WhatsApp.",
                "Sem tecnicês e sem bastidores.",
                "Nunca culpar o cliente; sempre oferecer opções.",
            ],
            "value_props": [],
            "how_it_works": [],
            "segments": {},
            "objections": {},
            "pricing_teasers": [],
            "version": "local_min",
        }

    _SALES_KB_CACHE = kb
    _SALES_KB_CACHE_AT = now
    return kb

# =========================
# Helpers: parsing simples
# =========================

def _now_iso() -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    except Exception:
        return ""

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _looks_like_greeting(t: str) -> bool:
    t = _norm(t)
    return t in ("oi", "olá", "ola", "e aí", "eai", "bom dia", "boa tarde", "boa noite", "oii", "oiii")

def _intent(t: str) -> str:
    t = _norm(t)
    if any(k in t for k in ("preço", "preco", "quanto custa", "valor", "mensal", "mês", "mes", "89", "119")):
        return "PRICE"
    if any(k in t for k in ("planos", "plano", "starter", "starter+", "plus")):
        return "PLANS"
    if any(k in t for k in ("diferença", "diferenca", "10gb", "2gb", "memória", "memoria")):
        return "DIFF"
    if any(k in t for k in ("o que é", "oq é", "o que voce faz", "o que você faz", "como funciona")):
        return "WHAT_IS"
    if any(k in t for k in ("ativar", "criar conta", "assinar", "começar", "comecar", "quero")):
        return "ACTIVATE"
    return "OTHER"

def _extract_name_freeform(text: str) -> str:
    """
    Extrai nome simples sem forçar.
    - "me chamo X", "sou X", "aqui é X", "eu sou X"
    - Se vier só uma palavra (ex.: "Ricardo"), aceita como nome.
    """
    t = (text or "").strip()
    if not t:
        return ""
    tl = _norm(t)

    m = re.search(r"(me chamo|meu nome é|meu nome e|aqui é|aqui e|eu sou|sou)\s+([a-zA-ZÀ-ÿ'\- ]{2,40})$", t, re.IGNORECASE)
    if m:
        name = (m.group(2) or "").strip()
        name = re.sub(r"\s+", " ", name)
        # corta se tiver muita coisa
        if len(name.split(" ")) > 4:
            name = " ".join(name.split(" ")[:3])
        return name

    # se for 1-3 palavras e não parecer pergunta, assume nome
    if len(t.split(" ")) <= 3 and "?" not in t and len(t) <= 32:
        return re.sub(r"\s+", " ", t).strip()

    return ""

def _extract_segment(text: str) -> str:
    t = _norm(text)
    if not t:
        return ""

    # mapeamento leve (humano): não substitui IA, só evita ruído óbvio
    if any(k in t for k in ("cabelo", "cabeleireir", "barbear", "salão", "salao", "beleza", "unha", "estética", "estetica")):
        return "beleza"
    if "dent" in t or "odonto" in t:
        return "dentista"
    if any(k in t for k in ("lanche", "lanches", "hamburg", "pizza", "comida", "marmita", "delivery", "restaurante")):
        return "lanches"
    if any(k in t for k in ("serviço", "servico", "prestador", "conserto", "reforma", "instala", "manutenção", "manutencao")):
        return "servico"
    return ""


def _extract_goal(text: str) -> str:
    t = _norm(text)
    if not t:
        return ""

    # objetivos típicos (bem curto; não vira regra-mãe)
    if any(k in t for k in ("agenda", "agendar", "horário", "horario", "marcar", "consulta")):
        return "agenda"
    if any(k in t for k in ("pedido", "pedidos", "anotar", "comanda", "delivery", "entrega")):
        return "pedidos"
    if any(k in t for k in ("orçamento", "orcamento", "cotação", "cotacao", "preço do serviço", "valor do serviço")):
        return "orcamento"
    if any(k in t for k in ("dúvida", "duvida", "perguntas", "triagem", "filtrar")):
        return "triagem"
    return ""


def _apply_next_step_safely(st: Dict[str, Any], next_step: str, has_name: bool, has_segment: bool, has_goal: bool) -> None:
    """
    next_step (IA) é sugestão. Nunca pode contradizer o que falta.
    Só ajusta stage quando for seguro.
    """
    ns = (next_step or "").strip().upper()
    if not ns:
        return

    # Se falta nome, sempre ASK_NAME
    if not has_name:
        st["stage"] = "ASK_NAME"
        return

    # Se falta segmento, sempre ASK_SEGMENT
    if not has_segment:
        st["stage"] = "ASK_SEGMENT"
        return

    # Se falta goal, permitir ASK_GOAL quando IA pedir VALUE/CTA cedo demais
    if not has_goal and ns in ("VALUE", "CTA", "PRICE"):
        st["stage"] = "ASK_GOAL"
        return

    # Aqui já temos nome+segmento (e possivelmente goal). Agora sim, respeita sugestão.
    if ns == "ASK_NAME":
        st["stage"] = "ASK_NAME"
    elif ns == "ASK_SEGMENT":
        st["stage"] = "ASK_SEGMENT"
    elif ns == "VALUE":
        st["stage"] = "PITCH"
    elif ns == "PRICE":
        st["stage"] = "PRICE"
    elif ns == "CTA":
        st["stage"] = "CTA"
    elif ns == "EXIT":
        st["stage"] = "EXIT"

# =========================
# Entrada do webhook (compat)
# =========================

def _extract_inbound_text(change: Dict[str, Any]) -> str:
    """Extrai texto de um payload 'change.value' (Meta/YCloud compat)."""
    try:
        msgs = (change or {}).get("messages") or []
        if msgs and isinstance(msgs, list):
            m0 = msgs[0] or {}
            if (m0.get("type") == "text") and isinstance(m0.get("text"), dict):
                body = (m0.get("text") or {}).get("body") or ""
                return str(body).strip()
        if isinstance(change.get("text"), dict):
            return str((change.get("text") or {}).get("body") or "").strip()
        if isinstance(change.get("text"), str):
            return str(change.get("text") or "").strip()
    except Exception:
        pass
    return ""

def _extract_sender(change: Dict[str, Any]) -> str:
    """
    Pega o sender em payload Meta/YCloud (messages[0].from) e também em payloads normalizados
    (change['from'], change['from_e164'], etc).
    """
    try:
        msgs = (change or {}).get("messages") or []
        if msgs and isinstance(msgs, list) and msgs:
            m0 = msgs[0] or {}
            v = str(m0.get("from") or "").strip()
            if v:
                return v
    except Exception:
        pass

    # payload normalizado / compat
    for k in ("from", "from_e164", "sender", "phone", "wa_from"):
        try:
            v = str((change or {}).get(k) or "").strip()
            if v:
                return v
        except Exception:
            pass

    return ""



def _is_audio_inbound(change: Dict[str, Any]) -> bool:
    try:
        # payload meta-style
        msgs = (change or {}).get("messages") or []
        if msgs and isinstance(msgs, list) and msgs:
            m0 = msgs[0] or {}
            mt = str(m0.get("type") or "").strip().lower()
            if mt == "audio":
                return True
            if "audio" in (m0 or {}):
                return True
    except Exception:
        pass

    # payload normalizado
    try:
        mt2 = str((change or {}).get("msg_type") or (change or {}).get("msgType") or "").strip().lower()
        if mt2 == "audio":
            return True
    except Exception:
        pass

    return False


def _audio_fallback_text() -> str:
    # Gatilho neutro pra IA: não inventa conteúdo, só mantém conversa viva
    return "Lead enviou um áudio."



def _stylize_for_sales_audio(text: str, st: Dict[str, Any]) -> str:
    """
    Converte a resposta em um texto mais falável (vendedor + sorriso),
    sem mudar o sentido e sem virar palestra.

    Regras:
    - curto (≈ 8–18s)
    - 1 ideia por frase
    - pausas naturais
    - sem links/site no áudio
    """
    t = (text or "").strip()
    if not t:
        return ""

    name = (st.get("name") or "").strip()
    segment = (st.get("segment") or "").strip()
    interest = (st.get("interest_level") or "").strip().lower()

    # remove CTA/links do áudio (site lido em voz = robô)
    t = re.sub(r"https?://\S+", "", t).strip()
    t = t.replace(SITE_URL, "").strip()

    # remove excesso de quebras e espaços
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()

    # se ficou longo, corta mantendo sentido (até ~280 chars)
    if len(t) > 280:
        t = t[:277].rsplit(" ", 1)[0] + "…"

    # “sorriso” e ritmo (bem leve)
    # cria uma abertura falada se for contexto de vendas
    opener = ""
    if name and segment:
        opener = f"{name}, rapidinho… no teu ramo ({segment}) é assim:"
    elif name:
        opener = f"{name}, rapidinho…"
    else:
        opener = "Rapidinho…"

    # se já começa com “Hoje o plano…” não precisa opener grande
    if t.lower().startswith("hoje o plano") or t.lower().startswith("hoje tem"):
        opener = "Fechou 🙂"

    # tom vendedor sob controle (sem gritaria)
    closer = ""
    if interest in ("high", "mid"):
        # pergunta simples (puxa conversa)
        if segment:
            closer = f"Quer que eu te diga, no {segment}, o jeito mais simples de usar isso?"
        else:
            closer = "Quer que eu te diga o jeito mais simples no teu caso?"
    else:
        closer = "Se fizer sentido, me fala teu caso em 1 frase 🙂"

    # monta em 2 blocos (pausa natural)
    out = f"{opener}\n\n{t}"
    # evita duplicar pergunta se já tem interrogação no final
    if "?" not in out[-80:]:
        out = out.strip() + f"\n\n{closer}"

    # último corte pra não virar áudio longo
    if len(out) > 420:
        out = out[:417].rsplit(" ", 1)[0] + "…"

    return out.strip()


# =========================
# Estado institucional (Firestore)
# - sessão curta pra manter contexto
# - lead “desconhecido conhecido” pra retomar outro dia + marketing
# =========================

from services.institutional_leads_store import (
    get_session, set_session,
    get_lead, upsert_lead,
)

def _load_state(from_sender: str) -> tuple[dict, str]:
    """
    Retorna (state_dict, wa_key_escolhida).
    - primeiro tenta sessão válida
    - se não tiver sessão, tenta lead pra “retomar leve”
    """
    sess, wa_key = get_session(from_sender)
    if isinstance(sess, dict) and sess:
        return sess, wa_key

    lead, wa_key2 = get_lead(from_sender)
    wa_key = wa_key or wa_key2

    # Se tem lead, sem sessão: retoma leve (não finge conversa no meio)
    if isinstance(lead, dict) and lead:
        st = {
            "stage": "ASK_SEGMENT" if (lead.get("name") and not lead.get("segment")) else "PITCH",
            "name": (lead.get("name") or "").strip(),
            "segment": (lead.get("segment") or "").strip(),
            "goal": (lead.get("goal") or "").strip(),
            "turns": int(lead.get("turns") or 0),
            "nudges": 0,
            "last_user_at": time.time(),
        }
        # se não tem nada útil, volta pro início
        if not (st.get("name") or st.get("segment")):
            st["stage"] = "ASK_NAME"
        return st, wa_key

    # desconhecido mesmo
    return {}, wa_key

def _save_session(wa_key: str, st: dict, ttl_seconds: int) -> None:
    set_session(wa_key, st, ttl_seconds=ttl_seconds)

def _upsert_lead_from_state(wa_key: str, st: dict) -> None:
    """
    Só grava lead quando tiver pelo menos nome OU sinal forte + segmento.
    Mantém compacto (sem histórico).
    """
    name = (st.get("name") or "").strip()
    segment = (st.get("segment") or "").strip()
    goal = (st.get("goal") or "").strip()
    turns = int(st.get("turns") or 0)

    if not name and not segment:
        return

    lead = {
        "name": name,
        "segment": segment,
        "goal": goal,
        "turns": turns,
        "status": st.get("lead_status") or "new",
        "interest_level": st.get("interest_level") or "",
        "lastSeenAt": time.time(),
        "updatedAt": time.time(),
    }
    upsert_lead(wa_key, lead)

# =========================
# Cache KV (apenas para pitch; NÃO é estado de conversa)
# =========================

def _kv_get(key: str) -> Optional[Dict[str, Any]]:
    try:
        from services.cache import kv  # type: ignore
        raw = kv.get(key)
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            return json.loads(raw)
    except Exception:
        return None
    return None

def _kv_set(key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
    try:
        from services.cache import kv  # type: ignore
        kv.set(key, json.dumps(value, ensure_ascii=False), ttl_seconds=ttl_seconds)
    except Exception:
        return

# =========================
# Core: gerar resposta
# =========================



def _pitch_cache_key(segment: str, hint: str, user_text: str) -> str:
    segment = (segment or "geral").strip().lower()
    hint = (hint or "default").strip().lower()
    base = f"{hint}|{segment}|{_norm(user_text)[:180]}"
    h = hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"sales:pitch:{segment}:{hint}:{h}"

def _get_cached_pitch(segment: str, hint: str, user_text: str) -> Optional[str]:
    try:
        raw = _kv_get(_pitch_cache_key(segment, hint, user_text))
        if isinstance(raw, dict):
            v = raw.get("pitch") or ""
            return str(v).strip() if v else None
        if isinstance(raw, str):
            return raw.strip() or None
    except Exception:
        return None
    return None

def _set_cached_pitch(segment: str, hint: str, user_text: str, pitch: str) -> None:
    try:
        ttl = int(os.getenv("SALES_PITCH_CACHE_TTL_SECONDS", "86400") or "86400")  # 24h
        _kv_set(_pitch_cache_key(segment, hint, user_text), {"pitch": pitch}, ttl_seconds=ttl)
    except Exception:
        pass

def _openai_chat(prompt: str, max_tokens: int = 140, temperature: float = 0.45) -> str:
    """
    Chamada mínima ao endpoint /chat/completions (igual padrão do repo em services/openai/nlu_intent.py).
    Retorna texto. Se falhar, retorna "".
    """
    if not OPENAI_API_KEY:
        return ""

    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_SALES_MODEL,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "messages": [
            {"role": "system", "content": "Você é um atendente de vendas via WhatsApp. Seja humano, curto e direto."},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code != 200:
            return ""
        data = r.json() or {}
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = (choices[0] or {}).get("message") or {}
        txt = (msg.get("content") or "").strip()
        return txt
    except Exception:
        return ""

def _ai_pitch(name: str, segment: str, user_text: str) -> str:
    """
    Gera um pitch curto e humano (WhatsApp) usando o "cérebro único".
    Mantém best-effort e não quebra o fluxo.
    """
    name = (name or "").strip()
    user_text = (user_text or "").strip()

    seg_key = (segment or "").strip().lower()
    if not seg_key:
        seg_key = "geral"

    hint = "pitch_v1"
    cached = _get_cached_pitch(seg_key, hint, user_text)
    if cached:
        return cached

    kb = _get_sales_kb() or {}
    segments = kb.get("segments") or {}
    seg_info = segments.get(seg_key) or {}
    seg_title = (seg_info.get("title") or segment or seg_key).strip()

    bullets = seg_info.get("bullets") or []
    if not isinstance(bullets, list):
        bullets = []

    scenarios = kb.get("scenarios") or []
    if not isinstance(scenarios, list):
        scenarios = []

    system = (
        "Você é o MEI Robô institucional de VENDAS.\n"
        "Objetivo: converter o lead com conversa curta, humana e objetiva.\n"
        "Regras:\n"
        "- Nada de bastidores técnicos.\n"
        "- Sem textão.\n"
        "- Faça 1 pergunta por vez.\n"
        "- Se faltar dado, pergunte.\n"
        "- CTA leve: preço/horários/endereço ou agendar.\n"
    )

    parts = []
    parts.append(f"Segmento: {seg_title}")
    if name:
        parts.append(f"Lead: {name}")
    if user_text:
        parts.append(f"Mensagem do lead: {user_text}")

    if bullets:
        parts.append("Pontos fortes do segmento (use só se ajudar agora):")
        parts.extend([f"- {b}" for b in bullets[:8]])

    if scenarios:
        # só um cheirinho, pra não virar palestra
        parts.append("Exemplos rápidos de uso por segmento (referência):")
        for s in scenarios[:5]:
            try:
                t = (s.get("title") or "").strip()
                d = (s.get("desc") or "").strip()
                if t or d:
                    parts.append(f"- {t}: {d}".strip(": "))
            except Exception:
                pass

    prompt = "\n".join(parts).strip()

    out = ""
    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        out = (_openai_chat(messages) or "").strip()
    except Exception:
        out = ""

    if not out:
        out = "Posso te passar valores, endereço/horários ou já marcar um horário. O que você prefere?"

    _set_cached_pitch(seg_key, hint, user_text, out)
    return out


def _ai_sales_answer(name: str, segment: str, goal: str, user_text: str, intent_hint: str = "") -> str:
    """
    Resposta final SEMPRE via IA, usando textos fixos apenas como repertório.
    - Curto, humano, WhatsApp.
    - Não expulsa lead.
    - Faz 1 pergunta objetiva para avançar.
    """
    name = (name or "").strip()
    segment = (segment or "").strip()
    goal = (goal or "").strip()
    user_text = (user_text or "").strip()
    intent_hint = (intent_hint or "").strip().upper()

    # Repertório compacto (não copiar literal)
    kb = _get_sales_kb()

    # Contexto de repertório (Firestore-first). A IA decide o que usar.
    # IMPORTANTÍSSIMO: não inventar números. Se não tiver preço no KB, falar sem valores.
    repertoire = {
        "site_url": SITE_URL,
        "kb": {
            "tone_rules": kb.get("tone_rules", []),
            "value_props": kb.get("value_props", []),
            "how_it_works": kb.get("how_it_works", []),
            "segments": kb.get("segments", {}),
            "objections": kb.get("objections", {}),
            "pricing_teasers": kb.get("pricing_teasers", []),
            "version": kb.get("version", ""),
            "updatedAt": kb.get("updatedAt", ""),
        },
    }

    prompt = (
        f"Contexto do lead:\n"
        f"- Nome (se houver): {name or '—'}\n"
        f"- Segmento/ramo (se houver): {segment or '—'}\n"
        f"- Objetivo (se houver): {goal or '—'}\n"
        f"- Intent_hint: {intent_hint or '—'}\n"
        f"- Última mensagem do lead: {user_text}\n\n"
        "Tarefa: responda como atendente de vendas do MEI Robô no WhatsApp.\n"
        "Regras:\n"
        "1) Seja humano, curto (2 a 6 linhas), direto e gentil.\n"
        "2) NÃO diga que o lead caiu no número errado. NÃO expulse.\n"
        "3) Se faltar nome ou ramo, peça só 1 coisa por vez e ofereça 2–3 opções quando estiver confuso.\n"
        "4) Use o repertório apenas como base; NÃO copie textos literalmente.\n"
        "5) Se perguntarem de preço/planos, explique de forma simples e em seguida faça 1 pergunta para avançar (ramo/objetivo).\n\n"
        f"Repertório (use como base, não copie):\n{json.dumps(repertoire, ensure_ascii=False)}\n"
    )

    return (_openai_chat(prompt, max_tokens=220, temperature=0.45) or "").strip()




def _sales_nlu_http(messages):
    if not OPENAI_API_KEY:
        return None
    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": OPENAI_SALES_NLU_MODEL,
        "temperature": 0.0,
        "max_tokens": 140,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=SALES_NLU_TIMEOUT)
        r.raise_for_status()
        js = r.json()
        content = (js.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return content
    except Exception:
        return None

def sales_micro_nlu(text: str, stage: str = "") -> Dict[str, Any]:
    """
    SEMPRE IA: classifica se é SALES / OFFTOPIC / EMERGENCY e extrai nome/segmento quando existirem.
    Não revela bastidores.
    """
    text = (text or "").strip()
    if not text:
        # áudio vazio vira SALES (vai pedir nome)
        return {"route": "sales", "intent": "OTHER", "name": "", "segment": "", "interest_level": "mid", "next_step": ""}

    system = (
        "Você é um CLASSIFICADOR de mensagens do WhatsApp do MEI Robô (pt-BR). "
        "Responda SOMENTE JSON válido (sem texto extra).\n\n"

        "Objetivo: entender a intenção do usuário para um atendimento de VENDAS do MEI Robô.\n\n"

        "Regras IMPORTANTES (produto):\n"
        "1) Continuidade: se STAGE_ATUAL NÃO for 'ASK_NAME', assuma que a conversa já começou — route DEVE ser 'sales' (exceto emergency).\n"
        "2) Boa-fé: mensagens curtas como 'sim', 'ok', 'pedidos', 'agenda', 'orçamento' normalmente são continuação, não erro.\n"
        "3) Não culpar o usuário: evite classificar como 'offtopic' a menos que seja claramente um assunto aleatório e a conversa ainda NÃO tenha começado.\n\n"

        "EMERGENCY:\n"
        "- Se pedir telefone dos bombeiros/polícia/SAMU/ambulância, ou mencionar 190/192/193 => route='emergency'.\n"
        "- Em emergency, intent='OTHER', name/segment vazios.\n\n"

        "OFFTOPIC (somente no início):\n"
        "- Use route='offtopic' apenas se STAGE_ATUAL='ASK_NAME' e a mensagem for claramente aleatória e NÃO relacionada a atendimento/negócio.\n"
        "- Mesmo em offtopic: intent='OTHER', name/segment vazios.\n\n"

        "Formato do JSON (sempre): {route, intent, name, segment, interest_level, next_step}.\n"
        "route em: 'sales' | 'offtopic' | 'emergency'.\n"
        "interest_level em: 'low' | 'mid' | 'high'.\n"
        "next_step pode ser: '' | 'ASK_NAME' | 'ASK_SEGMENT' | 'VALUE' | 'PRICE' | 'CTA'.\n"

    )

    stage = (stage or "").strip().upper()

    # Regra contextual (humana): se eu acabei de pedir o nome,
    # uma resposta curta normalmente É o nome (mas não vale "oi/olá/bom dia").
    if stage == "ASK_NAME" and text and len(text.strip()) <= 30:
        t = text.strip().lower()

        # Não trate perguntas como nome
        if any(k in t for k in ("quanto custa", "preço", "preco", "planos", "valor", "mensal", "assinatura")):
            return {"route": "sales", "intent": "OTHER", "name": "", "segment": "", "interest_level": "mid", "next_step": "ASK_NAME"}

        if t in ("oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "eai", "e aí", "opa"):
            return {"route": "sales", "intent": "OTHER", "name": "", "segment": "", "interest_level": "mid", "next_step": ""}
        return {"route": "sales", "intent": "OTHER", "name": text.strip(), "segment": "", "interest_level": "mid", "next_step": "ASK_SEGMENT"}

    # Regra contextual (humana): se eu acabei de pedir o ramo,
    # uma resposta curta normalmente É o segmento.
    if stage == "ASK_SEGMENT" and text and len(text.strip()) <= 40:
        return {"route": "sales", "intent": "OTHER", "name": "", "segment": text.strip(), "interest_level": "mid", "next_step": "VALUE"}

    user = f"STAGE_ATUAL: {stage}\nMENSAGEM: {text}"

    content = _sales_nlu_http([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])

    if not content:
        # fallback conservador: assume sales (pede nome) — mantém pilar, sem travar
        return {"route": "sales", "intent": "OTHER", "name": "", "segment": "", "interest_level": "mid", "next_step": ""}

    try:
        out = json.loads(content)
        route = (out.get("route") or "sales").strip().lower()
        if route not in ("sales", "offtopic", "emergency"):
            route = "offtopic"  # default seguro: cai fora
        intent = (out.get("intent") or "OTHER").strip().upper()
        if intent not in ("PRICE", "PLANS", "DIFF", "ACTIVATE", "WHAT_IS", "OTHER"):
            intent = "OTHER"
        name = (out.get("name") or "").strip()
        segment = (out.get("segment") or "").strip()
        interest_level = (out.get("interest_level") or "mid").strip().lower()
        if interest_level not in ("low", "mid", "high"):
            interest_level = "mid"

        next_step = (out.get("next_step") or "").strip().upper()
        if next_step not in ("ASK_NAME", "ASK_SEGMENT", "VALUE", "PRICE", "CTA", "EXIT"):
            next_step = ""
        return {
            "route": route,
            "intent": intent,
            "name": name,
            "segment": segment,
            "interest_level": interest_level,
            "next_step": next_step,
        }
    except Exception:
        return {"route": "offtopic", "intent": "OTHER", "name": "", "segment": "", "interest_level": "low", "next_step": "EXIT"}

def _reply_from_state(text_in: str, st: Dict[str, Any]) -> str:
    name = (st.get("name") or "").strip()
    segment = (st.get("segment") or "").strip()
    stage = (st.get("stage") or "").strip() or "ASK_NAME"
    # Se já temos nome por “desconhecido conhecido”, não pede nome de novo
    if stage == "ASK_NAME" and name:
        st["stage"] = "ASK_SEGMENT" if not segment else "PITCH"
        stage = st["stage"]
    goal = (st.get("goal") or "").strip()
    turns = int(st.get("turns") or 0)
    turns += 1
    st["turns"] = turns

    # Reset suave se ficou muito tempo parado (evita conversa “presa”)
    try:
        last_user_at = float(st.get("last_user_at") or 0.0)
    except Exception:
        last_user_at = 0.0

    now_ts = time.time()
    st["last_user_at"] = now_ts

    # se ficou parado mais de 24h, zera só o stage (mantém nome se já tiver)
    if last_user_at and (now_ts - last_user_at) > 86400:
        st["stage"] = "ASK_NAME" if not (st.get("name") or "").strip() else "ASK_SEGMENT"
        # não zera o resto agressivamente; só destrava o fluxo

    nudges = int(st.get("nudges") or 0)

    intent = _intent(text_in)
    nlu = sales_micro_nlu(text_in, stage=stage)
    interest = (nlu.get("interest_level") or "mid").strip().lower()
    next_step = (nlu.get("next_step") or "").strip().upper()
    # route (sales/offtopic/emergency) é decidido por IA
    route = nlu.get("route") or "sales"
    # Produto: depois que a conversa começou, NÃO existe "caiu no número errado".
    # Só permitimos emergency; o resto é continuidade de vendas.
    if (route == "offtopic") and (turns > 1 or name or segment or stage != "ASK_NAME"):
        route = "sales"

    # se IA extraiu nome/segmento, aproveita
    if not name and (nlu.get("name") or ""):
        st["name"] = (nlu.get("name") or "").strip()
        name = st["name"]
    if not segment and (nlu.get("segment") or ""):
        st["segment"] = (nlu.get("segment") or "").strip()
        segment = st["segment"]

    # intent canônico vindo da IA (não por palavra)
    intent = (nlu.get("intent") or intent or "OTHER").strip().upper()


    # Se o lead respondeu o objetivo principal, guarda (ex.: "agenda", "pedidos", "orçamento")
    if not goal:
        g = _extract_goal(text_in)
        if g:
            st["goal"] = g
            goal = g

    # Persistência canônica: tudo que foi capturado precisa ficar no estado
    if name and (st.get("name") or "").strip() != name:
        st["name"] = name
    if segment and (st.get("segment") or "").strip() != segment:
        st["segment"] = segment
    if goal and (st.get("goal") or "").strip() != goal:
        st["goal"] = goal

    has_name = bool(name)
    has_segment = bool(segment)
    has_goal = bool(goal)

    _apply_next_step_safely(st, next_step, has_name=has_name, has_segment=has_segment, has_goal=has_goal)
    stage = (st.get("stage") or stage or "").strip() or "ASK_NAME"

    if route == "emergency":
        return "Se for emergência, liga 193 agora. 🙏"

    if route == "offtopic":
        return "Oi! Eu sou o MEI Robô 🙂 Posso te explicar rapidinho como funciona e valores. Qual teu nome?"


    if stage == "EXIT":
        return "Beleza 🙂 Se quiser retomar sobre o MEI Robô, é só mandar aqui."
    # 0) Intenções diretas (preço/planos/diferença/o que é) — IA escreve o texto final.
    # Regras:
    # - Nada de "return" com textos prontos
    # - Se a IA falhar, fallback humano mínimo (sem marketing longo)

    # intents diretos primeiro
    if intent == "PRICE":
        # Responde já, e depois segue coletando info (sem resetar)
        if not name and not segment:
            st["stage"] = "ASK_NAME"
        elif not segment:
            st["stage"] = "ASK_SEGMENT"
        else:
            st["stage"] = "PITCH"

        txt = _ai_sales_answer(name=name, segment=segment, goal=goal, user_text=text_in, intent_hint="pricing")
        return (txt or "").strip() or _fallback_min_reply(name)

    if intent == "PLANS":
        # Explica e puxa o ramo (se faltar)
        st["stage"] = "ASK_NAME" if not name else ("ASK_SEGMENT" if not segment else st.get("stage", "PITCH"))
        txt = _ai_sales_answer(name=name, segment=segment, goal=goal, user_text=text_in, intent_hint="PLANS")
        return (txt or "").strip() or _fallback_min_reply(name)

    if intent in ("DIFF", "PLUS_DIFF"):
        st["stage"] = "ASK_NAME" if not name else ("ASK_SEGMENT" if not segment else st.get("stage", "PITCH"))
        txt = _ai_sales_answer(name=name, segment=segment, goal=goal, user_text=text_in, intent_hint="DIFF")
        return (txt or "").strip() or _fallback_min_reply(name)

    if intent == "WHAT_IS":
        st["stage"] = "ASK_NAME" if not name else st.get("stage", "VALUE")
        txt = _ai_sales_answer(name=name, segment=segment, goal=goal, user_text=text_in, intent_hint="what_is")
        return (txt or "").strip() or _fallback_min_reply(name)

    # 1) Captura nome se não temos (IA decide; não usar heurística aqui)
    if not name:
        # Saudação pura = SALES -> pede nome, mas NÃO persiste ainda (persistência é fora daqui)
        st["stage"] = "ASK_NAME"
        st["nudges"] = nudges + 1
        if st["nudges"] >= 3:
            st["stage"] = "EXIT"
            return "Tranquilo 🙂 Se tu quiser falar do MEI Robô depois, é só mandar uma mensagem por aqui."
        return OPENING_ASK_NAME

    # 2) Captura segmento se não temos
    if not segment:
        seg = _extract_segment(text_in)
        if seg:
            st["segment"] = seg
            segment = seg
            st["stage"] = "PITCH"
        else:
            st["stage"] = "ASK_SEGMENT"
            st["nudges"] = nudges + 1
            if st["nudges"] >= 4:
                st["stage"] = "EXIT"
                return f"Fechado, {name} 🙂 Se tu quiser retomar depois, me diz só teu ramo e eu te ajudo."
            return f"Show, {name} 😄\n\nTeu negócio é do quê?"

# 3) Temos nome + segmento: entregar valor + preço como diferencial + CTA site

    # Se o lead está frio, não despeja pitch. Responde curto e deixa a porta aberta.
    if interest == "low" and intent not in ("PRICE", "PLANS", "DIFF", "ACTIVATE"):
        # pergunta 1 vez e guarda stage pra não ficar chato
        if stage != "ASK_GOAL" and not goal:
            st["stage"] = "ASK_GOAL"
            st["nudges"] = nudges + 1
            return f"Entendi, {name} 🙂 Me diz teu objetivo principal no WhatsApp: agenda, pedidos ou orçamento?"
        # se já perguntou e ainda não veio goal, não insiste
        if not goal:
            return f"Tranquilo, {name} 🙂 Se quiser, me fala só o teu caso em 1 frase que eu te digo se encaixa."
    
    if intent == "ACTIVATE":
        # Só manda CTA direto quando o lead estiver quente
        if interest == "high":
            return f"Se fizer sentido, dá uma olhada em {SITE_URL} e me chama aqui que eu te guio."
        return f"Fechado, {name} 😄 Me diz teu objetivo principal no WhatsApp (agenda, pedidos, orçamento...) que eu te aponto o caminho certo."
    # IA só no pitch (com cache) — preço/CTA ficam fixos
    hint = intent or "OTHER"
    cached = _get_cached_pitch(segment, hint, text_in)
    if cached:
        pitch_txt = cached
    else:
        pitch_txt = _ai_pitch(name=name, segment=f"{segment} | objetivo: {goal}" if goal else segment, user_text=text_in)
        pitch_txt = (pitch_txt or "").strip()
        if pitch_txt:
            _set_cached_pitch(segment, hint, text_in, pitch_txt)

    # Teaser de preço/planos vem do KB (Firestore). Se não tiver, não inventa.
    kb = _get_sales_kb()
    teasers = kb.get("pricing_teasers", [])
    teaser = ""
    if isinstance(teasers, list) and teasers:
        teaser = str(teasers[0]).strip()
    if teaser:
        teaser = teaser.strip()

    cta = f"Se fizer sentido, dá uma olhada em {SITE_URL} e me chama aqui que eu te guio."

    # HIGH: pode aprofundar 1 linha + CTA opcional
    if interest == "high" or intent == "ACTIVATE":
        extra = "Se tu quiser, me diz teu ramo e eu te mostro um exemplo bem real em 2 mensagens."
        parts = [p for p in [pitch_txt, extra, teaser, cta] if (p or '').strip()]
        return "\n\n".join(parts).strip() or _fallback_min_reply(name)

    # MID: valor + teaser (sem virar panfleto)
    if interest == "mid":
        parts = [p for p in [pitch_txt, teaser] if (p or '').strip()]
        return "\n\n".join(parts).strip() or _fallback_min_reply(name)

    # LOW: só mantém curto e seguro
    return (pitch_txt or '').strip() or _fallback_min_reply(name)


def generate_reply(text: str, ctx: Optional[Dict[str, Any]] = None) -> str:
    """
    Retorna somente o texto de resposta (usado pelo wa_bot.reply_to_text).
    ctx deve conter 'from_e164' (ou 'from') para manter o estado no cache.
    """
    ctx = ctx or {}
    text_in = (text or "").strip()

    # aceitar áudio como gatilho de resposta (mantém coerência)
    if not text_in:
        text_in = "Lead enviou um áudio."

    from_e164 = str(ctx.get("from_e164") or ctx.get("from") or "").strip()
    if not from_e164:
        # sem remetente no ctx, responde padrão (sem estado)
        return OPENING_ASK_NAME

    st, wa_key = _load_state(from_e164)
    reply = _reply_from_state(text_in, st)

    # marca interesse no state (pra lead store)
    try:
        # _reply_from_state já calcula interest, mas não guarda; guardamos leve
        nlu = sales_micro_nlu(text_in, stage=(st.get("stage") or "ASK_NAME"))
        st["interest_level"] = (nlu.get("interest_level") or "").strip().lower()
    except Exception:
        pass

    has_name = bool((st.get("name") or "").strip())
    has_segment = bool((st.get("segment") or "").strip())

    # Sessão: sempre salva stage/slots por um tempo curto (mantém contexto)
    # Antes de virar lead real: TTL curto; depois: TTL maior
    if has_name or has_segment:
        _save_session(wa_key, st, ttl_seconds=int(os.getenv("INSTITUTIONAL_SESSION_TTL_KNOWN", "86400") or "86400"))  # 24h
        # Lead store (marketing / “desconhecido conhecido”)
        _upsert_lead_from_state(wa_key, st)
    else:
        st_min = {
            "stage": (st.get("stage") or "ASK_NAME"),
            "turns": int(st.get("turns") or 0),
            "nudges": int(st.get("nudges") or 0),
            "last_user_at": time.time(),
        }
        _save_session(wa_key, st_min, ttl_seconds=int(os.getenv("INSTITUTIONAL_SESSION_TTL_UNKNOWN", "600") or "600"))  # 10 min


    return (reply or "").strip() or OPENING_ASK_NAME

def handle_sales_lead(change_value: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handler de vendas (lead).
    Retorna:
      - replyText: texto normal
      - ttsText (opcional): texto otimizado para fala (quando inbound é áudio)
      - audioUrl (opcional): URL de áudio institucional (quando inbound é áudio)
    """
    from_e164 = _extract_sender(change_value) or ""
    if not from_e164:
        return {"replyText": OPENING_ASK_NAME}

    is_audio = _is_audio_inbound(change_value)
    text_in = _extract_inbound_text(change_value) or ""

    # Se veio áudio e não há texto, cria um gatilho neutro pra não resetar a conversa
    if is_audio and not text_in:
        text_in = _audio_fallback_text()

    ctx = {"from_e164": from_e164, "msg_type": "audio" if is_audio else "text"}
    reply = generate_reply(text_in, ctx=ctx)

    out: Dict[str, Any] = {"replyText": reply}

    if is_audio:
        # Texto "falável" (sorriso + ritmo) para TTS
        tts_text = ""
        try:
            st, _ = _load_state(from_e164)
            if not st.get("interest_level"):
                try:
                    nlu = sales_micro_nlu(text_in, stage=(st.get("stage") or "ASK_NAME"))
                    st["interest_level"] = (nlu.get("interest_level") or "").strip().lower()
                except Exception:
                    pass
            tts_text = _stylize_for_sales_audio(reply, st)
        except Exception:
            tts_text = ""

        if tts_text:
            out["ttsText"] = tts_text

        # Gera audioUrl (best-effort). Se falhar, não quebra.
        try:
            from services.institutional_tts_media import generate_institutional_audio_url
            base_url = os.environ.get("BACKEND_BASE_URL", "").rstrip("/")
            audio_url = generate_institutional_audio_url(
                text=(tts_text or reply),
                base_url=base_url,
            )
            if audio_url:
                out["audioUrl"] = audio_url
        except Exception:
            pass

    return out






