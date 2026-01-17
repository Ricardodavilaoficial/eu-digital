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

# Purificação (incremental e reversível):
# - SALES_STRATEGIC_OVERRIDES=1 mantém overrides antigos (link/procedimento/agenda) por compat.
#   Depois, desligar (=0) para IA+KB assumirem 100% do trilho.
# - SALES_STRICT_NO_PRICE_OUTSIDE_INTENT=1 aplica política dura: fora de PRICE/PLANS/DIFF, não pode sair "R$".

# Mensagem mínima de entrada (mantida local por segurança operacional)
OPENING_ASK_NAME = (
    "Beleza. Antes de eu te explicar certinho, como posso te chamar?"
)

# Fallback humano mínimo (nunca vazio; sem marketing longo)
def _fallback_min_reply(name: str = "") -> str:
    name = (name or "").strip()
    if name:
        return f"{name}, perfeito. Você quer falar de pedidos, agenda, orçamento ou só conhecer?"
    return "Beleza. Me diz teu nome e o que você quer resolver: pedidos, agenda, orçamento ou só entender como funciona?"



def _composer_mode() -> str:
    """Modo do composer (separa decisão de fala).

    - legacy: mantém compat (Planner pode devolver reply).
    - v1: Planner decide (intent/next_step/tone/kb_need) e o Composer gera o texto final.

    Use env: SALES_COMPOSER_MODE=legacy|v1
    """
    try:
        m = str(os.getenv("SALES_COMPOSER_MODE", "legacy") or "legacy").strip().lower()
    except Exception:
        m = "legacy"
    if m in ("1", "true", "on", "yes"):
        return "v1"
    if m in ("v1", "composer", "new"):
        return "v1"
    return "legacy"


def _compose_from_plan(
    *,
    plan: Dict[str, Any],
    name: str,
    segment: str,
    goal: str,
    user_text: str,
    state: Dict[str, Any],
    scene_text: str = "",
) -> str:
    """Gera o texto final a partir do plano (IA decide; composer fala).

    Importante: aqui não há estratégia escondida. Só executa o plano:
    - escolhe intent_hint coerente
    - injeta cena (quando fizer sentido)
    - garante link quando next_step=SEND_LINK
    """
    try:
        intent_p = str(plan.get("intent") or "OTHER").strip().upper()
    except Exception:
        intent_p = "OTHER"
    try:
        ns = str(plan.get("next_step") or "").strip().upper()
    except Exception:
        ns = ""

    # Mapeia o plano para um hint canônico (sem inventar estratégia).
    if ns in ("CTA", "SEND_LINK") or intent_p == "ACTIVATE":
        intent_hint = "CTA"
    else:
        intent_hint = intent_p

    txt = (_ai_sales_answer(
        name=name,
        segment=segment,
        goal=goal,
        user_text=user_text,
        intent_hint=intent_hint,
        state=state,
    ) or "").strip()

    if not txt:
        txt = _fallback_min_reply(name)

    # Injeta micro-cena (sem inventar), apenas se a resposta não veio em formato de fluxo
    if scene_text:
        try:
            if "→" not in txt and intent_p in ("OPERATIONAL", "OTHER", "OBJECTION"):
                txt = (scene_text + "\n" + txt).strip()
        except Exception:
            pass

    # Garantia de link quando o plano pede link
    if ns == "SEND_LINK":
        try:
            if not _has_url(txt):
                txt = (txt.rstrip() + f"\n\n{SITE_URL}").strip()
        except Exception:
            txt = (txt.rstrip() + f"\n\n{SITE_URL}").strip()
        # SEND_LINK é fechamento: sem pergunta
        txt = _strip_trailing_question(txt)

    return txt


def _has_url(s: str) -> bool:
    t = (s or "").lower()
    return ("http://" in t) or ("https://" in t) or ("www." in t) or ("meirobo.com.br" in t) or ("[site" in t)


def _strategic_overrides_enabled() -> bool:
    """Compat: overrides estratégicos antigos (link/procedimento/agenda).
    Desligar para evitar competição com IA+Firestore.
    """
    v = str(os.getenv("SALES_STRATEGIC_OVERRIDES", "1") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _strict_no_price_outside_intent() -> bool:
    v = str(os.getenv("SALES_STRICT_NO_PRICE_OUTSIDE_INTENT", "0") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def _strip_price_mentions(text: str) -> str:
    """Remove menções explícitas de preço (R$...) de forma conservadora.
    Usado apenas quando SALES_STRICT_NO_PRICE_OUTSIDE_INTENT=1.
    """
    t = (text or "").strip()
    if not t or "r$" not in t.lower():
        return t

    # Remove padrões comuns "R$ 99", "R$99,90", "R$ 1.234,56".
    t2 = re.sub(r"\bR\$\s*\d{1,3}(?:\.\d{3})*(?:,\d{2})?\b", "valor do plano", t, flags=re.IGNORECASE)
    # Se sobrar "valor do plano" repetido, normaliza.
    t2 = re.sub(r"(valor do plano\s*){2,}", "valor do plano ", t2, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t2).strip()

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

def _fmt_brl_from_cents(cents: Any) -> str:
    try:
        c = int(cents)
        if c <= 0:
            return ""
        # 8900 -> "R$ 89,00"
        reais = c // 100
        cent = c % 100
        return f"R$ {reais},%02d" % cent
    except Exception:
        return ""


def _merge_platform_pricing_into_kb(kb: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mantém 'preço em um único lugar' (platform_pricing/current).
    Se a KB trouxer pricing_facts.pricing_ref apontando para o doc canônico,
    puxa o doc e mapeia para as chaves que o runtime usa (starter_price/starter_plus_price).
    Best-effort: nunca quebra o fluxo.
    """
    try:
        pf = (kb or {}).get("pricing_facts") or {}
        if not isinstance(pf, dict):
            return kb

        ref_path = str(pf.get("pricing_ref") or "").strip()
        if not ref_path:
            return kb

        # já tem os campos que o enforcement usa -> ok
        if str(pf.get("starter_price") or "").strip() and str(pf.get("starter_plus_price") or "").strip():
            kb["pricing_source"] = ref_path
            return kb

        # busca doc canônico
        try:
            from google.cloud import firestore  # type: ignore
            client = firestore.Client()
        except Exception:
            return kb

        parts = [p for p in ref_path.split("/") if p]
        if len(parts) < 2:
            return kb

        doc = client.collection(parts[0]).document(parts[1]).get()
        if not doc or not doc.exists:
            return kb

        pdata = doc.to_dict() or {}
        if not isinstance(pdata, dict):
            return kb

        # 1) Preferir display_prices (já vem “bonito”)
        dp = pdata.get("display_prices") or {}
        if isinstance(dp, dict):
            sp = str(dp.get("starter") or "").strip()
            spp = str(dp.get("starter_plus") or "").strip()
            if sp:
                pf["starter_price"] = sp
            if spp:
                pf["starter_plus_price"] = spp

        # 2) Fallback: price_cents (formata BRL)
        plans = pdata.get("plans") or {}
        if isinstance(plans, dict):
            st = plans.get("starter") or {}
            stp = plans.get("starter_plus") or {}
            if isinstance(st, dict):
                if not str(pf.get("starter_price") or "").strip():
                    pf["starter_price"] = _fmt_brl_from_cents(st.get("price_cents"))
                # storage em GB -> texto simples
                if not str(pf.get("starter_storage") or "").strip():
                    gb = st.get("storage_gb")
                    if gb is not None:
                        pf["starter_storage"] = f"{gb} Gigabytes de memória."
            if isinstance(stp, dict):
                if not str(pf.get("starter_plus_price") or "").strip():
                    pf["starter_plus_price"] = _fmt_brl_from_cents(stp.get("price_cents"))
                if not str(pf.get("starter_plus_storage") or "").strip():
                    gb = stp.get("storage_gb")
                    if gb is not None:
                        pf["starter_plus_storage"] = f"{gb} Gigabytes de memória."

        kb["pricing_facts"] = pf
        kb["pricing_source"] = ref_path
        return kb
    except Exception:
        return kb


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

    
    # Preço vem do doc canônico (platform_pricing/current) via pricing_ref
    kb = _merge_platform_pricing_into_kb(kb)

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


def _pt_int(n: int) -> str:
    """Inteiro pt-BR bem simples (0–999). Suficiente para preços/GB/dias."""
    n = int(n)
    units = ["zero","um","dois","três","quatro","cinco","seis","sete","oito","nove"]
    teens = ["dez","onze","doze","treze","quatorze","quinze","dezesseis","dezessete","dezoito","dezenove"]
    tens = ["","", "vinte","trinta","quarenta","cinquenta","sessenta","setenta","oitenta","noventa"]
    hundreds = ["","cento","duzentos","trezentos","quatrocentos","quinhentos","seiscentos","setecentos","oitocentos","novecentos"]

    if n < 0:
        return "menos " + _pt_int(-n)
    if n < 10:
        return units[n]
    if n < 20:
        return teens[n - 10]
    if n < 100:
        d, r = divmod(n, 10)
        return tens[d] if r == 0 else f"{tens[d]} e {units[r]}"
    if n == 100:
        return "cem"
    if n < 1000:
        c, r = divmod(n, 100)
        if r == 0:
            return hundreds[c]
        return f"{hundreds[c]} e {_pt_int(r)}"
    return str(n)


def _spoken_normalize_numbers(text: str) -> str:
    """Normaliza padroes comuns para fala (pre-TTS)."""
    t = (text or "").strip()
    if not t:
        return ""

    # moeda: R$ 89,00 / R$89 / R$ 1.299,00
    def _repl_money(m):
        raw = (m.group(1) or "").replace(".", "").replace(",", ".")
        try:
            val = float(raw)
        except Exception:
            return m.group(0)
        inteiro = int(round(val))
        return f"{_pt_int(inteiro)} reais"

    t = re.sub(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?)", _repl_money, t)

    # GB / Gigabytes
    def _repl_gb(m):
        try:
            n = int(m.group(1))
        except Exception:
            return m.group(0)
        return f"{_pt_int(n)} gigabytes"

    t = re.sub(r"\b(\d{1,3})\s*GB\b", _repl_gb, t, flags=re.IGNORECASE)
    t = re.sub(r"\b(\d{1,3})\s*gigabytes\b", _repl_gb, t, flags=re.IGNORECASE)

    # "/mês" e "/mes" -> "por mês"
    t = t.replace("/mês", " por mês").replace("/mes", " por mês")
    t = re.sub(r"\s+", " ", t).strip()
    return t


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



def _strip_md_for_tts(text: str) -> str:
    """Remove marcas simples de Markdown que atrapalham a fala (TTS)."""
    t = (text or "").strip()
    if not t:
        return ""
    t = t.replace("**", "").replace("__", "").replace("`", "")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _flatten_scene_arrows(text: str) -> str:
    """Converte '→' em frases normais (evita soar template no áudio)."""
    t = (text or '').strip()
    if not t:
        return t
    t = t.replace('→', '.')
    t = re.sub(r'\s*\.\s*', '. ', t).strip()
    t = re.sub(r'\s+', ' ', t).strip()
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






def _strip_trailing_question(txt: str) -> str:
    """Remove pergunta final (ou última frase interrogativa)."""
    t = (txt or "").strip()
    if not t or "?" not in t:
        return t
    last_q = t.rfind("?")
    cut = max(t.rfind(".", 0, last_q), t.rfind("!", 0, last_q), t.rfind("\n", 0, last_q))
    if cut >= 0:
        return t[: cut + 1].strip()
    return t[:last_q].strip()


def _strip_generic_question_ending(txt: str) -> str:
    """Corta finais genéricos de SAC que viram loop (sem criar texto novo)."""
    t = (txt or "").strip()
    if not t:
        return t
    # padrões comuns (variações com/sem "?" no STT)
    t = re.sub(
        r"(\s*[\.!…]\s*)?(quer saber mais[^?]*\??|posso te ajudar[^?]*\??|quer ajuda[^?]*\??|"
        r"quer que eu te explique[^?]*\??|você gostaria de saber[^?]*\??|quer saber como funciona[^?]*\??|o que acha[^?]*\??|vamos nessa[^?]*\??)\s*$",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()

    # Se sobrou final truncado (ex.: "O que"), limpa para não mandar áudio quebrado
    if re.search(r"\b(o que|que|e)\s*$", t, flags=re.IGNORECASE):
        t = re.sub(r"\b(o que|que|e)\s*$", "", t, flags=re.IGNORECASE).strip()
        t = t.rstrip(",;:-").strip()
        if t and not t.endswith((".", "!", "…")):
            t = t + "."
    return t


def _enforce_price_direct(kb: Dict[str, Any], segment: str = "") -> str:
    """Resposta padrão de preço (direta, sem 'depende', sem pergunta)."""
    pf = (kb or {}).get("pricing_facts") or {}
    if not isinstance(pf, dict):
        pf = {}
    sp = str(pf.get("starter_price") or "").strip()
    spp = str(pf.get("starter_plus_price") or "").strip()
    ss = str(pf.get("starter_storage") or "").strip()
    sps = str(pf.get("starter_plus_storage") or "").strip()
    if not sp or not spp:
        # Preço é “fonte única”: só fala valores quando existirem no pricing doc (pricing_ref).
        # Sem inventar número e sem burocracia: manda o caminho curto por escrito.
        return (
            "É assinatura mensal (paga). "
            "Os valores certinhos ficam no site: meirobo.com.br. "
            "Se quiser, eu te mando o link aqui e já te digo o próximo passo pra assinar."
        )

    def _clean_price(p: str) -> str:
        t = (p or "").strip()
        tl = t.lower()
        # remove marcadores de mensalidade já embutidos no Firestore
        tl = tl.replace("por mês", "").replace("por mes", "")
        tl = tl.replace("/mês", "").replace("/mes", "")
        # aplica a mesma remoção no original mantendo caixa
        t = re.sub(r"(?i)\bpor\s+m[eê]s\b\.?", "", t).strip()
        t = re.sub(r"(?i)/m[eê]s\b\.?", "", t).strip()
        t = re.sub(r"\s+", " ", t).strip()
        # tira pontuação final solta
        t = t.rstrip(" .,-;:")
        return t

    sp = _clean_price(sp)
    spp = _clean_price(spp)
    seg = (segment or "").strip()
    seg_line = f"Pra {seg}," if seg else ""
    mem_line = "A diferença é só a memória." + (f" (Starter {ss} | Starter+ {sps})" if ss or sps else "")
    return f"{seg_line} hoje é **apenas {sp}/mês** (Starter) ou **{spp}/mês** (Starter+). {mem_line}".strip()


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
    - Aceita 1–3 palavras como nome.
    - Suporta: "me chamo X", "me chamam de X", "pode me chamar de X", "meu nome é X", "aqui é X", "sou X"
    """
    t = (text or "").strip()
    if not t:
        return ""

    # remove pontuação final e emojis comuns (evita "Rosália." quebrar regex)
    t = re.sub(r"[\.\,\!\?\;:\)\]\}]+$", "", t).strip()
    t = re.sub(r"[\U00010000-\U0010ffff]", "", t).strip()  # remove emoji (faixa unicode)

    # normaliza espaços
    t = re.sub(r"\s+", " ", t).strip()

    # casos super comuns no Brasil (sem dicionário infinito, só moldes)
    patterns = [
        r"^(me chamo|me chamam de|pode me chamar de|podem me chamar de|meu nome é|meu nome e|aqui é|aqui e|eu sou|sou)\s+(?:o|a)?\s*([a-zA-ZÀ-ÿ'\- ]{2,40})$",
    ]

    for pat in patterns:
        m = re.match(pat, t, flags=re.IGNORECASE)
        if m:
            name = (m.group(2) or "").strip()
            name = re.sub(r"\s+", " ", name)

            # limita comprimento (evita pegar frase inteira)
            parts = [p for p in name.split(" ") if p]
            if len(parts) > 4:
                parts = parts[:3]
            name = " ".join(parts).strip()

            # limpa pontuação residual
            name = re.sub(r"[^\wÀ-ÿ\s'\-]", "", name).strip()
            return name

    # fallback: se for curtinho (1-3 palavras), assume que é nome
    parts = t.split()
    if 1 <= len(parts) <= 3 and len(t) <= 30:
        name = re.sub(r"[^\wÀ-ÿ\s'\-]", "", t).strip()
        return name

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
    NOVA REGRA: next_step é sugestão (memória fraca), NÃO é trilho.
    O código não conduz a conversa; apenas registra e protege.
    """
    ns = (next_step or "").strip().upper()
    if not ns:
        return

    # Guarda como sugestão (memória fraca) para a próxima resposta/prompt.
    st["suggested_next_step"] = ns

    # EXIT é a única coisa que o código pode “promover” diretamente,
    # porque é proteção de custo e de loop infinito.
    if ns == "EXIT":
        st["stage"] = "EXIT"

    # Em OPERATIONAL, não “puxa” o trilho de coleta.
    # Só registra a sugestão e segue.
    return


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
        nm = re.sub(
            r"^(me chamo|me chamam de|o pessoal me chama de|pessoal me chama de|pode me chamar de|podem me chamar de|meu nome é|meu nome e|aqui é|aqui e|eu sou|sou)\s+(?:o|a)?\s*",
            "",
            nm,
            flags=re.IGNORECASE,
        ).strip()
        nm = re.sub(r"[^\wÀ-ÿ\s'\-]", "", nm).strip()
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
        "INTENTS permitidos: PRICE | PLANS | DIFF | ACTIVATE | WHAT_IS | OPERATIONAL | SLA | PROCESS | OTHER.\n"
        "- OPERATIONAL: pergunta prática de como funciona no dia a dia (ex.: agendar, organizar pedidos).\n"
        "- SLA: pergunta sobre demora/prazo para começar (ex.: \"demora?\", \"em quantos dias?\").\n"
        "- PROCESS: pergunta sobre etapas do processo (ativação/configuração), sem focar em preço.\n\n"
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
        if intent not in ("PRICE", "PLANS", "DIFF", "ACTIVATE", "WHAT_IS", "OPERATIONAL", "SLA", "PROCESS", "OTHER"):
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
# IA NO COMANDO: PLANO (JSON)
# - A IA decide intenção + modo de pergunta/fechamento + quais KBs precisa
# - O código só executa, busca KB solicitada e loga
# =========================

def _kb_need_allowlist(kb: Dict[str, Any]) -> list:
    allow = (kb or {}).get("kb_need_allowed")
    if isinstance(allow, list):
        out = []
        for x in allow:
            s = str(x or "").strip()
            if s:
                out.append(s)
        return out
    return []


def _kb_catalog(kb: Dict[str, Any]) -> Dict[str, str]:
    cat = (kb or {}).get("kb_catalog")
    if not isinstance(cat, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in cat.items():
        ks = str(k or "").strip()
        vs = str(v or "").strip()
        if ks and vs:
            out[ks] = vs
    return out


def _kb_pick(kb: Dict[str, Any], kb_need: list, *, segment: str = "") -> Dict[str, Any]:
    """Extrai somente os blocos pedidos (para prompt enxuto e log)."""
    out: Dict[str, Any] = {}
    if not isinstance(kb_need, list):
        return out

    seg = (segment or "").strip().lower()

    for key in kb_need:
        k = str(key or "").strip()
        if not k:
            continue
        if k not in kb:
            continue
        # segmentado: manda só o que importa
        if k in ("segment_pills", "segments") and seg and isinstance(kb.get(k), dict):
            blk = kb.get(k) or {}
            if isinstance(blk, dict) and seg in blk:
                out[k] = {seg: blk.get(seg)}
            else:
                out[k] = blk
            continue
        out[k] = kb.get(k)
    return out


def _resolve_scene_text(kb: Dict[str, Any], scene_key: str, *, segment: str = "") -> str:
    """Resolve uma 'scene_key' para um texto curto (sem inventar)."""
    kb = kb or {}
    sk = (scene_key or "").strip()
    seg = (segment or "").strip().lower()
    if not sk:
        return ""

    # atalhos canônicos
    if sk == "segment_pills" and seg:
        try:
            ms = (((kb.get("segment_pills") or {}).get(seg) or {}).get("micro_scene") or "")
            return str(ms).strip()
        except Exception:
            return ""

    if sk == "segments" and seg:
        try:
            ms = (((kb.get("segments") or {}).get(seg) or {}).get("micro_scene") or "")
            return str(ms).strip()
        except Exception:
            return ""

    # value_in_action_blocks.<key>
    if sk.startswith("value_in_action_blocks."):
        parts = sk.split(".", 1)
        if len(parts) == 2:
            key = parts[1].strip()
            blk = (kb.get("value_in_action_blocks") or {})
            if isinstance(blk, dict):
                obj = blk.get(key)
                if isinstance(obj, dict):
                    scene = obj.get("scene")
                    if isinstance(scene, list):
                        # junta em uma linha curta
                        t = " → ".join([str(x).strip() for x in scene if str(x).strip()])
                        return t.strip()[:420]
    # memory_positioning.core
    if sk.startswith("memory_positioning"):
        try:
            mp = kb.get("memory_positioning") or {}
            if isinstance(mp, dict):
                core = mp.get("core")
                if isinstance(core, list) and core:
                    # usa 1 linha
                    return str(core[0]).strip()[:260]
        except Exception:
            return ""

    return ""


def sales_ai_plan(
    *,
    user_text: str,
    stage: str,
    name: str,
    segment: str,
    goal: str,
    nlu_intent: str,
    turns: int,
    last_bot_excerpt: str,
) -> Dict[str, Any]:
    """Retorna um plano estruturado (JSON) para a resposta.

    Schema esperado:
      {
        intent: PRICE|ACTIVATE|OPERATIONAL|PROCESS|SLA|OTHER|SMALLTALK|OBJECTION,
        tone: confiante|consultivo|leve|bem_humano,
        ask_mode: none|one_short|ab_choice,
        close_mode: none|soft|hard,
        next_step: ''|ASK_NAME|ASK_SEGMENT|VALUE|PRICE|SEND_LINK|CTA|EXIT,
        scene_key: string (opcional),
        kb_need: [..] (somente itens de kb_need_allowed),
        reply: texto curto,
        evidence: 1 linha (apenas log)
      }

    Se falhar, retorna {}.
    """
    kb = _get_sales_kb()
    allow = _kb_need_allowlist(kb)
    cat = _kb_catalog(kb)

    user_text = (user_text or "").strip()
    if not user_text:
        return {}


    # prompt enxuto, sem despejar KB inteira
    system = (
        "Você é o PLANEJADOR do MEI Robô (Vendas) no WhatsApp (pt-BR).\n"
        "Você devolve SOMENTE JSON válido (sem texto extra).\n\n"
        "Objetivo: decidir a melhor próxima ação de forma humana e vendedora do bem, sem script.\n\n"
        "Regras de saída:\n"
        "- intent: PRICE|ACTIVATE|OPERATIONAL|PROCESS|SLA|OTHER|SMALLTALK|OBJECTION\n"
        "- tone: confiante|consultivo|leve|bem_humano\n"
        "- ask_mode: none|one_short|ab_choice\n"
        "- close_mode: none|soft|hard\n"
        "- next_step: ''|ASK_NAME|ASK_SEGMENT|VALUE|PRICE|SEND_LINK|CTA|EXIT\n"
        "- scene_key: opcional (ex.: 'segment_pills', 'segments', 'value_in_action_blocks.services_quote_scene', 'memory_positioning')\n"
        "- kb_need: lista objetiva do que buscar (somente permitido em kb_need_allowed)\n"
        "- reply: texto curto (2–5 linhas) pronto pra enviar\n"
        "- evidence: 1 linha explicando a escolha (somente para log)\n\n"
        "Regras de comportamento (produto):\n"
        "- Se o lead perguntar PREÇO: responda direto com valores Starter/Starter+ e diga que a diferença é só a memória.\n"
        "- Se for DECISÃO/ASSINAR/LINK: close_mode='hard' e ask_mode='none' (zero pergunta no final).\n"
        "- Se pedirem LINK/SITE/ONDE ASSINA: next_step='SEND_LINK' e inclua o site na reply.\n"
        "- Small talk (clima, piada, 'é bot?'): responda humano 1 frase e faça ponte suave pro valor (sem puxar formulário).\n"
        "- Não invente números; use somente pricing_facts/process_facts quando precisar de fatos.\n"
    )

    # PATCH7: quando SALES_COMPOSER_MODE=v1, o Planner NÃO gera o texto final (sem campo reply).
    if _composer_mode() == "v1":
        try:
            system = system.replace(
                "- reply: texto curto (2–5 linhas) pronto pra enviar\n",
                "- NÃO inclua campo reply (o Composer gera o texto final)\n"
            )
            system = system.replace(
                "- Se pedirem LINK/SITE/ONDE ASSINA: next_step='SEND_LINK' e inclua o site na reply.\n",
                "- Se pedirem LINK/SITE/ONDE ASSINA: next_step='SEND_LINK'. (O texto final incluirá o site.)\n"
            )
        except Exception:
            pass


    user = (
        f"STAGE={stage}\n"
        f"TURNS={int(turns or 0)}\n"
        f"NOME={name or '—'}\n"
        f"RAMO={segment or '—'}\n"
        f"OBJETIVO={goal or '—'}\n"
        f"NLU_INTENT={nlu_intent or '—'}\n"
        f"ULTIMA_RESPOSTA_NAO_REPETIR={last_bot_excerpt or '—'}\n\n"
        f"kb_need_allowed={allow}\n"
        f"kb_catalog={cat}\n\n"
        f"MENSAGEM={user_text}\n"
    )

    # chama o Planner (IA) e devolve dict validado (best-effort)
    try:
        raw = (_openai_chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=OPENAI_SALES_NLU_MODEL,
            max_tokens=220,
            temperature=0.2,
            response_format={"type": "json_object"},
        ) or "").strip()
        if not raw:
            return {}
        plan = json.loads(raw)
        if not isinstance(plan, dict):
            return {}

        # normaliza campos principais
        plan_intent = str(plan.get("intent") or "").strip().upper()
        if plan_intent and plan_intent not in ("PRICE","ACTIVATE","OPERATIONAL","PROCESS","SLA","OTHER","SMALLTALK","OBJECTION"):
            plan_intent = "OTHER"
        if plan_intent:
            plan["intent"] = plan_intent

        ns = str(plan.get("next_step") or "").strip().upper()
        if ns and ns not in ("ASK_NAME","ASK_SEGMENT","VALUE","PRICE","SEND_LINK","CTA","EXIT"):
            ns = ""
        plan["next_step"] = ns

        ask_mode = str(plan.get("ask_mode") or "").strip().lower()
        if ask_mode and ask_mode not in ("none","one_short","ab_choice"):
            ask_mode = "one_short"
        if ask_mode:
            plan["ask_mode"] = ask_mode

        close_mode = str(plan.get("close_mode") or "").strip().lower()
        if close_mode and close_mode not in ("none","soft","hard"):
            close_mode = "none"
        if close_mode:
            plan["close_mode"] = close_mode

        # kb_need deve ser lista
        kb_need = plan.get("kb_need")
        if kb_need is None:
            plan["kb_need"] = []
        elif not isinstance(kb_need, list):
            plan["kb_need"] = []

        return plan
    except Exception:
        return {}

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
    process_facts = (kb.get("process_facts") or {}) if isinstance(kb, dict) else {}
    # Fallback seguro: verdade do produto (evita promessas irreais)
    if not process_facts:
        process_facts = {
            "no_free_trial": True,
            "billing_model": "assinatura mensal (paga)",
            "sla_setup": "até 7 dias úteis para número virtual + configuração concluída",
            "can_prepare_now": "você já cria a conta e deixa tudo pronto na plataforma (serviços, rotina, agenda)."
        }

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
        "IMPORTANTE:\n"
        "- Não agradeça automaticamente (tipo 'obrigado por chamar'). Só agradeça se o lead agradecer primeiro.\n\n"
        "SOBERANIA (importante): você decide autonomamente, a cada resposta:\n"
        "- se usa ou não o nome do lead\n"
        "- se demonstra empatia\n"
        "- se aprofunda um pouco mais\n"
        "- se fecha ou apenas orienta\n"
        "- se a mensagem é teste/ironia/resistência consciente: acompanhe como humano e siga, sem puxar pra formulário\n"
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
        "- EXCEÇÃO: se intent_hint for 'CTA' (decisão), NÃO faça pergunta. Feche com próximo passo e despedida.\n\n"
        "CONTEÚDO:\n"
        "- Priorize sales_pills, value_props_top3, e micro-scenes por segmento.\n"
        "- Use micro-exemplo operacional (entrada → organização → resumo pro dono) quando ajudar.\n"
        "- Nunca invente números.\n"
        "- Só cite preço quando fizer sentido e apenas usando pricing_facts.\n\n"
        "PREÇO:\n"
        "- Se perguntarem preço direto: responda o valor (Starter/Starter+) e diga que a diferença é só a memória.\n"
        "- Não comece com 'depende'.\n"
        "- Sem pergunta no final (depois do preço, dê um próximo passo curto).\n\n"
        "REALIDADE DO PRODUTO (obrigatório):\n- Não diga que o robô 'agenda automaticamente'. Diga que ele organiza, confirma e registra; o profissional acompanha e decide.\n- Em fechamento (intent_hint='CTA'), assine a última linha como: — Ricardo, do MEI Robô\n\n"
        "- Não existe teste grátis. Não prometa “testar hoje”.\n"
        "- Assinatura é paga.\n"
        "- SLA: até 7 dias úteis para número virtual + configuração concluída.\n"
        "- Se perguntarem de demora/processo: seja direto, alinhe expectativa e dê próximo passo.\n\n"
        "FECHAMENTO:\n"
        "- Se intent_hint='CTA': feche sem pergunta (apenas benefício + próximo passo + tchau).\n\n"
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
        "REGRA OPERACIONAL IMPORTANTE:\n"
        "- Se intent_hint for OPERATIONAL_FLOW, responda SEMPRE como um micro-fluxo fechado:\n"
        "  entrada do cliente → confirmação → aviso ao MEI → registro na agenda → lembrete opcional.\n"
        "- Não explique conceitos soltos.\n"
        "- Não repita o que já foi dito antes.\n"
        "- Finalize com no máximo 1 pergunta de direcionamento (ex.: agenda ou pedidos?).\n\n"
        f"mensagem: {user_text}\n\n"
        f"continuidade: {continuity}\n\n"
        f"onboarding_hint (se existir): {json.dumps(onboarding_hint, ensure_ascii=False)}\n"
        f"fatos_do_produto (não negociar; não inventar): {json.dumps(process_facts, ensure_ascii=False, separators=(',',':'))}\n"
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


    # 1) Evita “metralhadora” de perguntas genéricas no final
    reply_text = _strip_generic_question_ending(reply_text)

    # 2) PRICE/PLANS/DIFF: preço SEMPRE vem do Firestore (nunca inventar)
    ih = str(intent_hint or '').strip().upper()
    if ih in ('PRICE', 'PLANS', 'DIFF'):
        reply_text = _enforce_price_direct(kb, segment=segment)
        reply_text = _strip_trailing_question(reply_text)

    # 3) CTA: nunca termina em pergunta e assina como Ricardo, do MEI Robô
    if ih == "CTA":
        reply_text = _strip_trailing_question(reply_text)
        if "ricardo" not in _norm(reply_text):
            reply_text = (reply_text.rstrip() + "\n\n— Ricardo, do MEI Robô").strip()


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

    reply_text = _flatten_scene_arrows(reply_text)


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
        nm_ai = re.sub(
            r"^(me chamo|me chamam de|o pessoal me chama de|pessoal me chama de|pode me chamar de|podem me chamar de|meu nome é|meu nome e|aqui é|aqui e|eu sou|sou)\s+(?:o|a)?\s*",
            "",
            nm_ai,
            flags=re.IGNORECASE,
        ).strip()
        nm_ai = re.sub(r"[^\wÀ-ÿ\s'\-]", "", nm_ai).strip()
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
        # só pode acontecer no início absoluto — mas ainda assim, IA decide como responder.
        txt = (_ai_sales_answer(
            name=name,
            segment=segment,
            goal=goal,
            user_text=text_in,
            intent_hint="OFFTOPIC",
            state=st,
        ) or "").strip()
        if not txt:
            return OPENING_ASK_NAME
        txt = _apply_anti_loop(st, txt, name=name, segment=segment, goal=goal, user_text=text_in)
        txt = _limit_questions(txt, max_questions=1)
        return _clip(txt, SALES_MAX_CHARS_REPLY)

    if stage == "EXIT":
        st["__sales_close"] = True
        return "Beleza. Pra ver tudo com calma e seguir com a ativação, é pelo site: www.meirobo.com.br"

    # Human Gate: ruído humano no início (piada, "é bot?", clima, futebol, teste)
    # Só roda 1x por lead e só antes de coletar nome/ramo.
    if not st.get("__human_gate_done"):
        if (turns <= 2) and (stage in ("ASK_NAME", "ASK_SEGMENT")) and (not has_name) and (not has_segment):
            if _detect_human_noise(text_in):
                st["__human_gate_done"] = True
                # IA soberana: ela decide se pergunta nome, se brinca, se avança.
                txt = (_ai_sales_answer(
                    name=name,
                    segment=segment,
                    goal=goal,
                    user_text=text_in,
                    intent_hint="HUMAN_NOISE",
                    state=st,
                ) or "").strip()
                if not txt:
                    return _human_gate_reply()
                txt = _apply_anti_loop(st, txt, name=name, segment=segment, goal=goal, user_text=text_in)
                txt = _limit_questions(txt, max_questions=1)
                return _clip(txt, SALES_MAX_CHARS_REPLY)

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



    # =========================
    # IA NO COMANDO (PLANO)
    # - Se o plano vier, ele manda.
    # - Se falhar, cai no fluxo legado abaixo.
    # =========================

    try:
        plan = sales_ai_plan(
            user_text=text_in,
            stage=stage,
            name=name,
            segment=segment,
            goal=goal,
            nlu_intent=str(nlu.get("intent") or "").strip().upper(),
            turns=turns,
            last_bot_excerpt=str(st.get("last_bot_reply_excerpt") or "").strip(),
        )
    except Exception:
        plan = {}

    if isinstance(plan, dict) and plan.get("intent"):
        # Segurança: garante fatos quando a intenção exigir
        kb_need = list(plan.get("kb_need") or [])
        intent_p = str(plan.get("intent") or "OTHER").strip().upper()
        if intent_p == "PRICE" and "pricing_facts" not in kb_need:
            kb_need.append("pricing_facts")
        if intent_p in ("SLA", "PROCESS") and "process_facts" not in kb_need:
            kb_need.append("process_facts")

        # Cena padrão (se fizer sentido) — sem obrigar
        scene_key = str(plan.get("scene_key") or "").strip()
        if not scene_key and (intent_p in ("OPERATIONAL", "OTHER", "OBJECTION") or segment):
            scene_key = "segment_pills" if segment else ""

        kb = _get_sales_kb()
        kb_used = [str(x).strip() for x in kb_need if str(x or "").strip()]
        kb_snip = _kb_pick(kb, kb_used, segment=segment)
        scene_text = _resolve_scene_text(kb, scene_key, segment=segment)
        reply_txt = ""

        if _composer_mode() == "v1":
            reply_txt = (_compose_from_plan(
                plan=plan,
                name=name,
                segment=segment,
                goal=goal,
                user_text=text_in,
                state=st,
                scene_text=scene_text,
            ) or "").strip()
        else:
            reply_txt = str(plan.get("reply") or "").strip()
            if not reply_txt:
                # fallback: usa a IA de resposta tradicional
                reply_txt = (_ai_sales_answer(
                    name=name,
                    segment=segment,
                    goal=goal,
                    user_text=text_in,
                    intent_hint=("CTA" if intent_p == "ACTIVATE" else intent_p),
                    state=st,
                ) or "").strip() or _fallback_min_reply(name)

            # Se vier cena e a resposta não tiver micro-fluxo, injeta 1 linha (sem inventar)
            if scene_text and ("→" not in reply_txt):
                reply_txt = (scene_text + "\n" + reply_txt).strip()

        ask_mode = str(plan.get("ask_mode") or "one_short").strip().lower()
        close_mode = str(plan.get("close_mode") or "none").strip().lower()

        # Hard close / sem pergunta
        if close_mode == "hard" or ask_mode == "none" or intent_p == "ACTIVATE":
            reply_txt = _strip_trailing_question(reply_txt)

        # Sempre: mata finais genéricos de SAC
        reply_txt = _strip_generic_question_ending(reply_txt)

        # Anti-loop + a11y social
        reply_txt = _apply_anti_loop(st, reply_txt, name=name, segment=segment, goal=goal, user_text=text_in)
        if name:
            reply_txt = _strip_repeated_greeting(reply_txt, name=name, turns=turns)

        # Perguntas: respeita o plano
        if ask_mode == "none" or close_mode == "hard":
            reply_txt = _limit_questions(reply_txt, max_questions=0)
        else:
            reply_txt = _limit_questions(reply_txt, max_questions=1)

        # Observabilidade: guarda no state (worker pode logar o payload de retorno)
        try:
            st["ai_plan"] = plan.get("raw") or plan
            st["kb_used"] = kb_used
            st["kb_snippet"] = kb_snip
            st["scene_key"] = scene_key
            st["ask_mode"] = ask_mode
            st["close_mode"] = close_mode
            st["plan_intent"] = intent_p
            st["plan_next_step"] = str(plan.get("next_step") or "").strip().upper()
            st["plan_evidence"] = str(plan.get("evidence") or "").strip()
        except Exception:
            pass

        return _clip(reply_txt, SALES_MAX_CHARS_REPLY)
    # OPERATIONAL tem prioridade absoluta: responde antes de coletar dados (nome/segmento)
    intent = (nlu.get("intent") or _intent_cheap(text_in) or "OTHER").strip().upper()
    st["last_intent"] = intent

    if intent == "OPERATIONAL":
        st["force_operational_reply"] = True

        # Flag leve para evitar repetir explicação operacional
        if st.get("saw_operational_flow"):
            st["operational_repeat"] = True
        else:
            st["saw_operational_flow"] = True

        # Hint correto para fluxo fechado
        if st.get("operational_repeat"):
            hint = "OPERATIONAL_FOLLOWUP"
        else:
            hint = "OPERATIONAL_FLOW"

        txt = (_ai_sales_answer(
            name=name, segment=segment, goal=goal, user_text=text_in, intent_hint=hint, state=st
        ) or "").strip()
        if not txt:
            txt = _fallback_min_reply(name)

        # OPERATIONAL não termina com “quer saber mais?”
        txt = re.sub(
            r"\b(quer saber mais\?|posso explicar melhor\?)\b",
            "",
            txt,
            flags=re.IGNORECASE
        ).strip()

        txt = _apply_anti_loop(st, txt, name=name, segment=segment, goal=goal, user_text=text_in)
        if name:
            txt = _strip_repeated_greeting(txt, name=name, turns=turns)
        txt = _limit_questions(txt, max_questions=1)
        return _clip(txt, SALES_MAX_CHARS_REPLY)


    # Intenções diretas NÃO dependem de nome/segmento. Responde agora.
    # Isso elimina “parece formulário” e evita cair em DISCOVERY quando o lead já foi direto.
    if intent in ("PRICE", "PLANS", "DIFF", "WHAT_IS", "SLA", "PROCESS"):
        txt = (_ai_sales_answer(
            name=name, segment=segment, goal=goal, user_text=text_in, intent_hint=intent, state=st
        ) or "").strip()
        if not txt:
            txt = _fallback_min_reply(name)
        txt = _apply_anti_loop(st, txt, name=name, segment=segment, goal=goal, user_text=text_in)
        txt = _strip_repeated_greeting(txt, name=name, turns=turns)
        txt = _limit_questions(txt, max_questions=1)
        return _clip(txt, SALES_MAX_CHARS_REPLY)

    if intent == "ACTIVATE":
        txt = (_ai_sales_answer(
            name=name, segment=segment, goal=goal, user_text=text_in, intent_hint="CTA", state=st
        ) or "").strip()
        if not txt:
            txt = f"Fechado 🙂 Pra ativar, é pelo site: {SITE_URL}. A ativação completa leva até 7 dias úteis."
        txt = _apply_anti_loop(st, txt, name=name, segment=segment, goal=goal, user_text=text_in)
        txt = _strip_repeated_greeting(txt, name=name, turns=turns)
        txt = _limit_questions(txt, max_questions=1)
        return _clip(txt, SALES_MAX_CHARS_REPLY)

    # Regra (memória fraca): se a intenção é vaga (OTHER) e faltam dados, aí sim DISCOVERY.
    if (not has_name) or (not has_segment):
        st["nudges"] = nudges + 1
        txt = (_ai_sales_answer(
            name=name,
            segment=segment,
            goal=goal,
            user_text=text_in,
            intent_hint="DISCOVERY",
            state=st,
        ) or "").strip()
        if not txt:
            txt = _fallback_min_reply(name)
        txt = _apply_anti_loop(st, txt, name=name, segment=segment, goal=goal, user_text=text_in)
        txt = _limit_questions(txt, max_questions=1)
        return _clip(txt, SALES_MAX_CHARS_REPLY)

    # Restante (intenção vaga/OTHER) — aqui a conversa já tem o mínimo (nome/ramo).
    # Mantém IA no comando, mas sem reintroduzir trilhos/ifs infinitos.

    # Lead frio: pergunta curta (sem despejar pitch)
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

    # Pitch (cacheado) + 1 pergunta de avanço
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
    # Trace simples (auditoria e correlação de logs)
    try:
        trace_id = hashlib.sha1(f"{wa_key}:{int(time.time()*1000)}".encode("utf-8")).hexdigest()[:12]
    except Exception:
        trace_id = ""

    policies_applied = []
    # wa_key disponível para observabilidade (não afeta fluxo)
    if isinstance(st, dict):
        st["wa_key"] = wa_key
    reply = _reply_from_state(text_in, st)

    # Intenção final preferencial: IA (plan_intent) -> estado (last_intent) -> cheap
    try:
        intent_final = str(st.get("plan_intent") or st.get("last_intent") or "").strip().upper()
    except Exception:
        intent_final = ""
    if not intent_final:
        try:
            intent_final = str(_intent_cheap(text_in) or "").strip().upper()
        except Exception:
            intent_final = ""

    # Next step final (Planner soberano): usado para policy (link/close), sem heurística esperta.
    try:
        next_step_final = str(st.get("plan_next_step") or "").strip().upper()
    except Exception:
        next_step_final = ""

    # Purificação: quando existe plano da IA (intent/next_step), overrides estratégicos não podem competir.
    has_plan = bool((str(st.get("plan_intent") or "").strip()) or (next_step_final or "").strip())


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
    reply_final = _flatten_scene_arrows(reply_final)
    # Segurança: nunca falar "eu me chamo ..." se nome estiver vazio
    if not lead_name:
        reply_final = re.sub(r"\b(eu me chamo|me chamo)\b[^,]*,\s*", "", reply_final, flags=re.IGNORECASE).strip()
    spoken_final = _sanitize_spoken(reply_final)
    # Camada de fala (padrão): números e unidades por extenso
    spoken_final = _strip_md_for_tts(spoken_final)
    spoken_final = _spoken_normalize_numbers(spoken_final)

    def _has_url(s: str) -> bool:
        t = (s or "").lower()
        return ("http://" in t) or ("https://" in t) or ("www." in t) or ("meirobo.com.br" in t) or ("[site" in t)

    prefers_text = False

    def _wants_link(s: str) -> bool:
        t = _norm(s)
        return (
            ("link" in t)
            or ("site" in t)
            or ("endereço" in t)
            or ("endereco" in t)
            or ("onde entro" in t)
            or ("onde eu entro" in t)
            or ("onde eu me dirijo" in t)
            or ("me dirijo" in t)
            or ("manda o link" in t)
            or ("qual o link" in t)
            or ("qual é o link" in t)
        )

    # Policy (novo trilho): se o Planner mandou SEND_LINK, o código só GARANTE que o link aparece.
    # Isso não é estratégia: é execução do plano (sem competir com a IA).
    if next_step_final == "SEND_LINK":
        if not _has_url(reply_final):
            reply_final = (reply_final.rstrip() + f"\n\n{SITE_URL}").strip()
        prefers_text = True
        spoken_final = "Te mandei o link por escrito aqui na conversa."
        policies_applied.append("policy:plan_send_link")

    # Legado controlado (compat): se não há plano e overrides estão ligados, mantém o comportamento antigo.
    if (next_step_final != "SEND_LINK") and (not has_plan) and _strategic_overrides_enabled() and _wants_link(text_in):
        reply_final = (
            f"{SITE_URL} — ali você cria a conta e já deixa serviços/agenda prontos. "
            "A ativação completa leva até 7 dias úteis."
        )
        prefers_text = True
        spoken_final = "Te mandei o link por escrito aqui na conversa."
        policies_applied.append("override:link")

    if _has_url(reply_final):
        prefers_text = True
        # áudio curto e humano; link vai por escrito
        spoken_final = "Te mandei o link por escrito aqui na conversa."

    # Regra de fechamento (POLICY): não termina em pergunta quando a decisão já está clara.
    # Purificação: quando SALES_STRATEGIC_OVERRIDES=0, evitamos heurísticas 'espertas' aqui.

    hard_close = False

    # 1) Sinais fortes vindos do trilho principal (IA/estado)
    try:
        if str(intent_final or '').strip().upper() == 'ACTIVATE':
            hard_close = True
    except Exception:
        pass

    try:
        if str((st.get('last_intent') or '')).strip().upper() == 'ACTIVATE':
            hard_close = True
    except Exception:
        pass
    try:
        ns = str(next_step_final or '').strip().upper()
        if ns == 'CTA':
            hard_close = True
        if ns == 'SEND_LINK':
            hard_close = True
    except Exception:
        pass

    # 2) Compat (somente quando overrides estratégicos estão ligados):
    #    heurísticas antigas de decisão (mantém comportamento atual por padrão).
    if (not hard_close) and _strategic_overrides_enabled() and (not has_plan):
        try:
            hard_close = (_intent_cheap(text_in) == 'ACTIVATE')
        except Exception:
            hard_close = False
        if not hard_close:
            try:
                tdec = _norm(text_in)
            except Exception:
                tdec = (text_in or '').lower()
            if ('vou assinar' in tdec) or ('quero assinar' in tdec) or ('vou querer assinar' in tdec):
                hard_close = True
            if ('procedimento' in tdec) and (('assina' in tdec) or ('assin' in tdec) or ('ativ' in tdec)):
                hard_close = True

    if hard_close or (_strategic_overrides_enabled() and (not has_plan) and _wants_link(text_in)):
        reply_final = _strip_trailing_question(reply_final)
        spoken_final = _strip_trailing_question(spoken_final)
        policies_applied.append('hard_close:no_question')

    # Sempre: remove finais genéricos de "SAC" para evitar loop
    reply_final = _strip_generic_question_ending(reply_final)
    spoken_final = _strip_generic_question_ending(spoken_final)

    # =========================
    # BLINDAGEM FINAL (produto)
    # =========================

    # PREÇO (política única): se intent_final é PRICE/PLANS/DIFF, a saída FINAL sempre vem do Firestore.
    is_price = intent_final in ("PRICE", "PLANS", "DIFF")
    pricing_used = False
    pricing_source = ""
    if is_price:
        reply_final = _enforce_price_direct(kb, segment="")
        reply_final = _strip_trailing_question(reply_final)
        prefers_text = False
        spoken_final = _sanitize_spoken(reply_final)
        spoken_final = _strip_md_for_tts(spoken_final)
        spoken_final = _spoken_normalize_numbers(spoken_final)
        pricing_used = True
        pricing_source = str((kb or {}).get("pricing_source") or "platform_pricing/current")
        policies_applied.append("price:firestore_only")

    # Política dura (opcional): fora de PRICE/PLANS/DIFF, não pode sair "R$...".
    if (not is_price) and _strict_no_price_outside_intent() and ("r$" in (reply_final or "").lower()):
        reply_final = _strip_price_mentions(reply_final)
        spoken_final = _sanitize_spoken(reply_final)
        spoken_final = _strip_md_for_tts(spoken_final)
        spoken_final = _spoken_normalize_numbers(spoken_final)
        policies_applied.append("price:strip_outside_intent")

    # CTA/ASSINAR: se a IA mencionar preço (R$) fora do modo PRICE,
    # força os valores do Firestore para não inventar 99/149.
    try:
        last_int = str(st.get("last_intent") or "").strip().upper()
    except Exception:
        last_int = ""

    # Normaliza texto uma vez (evita UnboundLocalError em 'tnorm')
    try:
        tnorm = _norm(text_in)
    except Exception:
        tnorm = (text_in or "").lower()

    looks_like_pricing_text = ("r$" in (reply_final or "").lower()) and (("starter" in (reply_final or "").lower()) or ("plano" in (reply_final or "").lower()))
    is_activate_flow = (last_int in ("ACTIVATE",)) or ("assina" in tnorm) or ("assin" in tnorm) or ("procedimento" in tnorm)

    wants_procedure = (
        ("procedimento" in tnorm)
        or ("como faço" in tnorm)
        or ("como eu faço" in tnorm)
        or ("a partir de agora" in tnorm)
        or ("pra assinar" in tnorm)
        or ("para assinar" in tnorm)
        or ("vou assinar" in tnorm)
        or ("quero assinar" in tnorm)
        or ("vou querer assinar" in tnorm)
    )

    if _strategic_overrides_enabled() and (not has_plan) and (not is_price) and is_activate_flow and looks_like_pricing_text and (not wants_procedure):
        reply_final = _enforce_price_direct(kb, segment="")
        reply_final = _strip_trailing_question(reply_final)
        spoken_final = _sanitize_spoken(reply_final)
        spoken_final = _strip_md_for_tts(spoken_final)
        spoken_final = _spoken_normalize_numbers(spoken_final)
        policies_applied.append("override:activate_flow_price")

    # Legado controlado: procedimento/link só entra se NÃO houver plano de SEND_LINK
    if (next_step_final != "SEND_LINK") and (not has_plan) and _strategic_overrides_enabled() and wants_procedure:
        reply_final = (
            f"{SITE_URL} — ali você assina e já deixa serviços/agenda prontos. "
            "A ativação completa leva até 7 dias úteis."
        )
        prefers_text = True
        spoken_final = "Te mandei o link por escrito aqui na conversa."
        policies_applied.append("override:procedure_link")

    # AGENDAMENTO: se o lead perguntou sobre agenda/agendamento e a resposta saiu genérica,
    # força o "como funciona na prática" do Firestore (sem prometer automático).

    is_agenda_question = ("agend" in tnorm) or ("agenda" in tnorm) or ("marcar" in tnorm) or ("consulta" in tnorm) or ("horário" in tnorm) or ("horario" in tnorm)
    # Legado controlado: override de agenda NÃO pode competir com plano da IA.
    # Se já existe plan_intent/plan_next_step, deixa o trilho principal mandar.
    # has_plan já calculado acima (plano da IA)
    if (not has_plan) and _strategic_overrides_enabled() and is_agenda_question and (not is_price):
        try:
            oc = kb.get("operational_capabilities") or {}
            sched = str(oc.get("scheduling_practice") or "").strip()
        except Exception:
            sched = ""

        # Se a resposta não mencionou agenda direito ou veio puxando micro-cena irrelevante, substitui
        if sched:
            out_norm = _norm(reply_final)
            looks_like_scene = reply_final.strip().lower().startswith(("paciente chega", "cliente manda", "cliente pergunta"))
            lacks_agenda = ("agenda" not in out_norm) and ("agend" not in out_norm)

            if looks_like_scene or lacks_agenda:
                reply_final = sched
                reply_final = _strip_trailing_question(reply_final)
                spoken_final = _sanitize_spoken(reply_final)

                spoken_final = _strip_md_for_tts(spoken_final)

                spoken_final = _spoken_normalize_numbers(spoken_final)
                policies_applied.append("override:agenda_practice")

    # aplica também aqui (garante consistência)
    spoken_final = _spoken_normalize_numbers(spoken_final)

    return {
        "replyText": reply_final,
        "nameUse": (st.get("last_name_use") or ""),
        "prefersText": prefers_text,

        # 🔒 Fonte de verdade para áudio (worker deve preferir estes campos)
        "ttsText": spoken_final,
        "spokenText": spoken_final,

        # Contrato de política/auditoria (incremental)
        "intentFinal": intent_final,
        "pricingUsed": pricing_used,
        "pricingSource": pricing_source,
        "policiesApplied": policies_applied,
        "traceId": trace_id,

        # Observabilidade (IA no comando): prova do plano e do que foi usado
        "aiPlan": (st.get("ai_plan") or {}),
        "kbUsed": (st.get("kb_used") or []),
        "sceneKey": (st.get("scene_key") or ""),
        "askMode": (st.get("ask_mode") or ""),
        "closeMode": (st.get("close_mode") or ""),
        "planIntent": (st.get("plan_intent") or ""),
        "planNextStep": (st.get("plan_next_step") or ""),
        "planEvidence": (st.get("plan_evidence") or ""),
        "kbSnippet": json.dumps((st.get("kb_snippet") or {}), ensure_ascii=False),
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
