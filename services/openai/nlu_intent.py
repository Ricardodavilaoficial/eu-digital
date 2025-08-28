# services/openai/nlu_intent.py
# NLU enxuto com OpenAI: extrai intent, serviceName, dateText, is_price_question.
# Mantém custo baixo; falha graciosa para fallback por regras.

import os, json, requests
from typing import List, Dict, Any

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_NLU_MODEL = os.getenv("OPENAI_NLU_MODEL", "gpt-4o-mini")
TIMEOUT = 20

_SYSTEM = """Você é o NLU do MEI Robô (pt-BR). Responda SOMENTE JSON válido.
Objetivo: extrair intenção, serviço e data/hora de mensagens reais (texto curto ou transcrição de áudio).
Campos:
- intent: oneof["precos","agendar","reagendar","cancelar","saudacao","smalltalk","fallback"]
- serviceName: string|null  (nome curto do serviço citado)
- dateText: string|null     (ex.: "01/09 14:00", "amanhã 10h", "terça 15:30")
- is_price_question: boolean

Regras:
- Se perguntar preço (ex.: "quanto custa", "quanto tá", "valor de..."), marque is_price_question=true (mesmo se intent="precos").
- Nunca invente serviço fora da lista conhecida; se não tiver claro, deixe serviceName=null.
- Se não entender, use intent="fallback".
"""

def _allowed_services_block(services: List[str]) -> str:
    if not services:
        return "Serviços conhecidos: (nenhum fornecido)."
    uniq = sorted({(s or "").strip() for s in services if s and s.strip()})
    return "Serviços conhecidos: " + ", ".join(uniq) + "."

def _http_chat(messages: list) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        return {"intent":"fallback","serviceName":None,"dateText":None,"is_price_question":False}
    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": OPENAI_NLU_MODEL,
        "temperature": 0.2,
        "max_tokens": 250,
        # Onde suportado, força JSON:
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    r = requests.post(url, headers=headers, json=data, timeout=TIMEOUT)
    r.raise_for_status()
    js = r.json()
    content = js["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except Exception:
        # fallback defensivo
        return {"intent":"fallback","serviceName":None,"dateText":None,"is_price_question":False}

def analyze_message(text: str, services: List[str]) -> Dict[str, Any]:
    user_ctx = _allowed_services_block(services)
    messages = [
        {"role":"system","content":_SYSTEM},
        {"role":"user","content": user_ctx + "\nUsuário: " + (text or "")}
    ]
    out = _http_chat(messages)
    intent = (out.get("intent") or "fallback").strip().lower()
    if intent not in {"precos","agendar","reagendar","cancelar","saudacao","smalltalk","fallback"}:
        intent = "fallback"
    svc = out.get("serviceName")
    if isinstance(svc, str):
        svc = svc.strip() or None
    date_text = out.get("dateText")
    if isinstance(date_text, str):
        date_text = date_text.strip() or None
    is_price = bool(out.get("is_price_question"))
    res = {"intent":intent,"serviceName":svc,"dateText":date_text,"is_price_question":is_price}
    # não expomos notas; mantemos o mínimo necessário
    return res
