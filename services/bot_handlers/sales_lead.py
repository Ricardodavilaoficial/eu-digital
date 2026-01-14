# services/bot_handlers/sales_lead.py
# Handler isolado: Vendas (lead) — Opção B (2025-12-26) + refinamentos (2026-01)
# - Conteúdo público (sem dados privados)
# - Sem ações irreversíveis
# - Webhook deve ser "burro": este handler vive no wa_bot
#
# Objetivo dos refinamentos:
# - IA ponta-a-ponta (sem frases prontas como resposta final)
# - Firestore como fonte de verdade
# - Sem duplicar geração de áudio (o worker é o dono do canal)
# - Menos custo: reduzir chamadas repetidas e usar cache

from __future__ import annotations

import os
import time
import json
import re
import hashlib
import requests
from typing import Any, Dict, Optional, Tuple


# Safe import (best-effort): usado só para observabilidade
try:
    from google.cloud import firestore  # type: ignore
except Exception:
    firestore = None  # type: ignore

# --- Sales usage logger (lightweight, best-effort) ---
def _log_sales_usage(
    fs,
    wa_key: str,
    stage: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
):
    try:
        ref = fs.collection("platform_sales_usage").document(wa_key)
        ref.set(
            {
                "turns": firestore.Increment(1),
                "ai_calls": firestore.Increment(1),
                "approx_tokens_in": firestore.Increment(int(tokens_in or 0)),
                "approx_tokens_out": firestore.Increment(int(tokens_out or 0)),
                "last_stage": stage,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    except Exception:
        # nunca quebra o fluxo de vendas
        pass


# =========================
# Conteúdo CANÔNICO (VENDAS)
# =========================

SITE_URL = os.getenv("MEI_ROBO_SITE_URL", "www.meirobo.com.br").strip()

# Mensagem mínima de entrada (mantida local por segurança operacional)
OPENING_ASK_NAME = (
    "Oi! 👋 Valeu por chamar 🙂\n\n"
    "Antes de eu te explicar certinho,\n"
    "como posso te chamar?"
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

SALES_NLU_TIMEOUT = int(os.getenv("SALES_NLU_TIMEOUT", "20") or "20")
SALES_CHAT_TIMEOUT = int(os.getenv("SALES_CHAT_TIMEOUT", "20") or "20")

# Guardrails de custo e “curioso infinito”
SALES_MAX_FREE_TURNS = int(os.getenv("SALES_MAX_FREE_TURNS", "9") or "9")  # após isso, encurta e fecha
SALES_MAX_CHARS_REPLY = int(os.getenv("SALES_MAX_CHARS_REPLY", "900") or "900")
SALES_MIN_ADVANCE_SLOTS = int(os.getenv("SALES_MIN_ADVANCE_SLOTS", "2") or "2")  # nome+ramo já dá 2 slots
SALES_PITCH_MAX_TOKENS = int(os.getenv("SALES_PITCH_MAX_TOKENS", "180") or "180")
SALES_ANSWER_MAX_TOKENS = int(os.getenv("SALES_ANSWER_MAX_TOKENS", "220") or "220")

# =========================
# Sales KB (Firestore-first)
# Fonte de verdade: platform_kb/sales (doc único)
# =========================

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
            "behavior_rules": [],
            "ethical_guidelines": [],
            "identity_positioning": "",
            "value_props": [],
            "how_it_works": [],
            "qualifying_questions": [],
            "pricing_behavior": [],
            "pricing_facts": {},
            "pricing_teasers": [],
            "segments": {},
            "objections": {},
            "version": "local_min",
        }

    _SALES_KB_CACHE = kb
    _SALES_KB_CACHE_AT = now
    return kb


# =========================
# Helpers: parsing simples
# =========================

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _hash_reply(text: str) -> str:
    t = _norm(text or "")
    if not t:
        return ""
    return hashlib.sha1(t.encode("utf-8", errors="ignore")).hexdigest()[:16]

def _excerpt(text: str, max_len: int = 240) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]

def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if n <= 0:
        return ""
    return s[:n]


def _sanitize_spoken(text: str) -> str:
    """
    Garante uma fala neutra e humana.
    Remove gírias de abertura que derrubam a humanização no áudio.
    """
    t = (text or "").strip()
    if not t:
        return ""

    # Normaliza espaços
    t = re.sub(r"\s+", " ", t).strip()

    # Mata aberturas ruins (caso apareçam por qualquer motivo)
    # Ex.: "Fala!" / "Fala, ..." / "Falaa!"
    t = re.sub(r"^(fala+[\s,!\.\-–—]*)", "", t, flags=re.IGNORECASE).strip()

    # Se ficou vazio (raro), retorna algo seguro
    if not t:
        return "Oi 🙂"

    return t


def _strip_repeated_greeting(text: str, name: str, turns: int) -> str:
    """
    Evita repetição de saudação/identidade em turnos seguidos.
    Regra: a partir do 2º turno, não começar com "Oi/Olá" nem "Eu sou o MEI Robô".
    """
    t = (text or "").strip()
    if not t:
        return ""
    if int(turns or 0) <= 1:
        return t

    # Normaliza espaços
    t = re.sub(r"\s+", " ", t).strip()

    nm = (name or "").strip()
    if nm:
        # Remove "Oi, Nome!" / "Olá, Nome!"
        t = re.sub(
            r"^(oi|ol[áa])[\s,!\.\-–—]*" + re.escape(nm) + r"[\s,!\.\-–—]*",
            "",
            t,
            flags=re.IGNORECASE,
        ).strip()

        # Remove vocativo repetido: "Nome!" / "Nome," no início
        t = re.sub(r"^" + re.escape(nm) + r"[\s,!\.\-–—]*", "", t, flags=re.IGNORECASE).strip()

    # Remove "Oi!" / "Olá!"
    t = re.sub(r"^(oi|ol[áa])[\s,!\.\-–—]*", "", t, flags=re.IGNORECASE).strip()

    # Remove auto-identificação repetida
    t = re.sub(r"^eu sou o mei rob[oô][^\.!\?]*[\.!\?]\s*", "", t, flags=re.IGNORECASE).strip()

    return t


def _limit_questions(text: str, max_questions: int = 1) -> str:
    """Garante no máximo N perguntas por resposta (barato e seguro)."""
    t = (text or "").strip()
    if not t:
        return t
    try:
        max_q = int(max_questions)
    except Exception:
        return t
    if max_q <= 0:
        return re.sub(r"\?+", ".", t).strip()

    q_pos = [m.start() for m in re.finditer(r"\?", t)]
    if len(q_pos) <= max_q:
        return t

    keep_at = q_pos[max_q - 1]
    head = t[: keep_at + 1]
    tail = t[keep_at + 1 :].replace("?", ".")
    out = (head + tail).replace("..", ".")
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _looks_like_greeting(t: str) -> bool:
    t = _norm(t)
    return t in ("oi", "olá", "ola", "e aí", "eai", "bom dia", "boa tarde", "boa noite", "oii", "oiii")

def _intent_cheap(t: str) -> str:
    """
    Hint barato (não é fonte canônica). O canônico vem da IA (sales_micro_nlu).
    """
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
    t = re.sub(r"[\.!\?]+$", "", t).strip()
    if not t:
        return ""

    m = re.search(
        r"(me chamo|meu nome é|meu nome e|aqui é|aqui e|eu sou|sou)\s+(?:o|a)?\s*([a-zA-ZÀ-ÿ'\- ]{2,40})$",
        t,
        re.IGNORECASE
    )
    if m:
        name = (m.group(2) or "").strip()
        name = re.sub(r"\s+", " ", name)
        if len(name.split(" ")) > 4:
            name = " ".join(name.split(" ")[:3])
        return name

    if len(t.split(" ")) <= 3 and "?" not in t and len(t) <= 32:
        return re.sub(r"\s+", " ", t).strip()

    return ""

def _extract_segment_hint(text: str) -> str:
    """
    Hint barato (não é fonte canônica). Se não encaixar, fica vazio.
    Segmentos são infinitos; isso aqui só resolve ruído óbvio.
    """
    t = _norm(text)
    if not t:
        return ""

    if any(k in t for k in ("cabelo", "cabeleireir", "barbear", "salão", "salao", "beleza", "unha", "estética", "estetica")):
        return "beleza"
    if "dent" in t or "odonto" in t:
        return "dentista"
    if any(k in t for k in ("advoc", "advog", "jurid", "juríd", "escritorio", "escritório", "contab", "contador", "contabilidade", "psicol", "psicó", "terapia", "clinica", "clínica", "consult", "medic", "médic")):
        return "consultorio"
    if any(k in t for k in ("lanche", "lanches", "hamburg", "pizza", "comida", "marmita", "delivery", "restaurante")):
        return "lanches"
    if any(k in t for k in ("serviço", "servico", "prestador", "conserto", "reforma", "instala", "manutenção", "manutencao")):
        return "servicos"
    if any(k in t for k in ("oficina", "mecânica", "mecanica", "carro", "moto")):
        return "oficina"
    return ""

def _extract_goal_hint(text: str) -> str:
    t = _norm(text)
    if not t:
        return ""
    if any(k in t for k in ("agenda", "agendar", "horário", "horario", "marcar", "consulta")):
        return "agenda"
    if any(k in t for k in ("pedido", "pedidos", "anotar", "comanda", "delivery", "entrega")):
        return "pedidos"
    if any(k in t for k in ("orçamento", "orcamento", "cotação", "cotacao", "preço do serviço", "valor do serviço")):
        return "orcamento"
    if any(k in t for k in ("dúvida", "duvida", "perguntas", "triagem", "filtrar")):
        return "triagem"
    return ""



def _pricing_stage_from_state(lead_state: dict, intent: str) -> str:
    turns = lead_state.get("turns", 0)
    saw_examples = lead_state.get("saw_operational_example", False)

    if turns <= 2:
        return "early"

    if saw_examples:
        return "contextual"

    if intent in ("pricing", "contratar", "assinar"):
        return "decision"

    return "contextual"

def _apply_next_step_safely(st: Dict[str, Any], next_step: str, has_name: bool, has_segment: bool, has_goal: bool) -> None:
    """
    next_step (IA) é sugestão. Nunca pode contradizer o que falta.
    Só ajusta stage quando for seguro.
    """
    ns = (next_step or "").strip().upper()
    if not ns:
        return

    if not has_name:
        st["stage"] = "ASK_NAME"
        return
    if not has_segment:
        st["stage"] = "ASK_SEGMENT"
        return
    if not has_goal and ns in ("VALUE", "CTA", "PRICE"):
        st["stage"] = "ASK_GOAL"
        return

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
# Human Gate (anti-ruído no 1º contato)
# - Ativa só no início, só 1x por lead
# - Responde curto e puxa pro trilho
# =========================

_HUMAN_NOISE_PATTERNS = [
    r"\b(e bot|é bot|eh bot|tu é bot|vc é bot|você é bot|rob[oô])\b",
    r"\b(teste|testando|to testando|tô testando|só testando)\b",
    r"\b(kkk+|haha+|rsrs+)\b",
    r"\b(futebol|time|gol|gr[êe]mio|inter|flamengo|corinthians|palmeiras)\b",
    r"\b(clima|tempo|chuva|calor|frio)\b",
    r"[\U0001F600-\U0001F64F]",  # emojis básicos (range)
]

# Palavras que indicam intenção prática (não deve acionar Human Gate)
_HUMAN_NOISE_EXCLUDE = [
    "preço", "preco", "valor", "plano", "planos", "quanto custa",
    "agenda", "agendar", "horário", "horario", "pedido", "pedidos",
    "orçamento", "orcamento", "ativar", "assinar", "contratar",
    "como funciona", "funciona", "meirobo", "mei robô", "mei robo",
]

def _detect_human_noise(text: str) -> bool:
    """
    Detecta ruído humano típico de 1º contato (piada, 'é bot?', clima, futebol, teste).
    Barato: regex + lista. Só para início de conversa.
    """
    t = (text or "").strip()
    if not t:
        return False

    tl = t.lower()

    # Se tem intenção prática, não é ruído
    for w in _HUMAN_NOISE_EXCLUDE:
        if w in tl:
            return False

    # Mensagens muito curtas são mais propensas a ruído
    if len(tl) <= 6 and tl in ("oi", "olá", "ola", "eai", "e aí", "opa", "bom dia", "boa tarde", "boa noite"):
        return False

    # Match de padrões
    for pat in _HUMAN_NOISE_PATTERNS:
        try:
            if re.search(pat, tl, re.IGNORECASE):
                return True
        except Exception:
            continue

    # Heurística: pergunta “solta” sem contexto (ex.: "qual teu time?")
    if "?" in tl and len(tl) <= 40:
        if any(x in tl for x in ("time", "futebol", "bot", "robô", "robo", "tempo", "clima")):
            return True

    return False


def _human_gate_reply() -> str:
    # 1 pergunta só, acolhe e puxa pro trilho
    return "😂 Respondo sim. Valeu por chamar 🙂 Como posso te chamar?"
# =========================
# Estado institucional (Firestore)
# =========================

from services.institutional_leads_store import (  # type: ignore
    get_session, set_session,
    get_lead, upsert_lead,
)
from services.institutional_leads_store import (  # type: ignore
    get_lead_profile, upsert_lead_profile,
)


def _load_state(from_sender: str) -> Tuple[dict, str]:
    """
    Retorna (state_dict, wa_key_escolhida).
    - sessão é cache curto
    - se existir lead em institutional_leads, ele é canônico
    """
    # 0) Perfil canônico durável (sem TTL) — base de identidade
    prof, wa_keyp = get_lead_profile(from_sender)
    # 1) Sessão curta (cache)
    sess, wa_key = get_session(from_sender)
    # 2) Lead “funil” (TTL opcional)
    lead, wa_key2 = get_lead(from_sender)
    wa_key = wa_key or wa_keyp or wa_key2

    if isinstance(sess, dict) and sess:
        # Enriquecimento por prioridade:
        # perfil durável -> lead funil -> sessão
        # (sessão é o "container" aqui)
        if isinstance(prof, dict) and prof:
            dn = (prof.get("displayName") or "").strip()
            if dn and not (sess.get("name") or "").strip():
                sess["name"] = dn
            segp = (prof.get("segment") or "").strip()
            if segp and not (sess.get("segment") or "").strip():
                sess["segment"] = segp
            gp = (prof.get("goal") or "").strip()
            if gp and not (sess.get("goal") or "").strip():
                sess["goal"] = gp
            uidp = (prof.get("uid") or "").strip()
            if uidp and not (sess.get("uid") or "").strip():
                sess["uid"] = uidp

        if isinstance(lead, dict) and lead:
            for k in ("name", "segment", "goal", "interest_level"):
                v = lead.get(k)
                if isinstance(v, str):
                    v = v.strip()
                if v and not (sess.get(k) or "").strip():
                    sess[k] = v
        return sess, wa_key

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
        # Perfil durável pode preencher buracos (prioridade maior que lead TTL)
        if isinstance(prof, dict) and prof:
            dn = (prof.get("displayName") or "").strip()
            if dn and not st.get("name"):
                st["name"] = dn
            segp = (prof.get("segment") or "").strip()
            if segp and not st.get("segment"):
                st["segment"] = segp
            gp = (prof.get("goal") or "").strip()
            if gp and not st.get("goal"):
                st["goal"] = gp
        if not (st.get("name") or st.get("segment")):
            st["stage"] = "ASK_NAME"
        return st, wa_key

    # Nenhum lead/sessão: ainda pode haver perfil durável
    if isinstance(prof, dict) and prof:
        st = {
            "stage": "ASK_NAME",
            "name": (prof.get("displayName") or "").strip(),
            "segment": (prof.get("segment") or "").strip(),
            "goal": (prof.get("goal") or "").strip(),
            "turns": 0,
            "nudges": 0,
            "last_user_at": time.time(),
        }
        if st.get("name") and not st.get("segment"):
            st["stage"] = "ASK_SEGMENT"
        if st.get("name") and st.get("segment"):
            st["stage"] = "PITCH"
        return st, wa_key

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


    # Perfil canônico durável (SEM TTL) — identidade do lead
    try:
        patch: Dict[str, Any] = {
            "displayName": name,
            "segment": segment,
            "goal": goal,
            "nameSource": (st.get("name_source") or "").strip() or "sales_lead",
        }
        upsert_lead_profile(wa_key, patch)
    except Exception:
        pass


    # Índice permanente de identidade (lead): sender_uid_links/{waKey}
    try:
        from services.sender_uid_links import upsert_lead as _upsert_sender_lead  # type: ignore
        _upsert_sender_lead(wa_key, display_name=name, source="sales_lead")
    except Exception:
        pass


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


# =========================
# OpenAI helpers (mínimo)
# =========================

def _openai_chat(prompt_or_messages, *, model: str = "", max_tokens: int = 160, temperature: float = 0.35, response_format: Optional[Dict[str, Any]] = None) -> str:
    if not OPENAI_API_KEY:
        return ""
    use_model = (model or OPENAI_SALES_MODEL).strip() or OPENAI_SALES_MODEL

    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    if isinstance(prompt_or_messages, list):
        messages = prompt_or_messages
    else:
        prompt = str(prompt_or_messages or "").strip()
        messages = [
            {"role": "system", "content": "Você é um atendente de vendas via WhatsApp. Seja humano, curto e direto."},
            {"role": "user", "content": prompt},
        ]

    payload = {
        "model": use_model,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "messages": messages,
    }
    if isinstance(response_format, dict) and response_format:
        payload["response_format"] = response_format


    try:
        r = requests.post(url, headers=headers, json=payload, timeout=SALES_CHAT_TIMEOUT)
        if r.status_code != 200:
            return ""
        data = r.json() or {}
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = (choices[0] or {}).get("message") or {}
        return (msg.get("content") or "").strip()
    except Exception:
        return ""


def _sales_nlu_http(messages) -> Optional[str]:
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
        js = r.json() or {}
        content = (js.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return content
    except Exception:
        return None


def sales_micro_nlu(text: str, stage: str = "") -> Dict[str, Any]:
    """
    SEMPRE IA: classifica se é SALES / OFFTOPIC / EMERGENCY e extrai nome/segmento quando existirem.
    """
    text = (text or "").strip()
    if not text:
        return {"route": "sales", "intent": "OTHER", "name": "", "segment": "", "interest_level": "mid", "next_step": ""}

    stage = (stage or "").strip().upper()

    # Heurísticas pequenas só pra economizar IA em casos óbvios (não substitui IA).
    if stage == "ASK_NAME" and text and len(text.strip()) <= 30:
        t = text.strip().lower()
        if any(k in t for k in ("quanto custa", "preço", "preco", "planos", "valor", "mensal", "assinatura")):
            return {"route": "sales", "intent": "OTHER", "name": "", "segment": "", "interest_level": "mid", "next_step": "ASK_NAME"}
        if t in ("oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "eai", "e aí", "opa"):
            return {"route": "sales", "intent": "OTHER", "name": "", "segment": "", "interest_level": "mid", "next_step": ""}
        nm = _extract_name_freeform(text) or text.strip()
        nm = re.sub(r"[\.!\?,;:]+$", "", nm).strip()
        nm = re.sub(r"^(me chamo|meu nome é|meu nome e|aqui é|aqui e|eu sou|sou)\s+(?:o|a)?\s*", "", nm, flags=re.IGNORECASE).strip()
        nm = re.sub(r"\s+", " ", nm).strip()
        if len(nm.split(" ")) > 3:
            nm = " ".join(nm.split(" ")[:3])
        if _looks_like_greeting(nm):
            nm = ""
        return {"route": "sales", "intent": "OTHER", "name": nm, "segment": "", "interest_level": "mid", "next_step": "ASK_SEGMENT"}

    if stage == "ASK_SEGMENT" and text and len(text.strip()) <= 40:
        return {"route": "sales", "intent": "OTHER", "name": "", "segment": text.strip(), "interest_level": "mid", "next_step": "VALUE"}

    system = (
        "Você é um CLASSIFICADOR de mensagens do WhatsApp do MEI Robô (pt-BR). "
        "Responda SOMENTE JSON válido (sem texto extra).\n\n"
        "Objetivo: entender a intenção do usuário para um atendimento de VENDAS do MEI Robô.\n\n"
        "Regras IMPORTANTES (produto):\n"
        "1) Continuidade: se STAGE_ATUAL NÃO for 'ASK_NAME', assuma que a conversa já começou — route DEVE ser 'sales' (exceto emergency).\n"
        "2) Boa-fé: mensagens curtas como 'sim', 'ok', 'pedidos', 'agenda', 'orçamento' normalmente são continuação.\n"
        "3) Não culpar o usuário: evite classificar como 'offtopic' a menos que seja claramente aleatório e a conversa ainda NÃO tenha começado.\n\n"
        "EMERGENCY:\n"
        "- Se pedir telefone dos bombeiros/polícia/SAMU/ambulância, ou mencionar 190/192/193 => route='emergency'.\n"
        "- Em emergency, intent='OTHER', name/segment vazios.\n\n"
        "OFFTOPIC (somente no início):\n"
        "- Use route='offtopic' apenas se STAGE_ATUAL='ASK_NAME' e a mensagem for claramente aleatória.\n\n"
        "Formato do JSON: {route, intent, name, segment, interest_level, next_step}.\n"
        "route: 'sales' | 'offtopic' | 'emergency'.\n"
        "interest_level: 'low' | 'mid' | 'high'.\n"
        "next_step: '' | 'ASK_NAME' | 'ASK_SEGMENT' | 'VALUE' | 'PRICE' | 'CTA' | 'EXIT'.\n"
    )

    user = f"STAGE_ATUAL: {stage}\nMENSAGEM: {text}"

    content = _sales_nlu_http([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])

    if not content:
        return {"route": "sales", "intent": "OTHER", "name": "", "segment": "", "interest_level": "mid", "next_step": ""}

    try:
        out = json.loads(content)
        route = (out.get("route") or "sales").strip().lower()
        if route not in ("sales", "offtopic", "emergency"):
            route = "offtopic"
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


# =========================
# IA: respostas (sempre reescritas)
# =========================

def _kb_compact_for_prompt(kb: Dict[str, Any]) -> Dict[str, Any]:
    kb = kb or {}
    pills = kb.get("sales_pills") or {}
    def _clip(s: str, n: int) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        s = re.sub(r"\s+", " ", s).strip()
        return s[:n]
    def _first_n(arr: Any, n: int) -> list:
        if not isinstance(arr, list):
            return []
        return arr[:n]

    def _pick_map(d: Any, max_items: int = 4) -> Dict[str, str]:
        if not isinstance(d, dict):
            return {}
        out: Dict[str, str] = {}
        for k in list(d.keys())[:max(0, int(max_items or 0))]:
            try:
                v = str(d.get(k) or "").strip()
                if v:
                    out[str(k)[:40]] = v[:220]
            except Exception:
                pass
        return out

    def _clip_long(s: str, n: int) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        s = re.sub(r"\s+", " ", s).strip()
        return s[:n]

    return {
        # super curto (1–2 linhas)
        "identity_blurb": _clip(str(pills.get("identity_blurb") or kb.get("identity_positioning") or ""), 260),
        # regras curtas
        "tone_rules": _first_n(kb.get("tone_rules") or [], 5),
        "behavior_rules": _first_n(kb.get("behavior_rules") or [], 6),
        "ethical_guidelines": _first_n(kb.get("ethical_guidelines") or [], 4),
        "closing_guidance": _first_n(kb.get("closing_guidance") or [], 4),
        # top3 benefícios e 3 passos
        "value_props_top3": _first_n(pills.get("value_props_top3") or kb.get("value_props") or [], 3),
        "how_it_works_3steps": _first_n(pills.get("how_it_works_3steps") or kb.get("how_it_works") or [], 3),
        # qualificação mínima
        "qualifying_questions": _first_n(kb.get("qualifying_questions") or [], 2),
        # preço (fatos ok)
        "pricing_behavior": _first_n(kb.get("pricing_behavior") or [], 4),
        "pricing_facts": kb.get("pricing_facts") or {},
        # blurb compacto (se existir)
        "pricing_blurb": _clip(str(pills.get("pricing_blurb") or kb.get("pricing_reasoning") or ""), 260),
        # CTA curto
        "cta_one_liners": _first_n(pills.get("cta_one_liners") or [], 3),
        "conversation_limits": _clip_long(str(kb.get("conversation_limits") or ""), 420),
        "sales_audio_modes": {
            "demo": _first_n(((kb.get("sales_audio_modes") or {}).get("demo") or []), 6),
            "close": _first_n(((kb.get("sales_audio_modes") or {}).get("close") or []), 7),
        },
        "objections_compact": _pick_map(kb.get("objections") or {}, 4),

    }


def _ai_sales_answer(
    *,
    name: str,
    segment: str,
    goal: str,
    user_text: str,
    intent_hint: str,
    state: Dict[str, Any],
) -> str:
    """
    Resposta final SEMPRE via IA (sem “frase pronta”).
    - Curto e humano.
    - 1 pergunta por vez.
    - Usa Firestore como repertório (sem copiar literal).
    """
    kb = _get_sales_kb()
    rep = _kb_compact_for_prompt(kb)

    # Pricing reasoning por estágio (economia + narrativa) — mantém lógica
    try:
        _stage = _pricing_stage_from_state(state or {}, str(intent_hint or "").strip().lower())
    except Exception:
        _stage = "contextual"
    _base_pr = str(rep.get("pricing_reasoning") or "").strip()

    if _stage == "early":
        rep["pricing_reasoning"] = (
            "O valor entra depois que você entende se faz sentido pro teu negócio. "
            "O ponto principal é reduzir erro, tempo perdido e bagunça no WhatsApp."
        )
    elif _stage == "contextual":
        rep["pricing_reasoning"] = (
            "Aqui a conta é operacional: menos interrupção, menos erro e tudo organizado. "
            "Quando isso faz sentido, o valor acaba sendo pequeno perto do ganho."
        )
    else:  # decision
        rep["pricing_reasoning"] = _base_pr

    # Exemplo operacional selecionado (super compacto quando existir segment_pills)
    op_example = ""
    try:
        sp = (kb.get("segment_pills") or {}).get((segment or "").strip().lower(), {}) if segment else {}
        op_example = str(sp.get("micro_scene") or "").strip()
        if not op_example:
            # fallback: tenta usar operational_examples antigo (se existir)
            op_example = str((kb.get("operational_examples") or {}).get((segment or "").strip().lower(), "") or "").strip()
    except Exception:
        op_example = ""
    rep["operational_example_selected"] = op_example[:320] if op_example else ""

    onboarding_hint = state.get("onboarding_hint") or ""

    stage = (state.get("stage") or "").strip()
    turns = int(state.get("turns") or 0)
    last_bot = (state.get("last_bot_reply_excerpt") or "").strip()

    continuity = f"STAGE={stage or '—'} | TURNS={turns}"
    if last_bot:
        continuity += f" | NÃO repetir: {last_bot}"

    prompt = (
        "Você é o MEI Robô – Vendas, atendendo leads no WhatsApp (pt-BR).\n"
        "Use o conteúdo do Firestore (platform_kb/sales) como REPERTÓRIO de identidade, nunca como script.\n"
        "Nada deve soar decorado, técnico ou robótico.\n\n"
        "SOBERANIA (importante): você decide autonomamente, a cada resposta:\n"
        "- se usa ou não o nome do lead\n"
        "- se demonstra empatia\n"
        "- se aprofunda um pouco mais\n"
        "- se fecha ou apenas orienta\n"
        "Use behavior_rules, tone_rules, closing_guidance, sales_audio_modes e conversation_limits para DECIDIR.\n"
        "Não siga regras mecânicas do tipo “use nome no turno X”.\n\n"
        "- Nunca diga 'meu nome é ...'. Você fala com o lead; não se apresenta como a pessoa.\n"
        "TAMANHO:\n"
        "- Curto por padrão (2–5 linhas).\n"
        "- Pode ser um pouco mais longo quando houver interesse real, confusão, comparação ou quando um exemplo prático ajudar a decidir.\n"
        "- Nunca faça palestra. Nunca repita longamente o que já foi explicado.\n\n"
        "ESTILO:\n"
        "- Conversa, não apresentação.\n"
        "- Confiante e vendedor do bem, sem pressão, sem urgência falsa, sem promessas.\n"
        "- Humor leve quando fizer sentido.\n"
        "- No máximo 1 pergunta por resposta.\n\n"
        "CONTEÚDO:\n"
        "- Priorize sales_pills, value_props_top3, e micro-scenes por segmento.\n"
        "- Use micro-exemplo operacional (entrada → organização → resumo pro dono) quando ajudar.\n"
        "- Nunca invente números.\n"
        "- Só cite preço quando fizer sentido e apenas usando pricing_facts.\n\n"
        "PREÇO:\n"
        "- Não jogar no começo.\n"
        "- Quando entrar, contextualize como custo operacional (tempo, erro, retrabalho).\n\n"
        "FECHAMENTO:\n"
        "- Quando fizer sentido fechar: benefício prático + próximo passo + despedida.\n"
        "- Direcione ao site de forma elegante, sem cortar o lead.\n\n"
        "FORMATO OBRIGATÓRIO:\n"
        "Responda APENAS em JSON válido, sem texto fora do JSON.\n"
        "Schema: {\"replyText\":\"...\",\"nameUse\":\"none|greet|empathy|closing\"}\n"
        "Guia nameUse:\n"
        "- greet: apenas no primeiro contato.\n"
        "- empathy: se houver confusão/insegurança/pressa/preço/comparação.\n"
        "- closing: se estiver fechando com CTA elegante.\n"
        "- none: no resto.\n\n"
        f"Lead:\n- nome: {name or '—'}\n- ramo: {segment or '—'}\n- objetivo: {goal or '—'}\n"
        f"intent_hint: {intent_hint or '—'}\n"
        f"mensagem: {user_text}\n\n"
        f"continuidade: {continuity}\n\n"
        f"onboarding_hint (se existir): {json.dumps(onboarding_hint, ensure_ascii=False)}\n"
        f"repertório_firestore (base, não copie): {json.dumps(rep, ensure_ascii=False, separators=(',', ':'))}\n"
    )

    raw = (_openai_chat(
            prompt,
            max_tokens=SALES_ANSWER_MAX_TOKENS,
            temperature=0.35,
            response_format={"type": "json_object"},
        ) or "").strip()

    reply_text = raw
    name_use = "none"
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            reply_text = str(obj.get("replyText") or "").strip()
            name_use = str(obj.get("nameUse") or "none").strip().lower()
            try:
                if isinstance(state, dict):
                    state["last_name_use"] = name_use
            except Exception:
                pass
    except Exception:
        # fallback: mantém texto bruto
        pass

    # --- lightweight sales usage log ---
    try:
        wa_key = str(state.get("wa_key") or state.get("__wa_key") or "").strip()
        if wa_key and firestore:
            fs = firestore.Client()
            _est_tokens_in = len(prompt) // 4 if prompt else 0
            _est_tokens_out = len(reply_text) // 4 if reply_text else 0

            _log_sales_usage(
                fs=fs,
                wa_key=wa_key,
                stage=intent_hint or "unknown",
                tokens_in=_est_tokens_in,
                tokens_out=_est_tokens_out,
            )
    except Exception:
        pass

    reply_text = _limit_questions(reply_text, max_questions=1)

    # Anti-eco de vocativo: se começar com "<nome>!" ou "<nome>," e a resposta anterior também, corta.
    try:
        nm = (name or "").strip()
        if nm and isinstance(state, dict):
            prev = str(state.get("last_bot_reply_excerpt") or "").strip()
            curr_starts = reply_text.lower().startswith((nm.lower() + "!", nm.lower() + ","))
            prev_starts = prev.lower().startswith((nm.lower() + "!", nm.lower() + ","))
            if curr_starts and prev_starts:
                reply_text = reply_text[len(nm):].lstrip("!, \t\n\r")
                if reply_text:
                    reply_text = reply_text[:1].upper() + reply_text[1:]
    except Exception:
        pass

    # Guard-rail: corta saudação/vocativo repetido quando a IA só "cumprimenta"
    try:
        if name and name_use in ("greet", "none"):
            reply_text = _strip_repeated_greeting(reply_text, name=name, turns=turns)
    except Exception:
        pass

    return reply_text



def _ai_pitch(name: str, segment: str, user_text: str, state: Optional[Dict[str, Any]] = None) -> str:
    """
    Pitch curto e humano usando KB (Firestore).
    Com cache KV (por segmento+hint+user_text normalizado).
    """
    name = (name or "").strip()
    user_text = (user_text or "").strip()

    seg_key = (segment or "").strip().lower() or "geral"
    hint = "pitch_v3"

    cached = _get_cached_pitch(seg_key, hint, user_text)
    if cached:
        return cached

    kb = _get_sales_kb() or {}
    rep = _kb_compact_for_prompt(kb)
    # Seleciona exemplo operacional só quando há segmento (anti-custo)
    examples = {}
    if segment:
        examples = (rep.get("operational_examples") or {}).get(segment.lower(), "")
    rep["operational_example_selected"] = examples

    onboarding_hint = state.get("onboarding_hint") or ""

    # Ajuda: se houver match em segments, puxa use_cases/openers
    segments = kb.get("segments") or {}
    seg_info = segments.get(seg_key) if isinstance(segments, dict) else None
    if not isinstance(seg_info, dict):
        seg_info = {}

    use_cases = seg_info.get("use_cases") or []
    if not isinstance(use_cases, list):
        use_cases = []

    system = (
        "Você é o MEI Robô institucional de VENDAS no WhatsApp.\n"
        "Escreva uma resposta humana, curta e objetiva.\n"
        "Regras:\n"
        "- 2 a 5 linhas.\n"
        "- 1 pergunta no final.\n"
        "- Sem bastidores técnicos.\n"
        "- Sem textão.\n"
        "- Evite frases prontas.\n"
    )

    user_lines = [
        f"Lead: {name or '—'}",
        f"Ramo (texto livre): {segment or '—'}",
        f"Mensagem: {user_text or '—'}",
    ]
    if use_cases:
        user_lines.append("Use cases relevantes (escolha 1–2, só pra inspirar):")
        user_lines.extend([f"- {str(x).strip()}" for x in use_cases[:4] if str(x).strip()])

    user_lines.append(f"Repertório Firestore (base, não copie): {json.dumps(rep, ensure_ascii=False)}")
    user_lines.append("Agora escreva a resposta final.")

    out = _openai_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(user_lines)}],
        max_tokens=SALES_PITCH_MAX_TOKENS,
        temperature=0.4,
    ).strip()

    # --- lightweight sales usage log ---
    try:
        state = state or {}
        wa_key = str(state.get("wa_key") or state.get("__wa_key") or "").strip()
        if wa_key and firestore:
            fs = firestore.Client()
            _prompt_chars = len(system or "") + len("\n".join(user_lines) if user_lines else "")
            _est_tokens_in = _prompt_chars // 4 if _prompt_chars else 0
            _est_tokens_out = len(out) // 4 if out else 0

            _log_sales_usage(
                fs=fs,
                wa_key=wa_key,
                stage="PITCH",
                tokens_in=_est_tokens_in,
                tokens_out=_est_tokens_out,
            )
    except Exception:
        pass



    if not out:
        out = "Posso te mostrar um exemplo bem real no teu caso. Teu foco hoje é pedidos, agenda ou orçamento?"

    _set_cached_pitch(seg_key, hint, user_text, out)
    return out


# =========================
# Anti-loop helper
# =========================

def _apply_anti_loop(st: Dict[str, Any], txt: str, *, name: str, segment: str, goal: str, user_text: str) -> str:
    """
    Se repetir o mesmo hash, pede pra IA avançar com pergunta diferente.
    """
    txt = (txt or "").strip()
    if not txt:
        return txt

    prev_h = (st.get("last_bot_reply_hash") or "").strip()
    cur_h = _hash_reply(txt)
    if prev_h and cur_h and prev_h == cur_h:
        alt = (_ai_sales_answer(
            name=name,
            segment=segment,
            goal=goal,
            user_text=user_text,
            intent_hint="ANTI_LOOP",
            state=st,
        ) or "").strip()
        if alt and _hash_reply(alt) != cur_h:
            txt = alt

    st["last_bot_reply_hash"] = _hash_reply(txt)
    st["last_bot_reply_excerpt"] = _excerpt(txt)
    return txt


# =========================
# Core: gerar resposta (texto)
# =========================

def _should_soft_close(st: Dict[str, Any], *, has_name: bool, has_segment: bool) -> bool:
    """
    Política anti-curioso infinito:
    - se excedeu turnos e não coletou o mínimo (nome+ramo),
      ou lead não avança, fecha curto.
    """
    turns = int(st.get("turns") or 0)
    if turns < SALES_MAX_FREE_TURNS:
        return False
    slots = 0
    if has_name:
        slots += 1
    if has_segment:
        slots += 1
    # Se até aqui não coletou o mínimo, ou já é muita conversa, fecha suave
    return slots < SALES_MIN_ADVANCE_SLOTS or turns >= SALES_MAX_FREE_TURNS


def _reply_from_state(text_in: str, st: Dict[str, Any]) -> str:
    """
    Única função que decide a resposta final (texto).
    """
    name = (st.get("name") or "").strip()
    segment = (st.get("segment") or "").strip()
    goal = (st.get("goal") or "").strip()
    stage = (st.get("stage") or "").strip() or "ASK_NAME"

    # Se já temos nome por “desconhecido conhecido”, não pede nome de novo
    if stage == "ASK_NAME" and name:
        st["stage"] = "ASK_SEGMENT" if not segment else "PITCH"
        stage = st["stage"]

    turns = int(st.get("turns") or 0) + 1
    st["turns"] = turns
    st["last_user_at"] = time.time()

    nudges = int(st.get("nudges") or 0)

    # NLU (IA) — fonte canônica de intent/route/next_step/interest
    nlu = sales_micro_nlu(text_in, stage=stage)
    interest = (nlu.get("interest_level") or "mid").strip().lower()
    st["interest_level"] = interest  # evita segunda chamada no generate_reply
    next_step = (nlu.get("next_step") or "").strip().upper()
    route = (nlu.get("route") or "sales").strip().lower()

    # Regra de produto: depois que conversa começou, não existe "offtopic".
    if (route == "offtopic") and (turns > 1 or name or segment or stage != "ASK_NAME"):
        route = "sales"

    # Nome/segmento detectados pela IA (se vier)
    if not name and (nlu.get("name") or ""):
        nm_ai = (nlu.get("name") or "").strip()
        nm_ai = _extract_name_freeform(nm_ai) or nm_ai
        nm_ai = re.sub(r"[\.!\?,;:]+$", "", nm_ai).strip()
        nm_ai = re.sub(r"^(me chamo|meu nome é|meu nome e|aqui é|aqui e|eu sou|sou)\s+(?:o|a)?\s*", "", nm_ai, flags=re.IGNORECASE).strip()
        nm_ai = re.sub(r"\s+", " ", nm_ai).strip()
        if len(nm_ai.split(" ")) > 3:
            nm_ai = " ".join(nm_ai.split(" ")[:3])
        if _looks_like_greeting(nm_ai):
            nm_ai = ""
        st["name"] = nm_ai
        st["name_source"] = (st.get("name_source") or "ai")
        name = st["name"]
    if not segment and (nlu.get("segment") or ""):
        st["segment"] = (nlu.get("segment") or "").strip()
        segment = st["segment"]

    # Fallback barato de extração (não manda na conversa; só evita perder slot óbvio)
    if not name:
        nm = _extract_name_freeform(text_in)
        if nm and not _looks_like_greeting(nm):
            st["name"] = nm
            st["name_source"] = (st.get("name_source") or "regex")
            name = nm
    if not segment:
        sg = _extract_segment_hint(text_in)
        if sg:
            st["segment"] = sg
            segment = sg

    if not goal:
        g = _extract_goal_hint(text_in)
        if g:
            st["goal"] = g
            goal = g

    has_name = bool(name)
    has_segment = bool(segment)
    has_goal = bool(goal)

    _apply_next_step_safely(st, next_step, has_name=has_name, has_segment=has_segment, has_goal=has_goal)
    stage = (st.get("stage") or stage or "").strip() or "ASK_NAME"

    if route == "emergency":
        return "Se for emergência, liga 193 agora. 🙏"

    if route == "offtopic":
        # só pode acontecer no início absoluto
        return "Oi! 👋 Valeu por chamar 🙂 Antes de eu te explicar certinho, como posso te chamar?"

    if stage == "EXIT":
        st["__sales_close"] = True
        return "Beleza 🙂 Pra ver tudo com calma e ativar, o melhor é seguir pelo site. Por lá fica tudo certinho."


    # Human Gate: ruído humano no início (piada, "é bot?", clima, futebol, teste)
    # Só roda 1x por lead e só antes de coletar nome/ramo.
    if not st.get("__human_gate_done"):
        if (turns <= 2) and (stage in ("ASK_NAME", "ASK_SEGMENT")) and (not has_name) and (not has_segment):
            if _detect_human_noise(text_in):
                st["__human_gate_done"] = True
                st["stage"] = "ASK_NAME"
                return _human_gate_reply()

    # Anti-custo / soft close
    if _should_soft_close(st, has_name=has_name, has_segment=has_segment):
        intent_now = (nlu.get("intent") or "").strip().upper()
        if intent_now in ("PRICE", "PLANS", "DIFF", "ACTIVATE", "WHAT_IS"):
            st["__sales_close"] = False
        else:
            # sinaliza para o worker que aqui é hora de FECHAR (fala mais vendedora e sem pergunta)
            st["__sales_close"] = True
            # IA também pode fechar (sem frase pronta), mas aqui mantemos bem curto e seguro.
            if has_name:
                return f"{name}, pra ver tudo com calma e ativar, o melhor é pelo site. Se quiser, me diz teu ramo em 1 frase que eu te mostro o caminho mais enxuto 🙂"
            return "Pra ver tudo com calma e ativar, o melhor é pelo site 🙂 Se quiser, me diz teu tipo de negócio em 1 frase que eu te indico o caminho mais enxuto."

    # 1) Nome
    if not has_name:
        st["stage"] = "ASK_NAME"
        st["nudges"] = nudges + 1
        if st["nudges"] >= 3:
            st["stage"] = "EXIT"
            return "Tranquilo 🙂 Pra ver tudo com calma e ativar, o melhor é pelo site. Se quiser retomar depois, é só mandar um oi."
        return OPENING_ASK_NAME

    # 2) Segmento (texto livre)
    if not has_segment:
        st["stage"] = "ASK_SEGMENT"
        st["nudges"] = nudges + 1
        if st["nudges"] >= 4:
            st["stage"] = "EXIT"
            return f"Fechado, {name} 🙂 Pra eu te indicar direitinho, só me diz teu tipo de negócio em 1 frase (ex.: lanches, salão, serviços)."
        # pergunta curta (sem “formulário”)
        return f"Perfeito, {name} 🙂. Qual o segmento do teu negócio?"

    # Intent canônico da IA, com fallback barato
    intent = (nlu.get("intent") or _intent_cheap(text_in) or "OTHER").strip().upper()

    # 🔓 Onboarding helpers (só quando necessário)
    helpers = (_get_sales_kb().get("onboarding_helpers") or {})
    if intent == "ACTIVATE" and helpers:
        st["onboarding_hint"] = helpers

    # Intenções diretas: sempre IA escreve a resposta final
    if intent in ("PRICE", "PLANS", "DIFF", "WHAT_IS"):
        hint = intent
        txt = (_ai_sales_answer(
            name=name, segment=segment, goal=goal, user_text=text_in, intent_hint=hint, state=st
        ) or "").strip()
        if not txt:
            txt = _fallback_min_reply(name)
        txt = _apply_anti_loop(st, txt, name=name, segment=segment, goal=goal, user_text=text_in)
        txt = _strip_repeated_greeting(txt, name=name, turns=turns)
        txt = _limit_questions(txt, max_questions=1)
        return _clip(txt, SALES_MAX_CHARS_REPLY)

    if intent == "ACTIVATE":
        # Sempre via IA também (evita frase pronta)
        txt = (_ai_sales_answer(
            name=name, segment=segment, goal=goal, user_text=text_in, intent_hint="CTA", state=st
        ) or "").strip()
        if not txt:
            txt = f"Fechado, {name} 🙂 Pra ativar com calma, o melhor é seguir pelo site. Quer que eu te diga o caminho mais enxuto pra {goal or 'começar'}?"
        txt = _apply_anti_loop(st, txt, name=name, segment=segment, goal=goal, user_text=text_in)
        txt = _strip_repeated_greeting(txt, name=name, turns=turns)
        txt = _limit_questions(txt, max_questions=1)
        return _clip(txt, SALES_MAX_CHARS_REPLY)

    # Lead frio: pergunta curta, sem despejar pitch
    if interest == "low" and not has_goal:
        st["stage"] = "ASK_GOAL"
        txt = (_ai_sales_answer(
            name=name, segment=segment, goal=goal, user_text=text_in, intent_hint="ASK_GOAL", state=st
        ) or "").strip()
        if not txt:
            txt = f"Entendi, {name} 🙂 Teu foco hoje é mais agenda, pedidos ou orçamento?"
        txt = _apply_anti_loop(st, txt, name=name, segment=segment, goal=goal, user_text=text_in)
        txt = _strip_repeated_greeting(txt, name=name, turns=turns)
        txt = _limit_questions(txt, max_questions=1)
        return _clip(txt, SALES_MAX_CHARS_REPLY)

    # Pitch (cacheado) + sempre uma pergunta de avanço
    hint = intent or "OTHER"
    cached = _get_cached_pitch(segment, hint, text_in)
    if cached:
        pitch_txt = cached
    else:
        pitch_txt = (_ai_pitch(name=name, segment=segment, user_text=text_in, state=st) or "").strip()
        if pitch_txt:
            _set_cached_pitch(segment, hint, text_in, pitch_txt)

    if not pitch_txt:
        pitch_txt = _fallback_min_reply(name)

    # Anti-loop
    pitch_txt = _apply_anti_loop(st, pitch_txt, name=name, segment=segment, goal=goal, user_text=text_in)
    pitch_txt = _strip_repeated_greeting(pitch_txt, name=name, turns=turns)
    pitch_txt = _limit_questions(pitch_txt, max_questions=1)
    return _clip(pitch_txt, SALES_MAX_CHARS_REPLY)


# =========================
# API pública do handler
# =========================

def generate_reply(text: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Retorna um dict canônico.
    Compatível com wa_bot:
      - wa_bot pode ler replyText e ignorar o resto.
    A ideia é: o worker é o dono do áudio; aqui só sai "cérebro".
    """
    ctx = ctx or {}
    text_in = (text or "").strip() or "Lead enviou um áudio."
    from_e164 = str(ctx.get("from_e164") or ctx.get("from") or "").strip()

    # Sem remetente => resposta padrão (sem estado)
    if not from_e164:
        return {
            "replyText": OPENING_ASK_NAME,
            "ttsOwner": "worker",
            "kind": "sales",
        }

    st, wa_key = _load_state(from_e164)
    # wa_key disponível para observabilidade (não afeta fluxo)
    if isinstance(st, dict):
        st["wa_key"] = wa_key
    reply = _reply_from_state(text_in, st)

    # Salva interesse já setado pelo _reply_from_state
    # (sem re-chamar a IA)
    has_name = bool((st.get("name") or "").strip())
    has_segment = bool((st.get("segment") or "").strip())

    if has_name or has_segment:
        _save_session(wa_key, st, ttl_seconds=int(os.getenv("INSTITUTIONAL_SESSION_TTL_KNOWN", "86400") or "86400"))
        _upsert_lead_from_state(wa_key, st)
    else:
        st_min = {
            "stage": (st.get("stage") or "ASK_NAME"),
            "turns": int(st.get("turns") or 0),
            "nudges": int(st.get("nudges") or 0),
            "last_user_at": time.time(),
        }
        _save_session(wa_key, st_min, ttl_seconds=int(os.getenv("INSTITUTIONAL_SESSION_TTL_UNKNOWN", "600") or "600"))

    # Metadados úteis (sem obrigar ninguém a usar):
    # - leadName ajuda humanização no pipeline geral
    # - kind permite (no worker) escolher uma fala mais “com exemplo”
    lead_name = (st.get("name") or "").strip()
    lead_segment = (st.get("segment") or "").strip()
    lead_goal = (st.get("goal") or "").strip()

    # Micro-contexto (compacto) para o worker, caso queira gerar fala “com exemplo”
    kb = _get_sales_kb()
    kb_compact = {
        "tone_rules": kb.get("tone_rules") or [],
        "behavior_rules": kb.get("behavior_rules") or [],
        "ethical_guidelines": kb.get("ethical_guidelines") or [],
        "value_props": kb.get("value_props") or [],
        "qualifying_questions": kb.get("qualifying_questions") or [],
        "pricing_facts": kb.get("pricing_facts") or {},
    }

    # Decide kind final: demo vs fechamento
    stage_now = str(st.get("stage") or "").strip()
    is_close = bool(st.get("__sales_close")) or stage_now in ("CTA", "EXIT")
    if is_close:
        kind = "sales_close"
    else:
        kind = "sales_example" if (lead_segment and (stage_now in ("PITCH", "CTA", "PRICE"))) else "sales"

    reply_final = (reply or "").strip() or OPENING_ASK_NAME
    spoken_final = _sanitize_spoken(reply_final)

    return {
        "replyText": reply_final,
        "nameUse": (st.get("last_name_use") or ""),

        # 🔒 Fonte de verdade para áudio (worker deve preferir estes campos)
        "ttsText": spoken_final,
        "spokenText": spoken_final,
        "spokenSource": "replyText",

        "leadName": lead_name,
        "segment": lead_segment,
        "goal": lead_goal,
        "interest_level": (st.get("interest_level") or "").strip(),
        "kind": kind,
        "kbContext": json.dumps(kb_compact, ensure_ascii=False),
        "ttsOwner": "worker",
        "nameToSay": lead_name,
    }




def handle_sales_lead(change_value: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mantido por compat, mas NÃO é mais o dono do áudio.
    O worker deve decidir canal/TTS para não duplicar custo/bugs.
    """
    from_e164 = ""
    try:
        msgs = (change_value or {}).get("messages") or []
        if msgs and isinstance(msgs, list) and msgs:
            from_e164 = str((msgs[0] or {}).get("from") or "").strip()
    except Exception:
        from_e164 = ""

    if not from_e164:
        return {"replyText": OPENING_ASK_NAME, "ttsOwner": "worker", "kind": "sales"}

    # Extrai texto (quando existir)
    text_in = ""
    try:
        msgs = (change_value or {}).get("messages") or []
        if msgs and isinstance(msgs, list) and msgs:
            m0 = msgs[0] or {}
            if (m0.get("type") == "text") and isinstance(m0.get("text"), dict):
                text_in = str((m0.get("text") or {}).get("body") or "").strip()
    except Exception:
        text_in = ""

    if not text_in:
        text_in = "Lead enviou um áudio."

    return generate_reply(text_in, ctx={"from_e164": from_e164})
