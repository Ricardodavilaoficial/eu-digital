# services/phone_utils.py
# Utilitário canônico de telefone (BR) — v1 (2026-01-03)
# Objetivo: 1 forma de normalizar (sem quebrar compat).
# - digits_only: remove tudo que não é dígito
# - to_plus_e164: garante prefixo + nos dígitos
# - phone_variants_br: variações tolerantes ao '9' após DDD (BR)

from __future__ import annotations

from typing import List

def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def to_plus_e164(raw: str) -> str:
    d = digits_only(raw)
    if not d:
        return (raw or "").strip()
    return "+" + d

def phone_variants_br(e164: str) -> List[str]:
    """Gera variações comuns BR (com/sem '9' após DDD). Retorna sempre com '+' + dígitos."""
    s = (e164 or "").strip()
    if not s:
        return []
    digits = digits_only(s)
    if not digits:
        return []

    out: List[str] = []

    def add(x: str) -> None:
        x = to_plus_e164(x)
        if x and x not in out:
            out.append(x)

    add(digits)

    # Se já tem 55, tenta variantes com/sem 9
    if digits.startswith("55") and len(digits) >= 12:
        ddd = digits[2:4]
        num = digits[4:]
        if len(num) == 9 and num.startswith("9"):
            add("55" + ddd + num[1:])     # remove 9
        elif len(num) == 8:
            add("55" + ddd + "9" + num)   # adiciona 9
    else:
        # se vier sem 55 e parecer BR (>=10 dígitos), também tenta com 55
        if len(digits) in (10, 11):
            add("55" + digits)

    return out
