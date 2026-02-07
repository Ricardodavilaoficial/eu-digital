# services/conversational_front.py
# Conversational Front v1.0 — MEI Robô
#
# Papel:
# - Intérprete inicial de conversa (vendedor humano)
# - Até MAX_AI_TURNS (hard cap decidido fora)
# - IA entende, responde e devolve metadados simples
#
# Regras:
# - NÃO grava Firestore
# - NÃO chama rotas de envio
# - NÃO gera áudio
# - NÃO executa ações
#
# Saída SEMPRE compatível com o worker
#
# 2026-02

from __future__ import annotations

import logging
from typing import Dict, Any

import os
from openai import OpenAI

# -----------------------------
# Configuração fixa (produto)
# -----------------------------
MODEL = "gpt-4o-mini"
TEMPERATURE = 0.5
MAX_TOKENS = 260  # resposta humana, sem textão infinito

_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# -----------------------------
# Enum fechado de tópicos
# -----------------------------
TOPICS = {
    "AGENDA",
    "PRECO",
    "ORCAMENTO",
    "VOZ",
    "SOCIAL",
    "OTHER",
}

# -----------------------------
# Prompt base (alma do vendedor)
# -----------------------------
SYSTEM_PROMPT = """
Você é o MEI Robô em modo VENDAS institucional.

Objetivo:
- Conversar como um vendedor humano, claro e útil.
- Entender a intenção do usuário e conduzir a conversa.
- Ajudar sem enrolar, sem menus, sem respostas robóticas.

Regras IMPORTANTES:
- NUNCA escreva o nome da pessoa no texto.
- Se quiser usar o nome, apenas sinalize via "nameUse".
- Quando a confiança for BAIXA, faça APENAS 1 pergunta prática.
- Nada de listas longas ou menus artificiais.
- Pode explicar melhor quando a intenção estiver clara.

Tópicos possíveis (escolha 1):
AGENDA, PRECO, ORCAMENTO, VOZ, SOCIAL, OTHER

Definições:
- PRECO = valores, planos, custo.
- ORCAMENTO = contratação, ativação, orçamento para o negócio.
- AGENDA = como clientes marcam horário.
- VOZ = áudio, responder por voz, voz clonada.
- SOCIAL = conversa casual, curiosidade, elogio.
- OTHER = fora do escopo.

Fechamento:
- Se o usuário pedir link, site, como assinar ou ativar:
  - nextStep = SEND_LINK
  - shouldEnd = true
"""

# -----------------------------
# Função principal
# -----------------------------
def handle(*, user_text: str, state_summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Entrada:
      - user_text: texto do usuário
      - state_summary: { ai_turns, is_lead, name_hint }

    Saída (contrato fixo):
      {
        replyText: str,
        understanding: { topic, confidence },
        nextStep: "NONE" | "SEND_LINK",
        shouldEnd: bool,
        nameUse: "none|greet|empathy|clarify",
        prefersText: bool
      }
    """

    ai_turns = int(state_summary.get("ai_turns") or 0)

    # Mensagens curtas para controle de custo
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""
Mensagem do usuário:
\"\"\"{user_text}\"\"\"

Turno atual: {ai_turns}

Responda em JSON estrito no formato:

{{
  "replyText": "...",
  "understanding": {{
    "topic": "AGENDA|PRECO|ORCAMENTO|VOZ|SOCIAL|OTHER",
    "confidence": "high|medium|low"
  }},
  "nextStep": "NONE|SEND_LINK",
  "shouldEnd": true|false,
  "nameUse": "none|greet|empathy|clarify"
}}
""",
        },
    ]

    try:
        resp = _client.chat.completions.create(
            model=MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            messages=messages,
        )

        raw = resp.choices[0].message.content.strip()

        # -----------------------------
        # Parse seguro do JSON
        # -----------------------------
        import json

        data = json.loads(raw)

        reply_text = str(data.get("replyText") or "").strip()
        understanding = data.get("understanding") or {}
        topic = str(understanding.get("topic") or "OTHER").upper()
        confidence = str(understanding.get("confidence") or "low").lower()

        if topic not in TOPICS:
            topic = "OTHER"

        next_step = data.get("nextStep") or "NONE"
        should_end = bool(data.get("shouldEnd"))
        name_use = data.get("nameUse") or "none"

        out = {
            "replyText": reply_text,
            "understanding": {
                "topic": topic,
                "confidence": confidence,
            },
            "nextStep": next_step,
            "shouldEnd": should_end,
            "nameUse": name_use,
            "prefersText": True,
        }

        # -----------------------------
        # Observabilidade leve
        # -----------------------------
        logging.info(
            "[CONVERSATIONAL_FRONT] ai_turns=%s topic=%s confidence=%s nextStep=%s shouldEnd=%s",
            ai_turns,
            topic,
            confidence,
            next_step,
            should_end,
        )

        return out

    except Exception as e:
        # Fail-safe absoluto: nunca quebrar o fluxo
        logging.exception("[CONVERSATIONAL_FRONT] erro, fallback silencioso: %s", e)

        return {
            "replyText": "Me conta um pouquinho melhor o que você quer resolver?",
            "understanding": {
                "topic": "OTHER",
                "confidence": "low",
            },
            "nextStep": "NONE",
            "shouldEnd": False,
            "nameUse": "clarify",
            "prefersText": True,
        }
