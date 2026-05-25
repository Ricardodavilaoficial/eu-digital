# Fronteira arquitetural — KB Runtime / Conversational Front

## Objetivo

Mapear a fronteira do núcleo KB/runtime antes de qualquer extração ou correção comportamental.

Este documento não altera código. Ele serve como guia de risco para a próxima fase da refatoração.

## Subfamília A — Lookup e segmentação

Funções centrais:

- `_infer_segment_from_text`
- `_infer_segment_from_docs`
- `_kb_lookup_operational_docs`
- `_best_doc_match`
- `_best_lookup_key_match`
- `_score_query_against_doc`
- `_lookup_token_overlap_score`
- `_keyword_doc_match`
- `_find_kb_map_anywhere`

Risco:

- alto acoplamento com `handle()`
- impacto direto em `kbUsed`, `kbContractId`, `kbDocPath`
- risco de regressão silenciosa
- risco de piorar fallback global
- risco de deformar inferência de segmento

Decisão:

- não mover isoladamente agora
- não corrigir comportamento nesta etapa
- só mexer depois de mapa de fluxo e testes específicos

## Subfamília B — Runtime pack/material

Funções centrais:

- `_platform_kb_resolve_runtime`
- `_platform_pack_material`
- `_platform_get_map`
- `_prepare_kb_snapshot_buffers`
- `_platform_apply_slots`
- `_compose_pack_runtime_short_reply`
- `_compose_pack_runtime_compact_reply`

Risco:

- médio/alto
- impacto no fallback global
- impacto em `platform_kb`
- impacto em resposta DIRECT
- impacto em conteúdo usado pelo assembly

Decisão:

- pode virar futuro módulo dedicado
- não mover sem script automático
- não mover sem backup
- não mover sem compile
- não mover sem validação WhatsApp
- não misturar com correção comportamental

## Possível módulo futuro

`services/front_kb_runtime.py`

Responsabilidade provável:

- preparar snapshot compacto
- resolver runtime pack
- aplicar slots
- montar material de pack
- expor funções puras para o `conversational_front.py`

Não deve assumir ainda:

- decisão de resposta final
- comportamento vendedor
- prompt
- chamada OpenAI
- handoff pós-5-turnos

## Regra de ouro

Antes de qualquer movimento no núcleo KB/runtime:

1. auditar chamadas;
2. mapear dependências;
3. escolher bloco coeso;
4. mover apenas por script;
5. criar backup;
6. compilar;
7. revisar diff;
8. deployar;
9. validar estrutura no WhatsApp;
10. registrar dívida comportamental separadamente.

## Decisão atual

Não mover lookup/segmentação agora.

Próximo candidato futuro, se a análise confirmar segurança:

- runtime pack/material, possivelmente para `front_kb_runtime.py`

Mas antes disso, rodar auditoria específica sobre:
- `_platform_apply_slots`
- `_compose_pack_runtime_short_reply`
- `_compose_pack_runtime_compact_reply`
- `_platform_pack_material`
- `_platform_kb_resolve_runtime`
- `_prepare_kb_snapshot_buffers`
