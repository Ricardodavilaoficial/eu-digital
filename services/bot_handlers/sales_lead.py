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
    "Hoje o plano Starter tá R$ 89/mês.\n"
    "E o Starter+ tá R$ 119/mês.\n\n"
    "A única diferença é o espaço de memória: Starter tem 2 GB e o Starter+ tem 10 GB. O resto é igual."
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
# Catálogo CANÔNICO (repertório operacional)
# - NÃO é resposta pronta
# - É matéria-prima para a IA escolher 1 cenário real e escrever curto
# =========================
OPERATIONAL_SCENARIOS: Dict[str, list] = {
    "geral": [
        {
            "situation": "Cliente chama no WhatsApp e pergunta coisas repetidas",
            "pain": "Interrupção constante e demora pra responder todo mundo",
            "action": "Responde o básico, organiza o atendimento e encaminha o que importa",
            "outcome": "Mais tempo livre e atendimento mais profissional",
        }
    ],
    "beleza": [
        {
            "situation": "Cliente pergunta horário o dia todo",
            "pain": "Interrupção constante e agenda confusa",
            "action": "Mostra horários livres, confirma o serviço e agenda",
            "outcome": "O profissional trabalha sem parar pra responder",
        },
        {
            "situation": "Cliente pergunta preço/serviço (corte, barba, etc.)",
            "pain": "Responder a mesma coisa toda hora",
            "action": "Explica serviços e valores automaticamente e já puxa pro agendamento",
            "outcome": "Cliente vem mais decidido e fecha mais rápido",
        },
    ],
    "lanches": [
        {
            "situation": "Pedidos chegam rápido no WhatsApp",
            "pain": "Erro de item/valor e atraso na entrega",
            "action": "Anota pedido, confirma itens e calcula o valor",
            "outcome": "Menos erro e mais pedido fechado",
        },
        {
            "situation": "Alguém só fica anotando pedido",
            "pain": "Gargalo e custo (gente anotando em vez de produzir)",
            "action": "Envia pro WhatsApp do MEI o pedido completo com valor, endereço e pagamento",
            "outcome": "A pessoa vai produzir, não anotar",
        },
    ],
    "dentista": [
        {
            "situation": "Paciente manda dúvidas longas antes de marcar",
            "pain": "Conversa que não vira consulta",
            "action": "Responde o básico, filtra e já oferece horários",
            "outcome": "Agenda só quem realmente quer",
        },
        {
            "situation": "Remarcação/confirmar horário vira um inferno",
            "pain": "Secretaria presa no WhatsApp",
            "action": "Confirma, remarca e organiza a agenda",
            "outcome": "Menos faltas e rotina mais leve",
        },
    ],
    "servico": [
        {
            "situation": "Cliente pergunta 'faz isso?' e some",
            "pain": "Vai-e-volta e perda de tempo",
            "action": "Coleta as informações essenciais e organiza o pedido",
            "outcome": "Orçamento mais rápido e atendimento mais profissional",
        },
        {
            "situation": "Contato e detalhes ficam perdidos no WhatsApp",
            "pain": "Esquece cliente e perde histórico",
            "action": "Organiza dados do cliente e o que foi combinado",
            "outcome": "Menos retrabalho e mais confiança",
        },
    ],
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
    try:
        msgs = (change or {}).get("messages") or []
        if msgs and isinstance(msgs, list):
            m0 = msgs[0] or {}
            return str(m0.get("from") or "").strip()
    except Exception:
        pass
    return ""

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
    IA só no pitch (2 a 4 linhas). Proibido bastidores.
    NÃO cita preço nem site (isso entra fixo fora).
    """
    name = (name or "").strip()
    segment = (segment or "").strip()
    user_text = (user_text or "").strip()

    # Puxa repertório operacional do segmento (fallback: geral)
    seg_key = _extract_segment(segment) or _extract_segment(user_text) or ""
    if not seg_key:
        seg_key = "geral"
    scenarios = OPERATIONAL_SCENARIOS.get(seg_key) or OPERATIONAL_SCENARIOS.get("geral") or []
    # manda no máx. 2 cenários pra não inflar tokens
    scenarios = scenarios[:2]

    prompt = (
        f"Lead: {name}\n"
        f"Segmento do lead (texto): {segment}\n"
        f"Segmento normalizado: {seg_key}\n"
        f"Última mensagem do lead: {user_text}\n\n"
        "Use APENAS 1 dos cenários operacionais abaixo como exemplo prático (não liste todos):\n"
        f"{json.dumps(scenarios, ensure_ascii=False)}\n\n"
        "Escreva um pitch curtinho (2 a 4 linhas) no estilo WhatsApp.\n"
        "Fale simples, humano, com humor leve.\n"
        "Mostre a diferença na prática (exemplo real do cenário escolhido).\n"
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
        return {"route": "sales", "intent": "OTHER", "name": "", "segment": "", "interest_level": "mid", "next_step": ""}

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
        "interest_level:\n"
        "- low: só curiosidade solta, sem sinais de compra\n"
        "- mid: perguntas de como funciona, exemplos, quer entender\n"
        "- high: pergunta preço + quer ativar/assinar, ou fala 'quero isso'\n\n"
        "next_step:\n"
        "- ASK_NAME: quando ainda falta nome\n"
        "- ASK_SEGMENT: quando falta ramo\n"
        "- VALUE: quando já tem nome+ramo e vale mostrar 1 cenário prático\n"
        "- PRICE: quando perguntou preço/planos (ou está high)\n"
        "- CTA: quando está pronto pra ir pro site/configurar\n"
        "- EXIT: quando é conversa fraca/sem aderência (responder curto e encerrar)\n\n"

        "Formato de saída (obrigatório):\n"
        "{"
        "\"route\":\"sales|offtopic|emergency\","
        "\"intent\":\"PRICE|PLANS|DIFF|ACTIVATE|WHAT_IS|OTHER\","
        "\"name\":\"\","
        "\"segment\":\"\","
        "\"interest_level\":\"low|mid|high\","
        "\"next_step\":\"ASK_NAME|ASK_SEGMENT|VALUE|PRICE|CTA|EXIT\""
        "}"
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
        return "Oi! Esse WhatsApp é do MEI Robô 🙂 Acho que tu caiu no número errado. Se tu tava procurando atendimento do MEI Robô, me diz teu nome que eu te ajudo."


    if stage == "EXIT":
        return "Beleza 🙂 Se quiser retomar sobre o MEI Robô, é só mandar aqui."


    # 0) Intenções diretas (preço/planos/diferença) — mas ainda respeita coleta de nome/segmento
    if intent in ("WHAT_IS",):
        # sempre puxa pra nome depois
        st["stage"] = "ASK_NAME"
        return WHAT_IS

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
            # se o lead perguntou preço/planos/diferença antes de dizer o ramo, responde curto e volta pro ramo
            if intent == "PRICE":
                st["stage"] = "ASK_SEGMENT"
                return PRICE_REPLY
            if intent == "PLANS":
                st["stage"] = "ASK_SEGMENT"
                return PLANS_SHORT
            if intent == "DIFF":
                st["stage"] = "ASK_SEGMENT"
                return PLUS_DIFF + "\n\n" + "Agora me diz teu ramo que eu te explico onde isso encaixa 🙂"

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
    if intent == "PRICE":
        # Responde preço SEM resetar conversa
        # Só pede o que estiver faltando (e de forma humana)
        msg = PRICE_REPLY

        name = (st.get("name") or "").strip()
        segment = (st.get("segment") or "").strip()

        if not name and not segment:
            msg += "\n\nPra eu te indicar o melhor no teu caso: qual teu nome e teu ramo?"
            st["stage"] = "ASK_NAME"
        elif not segment:
            msg += "\n\nE teu ramo é qual?"
            st["stage"] = "ASK_SEGMENT"
        else:
            msg += f"\n\nNo teu ramo ({segment}), quer que eu te diga qual costuma valer mais a pena?"
            st["stage"] = "PITCH"

        return msg
    if intent == "PLANS":
        return PLANS_SHORT
    if intent == "DIFF":
        return PLUS_DIFF + "\n\n" + CTA_SITE
    if intent == "ACTIVATE":
        # Só manda CTA direto quando o lead estiver quente
        if interest == "high":
            return CTA_SITE
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

    add_value = f"Sendo bem sincero: por {PRICE_STARTER} por mês, costuma se pagar fácil."

    # HIGH: pode aprofundar 1 linha + CTA
    if interest == "high" or intent == "ACTIVATE":
        extra = "Se tu quiser, eu te mostro um exemplo bem real em 2 mensagens e tu já sente o jeito."
        return f"{pitch_txt}\n{extra}\n\n{add_value}\n\n{CTA_SITE}"

    # MID: valor + preço (curto), SEM CTA (não vira panfleto)
    if interest == "mid":
        return f"{pitch_txt}\n\n{add_value}"

    # LOW: segurança
    return pitch_txt

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
    Entrada única do handler de vendas (lead).
    Recebe um payload compat (change.value) e devolve {replyText}.
    """
    text_in = _extract_inbound_text(change_value) or ""
    from_e164 = _extract_sender(change_value) or ""
    if not from_e164:
        return {"replyText": OPENING_ASK_NAME}

    # Reusa o fluxo canônico (áudio como gatilho + TTL curto quando não é lead)
    reply = generate_reply(text_in, ctx={"from_e164": from_e164})
    return {"replyText": reply}


