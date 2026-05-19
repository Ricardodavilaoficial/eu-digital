"""
Utilitários puros do Conversational Front.

Regras:
- Sem chamadas de rede.
- Sem acesso a banco.
- Sem dependência de estado global.
- Apenas funções determinísticas.
"""

from __future__ import annotations

import re


def split_sentences_pt(text: str) -> list[str]:
    try:
        t = str(text or "").strip()
        if not t:
            return []
        parts = re.split(r'(?<=[.!?])\s+', t)
        return [p.strip() for p in parts if p.strip()]
    except Exception:
        return [str(text or "").strip()]


def has_question(text: str) -> bool:
    try:
        return "?" in str(text or "")
    except Exception:
        return False


def strip_trailing_question(text: str) -> str:
    try:
        t = str(text or "").strip()
        qpos = t.rfind("?")
        if qpos == -1:
            return t
        return t[:qpos].strip()
    except Exception:
        return str(text or "").strip()
