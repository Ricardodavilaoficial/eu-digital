# OTICA_FIRESTORE_MAPPING_V1

## Objetivo

Mapear o runtime compacto da Ótica para campos futuros no Firestore.

## Documento alvo

Coleção:
kb_subsegments_v1

Documento:
comercio_varejista__loja_oculos

## Origem

docs/subsegments/OTICA_RUNTIME_COMPACT_V1.md

## Campos novos sugeridos

- runtime_compact_enabled
- runtime_compact_version
- runtime_compact
- consultant_decision_sequence
- technical_expertise_compact
- behavioral_clusters_compact
- information_gap_patterns
- risk_alert_patterns
- trust_building_patterns
- failure_patterns
- subscriber_customization_slots

## Regra de aplicação

Aplicar sempre com merge=True.

Nunca sobrescrever o documento inteiro.

## Regra de runtime

O Firestore pode ter conteúdo rico.

O GPT-4o-mini deve receber apenas recortes compactos.

