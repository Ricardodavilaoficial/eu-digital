# OTICA_FIRESTORE_APPLY_RUNBOOK_V1

## Objetivo

Roteiro para aplicar futuramente o runtime compacto da Ótica no Firestore.

## Arquivos

JSON:
kb_seed_v1/subsegments/comercio_varejista__loja_oculos_runtime_compact_v1.json

Script:
kb_seed_v1/scripts/apply_subsegment_patch.py

## Documento Firestore alvo

Coleção:
kb_subsegments_v1

Documento:
comercio_varejista__loja_oculos

## Antes de aplicar

Validar JSON:

```cmd
python -m json.tool kb_seed_v1\subsegments\comercio_varejista__loja_oculos_runtime_compact_v1.json > nul

