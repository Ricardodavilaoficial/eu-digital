# services/acervo.py
# Shim estável: reexporta o domínio canônico domain.acervo com assinatura compatível
# com chamadas legadas (services.acervo.query_acervo_for_uid).
#
# Safe-by-default: qualquer falha -> {"reason":"err",...}

from __future__ import annotations

from typing import Any, Dict


def query_acervo_for_uid(uid: str, pergunta: str, max_tokens: int = 120) -> Dict[str, Any]:
    try:
        from domain.acervo import query_acervo_for_uid as _q  # type: ignore
    except Exception:
        return {"reason": "err", "answer": "", "chunks": []}

    try:
        # Mantém defaults do domínio; só passamos max_tokens como o caller espera.
        out = _q(uid=uid, pergunta=pergunta, max_tokens=max_tokens) or {}
        if not isinstance(out, dict):
            return {"reason": "err", "answer": "", "chunks": []}
        # garante shape mínimo
        out.setdefault("reason", "")
        out.setdefault("answer", "")
        out.setdefault("chunks", [])
        return out
    except Exception:
        return {"reason": "err", "answer": "", "chunks": []}
