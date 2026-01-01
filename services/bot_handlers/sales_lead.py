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

SITE_URL = "www.meirobo.com.br"

PRICE_STARTER = "R$ 89/mês"
PRICE_PLUS = "R$ 119/mês"
PLUS_DIFF = "A única diferença é o espaço de memória: Starter tem 2 GB e o Starter+ tem 10 GB. O resto é igual."

OPENING_ASK_NAME = (
    "Oi! 👋 Eu sou o MEI Robô 🙂\n\n"
    "Antes de te explicar direitinho,\n"
    "me diz teu nome?"
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_SALES_NLU_MODEL = os.getenv("OPENAI_SALES_NLU_MODEL", os.getenv("OPENAI_NLU_MODEL", "gpt-4o-mini"))
SALES_NLU_TIMEOUT = 20
OPENAI_SALES_MODEL = os.getenv("OPENAI_SALES_MODEL", os.getenv("OPENAI_NLU_MODEL", "gpt-4o-mini"))


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


def _pitch_cache_key(segment: str, hint: str) -> str:
    segment = (segment or "geral").strip().lower()
    hint = (hint or "default").strip().lower()
    return f"sales:pitch:{segment}:{hint}"

def _get_cached_pitch(segment: str, hint: str) -> Optional[str]:
    try:
        raw = _kv_get(_pitch_cache_key(segment, hint))
        if isinstance(raw, dict):
            v = raw.get("pitch") or ""
            return str(v).strip() if v else None
        if isinstance(raw, str):
            return raw.strip() or None
    except Exception:
        return None
    return None

def _set_cached_pitch(segment: str, hint: str, pitch: str) -> None:
    try:
        ttl = int(os.getenv("SALES_PITCH_CACHE_TTL_SECONDS", "86400") or "86400")  # 24h
        _kv_set(_pitch_cache_key(segment, hint), {"pitch": pitch}, ttl_seconds=ttl)
    except Exception:
        pass

def _ai_pitch(name: str, segment: str, user_text: str) -> str:
    """
    Gera pitch curto via IA (somente aqui).
    Regras:
      - WhatsApp, frases curtas, humano, humor leve.
      - Foco: conta bancária mais positiva / tempo / profissionalismo.
      - Proibido: qualquer bastidor, tecnologia, IA, "como funciona por dentro".
      - 2 a 4 linhas no máximo.
    """
    name = (name or "").strip()
    segment = (segment or "").strip()

    # >>> AQUI entra a tua chamada de IA padrão <<<
    # Troca o bloco abaixo pela função/client que vocês já usam no pilar NLU.
    # Exemplo: return call_llm(prompt, model="gpt-4o-mini", max_tokens=120, temperature=0.4)
    try:
        prompt = (
            f"Você é o atendente de vendas do MEI Robô no WhatsApp.\n"
            f"Fale com {name}.\n"
            f"Segmento: {segment}.\n"
            f"Mensagem do lead: {user_text}\n\n"
            f"Escreva um pitch curto (2 a 4 linhas), humano, simples, com humor leve.\n"
            f"Mostre onde isso ajuda no dia a dia do segmento e puxe para: mais tempo, rotina mais profissional e conta bancária mais positiva.\n"
            f"NUNCA mencione tecnologia, IA, bastidores, processos, integrações.\n"
            f"NÃO cite preços nem site.\n"
        )

        # TODO: Substituir por chamada real do teu LLM (pilar NLU).
        # fallback ultra conservador se não conseguir chamar IA:
        return (
            f"Fechado, {name} 😄\n"
            f"No teu negócio, eu tiro do teu colo as mensagens repetidas e deixo o atendimento mais redondo.\n"
            f"Isso costuma dar mais tempo livre e mais dinheiro no fim do mês."
        )

    except Exception:
        return (
            f"Fechado, {name} 😄\n"
            f"No teu negócio, eu tiro do teu colo as mensagens repetidas e deixo o atendimento mais redondo.\n"
            f"Isso costuma dar mais tempo livre e mais dinheiro no fim do mês."
        )

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
    IA só no pitch (2 a 4 linhas). Proibido bastidores.
    NÃO cita preço nem site (isso entra fixo fora).
    """
    name = (name or "").strip()
    segment = (segment or "").strip()
    user_text = (user_text or "").strip()

    prompt = (
        f"Lead: {name}\n"
        f"Segmento do lead: {segment}\n"
        f"Última mensagem do lead: {user_text}\n\n"
        "Escreva um pitch curtinho (2 a 4 linhas) no estilo WhatsApp.\n"
        "Fale simples, humano, com humor leve.\n"
        "Mostre onde isso ajuda no dia a dia desse segmento.\n"
        "Feche reforçando: mais tempo, rotina mais profissional e conta bancária mais positiva.\n"
        "PROIBIDO mencionar tecnologia, IA, sistema, integração, processos ou bastidores.\n"
        "NÃO cite preço e NÃO cite site.\n"
    )

    txt = _openai_chat(prompt, max_tokens=140, temperature=0.45).strip()
    if not txt:
        # fallback ultra conservador (humano, sem bastidor)
        return (
            f"Fechado, {name} 😄\n"
            "Eu tiro do teu colo as mensagens repetidas e deixo o atendimento mais redondo.\n"
            "Isso costuma dar mais tempo livre e mais dinheiro no fim do mês."
        )

    # limita a 4 linhas pra ficar WhatsApp e barato
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    if len(lines) > 4:
        lines = lines[:4]
    return "\n".join(lines).strip()



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
        return {"route": "sales", "intent": "OTHER", "name": "", "segment": ""}

    system = (
        "Você é um CLASSIFICADOR de mensagens do WhatsApp do MEI Robô (pt-BR). "
        "Responda SOMENTE JSON válido (sem texto extra).\n\n"
        "Objetivo: decidir se a mensagem é sobre o produto/serviço MEI Robô (vendas) "
        "OU se é um assunto aleatório (caiu no número errado) "
        "OU se é um pedido de emergência (bombeiros/polícia/SAMU).\n\n"
        "REGRA MÃE (muito importante):\n"
        "- Se NÃO for claramente sobre o MEI Robô, route DEVE ser 'offtopic'.\n"
        "- Só use 'sales' quando for saudação (oi/bom dia etc.) OU quando a pessoa estiver falando do MEI Robô "
        "(preço, plano, assinar, ativar, indicação, 'me falaram desse número', 'quero entender o serviço', etc.).\n\n"
        "EMERGENCY:\n"
        "- Se pedir telefone dos bombeiros/polícia/SAMU/ambulância, ou mencionar 190/192/193 => route='emergency'.\n"
        "- Em emergency, intent='OTHER', name/segment vazios.\n\n"
        "OFFTOPIC:\n"
        "- Exemplos típicos: capital de país, previsão do tempo, perguntas escolares, assuntos gerais que não citam MEI Robô.\n"
        "- Nesses casos: route='offtopic', intent='OTHER', name/segment vazios.\n\n"
        "SALES intents:\n"
        "- PRICE: preço/valor/mensalidade\n"
        "- PLANS: planos/starter/starter+\n"
        "- DIFF: diferença entre planos/memória 2GB vs 10GB\n"
        "- ACTIVATE: ativar/criar conta/assinar/começar\n"
        "- WHAT_IS: o que é / o que você faz (sobre MEI Robô)\n"
        "- OTHER: conversa sobre MEI Robô sem cair nas categorias acima\n\n"
        "Extração:\n"
        "- name: só quando a pessoa realmente disser o nome (ex: 'Ricardo', 'me chamo Ana'). Nunca chute.\n"
        "- segment: só quando a pessoa disser o ramo (ex: 'barbearia', 'sou barbeiro', 'dentista'). Nunca chute.\n"
        "- Se a pessoa disser só 'Barbearia', isso é segment (não é name).\n\n"
        "Formato de saída (obrigatório):\n"
        "{"
        "\"route\":\"sales|offtopic|emergency\","
        "\"intent\":\"PRICE|PLANS|DIFF|ACTIVATE|WHAT_IS|OTHER\","
        "\"name\":\"\","
        "\"segment\":\"\""
        "}"
    )

    user = f"Mensagem: {text}"

    content = _sales_nlu_http([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])

    if not content:
        # fallback conservador: assume sales (pede nome) — mantém pilar, sem travar
        return {"route": "offtopic", "intent": "OTHER", "name": "", "segment": ""}

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
        return {"route": route, "intent": intent, "name": name, "segment": segment}
    except Exception:
        return {"route": "offtopic", "intent": "OTHER", "name": "", "segment": ""}

def _reply_from_state(text_in: str, st: Dict[str, Any]) -> str:
    name = (st.get("name") or "").strip()
    segment = (st.get("segment") or "").strip()
    stage = (st.get("stage") or "").strip() or "ASK_NAME"
    turns = int(st.get("turns") or 0)
    turns += 1
    st["turns"] = turns

    intent = _intent(text_in)
    nlu = sales_micro_nlu(text_in, stage=stage)
    # route (sales/offtopic/emergency) é decidido por IA
    route = nlu.get("route") or "sales"

    # se IA extraiu nome/segmento, aproveita
    if not name and (nlu.get("name") or ""):
        st["name"] = (nlu.get("name") or "").strip()
        name = st["name"]
    if not segment and (nlu.get("segment") or ""):
        st["segment"] = (nlu.get("segment") or "").strip()
        segment = st["segment"]

    # intent canônico vindo da IA (não por palavra)
    intent = (nlu.get("intent") or intent or "OTHER").strip().upper()

    if route == "emergency":
        return "Se for emergência, liga 193 agora. 🙏"

    if route == "offtopic":
        return "Oi! Esse WhatsApp é do MEI Robô 🙂 Acho que tu caiu no número errado."


    # 0) Intenções diretas (preço/planos/diferença) — mas ainda respeita coleta de nome/segmento
    if intent in ("WHAT_IS",):
        # sempre puxa pra nome depois
        st["stage"] = "ASK_NAME"
        return WHAT_IS

    # 1) Captura nome se não temos (IA decide; não usar heurística aqui)
    if not name:
        # Saudação pura = SALES -> pede nome, mas NÃO persiste ainda (persistência é fora daqui)
        st["stage"] = "ASK_NAME"
        return OPENING_ASK_NAME

    # 2) Captura segmento se não temos
    if not segment:
        seg = _extract_segment(text_in)
        if seg:
            st["segment"] = seg
            segment = seg
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

            st["stage"] = "ASK_SEGMENT"
            return f"Show, {name} 😄\n\nTeu negócio é do quê?"

    # 3) Temos nome + segmento: entregar valor + preço como diferencial + CTA site
    if intent == "PRICE":
        return PRICE_REPLY
    if intent == "PLANS":
        return PLANS_SHORT
    if intent == "DIFF":
        return PLUS_DIFF + "\n\n" + CTA_SITE
    if intent == "ACTIVATE":
        return CTA_SITE
    # IA só no pitch (com cache) — preço/CTA ficam fixos
    hint = intent or "OTHER"
    cached = _get_cached_pitch(segment, hint, text_in)
    if cached:
        pitch_txt = cached
    else:
        pitch_txt = _ai_pitch(name=name, segment=segment, user_text=text_in)
        pitch_txt = (pitch_txt or "").strip()
        if pitch_txt:
            _set_cached_pitch(segment, hint, text_in, pitch_txt)

    add_value = f"Sendo bem sincero: por {PRICE_STARTER} por mês, costuma se pagar fácil."
    return f"{pitch_txt}\n\n{add_value}\n\n{CTA_SITE}"

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

    st = _load_state(from_e164)
    reply = _reply_from_state(text_in, st)
    # Só salva estado se tiver nome (lead real)
    if (st.get("name") or "").strip():
        _save_state(from_e164, st)

    return (reply or "").strip() or OPENING_ASK_NAME


def handle_sales_lead(change_value: Dict[str, Any]) -> Dict[str, Any]:
    """
    Entrada única do handler de vendas (lead).
    Recebe um payload compat (change.value) e devolve {replyText}.
    """
    text_in = _extract_inbound_text(change_value) or ""
    from_e164 = _extract_sender(change_value) or ""
    if not from_e164:
        return {"replyText": OPENING_ASK_NAME}

    st = _load_state(from_e164)
    reply = _reply_from_state(text_in, st)
    if (st.get("name") or "").strip():
        _save_state(from_e164, st)

    return {"replyText": reply}

