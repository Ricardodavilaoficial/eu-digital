# services/bot_handlers/sales_lead.py
# Handler isolado: Vendas (lead) — Opção B (2025-12-26)
# - Conteúdo público (sem dados privados)
# - Sem ações irreversíveis
# - Webhook deve ser "burro": este handler vive no wa_bot

from __future__ import annotations

import os
import time
import json
from typing import Any, Callable, Dict, Optional

def _now_iso() -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    except Exception:
        return ""

def _extract_inbound_text(change: Dict[str, Any]) -> str:
    """Extrai texto de um payload 'change.value' (Meta/YCloud compat)."""
    try:
        # formato Meta (value.messages[])
        msgs = (change or {}).get("messages") or []
        if msgs and isinstance(msgs, list):
            m0 = msgs[0] or {}
            if (m0.get("type") == "text") and isinstance(m0.get("text"), dict):
                body = (m0.get("text") or {}).get("body") or ""
                return str(body).strip()
        # formatos alternativos
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

def _fallback_pitch(app_tag: Optional[str] = None) -> str:
    brand = "MEI Robô"
    if app_tag:
        brand = brand
    return (
        f"Oi! 👋 Eu sou o {brand}.\n\n"
        "Eu automatizo seu WhatsApp pra você vender mais e perder menos tempo: \n"
        "• respondo clientes \n"
        "• organizo agenda \n"
        "• ajudo com preços/serviços\n\n"
        "Quer que eu te explique os planos? (responde: *planos*)\n"
        "Ou me diz rapidinho: qual é o seu negócio?"
    )

def _openai_chat(prompt: str) -> Optional[str]:
    """Gera resposta curta via OpenAI usando requests (sem SDK)."""
    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key:
        return None

    model = os.getenv("LLM_MODEL_SALES") or os.getenv("LLM_MODEL_ACERVO") or "gpt-4o-mini"
    max_tokens = int(os.getenv("LLM_MAX_TOKENS_SALES", "180") or "180")
    temperature = float(os.getenv("LLM_TEMPERATURE_SALES", "0.4") or "0.4")

    system = (
        "Você é o atendente de VENDAS do MEI Robô no WhatsApp. "
        "Responda em PT-BR, curto, simpático e direto. "
        "Explique valor sem jargão. Faça 1 CTA claro. "
        "Não peça dados sensíveis. Não prometa detalhes técnicos profundos. "
        "Nada de ações irreversíveis. "
        "Se a pessoa disser apenas 'oi/olá', apresente o produto e pergunte o ramo. "
        "Se perguntar preço, ofereça ver os planos. "
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        import requests  # type: ignore
    except Exception:
        return None

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=25,
        )
        if resp.status_code >= 400:
            return None
        js = resp.json() or {}
        choices = js.get("choices") or []
        if not choices:
            return None
        msg = (choices[0] or {}).get("message") or {}
        content = (msg.get("content") or "").strip()
        if content:
            return content
    except Exception:
        return None
    return None
    
def generate_reply(text: str, ctx: Optional[Dict[str, Any]] = None) -> str:
    """Retorna apenas o texto de resposta (usado pelo wa_bot.reply_to_text)."""
    ctx = ctx or {}

    text_in = (text or "").strip()

    # aceitar áudio como gatilho de resposta
    if not text_in:
        text_in = "Lead enviou um áudio."

    prompt = (
        f"Mensagem do lead: {text_in}\n\n"
        "Responda como vendas do MEI Robô. "
        "Finalize com uma pergunta curta para qualificar o lead."
    )

    out = _openai_chat(prompt) or _fallback_pitch(ctx.get("app_tag"))
    return (out or "").strip() or _fallback_pitch(ctx.get("app_tag"))

def handle_sales_lead(
    change: Dict[str, Any],
    send_text_fn: Callable[[str, str], Any],
    app_tag: Optional[str] = None,
) -> bool:
    """Retorna True se respondeu algo ao lead."""
    to_raw = _extract_sender(change) or ""
    text_in = _extract_inbound_text(change)

    # aceitar áudio como gatilho de resposta
    if not text_in:
        text_in = "Lead enviou um áudio."

    if not to_raw:
        return False

    prompt = (
        f"Mensagem do lead: {text_in}\n\n"
        "Responda como vendas do MEI Robô. "
        "Finalize com uma pergunta curta para qualificar o lead."
    )

    out = _openai_chat(prompt) or _fallback_pitch(app_tag)
    try:
        send_text_fn(to_raw, out)
        return True
    except Exception:
        return False
