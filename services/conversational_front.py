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
FRONT_ANSWER_MAX_TOKENS = int(os.getenv("FRONT_ANSWER_MAX_TOKENS", "260") or 260)  # saída do modelo
FRONT_KB_MAX_CHARS = int(os.getenv("FRONT_KB_MAX_CHARS", "2500") or 2500)          # entrada (snapshot)
FRONT_REPLY_MAX_CHARS = int(os.getenv("FRONT_REPLY_MAX_CHARS", "900") or 900)      # corte final (anti-textão)

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
- Regra de ouro: responda PRIMEIRO a pergunta do usuário de forma direta (sim/não ou a informação pedida) em 1 frase.
- Só depois (se fizer sentido), complemente com 1 frase curta e faça no máximo 1 pergunta prática para avançar.
- Evite começar com um "pitch" padrão quando o usuário fez uma pergunta objetiva.
- Quando a confiança for BAIXA, faça APENAS 1 pergunta prática.
- Nada de listas longas ou menus artificiais.
- Pode explicar melhor quando a intenção estiver clara.
- Use o KB Snapshot como fonte da verdade do produto. Se não estiver no snapshot, NÃO invente.
- Respostas: diretas, consultivas, com humor leve quando couber. Sem textão.

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

Exemplo rápido de estilo:
Usuário: "Posso tirar dúvidas por aqui?"
Você: "Sim — pode mandar suas dúvidas por aqui mesmo. Quer falar de agenda, preço ou ativação?"
"""

# -----------------------------
# Função principal
# -----------------------------
def handle(*, user_text: str, state_summary: Dict[str, Any], kb_snapshot: str = "") -> Dict[str, Any]:
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


    last_intent = str(state_summary.get("last_intent") or "").strip().upper()
    last_user_goal = str(state_summary.get("last_user_goal") or "").strip()
    kb_snapshot = (kb_snapshot or "").strip()
    if kb_snapshot:
        kb_snapshot = kb_snapshot[:FRONT_KB_MAX_CHARS]

    # Mensagens curtas para controle de custo
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""
Mensagem do usuário:
\"\"\"{user_text}\"\"\"

Turno atual: {ai_turns}


Contexto curto (se existir; não invente):
+- last_intent: {last_intent or "NONE"}
+- last_user_goal: {last_user_goal or "NONE"}
KB Snapshot (fonte da verdade, compacto; não invente fora disso):
\"\"\"
{kb_snapshot}
\"\"\"

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
            max_tokens=FRONT_ANSWER_MAX_TOKENS,
            messages=messages,
        )

        # -----------------------------
        # Uso de tokens (telemetria)
        # -----------------------------
        token_usage = {}
        try:
            u = getattr(resp, "usage", None)
            if u:
                token_usage = {
                    "input_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
                    "output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(u, "total_tokens", 0) or 0),
                }
        except Exception:
            token_usage = {}

        raw = resp.choices[0].message.content.strip()
        # -----------------------------
        # Parse seguro do JSON
        # -----------------------------
        import json
        import re

        # Alguns modelos devolvem JSON com texto extra ou em bloco ```json ...```.
        # Extraímos o primeiro objeto { ... } para reduzir fallback por parse.
        raw_json = raw
        try:
            m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if m:
                raw_json = m.group(0)
        except Exception:
            raw_json = raw

        data = json.loads(raw_json)
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
            "replyText": reply_text[:FRONT_REPLY_MAX_CHARS].rstrip(),
            "understanding": {
                "topic": topic,
                # Harmoniza com o resto do pipeline (sales_lead/outbox)
                "intent": topic,
                "confidence": confidence,
            },
            "nextStep": next_step,
            "shouldEnd": should_end,
            "nameUse": name_use,
            "prefersText": True,
            # Auditoria: quem respondeu
            "replySource": "front",
            # Probe leve do snapshot (ajuda a ver se o front "passou fome")
            "kbSnapshotSizeChars": len(kb_snapshot or ""),
            # Telemetria de custo (best-effort)
            "tokenUsage": token_usage,
        }

        # -----------------------------
        # Observabilidade leve
        # -----------------------------
        logging.info(
            "[CONVERSATIONAL_FRONT] ai_turns=%s topic=%s confidence=%s nextStep=%s shouldEnd=%s kbChars=%s tok=%s",
            ai_turns,
            topic,
            confidence,
            next_step,
            should_end,
            len(kb_snapshot or ""),
            token_usage or {},
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
