\
# services/brain/boxes/clarify.py
# Caixa: CLARIFY (1 pergunta) — corta interrogatório, mantém humano.

from __future__ import annotations

def render_one_question(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return "Só pra eu te responder certinho: qual é a sua dúvida principal agora?"
    # Garante 1 pergunta e curta
    q = q.replace("\n", " ").strip()
    if q.count("?") > 1:
        q = q.split("?")[0].strip() + "?"
    return q
