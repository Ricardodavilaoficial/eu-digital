# FRONT FUNCTION CANDIDATES AUDIT

## Objetivo

Auditar candidatos de extração dentro do:

`services/conversational_front.py`

Este documento classifica helpers por:
- risco;
- soberania;
- estabilidade;
- acoplamento;
- readiness arquitetural.

---

# Descoberta central

Nem todo helper pequeno é:
`SAFE`

E nem todo helper grande é:
`HIGH RISK`

O fator decisivo é:
`SOBERANIA RUNTIME`

---

# Critérios oficiais de classificação

## EXTRACTION READY

Helper:
- determinístico;
- sem recovery;
- sem orchestration;
- sem runtime mutation;
- sem discovery governance;
- sem terminal control;
- sem response arbitration.

---

## SEMI-SAFE

Helper:
- parcialmente superficial;
- toca contexto operacional;
- pode depender de material runtime;
- mas ainda não governa runtime.

---

## SOVEREIGN

Helper:
- altera fluxo;
- arbitra modo;
- executa discovery;
- controla scene;
- altera continuidade runtime.

---

## HIGH RISK SOVEREIGN

Helper:
- executa recovery;
- executa resurrection;
- controla terminals;
- reconstrói operação;
- altera runtime tardiamente.

---

# EXTRACTION READY

## `_apply_response_mode_surface(...)`

Status:
- extraído;
- estável;
- compile limpo.

Novo módulo:
- `services/front_surface.py`

Classificação:
`PURE SAFE FINAL PIPELINE`

---

## `_restore_final_candidate_if_degraded(...)`

Status:
- extraído;
- estável;
- compile limpo.

Classificação:
`PURE SAFE FINAL PIPELINE`

---

# SEMI-SAFE CANDIDATES

## `_apply_final_reply_size_policy(...)`

Pode:
- truncar;
- sanitizar;
- reorganizar superfície.

Risco:
- ainda toca densidade operacional;
- ainda encosta em material runtime.

Classificação:
`SEMI-SAFE`

---

## `_apply_final_surface_polish(...)`

Pode:
- normalize;
- polish;
- limpar superfície.

Risco:
- ainda pode tocar enrichment operacional.

Classificação:
`SEMI-SAFE`

---

## `_upgrade_operational_reply_with_model(...)`

Responsabilidade:
- enhancement operacional.

Risco:
- depende de contexto;
- pode alterar densidade runtime;
- usa geração indireta.

Classificação:
`SEMI-SAFE / HIGH CONTEXT`

---

# SOVEREIGN CANDIDATES

## `_apply_response_mode_arbitration(...)`

Controla:
- DIRECT;
- DISCOVERY;
- SCENE;
- degradation;
- promotion.

Classificação:
`SOVEREIGN`

---

## `_apply_discovery_to_scene_bypass(...)`

Controla:
- DISCOVERY → SCENE.

Classificação:
`SOVEREIGN ORCHESTRATION`

---

## `_apply_current_turn_topic_reset(...)`

Controla:
- runtime continuity;
- topic contamination.

Classificação:
`SOVEREIGN`

---

## `_pick_runtime_scene_material(...)`

Controla:
- material selection;
- operational trajectory.

Classificação:
`SOVEREIGN ORCHESTRATION`

---

# HIGH RISK SOVEREIGN

## `_build_kb_show_reply(...)`

Executa:
- runtime recovery;
- fallback rebuilding;
- resurrection.

Classificação:
`HIGH RISK`

---

## `_build_kb_anchor_reply(...)`

Executa:
- operational recovery;
- runtime salvage.

Classificação:
`HIGH RISK`

---

## `_build_last_resort_operational_reply(...)`

Executa:
- terminal recovery;
- late runtime reconstruction.

Classificação:
`HIGH RISK`

---

# Reconstruction candidates

## `_generate_micro_scene_with_model(...)`

Executa:
- scene generation;
- progression construction.

Classificação:
`HIGH RISK SOVEREIGN`

---

## `_compose_grounded_scene_with_progression(...)`

Executa:
- grounded operational flow;
- runtime progression.

Classificação:
`HIGH RISK SOVEREIGN`

---

# Discovery governance candidates

## `_apply_discovery_mode_identity_guard(...)`

Executa:
- identity enforcement;
- discovery protection.

Classificação:
`SOVEREIGN`

---

## `_apply_identity_clarify_guard(...)`

Executa:
- clarify governance;
- discovery stabilization.

Classificação:
`SOVEREIGN`

---

# Helpers que NÃO devem sair agora

## Recovery helpers

Motivo:
- resurrection;
- orchestration leakage;
- fallback contamination.

---

## Terminal helpers

Motivo:
- bypasses;
- return ownership;
- payload protection.

---

## Arbitration helpers

Motivo:
- response_mode sovereignty;
- runtime trajectory.

---

# Critérios futuros para extração

Antes de mover qualquer helper:
- mapear callsites;
- mapear mutações;
- mapear terminals;
- validar ownership;
- validar recovery impact.

---

# SAFE vs HIGH RISK

## SAFE

Pode:
- sanitize;
- normalize;
- sync;
- polish;
- preservar superfície.

---

## HIGH RISK

Pode:
- alterar runtime;
- reabrir recovery;
- promover SCENE;
- alterar continuidade;
- reconstruir operação.

---

# Estado atual

A refatoração já validou:
- extrações PURE SAFE;
- boundaries saudáveis;
- compile incremental seguro.

Mas:
- orchestration;
- recovery;
- discovery;
- reconstruction;

ainda permanecem soberanos.

---

# Decisão consolidada

A prioridade correta NÃO é:
- aumentar quantidade de módulos;
- mover muitos helpers.

A prioridade correta é:
- mover apenas helpers realmente SAFE;
- impedir leakage soberano;
- preservar runtime integrity.

---

# Conclusão

O critério correto de extração é:

`SOBERANIA > TAMANHO`

Helpers pequenos ainda podem ser:
- perigosos;
- soberanos;
- destrutivos arquiteturalmente.

Enquanto helpers maiores podem continuar seguros se:
- determinísticos;
- superficiais;
- semanticamente estáveis.