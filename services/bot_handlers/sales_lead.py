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
import unicodedata
from typing import Any, Dict, Optional, Tuple
# ==========================================================
# Firestore client (credencial consistente)
# - Evita 403 "Missing or insufficient permissions" quando o client pega credencial errada (ADC).
# - Preferimos o client do firebase_admin (mesma credencial do backend).
# ==========================================================
def _fs_client():
    """Firestore client canônico: sempre via firebase_admin.
    - Determinístico em Render e Cloud Run.
    - Evita ADC (GOOGLE_APPLICATION_CREDENTIALS) apontar para projeto errado.
    """
    try:
        from services.firebase_admin_init import ensure_firebase_admin  # type: ignore
        ensure_firebase_admin()
        from firebase_admin import firestore as fb_firestore  # type: ignore
        return fb_firestore.client()
    except Exception:
        raise RuntimeError("firestore_client_failed_firebase_admin_required")



# ==========================================================
# Limites de custo / sessão (cinturão de excesso)
# ==========================================================
MAX_TURNS_PER_SESSION = 15
MAX_AI_CALLS_PER_SESSION = 6
MAX_TTS_PER_SESSION = 6
MAX_OTHER_STREAK = 3





_SALES_INJECT_NAME_IN_TEXT = str(os.getenv("SALES_INJECT_NAME_IN_TEXT", "0")).strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

def _maybe_prefix_name_in_text(text: str, name: str) -> str:
    """Nome no TEXTO é desligado por padrão.
    Motivo: o nome deve ser aplicado pelo worker só no ÁUDIO (gate), quando a IA sinaliza via nameUse/name_use.
    Feature flag de emergência: SALES_INJECT_NAME_IN_TEXT=1
    """
    try:
        if not _SALES_INJECT_NAME_IN_TEXT:
            return text
        nm = (name or "").strip()
        if not nm or not text:
            return text
        low = text.lower()
        if nm.lower() in low:
            return text
        return f"{nm}, " + text.lstrip()
    except Exception:
        return text

# ==========================================================
# Regra de produto (VENDAS institucional): teto por contato
# - 15..18 mensagens "inteligentes" por contato (hard cap = 18)
# - Pergunta esclarecedora é permitida (custo assumido), mas limitada por contato
# ==========================================================
LEAD_MAX_SMART_MSGS = int(os.getenv("LEAD_MAX_SMART_MSGS", "18") or "18")
LEAD_SOFT_WARNING_AT = int(os.getenv("LEAD_SOFT_WARNING_AT", "15") or "15")
LEAD_MAX_CLARIFY_QS = int(os.getenv("LEAD_MAX_CLARIFY_QS", "1") or "1")

def _speechify_for_tts(text: str) -> str:
    """
    Ajustes mínimos pra TTS falar bem, sem destruir conteúdo.
    IMPORTANTE: aplicar só no texto falado (spoken/tts), nunca no replyText.
    """
    try:
        s = str(text or "").strip()
        if not s:
            return ""

        # Remove bullets visuais (TTS costuma falar "bolinha" ou truncar ritmo)
        s = s.replace("•", "").replace("·", "")

        # URLs: não ler inteiro no áudio (o link vai no texto do worker)
        s = re.sub(r"https?://\S+", "o link tá na mensagem", s)

        # HH:MM -> "H horas" / "H e MM"
        def _hhmm(m):
            hh = int(m.group(1))
            mm = int(m.group(2))
            if mm == 0:
                return f"{hh} horas"
            return f"{hh} e {mm:02d}"
        s = re.sub(r"\b(\d{1,2}):(\d{2})\b", _hhmm, s)

        # Data BR simples dd/mm/aaaa -> "dd de mm de aaaa" (sem nomes de mês)
        s = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", r"\1 de \2 de \3", s)

        # Dinheiro: "R$ 89,00" -> "89 reais"
        s = re.sub(r"R\$\s*(\d+)(?:[.,](\d{2}))?", r"\1 reais", s)

        # Travessão vira pausa (mais humano no TTS)
        s = s.replace("—", ", ").replace("–", ", ")

        # Setas / "->" viram pausa natural
        s = s.replace("→", ". ").replace("->", ". ")

        # Pontos e vírgulas / reticências: pausas mais humanas
        s = s.replace(";", ". ")
        s = s.replace("...", "…")

        # Normaliza espaços
        s = re.sub(r"[ \t]+", " ", s).strip()


        # Pontuação: remove espaços antes de vírgula/ponto/interrogação etc.
        s = re.sub(r"\s+,", ",", s)
        s = re.sub(r"\s+\.", ".", s)
        s = re.sub(r"\s+([!?])", r"\1", s)
        s = re.sub(r"\s+:", ":", s)
        s = re.sub(r"\s{2,}", " ", s).strip()

        # Ritmo (VENDAS): se estiver longo, quebra em pausas (no máximo 6 linhas)
        if len(s) >= 140:
            s = re.sub(r"([.!?])\s+", r"\1\n", s)
            s = re.sub(r"(:)\s+", r"\1\n", s)
            parts = [p.strip() for p in s.split("\n") if p.strip()]
            if len(parts) > 6:
                parts = parts[:6]
            s = "\n".join(parts)

        return s.strip()
    except Exception:
        return text


# --- Sales usage logger (lightweight, best-effort) ---
def _log_sales_usage(
    fs,
    wa_key: str,
    stage: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
):
    try:

        from firebase_admin import firestore as fb_firestore  # type: ignore
        ref = fs.collection("platform_sales_usage").document(wa_key)
        ref.set(
            {
                "turns": fb_firestore.Increment(1),
                "ai_calls": fb_firestore.Increment(1),
                "approx_tokens_in": fb_firestore.Increment(int(tokens_in or 0)),
                "approx_tokens_out": fb_firestore.Increment(int(tokens_out or 0)),
                "last_stage": stage,
                "updatedAt": fb_firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    except Exception:
        # nunca quebra o fluxo de vendas
        pass


# =========================
# Conteúdo CANÔNICO (VENDAS)
# =========================

SITE_URL = os.getenv("MEI_ROBO_SITE_URL", "https://www.meirobo.com.br").strip()

# Link canônico (cadastro/ativação) — usado quando o lead pede "assinar/ativar/link".
MEI_ROBO_CADASTRO_URL = os.getenv(
    "MEI_ROBO_CADASTRO_URL",
    "https://www.meirobo.com.br",
).strip()

# Preço SEMPRE vem daqui (fonte única)
PLATFORM_PRICING_DOC = os.getenv(
    "PLATFORM_PRICING_DOC",
    "platform_pricing/current",
).strip()

# Auto-alias + cache mínimo (Firestore)
PLATFORM_ALIAS_DOC = os.getenv("PLATFORM_ALIAS_DOC", "platform_kb_action_maps/aliases_sales").strip()
PLATFORM_RESPONSE_CACHE_COLLECTION = os.getenv("PLATFORM_RESPONSE_CACHE_COLLECTION", "platform_response_cache").strip()



# Purificação (incremental e reversível):
# - SALES_STRATEGIC_OVERRIDES=1 mantém overrides antigos (link/procedimento/agenda) por compat.
#   Depois, desligar (=0) para IA+KB assumirem 100% do trilho.
# - SALES_STRICT_NO_PRICE_OUTSIDE_INTENT=1 aplica política dura: fora de PRICE/PLANS/DIFF, não pode sair "R$".

# Mensagem mínima de entrada (mantida local por segurança operacional)
OPENING_ASK_NAME = (
    "Beleza. Antes de eu te explicar certinho, como posso te chamar?"
)

# Fallback humano mínimo (nunca vazio; sem marketing longo)
def _fallback_min_reply(name: str = "", user_text: str = "") -> str:
    # Texto nunca recebe nome por padrão (nome é do ÁUDIO via worker/gate).
    # Mantemos flag de emergência para reativar prefixo no texto se precisar.
    ut = (user_text or "").strip().lower()
    if any(k in ut for k in ("quanto tempo", "demora", "quando", "fica pronto", "ativ", "funcion")):
        base = "Entendi. É sobre em quanto tempo o WhatsApp fica ativo depois que você contrata, ou é sobre pagamento/cadastro?"
    else:
        base = "Perfeito. Você quer falar de pedidos, agenda, orçamento ou só conhecer?"
    return _maybe_prefix_name_in_text(base, name)


def _fallback_by_intent(intent: str, *, name: str = "", user_text: str = "") -> str:
    """Fallback honesto + 1 pergunta prática (por intent).

    Usado quando a KB faltar ou o contrato mínimo não fechar.
    Regra: nunca cair em "menu" genérico.
    """
    i = (intent or "OTHER").strip().upper()

    if i in ("PROCESS", "SLA", "ACTIVATE", "ACTIVATE_SEND_LINK"):
        base = "Entendi. É sobre em quanto tempo o WhatsApp fica ativo depois que você contrata, ou é sobre pagamento/cadastro?"
    elif i in ("PRICE", "PLANS", "DIFF"):
        base = "Fechado. Você quer que eu te diga o plano ideal pelo teu uso: vai ser mais agenda, pedidos ou orçamento?"
    elif i in ("VOICE",):
        base = "Beleza. Você quer entender como funciona a voz na prática, ou prefere só saber o passo a passo de envio do áudio?"
    elif i in ("OPERATIONAL",):
        base = "Perfeito. No teu caso é mais agenda (horários) ou mais pedidos/orçamentos no WhatsApp?"
    else:
        base = _fallback_min_reply(name=name, user_text=user_text)
        return _maybe_prefix_name_in_text(base, name)

    return _maybe_prefix_name_in_text(base, name)


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
    elif intent_p == "OPERATIONAL":
        # Força micro-fluxo fechado (entrada → confirmação → aviso → agenda → lembrete)
        intent_hint = "OPERATIONAL_FLOW"
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

    # ==========================================================
    # Social ACK (IA decide; código só dá cadência)
    # - evita "frase pronta": IA escreve a linha
    # - evita spam: no mínimo 3 turnos entre ACKs
    # ==========================================================
    try:
        sal = str(plan.get("social_ack_line") or "").strip()
    except Exception:
        sal = ""
    if sal:
        try:
            turns = int(state.get("turns") or 0) if isinstance(state, dict) else 0
        except Exception:
            turns = 0
        try:
            last_t = int(state.get("last_social_ack_turn") or 0) if isinstance(state, dict) else 0
        except Exception:
            last_t = 0
        # gap de turnos (barato e suficiente)
        if (turns - last_t) >= 3:
            low = (txt or "").lower()
            if sal.lower() not in low:
                txt = (sal + "\n" + txt).strip()
            if isinstance(state, dict):
                state["last_social_ack_turn"] = int(turns)
                state["last_social_ack_text"] = sal


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


SALES_SIGNUP_URL = str(os.getenv("SALES_SIGNUP_URL") or "https://www.meirobo.com.br").strip()

# ==========================================================
# Spoken sanitize (TTS): horas/datas/moeda/pontuação/URL
# - Não altera replyText (texto WhatsApp)
# - Só melhora spokenText/ttsText
# ==========================================================
_RE_TIME_HHMM = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_RE_DATE_DDMMYYYY = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_RE_BR_MONEY = re.compile(r"\bR\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\b")
_RE_URL = re.compile(r"\bhttps?://\S+\b", re.IGNORECASE)
_RE_DOT_DOT = re.compile(r"\.\s*\.")

def _spoken_sanitize(text: str) -> str:
    """Sanitiza texto para fala (TTS). Mantém o texto curto e natural."""
    try:
        s = str(text or "").strip()
        if not s:
            return s

        # Evita "palestra de URL" no áudio: link fica no texto
        s = _RE_URL.sub("o link tá aqui na mensagem", s)

        # Corrige pontuação duplicada que atrapalha TTS (". .")
        s = _RE_DOT_DOT.sub(".", s)

        # Horas: 06:30 -> 06h30 (evita virar "06. 30")
        s = _RE_TIME_HHMM.sub(r"\1h\2", s)

        # Datas: 30/01/2026 -> 30 de 01 de 2026 (neutro e estável)
        s = _RE_DATE_DDMMYYYY.sub(r"\1 de \2 de \3", s)

        # Moeda: R$ 89,00 -> 89 reais (mantém simples)
        def _money(m):
            v = (m.group(1) or "").replace(".", "").replace(",00", "")
            return f"{v} reais"
        s = _RE_BR_MONEY.sub(_money, s)

        # Limpa espaços estranhos
        s = re.sub(r"\s+", " ", s).strip()
        return s
    except Exception:
        return str(text or "")

def _is_link_request(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    # Pedido direto/objetivo: não pode cair em OTHER
    keys = ("link", "site", "cadastro", "criar conta", "criar a conta", "assinar", "assinatura", "começar", "comecar", "entrar")
    return any(k in t for k in keys)

_RE_NAME_1 = re.compile(r"\b(meu nome e|meu nome é|me chamo|eu sou o|eu sou a|sou o|sou a)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\- ]{1,40})", re.IGNORECASE)
def _extract_name_from_text(text: str) -> str:
    """Extrai nome simples de frases comuns. Conservador por segurança."""
    try:
        t = (text or "").strip()
        if not t:
            return ""
        m = _RE_NAME_1.search(t)
        if not m:
            return ""
        name = (m.group(2) or "").strip()
        # corta no primeiro separador óbvio
        name = re.split(r"[,.!?/\\|\n\r]", name)[0].strip()
        if len(name) < 2:
            return ""
        # pega só as 2 primeiras palavras (nome/sobrenome) pra não virar frase inteira
        parts = [p for p in name.split() if p]
        name = " ".join(parts[:2]).strip()
        return name
    except Exception:
        return ""

def _maybe_append_ask_name(reply_text: str, st: Dict[str, Any], intent_final: str) -> str:
    """Pergunta o nome UMA vez, no momento certo (não em ACTIVATE/SEND_LINK)."""
    try:
        if not isinstance(st, dict):
            return reply_text
        name = (st.get("name") or st.get("lead_name") or "").strip()
        if name:
            return reply_text
        if st.get("asked_name_once") is True:
            return reply_text
        i = (intent_final or "").strip().upper()
        if i in ("ACTIVATE", "ACTIVATE_SEND_LINK") or st.get("plan_next_step") == "SEND_LINK":
            return reply_text

        # (sem gate de turnos): responde e coleta o nome 1x, exceto em CTA/link


        st["asked_name_once"] = True
        q = "Só pra eu te tratar direitinho: qual teu nome?"
        if reply_text.endswith("?") or reply_text.endswith("!"):
            return reply_text + " " + q
        return reply_text.rstrip() + " " + q
    except Exception:
        return reply_text

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



# Blindagem de economia: nunca enviar KB inteira ao LLM
# Limite duro do "slice" de KB que pode entrar em prompts (chars ~ tokens*4)
_SALES_KB_SLICE_MAX_CHARS = int(os.getenv("SALES_KB_SLICE_MAX_CHARS", "3600") or "3600")
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
            from firebase_admin import firestore as fb_firestore  # type: ignore
            client = _fs_client()
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
        from firebase_admin import firestore as fb_firestore  # type: ignore
        client = _fs_client()
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
# Firestore: leitura mínima (1 caixa/turno)
# =========================

_SALES_SLICE_CACHE: Dict[str, Any] = {}
_SALES_SLICE_CACHE_AT: Dict[str, float] = {}

def _get_doc_fields(doc_path: str, field_paths: list, *, ttl_seconds: int = 180) -> Dict[str, Any]:
    """Busca apenas campos específicos de um doc no Firestore.
    Best-effort: se não suportar field_paths no ambiente, cai em get() normal e filtra em memória.
    """
    doc_path = (doc_path or "").strip().strip("/")
    if not doc_path:
        return {}
    try:
        fp = [str(x).strip() for x in (field_paths or []) if str(x).strip()]
    except Exception:
        fp = []
    cache_key = f"doc:{doc_path}|" + ",".join(fp)
    now = time.time()
    try:
        at = float(_SALES_SLICE_CACHE_AT.get(cache_key) or 0.0)
        if cache_key in _SALES_SLICE_CACHE and (now - at) < float(ttl_seconds or 0):
            v = _SALES_SLICE_CACHE.get(cache_key)
            return v if isinstance(v, dict) else {}
    except Exception:
        pass

    out: Dict[str, Any] = {}
    try:
        from firebase_admin import firestore as fb_firestore  # type: ignore
        client = _fs_client()
        parts = [p for p in doc_path.split("/") if p]
        if len(parts) < 2:
            return {}
        ref = client.collection(parts[0]).document(parts[1])

        doc = None
        if fp:
            try:
                doc = ref.get(field_paths=fp)
            except Exception:
                doc = ref.get()
        else:
            doc = ref.get()

        if not doc or not getattr(doc, "exists", False):
            return {}

        data = doc.to_dict() or {}
        if not isinstance(data, dict):
            return {}

        if not fp:
            out = data
        else:
            # Filtra em memória (resiliente a field_paths não suportado)
            for p in fp:
                cur = data
                ok = True
                for seg in p.split("."):
                    if not isinstance(cur, dict) or seg not in cur:
                        ok = False
                        break
                    cur = cur.get(seg)
                if ok:
                    tgt = out
                    segs = p.split(".")
                    for seg in segs[:-1]:
                        if seg not in tgt or not isinstance(tgt.get(seg), dict):
                            tgt[seg] = {}
                        tgt = tgt[seg]
                    tgt[segs[-1]] = cur
    except Exception:
        out = {}

    try:
        _SALES_SLICE_CACHE[cache_key] = out
        _SALES_SLICE_CACHE_AT[cache_key] = now
    except Exception:
        pass
    return out


def _get_display_prices(*, ttl_seconds: int = 180) -> Dict[str, str]:
    """Retorna display_prices do doc canônico de pricing."""
    data = _get_doc_fields(PLATFORM_PRICING_DOC, ["display_prices"], ttl_seconds=ttl_seconds) or {}
    dp = data.get("display_prices") if isinstance(data, dict) else {}
    if not isinstance(dp, dict):
        return {}
    out: Dict[str, str] = {}
    for k in ("starter", "starter_plus", "starterPlus", "starter+"):
        v = dp.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    if "starter_plus" not in out and "starterPlus" in out:
        out["starter_plus"] = out["starterPlus"]
    return out


def _is_smalltalk(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if _detect_human_noise(t):
        return True
    if any(x in t for x in ("kkk", "haha", "rsrs", "robôzinho", "robozinho", "cartoon", "chuva", "papagaio")):
        return True
    if len(t) <= 12 and t in ("e aí", "eai", "oi", "olá", "ola", "opa", "bom dia", "boa tarde", "boa noite"):
        return True
    return False


def _smalltalk_bridge(text: str) -> str:
    t = (text or "").strip().lower()
    if "cartoon" in t:
        return "Saudades do Cartoon também 😅 Mas me diz: você quer ver como o robô ajuda na agenda, pedidos ou orçamento?"
    if "chuva" in t or "clima" in t or "tempo" in t:
        return "Aqui o tempo muda e o WhatsApp não perdoa 😄 Quer que eu te mostre como ele organiza agenda ou pedidos?"
    if "papagaio" in t:
        return "Se for pra repetir, que seja pedido do cliente 😄 Quer ver como ele responde e organiza tudo no WhatsApp?"
    if "kkk" in t or "haha" in t or "rsrs" in t:
        return "Boa 😄 Me diz: você quer entender como funciona, preço, ou ver um exemplo prático?"
    return "Fechado 😄 Você quer entender como funciona, preço, ou ver um exemplo prático?"

_BOX_INTENTS = (
    "PRICE",
    "VOICE",
    "AGENDA",
    "CONTACTS",
    "QUOTE",
    "WHAT_IS",
    "OPERATIONAL",
    "DIFF",
    "PROCESS",
    "ACTIVATE_SEND_LINK",
    "TRUST",
    "OTHER",
)

def _sales_box_mode() -> str:
    v = str(os.getenv("SALES_BOX_MODE", "v1") or "v1").strip().lower()
    if v in ("0", "off", "false", "no"):
        return "off"
    return "v1"


def _box_decider_cache_key(text: str) -> str:
    base = _norm(text or "")[:240]
    h = hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"sales:boxdec:{h}"


def _box_decider_cache_get(text: str) -> Optional[Dict[str, Any]]:
    try:
        return _kv_get(_box_decider_cache_key(text))
    except Exception:
        return None


def _box_decider_cache_set(text: str, val: Dict[str, Any]) -> None:
    try:
        ttl = int(os.getenv("SALES_BOX_DECIDER_CACHE_TTL_SECONDS", "600") or "600")
    except Exception:
        ttl = 600
    try:
        _kv_set(_box_decider_cache_key(text), val, ttl_seconds=ttl)
    except Exception:
        pass



def _detect_social_gesture(t: str) -> Dict[str, str]:
    """
    Detector BARATO (não é NLU) só para garantir ACK humano quando a IA não sinaliza.
    Não lista datas/feriados: usa respostas universais.
    Retorna: {"kind": "none|thanks|praise|holiday", "line": "..."}
    """
    try:
        s = (t or "").strip().lower()
    except Exception:
        return {"kind": "none", "line": ""}
    if not s:
        return {"kind": "none", "line": ""}

    # votos/saudações (universal)
    if any(k in s for k in ("feliz ", "boas festas", "bom ano", "ano novo", "boas", "parabéns", "parabens")):
        return {"kind": "holiday", "line": "Igualmente! 🎉"}

    # agradecimento
    if any(k in s for k in ("obrigad", "valeu", "agradec")):
        return {"kind": "thanks", "line": "Valeu mesmo! 😊"}

    # elogio
    if any(k in s for k in ("top", "show", "muito bom", "massa", "curti", "gostei", "legal demais")):
        return {"kind": "praise", "line": "Que bom! 😊"}

    return {"kind": "none", "line": ""}



def sales_box_decider(*, user_text: str) -> Dict[str, Any]:
    """Decider econômico: escolhe 1 caixa e (quando necessário) 1 pergunta."""
    t = (user_text or "").strip()
    if not t:
        return {"intent": "OTHER", "confidence": 0.3, "needs_clarification": False, "clarifying_question": "", "next_step": "NONE", "gratitude": "NONE"}

    cached = _box_decider_cache_get(t)
    if isinstance(cached, dict) and str(cached.get("intent") or "").strip():
        return cached

    if not OPENAI_API_KEY:
        cheap = _intent_cheap(t)
        intent = "OTHER"
        if cheap in ("PRICE", "PLANS"):
            intent = "PRICE"
        elif cheap in ("DIFF",):
            intent = "DIFF"
        elif cheap in ("VOICE",):
            intent = "VOICE"
        elif cheap in ("WHAT_IS",):
            intent = "WHAT_IS"
        elif cheap in ("OPERATIONAL",):
            intent = "OPERATIONAL"
        elif cheap in ("PROCESS",):
            intent = "PROCESS"
        elif cheap in ("ACTIVATE",):
            intent = "ACTIVATE_SEND_LINK"
        out = {"intent": intent, "confidence": 0.65, "needs_clarification": False, "clarifying_question": "", "next_step": ("SEND_LINK" if intent == "ACTIVATE_SEND_LINK" else "NONE"), "gratitude": "NONE"}
        _box_decider_cache_set(t, out)
        return out

    # Firestore-first: regras extras do decider vindas do KB (sem deploy)
    kb_rules = ""
    try:
        kb = _get_sales_kb() or {}
        kb_rules = str(kb.get("box_decider_rules") or "").strip()
    except Exception:
        kb_rules = ""

    system = (
        "Você é o DECIDER de VENDAS do MEI Robô (WhatsApp, pt-BR).\n"
        "Responda SOMENTE JSON válido.\n\n"
        "Escolha UMA intenção (caixa) por turno:\n"
        "PRICE, VOICE, AGENDA, CONTACTS, QUOTE, WHAT_IS, OPERATIONAL, DIFF, PROCESS, ACTIVATE_SEND_LINK, TRUST, OTHER.\n\n"
        "Dica: se falar de \"marcar horário\", \"agenda\", \"ligam/telefone\", \"procedimento\", é AGENDA.\n"
        "Regras:\n"
        "- Se estiver ambíguo e faltar dado essencial: needs_clarification=true e faça UMA pergunta curta.\n"
        "- Se a pergunta for objetiva, responda direto (needs_clarification=false).\n"
        "- confidence deve ser número de 0 a 1.\n"
        "- next_step: SEND_LINK ou NONE.\n\n"
        "- social_ack: none|contact|thanks|praise|holiday (obrigatório quando houver gesto social)\n"
        "- social_ack_line: 1 frase curta (<=70 chars), sem pergunta (obrigatória quando houver gesto social)\n"
        "\n"
        "Se o lead fizer gesto social (agradecer, elogiar, mandar votos/saudações, ou \"valeu\"):\n"
        "- SEMPRE preencha social_ack e escreva social_ack_line curta e humana.\n"
        "- social_ack_line é OBRIGATÓRIA nesses casos.\n"
        "- exemplos de votos (não exaustivo): \"feliz 2026\", \"boas festas\", \"feliz ano\".\n"
        "- não faça textão; no máximo 1 frase.\n"
        "- não coloque pergunta nessa linha.\n\n"
        "Além disso, sinalize gratidão quando o usuário agradecer/elogiar/mandar votos (sem criar nova intent):\n- gratitude: NONE | THANKS | PRAISE | HOLIDAY\n\nSchema: {\"intent\":...,\"confidence\":0.0,\"needs_clarification\":true|false,\"clarifying_question\":\"\",\"next_step\":\"SEND_LINK|NONE\",\"gratitude\":\"NONE|THANKS|PRAISE|HOLIDAY\",\"social_ack\":\"none|contact|thanks|praise|holiday\",\"social_ack_line\":\"...\"}"
    )
    if kb_rules:
        system = system + "\n\n" + kb_rules

    user = f"MENSAGEM={t}"
    raw = (_openai_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=OPENAI_SALES_NLU_MODEL,
        max_tokens=120,
        temperature=0.0,
        response_format={"type": "json_object"},
    ) or "").strip()
    out: Dict[str, Any] = {}
    try:
        obj = json.loads(raw) if raw else {}
        if not isinstance(obj, dict):
            obj = {}
        intent = str(obj.get("intent") or "OTHER").strip().upper()
        if intent not in _BOX_INTENTS:
            intent = "OTHER"
        conf = obj.get("confidence")
        try:
            conf_f = float(conf)
        except Exception:
            conf_f = 0.55
        conf_f = max(0.0, min(1.0, conf_f))
        needs = bool(obj.get("needs_clarification")) if obj.get("needs_clarification") is not None else False
        q = str(obj.get("clarifying_question") or "").strip()
        ns = str(obj.get("next_step") or "NONE").strip().upper()
        if ns not in ("SEND_LINK", "NONE"):
            ns = "NONE"

        gr = str(obj.get("gratitude") or "").strip().upper()
        if not gr:
            try:
                sa_tmp = str(obj.get("social_ack") or "").strip().lower()
            except Exception:
                sa_tmp = ""
            if sa_tmp == "thanks":
                gr = "THANKS"
            elif sa_tmp == "praise":
                gr = "PRAISE"
            elif sa_tmp == "holiday":
                gr = "HOLIDAY"
            else:
                gr = "NONE"
        if gr not in ("NONE", "THANKS", "PRAISE", "HOLIDAY"):
            gr = "NONE"


        # social ACK (best-effort; opcional)
        try:
            sa = str(obj.get("social_ack") or "none").strip().lower()
        except Exception:
            sa = "none"
        if sa not in ("none", "contact", "thanks", "praise", "holiday"):
            sa = "none"
        try:
            sal = str(obj.get("social_ack_line") or "").strip()
        except Exception:
            sal = ""
        # 1 frase só, curta, sem quebras
        if sal:
            sal = sal.replace("\\r", " ").replace("\\n", " ").strip()
            if len(sal) > 70:
                sal = sal[:70].rstrip() + "…"


        # ==========================================================
        # GARANTIA (produto): gesto social => 1 ACK humano sempre
        # - Preferência: IA sinaliza via social_ack_line
        # - Fallback: 1 linha universal (sem lista de datas)
        # ==========================================================
        if not sal or sa == "none":
            det = _detect_social_gesture(t)
            if det.get("kind") and det.get("kind") != "none":
                # se a IA não marcou, a gente marca (barato) e deixa a composição prefixar
                if sa == "none":
                    sa = det["kind"]
                if not sal:
                    sal = det.get("line") or ""
                # Gratitude alinhada (melhor para logs/política)
                if gr == "NONE":
                    if sa == "thanks":
                        gr = "THANKS"
                    elif sa == "praise":
                        gr = "PRAISE"
                    elif sa == "holiday":
                        gr = "HOLIDAY"
        out = {
            "intent": intent,
            "confidence": conf_f,
            "needs_clarification": needs,
            "clarifying_question": q,
            "next_step": ns,
            "gratitude": gr,
            "social_ack": sa,
            "social_ack_line": sal,
        }
    except Exception:
        out = {"intent": "OTHER", "confidence": 0.45, "needs_clarification": False, "clarifying_question": "", "next_step": "NONE", "gratitude": "NONE"}

    _box_decider_cache_set(t, out)
    return out


def _kb_slice_for_box(intent: str, *, segment: str = "") -> Dict[str, Any]:
    i = (intent or "OTHER").strip().upper()
    seg = (segment or "").strip().lower()
    base_fields = [
        "tone_rules",
        "behavior_rules",
        "brand_guardrails",
        "closing_guidance",
        "closing_styles",
        "value_props",
    ]

    if i == "PRICE":
        fields = base_fields + ["sales_pills.cta_one_liners"]
        # cache mínimo (Firestore) — evita reler sempre se estiver quente
        ck = _kb_slice_cache_key(i, segment)
        cached = _fs_cache_get(ck)
        if isinstance(cached, dict) and cached.get("kind") == "kb_slice" and isinstance(cached.get("payload"), dict):
            return cached.get("payload") or {}
        payload = _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)
        _fs_cache_set(ck, {"kind": "kb_slice", "intent": i, "payload": payload}, ttl_seconds=int(os.getenv("SALES_KB_SLICE_CACHE_TTL_SECONDS", "600") or "600"))
        return payload


    if i == "ACTIVATE_SEND_LINK":
        fields = base_fields + [
            "process_facts.sla_setup",
            "process_facts.can_prepare_now",
            "process_facts.no_free_trial",
            "intent_guidelines.ACTIVATE",
            "closing_behaviors",
            "cta_variations",
            "sales_pills.cta_one_liners",
        ]
        # cache mínimo (Firestore) — evita reler sempre se estiver quente
        ck = _kb_slice_cache_key(i, segment)
        cached = _fs_cache_get(ck)
        if isinstance(cached, dict) and cached.get("kind") == "kb_slice" and isinstance(cached.get("payload"), dict):
            return cached.get("payload") or {}
        payload = _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)
        _fs_cache_set(ck, {"kind": "kb_slice", "intent": i, "payload": payload}, ttl_seconds=int(os.getenv("SALES_KB_SLICE_CACHE_TTL_SECONDS", "600") or "600"))
        return payload

    if i == "WHAT_IS":
        fields = base_fields + [
            "sales_pills.identity_blurb",
            "sales_pills.how_it_works_3steps",
            "sales_pills.how_it_works",
            "identity_positioning",
            "value_in_action_blocks.scheduling_scene",
            # Preferir texto “falável” quando existir na KB (evita “scene/next_step_hint” cru)
            "value_in_action_blocks.scheduling_scene_text",
        ]
        # cache mínimo (Firestore) — evita reler sempre se estiver quente
        ck = _kb_slice_cache_key(i, segment)
        cached = _fs_cache_get(ck)
        if isinstance(cached, dict) and cached.get("kind") == "kb_slice" and isinstance(cached.get("payload"), dict):
            return cached.get("payload") or {}
        payload = _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)
        _fs_cache_set(ck, {"kind": "kb_slice", "intent": i, "payload": payload}, ttl_seconds=int(os.getenv("SALES_KB_SLICE_CACHE_TTL_SECONDS", "600") or "600"))
        return payload

    if i == "DIFF":
        fields = base_fields + ["commercial_positioning", "product_boundaries", "plans.difference"]
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)


    if i == "OPERATIONAL":
        fields = base_fields + [
            # Direção de fala + regras de vendedor (vem do teu Firestore)
            "behavior_rules",
            "brand_guardrails",
            "discovery_policy",
            "depth_policy",
            "operational_capabilities",
            "operational_flows",
            "operational_value_scenarios",
            "value_in_action_blocks.scheduling_scene",
            "value_in_action_blocks.services_quote_scene",
            "value_in_action_blocks.formal_quote_email_scene",
            "segment_pills.servicos.micro_scene",
        ]
        if seg:
            fields.append(f"segment_pills.{seg}.micro_scene")
            fields.append(f"segments.{seg}.one_question")
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)

    if i == "AGENDA":
        fields = base_fields + [
            "behavior_rules",
            "brand_guardrails",
            "operational_capabilities.scheduling_practice",
            "operational_flows.agenda_do_dia",
            "operational_flows.agendamento_completo",
            "value_in_action_blocks.scheduling_scene",
            "process_facts.dashboard_agenda",
            "process_facts.daily_email_digest",
        ]
        if seg:
            fields.append(f"segment_pills.{seg}.micro_scene")
            fields.append(f"segments.{seg}.one_question")
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)

    if i == "QUOTE":
        fields = base_fields + [
            "behavior_rules",
            "brand_guardrails",
            "operational_flows.orcamento_com_validacao",
            "operational_capabilities.quotes_practice",
            "value_in_action_blocks.services_quote_scene",
            "value_in_action_blocks.formal_quote_email_scene",
        ]
        if seg:
            fields.append(f"segment_pills.{seg}.micro_scene")
            fields.append(f"segments.{seg}.one_question")
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)

    if i == "CONTACTS":
        fields = base_fields + [
            "behavior_rules",
            "brand_guardrails",
            "operational_capabilities.services_practice",
            "operational_value_scenarios.whatsapp_organizado_sem_bagunça",
        ]
        if seg:
            fields.append(f"segment_pills.{seg}.micro_scene")
            fields.append(f"segments.{seg}.one_question")
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)

    if i == "VOICE":
        fields = base_fields + [
            "voice_pill.short_yes",
            "voice_pill.how_it_works",
            "voice_pill.boundaries",
            "voice_pill.next_step",
            "voice_positioning.core",
        ]
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)

    if i in ("PROCESS", "SLA"):
        # Processo / SLA: precisa de fatos do processo (prazo, preparo, cobrança, etc.)
        fields = base_fields + [
            "commercial_positioning",
            "process_facts.sla_setup",
            "process_facts.can_prepare_now",
            "process_facts.billing_model",
            "process_facts.no_free_trial",
        ]
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)

    if i == "ACTIVATE":
        # Ativação: como começa + o que precisa (sem prometer mágica)
        fields = base_fields + [
            "commercial_positioning",
            "intent_guidelines.ACTIVATE",
            "process_facts.can_prepare_now",
        ]
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)

    if i == "PLANS":
        # Planos: visão geral + CTA curto + posicionamento
        fields = base_fields + [
            "commercial_positioning",
            "pricing_behavior",
            "sales_pills.pricing_blurb",
            "sales_pills.cta_one_liners",
        ]
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)

    if i == "TRUST":
        fields = base_fields + ["ethical_guidelines", "product_boundaries", "objections.confianca"]
        return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)

    fields = base_fields + ["sales_pills.identity_blurb", "sales_pills.how_it_works_3steps", "sales_pills.how_it_works"]
    return _get_doc_fields("platform_kb/sales", fields, ttl_seconds=300)


# ==========================================================
# Observabilidade (DIFF 0): metadados do slice
# - Não altera comportamento, só registra o que já escolhemos carregar.
# - Importante para auditar "Firestore-first" em produção.
# ==========================================================
def _kb_slice_fields_for_intent(intent: str, *, segment: str = "") -> list[str]:
    """Replica a lista de campos do slice (por intent) sem ler Firestore.

    Usado apenas para logging/auditoria.
    """
    i = (intent or "OTHER").strip().upper()
    seg = (segment or "").strip().lower()
    base_fields = [
        "tone_rules",
        "behavior_rules",
        "brand_guardrails",
        "closing_guidance",
        "closing_styles",
        "value_props",
    ]

    if i == "PRICE":
        return base_fields + ["sales_pills.cta_one_liners"]

    if i == "ACTIVATE_SEND_LINK":
        return base_fields + [
            "process_facts.sla_setup",
            "process_facts.can_prepare_now",
            "process_facts.no_free_trial",
            "intent_guidelines.ACTIVATE",
            "closing_behaviors",
            "cta_variations",
            "sales_pills.cta_one_liners",
        ]

    if i == "WHAT_IS":
        return base_fields + [
            "sales_pills.identity_blurb",
            "sales_pills.how_it_works_3steps",
            "sales_pills.how_it_works",
            "identity_positioning",
            "value_in_action_blocks.scheduling_scene",
        ]

    if i == "DIFF":
        return base_fields + ["commercial_positioning", "product_boundaries", "plans.difference"]

    if i == "OPERATIONAL":
        fields = base_fields + [
            "behavior_rules",
            "brand_guardrails",
            "discovery_policy",
            "depth_policy",
            "operational_capabilities",
            "operational_flows",
            "operational_value_scenarios",
            "value_in_action_blocks.scheduling_scene",
            "value_in_action_blocks.services_quote_scene",
            "value_in_action_blocks.formal_quote_email_scene",
            "segment_pills.servicos.micro_scene",
        ]
        if seg:
            fields.append(f"segment_pills.{seg}.micro_scene")
            fields.append(f"segments.{seg}.one_question")
        return fields

    if i == "AGENDA":
        fields = base_fields + [
            "behavior_rules",
            "brand_guardrails",
            "operational_capabilities.scheduling_practice",
            "operational_flows.agenda_do_dia",
            "operational_flows.agendamento_completo",
            "value_in_action_blocks.scheduling_scene",
            "process_facts.dashboard_agenda",
            "process_facts.daily_email_digest",
        ]
        if seg:
            fields.append(f"segment_pills.{seg}.micro_scene")
            fields.append(f"segments.{seg}.one_question")
        return fields

    if i == "QUOTE":
        fields = base_fields + [
            "behavior_rules",
            "brand_guardrails",
            "operational_flows.orcamento_com_validacao",
            "operational_capabilities.quotes_practice",
            "value_in_action_blocks.services_quote_scene",
            "value_in_action_blocks.formal_quote_email_scene",
        ]
        if seg:
            fields.append(f"segment_pills.{seg}.micro_scene")
            fields.append(f"segments.{seg}.one_question")
        return fields

    if i == "CONTACTS":
        fields = base_fields + [
            "behavior_rules",
            "brand_guardrails",
            "operational_capabilities.services_practice",
            "operational_value_scenarios.whatsapp_organizado_sem_bagunça",
        ]
        if seg:
            fields.append(f"segment_pills.{seg}.micro_scene")
            fields.append(f"segments.{seg}.one_question")
        return fields

    if i == "VOICE":
        return base_fields + [
            "voice_pill.short_yes",
            "voice_pill.how_it_works",
            "voice_pill.boundaries",
            "voice_pill.next_step",
            "voice_positioning.core",
        ]

    if i == "TRUST":
        return base_fields + ["ethical_guidelines", "product_boundaries", "objections.confianca"]

    return base_fields + ["sales_pills.identity_blurb", "sales_pills.how_it_works_3steps", "sales_pills.how_it_works"]


def _pick_one(arr: Any) -> str:
    """Escolhe 1 string válida de uma lista, evitando vazar dict/list/JSON cru.
    Aceita:
    - str
    - dict com um campo textual conhecido (text/line/value/msg)
    Ignora qualquer outro tipo.
    """
    if not isinstance(arr, list) or not arr:
        return ""

    def _as_text(v: Any) -> str:
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, dict):
            for k in ("text", "line", "value", "msg"):
                vv = v.get(k)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
        return ""

    for x in arr:
        s = _as_text(x)
        if s:
            return s
    return ""

def _compose_sales_reply(
    *,
    intent: str,
    confidence: str,
    stt_text: str,
    reply_text: str,
    kb_context: dict,
    display_name: str | None = None,
    name_recently_used: bool = False,
    gratitude: str = "NONE",
):
    """
    Ajuste de comportamento vendedor (pós-intent):
    - IA decide intent / next_step antes.
    - Aqui garantimos resposta humana, rica e condutiva.
    """

    i = (intent or "OTHER").strip().upper()
    conf = (confidence or "").strip().lower()
    stt_lc = (stt_text or "").lower().strip()
    gr = (gratitude or "NONE").strip().upper()

    # Getter leve (dot path), sem depender de libs
    def _get(path: str, default: Any = "") -> Any:
        try:
            cur: Any = kb_context
            for p in (path or "").split("."):
                if not p:
                    continue
                if not isinstance(cur, dict):
                    return default
                cur = cur.get(p)
            return cur if cur is not None else default
        except Exception:
            return default

    has_greeting = any(
        k in stt_lc
        for k in ("bom dia", "boa tarde", "boa noite", "oi", "olá", "tudo bem", "feliz")
    )

    # --------------------------------------------------
    # 0) Empatia condicional (1 linha, só quando disparar trigger)
    # --------------------------------------------------
    empathy_line = ""
    try:
        triggers = _get("empathy_triggers", []) or []
        if isinstance(triggers, list) and triggers:
            if any(str(t).strip().lower() in stt_lc for t in triggers[:12]):
                empathy_line = "Entendi. Isso aí no WhatsApp cansa mesmo — bora deixar simples."
    except Exception:
        pass

    # Empatia mínima (fallback) — evita resposta “correta porém fria”
    # Só em intents operacionais, sem mexer em PRICE/WHAT_IS/ACTIVATE.
    # Determinístico e barato (sem random de verdade): escolhe pelo “peso” do texto.
    try:
        if (not empathy_line) and i in ("OPERATIONAL", "AGENDA", "PROCESS"):
            opts = [
                "Boa pergunta. Vou te explicar bem direto e sem enrolação.",
                "Entendi. Bora deixar isso simples e prático.",
                "Perfeito — vou te mostrar como fica no dia a dia, sem firula.",
            ]
            w = sum(ord(c) for c in (stt_text or "")) % max(1, len(opts))
            empathy_line = opts[int(w)]
    except Exception:
        pass

    # --------------------------------------------------
    # 0.25) Gratidão natural (IA sinaliza; 1 linha curta)
    # - Sem nome no texto (nome é só no ÁUDIO via gate do worker)
    # - Barato: só adiciona alguns caracteres
    # --------------------------------------------------
    gratitude_line = ""
    try:
        if gr == "HOLIDAY":
            gratitude_line = "Igualmente! 🙌"
        elif gr == "PRAISE":
            gratitude_line = "Valeu! 😄"
        elif gr == "THANKS":
            gratitude_line = "Tamo junto — valeu por chamar. 👊"
    except Exception:
        gratitude_line = ""

    # --------------------------------------------------
    # 0.5) Opener (tone_spark) — tempero, não base
    # --------------------------------------------------
    opener = ""
    try:
        spark = _get("tone_spark", {}) or {}
        if isinstance(spark, dict) and bool(spark.get("enabled")):
            do_not = spark.get("do_not_use_intents") or []
            blocked = isinstance(do_not, list) and i in [str(x).strip().upper() for x in do_not]
            if not blocked:
                opener = _pick_one(spark.get("openers") or [])
    except Exception:
        opener = ""

    # --------------------------------------------------
    # 0.6) Humor leve (vendedor do bem) — 1 toque no máximo
    # - Só quando a conversa está andando (conf != low)
    # - Nunca em PRICE puro (não “zoar” preço) nem em ACTIVATE/PROCESS (fluxo)
    # - Determinístico e barato (sem chamar IA)
    # --------------------------------------------------
    humor_line = ""
    try:
        if conf in ("high", "mid") and i not in ("PRICE", "ACTIVATE", "ACTIVATE_SEND_LINK", "PROCESS", "SLA"):
            pool = _get("tone_spark.humor_one_liners", []) or _get("humor_one_liners", []) or []
            if not isinstance(pool, list):
                pool = []
            # fallback seguro (curto, sem palhaçada)
            if not pool:
                pool = ["Sem menu maluco nem robô engessado 😄"]
            w = (sum(ord(c) for c in (stt_text or "")) + 7) % max(1, len(pool))
            humor_line = str(pool[int(w)] or "").strip()
            # trava: humor só se for realmente curto
            if humor_line and len(humor_line) > 70:
                humor_line = humor_line[:70].rstrip() + "…"
    except Exception:
        humor_line = ""

    # --------------------------------------------------
    # 1) OPENING POLICY — nunca responder seco a saudação
    # --------------------------------------------------
    if has_greeting and (i in ("WHAT_IS", "UNKNOWN") or conf == "low"):
        opening = (
            "Oi! Legal falar contigo 😄 "
            "Eu sou o MEI Robô — organizo o WhatsApp do teu negócio "
            "pra você atender clientes, agenda e pedidos sem correria."
        )
        if gratitude_line:
            opening = (gratitude_line + " " + opening).strip()

        # Texto NÃO deve incluir o nome por padrão (nome é aplicado só no ÁUDIO pelo worker).
        ask_name = "Como posso te chamar?" if not display_name else "Quer que eu te mostre como funciona na prática?"

        return f"{opening} {ask_name}".strip()

    # --------------------------------------------------
    # 1.5) Low confidence — nunca responder com “frasezinha”
    # --------------------------------------------------
    if conf == "low":
        if display_name:
            # Sem nome no texto; o gate do áudio decide.
            base = (
                "Peguei a ideia. Só pra eu te orientar certo: você quer usar mais pra agenda, pedidos ou orçamento?"
            )
            return (f"{gratitude_line} {base}".strip() if gratitude_line else base)
        base2 = "Show. Só me diz uma coisa rapidinho: você quer usar mais pra agenda, pedidos ou orçamento?"
        return (f"{gratitude_line} {base2}".strip() if gratitude_line else base2)


    # --------------------------------------------------
    # 2) Intents CORE nunca caem em qualifier genérico
    # --------------------------------------------------
    if i == "AGENDA":
        base = (
            "Funciona assim: o cliente chama no WhatsApp, o robô pergunta o serviço, dia e horário "
            "e já te entrega o agendamento confirmadinho."
        )
        extra = (
            "Se o cliente ligar, você só fala “me chama no WhatsApp” e o robô assume dali."
        )
        follow = "No teu caso é mais horário marcado ou atendimento por ordem?"
        core = " ".join([x for x in (base, extra, follow) if x]).strip()
        parts = [p for p in (gratitude_line, opener, empathy_line, humor_line, core) if p]
        return "\n".join(parts).strip()

    if i == "PRICE":
        # reply_text já vem com preço do cérebro + Firestore
        benefit = "Isso já inclui atendimento automático e organização das conversas."
        core = f"{reply_text.strip()} {benefit}".strip()
        parts = [p for p in (gratitude_line, opener, empathy_line, humor_line, core) if p]
        # Cenário curtinho como ancoragem (policy: preço direto + 1 cenário curto)
        try:
            scenarios = _get("operational_value_scenarios", {}) or {}
            idx = _get("scenario_index.for_intent_price", []) or []
            if isinstance(scenarios, dict) and isinstance(idx, list) and idx:
                k = str(idx[0]).strip()
                sline = str(scenarios.get(k) or "").strip()
                if sline:
                    if len(sline) > 180:
                        sline = sline[:180].rstrip() + "…"
                    parts.append(sline)
        except Exception:
            pass
        # Closer vendedor (sem empurrar)
        closer = ""
        try:
            closer = _pick_one(_get("tone_spark.closers", []) or []) or ""
            if not closer:
                cs = _get("closing_styles", {}) or {}
                if isinstance(cs, dict):
                    closer = str(cs.get("suave") or "").strip()
        except Exception:
            closer = ""
        if closer:
            parts.append(closer)
        out = "\n".join([x for x in parts if x]).strip()
        return out

    if i == "WHAT_IS":
        base = reply_text.strip()
        enrich = (
            "Na prática, ele responde clientes, organiza pedidos e agenda "
            "enquanto você foca no trabalho."
        )
        core = f"{base} {enrich}".strip()
        parts = [p for p in (gratitude_line, opener, empathy_line, humor_line, core) if p]
        # Closer leve (opcional)
        closer = _pick_one(_get("tone_spark.closers", []) or []) or ""
        if closer:
            parts.append(closer)
        out = "\n".join([x for x in parts if x]).strip()
        return out

    # --------------------------------------------------
    # 3) Guardrail — resposta curta demais = enriquecer
    # --------------------------------------------------
    if reply_text and len(reply_text.strip()) < 80:
        tail = "Quer que eu te dê um exemplo real de como isso funciona no dia a dia?"
        core = f"{reply_text.strip()} {tail}".strip()
        parts = [p for p in (gratitude_line, opener, empathy_line, humor_line, core) if p]
        return "\n".join(parts).strip()

    # --------------------------------------------------
    # 4) Uso do nome (uma vez, sem insistir)
    # --------------------------------------------------
    # Sem nome no texto por padrão (nome é aplicado só no ÁUDIO pelo worker).
    if False:
        pass

    # --------------------------------------------------
    # 5) Cenário (1 por resposta, no máximo) + fechamento
    # --------------------------------------------------
    scenario_line = ""
    try:
        scenarios = _get("operational_value_scenarios", {}) or {}
        idx = _get("scenario_index.for_intent_operational_flow", []) or []
        if i in ("OPERATIONAL", "AGENDA") and isinstance(scenarios, dict) and isinstance(idx, list) and idx:
            k = str(idx[0]).strip()
            scenario_line = str(scenarios.get(k) or "").strip()
    except Exception:
        scenario_line = ""

    closer = ""
    try:
        closer = _pick_one(_get("tone_spark.closers", []) or []) or ""
        if not closer:
            cs = _get("closing_styles", {}) or {}
            if isinstance(cs, dict):
                closer = str(cs.get("suave") or "").strip()
        if not closer:
            closer = _pick_one(_get("closing_guidance", []) or []) or ""
    except Exception:
        closer = ""

    parts = [p for p in (gratitude_line, opener, empathy_line, humor_line, reply_text.strip()) if p]
    if scenario_line and i not in ("PROCESS", "SLA"):
        if len(scenario_line) > 180:
            scenario_line = scenario_line[:180].rstrip() + "…"
        parts.append(scenario_line)
    if closer and (closer.lower() not in (reply_text or "").lower()):
        # Hard close: não terminar com pergunta em ACTIVATE/PROCESS
        if i in ("ACTIVATE", "ACTIVATE_SEND_LINK", "PROCESS") and closer.endswith("?"):
            closer = closer.rstrip("?").rstrip() + "."
        parts.append(closer)

    out = "\n".join([x for x in parts if x]).strip()

    # 2–5 linhas (tone_rules): corta excesso sem destruir o núcleo
    try:
        lines = [x.strip() for x in out.split("\n") if x.strip()]
        if len(lines) > 5:
            out = "\n".join(lines[:5]).strip()
    except Exception:
        pass

    return out


def _kb_get_by_path(data: Any, path: str) -> Any:
    """Acessa dot path em dicts. Best-effort."""
    try:
        cur: Any = data
        for part in (path or "").split("."):
            if not part:
                continue
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur
    except Exception:
        return None


def _kb_path_has_value(kb_slice: Dict[str, Any], path: str) -> bool:
    """Define 'valor presente' de forma barata (sem heurística pesada)."""
    v = _kb_get_by_path(kb_slice or {}, path)
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, tuple)):
        return any(bool(str(x).strip()) for x in v[:5])
    if isinstance(v, dict):
        return bool(v)
    return True



def _kb_contract_id(intent: str, *, segment: str = "") -> str:
    """ID estável do contrato mínimo de KB por intent (para logs/auditoria)."""
    i = (intent or "OTHER").strip().upper()
    seg = (segment or "").strip().lower()
    return f"sales_kb_contract:{seg}:{i}:v1"


def _kb_contract_missing_groups(kb_slice: Dict[str, Any], intent: str, *, segment: str = "") -> list[str]:
    """Retorna lista de grupos (string) que falharam no contrato."""
    missing: list[str] = []
    groups = _kb_contract_required_groups(intent, segment=segment)
    for g in groups:
        ok = False
        for p in g:
            if _kb_path_has_value(kb_slice, p):
                ok = True
                break
        if not ok:
            missing.append("|".join(list(g)))
    return missing

def _compose_box_reply(
    *,
    box_intent: str,
    confidence: str,
    box_data: Dict[str, Any],
    prices: Dict[str, str],
    user_text: str,
    name: str,
    segment: str,
    gratitude: str = "NONE",
) -> Tuple[str, str]:
    i = (box_intent or "OTHER").strip().upper()
    nm = (name or "").strip()
    seg = (segment or "").strip()

    def _get(path: str) -> Any:
        cur: Any = box_data
        for p in (path or "").split("."):
            if not p:
                continue
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur.get(p)
        return cur

    def _scene_to_lines(val: Any) -> Tuple[str, str, str]:
        """
        Normaliza value_in_action_blocks.scheduling_scene:
        Pode ser dict {scene:[], optional_questions:[], next_step_hint:""}
        ou string/list.
        Retorna (line1, line2, line3) já “faláveis”.
        """
        line1 = ""
        line2 = ""
        line3 = ""

        if isinstance(val, dict):
            # 1) scene: lista de passos
            sc = val.get("scene") or val.get("micro_scene") or val.get("steps") or val.get("text") or ""
            if isinstance(sc, list):
                sc_items = [str(x).strip() for x in sc if str(x).strip()]
                if sc_items:
                    # 1 frase curta (não vira texto gigante)
                    line1 = sc_items[0]
                    if len(sc_items) >= 2:
                        line2 = sc_items[1]
            elif isinstance(sc, str):
                line1 = sc.strip()

            # 2) next_step_hint
            nsh = val.get("next_step_hint") or val.get("hint") or ""
            if isinstance(nsh, str) and nsh.strip():
                # vira complemento curto
                if not line2:
                    line2 = nsh.strip()
                else:
                    # se já tem line2, joga no fim
                    line2 = (line2 + " " + nsh.strip()).strip()

            # 3) pergunta opcional
            oq = val.get("optional_questions") or []
            if isinstance(oq, list):
                oq_items = [str(x).strip() for x in oq if str(x).strip()]
                if oq_items:
                    line3 = oq_items[0]

        elif isinstance(val, list):
            items = [str(x).strip() for x in val if str(x).strip()]
            if items:
                line1 = items[0]
                if len(items) >= 2:
                    line2 = items[1]
        elif isinstance(val, str):
            line1 = val.strip()

        # Fallback bom (nunca devolve dict)
        if not line1:
            line1 = "Funciona assim: o cliente chama no WhatsApp, o robô pergunta o serviço, dia e horário, confirma e te manda tudo organizadinho."
        if not line3:
            line3 = "No teu caso é mais horário marcado ou atendimento por ordem?"
        return (line1.strip(), line2.strip(), line3.strip())

    if i == "AGENDA":
        # AGENDA (vendedor humano):
        # - 1 abertura curta (tone_spark)
        # - 1 micro-exemplo prático (KB)
        # - 1 pergunta curta (qualificação leve)
        opener = _pick_one(_get("tone_spark.openers") or [])

        if not opener:
            opener = "Tranquilo. Vou direto ao ponto."

        # Preferir texto pronto “falável”; fallback para prática/fluxo
        agenda_text = (
            str(_get("value_in_action_blocks.scheduling_scene_text") or "").strip()
            or str(_get("operational_capabilities.scheduling_practice") or "").strip()
            or str(_get("operational_flows.agendamento_completo") or "").strip()
        )

        # 1 ancoragem curta (benefício)
        anchor = "Fica tudo registrado por escrito, sem você ficar caçando conversa."

        # 1 pergunta curta (segmento se tiver; senão genérica)
        seg_q = ""
        try:
            if seg:
                seg_q = _pick_one(_get(f"segments.{seg}.one_question") or [])
        except Exception:
            seg_q = ""
        if not seg_q:
            seg_q = "No teu caso é mais horário marcado ou por ordem?"

        # Ordem pensada pro áudio:
        # - opener + anchor + pergunta vêm cedo (não podem ser cortados pelo shorten)
        # - bloco mais longo vem depois
        parts = [x for x in (opener, anchor, seg_q, agenda_text) if str(x or "").strip()]
        return (" ".join(parts).strip(), "NONE")



    if i == "PRICE":
        starter = (prices.get("starter") or "").strip()
        plus = (prices.get("starter_plus") or "").strip()
        cta = ""
        try:
            cta = _pick_one(_get("sales_pills").get("cta_one_liners") if isinstance(_get("sales_pills"), dict) else _get("sales_pills.cta_one_liners"))
        except Exception:
            cta = _pick_one(_get("sales_pills.cta_one_liners") or [])

        if not starter or not plus:
            line1 = "É assinatura mensal (paga). Os valores certinhos ficam no site."
            line2 = f"{MEI_ROBO_CADASTRO_URL}"
            line3 = "Obs: ativação só com CNPJ."
            _txt = "\n".join([x for x in (line1, line2, line3) if x]).strip()
        _txt = _compose_sales_reply(intent=i, confidence=confidence, stt_text=user_text, reply_text=_txt, kb_context=box_data, display_name=(nm or None), name_recently_used=False, gratitude=gratitude)
        return (_txt, "SEND_LINK")

        prefix = ""  # sem nome no texto (apenas no áudio)

        line1 = f"{prefix}hoje é {starter}/mês (Starter) ou {plus}/mês (Starter+).".strip()
        line2 = "A diferença é só a memória."
        line3 = "Obs: ativação só com CNPJ."
        line4 = (cta or "").strip()
        return ("\n".join([x for x in (line1, line2, line3, line4) if x]).strip(), "NONE")

    if i == "ACTIVATE_SEND_LINK":
        sla = str(_get("process_facts.sla_setup") or "até 7 dias úteis").strip()
        can_now = str(_get("process_facts.can_prepare_now") or "").strip()
        cta = _pick_one(_get("cta_variations") or []) or _pick_one(_get("sales_pills.cta_one_liners") or [])
        line1 = f"Fechado — é por aqui pra assinar e começar: {MEI_ROBO_CADASTRO_URL}".strip()
        line2 = f"Prazo: {sla}.".strip()
        line3 = can_now
        line4 = (cta or "").strip()
        _txt = "\n".join([x for x in (line1, line2, line3, line4) if x]).strip()
        _txt = _maybe_prefix_name_in_text(_txt, nm)
        return (_txt, "SEND_LINK")


    if i == "SLA":
        # SLA: responder o prazo (fato) + 1 pergunta prática (se precisar)
        sla = str(_get("process_facts.sla_setup") or "").strip()
        can_now = str(_get("process_facts.can_prepare_now") or "").strip()
        if not sla:
            sla = "até 7 dias úteis para número virtual + configuração concluída"
        line1 = f"Hoje o prazo é {sla}."
        line2 = (can_now or "").strip()
        line3 = "Se quiser, eu te mando o link pra criar a conta e já deixar tudo pronto."
        _txt = "\n".join([x for x in (line1, line2, line3) if x]).strip()
        _txt = _compose_sales_reply(intent=i, confidence=confidence, stt_text=user_text, reply_text=_txt, kb_context=box_data, display_name=(nm or None), name_recently_used=False, gratitude=gratitude)
        return (_txt, "SEND_LINK")

    if i == "PROCESS":
        # PROCESS: explicar caminho (sem triagem genérica) e ancorar em fatos do KB
        billing = str(_get("process_facts.billing_model") or "").strip()
        sla = str(_get("process_facts.sla_setup") or "").strip()
        can_now = str(_get("process_facts.can_prepare_now") or "").strip()
        if not billing:
            billing = "assinatura mensal (paga)"
        if not sla:
            sla = "até 7 dias úteis para número virtual + configuração concluída"
        line1 = f"É {billing}."
        line2 = "O fluxo é: criar a conta → preencher o básico (serviços/rotina) → ativação."
        line3 = f"Depois disso, o WhatsApp fica pronto em {sla}."
        line4 = (can_now or "").strip()
        line5 = "Quer que eu te mande o link pra você já começar por lá?"
        _txt = "\n".join([x for x in (line1, line2, line3, line4, line5) if x]).strip()
        _txt = _compose_sales_reply(intent=i, confidence=confidence, stt_text=user_text, reply_text=_txt, kb_context=box_data, display_name=(nm or None), name_recently_used=False, gratitude=gratitude)
        return (_txt, "SEND_LINK")

    if i == "WHAT_IS":
        blurb = str(_get("sales_pills.identity_blurb") or "").strip() or "Eu organizo o WhatsApp do teu negócio e tiro o caos do atendimento."
        steps = _get("sales_pills.how_it_works_3steps")
        if not isinstance(steps, list) or not steps:
            steps = _get("sales_pills.how_it_works")
        s1 = _pick_one(steps) if isinstance(steps, list) else ""
        s2 = str(steps[1]).strip() if isinstance(steps, list) and len(steps) >= 2 else ""
        prefix = ""  # sem nome no texto (apenas no áudio)

        opener = _pick_one(_get("tone_spark.openers") or [])
        if opener:
            opener = opener.strip()
        else:
            opener = "Oi! Legal falar contigo 😄"

        greet = ""
        t = (user_text or "").lower()
        if any(x in t for x in ("bom dia", "boa tarde", "boa noite", "feliz", "tudo bem", "oi", "olá", "ola")):
            greet = opener
        line1 = (((prefix if not greet else "") + blurb).strip())
        line2 = "Como funciona (bem direto):" if (s1 or s2) else ""
        line3 = (f"• {s1}" if s1 else "")
        line4 = (f"• {s2}" if s2 else "")
        # Exemplo prático (Firestore): 1 micro-cena curta para não ficar "robótico".
        scene_val = _get("value_in_action_blocks.scheduling_scene")
        dl1, dl2, _dq = _scene_to_lines(scene_val)
        demo1 = (f"Exemplo rápido (agenda):\n• {dl1}").strip() if dl1 else ""
        demo2 = (f"• {dl2}").strip() if dl2 else ""
        line5 = "Quer que eu te mostre também um exemplo de orçamento, ou você quer ver como fica a agenda?"
        _txt = "\n".join([x for x in (greet, line1, line2, line3, line4, demo1, demo2, line5) if x]).strip()
        _txt = _compose_sales_reply(intent=i, confidence=confidence, stt_text=user_text, reply_text=_txt, kb_context=box_data, display_name=(nm or None), name_recently_used=False, gratitude=gratitude)
        return (_txt, "NONE")

    if i == "DIFF":
        pos = str(_get("commercial_positioning") or "").strip()
        bounds = _get("product_boundaries")
        one_bound = _pick_one(bounds) if isinstance(bounds, list) else ""
        diff = str(_get("plans.difference") or "").strip()
        prefix = ""  # sem nome no texto (apenas no áudio)

        line1 = (prefix + (pos or "A diferença é bem simples: o plano muda a memória disponível.")).strip()
        line2 = (diff or "").strip()
        line3 = (one_bound or "").strip()
        line4 = "Se quiser, eu te digo o melhor pro teu caso em 1 pergunta."
        return ("\n".join([x for x in (line1, line2, line3, line4) if x]).strip(), "NONE")

    if i == "OPERATIONAL":
        t = (user_text or "").lower()
        scene = None
        if "agenda" in t or "agend" in t or "hor" in t:
            scene = _get("value_in_action_blocks.scheduling_scene")
        elif "email" in t or "e-mail" in t:
            scene = _get("value_in_action_blocks.formal_quote_email_scene")
        else:
            scene = _get("value_in_action_blocks.services_quote_scene")

        scene_line = ""
        if isinstance(scene, dict):
            sc = scene.get("scene") or scene.get("micro_scene") or scene.get("text") or ""
            if isinstance(sc, list):
                scene_line = " → ".join([str(x).strip() for x in sc if str(x).strip()])[:380]
            else:
                scene_line = str(sc).strip()[:380]
        elif isinstance(scene, list):
            scene_line = " → ".join([str(x).strip() for x in scene if str(x).strip()])[:380]
        elif isinstance(scene, str):
            scene_line = scene.strip()[:380]

        seg_ms = ""
        if seg:
            seg_ms = str(_get(f"segment_pills.{seg.lower()}.micro_scene") or "").strip()
        if not seg_ms:
            seg_ms = str(_get("segment_pills.servicos.micro_scene") or "").strip()

        q = ""
        if seg:
            q = str(_get(f"segments.{seg.lower()}.one_question") or "").strip()

        prefix = ""  # sem nome no texto (apenas no áudio)

        line1 = (prefix + "na prática fica assim:").strip()
        line2 = scene_line or seg_ms
        line3 = "Se quiser, eu te explico com um exemplo bem do teu tipo de negócio em 1 pergunta."
        # Vibração de vendedor (leve): transmite “isso resolve o dia a dia”
        line_vibra = "Isso costuma reduzir bem a correria e evita desencontro com cliente."
        return ("\n".join([x for x in (line1, line2, line3, line_vibra) if x]).strip(), "NONE")

    if i == "VOICE":
        yes = str(_get("voice_pill.short_yes") or "Sim." ).strip()
        how = str(_get("voice_pill.how_it_works") or "Você grava a voz na configuração e o robô passa a responder em áudio com ela.").strip()
        bounds = str(_get("voice_pill.boundaries") or "Sem inventar coisas e sem prometer milagre — é voz, não mágica 😄").strip()
        nxt = str(_get("voice_pill.next_step") or "Quer que eu te mande o link pra criar a conta e ver o passo-a-passo?").strip()
        prefix = ""  # sem nome no texto (apenas no áudio)

        return ("\n".join([x for x in ((prefix + yes).strip(), how, bounds, nxt) if x]).strip(), "NONE")

    if i == "TRUST":
        conf = ""
        try:
            conf = str(_get("objections.confianca") or "").strip()
        except Exception:
            conf = ""
        bounds = _get("product_boundaries")
        one_bound = _pick_one(bounds) if isinstance(bounds, list) else ""
        line1 = (conf or "Não é golpe 🙂 É uma plataforma pra organizar teu atendimento no WhatsApp.").strip()
        line2 = (one_bound or "").strip()
        line3 = "Se quiser, eu te mando o link oficial pra você ver tudo por você mesmo."
        line4 = MEI_ROBO_CADASTRO_URL
        _txt = "\n".join([x for x in (line1, line2, line3, line4) if x]).strip()
        _txt = _maybe_prefix_name_in_text(_txt, nm)
        return (_txt, "SEND_LINK")
    _txt = "Me diz só o que você quer resolver primeiro: preço, voz, ou um exemplo prático?"
    _txt = _maybe_prefix_name_in_text(_txt, nm)
    return (_txt.strip(), "NONE")


def _sales_box_handle_turn(text_in: str, st: Dict[str, Any]) -> Optional[str]:
    if _sales_box_mode() != "v1":
        return None

    user_text = (text_in or "").strip()
    if not user_text:
        return None
    # ==========================
    # Contadores de sessão
    # ==========================
    try:
        st["turns"] = int(st.get("turns") or 0) + 1
    except Exception:
        st["turns"] = 1

    try:
        st["ai_calls"] = int(st.get("ai_calls") or 0)
    except Exception:
        st["ai_calls"] = 0

    try:
        st["tts_calls"] = int(st.get("tts_calls") or 0)
    except Exception:
        st["tts_calls"] = 0


    name = str(st.get("name") or "").strip()
    segment = str(st.get("segment") or "").strip()

    if _is_smalltalk(user_text):
        st["understand_source"] = "smalltalk"
        st["plan_intent"] = "SMALLTALK"
        st["plan_next_step"] = "NONE"
        st["understand_intent"] = "SMALLTALK"
        st["understand_confidence"] = "high"
        return _smalltalk_bridge(user_text)

    dec = sales_box_decider(user_text=user_text) or {}
    intent = str(dec.get("intent") or "OTHER").strip().upper()
    conf = float(dec.get("confidence") or 0.55)
    needs = bool(dec.get("needs_clarification"))
    q = str(dec.get("clarifying_question") or "").strip()
    ns = str(dec.get("next_step") or "NONE").strip().upper()
    try:
        st["gratitude"] = str(dec.get("gratitude") or "NONE").strip().upper()
    except Exception:
        st["gratitude"] = "NONE"

    # ==========================================================
    # Pergunta esclarecedora (regra atualizada):
    # - liberada
    # - mas limitada por contato (evita ficar "perguntando demais")
    # ==========================================================
    try:
        used = int(st.get("clarify_used") or 0)
    except Exception:
        used = 0
    if needs:
        if used >= LEAD_MAX_CLARIFY_QS:
            # já perguntou o bastante; segue sem perguntar (melhor esforço)
            needs = False
            q = ""
        else:
            st["clarify_used"] = used + 1


    # ==========================
    # OTHER streak
    # ==========================
    try:
        if intent == "OTHER":
            st["other_streak"] = int(st.get("other_streak") or 0) + 1
        else:
            st["other_streak"] = 0
    except Exception:
        st["other_streak"] = 0

    # Se OTHER mas há contexto suficiente, responde direto (WHAT_IS)
    try:
        if intent == "OTHER":
            tlen = len((user_text or "").strip())
            has_q = "?" in (user_text or "")
            if tlen >= 40 or has_q:
                intent = "WHAT_IS"
                st["understand_source"] = "other_promoted_to_whatis"
    except Exception:
        pass

    # ==========================
    # Cinturão de excesso
    # ==========================
    try:
        if (
            st.get("turns", 0) > MAX_TURNS_PER_SESSION or
            st.get("ai_calls", 0) > MAX_AI_CALLS_PER_SESSION or
            st.get("tts_calls", 0) > MAX_TTS_PER_SESSION
        ):
            st["excess_level"] = "HARD"
        elif st.get("other_streak", 0) >= MAX_OTHER_STREAK:
            st["excess_level"] = "SOFT"
        else:
            st["excess_level"] = "NORMAL"
    except Exception:
        st["excess_level"] = "NORMAL"
    if st.get("excess_level") == "HARD":
        msgs = [
            "Pra não ficar repetindo respostas por aqui, concentrei tudo no site.\\n👉 www.meirobo.com.br",
            "Aqui já deu pra passar a visão geral 🙂\\nAs infos completas estão em:\\nwww.meirobo.com.br",
            "Pra seguir sem confusão, o próximo passo é direto pelo site:\\nwww.meirobo.com.br",
            "A partir daqui, o melhor caminho é pelo site mesmo:\\nwww.meirobo.com.br",
        ]

        # Budget guard HARD: não é "fallback burro" — é política de custo/loop.
        # Mantém rastreabilidade clara no Firestore.
        try:
            st["understand_source"] = "budget_guard"
            st["understand_intent"] = str(intent or "OTHER").strip().upper()
            st["understand_confidence"] = "low"
            st["plan_intent"] = str(intent or "OTHER").strip().upper()
            st["plan_next_step"] = "SEND_LINK"
        except Exception:
            pass
        try:
            idx = int(st.get("fallback_idx") or 0) % len(msgs)
            st["fallback_idx"] = idx + 1
            return msgs[idx]
        except Exception:
            return msgs[0]

    # ==========================================================
    # GUARD (produto): evitar SEND_LINK prematuro
    # - Se o lead NÃO pediu link/site/assinar explicitamente, não manda link "do nada"
    # - Mantém SEND_LINK para intents naturalmente de fechamento (ACTIVATE/PRICE/PROCESS/SLA)
    # ==========================================================
    try:
        if ns == "SEND_LINK" and intent in ("AGENDA", "OPERATIONAL", "WHAT_IS"):
            if not _is_link_request(user_text):
                ns = "NONE"
    except Exception:
        pass

    st["understand_source"] = "box_decider"
    st["plan_intent"] = intent
    st["plan_next_step"] = ns
    st["understand_intent"] = intent
    st["understand_confidence"] = ("high" if conf >= 0.80 else ("mid" if conf >= 0.55 else "low"))
    st["understand_next_step"] = ns

    if needs and q:
        q = _strip_generic_question_ending(q)
        q = _limit_questions(q, max_questions=1)
        return q

    kb_slice = _kb_slice_for_box(intent if intent != "OTHER" else "OTHER", segment=segment) or {}
    # ==========================
    # Firestore-first (KB): carrega slice + valida contrato mínimo por intent
    # ==========================
    try:
        st["kb_doc_path"] = "platform_kb/sales"
        st["kb_slice_fields"] = _kb_slice_fields_for_intent(intent, segment=segment)
        st["kb_slice_size_chars"] = int(len(json.dumps(kb_slice, ensure_ascii=False))) if kb_slice else 0

        # contrato mínimo: deve fechar antes de sair resposta "boa"
        missing_groups = _kb_contract_missing_groups(kb_slice, intent, segment=segment) if kb_slice else list(st.get("kb_slice_fields") or [])
        missing_flat: list[str] = []
        try:
            for g in (missing_groups or []):
                if isinstance(g, (list, tuple)):
                    missing_flat.extend([str(x) for x in g])
                else:
                    missing_flat.append(str(g))
        except Exception:
            missing_flat = []

        st["kb_contract_id"] = _kb_contract_id(intent, segment=segment)
        st["kb_required_ok"] = (len(missing_groups or []) == 0)
        st["kb_missing_fields"] = missing_flat
        st["kb_miss_reason"] = "" if st["kb_required_ok"] else "contract_missing"
        st["kb_used"] = bool(st["kb_required_ok"] and bool(kb_slice))

        # Se contrato falhar, cai em fallback específico por intent (1 pergunta prática)
        if not bool(st["kb_required_ok"]):
            fb = _fallback_by_intent(intent, name=name or "", user_text=user_text or "")
            return fb
    except Exception:
        # não quebra fluxo; apenas deixa rastreável
        st["kb_miss_reason"] = str(st.get("kb_miss_reason") or "kb_probe_failed")

    prices = _get_display_prices(ttl_seconds=180) or {}
    reply, next_step = _compose_box_reply(
        box_intent=intent,
        confidence=str(st.get("understand_confidence") or ""),
        box_data=kb_slice,
        prices=prices,
        user_text=user_text,
        name=name,
        segment=segment,
        gratitude=str(st.get("gratitude") or "NONE"),
    )
    reply = (reply or "").strip()
    if not reply:
        return None

    if next_step == "SEND_LINK":
        st["plan_next_step"] = "SEND_LINK"
        st["understand_next_step"] = "SEND_LINK"

    if intent == "OTHER" and conf < 0.50:
        try:
            other_streak = int(st.get("other_streak") or 0)
            used = bool(st.get("extra_clarify_used"))
        except Exception:
            other_streak = 0
            used = False

        if other_streak >= 2 and not used:
            try:
                st["extra_clarify_used"] = True
                st["ai_calls"] += 1
                q = (_ai_sales_answer(
                    user_text=user_text,
                    intent_hint="NEEDS_CLARIFICATION",
                    state=st,
                ) or "").strip()
                if q:
                    return _limit_questions(q, 1)
            except Exception:
                pass

        return "Só pra eu te atender certo: você quer preço, voz, ou um exemplo prático?"



    reply = _apply_anti_loop(st, reply, name=name, segment=segment, goal=str(st.get("goal") or "").strip(), user_text=user_text)
    reply = _limit_questions(reply, max_questions=0 if next_step == "SEND_LINK" else 1)
    return reply.strip()


# =========================
# Helpers: parsing simples
# =========================

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _strip_accents(s: str) -> str:
    try:
        s = str(s or "")
        nfkd = unicodedata.normalize("NFKD", s)
        return "".join([c for c in nfkd if not unicodedata.combining(c)])
    except Exception:
        return str(s or "")

def _norm_alias(s: str) -> str:
    """
    Normalização "Brasil-raiz" pra alias:
    - lowercase
    - sem acento
    - remove pontuação básica
    - colapsa espaços
    """
    try:
        t = _strip_accents(str(s or "").lower())
        t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)  # remove pontuação
        t = re.sub(r"\s+", " ", t).strip()
        return t
    except Exception:
        return _norm(s or "")

def _sha1_short(s: str, n: int = 16) -> str:
    try:
        h = hashlib.sha1((s or "").encode("utf-8", errors="ignore")).hexdigest()
        return h[: max(8, int(n or 16))]
    except Exception:
        return ""

def _now_epoch() -> int:
    try:
        return int(time.time())
    except Exception:
        return 0

def _fs_cache_get(doc_id: str) -> Optional[Dict[str, Any]]:
    """
    Cache mínimo no Firestore (platform_response_cache).
    Regra: ignora se expirado (expiresAt < now epoch).
    Best-effort: nunca quebra fluxo.
    """
    try:
        if not doc_id:
            return None
        from firebase_admin import firestore as fb_firestore  # type: ignore
        client = _fs_client()
        ref = client.collection(PLATFORM_RESPONSE_CACHE_COLLECTION).document(doc_id)
        doc = ref.get()
        if not doc or not doc.exists:
            return None
        data = doc.to_dict() or {}
        if not isinstance(data, dict):
            return None
        exp = data.get("expiresAt")
        try:
            exp_i = int(exp)
        except Exception:
            exp_i = 0
        if exp_i and exp_i < _now_epoch():
            return None
        return data
    except Exception:
        return None

def _fs_cache_set(doc_id: str, payload: Dict[str, Any], *, ttl_seconds: int) -> None:
    try:
        if not doc_id or not isinstance(payload, dict):
            return
        from firebase_admin import firestore as fb_firestore  # type: ignore
        client = _fs_client()
        exp = _now_epoch() + int(ttl_seconds or 0)
        obj = dict(payload)
        obj["expiresAt"] = int(exp)
        obj["createdAt"] = fb_firestore.SERVER_TIMESTAMP
        client.collection(PLATFORM_RESPONSE_CACHE_COLLECTION).document(doc_id).set(obj, merge=True)
    except Exception:
        pass

def _intent_cache_key(text_in: str) -> str:
    base = _norm_alias(text_in)[:240]
    return f"sales_intent:{_sha1_short(base, 20)}"

def _kb_slice_cache_key(intent: str, segment: str = "") -> str:
    i = (intent or "OTHER").strip().upper()
    seg = (segment or "").strip().lower()[:32]
    return f"kb_slice:{i}:{seg or 'na'}"

_ALIAS_MEM_CACHE: Dict[str, Any] = {}
_ALIAS_MEM_AT: float = 0.0
_ALIAS_MEM_TTL: int = int(os.getenv("SALES_ALIAS_MEM_TTL_SECONDS", "60") or "60")

def _load_alias_config_and_enabled_items() -> Tuple[Dict[str, Any], list]:
    """
    Lê platform_kb_action_maps/aliases_sales e lista items enabled=true.
    Cache curto em memória pra reduzir custo.
    """
    global _ALIAS_MEM_CACHE, _ALIAS_MEM_AT
    now = time.time()
    if isinstance(_ALIAS_MEM_CACHE, dict) and _ALIAS_MEM_CACHE and (now - float(_ALIAS_MEM_AT or 0.0)) < float(_ALIAS_MEM_TTL or 0):
        cfg = _ALIAS_MEM_CACHE.get("cfg") or {}
        items = _ALIAS_MEM_CACHE.get("items") or []
        return (cfg if isinstance(cfg, dict) else {}, items if isinstance(items, list) else [])

    cfg: Dict[str, Any] = {}
    items: list = []
    try:
        from firebase_admin import firestore as fb_firestore  # type: ignore
        client = _fs_client()
        parts = [p for p in PLATFORM_ALIAS_DOC.split("/") if p]
        if len(parts) >= 2:
            doc = client.collection(parts[0]).document(parts[1]).get()
            if doc and doc.exists:
                cfg = doc.to_dict() or {}
        # items enabled
        col = client.collection(parts[0]).document(parts[1]).collection("items")
        try:
            qs = col.where("enabled", "==", True).stream()
        except Exception:
            qs = col.stream()
        for d in qs:
            try:
                dd = d.to_dict() or {}
                if not isinstance(dd, dict):
                    continue
                if dd.get("enabled") is not True:
                    continue
                phrase = str(dd.get("phrase") or "").strip()
                if not phrase:
                    continue
                items.append(dd)
            except Exception:
                continue
    except Exception:
        cfg = {}
        items = []

    try:
        _ALIAS_MEM_CACHE = {"cfg": cfg, "items": items}
        _ALIAS_MEM_AT = now
    except Exception:
        pass
    return (cfg if isinstance(cfg, dict) else {}, items if isinstance(items, list) else [])

def _alias_lookup(text_in: str) -> Optional[Dict[str, Any]]:
    """
    Match simples:
    - exato por phrase normalizada
    - ou "contém" (phrase curta dentro do texto) quando phrase >= 4 chars
    """
    t = _norm_alias(text_in)
    if not t:
        return None
    _cfg, enabled_items = _load_alias_config_and_enabled_items()
    if not enabled_items:
        return None
    # tenta exato primeiro
    for it in enabled_items:
        try:
            ph = _norm_alias(it.get("phrase") or "")
            if ph and ph == t:
                return it
        except Exception:
            continue
    # fallback: contém
    for it in enabled_items:
        try:
            ph = _norm_alias(it.get("phrase") or "")
            if not ph or len(ph) < 4:
                continue
            if ph in t:
                return it
        except Exception:
            continue
    return None

def _alias_candidate_allowed(text_in: str, max_len: int) -> bool:
    """
    Auto-learn só pra frase curta e "limpa":
    - <= max_phrase_len
    - sem URL
    - sem números (reduz alias errado)
    """
    try:
        raw = str(text_in or "").strip()
        if not raw:
            return False
        if len(raw) > int(max_len or 0):
            return False
        if _has_url(raw):
            return False
        if re.search(r"\d", raw):
            return False
        return True
    except Exception:
        return False

def _alias_snippet(text: str, max_len: int = 120) -> str:
    try:
        t = str(text or "").strip()
        if not t:
            return ""
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) <= int(max_len or 120):
            return t
        return t[: max(0, int(max_len or 120) - 1)].rstrip() + "…"
    except Exception:
        return ""

def _alias_word_count(phrase: str) -> int:
    try:
        # reaproveita normalização Brasil-raiz (sem acento, sem pontuação)
        t = _norm_alias(phrase or "")
        if not t:
            return 0
        parts = [p for p in t.split(" ") if p]
        return len(parts)
    except Exception:
        return 0

def _alias_stopwords_set(cfg_stopwords: Any) -> set:
    try:
        if isinstance(cfg_stopwords, list):
            arr = [str(x or "").strip().lower() for x in cfg_stopwords]
        else:
            arr = [x.strip().lower() for x in str(cfg_stopwords or "").split(",")]
        arr = [a for a in arr if a]
        # normaliza também (sem acento/pontuação)
        out = set()
        for a in arr:
            out.add(_norm_alias(a))
        return out
    except Exception:
        return set()

def _alias_is_stopword_only(phrase: str, stopwords: set) -> bool:
    """
    True quando a frase for só stopword(s).
    Ex.: "oi", "bom dia", "kkk", "sim", "ta"
    """
    try:
        t = _norm_alias(phrase or "")
        if not t:
            return True
        if t in stopwords:
            return True
        parts = [p for p in t.split(" ") if p]
        if not parts:
            return True
        return all(p in stopwords for p in parts)
    except Exception:
        return False

def _alias_examples_push(prev: Any, new_text: str, max_examples: int) -> list:
    ex = []
    try:
        if isinstance(prev, list):
            ex = [str(x) for x in prev if str(x or "").strip()]
    except Exception:
        ex = []
    sn = _alias_snippet(new_text, max_len=120)
    if sn:
        ex.append(sn)
    mx = int(max_examples or 0)
    if mx > 0 and len(ex) > mx:
        ex = ex[-mx:]
    return ex

def _alias_autolearn_update(text_in: str, *, intent: str, next_step: str, confidence: float) -> None:
    """
    Atualiza/Cria item em platform_kb_action_maps/aliases_sales/items:
    - incrementa count
    - atualiza confidence_avg
    - habilita enabled=true ao bater threshold do doc aliases_sales
    """
    try:
        cfg, _ = _load_alias_config_and_enabled_items()
        if not isinstance(cfg, dict) or not cfg:
            return
        if cfg.get("enabled") is not True:
            return

        # ==========================
        # Governança (fase 1)
        # defaults seguros quando o doc raiz ainda não tem os campos novos
        # ==========================
        max_len = int(cfg.get("max_phrase_len") or 60)
        min_count = int(cfg.get("min_count") or 10)
        min_avg = float(cfg.get("min_confidence_avg") or 0.85)
        min_words = int(cfg.get("min_words") or 2)
        max_examples = int(cfg.get("max_examples") or 5)
        stopwords = _alias_stopwords_set(cfg.get("stopwords") or ["oi","ola","bom dia","boa","ok","tá","ta","sim","não","nao","kkk","haha"])

        if not _alias_candidate_allowed(text_in, max_len):
            return
        i = str(intent or "").strip().upper()
        ns = str(next_step or "").strip().upper() or "NONE"
        if not i:
            return

        phrase_norm = _norm_alias(text_in)
        if not phrase_norm:
            return

        # Nunca auto-habilitar 1 palavra / stopword pura / frases “curtas demais”
        wc = _alias_word_count(phrase_norm)
        dangerous = False
        if wc < int(min_words or 2):
            dangerous = True
        if _alias_is_stopword_only(phrase_norm, stopwords):
            dangerous = True

        from firebase_admin import firestore as fb_firestore  # type: ignore
        client = _fs_client()
        parts = [p for p in PLATFORM_ALIAS_DOC.split("/") if p]
        if len(parts) < 2:
            return
        alias_id = _sha1_short(phrase_norm, 16)
        ref = client.collection(parts[0]).document(parts[1]).collection("items").document(alias_id)
        doc = ref.get()
        old = doc.to_dict() if doc and doc.exists else {}
        if not isinstance(old, dict):
            old = {}

        old_count = int(old.get("count") or 0)
        old_avg = float(old.get("confidence_avg") or 0.0)
        new_count = old_count + 1
        conf_f = float(confidence or 0.0)
        conf_f = max(0.0, min(1.0, conf_f))
        new_avg = ((old_avg * float(old_count)) + conf_f) / float(new_count) if new_count > 0 else conf_f

        enabled_prev = (old.get("enabled") is True)
        enabled_now = bool(enabled_prev)

        # Evidência (últimos exemplos)
        examples = _alias_examples_push(old.get("examples"), text_in, max_examples=max_examples)

        # lastSeenAt sempre atualiza
        patch: Dict[str, Any] = {
            "phrase": str(old.get("phrase") or text_in).strip(),
            "intent": i,
            "next_step": ns,
            "count": int(new_count),
            "confidence_avg": float(round(new_avg, 4)),
            "examples": examples,
            "lastSeenAt": fb_firestore.SERVER_TIMESTAMP,
            "updatedAt": fb_firestore.SERVER_TIMESTAMP,
            # mantém origem se já existir
            "createdFrom": str(old.get("createdFrom") or "box_decider").strip(),
        }

        # Se perigoso: NUNCA auto-enable. Marca pra revisão.
        if dangerous:
            patch["enabled"] = False
            patch["needs_review"] = True
            # não pisa em decisões do admin (se já estiver aprovado manualmente)
            if (old.get("enabled") is True) and (str(old.get("enabledBy") or "") == "admin"):
                patch["enabled"] = True
                patch["needs_review"] = False
        else:
            # Só habilita quando bate threshold + regras OK
            if (not enabled_prev) and (new_count >= min_count) and (new_avg >= min_avg):
                enabled_now = True
                patch["enabled"] = True
                patch["enabledBy"] = "auto"
                patch["enabledAt"] = fb_firestore.SERVER_TIMESTAMP
                patch["needs_review"] = True  # sempre que auto-habilitar
            else:
                patch["enabled"] = bool(enabled_prev)
                # se foi auto, mantém needs_review true por padrão
                if (str(old.get("enabledBy") or "") == "auto") and (old.get("enabled") is True):
                    patch["needs_review"] = bool(old.get("needs_review") if "needs_review" in old else True)
                else:
                    patch["needs_review"] = bool(old.get("needs_review") or False)

        if not (doc and doc.exists):
            patch["createdAt"] = fb_firestore.SERVER_TIMESTAMP
        ref.set(patch, merge=True)
    except Exception:
        pass



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
    max_chars_override: Optional[int] = None,
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
            return f"Fechado, {nm}. Tá aí no texto o link e o caminho. Se travar em algo, me chama."
        return "Fechado. Tá aí no texto o link e o caminho. Se travar em algo, me chama."

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

    # evita "cara de template" SEM quebrar horário (06:30)
    # troca ":" por ". " somente quando não estiver entre dígitos
    t = re.sub(r"(?<!\d):(?!\d)", ". ", t)
        # "—" como pausa (vírgula) soa mais humano do que virar “ponto” no TTS
    t = t.replace("—", ", ").replace("–", ", ")
    # Mantém reticências como pausa (mais humano) e normaliza "..." para "…"
    t = t.replace("...", "…")
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
        try:
            if max_chars_override is not None:
                max_chars = min(max_chars, int(max_chars_override))
        except Exception:
            pass
    except Exception:
        max_chars = 520

    if max_chars > 0 and len(out) > max_chars:
        # Corta bonito por frase pra evitar áudio truncado pelo worker.
        parts = re.split(r"(?<=[\.\!\?])\s+", out.strip())
        acc = ""
        for p in parts:
            cand = (acc + (" " if acc else "") + p).strip()
            if len(cand) <= max_chars:
                acc = cand
            else:
                break
        out = acc.strip() if acc.strip() else (out[: max_chars - 1].rstrip() + "…")

    # Limpeza: evita espaço antes de pontuação (impacta pronúncia)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)

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


def _looks_like_bad_name(name: str) -> bool:
    """
    Detecta nomes "colados" pelo STT/regex (ex.: "Rosália podia me", "Rosália de Ponta").
    Regra: melhor não usar nem persistir do que falar estranho no áudio.
    """
    n = _norm(name or "")
    if not n:
        return False
    parts = [p for p in n.split(" ") if p]
    if not parts:
        return False
    # Caudas típicas de STT colado
    bad_tail = {
        "pode","podia","podem","podes","me","te","vc","você","voces","vocês",
        "pra","para","dizer","fala","falar","informar","confirmar",
    }
    if len(parts) >= 2 and parts[-1] in bad_tail:
        return True
    # "de/da/do/em" como parte do "nome" (muito comum quando vem cidade)
    bad_mid = {"de","da","do","dos","das","em"}
    if len(parts) >= 2 and any(p in bad_mid for p in parts[1:]):
        return True
    # strings muito longas (nome não vira frase)
    if len(n) > 28:
        return True
    return False


def _intent_cheap(t: str) -> str:
    """
    Hint barato (não é fonte canônica). O canônico vem da IA (sales_micro_nlu).

    Objetivo: evitar queda em OTHER/menus quando a frase tem sinais óbvios.
    Ordem importa: primeiro casos operacionais/fechamento/preço.
    """
    t = _norm(t)

    # Prazo / tempo / demora (ativação/processo)
    if any(k in t for k in ("quanto tempo", "em quanto tempo", "demora", "prazo", "leva quanto", "leva qto", "tempo de", "em quantos dias", "em quantas horas", "quanto demora", "quanto tempo leva", "qual prazo")):
        return "PROCESS"

    # Fechamento / ativação
    if any(k in t for k in ("vou assinar", "quero assinar", "assinatura", "assinar", "quero contratar", "contratar", "ativar", "ativação", "passo a passo", "procedimento")):
        return "ACTIVATE"

    # Voz
    if any(k in t for k in ("voz", "minha voz", "fala como", "fala igual", "parece minha voz", "voz do dono", "clone de voz", "clonagem de voz")):
        return "VOICE"

    # Operacional (dia a dia): agenda / pedidos / orçamento
    if any(k in t for k in ("agenda", "agendar", "agendamento", "marcar horário", "marcar horario", "horário", "horario", "reagendar", "cancelar", "confirmar presença", "confirmar presenca", "cliente", "consulta")):
        return "OPERATIONAL"
    if any(k in t for k in ("pedido", "pedidos", "delivery", "entrega", "comanda", "orçamento", "orcamento", "cotação", "cotacao", "serviço", "servico")):
        return "OPERATIONAL"

    # Preço / planos
    if any(k in t for k in ("preço", "preco", "quanto custa", "valor", "mensal", "mensalidade", "por mês", "por mes", "mês", "mes", "89", "119")):
        return "PRICE"
    if any(k in t for k in ("planos", "plano", "starter", "starter+", "plus")):
        return "PLANS"
    if any(k in t for k in ("diferença", "diferenca", "10gb", "2gb", "memória", "memoria")):
        return "DIFF"

    # O que é / como funciona (conceitual)
    if any(k in t for k in ("o que é", "oq é", "o que voce faz", "o que você faz", "como funciona", "como que funciona")):
        return "WHAT_IS"

    return "OTHER"


def _extract_name_freeform(text: str) -> str:
    """
    Extrai nome simples sem forçar.
    - Aceita 1–3 palavras como nome.
    - Suporta: "me chamo X", "me chamam de X", "pode me chamar de X", "meu nome é X", "aqui é X", "sou X"
    """
    def _sanitize_name_candidate(n: str) -> str:
        n = re.sub(r"\s+", " ", (n or "").strip())
        if not n:
            return ""
        # corta cola do STT logo após o nome
        n = re.split(r"\b(pode|podia|podem|podes|me|te|vc|você|vocês|pra|para|dizer|fala|falar|informar|confirmar)\b", n, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        n = re.sub(r"\s+", " ", n).strip()
        if not n:
            return ""
        # limita palavras
        parts = [p for p in n.split(" ") if p]
        if len(parts) > 3:
            n = " ".join(parts[:3]).strip()
        # não aceita "nome" com cara de frase/cidade
        if _looks_like_bad_name(n):
            return ""
        return n

    
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
            name = _sanitize_name_candidate(name)
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
            name = _sanitize_name_candidate(name)
            if name and (not _looks_like_greeting(name)):
                return name
    except Exception:
        pass

    # fallback: se for curtinho (1-3 palavras), assume que é nome
    parts = t.split()
    if 1 <= len(parts) <= 3 and len(t) <= 30:
        name = re.sub(r"[^\wÀ-ÿ\s'\-]", "", t).strip()
        name = _sanitize_name_candidate(name)
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

    # MEMÓRIA PEGAJOSA: se pedimos algo no turno anterior, consumir isso primeiro
    try:
        pending = str(st.get("pending_question") or "")
        if pending:
            st["pending_question"] = ""
            st["understand_source"] = "memory_followup"
            txt = (_ai_sales_answer(
                name=name,
                segment=segment,
                goal=goal,
                user_text=text_in,
                intent_hint=pending,
                state=st,
            ) or "").strip()
            if txt:
                return _clip(txt, SALES_MAX_CHARS_REPLY)
    except Exception:
        pass

    # PRIORIDADE: esclarecimento curto antes de menu
    try:
        conf = str(st.get("understand_confidence") or "").lower()
        depth = str(st.get("plan_depth") or "").lower()
        if conf in ("low", "mid") and depth == "deep":
            txt = (_ai_sales_answer(
                name=name,
                segment=segment,
                goal=goal,
                user_text=text_in,
                intent_hint="NEEDS_CLARIFICATION",
                state=st,
            ) or "").strip()
            if txt:
                txt = _limit_questions(txt, max_questions=1)
                return _clip(txt, SALES_MAX_CHARS_REPLY)
    except Exception:
        pass
    turns = int(st.get("turns") or 0)


    # ==========================================================
    # REGRA DE PRODUTO — 1º turno com nome => greet automático
    # - Apenas no primeiro turno
    # - Apenas se houver nome detectado ou já conhecido
    # - Não injeta nome no texto
    # ==========================================================
    try:
        if turns == 0:
            lead_name = (
                (st.get("display_name") or "").strip()
                or (st.get("lead_name") or "").strip()
            )
            if lead_name:
                st["last_name_use"] = "greet"
                st["lead_name"] = lead_name
    except Exception:
        pass


    # Não persiste nome lixo (evita poluir lead/profile/index)
    try:
        if name and _looks_like_bad_name(name):
            name = ""
            st["name"] = ""
    except Exception:
        pass

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
        head = "Sim —"
        # IA sinaliza (nameUse) e o worker decide se usa nome no ÁUDIO (gate por cadência).
        if nm and str(st.get("last_name_use") or "none").strip().lower() in ("", "none"):
            st["last_name_use"] = "greet"

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


def _kb_intent_allowlist_keys(intent_hint: str) -> set:
    """Chaves do KB compacto permitidas por intenção.
    Blindagem: mesmo se platform_kb/sales crescer, o prompt fica estável.
    """
    i = (intent_hint or "").strip().upper()
    base = {
        "identity_blurb",
        "tone_rules",
        "behavior_rules",
        "ethical_guidelines",
        "value_props",
        "cta_one_liners",
    }
    if i in ("PRICE", "PLANS"):
        return base | {"pricing_behavior", "objections_preco"}
    if i in ("VOICE",):
        return base | {"voice_pill", "voice_positioning"}
    if i in ("OPERATIONAL", "WHAT_IS", "OPERATIONAL_FLOW"):
        return base | {"how_it_works_3steps", "operational_examples", "value_in_action_blocks", "segments"}
    if i in ("ACTIVATE", "ACTIVATE_SEND_LINK", "SEND_LINK"):
        return base | {"process_facts", "intent_guidelines", "closing_behaviors", "how_to_get_started"}
    if i in ("DIFF",):
        return base | {"commercial_positioning", "product_boundaries", "how_it_works_rich", "plans"}
    if i in ("TRUST", "SECURITY"):
        return base | {"product_boundaries", "objections_confianca"}
    return base | {"how_it_works_3steps"}


def _compact_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        try:
            return str(obj)
        except Exception:
            return ""


def _enforce_kb_slice_cap(obj: Dict[str, Any], *, max_chars: int) -> Tuple[Dict[str, Any], bool, int]:
    """Limite duro: garante que o contexto de KB para o LLM não explode."""
    if not isinstance(obj, dict):
        return ({}, False, 0)
    s = _compact_json(obj)
    n = len(s)
    if n <= max_chars:
        return (obj, False, n)

    # Truncagem segura: mantém só o núcleo útil e curto
    keep_order = [
        "identity_blurb",
        "tone_rules",
        "behavior_rules",
        "ethical_guidelines",
        "value_props",
        "how_it_works_3steps",
        "cta_one_liners",
        "process_facts",
        "voice_pill",
        "value_in_action_blocks",
    ]
    out: Dict[str, Any] = {}
    for k in keep_order:
        if k in obj:
            out[k] = obj.get(k)
            if len(_compact_json(out)) >= max_chars:
                break

    try:
        if isinstance(out.get("identity_blurb"), str) and len(out["identity_blurb"]) > 220:
            out["identity_blurb"] = out["identity_blurb"][:220]
    except Exception:
        pass

    return (out, True, len(_compact_json(out)))


def _kb_slice_for_llm(*, kb: Dict[str, Any], intent_hint: str, segment: str = "") -> Dict[str, Any]:
    """Gera slice compacto + allowlist do KB para prompts (economia garantida)."""
    rep = _kb_compact_for_prompt(kb or {})
    allowed = _kb_intent_allowlist_keys(intent_hint)

    sliced: Dict[str, Any] = {}
    for k in allowed:
        if k in rep:
            sliced[k] = rep.get(k)

    seg = (segment or "").strip().lower()
    if seg and isinstance(sliced.get("segments"), dict):
        try:
            segs = sliced.get("segments") or {}
            if isinstance(segs, dict) and seg in segs:
                sliced["segments"] = {seg: segs.get(seg)}
            else:
                # não inclui segments se não for relevante
                sliced.pop("segments", None)
        except Exception:
            pass

    final, truncated, chars = _enforce_kb_slice_cap(sliced, max_chars=_SALES_KB_SLICE_MAX_CHARS)
    if truncated:
        try:
            logger.info("[sales_kb] slice_truncated intent=%s chars=%s max=%s", (intent_hint or ""), chars, _SALES_KB_SLICE_MAX_CHARS)
        except Exception:
            pass
    return final



def _select_kb_blocks_by_intent(intent_final: str) -> list:
    """
    Retorna lista de chaves da KB que devem entrar no prompt,
    com base na intenção final detectada.
    Sempre curto, previsível e econômico.
    """
    if not intent_final:
        return []

    intent_ai = str(intent_final).strip().upper()
    intent = intent_ai
    override_reason = ""

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

    if intent == "AGENDA":
        return ["segment_pills", "operational_capabilities", "process_facts"]

    if intent == "CONTACTS":
        return ["operational_capabilities", "process_facts"]

    if intent == "QUOTE":
        return ["operational_capabilities", "pricing_facts", "process_facts"]

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
    rep = _kb_slice_for_llm(kb=kb, intent_hint=intent_hint or "", segment=segment or "")

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
        "Nada deve soar decorado, técnico ou robótico.\nResponda SOMENTE JSON válido (sem markdown), seguindo o schema pedido.\n\n"
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
        "POLÍTICA DE NOME (produto):\n"
        "- Se você já sabe o nome do lead (campo name), use 1 vez de forma natural em respostas iniciais (ex.: \"Rosália, ...\") para empatia e prova técnica.\n"
        "- Se não souber o nome, você pode perguntar de forma leve, MAS sem travar: responda a dúvida e no final peça o nome em 1 frase.\n"
        "- Não repita o nome em toda mensagem.\n\n"
        "POLÍTICA DE LINK/CTA:\n"
        "- Link é CTA, não é resposta.\n"
        "- Se você for citar o site, antes entregue 2–4 frases úteis (explicação + micro-exemplo + benefício) e só então coloque o link em linha separada.\n"
        "- Não use \"entra no site\" como fuga quando a pergunta é simples.\n\n"
        "FORMATO DE SAÍDA (JSON):\n"
        "- Sempre responda como JSON: {\"replyText\":\"...\",\"nameUse\":\"greet|ask|none\"}\n"
        "- nameUse=greet quando você usou o nome; ask quando pediu o nome; none quando não usou.\n\n"
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
    # Operacional pode precisar de um pouco mais de tokens pra explicar o "fluxo fechado"
    # sem virar palestra. Mantém custo sob controle: só aplica nesses intent_hints.
    _max_tokens = SALES_ANSWER_MAX_TOKENS
    try:
        ih_local = str(intent_hint or "").strip().upper()
        if ih_local in ("OPERATIONAL_FLOW", "OPERATIONAL", "AGENDA", "PROCESS"):
            _max_tokens = int(os.getenv("SALES_ANSWER_MAX_TOKENS_OPERATIONAL", str(SALES_ANSWER_MAX_TOKENS)) or str(SALES_ANSWER_MAX_TOKENS))
    except Exception:
        _max_tokens = SALES_ANSWER_MAX_TOKENS

    raw = (_openai_chat(
            prompt,
            max_tokens=_max_tokens,
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


    # Nome (produto): NÃO injetar nome no texto por padrão.
    # Motivo: o nome deve ser aplicado pelo worker só no ÁUDIO (gate), quando a IA sinaliza via nameUse.
    # Feature flag para reativar em emergência: SALES_INJECT_NAME_IN_TEXT=1
    try:
        if str(os.environ.get("SALES_INJECT_NAME_IN_TEXT", "0") or "0").strip().lower() in ("1", "true", "yes"):
            turns = int(state.get("turns") or 0) if isinstance(state, dict) else 0
            nm = (name or "").strip()
            if nm and name_use in ("none", "") and turns <= 3:
                low = (reply_text or "").lower()
                if nm.lower() not in low:
                    reply_text = f"{nm}, " + (reply_text or "").lstrip()
                    name_use = "greet"
    except Exception:
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
            fs = _fs_client()
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
    rep = _kb_slice_for_llm(kb=kb, intent_hint=hint or "", segment=segment or "")
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
        "Escreva uma resposta humana, vendedora e clara (sem soar robótico).\n"
        "Regras:\n"
        "- Preferir 4 a 8 linhas (ou ~250 a 650 caracteres quando fizer sentido).\n"
        "- Sempre 1 pergunta no final.\n"
        "- NÃO escreva o nome do lead no TEXTO (replyText). Nome é aplicado só no ÁUDIO via worker/gate.\n"
        "- Acolhimento/gratidão (humano, sem soar decorado):\n"
        "  - Se for primeiro contato: 1 frase curta de agradecimento/acolhida e já entra no assunto.\n"
        "  - Se o lead elogiar, agradecer, ou desejar boas-festas (ano-novo, natal, páscoa etc.): retribua com 1 frase curta e natural.\n"
        "  - Fora isso, não repita 'obrigado' em toda mensagem.\n"
        "- Para áudio: frases curtas e fáceis de ouvir; detalhes podem ir no texto (link pode ir no texto).\n"
        "- Sem bastidores técnicos.\n"
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
            fs = _fs_client()
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

def _is_internal_policy_text(s: str) -> bool:
    """Heurística barata para evitar vazar texto interno do KB (playbook) no áudio."""
    try:
        t = re.sub(r"\s+", " ", str(s or "")).strip().lower()
    except Exception:
        return True
    if not t:
        return True
    bad = (
        "micro-exemplo",
        "próximo passo",
        "proximo passo",
        "sempre com direção",
        "sempre com direcao",
        "lead",
        "aprofund",
        "resuma e devolv",
    )
    if any(b in t for b in bad):
        return True
    if re.search(r"\b1\b\s*(micro|passo|\)|\-|\.)", t):
        return True
    return False


def _is_social_gesture_cheap(text: str) -> bool:
    """Só para NÃO acionar soft-close em cima de elogio/agradecimento/votos.
    A resposta em si deve vir da IA (social_ack_line).
    """
    try:
        t = (text or "").lower()
    except Exception:
        return False
    keys = ("obrigad", "valeu", "parab", "show", "top", "feliz ", "boas festas", "bom ano")
    return any(k in t for k in keys)



def _soft_close_message(kb: Dict[str, Any], name: str = "") -> str:
    """Fechamento gentil quando a conversa não está avançando (anti-curioso infinito).
    Sempre:
    - curto
    - sem pergunta
    - aponta pro site
    """
    try:
        site = (SITE_URL or "www.meirobo.com.br").strip()
    except Exception:
        site = "www.meirobo.com.br"

    nm = (name or "").strip()
    prefix = ""  # sem nome no texto (apenas no áudio)

    # Se o Firestore trouxer um limite/guia, usa (sem copiar textão).
    try:
        limits = str((kb or {}).get("conversation_limits") or "").strip()
    except Exception:
        limits = ""

    if limits and (not _is_internal_policy_text(limits)):
        # pega 1 linha “falável”
        one = re.sub(r"\s+", " ", limits).strip()
        one = one[:180].rstrip(" ,;:-") + "."
        return f"{prefix}{one}\n\nPra ver tudo com calma, é por aqui: {site}"

    return f"{prefix}Pra eu não te prender aqui no vai-e-vem, o caminho mais rápido é pelo site.\n\n{site}"


def _reply_from_state(text_in: str, st: Dict[str, Any]) -> str:
    """
    Única função que decide a resposta final (texto).
    """
    # Captura de nome (conservador) — antes de decidir caixa
    try:
        nm = _extract_name_from_text(text_in)
        if nm:
            st["name"] = nm
            st["lead_name"] = nm
            # Sinaliza para o worker que pode usar o nome no ÁUDIO (gate decide).
            # Evita repetir: só nos primeiros turnos.
            try:
                turns = int(st.get("turns") or 0)
            except Exception:
                turns = 0
            if turns <= 3 and not str(st.get("last_name_use") or "").strip():
                st["last_name_use"] = "greet"
    except Exception:
        pass

    # Pedido direto de link/site: não pode cair em OTHER (resposta curta)
    try:
        if _is_link_request(text_in):
            st["understand_source"] = "policy_link_request"
            st["understand_intent"] = "ACTIVATE"
            st["understand_confidence"] = "high"
            st["plan_intent"] = "ACTIVATE"
            st["plan_next_step"] = "SEND_LINK"
            nm = (st.get("name") or "").strip()
            if nm and str(st.get("last_name_use") or "none").strip().lower() in ("", "none"):
                st["last_name_use"] = "greet"
            return "Fechado — vou te mandar o link aqui na conversa."
    except Exception:
        pass

    # ==========================================================
    # AUTO-ALIAS (antes de IA): se bater, pula decider/NLU
    # ==========================================================
    try:
        hit = _alias_lookup(text_in)
        if isinstance(hit, dict) and hit.get("enabled") is True:
            a_int = str(hit.get("intent") or "").strip().upper()
            a_ns = str(hit.get("next_step") or "NONE").strip().upper()
            if a_int:
                st["understand_source"] = "alias"
                st["understand_intent"] = a_int
                st["understand_confidence"] = "high"
                st["plan_intent"] = a_int
                st["plan_next_step"] = ("SEND_LINK" if a_ns == "SEND_LINK" else "")
                try:
                    st["policiesApplied"] = list(set((st.get("policiesApplied") or []) + ["alias_hit"]))
                except Exception:
                    pass

                # Se o alias for SEND_LINK, não cola URL aqui: generate_reply garante link no texto.
                if a_ns == "SEND_LINK":
                    nm = (st.get("name") or "").strip()
                    if nm and str(st.get("last_name_use") or "none").strip().lower() in ("", "none"):
                        st["last_name_use"] = "greet"
                    return "Fechado — vou te mandar o link aqui na conversa."

                # Caso conceitual (ex.: VOICE): usa caminho econômico (sem IA geradora)
                econ, _, _pol = _economic_reply(
                    intent=a_int,
                    name=(st.get("name") or "").strip(),
                    segment=(st.get("segment") or "").strip(),
                    goal=(st.get("goal") or "").strip(),
                    user_text=text_in,
                    st=st,
                )
                if econ:
                    return econ
    except Exception:
        pass

    name = (st.get("name") or "").strip()
    segment = (st.get("segment") or "").strip()
    goal = (st.get("goal") or "").strip()
    stage = (st.get("stage") or "").strip() or "ASK_NAME"

    turns = int(st.get("turns") or 0) + 1
    st["turns"] = turns
    st["last_user_at"] = time.time()

    nudges = int(st.get("nudges") or 0)


    # Firestore é fonte de verdade (sempre): carrega KB (cache TTL interno) e registra no estado.
    kb = _get_sales_kb() or {}
    try:
        st["kb_version"] = str(kb.get("version") or kb.get("kb_version") or "").strip() or st.get("kb_version") or ""
        st["kb_loaded"] = True
    except Exception:
        pass

    # Anti-curioso infinito: se já estourou turnos sem avançar, fecha gentil e aponta pro site.
    has_name = bool((name or "").strip())
    has_segment = bool((segment or "").strip())
    should_close = _should_soft_close(st, has_name=has_name, has_segment=has_segment)
    if should_close and _is_social_gesture_cheap(text_in):
        # Gesto social não deve virar "EXIT" automático; deixa a IA responder humano.
        should_close = False
        try:
            st["policiesApplied"] = list(set((st.get("policiesApplied") or []) + ["no_soft_close_social"]))
        except Exception:
            pass
    if should_close:
        st["stage"] = "EXIT"
        st["plan_intent"] = "EXIT"
        st["plan_next_step"] = "EXIT"
        st["understand_source"] = "soft_close_policy"
        st["understand_intent"] = "EXIT"
        st["understand_confidence"] = "high"
        return _clip(_soft_close_message(kb, name=name), SALES_MAX_CHARS_REPLY)


    
    # ==========================================================
    # Cache mínimo de intent (Firestore): evita IA repetida em frases iguais
    # ==========================================================
    try:
        ck = _intent_cache_key(text_in)
        cached = _fs_cache_get(ck)
        if isinstance(cached, dict) and cached.get("kind") == "sales_intent":
            ci = str(cached.get("intent") or "").strip().upper()
            cns = str(cached.get("next_step") or "").strip().upper()
            if ci:
                st["understand_source"] = "fs_intent_cache"
                st["understand_intent"] = ci
                st["understand_confidence"] = "high"
                st["plan_intent"] = ci
                if cns:
                    st["plan_next_step"] = cns
                # Para casos óbvios de SEND_LINK: responde curto e deixa o link pro final
                if cns == "SEND_LINK":
                    nm = (st.get("name") or "").strip()
                    if nm and str(st.get("last_name_use") or "none").strip().lower() in ("", "none"):
                        st["last_name_use"] = "greet"
                    return "Fechado — vou te mandar o link aqui na conversa."
    except Exception:
        pass

    # ==========================================================
    # BOX MODE (canônico): 1 caixa/turno + leitura mínima do Firestore
    # ==========================================================
    try:
        bx = _sales_box_handle_turn(text_in, st)
        if isinstance(bx, str) and bx.strip():
            return _clip(bx.strip(), SALES_MAX_CHARS_REPLY)
    except Exception:
        pass

    # ==========================================================
    # FALLBACK CANÔNICO (sem micro_nlu/plan):
    # - Se o box não respondeu (raro), tenta um intent barato e responde economicamente.
    # - Se ainda assim nada, devolve resposta útil + link (NUNCA menu genérico).
    # ==========================================================
    try:
        cheap = str(_intent_cheap(text_in) or "").strip().upper()
        if cheap in ("PLANS",):
            cheap = "PRICE"
        if cheap and cheap != "OTHER":
            econ, ns, _pol = _economic_reply(
                intent=cheap,
                name=(st.get("name") or "").strip(),
                segment=(st.get("segment") or "").strip(),
                goal=(st.get("goal") or "").strip(),
                user_text=text_in,
                st=st,
            )
            if econ:
                st["understand_source"] = "fallback_economic"
                st["understand_intent"] = cheap
                st["understand_confidence"] = "mid"
                st["plan_intent"] = cheap
                st["plan_next_step"] = (ns or "NONE")
                return _clip(str(econ).strip(), SALES_MAX_CHARS_REPLY)
    except Exception:
        pass

    # fallback final — NUNCA "jogar pro site" como corpo da resposta.
    # A IA pode pedir SEND_LINK, mas o corpo precisa trazer valor antes (2–4 frases).
    try:
        if not str(st.get("understand_source") or "").strip():
            st["understand_source"] = "fallback_box"
            st["understand_intent"] = "WHAT_IS"
            st["understand_confidence"] = "low"
            st["plan_intent"] = "WHAT_IS"
            st["plan_next_step"] = "NONE"
        else:
            st["understand_intent"] = str(st.get("understand_intent") or st.get("plan_intent") or "WHAT_IS").strip().upper()
            st["plan_intent"] = str(st.get("plan_intent") or "WHAT_IS").strip().upper()
            st["plan_next_step"] = str(st.get("plan_next_step") or "NONE").strip().upper()

        intent_u = str(st.get("plan_intent") or "WHAT_IS").strip().upper()
        name = str(st.get("name") or st.get("lead_name") or "").strip()
        segment = str(st.get("segment") or "").strip()


        # ==========================================================
        # Firestore-first (telemetria INELÁSTICA)
        # - aiMeta NUNCA pode sair vazio
        # - sem try/except "pass" que apaga evidência
        # ==========================================================
        iu = (intent_u if intent_u else "WHAT_IS").strip().upper()
        st["kb_doc_path"] = "platform_kb/sales"
        st["kb_contract_id"] = f"{iu}:v1"
        st["kb_slice_fields"] = []
        try:
            st["kb_slice_fields"] = list(_kb_slice_fields_for_intent(iu, segment=segment) or [])
        except Exception:
            st["kb_slice_fields"] = []
        st["kb_slice_size_chars"] = 0
        st["kb_loaded"] = False
        st["kb_required_ok"] = False
        st["kb_miss_reason"] = ""
        st["kb_missing_fields"] = []
        st["kb_used"] = False

        kb_slice = _kb_slice_for_box(iu, segment=segment) or {}

        # tamanho aproximado + loaded
        try:
            st["kb_slice_size_chars"] = int(len(json.dumps(kb_slice, ensure_ascii=False, sort_keys=True)))
        except Exception:
            st["kb_slice_size_chars"] = int(len(str(kb_slice or "")))
        st["kb_loaded"] = bool(kb_slice)

        # contrato mínimo por intent (se falhar, registra o motivo)
        if not bool(kb_slice):
            st["kb_required_ok"] = False
            st["kb_miss_reason"] = "empty_slice"
            st["kb_missing_fields"] = list(st.get("kb_slice_fields") or [])
        else:
            try:
                miss = _kb_contract_missing_groups(kb_slice, iu, segment=segment)
                if miss:
                    st["kb_required_ok"] = False
                    st["kb_miss_reason"] = "missing_required"
                    st["kb_missing_fields"] = list(miss or [])
                else:
                    st["kb_required_ok"] = True
                    st["kb_miss_reason"] = ""
                    st["kb_missing_fields"] = []
            except Exception:
                st["kb_required_ok"] = False
                st["kb_miss_reason"] = "contract_exception"
                st["kb_missing_fields"] = list(st.get("kb_slice_fields") or [])

        st["kb_used"] = bool(kb_slice) and bool(st.get("kb_required_ok") is True)
        prices = _get_display_prices(ttl_seconds=180) or {}
# Observabilidade: marca fonte e exemplo quando KB ok
        try:
            st["kb_used"] = bool(kb_slice) and bool(st.get("kb_required_ok"))
            if st["kb_used"] and intent_u == "WHAT_IS" and _kb_path_has_value(kb_slice, "value_in_action_blocks.scheduling_scene"):
                st["kb_example_used"] = "value_in_action_blocks.scheduling_scene"
            st["spoken_source"] = "speechify(replyText)"
            st["reply_text_role"] = "audit_text"
            st["spoken_text_role"] = "tts_script"
        except Exception:
            pass

        if not bool(st.get("kb_required_ok")):
            # Fallback honesto + 1 pergunta prática (POR INTENT) — sem triagem genérica
            iu = intent_u
            if iu == "PROCESS":
                body = "Posso te responder certinho — você quer saber do PRAZO pra ficar ativo no WhatsApp, ou do passo-a-passo de cadastro/ativação?"
                suggested = "ASK_CLARIFY"
            elif iu == "PRICE":
                body = "Pra eu te indicar o plano certo: é só você atendendo (1 número) ou tem mais gente junto no WhatsApp?"
                suggested = "ASK_CLARIFY"
            elif iu == "VOICE":
                body = "Sobre a voz: você quer ver COMO envia o áudio pra treinar, ou quer entender os limites (o que pode e o que não pode)?"
                suggested = "ASK_CLARIFY"
            else:
                body = _fallback_min_reply(name=name, user_text=text_in)
                suggested = "NONE"
            # Observabilidade: fallback por KB miss/contrato
            try:
                st["kb_used"] = False
                st["spoken_source"] = "fallback_min_reply"
                st["reply_text_role"] = "fallback_text"
                st["spoken_text_role"] = "fallback_tts_script"
            except Exception:
                pass
        else:
            body, suggested = _compose_box_reply(

                box_intent=intent_u,
                confidence=str(st.get("understand_confidence") or ""),
                box_data=kb_slice,
                prices=prices,
                user_text=text_in,
                name=name,
                segment=segment,
            )
            body = (body or "").strip() or _fallback_min_reply(name=name, user_text=text_in)

            # Observabilidade: resposta composta com KB ok
            try:
                st["spoken_source"] = "compose_box_reply"
            except Exception:
                pass

        # CTA só se for ação pedida (ou sugerida) — e sempre no fim.
        ns = str(st.get("plan_next_step") or suggested or "NONE").strip().upper()

        # Observabilidade (DIFF 0): momento do funil (heurística barata; sem IA).
        try:
            if ns == "SEND_LINK" or intent_u in ("ACTIVATE_SEND_LINK",):
                st["funnel_moment"] = "CLOSING"
            elif intent_u in ("PRICE", "DIFF", "VOICE"):
                st["funnel_moment"] = "EVALUATION"
            else:
                st["funnel_moment"] = "CURIOSITY"
        except Exception:
            pass
        if ns == "SEND_LINK":
            st["plan_next_step"] = "SEND_LINK"
            body = (body + f"\n\nSe fizer sentido, o próximo passo é criar a conta no site: {SITE_URL}").strip()
        else:
            st["plan_next_step"] = "NONE"

        return _clip(body, SALES_MAX_CHARS_REPLY)
    except Exception:
        # Último-último fallback: humano e curto, sem empurrar link.
        st["understand_source"] = str(st.get("understand_source") or "fallback_min")
        st["plan_next_step"] = "NONE"
        return _clip(_fallback_min_reply(name=str(st.get("name") or st.get("lead_name") or "").strip()), SALES_MAX_CHARS_REPLY)

def generate_reply(text: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = ctx or {}
    text_in = (text or "").strip() or "Lead enviou um áudio."
    from_e164 = str(ctx.get("from_e164") or ctx.get("from") or "").strip()

    # Nome do lead (quando o worker já sabe / Firestore override):
    # - texto NÃO leva nome; só ajuda a IA e o gate do ÁUDIO.
    ctx_display_name = str(ctx.get("display_name") or ctx.get("displayName") or "").strip()
    if ctx_display_name and len(ctx_display_name) > 1:
        try:
            ctx["display_name"] = ctx_display_name
        except Exception:
            pass

    # Helper: monta saída canônica SEMPRE
    def _mk_out(reply_text: str, st: Dict[str, Any]) -> Dict[str, Any]:
        rt = (reply_text or "").strip() or f"Infos completas aqui: {SITE_URL}"

        # Se tem link, preferir texto também (worker pode mandar áudio+texto)
        prefers_text = False
        try:
            u = (rt or "").lower()
            prefers_text = ("www.meirobo.com.br" in u) or ("http://" in u) or ("https://" in u)
        except Exception:
            prefers_text = False

        # Understanding sempre preenchido
        und = {
            "intent": str(st.get("understand_intent") or st.get("plan_intent") or "OTHER").strip().upper(),
            "confidence": str(st.get("understand_confidence") or "mid").strip().lower(),
            "source": str(st.get("understand_source") or "sales_box").strip(),
            "next_step": str(st.get("plan_next_step") or "NONE").strip().upper(),
            "risk": str(st.get("risk") or "").strip(),
            "depth": str(st.get("depth") or "deep").strip(),
        }

        # Sinal leve para o worker (IA pede; código autoriza no áudio).
        # - IA não deve escrever o nome no texto.
        try:
            _name_use_out = str(st.get("last_name_use") or "none").strip().lower()
        except Exception:
            _name_use_out = "none"
        try:
            _lead_name_out = str((st.get("name") or st.get("lead_name") or "")).strip()
        except Exception:
            _lead_name_out = ""
        try:
            und["name_use"] = _name_use_out
        except Exception:
            pass

        # ==========================================================
        # Spoken composer (determinístico, barato)
        # - Por padrão: spokenizer v1 (se habilitado)
        # - Fallback: speechify_for_tts(replyText)
        # ==========================================================
        def _compose_spoken(rt_in: str) -> str:
            s = (rt_in or "").strip()
            if not s:
                return ""
            # Se tiver URL, não ler URL no áudio
            has_url_local = False
            try:
                has_url_local = bool(_RE_URL.search(s))
            except Exception:
                has_url_local = ("http://" in s.lower()) or ("https://" in s.lower()) or ("www." in s.lower())
            if has_url_local:
                try:
                    s = _RE_URL.sub("", s).strip()
                except Exception:
                    pass
                ns = str(und.get("next_step") or "").strip().upper()
                if ns == "SEND_LINK" or bool(prefers_text):
                    if s and not s.endswith((".", "!", "?")):
                        s = s + "."
                    s = (s + " O link tá na mensagem.").strip()
            return _speechify_for_tts(s)

        spoken = _compose_spoken(rt)

        spoken_txt = ""
        spoken_src = "speechify(replyText)"
        spoken_role = "tts_script"
        try:
            turns = int(st.get("turns") or 0) if isinstance(st, dict) else 0
        except Exception:
            turns = 0
        try:
            has_url = bool(_RE_URL.search(rt)) if rt else False
        except Exception:
            has_url = False

        # Se há link a mandar, força fala curta sem URL (áudio não vira "leitura de link")
        try:
            ns = str(und.get("next_step") or "").strip().upper()
            if bool(has_url) and (ns == "SEND_LINK" or bool(prefers_text)):
                spoken_txt = _compose_spoken(rt)
                spoken_src = "compose_spoken"
                spoken_role = "spoken_source_of_truth"
        except Exception:
            pass


        try:
            if _spokenizer_should_run() and not spoken_txt:
                try:
                    _i = str(und.get("intent") or "OTHER").strip().upper()
                    if _i in ("AGENDA", "OPERATIONAL", "PROCESS"):
                        # Operacional precisa de mais "respiro" no áudio.
                        # Mantém custo sob controle: default continua curto, mas se a IA sinalizar depth=deep,
                        # liberamos um pouco mais para não cortar a explicação no meio.
                        _spoken_max = int(os.getenv("SALES_SPOKEN_MAX_CHARS_OPERATIONAL", "260"))
                        try:
                            _depth = str(und.get("depth") or "").strip().lower()
                        except Exception:
                            _depth = ""
                        if _depth == "deep":
                            _spoken_max = int(os.getenv("SALES_SPOKEN_MAX_CHARS_OPERATIONAL_DEEP", "420"))
                    elif _i in ("ACTIVATE", "SLA"):
                        _spoken_max = int(os.getenv("SALES_SPOKEN_MAX_CHARS_ACTIVATE", "220"))
                    elif _i in ("WHAT_IS",):
                        _spoken_max = int(os.getenv("SALES_SPOKEN_MAX_CHARS_WHAT_IS", "230"))
                    else:
                        _spoken_max = int(os.getenv("SALES_SPOKEN_MAX_CHARS_DEFAULT", "240"))
                except Exception:
                    _spoken_max = 240

                spoken_txt = _spokenize_v1(
                    reply_text=rt,
                    intent_final=str(und.get("intent") or "OTHER"),
                    prefers_text=bool(prefers_text),
                    has_url=bool(has_url),
                    lead_name=str(_lead_name_out or ""),
                    turns=int(turns or 0),
                    max_chars_override=_spoken_max,
                )
                spoken_src = "spokenizer_v1"
                spoken_role = "spokenizer_v1"
            else:
                spoken_txt = _speechify_for_tts(rt)
                spoken_src = "speechify(replyText)"
                spoken_role = "tts_script"
        except Exception:
            spoken_txt = _speechify_for_tts(rt)
            spoken_src = "speechify(replyText)"
            spoken_role = "tts_script"
        # Sanitiza fala (pontuação/aberturas ruins) e carimba observabilidade
        try:
            spoken_txt = _sanitize_spoken(spoken_txt)
        except Exception:
            pass

        # Mantém compat: spoken segue o texto sanitizado
        try:
            spoken = spoken_txt
        except Exception:
            pass

        # carimba no state p/ observabilidade + payload final
        try:
            st["spoken_source"] = spoken_src
            st["spoken_text_role"] = spoken_role
        except Exception:
            pass

        # aiMeta (payload final): worker/outbox/probe podem auditar daqui
        # ==========================================================
        # 🔧 ENRIQUECE TELEMETRIA DO STATE COM DADOS REAIS DO CONTRACT
        contract = st.get("contract") or {}

        if isinstance(contract, dict) and contract:
            contract_kb_used = bool(
                contract.get("hydrated_from_docs")
                or contract.get("has_example_line")
                or contract.get("has_practical_scene")
                or contract.get("archetype_id")
                or contract.get("segment_id")
                or contract.get("segment")
            )

            st["kb_used"] = bool(st.get("kb_used") is True or contract_kb_used)
            st["kb_example_used"] = bool(
                st.get("kb_example_used") is True or bool(contract.get("has_example_line"))
            )
            st["kb_scene_used"] = bool(
                st.get("kb_scene_used") is True or bool(contract.get("has_practical_scene"))
            )

            if not str(st.get("kb_doc_path") or "").strip():
                st["kb_doc_path"] = (
                    contract.get("subsegment_id")
                    or contract.get("segment_id")
                    or contract.get("archetype_id")
                    or ""
                )

            if (
                not bool(st.get("kb_required_ok"))
                and (
                    contract.get("hydrated_from_docs")
                    or contract.get("has_example_line")
                    or contract.get("has_practical_scene")
                )
            ):
                st["kb_required_ok"] = True
                if not bool(st.get("kb_missing_fields")):
                    st["kb_miss_reason"] = ""

        ai_meta = {
            "iaSource": str(st.get("understand_source") or und.get("source") or "").strip(),
            "kbDocPath": str(st.get("kb_doc_path") or "").strip(),
            "kbContractId": str(st.get("kb_contract_id") or "").strip(),
            "kbSliceFields": list(st.get("kb_slice_fields") or []),
            "kbSliceSizeChars": int(st.get("kb_slice_size_chars") or 0),
            "kbRequiredOk": bool(st.get("kb_required_ok") is True),
            "kbMissReason": str(st.get("kb_miss_reason") or "").strip(),
            "kbMissingFields": list(st.get("kb_missing_fields") or []),
            "kbUsed": bool(st.get("kb_used") is True),
            "kbExampleUsed": bool(st.get("kb_example_used") is True),
            "kbSceneUsed": bool(st.get("kb_scene_used") is True),
            "spokenSource": str(st.get("spoken_source") or spoken_src).strip(),
            "replyTextRole": str(st.get("reply_text_role") or "audit_text").strip(),
            "spokenTextRole": str(st.get("spoken_text_role") or spoken_role).strip(),
            "funnelMoment": str(st.get("funnel_moment") or "").strip(),
        }

    # ==========================================================
    # Teto por contato (produto): se já fechou, não volta a conversar.
    # ==========================================================
    try:
        if bool((ctx or {}).get("state", {}).get("closed")):
            # se alguém passar state fechado por fora (defensivo)
            st_closed = dict((ctx or {}).get("state") or {})
            return _mk_out(
                f"Pra seguir, é pelo site mesmo: {SITE_URL}",
                st_closed,
            )
    except Exception:
        pass


    # Sem remetente: ainda assim devolve canônico
    if not from_e164:
        st0: Dict[str, Any] = {
            "understand_source": "no_sender",
            "understand_intent": "WHAT_IS",
            "understand_confidence": "low",
            "plan_intent": "WHAT_IS",
            "plan_next_step": "SEND_LINK",
        }
        return _mk_out(f"Pra ver tudo certinho, entra aqui: {SITE_URL}", st0)

    # Carrega estado e responde pelo caminho canônico (box-first)
    st, wa_key = _load_state(from_e164)
    if isinstance(st, dict):
        st["wa_key"] = wa_key
        # Se o worker já sabe o nome (display_name), aproveita como contexto.
        # Isso NÃO injeta nome no texto; só ajuda a IA e o gate do ÁUDIO.
        try:
            _dn = str(ctx.get("display_name") or "").strip()
        except Exception:
            _dn = ""
        if _dn and not str(st.get("name") or st.get("lead_name") or "").strip():
            st["name"] = _dn
            st["lead_name"] = _dn
            try:
                turns0 = int(st.get("turns") or 0)
            except Exception:
                turns0 = 0
            if turns0 <= 3 and str(st.get("last_name_use") or "none").strip().lower() in ("", "none"):
                st["last_name_use"] = "greet"

    # hard-stop se o contato já foi encerrado
    if bool(st.get("closed")):
        st["understand_source"] = "lead_closed"
        st["understand_intent"] = "OTHER"
        st["understand_confidence"] = "mid"
        st["plan_intent"] = "OTHER"
        st["plan_next_step"] = "SEND_LINK"
        return _mk_out(
            f"Fechado 🙂 Pra seguir, é pelo site mesmo: {SITE_URL}",
            st,
        )


    try:
        reply_text = _reply_from_state(text_in, st)
    except Exception:
        # Fallback interno (nunca deixar o worker usar fallback genérico)
        st["understand_source"] = "sales_lead_exception_fallback"
        st["understand_intent"] = "OTHER"
        st["understand_confidence"] = "low"
        st["plan_intent"] = "OTHER"
        st["plan_next_step"] = "SEND_LINK"
        reply_text = f"Pra ver tudo certinho (voz, preço e como funciona), entra aqui: {SITE_URL}"

    # ==========================================================
    # Contador de mensagens "inteligentes" por contato
    # - conta qualquer resposta útil (inclui clarificação)
    # ==========================================================
    try:
        st["smart_msgs"] = int(st.get("smart_msgs") or 0) + 1
    except Exception:
        st["smart_msgs"] = 1

    # soft warning (a partir de 15): prepara o encerramento sem soar rude
    try:
        if int(st.get("smart_msgs") or 0) == LEAD_SOFT_WARNING_AT:
            st["soft_warned"] = True
    except Exception:
        pass

    # hard cap: encerra e marca state fechado
    try:
        if int(st.get("smart_msgs") or 0) >= LEAD_MAX_SMART_MSGS:
            st["closed"] = True
            st["closed_reason"] = "lead_max_msgs"
            st["closed_at"] = time.time()
            st["understand_source"] = "lead_cap_close"
            st["understand_intent"] = "OTHER"
            st["understand_confidence"] = "high"
            st["plan_intent"] = "OTHER"
            st["plan_next_step"] = "SEND_LINK"
            reply_text = (
                "Fechado 🙂 Pra não virar conversa infinita por aqui, eu encerro por aqui.\n"
                f"Se você quiser seguir e ver tudo certinho (voz, preço e como funciona): {SITE_URL}"
            )
    except Exception:
        pass

    # Se chegou no soft warning, adiciona 1 linha humana (sem alongar)
    try:
        if bool(st.get("soft_warned")) and (not bool(st.get("closed"))):
            # não cola link automaticamente; só sinaliza
            reply_text = (str(reply_text or "").strip() + "\n\n"
                          "Se você quiser, eu te mando o link e a gente fecha por lá.").strip()
    except Exception:
        pass

    # Persistência leve (mantém o que já existe)
    try:
        _save_session(wa_key, st, ttl_seconds=int(os.getenv("INSTITUTIONAL_SESSION_TTL", "86400") or "86400"))
    except Exception:
        pass
    try:
        _upsert_lead_from_state(wa_key, st)
    except Exception:
        pass

    return _mk_out(str(reply_text or ""), st)
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
