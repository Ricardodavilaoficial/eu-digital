# services/llm.py
from __future__ import annotations
import os
import openai

def gpt_mini_complete(prompt: str, max_tokens: int = 220) -> str:
    """
    Wrapper econômico para completions (chat) usado no acervo.
    Compatível com openai==0.28.1 (ChatCompletion).
    """
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY ausente")
    openai.api_key = api_key

    model = (os.getenv("LLM_MODEL_ACERVO") or "gpt-4o-mini").strip()
    temperature = float(os.getenv("LLM_TEMPERATURE_ACERVO") or "0.2")

    resp = openai.ChatCompletion.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": "Você é um assistente econômico. Responda de forma curta, clara e útil."},
            {"role": "user", "content": prompt},
        ],
    )
    return (resp.choices[0].message.get("content") or "").strip()
