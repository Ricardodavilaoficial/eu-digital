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
