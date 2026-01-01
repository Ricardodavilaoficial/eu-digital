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
from typing import Any, Callable, Dict, Optional

# =========================
# Conteúdo CANÔNICO (VENDAS)
# =========================

SITE_URL = "www.meirobo.com.br"

PRICE_STARTER = "R$ 89/mês"
PRICE_PLUS = "R$ 119/mês"
PLUS_DIFF = "A única diferença é o espaço de memória: Starter tem 2 GB e o Starter+ tem 10 GB. O resto é igual."

OPENING_ASK_NAME = (
    "Oi! 👋 Eu sou o MEI Robô 🙂\n\n"
    "Antes de te explicar direitinho,\n"
    "me diz teu nome?"
)

ASK_SEGMENT = (
    "Prazer, {name} 😄\n\n"
    "Teu negócio é do quê?"
)

CTA_SITE = (
    f"O melhor caminho agora é pelo site:\n{SITE_URL}\n\n"
    "Se puder, faz a configuração num computador com internet — fica mais fácil e rapidinho.\n"
    "Se precisar, dá pra fazer pelo celular também."
)

WHAT_IS = (
    "Eu ajudo MEI a atender melhor no WhatsApp, ganhar tempo e deixar o atendimento mais profissional.\n"
    "Respondo clientes, organizo agenda/pedidos e deixo tudo mais redondo no dia a dia.\n\n"
    "Me diz teu nome pra eu te explicar do jeito certo 🙂"
)

PLANS_SHORT = (
    f"Hoje tem 2 opções bem diretas:\n"
    f"• Starter: {PRICE_STARTER} (2 GB)\n"
    f"• Starter+: {PRICE_PLUS} (10 GB)\n\n"
    "Sem fidelidade: cancela quando quiser.\n"
    "E a configuração inicial tá sem custo por tempo indeterminado.\n\n"
    "Me diz teu nome e teu ramo que eu te digo qual combina mais contigo 🙂"
)

PRICE_REPLY = (
    f"Hoje o plano Starter tá {PRICE_STARTER}.\n"
    f"E o Starter+ tá {PRICE_PLUS}.\n\n"
    f"{PLUS_DIFF}\n\n"
    "Me diz teu nome e teu ramo que eu te falo qual faz mais sentido 🙂"
)

# Pitch por segmento (curto, WhatsApp)
PITCH = {
    "beleza": (
        "No teu caso, eu cuido da agenda, mostro horários livres, passo valores e marco tudo sem te incomodar.\n"
        "Teu cliente marca e tu só confere.\n\n"
        f"Sendo bem sincero: por {PRICE_STARTER} isso é barato pelo tempo que tu economiza.\n\n"
        + CTA_SITE
    ),
    "cabeleireiro": (
        "No teu caso, eu cuido da agenda, mostro horários livres, passo valores e marco tudo sem te incomodar.\n"
        "Teu cliente marca e tu só confere.\n\n"
        f"Sendo bem sincero: por {PRICE_STARTER} isso é barato pelo tempo que tu economiza.\n\n"
        + CTA_SITE
    ),
    "dentista": (
        "Puxa! Sendo dentista, eu marco consulta, confirmo horário e organizo o atendimento no WhatsApp.\n"
        "Tu ganha tempo e passa mais confiança pro paciente.\n\n"
        f"Por {PRICE_STARTER} por mês, é bem barato pelo resultado.\n\n"
        + CTA_SITE
    ),
    "comida": (
        "Pra quem vende comida, eu ajudo a anotar pedido certinho, confirmar, e deixar a rotina mais organizada.\n"
        "Tu perde menos pedido e atende mais rápido.\n\n"
        f"Por {PRICE_STARTER} por mês, costuma se pagar fácil.\n\n"
        + CTA_SITE
    ),
    "lanches": (
        "Pra quem vende lanches, eu ajudo a anotar pedido certinho, confirmar, e deixar a rotina mais organizada.\n"
        "Tu perde menos pedido e atende mais rápido.\n\n"
        f"Por {PRICE_STARTER} por mês, costuma se pagar fácil.\n\n"
        + CTA_SITE
    ),
    "servico": (
        "Pra prestador de serviço, eu respondo dúvidas, passo preços e organizo contatos.\n"
        "Menos ligação fora de hora, mais atendimento profissional.\n\n"
        f"Por {PRICE_STARTER} por mês, costuma se pagar fácil.\n\n"
        + CTA_SITE
    ),
}

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
    # mapeamento leve
    if any(k in t for k in ("cabelo", "cabeleireir", "barbear", "salão", "salao", "beleza", "unha", "estética", "estetica")):
        return "beleza"
    if "dent" in t or "odonto" in t:
        return "dentista"
    if any(k in t for k in ("lanche", "lanches", "hamburg", "pizza", "comida", "marmita", "delivery", "restaurante")):
        return "lanches"
    if any(k in t for k in ("serviço", "servico", "prestador", "conserto", "reforma", "instala", "manutenção", "manutencao")):
        return "servico"
    return ""

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
    try:
        msgs = (change or {}).get("messages") or []
        if msgs and isinstance(msgs, list):
            m0 = msgs[0] or {}
            return str(m0.get("from") or "").strip()
    except Exception:
        pass
    return ""

# =========================
# Estado em cache/kv (TTL)
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

def _state_key(from_e164: str) -> str:
    return f"sales:lead:{from_e164}"

def _load_state(from_e164: str) -> Dict[str, Any]:
    st = _kv_get(_state_key(from_e164)) or {}
    if not isinstance(st, dict):
        st = {}
    return st

def _save_state(from_e164: str, st: Dict[str, Any]) -> None:
    ttl = int(os.getenv("SALES_LEAD_TTL_SECONDS", "604800") or "604800")  # 7 dias
    st["updated_at"] = _now_iso()
    _kv_set(_state_key(from_e164), st, ttl_seconds=ttl)

# =========================
# Core: gerar resposta
# =========================

def _reply_from_state(text_in: str, st: Dict[str, Any]) -> str:
    name = (st.get("name") or "").strip()
    segment = (st.get("segment") or "").strip()
    stage = (st.get("stage") or "").strip() or "ASK_NAME"
    turns = int(st.get("turns") or 0)
    turns += 1
    st["turns"] = turns

    intent = _intent(text_in)

    # 0) Intenções diretas (preço/planos/diferença) — mas ainda respeita coleta de nome/segmento
    if intent in ("WHAT_IS",):
        # sempre puxa pra nome depois
        st["stage"] = "ASK_NAME"
        return WHAT_IS

    # 1) Captura nome se não temos
    if not name:
        maybe = _extract_name_freeform(text_in)
        if maybe and not _looks_like_greeting(maybe):
            st["name"] = maybe
            st["stage"] = "ASK_SEGMENT"
            return ASK_SEGMENT.format(name=maybe)
        st["stage"] = "ASK_NAME"
        return OPENING_ASK_NAME

    # 2) Captura segmento se não temos
    if not segment:
        seg = _extract_segment(text_in)
        if seg:
            st["segment"] = seg
            st["stage"] = "PITCH"
        else:
            # se o lead perguntou preço antes de dizer o ramo, responde e volta pra ramo
            if intent in ("PRICE", "PLANS", "DIFF"):
                st["stage"] = "ASK_SEGMENT"
                if intent == "PRICE":
                    return PRICE_REPLY
                if intent == "DIFF":
                    return PLUS_DIFF + "\n\n" + "Agora me diz teu ramo que eu te explico onde isso encaixa 🙂"
                return PLANS_SHORT
            st["stage"] = "
