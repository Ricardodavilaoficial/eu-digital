# services/contact_memory.py
# Shim estável para compatibilizar imports do Customer Final com o domínio canônico.
#
# Motivo:
# - services/bot_handlers/customer_final.py importa services.contact_memory
# - mas o canônico existente está em domain/contact_memory.py e a assinatura é diferente.
#
# Este shim:
# - mantém o contrato esperado pelo customer_final (retornar dict com "summary")
# - chama domain.contact_memory.build_contact_context(...) por baixo
# - safe-by-default: qualquer falha -> {} (não quebra produção)

from __future__ import annotations

from typing import Any, Dict, Optional


def build_contact_context(
    uid: str,
    wa_key: str,
    value: Optional[Dict[str, Any]] = None,
    *,
    max_chars: int = 800,
) -> Dict[str, Any]:
    """
    Retorna dict no formato esperado pelo customer_final:
      { "summary": "<texto curto>" }
    """
    try:
        from domain.contact_memory import build_contact_context as _domain_build  # type: ignore
    except Exception:
        return {}

    try:
        ctx_str = _domain_build(uid, wa_key, value or {}, max_chars=max_chars) or ""
        ctx_str = str(ctx_str).strip()
        if not ctx_str:
            return {}
        return {"summary": ctx_str}
    except Exception:
        return {}
