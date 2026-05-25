# Mapa de dependências — front_kb.py

## Funções analisadas

### _compact_kb_snapshot
Local atual:
- conversational_front.py:5500

Chamadas:
- dentro de _prepare_kb_snapshot_buffers

Conclusão:
Não mover isoladamente.

Motivo:
A função participa da preparação dos buffers de KB usados no handle().

### _prepare_kb_snapshot_buffers
Local atual:
- conversational_front.py:5651

Chamada:
- handle(): kb_snapshot, kb_compact, kb_snapshot_json_ok = _prepare_kb_snapshot_buffers(kb_snapshot)

Dependências:
- _compact_kb_snapshot
- _truncate
- FRONT_KB_MAX_CHARS
- json

Conclusão:
Se for movida, deve ir junto com _compact_kb_snapshot ou receber dependências explicitamente por parâmetro.

## Decisão
Não extrair nesta etapa.

## Próxima extração possível
Criar front_kb.py vazio/estrutural primeiro, sem mover lógica.
Depois mover apenas funções de leitura/parsing com dependências explícitas.

## Risco evitado
Evita regressão em:
- kb_snapshot runtime
- kb_compact prompt
- json_ok
- fallback global
- platform_kb_mode
