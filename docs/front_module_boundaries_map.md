# FRONT MODULE BOUNDARIES MAP

## Objetivo

Mapear futuras fronteiras físicas do `services/conversational_front.py`.

Este documento NÃO autoriza extrações imediatas.

Seu objetivo é:
- preservar boundaries corretos;
- evitar mini-monólitos;
- impedir mistura de soberanias;
- orientar modularização futura segura.

---

# Regra arquitetural central

As futuras extrações devem separar:
- responsabilidade real;
- soberania runtime;
- ownership de estado;
- governance;
- recovery;
- surface.

Nunca modularizar por proximidade de linhas.

---

# 1. front_final_pipeline.py

## Domínio
`SAFE FINAL PIPELINE`

## Responsabilidades
- sanitize final;
- response surface normalization;
- spoken/reply sync;
- final polish;
- size policy;
- payload shaping superficial;
- preservação de melhor candidato final.

## Pode conter futuramente
- `_apply_final_reply_size_policy(...)`
- `_apply_final_surface_polish(...)`
- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

## NÃO deve conter
- runtime recovery;
- KB reinjection;
- reconstruction;
- discovery governance;
- response arbitration;
- micro_scene generation;
- terminals soberanos.

## Classificação
`SAFE`

---

# 2. front_surface_enhancement.py

## Domínio
`OPERATIONAL SURFACE ENHANCEMENT`

## Responsabilidades
- refino operacional localizado;
- consequence generation;
- enhancement superficial;
- melhoria contextual da resposta.

## Pode conter futuramente
- `_upgrade_operational_reply_with_model(...)`
- `_generate_consequence_with_model(...)`
- `_build_contract_consequence(...)`

## NÃO deve conter
- reconstruction;
- recovery transversal;
- response governance;
- runtime mutation.

## Classificação
`SEMI-SAFE`

---

# 3. front_response_mode.py

## Domínio
`RESPONSE MODE GOVERNANCE`

## Responsabilidades
- DIRECT / DISCOVERY / SCENE / CLOSING;
- arbitration;
- structural bypass;
- mode normalization;
- topic reset;
- scene promotion.

## Pode conter futuramente
- `_apply_current_turn_topic_reset(...)`
- `_apply_response_mode_arbitration(...)`
- `_apply_discovery_to_scene_bypass(...)`
- `_infer_response_mode_from_signals(...)`

## Risco
Altera comportamento estrutural e comercial.

## Classificação
`SOVEREIGN`

---

# 4. front_sovereign_decision.py

## Domínio
`DISCOVERY / IDENTITY GOVERNANCE`

## Responsabilidades
- identity enforcement;
- clarify governance;
- question authorization;
- discovery stabilization;
- discovery integrity.

## Pode conter futuramente
- `_should_allow_question(...)`
- `_apply_discovery_mode_identity_guard(...)`
- `_apply_identity_clarify_guard(...)`

## NÃO deve misturar com
- final polish;
- runtime recovery;
- KB runtime;
- reconstruction.

## Classificação
`SOVEREIGN`

---

# 5. front_runtime_recovery.py

## Domínio
`RUNTIME RECOVERY INFRASTRUCTURE`

## Responsabilidades
- runtime resurrection;
- fallback recovery;
- scene recovery;
- late KB reinjection;
- operational reconstruction tardia.

## Pode conter futuramente
- `_build_kb_anchor_reply(...)`
- `_build_kb_show_reply(...)`
- `_build_last_resort_operational_reply(...)`

## Risco
Muito alto.

Pode explicar:
- scene resurrection bugs;
- PACK_A bleed;
- fallback fantasma;
- runtime contamination.

## Classificação
`HIGH RISK SOVEREIGN`

---

# 6. front_operational_reconstruction.py

## Domínio
`OPERATIONAL RECONSTRUCTION ENGINE`

## Responsabilidades
- micro_scene generation;
- operational progression;
- grounded operational flow;
- scene rebuilding;
- progression validation.

## Pode conter futuramente
- `_generate_micro_scene_with_model(...)`
- `_compose_grounded_scene_with_progression(...)`
- `_select_structured_scene_steps(...)`

## Regra crítica
Não extrair cedo.

Antes:
- separar geração;
- separar validação;
- separar mutação;
- mapear todos os callsites.

## Classificação
`HIGH RISK SOVEREIGN`

---

# Governanças soberanas identificadas

## RESPONSE MODE GOVERNANCE
Controla:
- DIRECT;
- DISCOVERY;
- SCENE;
- CLOSING;
- bypasses;
- arbitration.

---

## DISCOVERY GOVERNANCE
Controla:
- identity;
- clarify;
- discovery stabilization;
- discovery terminals.

---

## SCENE GOVERNANCE
Controla:
- `micro_scene_allowed`
- `allow_scene_runtime`

---

## TERMINAL GOVERNANCE
Controla:
- early terminals;
- guarded terminals;
- official final terminal;
- runtime bypasses.

---

# Terminais reais do runtime

## Early Discovery Terminal
DISCOVERY early return.

---

## Direct Scene Early Terminal
SCENE return antecipado.

---

## Official Final Pipeline Terminal
Terminal final oficial.

---

# Ordem futura recomendada

## FASE 1 — SAFE
- `front_final_pipeline.py`

---

## FASE 2 — SEMI-SAFE
- `front_surface_enhancement.py`

---

## FASE 3 — SOVEREIGN MODERADO
- `front_response_mode.py`

---

## FASE 4 — SOVEREIGN
- `front_sovereign_decision.py`

---

## FASE 5 — HIGH RISK SOVEREIGN
- `front_runtime_recovery.py`

---

## FASE 6 — HIGH RISK RECONSTRUCTION
- `front_operational_reconstruction.py`

---

# PURE SAFE EXTRACTION READY

Boundaries já empiricamente validados:

- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Status:
- extraídos;
- compile limpo;
- boundaries preservados.

Novo módulo:
- `services/front_surface.py`

---

# Boundaries já estabilizados

## `services/front_utils.py`
`PURE UTILITY ENGINE`

---

## `services/front_guards.py`
`GUARD / VALIDATION ENGINE`

---

## `services/front_policies.py`
`POLICY ORCHESTRATION ENGINE`

---

## `services/front_assembly.py`
`DETERMINISTIC HUMANIZATION ENGINE`

---

## `services/front_surface.py`
`PURE SAFE FINAL PIPELINE ENGINE`

---

## `services/front_kb.py`
`KB RUNTIME MATERIALIZATION ENGINE`

---

# Decisão estratégica consolidada

O monólito restante concentra principalmente:
- governance;
- orchestration;
- recovery;
- reconstruction;
- runtime arbitration;
- terminals soberanos.

A prioridade correta NÃO é acelerar modularização.

A prioridade correta é:
- preservar soberania;
- consolidar boundaries;
- evitar mistura de domínios;
- estabilizar contratos;
- reduzir risco arquitetural antes da redução física do core.

# SECOND SAFE EXTRACTION WAVE

Helper extraído:
- `_sync_spoken_after_technical_rescue(...)`

Destino:
- `services/front_surface.py`

Boundary:
- PURE SAFE FINAL PIPELINE

Status:
- compile limpo;
- callsites preservados;
- sem alteração comportamental intencional.

