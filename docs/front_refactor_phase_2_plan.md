# Fase 2 — Planejamento front_kb.py

## Decisão
Não mover funções de KB ainda.

## Motivo
As funções de KB estão fortemente acopladas ao handle(), ao kb_snapshot, platform_kb_mode, operational_contract, real_kb_docs e fallback runtime.

## Cluster KB identificado
- _compact_kb_snapshot
- _prepare_kb_snapshot_buffers
- _try_parse_kb_json
- _find_kb_map_anywhere
- _kb_lookup_operational_docs
- _merge_real_kb_operational_context
- _build_operational_contract
- _infer_segment_from_docs
- _platform_kb_resolve_runtime
- _platform_topic_from_kb_rules
- _platform_segment_profile_from_kb
- _platform_pack_from_profile
- _platform_pack_material
- _platform_get_map
- _front_build_continuity_reply_from_platform_kb

## Risco
Mover funções de KB sem fronteira clara pode reintroduzir:
- agenda bleeding
- resposta genérica
- kbUsed=false
- fallback global indevido
- scene sem hidratação real
- perda de segmentação

## Estratégia
Antes de extrair, criar front_kb.py com funções copiadas apenas quando:
1. dependências estiverem explícitas;
2. assinatura estiver estável;
3. imports forem conhecidos;
4. teste canônico estiver definido;
5. rollback estiver pronto.

## Próximo passo
Mapear dependências de _compact_kb_snapshot e _prepare_kb_snapshot_buffers antes de qualquer alteração.

