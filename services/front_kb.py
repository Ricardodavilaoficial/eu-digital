"""
Camada de KB do Conversational Front.

Este módulo será usado para isolar gradualmente funções relacionadas a:
- leitura/parsing de kb_snapshot;
- runtime de platform_kb;
- lookup de documentos operacionais;
- construção de contratos operacionais.

Regra desta fase:
- não alterar comportamento;
- não chamar rede;
- não acessar banco;
- mover apenas funções com dependências explícitas;
- preservar equivalência funcional.
"""

from __future__ import annotations

import json
from typing import Any, Dict


def _try_parse_kb_json(kb_snapshot: str) -> Dict[str, Any] | None:
    try:
        raw = str(kb_snapshot or "").strip()
        if raw and (raw.startswith("{") or raw.startswith("[")):
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        return None
    return None
