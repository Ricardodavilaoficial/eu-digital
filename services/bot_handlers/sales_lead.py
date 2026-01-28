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




def _decider_mode() -> str:
    """
    Decider (IA) para "decisão cognitiva" antes do resto.
    - off: não roda (default)
    - v1: roda com cache e guardrails
    Env: SALES_DECIDER_MODE=off|v1
    """
    try:
        m = str(os.getenv("SALES_DECIDER_MODE", "v1") or "v1").strip().lower()
    except Exception:
        m = "v1"
    if m in ("1", "true", "on", "yes", "v1"):
        return "v1"
    return "off"


def _decider_should_run(turns: int, user_text: str) -> bool:
    """
    Custo estável: roda mais quando o impacto é maior (início) e quando há risco de desvio.
    """
    if _decider_mode() != "v1":
        return False
    try:
        t = (user_text or "").strip()
    except Exception:
        t = ""
    if not t:
        return False
    # começo da conversa = onde errar intenção mata a experiência
    if int(turns or 0) <= 3:
        return True
    # também roda se for pergunta (?)
    if "?" in t:
        return True
    return False

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


# Spokenizer (texto -> fala humana) — V1
# - NÃO altera replyText (texto WhatsApp)
# - Só ajusta spokenText/ttsText (fala)
# - Default: v1 (pode desligar com SPOKENIZER_MODE=off)
SPOKENIZER_MODE = str(os.getenv("SPOKENIZER_MODE", "v1") or "v1").strip().lower()

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

    # Evita "rabicho" de TTS no final: sempre fecha com pontuação.
    if t and t[-1] not in ".!?)?":
        t = t + "."
    return t




def _spokenizer_should_run() -> bool:
    m = (SPOKENIZER_MODE or "").strip().lower()
    if not m:
        return False
    if m in ("0", "off", "false", "no", "none", "disabled", "disable"):
        return False
    return True


def _spokenize_v1(
    *,
    reply_text: str,
    intent_final: str,
    prefers_text: bool,
    has_url: bool,
    lead_name: str,
    turns: int,
) -> str:
    """
    Spokenizer v1 (determinístico e barato):
    - deixa a fala com ritmo (frases curtas, pausas naturais)
    - remove "cara de texto" (bullets, markdown, url)
    - quando há link/URL: fala curto e manda o link por escrito
    - no máximo 1 interjeição leve (sem teatrinho)
    """
    rt = (reply_text or "").strip()
    if not rt:
        return ""

    # Se a resposta contém link ou o policy marcou prefers_text, fala curto e humano
    # - prefers_text = fechamento/pedido explícito de link (ACK curto + link vai por escrito)
    # - has_url sozinho NÃO pode sequestrar a fala: só remove o link e mantém o conteúdo
    if prefers_text:
        nm = (lead_name or "").strip()
        if nm:
            return f"Fechado, {nm}. Te mandei por escrito o link e o caminho pra seguir."
        return "Fechado. Te mandei por escrito o link e o caminho pra seguir."

    # Se has_url=True sem prefers_text, seguimos e só limpamos o link da fala.

    t = rt
    # remove URLs explícitas (mesmo sem prefers_text)
    t = re.sub(r"(https?://\S+|www\.\S+)", "", t, flags=re.IGNORECASE).strip()
    # remove markdown simples
    t = _strip_md_for_tts(t)

    # troca quebras por pausa e limpa bullets/numeração no início de linha
    t = t.replace("\r", "\n")
    t = re.sub(r"\n{2,}", "\n", t).strip()
    t = re.sub(r"(?m)^\s*[-•\*\d]+\s*[\)\.\-–—]?\s*", "", t).strip()
    t = re.sub(r"\s+", " ", t).strip()

    # evita "cara de template"
    t = t.replace(":", ". ")
    t = t.replace("—", ". ").replace("–", ". ")
    t = t.replace("…", ". ")
    t = _flatten_scene_arrows(t)
    t = re.sub(r"\s*\.\s*", ". ", t).strip()
    t = re.sub(r"\s+", " ", t).strip()

    # intenção -> ritmo (sem interjeições fixas)
    # A IA já decide o tom no replyText; aqui a gente só deixa "falável".
    it = (intent_final or "").strip().upper()
    interj = ""

    # quebra frases longas: insere pausa antes de "mas", "só que", "aí", "então"
    t = re.sub(r"\s+(mas|só que|so que|aí|ai|então|entao)\s+", r". \1 ", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s+", " ", t).strip()

    # (Opcional) NÃO forçar nome aqui. Se a IA quiser usar nome, ela usa no replyText.

    out = t.strip()

    # normaliza números e unidades pra fala
    out = _spoken_normalize_numbers(out)
    out = _sanitize_spoken(out)

    # limite (evita fala longa demais no áudio)
    try:
        max_chars = int(os.getenv("SPOKENIZER_MAX_CHARS", "520") or "520")
    except Exception:
        max_chars = 520
    if max_chars > 0 and len(out) > max_chars:
        out = out[:max_chars].rstrip(" ,;:-") + "."

    return out.strip()


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


    # Pega "meu nome é X" / "me chamo X" no meio da frase (áudio STT real)
    try:
        m2 = re.search(
            r"\b(me chamo|meu nome é|meu nome e|pode me chamar de|podem me chamar de|aqui é|aqui e|eu sou|sou)\s+(?:o|a)?\s*([a-zA-ZÀ-ÿ'\-]{2,20}(?:\s+[a-zA-ZÀ-ÿ'\-]{2,20}){0,2})\b",
            t,
            flags=re.IGNORECASE,
        )
        if m2:
            name = (m2.group(2) or "").strip()
            name = re.sub(r"\s+", " ", name).strip()
            name = re.sub(r"[^\wÀ-ÿ\s'\-]", "", name).strip()
            if name and (not _looks_like_greeting(name)):
                return name
    except Exception:
        pass

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
    r"\b(e bot|é bot|eh bot|tu é bot|vc é bot|você é bot)\b",
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


def _is_capability_question(text: str) -> bool:
    """
    Detector barato de pergunta de capacidade/produto.
    Ex.: "O robô envia fotos?", "O robô canta?", "Ele marca horário?"
    Regra: se for pergunta objetiva de "faz X", NÃO é ruído.
    """
    t = (text or "").strip()
    if not t:
        return False
    tl = t.lower()
    if "?" not in tl:
        return False
    # começos típicos de dúvida objetiva
    if any(tl.startswith(x) for x in ("o robô", "o robo", "ele ", "ela ", "vocês", "voces", "dá pra", "da pra", "pode", "consegue", "tem como")):
        return True
    # verbos de capability (sem tentar prever tudo)
    if any(v in tl for v in ("envia", "manda", "responde", "fala", "canta", "marca", "agenda", "confirma", "anota", "cobra", "lembra")):
        return True
    return False

def _should_disclose_identity(user_text: str) -> bool:
    """Disclosure só quando provocado (lead pergunta se é humano/bot/quem está falando)."""
    t = (user_text or "").strip()
    if not t:
        return False
    tl = t.lower()

    # Perguntas explícitas / provocação direta
    patterns = [
        r"\b(vc|você)\s+é\s+(humano|pessoa)\b",
        r"\b(é|eh)\s+(humano|pessoa)\b",
        r"\b(é|eh)\s+(bot|rob[oô]|robozinho)\b",
        r"\b(quem)\s+(tá|ta|está|esta)\s+falando\b",
        r"\b(quem)\s+é\s+você\b",
        r"\b(quem)\s+é\s+vc\b",
        r"\b(atendente)\s+(humano|de\s+verdade)\b",
        r"\b(você)\s+é\s+real\b",
    ]
    for p in patterns:
        try:
            if re.search(p, tl, re.IGNORECASE):
                return True
        except Exception:
            continue

    # Heurística curta: "é bot?" / "é humano?" etc.
    if "?" in tl and len(tl) <= 30 and any(x in tl for x in ("bot", "robô", "robo", "humano", "real", "pessoa", "atendente")):
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


def _decider_cache_key(user_text: str) -> str:
    base = _norm(user_text or "")[:240]
    h = hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"sales:decider:{h}"


def _decider_cache_get(user_text: str) -> Optional[Dict[str, Any]]:
    try:
        raw = _kv_get(_decider_cache_key(user_text))
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            return json.loads(raw)
    except Exception:
        return None
    return None


def _decider_cache_set(user_text: str, val: Dict[str, Any]) -> None:
    try:
        ttl = int(os.getenv("SALES_DECIDER_CACHE_TTL_SECONDS", "600") or "600")  # 10 min
    except Exception:
        ttl = 600
    try:
        _kv_set(_decider_cache_key(user_text), val, ttl_seconds=ttl)
    except Exception:
        pass


def sales_ai_decider(
    *,
    user_text: str,
    turns: int,
    last_bot_excerpt: str,
) -> Dict[str, Any]:
    """
    IA (barata) para decisão cognitiva:
    - intent: VOICE|PRICE|PLANS|DIFF|ACTIVATE|WHAT_IS|OPERATIONAL|SLA|PROCESS|OTHER
    - confidence: high|mid|low
    - needs_clarification: bool
    - clarifying_question: 1 pergunta curta quando essencial
    - forbid_price: bool (evita cair em PRICE sem o usuário pedir)
    - safe_to_use_humor: bool (humor/empatia só com entendimento alto)
    """
    t = (user_text or "").strip()
    if not t:
        return {}

    cached = _decider_cache_get(t)
    if isinstance(cached, dict) and cached.get("intent"):
        return cached

    system = (
        "Você é o DECIDER do MEI Robô (Vendas) no WhatsApp (pt-BR).\n"
        "Responda SOMENTE JSON válido.\n\n"
        "Você decide o 'modo correto' de responder ANTES do texto final.\n"
        "Regras:\n"
        "- Não inventar. Não vender. Não falar preço se o usuário não pediu.\n"
        "- Se estiver ambíguo e precisar de dado essencial: needs_clarification=true e faça UMA pergunta curta.\n"
        "- Se estiver claro: needs_clarification=false.\n"
        "- VOICE: quando a pessoa pergunta se o robô 'parece ela', 'fala como ela', 'usa a voz dela', etc.\n\n"
        "Schema:\n"
        "{\"intent\":\"VOICE|PRICE|PLANS|DIFF|ACTIVATE|WHAT_IS|OPERATIONAL|SLA|PROCESS|OTHER\","
        "\"confidence\":\"high|mid|low\","
        "\"needs_clarification\":true|false,"
        "\"clarifying_question\":\"\","
        "\"forbid_price\":true|false,"
        "\"safe_to_use_humor\":true|false}\n"
    )
    user = (
        f"TURNS={int(turns or 0)}\n"
        f"ULTIMA_RESPOSTA_NAO_REPETIR={last_bot_excerpt or '—'}\n"
        f"MENSAGEM={t}\n"
    )

    raw = (_openai_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=OPENAI_SALES_NLU_MODEL,
        max_tokens=160,
        temperature=0.0,
        response_format={"type": "json_object"},
    ) or "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return {}
        intent = str(obj.get("intent") or "").strip().upper()
        if intent not in ("VOICE","PRICE","PLANS","DIFF","ACTIVATE","WHAT_IS","OPERATIONAL","SLA","PROCESS","OTHER"):
            intent = "OTHER"
        conf = str(obj.get("confidence") or "").strip().lower()
        if conf not in ("high","mid","low"):
            conf = "mid"
        needs = bool(obj.get("needs_clarification")) if obj.get("needs_clarification") is not None else False
        q = str(obj.get("clarifying_question") or "").strip()
        forbid_price = bool(obj.get("forbid_price")) if obj.get("forbid_price") is not None else False
        safe_humor = bool(obj.get("safe_to_use_humor")) if obj.get("safe_to_use_humor") is not None else False

        out = {
            "intent": intent,
            "confidence": conf,
            "needs_clarification": needs,
            "clarifying_question": q,
            "forbid_price": forbid_price,
            "safe_to_use_humor": safe_humor,
        }
        _decider_cache_set(t, out)
        return out
    except Exception:
        return {}

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

    # IA-first: heurísticas viram *prefill* (ajudam a IA), mas NUNCA retornam sem IA.
    prefill_name = ""
    prefill_segment = ""
    prefill_intent = ""
    try:
        # Prefill VOICE: ajuda a IA a classificar certo quando a frase é curta ("voz da gente", "fala como eu")
        tl = text.strip().lower()
        if any(k in tl for k in ("voz", "fala como", "fala igual", "minha voz", "voz da gente", "parece minha voz", "voz do dono", "responde com a voz")):
            prefill_intent = "VOICE"

        # Prefill OPERATIONAL+SEND_LINK: quando o lead pede link/site/onde entra (pedido operacional explícito)
        # (não é decisão final; só ajuda a IA a não escorregar para VALUE/triagem)
        if any(k in tl for k in ("link", "site", "url", "endereço", "endereco", "onde eu entro", "onde entro", "me manda o link", "me passa o site", "qual é o link", "qual o link")):
            if not prefill_intent:
                prefill_intent = "OPERATIONAL"

        if stage == "ASK_NAME" and len(text.strip()) <= 30:
            t = text.strip().lower()
            if any(k in t for k in ("quanto custa", "preço", "preco", "valor", "mensal", "assinatura", "planos", "plano", "starter", "starter+", "plus", "diferença", "diferenca", "memória", "memoria", "2gb", "10gb")):
                prefill_intent = "PRICE"
                if any(k in t for k in ("diferença", "diferenca", "memória", "memoria", "2gb", "10gb")):
                    prefill_intent = "DIFF"
                elif any(k in t for k in ("planos", "plano", "starter", "starter+", "plus")):
                    prefill_intent = "PLANS"
            if t not in ("oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "eai", "e aí", "opa"):
                nm = _extract_name_freeform(text) or ""
                nm = re.sub(r"[^\wÀ-ÿ\s'\-]", "", nm).strip()
                nm = re.sub(r"\s+", " ", nm).strip()
                if len(nm.split(" ")) > 3:
                    nm = " ".join(nm.split(" ")[:3])
                if nm and (not _looks_like_greeting(nm)):
                    prefill_name = nm
        if stage == "ASK_SEGMENT" and len(text.strip()) <= 40:
            prefill_segment = text.strip()
    except Exception:
        prefill_name = prefill_segment = prefill_intent = ""

    # Se não temos OpenAI, devolve algo seguro (degradação saudável)
    if not OPENAI_API_KEY:
        out = {"route": "sales", "intent": (prefill_intent or "OTHER"), "name": prefill_name, "segment": prefill_segment, "interest_level": "mid", "next_step": ""}
        if stage == "ASK_NAME" and prefill_name:
            out["next_step"] = "ASK_SEGMENT"
        if stage == "ASK_SEGMENT" and prefill_segment:
            out["next_step"] = "VALUE"
        return out

    system = (
        "Você é um CLASSIFICADOR de mensagens do WhatsApp do MEI Robô (pt-BR). "
        "Responda SOMENTE JSON válido (sem texto extra).\n\n"
        "Objetivo: entender a intenção do usuário para um atendimento de VENDAS do MEI Robô.\n\n"        "IMPORTANTE (IA no comando): você pode pedir 1 esclarecimento quando for essencial.\n"
        "- Se a intenção estiver clara, mas faltar um dado essencial ou a frase estiver ambígua: needs_clarification=true\n"
        "- Nesse caso, devolva clarifying_question com UMA pergunta curta e objetiva.\n"
        "- Se não precisar: needs_clarification=false e clarifying_question=\"\".\n"
        "- Extraia entities (map simples) quando existir (ex.: tipo_orcamento, timbrado, cor, logo, prazo, local, etc.).\n"
        "- confidence: high|mid|low.\n\n"

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
        "INTENTS permitidos: VOICE | PRICE | PLANS | DIFF | ACTIVATE | WHAT_IS | OPERATIONAL | SLA | PROCESS | OTHER.\n"
        "- VOICE: pergunta sobre parecer o profissional / responder em áudio com a voz/estilo do próprio profissional.\n"

        "- OPERATIONAL: pergunta prática de como funciona no dia a dia (ex.: agendar, organizar pedidos).\n"
"- PEDIDO DE LINK/SITE/ONDE ENTRA: isso é operacional explícito.\n"
"  -> intent='OPERATIONAL' e next_step='SEND_LINK' (sem triagem, sem VALUE).\n"
        "- SLA: pergunta sobre demora/prazo para começar (ex.: \"demora?\", \"em quantos dias?\").\n"
        "- PROCESS: pergunta sobre etapas do processo (ativação/configuração), sem focar em preço.\n\n"
        "route: 'sales' | 'offtopic' | 'emergency'.\n"
        "interest_level: 'low' | 'mid' | 'high'.\n"
        "next_step: '' | 'ASK_NAME' | 'ASK_SEGMENT' | 'VALUE' | 'PRICE' | 'SEND_LINK' | 'ASK_CLARIFY' | 'CTA' | 'EXIT'.\n"
        "Campos extras permitidos: entities (map), needs_clarification (bool), clarifying_question (string), confidence (high|mid|low).\n"

    )

    user = f"STAGE_ATUAL: {stage}\nMENSAGEM: {text}"
    # Prefill (não é decisão; só ajuda a IA a não errar slots óbvios)
    if prefill_name or prefill_segment or prefill_intent:
        user = (
            user
            + "\nPREFILL (heurística, se fizer sentido): "
            + json.dumps({"intent": prefill_intent, "name": prefill_name, "segment": prefill_segment}, ensure_ascii=False)
        )

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
        if intent not in ("VOICE", "PRICE", "PLANS", "DIFF", "ACTIVATE", "WHAT_IS", "OPERATIONAL", "SLA", "PROCESS", "OTHER"):
            intent = "OTHER"
        name = (out.get("name") or "").strip()
        segment = (out.get("segment") or "").strip()
        interest_level = (out.get("interest_level") or "mid").strip().lower()
        if interest_level not in ("low", "mid", "high"):
            interest_level = "mid"
        next_step = (out.get("next_step") or "").strip().upper()
        if next_step not in ("ASK_NAME", "ASK_SEGMENT", "VALUE", "PRICE", "SEND_LINK", "ASK_CLARIFY", "CTA", "EXIT"):
            next_step = ""

        entities = out.get("entities") if isinstance(out.get("entities"), dict) else {}
        needs_clarification = bool(out.get("needs_clarification")) if out.get("needs_clarification") is not None else False
        clarifying_question = str(out.get("clarifying_question") or "").strip()
        confidence = str(out.get("confidence") or "").strip().lower()
        if confidence not in ("high", "mid", "low"):
            confidence = "mid"

        return {
            "route": route,
            "intent": intent,
            "name": name,
            "segment": segment,
            "interest_level": interest_level,
            "next_step": next_step,
            "entities": entities,
            "needs_clarification": needs_clarification,
            "clarifying_question": clarifying_question,
            "confidence": confidence,
        }
    except Exception:
        return {"route": "offtopic", "intent": "OTHER", "name": "", "segment": "", "interest_level": "low", "next_step": "EXIT"}


def _economic_reply(
    *,
    intent: str,
    name: str,
    segment: str,
    goal: str,
    user_text: str,
    st: Dict[str, Any],
) -> Tuple[str, str, list]:
    """
    Execução econômica (sem IA geradora):
    Retorna (replyText, planNextStep, policiesApplied)
    """
    intent_u = (intent or "").strip().upper()
    policies: list = []
    kb = _get_sales_kb() or {}
    process = (kb.get("process_facts") or {}) if isinstance(kb, dict) else {}

    # defaults factuais (não promete o que não existe)
    if not isinstance(process, dict) or not process:
        process = {
            "billing_model": "assinatura mensal (paga)",
            "no_free_trial": True,
            "sla_setup": "até 7 dias úteis para número virtual + configuração concluída",
            "can_prepare_now": "você já cria a conta e deixa tudo pronto na plataforma (serviços, rotina, agenda).",
        }

    def _site_line() -> str:
        return SITE_URL if SITE_URL else "www.meirobo.com.br"

    # PRICE/PLANS/DIFF: determinístico e canônico
    if intent_u in ("PRICE", "PLANS", "DIFF"):
        policies.append("depth:economic")
        return (_enforce_price_direct(kb, segment=segment), "PRICE", policies)

    # SLA
    if intent_u == "SLA":
        policies.append("depth:economic")
        sla = str(process.get("sla_setup") or "até 7 dias úteis para número virtual + configuração concluída").strip()
        can = str(process.get("can_prepare_now") or "").strip()
        txt = f"Hoje o prazo é {sla}. {can}".strip()
        txt = (txt + f"\n\nSe quiser, eu te mando o link pra criar a conta: {_site_line()}").strip()
        return (txt, "SEND_LINK", policies)

    # PROCESS (como assina / passos)
    if intent_u == "PROCESS":
        policies.append("depth:economic")
        billing = str(process.get("billing_model") or "assinatura mensal (paga)").strip()
        txt = (
            f"É {billing}. O caminho é simples:\n"
            f"1) entra no site\n"
            f"2) cria a conta\n"
            f"3) segue a ativação\n\n"
            f"{_site_line()}"
        )
        txt = _strip_trailing_question(txt)
        return (txt, "SEND_LINK", policies)

    # VOICE (pergunta sobre voz / parecer a própria pessoa)
    if intent_u == "VOICE":
        policies.append("depth:economic")

        nm = (name or "").strip()
        head = f"{nm}, sim —" if nm else "Sim —"

        txt = (
            f"{head} o MEI Robô pode responder em áudio com a voz do próprio profissional, "
            "depois que ele configura a voz na conta dele. "
            "Se quiser ver o caminho certinho, é só entrar no nosso site."
        )

        return (txt, "VALUE", policies)

    # ACTIVATE (quero assinar / ativar / manda o link)
    if intent_u == "ACTIVATE":
        policies.append("depth:economic")
        txt = f"Fechado. Pra assinar e começar a ativação, é por aqui: {_site_line()}"
        txt = _strip_trailing_question(txt)
        return (txt, "SEND_LINK", policies)

    return ("", "", [])


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
        "- intent: VOICE|PRICE|ACTIVATE|OPERATIONAL|PROCESS|SLA|OTHER|SMALLTALK|OBJECTION\n"
        "- tone: confiante|consultivo|leve|bem_humano\n"
        "- ask_mode: none|one_short|ab_choice\n"
        "- close_mode: none|soft|hard\n"
        "- next_step: ''|ASK_NAME|ASK_SEGMENT|VALUE|PRICE|SEND_LINK|CTA|EXIT\n"
        "- scene_key: opcional (ex.: 'segment_pills', 'segments', 'value_in_action_blocks.services_quote_scene', 'memory_positioning')\n"
        "- kb_need: lista objetiva do que buscar (somente permitido em kb_need_allowed)\n"
        "- reply: texto curto (2–5 linhas) pronto pra enviar\n"
        "- evidence: 1 linha explicando a escolha (somente para log)\n\n"
        "Regras de comportamento (produto):\n"
        "- Se intent=VOICE: responda direto e curto (sim + como funciona + limites + próximo passo). Não misture com 'número virtual' a menos que perguntem isso.\n"

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
        if plan_intent and plan_intent not in ("VOICE","PRICE","ACTIVATE","OPERATIONAL","PROCESS","SLA","OTHER","SMALLTALK","OBJECTION"):
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

        # operações (repertório factual; ex.: e-mail diário 06:30)
        "operational_capabilities": {
            "scheduling_practice": _clip_long(
                str((((kb.get("operational_capabilities") or {}) if isinstance(kb, dict) else {}).get("scheduling_practice") or "")),
                520,
            )
        },
        "empathy_triggers": _first_n(kb.get("empathy_triggers") or [], 6),

    }



def _select_kb_blocks_by_intent(intent_final: str) -> list:
    """
    Retorna lista de chaves da KB que devem entrar no prompt,
    com base na intenção final detectada.
    Sempre curto, previsível e econômico.
    """
    if not intent_final:
        return []

    intent = str(intent_final).strip().upper()

    if intent == "PRICE":
        return ["pricing_facts", "scenario_index"]

    if intent == "TRUST":
        return ["objections", "memory_positioning"]

    if intent == "VOICE":
        # factual e curto; voice_pill entra quando existir no Firestore
        return ["voice_pill", "voice_positioning", "process_facts"]

    if intent in ("PROCESS", "SLA"):
        return ["process_facts", "intent_guidelines"]

    if intent == "OPERATIONAL":
        return ["segment_pills", "operational_capabilities"]

    if intent == "ACTIVATE":
        return ["closing_guidance", "pricing_facts"]

    return []


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

    kb_blocks = []

    # --- Roteamento de KB por intenção (econômico e previsível) ---
    routed_kb_keys = _select_kb_blocks_by_intent(intent_hint)

    for kb_key in routed_kb_keys:
        if kb_key in kb:
            kb_blocks.append(kb[kb_key])

    # Respeita política: usar pills primeiro, long form só como referência
    kb_policy = (kb or {}).get("kb_policy") or {}
    if isinstance(kb_policy, dict) and kb_policy.get("runtime_use_pills_first", False):
        kb_blocks = [b for b in kb_blocks if isinstance(b, (str, dict))]
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

    # Políticas extras (Firestore) — manter curto pra custo
    should_disclose = _should_disclose_identity(user_text)

    disclosure_line = ""
    try:
        disclosure_line = str(((kb.get("identity_disclosure") or {}) if isinstance(kb.get("identity_disclosure"), dict) else {}).get("disclosure_line") or "").strip()
    except Exception:
        disclosure_line = ""
    if not disclosure_line:
        disclosure_line = "Sou assistente virtual do MEI Robô."

    brand_guardrails = []
    try:
        bg = kb.get("brand_guardrails") or []
        if isinstance(bg, list):
            brand_guardrails = [str(x).strip() for x in bg if str(x).strip()]
    except Exception:
        brand_guardrails = []

    depth_policy = str(kb.get("depth_policy") or "").strip()
    discovery_policy = []
    try:
        dp = kb.get("discovery_policy") or []
        if isinstance(dp, list):
            discovery_policy = [str(x).strip() for x in dp if str(x).strip()]
    except Exception:
        discovery_policy = []

    brand_block = ""
    if brand_guardrails:
        brand_block = "MARCA (obrigatório):\n" + "\n".join([f"- {x}" for x in brand_guardrails[:6]]) + "\n\n"

    discovery_block = ""
    if discovery_policy:
        discovery_block = "DESCOBERTA (jeito de puxar contexto):\n" + "\n".join([f"- {x}" for x in discovery_policy[:4]]) + "\n\n"

    identity_block = (
        "IDENTIDADE (só quando provocado):\n"
        f"- Se o lead perguntar se é humano/bot/quem está falando: responda 1 frase curta e honesta (ex.: {disclosure_line}) e volte pro valor.\n\n"
    )

    routed_block_line = ""
    try:
        if kb_blocks:
            routed_block_line = (
                "kb_routed_blocks (use como referência; não copie): "
                + json.dumps(kb_blocks, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
    except Exception:
        routed_block_line = ""


    prompt = (
        f"{brand_block}{discovery_block}{identity_block}Você é o MEI Robô – Vendas, atendendo leads no WhatsApp (pt-BR).\n"
        "Use o conteúdo do Firestore (platform_kb/sales) como REPERTÓRIO de identidade, nunca como script.\n"
        "Nada deve soar decorado, técnico ou robótico.\n\n"
        "Fale com energia positiva (vibrante na medida), como um vendedor humano, sem soar forçado.\n\n"
        "IMPORTANTE:\n"
        "- Se is_first_contact=yes, agradeça o contato em 1 frase curta e humana e já responda a dúvida; sem formalidade.\n"
        "- Se is_first_contact=no, não repita agradecimento.\n\n"
        "SOBERANIA (importante): você decide autonomamente, a cada resposta:\n"
        "- se usa ou não o nome do lead\n"
        "- se demonstra empatia\n"
        "- se aprofunda um pouco mais\n"
        "- se fecha ou apenas orienta\n"
        "- se a mensagem é teste/ironia/resistência consciente: acompanhe como humano e siga, sem puxar pra formulário\n"
        "Use behavior_rules, tone_rules, closing_guidance, sales_audio_modes e conversation_limits para DECIDIR.\n"
        "Não siga regras mecânicas do tipo 'use nome no turno X'.\n\n"
        "- Não se apresente do nada (sem 'meu nome é...'). EXCEÇÃO: se o lead perguntar se é humano/bot/quem está falando, responda 1 frase curta e honesta sobre ser assistente virtual do MEI Robô e volte pro valor.\n"
        f"depth_policy_ref: {depth_policy or '—'}\n"
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
        "- Ritmo de conversa: 1) valida em 1 frase, 2) dá 1 micro-exemplo, 3) fecha com 1 próximo passo. Sem lista gigante.\n"
        "- Humor leve permitido, mas só 1 toque e sem virar piada.\n"

        "CONTEÚDO:\n"
        "- Priorize sales_pills, value_props_top3, e micro-scenes por segmento.\n"
        "- Use micro-exemplo operacional (entrada → organização → resumo pro dono) quando ajudar.\n"
        "- Nunca invente números.\n"
        "- Só cite preço quando fizer sentido e apenas usando pricing_facts.\n\n"
        "PREÇO:\n"
        "- Se perguntarem preço direto: responda o valor (Starter/Starter+) e diga que a diferença é só a memória.\n"
        "- Não comece com 'depende'.\n"
        "- Sem pergunta no final (depois do preço, dê um próximo passo curto).\n\n"
        "REALIDADE DO PRODUTO (obrigatório):\n"
        "- Não diga que o robô 'agenda automaticamente'. Diga que ele organiza, confirma e registra; o profissional acompanha e decide.\n"
        "- O profissional recebe um número de WhatsApp Business virtual (na nuvem), sem chip. Ele pode continuar com os números atuais e migrar aos poucos.\n"
        "- Não force troca de número: explique uso em paralelo e migração gradual.\n"
        "- Não existe teste grátis. Não prometa 'testar hoje'.\n"
        "- Em fechamento (intent_hint='CTA'), assine a última linha como: — Ricardo, do MEI Robô\n\n"
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
        "  entrada do cliente → confirmação → aviso ao profissional → registro na agenda → lembrete opcional.\n"
        "- Não explique conceitos soltos.\n"
        "- Não repita o que já foi dito antes.\n"
        "- Finalize com no máximo 1 pergunta de direcionamento (ex.: agenda ou pedidos?).\n\n"
        f"mensagem: {user_text}\n\n"
        f"continuidade: {continuity}\n\n"
        f"is_first_contact: {'yes' if turns == 0 else 'no'}\n\n"
        f"onboarding_hint (se existir): {json.dumps(onboarding_hint, ensure_ascii=False)}\n"
        f"{routed_block_line}"
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


    # Disclosure só quando provocado (e sem virar textão)
    try:
        if should_disclose and disclosure_line:
            low = (reply_text or "").lower()
            if not re.search(r"(assistente\s+virtual|atendente\s+virtual|sou\s+um\s+(bot|rob[oô]))", low, re.IGNORECASE):
                reply_text = (disclosure_line.strip() + "\n" + reply_text).strip()
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

    turns = int(st.get("turns") or 0) + 1
    st["turns"] = turns
    st["last_user_at"] = time.time()

    nudges = int(st.get("nudges") or 0)

    # =========================
    # DECIDER (IA) — manda no "modo de resposta"
    # =========================

    dec = {}
    try:
        # IA-first: sempre roda (custo controlado por cache + max_tokens)
        if _decider_mode() == "v1":
            dec = sales_ai_decider(
                user_text=text_in,
                turns=turns,
                last_bot_excerpt=str(st.get("last_bot_reply_excerpt") or "").strip(),
            ) or {}
            # Observabilidade
            if isinstance(dec, dict) and dec:
                st["decision_intent"] = str(dec.get("intent") or "").strip().upper()
                st["decision_confidence"] = str(dec.get("confidence") or "").strip().lower()
                st["decision_forbid_price"] = bool(dec.get("forbid_price"))
                st["decision_safe_humor"] = bool(dec.get("safe_to_use_humor"))
                st["decision_needs_clarification"] = bool(dec.get("needs_clarification"))
    except Exception:
        dec = {}


    # Se a IA decidiu que precisa esclarecer (1 pergunta) -> obedece e para
    try:
        if isinstance(dec, dict) and dec.get("needs_clarification"):
            q = str(dec.get("clarifying_question") or "").strip()
            if q:
                q = _strip_generic_question_ending(q)
                q = _limit_questions(q, max_questions=1)
                q = _apply_anti_loop(
                    st, q,
                    name=(st.get("name") or "").strip(),
                    segment=(st.get("segment") or "").strip(),
                    goal=(st.get("goal") or "").strip(),
                    user_text=text_in
                )
                return _clip(q, SALES_MAX_CHARS_REPLY)
    except Exception:
        pass

    # NLU (IA) — fonte canônica de intent/route/next_step/interest
    nlu = sales_micro_nlu(text_in, stage=stage)

    # IA-first: quando a NLU já decidiu SEND_LINK, isso é execução imediata (não triagem).
    # OBS: o generate_reply é quem garante prefersText + link no replyText + ACK falável.
    try:
        _ns0 = str((nlu or {}).get("next_step") or "").strip().upper()
        if _ns0 == "SEND_LINK":
            st["plan_intent"] = str((nlu or {}).get("intent") or "OPERATIONAL").strip().upper() or "OPERATIONAL"
            st["plan_next_step"] = "SEND_LINK"
            _name = (st.get("name") or "").strip()
            if _name:
                return f"{_name}, fechado — vou te mandar o link aqui na conversa."
            return "Fechado — vou te mandar o link aqui na conversa."
    except Exception:
        pass

    # Guardrail (IA-first): pedido OPERACIONAL não pode cair em "OTHER".
    # Se não estiver claro o que enviar, faz 1 pergunta objetiva (sem congelar).
    try:
        _t = str(text_in or "").strip().lower()
        _i = str((nlu or {}).get("intent") or "").strip().upper()
        _ns = str((nlu or {}).get("next_step") or "").strip().upper()

        # Sinais fracos porém úteis de "pedido" (não depende de palavra exata; só reduz falso-negative)
        _has_request_shape = any(x in _t for x in (
            "pode", "podes", "poderia", "consegue", "tem como",
            "me ", "pra mim", "pra gente", "aí", "ai"
        ))
        _has_send_shape = any(x in _t for x in (
            "manda", "mandar", "envia", "enviar", "passa", "passar",
            "compartilha", "compartilhar", "anexa", "anexar",
            "me dá", "me da", "joga", "jogar", "solta", "soltar"
        ))

        # Objetos comuns (apenas para decidir "SEND_LINK" quando for muito óbvio; resto pergunta)
        _asks_link = any(x in _t for x in ("link", "site", "página", "pagina", "url", "endereço", "endereco"))

        _looks_operational = (_has_request_shape and _has_send_shape) or _asks_link

        if _looks_operational and (_i in ("", "OTHER")):
            nlu = dict(nlu or {})
            nlu["intent"] = "OPERATIONAL"
            # Se é claramente link/site, já manda SEND_LINK; senão, 1 clarificação objetiva
            if _asks_link:
                nlu["next_step"] = "SEND_LINK"
                nlu["depth"] = nlu.get("depth") or "shallow"
                nlu["risk"] = nlu.get("risk") or "low"
                nlu["confidence"] = nlu.get("confidence") or "high"
            else:
                nlu["next_step"] = "ASK_CLARIFY"
                nlu["depth"] = nlu.get("depth") or "shallow"
                nlu["risk"] = nlu.get("risk") or "low"
                nlu["confidence"] = nlu.get("confidence") or "mid"
                # UMA pergunta curta, sem triagem genérica
                nlu["clarifying_question"] = nlu.get("clarifying_question") or "Beleza — você quer que eu te envie o link do site, um PDF ou uma imagem?"
        else:
            # Se a IA já escolheu ASK_CLARIFY, garante que exista pergunta
            if _ns == "ASK_CLARIFY":
                nlu = dict(nlu or {})
                if not str(nlu.get("clarifying_question") or "").strip():
                    nlu["clarifying_question"] = "Só pra eu te atender certo: você quer link, PDF ou imagem?"
    except Exception:
        pass
        # IA-first (trava operacional): pedido operacional NÃO pode cair em VALUE/triagem.
        # Aqui o handler só executa a decisão: ou manda link (SEND_LINK) ou faz 1 pergunta objetiva (ASK_CLARIFY).
        # Importante: _reply_from_state SEMPRE retorna string (o dict canônico é montado em generate_reply).
        try:
            _i = str((nlu or {}).get("intent") or "").strip().upper()
            _ns = str((nlu or {}).get("next_step") or "").strip().upper()
            if _i == "OPERATIONAL" and _ns in ("SEND_LINK", "ASK_CLARIFY"):
                st["plan_intent"] = "OPERATIONAL"
                st["plan_next_step"] = _ns

                _name = (
                    st.get("lead_name")
                    or st.get("name")
                    or st.get("leadName")
                    or st.get("display_name")
                    or ""
                )
                _name = str(_name or "").strip()
                _prefix = (f"{_name}, " if _name else "")

                if _ns == "SEND_LINK":
                    # Não precisa colar URL aqui: generate_reply garante o link e o prefersText.
                    return (_prefix + "fechado — vou te mandar o link aqui na conversa.").strip()

                # ASK_CLARIFY (1 pergunta curta, sem triagem)
                q = str((nlu or {}).get("clarifying_question") or "").strip()
                if not q:
                    q = "Beleza — você quer o link do site, um PDF ou uma imagem?"
                return (_prefix + q).strip()
        except Exception:
            pass

# IA-first (mínimo garantido): se ainda não existe plano, “promove” NLU para plano leve.
    # Isso NÃO gera texto caro — só evita cair no genérico.
    try:
        _nlu_intent = str(nlu.get("intent") or "").strip().upper()
        _nlu_next = str(nlu.get("next_step") or "").strip().upper()
        if not str(st.get("plan_intent") or "").strip() and _nlu_intent:
            st["plan_intent"] = _nlu_intent
        if not str(st.get("plan_next_step") or "").strip() and _nlu_next:
            st["plan_next_step"] = _nlu_next
    except Exception:
        pass

    interest = (nlu.get("interest_level") or "mid").strip().lower()
    st["interest_level"] = interest  # evita segunda chamada no generate_reply
    next_step = (nlu.get("next_step") or "").strip().upper()
    route = (nlu.get("route") or "sales").strip().lower()

    # Se o Decider estiver confiante, ele ganha (IA-first).
    # Isso evita o caso que você viu: cair em PRICE e forçar preço fora de contexto.
    try:
        if isinstance(dec, dict) and dec.get("intent"):
            if str(dec.get("confidence") or "").strip().lower() == "high":
                nlu["intent"] = str(dec.get("intent") or "").strip().upper()
                # Árbitro final (IA-first): promove para plano canônico
                st["plan_intent"] = str(nlu.get("intent") or "").strip().upper()
                # Quando o Decider proíbe preço, evitamos qualquer trilho que force preço
                if bool(dec.get("forbid_price")) and str(nlu.get("intent") or "").strip().upper() in ("PRICE","PLANS","DIFF"):
                    nlu["intent"] = "OTHER"
                    st["plan_intent"] = "OTHER"
    except Exception:
        pass

    # Guarda um “intent de entendimento” (contrato) — usado na saída
    try:
        st["understand_intent"] = str(nlu.get("intent") or "").strip().upper()
        st["understand_confidence"] = str(nlu.get("confidence") or "").strip().lower()
        st["understand_route"] = str(nlu.get("route") or "sales").strip().lower()
        # risco simples: low/mid/high (barato)
        _cf = st.get("understand_confidence") or "mid"
        st["understand_risk"] = ("high" if _cf == "low" else ("mid" if _cf == "mid" else "low"))
    except Exception:
        pass


    # Guarda entities (slots) para continuidade/observabilidade (best-effort)
    try:
        ents = nlu.get("entities") or {}
        if isinstance(ents, dict) and ents:
            st["entities"] = ents
    except Exception:
        pass

    # Clarificação universal (IA decide; código só executa)
    try:
        if bool(nlu.get("needs_clarification")):
            q = str(nlu.get("clarifying_question") or "").strip()
            if q:
                # Guardrails universais: 1 pergunta, sem loop, falável
                q = _strip_generic_question_ending(q)
                q = _limit_questions(q, max_questions=1)
                q = _apply_anti_loop(
                    st,
                    q,
                    name=(st.get("name") or "").strip(),
                    segment=(st.get("segment") or "").strip(),
                    goal=(st.get("goal") or "").strip(),
                    user_text=text_in,
                )
                return _clip(q, SALES_MAX_CHARS_REPLY)
    except Exception:
        pass

    # VOICE: não “pula” o pipeline. A resposta sairá pelo econ/planner/composer.

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
            # Não aciona Human Gate quando a mensagem é claramente sobre VOICE (produto).
            try:
                tl = (text_in or "").strip().lower()
                if ("voz" in tl) or ("fala com" in tl and "voz" in tl) or ("minha voz" in tl) or ("voz da gente" in tl):
                    st["__human_gate_done"] = True
                # também: se a pessoa já mandou "meu nome é", não pedir de novo
                if ("meu nome" in tl) or ("me chamo" in tl) or ("pode me chamar" in tl):
                    st["__human_gate_done"] = True
            except Exception:
                pass
            # Pergunta objetiva de capacidade/produto NÃO é ruído (bloqueia gate).
            if (not _is_capability_question(text_in)) and _detect_human_noise(text_in):
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
    # EXECUÇÃO ECONÔMICA (templates) — 80–90% dos casos
    (econ, econ_next, econ_policies) = ("", "", [])
    try:
        econ, econ_next, econ_policies = _economic_reply(
            intent=str(nlu.get("intent") or "").strip().upper(),
            name=name,
            segment=segment,
            goal=goal,
            user_text=text_in,
            st=st,
        )
        if econ:
            try:
                st["plan_intent"] = str(nlu.get("intent") or "").strip().upper()
                st["plan_next_step"] = (econ_next or "").strip().upper()
                st["plan_depth"] = "economic"
                st["plan_risk"] = str(st.get("understand_risk") or "mid")
                st["policiesApplied"] = list(set((st.get("policiesApplied") or []) + econ_policies))
            except Exception:
                pass
            econ = _apply_anti_loop(st, econ, name=name, segment=segment, goal=goal, user_text=text_in)
            econ = _limit_questions(econ, max_questions=1)
            return _clip(econ, SALES_MAX_CHARS_REPLY)
    except Exception:
        pass

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
    if ((not has_name) or (not has_segment)) and intent not in ("VOICE",):
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
        # Sempre devolve debug leve, mesmo se plan/intent estiverem vazios
        try:
            _dbg_intent = ""
        except Exception:
            _dbg_intent = ""
        try:
            _dbg_next = ""
        except Exception:
            _dbg_next = ""

        dbg = {
            "source": "sales_lead",
            "composer_mode": _composer_mode(),
            "intent": _dbg_intent,
            "next_step": _dbg_next,
        }

        return {
            "replyText": OPENING_ASK_NAME,
            "ttsOwner": "worker",
            "kind": "sales",
            "_debug": dbg,
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

    

    # Helpers locais (precisam existir ANTES do primeiro uso)
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
            or ("como assina" in t)
            or ("como assinar" in t)
            or ("quero assinar" in t)
            or ("quero contratar" in t)
            or ("quero fechar" in t)
            or ("vou assinar" in t)
            or ("pode me mandar" in t and "proced" in t)
            or ("me manda" in t and "proced" in t)
            or ("como eu contrato" in t)
        )

    # Intenção final preferencial: IA (plan_intent / understand_intent) -> estado (last_intent) -> cheap (só se sem OpenAI)
    try:
        intent_final = str(st.get("plan_intent") or st.get("understand_intent") or st.get("last_intent") or "").strip().upper()
    except Exception:
        intent_final = ""
    if not intent_final:
        # Só cai no cheap se NÃO tem OpenAI (degradação saudável)
        if not OPENAI_API_KEY:
            try:
                intent_final = str(_intent_cheap(text_in) or "").strip().upper()
            except Exception:
                intent_final = ""

    
    # --------------------------------------------------
    # FALLBACK SEMÂNTICO BARATO — VOICE (sem IA cara)
    # --------------------------------------------------
    if not intent_final:
        t = (text_in or "").lower()
        if any(k in t for k in [
            "minha voz",
            "voz da gente",
            "fala com a minha voz",
            "robô fala como eu",
            "fala com a voz"
        ]):
            intent_final = "VOICE"
            # VOICE é conceitual; não é fechamento
            # (next_step_final fica resolvido abaixo; aqui só dá um default seguro)

# Next step final (Planner soberano): usado para policy (link/close), sem heurística esperta.
    try:
        next_step_final = str(st.get("plan_next_step") or "").strip().upper()
    except Exception:
        next_step_final = ""

    # Purificação: quando existe plano da IA (intent/next_step), overrides estratégicos não podem competir.
    has_plan = bool((str(st.get("plan_intent") or "").strip()) or (next_step_final or "").strip())


    # Paraquedas controlado (execução): se o lead pediu LINK/SITE,
    # SEND_LINK tem precedência sobre VALUE (pedido explícito do usuário).
    try:
        if (next_step_final != "SEND_LINK") and _wants_link(text_in):
            next_step_final = "SEND_LINK"
            st["plan_next_step"] = "SEND_LINK"
            # Ajuda a manter o contrato estável sem inventar intent novo.
            if not str(st.get("plan_intent") or "").strip():
                st["plan_intent"] = "ACTIVATE"
            policies_applied.append("policy:force_send_link_on_wants_link")
    except Exception:
        pass


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

    # Policy (novo trilho): se o Planner mandou SEND_LINK, o código só GARANTE que o link aparece.
    # Isso não é estratégia: é execução do plano (sem competir com a IA).
    # Blindagem de produto: VOICE não é fechamento, a menos que o lead tenha pedido link/assinar.
    try:
        if str(intent_final or "").strip().upper() == "VOICE" and (not _wants_link(text_in)):
            if str(next_step_final or "").strip().upper() == "SEND_LINK":
                next_step_final = "VALUE"
    except Exception:
        pass

    if next_step_final == "SEND_LINK":
        if not _has_url(reply_final):
            reply_final = (reply_final.rstrip() + f"\n\n{SITE_URL}").strip()
        prefers_text = True
        if lead_name:
            spoken_final = f"Fechado, {lead_name}! Na sequência eu te mando por escrito o link pra assinar."
        else:
            spoken_final = "Fechado! Na sequência eu te mando por escrito o link pra assinar."
        policies_applied.append("policy:plan_send_link")

    # Legado controlado (compat): se não há plano e overrides estão ligados, mantém o comportamento antigo.
    if (next_step_final != "SEND_LINK") and (not has_plan) and _strategic_overrides_enabled() and _wants_link(text_in):
        reply_final = (
            f"{SITE_URL} — ali você cria a conta e já deixa serviços/agenda prontos. "
            "A ativação completa leva até 7 dias úteis."
        )
        prefers_text = True
        if lead_name:
            spoken_final = f"Fechado, {lead_name}! Na sequência eu te mando por escrito o link pra assinar."
        else:
            spoken_final = "Fechado! Na sequência eu te mando por escrito o link pra assinar."
        policies_applied.append("override:link")
    # URL no replyText NUNCA liga prefersText.
    # prefersText só vem do plano (next_step_final == SEND_LINK) ou do override controlado (wants_link sem plano).

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

    # Decider (IA) pode proibir preço quando o usuário NÃO pediu preço
    forbid_price = False
    try:
        forbid_price = bool(st.get("decision_forbid_price"))
    except Exception:
        forbid_price = False

    if is_price and (not forbid_price):
        reply_final = _enforce_price_direct(kb, segment="")
        reply_final = _strip_trailing_question(reply_final)
        prefers_text = False
        spoken_final = _sanitize_spoken(reply_final)
        spoken_final = _strip_md_for_tts(spoken_final)
        spoken_final = _spoken_normalize_numbers(spoken_final)
        pricing_used = True
        pricing_source = str((kb or {}).get("pricing_source") or "platform_pricing/current")
        policies_applied.append("price:firestore_only")
    elif is_price and forbid_price:
        policies_applied.append("price:blocked_by_decider")


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

    # Complemento leve (sem competir com plano): se o Firestore tem o fato do e-mail 06:30,
    # e a pergunta foi sobre agenda/agendamento/notificação, mas a resposta não citou isso,
    # acrescenta apenas a frase factual.
    try:
        oc2 = kb.get("operational_capabilities") or {}
        sched2 = str(oc2.get("scheduling_practice") or "").strip()
    except Exception:
        sched2 = ""

    if is_agenda_question and sched2:
        out_norm2 = _norm(reply_final)
        if ("06:30" in sched2) and ("06:30" not in reply_final) and ("email" not in out_norm2) and ("e-mail" not in out_norm2):
            reply_final = (reply_final.rstrip(". ") + ".\n\nTambém recebe um e-mail diário (dias úteis) às 06:30 com os agendamentos do dia.").strip()
            spoken_final = _sanitize_spoken(reply_final)
            spoken_final = _strip_md_for_tts(spoken_final)
            spoken_final = _spoken_normalize_numbers(spoken_final)
            policies_applied.append("append:email_digest_0630")

    # aplica também aqui (garante consistência)
    spoken_final = _spoken_normalize_numbers(spoken_final)

        # VOICE: sinal para o worker preservar resposta conceitual importante (sem truncar)
    tts_no_truncate = False
    try:
        if str(intent_final or "").strip().upper() == "VOICE":
            tts_no_truncate = True
            policies_applied.append("voice:no_truncate")
    except Exception:
        pass

    # =========================
    # SPOKENIZER v1 (só fala)
    # =========================
    try:
        if _spokenizer_should_run():
            _has = _has_url(reply_final)
            spoken_v1 = _spokenize_v1(
                reply_text=reply_final,
                intent_final=intent_final,
                prefers_text=bool(prefers_text),
                has_url=bool(_has),
                lead_name=lead_name,
                turns=int(st.get("turns") or 0),
            )
            if spoken_v1:
                spoken_final = spoken_v1
    except Exception:
        # nunca quebra o fluxo por causa da fala
        pass


    # Sempre devolve debug leve, mesmo se plan/intent estiverem vazios
    try:
        _dbg_intent = (intent_final or "").strip().upper()
    except Exception:
        _dbg_intent = ""
    try:
        _dbg_next = ""
        plan = st.get("ai_plan") if isinstance(st, dict) else None
        if isinstance(plan, dict):
            _dbg_next = str(plan.get("next_step") or "").strip()
        if not _dbg_next:
            _dbg_next = str(next_step_final or "").strip()
    except Exception:
        _dbg_next = ""

    dbg = {
        "source": "sales_lead",
        "composer_mode": _composer_mode(),
        "intent": _dbg_intent,
        "next_step": _dbg_next,
    }

    # Decider debug (IA-first)
    decision_debug = {
        "mode": _decider_mode(),
        "intent": str(st.get("decision_intent") or "").strip(),
        "confidence": str(st.get("decision_confidence") or "").strip(),
        "forbid_price": bool(st.get("decision_forbid_price")),
        "needs_clarification": bool(st.get("decision_needs_clarification")),
        "safe_to_use_humor": bool(st.get("decision_safe_humor")),
    }
    # Contrato IA-first (entendimento) — nunca vazio (auditável no worker/Firestore)
    try:
        _intent_u = str(st.get("understand_intent") or intent_final or "").strip().upper()
    except Exception:
        _intent_u = (intent_final or "").strip().upper()
    if not _intent_u:
        _intent_u = "OTHER"

    try:
        _ns_u = str(next_step_final or st.get("plan_next_step") or "").strip().upper()
    except Exception:
        _ns_u = str(next_step_final or "").strip().upper()

    try:
        _conf_u = str(st.get("understand_confidence") or st.get("decision_confidence") or "").strip().lower()
    except Exception:
        _conf_u = ""
    if _conf_u not in ("high", "mid", "low"):
        _conf_u = ""

    try:
        _risk_u = str(st.get("understand_risk") or "").strip().lower()
    except Exception:
        _risk_u = ""
    if _risk_u not in ("low", "mid", "high"):
        _risk_u = ("high" if _conf_u == "low" else ("mid" if _conf_u else "mid"))

    try:
        _depth_u = str(st.get("plan_depth") or "").strip().lower()
    except Exception:
        _depth_u = ""
    if _depth_u not in ("economic", "deep"):
        _depth_u = "economic" if _intent_u in ("VOICE","PRICE","PLANS","DIFF","PROCESS","SLA","ACTIVATE") else "deep"

    understand_contract = {
        "intent": _intent_u,
        "confidence": _conf_u,
        "route": str(st.get("understand_route") or "sales").strip().lower(),
        "risk": _risk_u,
        "depth": _depth_u,
        "next_step": _ns_u,
    }

    return {
        "replyText": reply_final,
        "nameUse": (st.get("last_name_use") or ""),
        "prefersText": prefers_text,

        # 🔒 Fonte de verdade para áudio (worker deve preferir estes campos)
        "ttsText": spoken_final,
        "spokenText": spoken_final,

        # Contrato de política/auditoria (incremental)
        "intentFinal": understand_contract.get("intent") or "OTHER",
        "planNextStep": understand_contract.get("next_step") or "",
        "understanding": understand_contract,
        "pricingUsed": pricing_used,
        "pricingSource": pricing_source,
        "policiesApplied": policies_applied,
        "traceId": trace_id,

        "ttsNoTruncate": tts_no_truncate,

        # Observabilidade (IA no comando): prova do plano e do que foi usado
        "aiPlan": (st.get("ai_plan") or {}),
        "kbUsed": (st.get("kb_used") or []),
        "sceneKey": (st.get("scene_key") or ""),
        "askMode": (st.get("ask_mode") or ""),
        "closeMode": (st.get("close_mode") or ""),
        "planIntent": (st.get("plan_intent") or ""),
        "planNextStepRaw": (st.get("plan_next_step") or ""),
        "planEvidence": (st.get("plan_evidence") or ""),
        "kbSnippet": json.dumps((st.get("kb_snippet") or {}), ensure_ascii=False),
        "spokenSource": "replyText",
        "decisionDebug": decision_debug,

        "decision": decision_debug,

        "leadName": lead_name,
        "segment": lead_segment,
        "goal": lead_goal,
        "interest_level": (st.get("interest_level") or "").strip(),
        "kind": kind,
        "kbContext": json.dumps(kb_compact, ensure_ascii=False),
        "ttsOwner": "worker",
        "nameToSay": lead_name,

        "_debug": dbg,
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
