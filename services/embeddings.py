# services/embeddings.py
from __future__ import annotations
import os
import openai
from typing import List

def get_mini_embedding(text: str) -> List[float]:
    """
    Embedding econômico para acervo. Compatível com openai==0.28.1.
    """
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY ausente")
    openai.api_key = api_key

    model = (os.getenv("ACERVO_EMBEDDINGS_MODEL") or "text-embedding-3-small").strip()

    # corta pra evitar payload gigante
    t = (text or "").strip()
    if len(t) > 12000:
        t = t[:12000]

    resp = openai.Embedding.create(model=model, input=t)
    return resp["data"][0]["embedding"]
