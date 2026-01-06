# services/phone_utils.py
# Utilitário canônico de telefone (BR) — v1 (2026-01-03)
# Objetivo: 1 forma de normalizar (sem quebrar compat).
# - digits_only: remove tudo que não é dígito
# - to_plus_e164: garante prefixo + nos dígitos
# - phone_variants_br: variações tolerantes ao '9' após DDD (BR)

from __future__ import annotations

from typing import List

import re

def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def normalize_e164_br(e164: str) -> str:
    """Normaliza para algo tipo E164 (+<digits>), com heurística BR.

    - Aceita: +55..., 55..., 00..., (51) 9xxxx-xxxx, etc.
    - Para BR com DDI 55:
        * Se tiver DDD + 9 + 8 dígitos (celular 11 dígitos nacionais), remove o '9' móvel e
          canonicaliza para +55DDXXXXXXXX.
        * Se tiver DDD + 8 dígitos (fixo), mantém.
    """
    s = re.sub(r"[^\d+]", "", (e164 or "").strip())
    if not s:
        return ""

    # 00xx... -> +xx...
    if s.startswith("00"):
        s = "+" + s[2:]

    # se veio sem '+', tenta inferir BR
    if not s.startswith("+"):
        digits = re.sub(r"\D+", "", s)
        if digits.startswith("55"):
            s = "+" + digits
        elif len(digits) in (10, 11):  # DDD + (8|9) dígitos
            s = "+55" + digits
        else:
            s = "+" + digits

    # garante só dígitos após '+'
    s = "+" + re.sub(r"\D+", "", s)

    # Heurística BR: canonicalizar removendo o '9' móvel (DDD + 9 + 8)
    digits = s[1:]
    if digits.startswith("55"):
        national = digits[2:]  # tudo após 55
        if len(national) == 11:
            ddd = national[:2]
            num = national[2:]
            if num.startswith("9") and len(num) == 9:
                s = "+55" + ddd + num[1:]
    return s

def to_plus_e164(raw: str) -> str:
    canon = normalize_e164_br(raw)
    if canon:
        return canon
    d = digits_only(raw)
    if not d:
        return (raw or "").strip()
    return "+" + d

def phone_variants_br(e164: str) -> List[str]:
    """Gera variações comuns BR (com/sem '9' após DDD).

    Regra: sempre começa do canônico (sem 9 móvel) e adiciona a variante com 9.
    Retorna sempre com '+' + dígitos.
    """
    base = to_plus_e164(e164)
    if not base:
        return []
    digits = digits_only(base)
    if not digits:
        return []

    out: List[str] = []

    def add(x: str) -> None:
        x = to_plus_e164(x)
        if x and x not in out:
            out.append(x)

    # 1) canônico primeiro (sem 9 quando BR)
    add(digits)

    # 2) variante BR com/sem 9 para tolerar WhatsApp/contatos
    if digits.startswith("55") and len(digits) >= 12:
        ddd = digits[2:4]
        num = digits[4:]
        if len(num) == 8:
            add("55" + ddd + "9" + num)  # adiciona 9
        elif len(num) == 9 and num.startswith("9"):
            add("55" + ddd + num[1:])  # remove 9 (garantia)

    return out

