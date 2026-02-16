# services/budget_intent_detector.py
# Detector leve de intenção para envio de orçamento por e-mail
# Seguro, barato e fail-safe

from __future__ import annotations

import os
import json
import logging
from typing import Dict, Any

try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None


_MODEL = os.getenv("LLM_MODEL_INTENT", "gpt-4o-mini")
_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_INTENT", "60"))
_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE_INTENT", "0.1"))


def _client():
    if not OpenAI:
        return None
    try:
        return OpenAI()
    except Exception:
        return None


def detect_budget_email_intent(
    *,
    text: str,
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Detecta intenção de envio de orçamento por e-mail.
    Nunca lança exceção.
    Sempre retorna dict seguro.
    """

    if not text or len(text.strip()) < 3:
        return {"intent": "none", "confidence": 0.0}

    client = _client()
    if not client:
        return {"intent": "none", "confidence": 0.0}

    context_summary = ""
    if context:
        # contexto leve (ex: último serviço citado)
        last_service = context.get("last_service") or ""
        last_price = context.get("last_price") or ""
        if last_service:
            context_summary += f"Serviço discutido: {last_service}\n"
        if last_price:
            context_summary += f"Valor mencionado: {last_price}\n"

    prompt = f"""
Você é um classificador semântico.

Analise a mensagem abaixo e determine se o cliente está pedindo
para FORMALIZAR ou ENVIAR um orçamento por e-mail.

Não dependa de palavras específicas.
Considere variações naturais do português brasileiro.

Responda apenas JSON no formato:

{{
  "intent": "send_budget_email" ou "none",
  "confidence": número entre 0 e 1
}}

Contexto:
{context_summary}

Mensagem:
{text}
"""

    try:
        response = client.chat.completions.create(
            model=_MODEL,
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": "Você responde apenas JSON válido."},
                {"role": "user", "content": prompt},
            ],
        )

        content = response.choices[0].message.content.strip()

        parsed = json.loads(content)

        intent = parsed.get("intent")
        confidence = float(parsed.get("confidence") or 0.0)

        if intent not in ("send_budget_email", "none"):
            return {"intent": "none", "confidence": 0.0}

        return {
            "intent": intent,
            "confidence": max(0.0, min(confidence, 1.0)),
        }

    except Exception as e:
        logging.warning("budget_intent_detector_fail: %s", e)
        return {"intent": "none", "confidence": 0.0}
