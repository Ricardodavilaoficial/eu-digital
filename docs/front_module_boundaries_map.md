# FRONT MODULE BOUNDARIES MAP

## Objetivo

Mapear futuras fronteiras físicas de módulos do `conversational_front.py`.

Este documento NÃO autoriza extração imediata.
Ele serve para orientar uma modularização futura, segura e baseada na arquitetura real descoberta.

---

# Regra central

A modularização futura deve separar domínios por responsabilidade real, não por proximidade de linhas.

---

# 1. front_final_pipeline.py

## Domínio

SAFE FINAL PIPELINE

## Pode conter futuramente

- `_apply_final_reply_size_policy(...)`
- `_apply_final_surface_polish(...)`
- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

## Responsabilidades

- sanitize final;
- size policy;
- surface polish;
- spoken/reply sync;
- response surface normalization;
- preservação de melhor candidato final.

## Não deve conter

- `_build_kb_anchor_reply(...)`
- `_build_kb_show_reply(...)`
- `_generate_micro_scene_with_model(...)`
- `_build_last_resort_operational_reply(...)`
- `_should_allow_question(...)`
- `_apply_discovery_mode_identity_guard(...)`

---

# 2. front_surface_enhancement.py

## Domínio

OPERATIONAL SURFACE ENHANCEMENT

## Pode conter futuramente

- `_upgrade_operational_reply_with_model(...)`
- `_generate_consequence_with_model(...)`
- `_build_contract_consequence(...)`

## Responsabilidades

- melhorar superfície operacional já existente;
- reescrever texto operacional sem mutar runtime;
- gerar consequência curta e controlada.

## Risco

Médio.

Motivo:
usa IA, mas não deve mutar contract, response_mode ou micro_scene_allowed.

---

# 3. front_operational_reconstruction.py

## Domínio

OPERATIONAL RECONSTRUCTION ENGINE

## Pode conter futuramente

- `_generate_micro_scene_with_model(...)`
- `_compose_grounded_scene_with_progression(...)`
- `_select_structured_scene_steps(...)`
- validadores de progressão operacional ligados a reconstrução.

## Responsabilidades

- gerar microcena;
- reconstruir progressão operacional;
- validar densidade operacional;
- recompor cena runtime.

## Atenção

Este módulo NÃO deve nascer cedo.

Antes de extraí-lo:
- separar geração de mutação;
- separar validação de fallback;
- remover efeitos colaterais implícitos;
- mapear todos os callsites.

---

# 4. front_runtime_recovery.py

## Domínio

RUNTIME RECOVERY INFRASTRUCTURE

## Pode conter futuramente

- `_build_kb_anchor_reply(...)`
- `_build_kb_show_reply(...)`
- `_build_last_resort_operational_reply(...)`

## Responsabilidades

- fallback operacional;
- recovery transversal;
- reconstrução após degradação;
- reanimação operacional;
- fallback final baseado em KB/runtime.

## Risco

Muito alto.

Motivo:
é transversal, possui múltiplos callsites e pode explicar bugs históricos de scene resurrection, PACK_A bleed e fallback fantasma.

---

# 5. front_sovereign_decision.py

## Domínio

SOVEREIGN FINAL DECISION

## Pode conter futuramente

- `_should_allow_question(...)`
- `_apply_discovery_mode_identity_guard(...)`
- futuras políticas de identity/discovery/clarify.

## Responsabilidades

- política de perguntas;
- autorização de discovery;
- identity guard;
- clarify guard;
- decisões soberanas finais.

## Não deve ser misturado com

- final surface polish;
- sanitize;
- runtime recovery;
- reconstruction engine.

---

# 6. front_response_mode.py

## Domínio

RESPONSE MODE ORCHESTRATION

## Pode conter futuramente

- `_apply_current_turn_topic_reset(...)`
- `_apply_response_mode_arbitration(...)`
- `_apply_discovery_to_scene_bypass(...)`
- `_normalize_response_mode(...)`
- `_infer_response_mode_from_signals(...)`

## Responsabilidades

- arbitragem DIRECT / DISCOVERY / SCENE / CLOSING;
- reset estrutural de tópico;
- bypass discovery → scene;
- regras estruturais de modo.

## Risco

Médio/alto.

Motivo:
altera forma da resposta e pode impactar comportamento comercial.

---

# Ordem futura recomendada de extração

## Fase 1 — Baixo risco

- `front_final_pipeline.py`
- apenas SAFE FINAL PIPELINE.

## Fase 2 — Médio risco

- `front_surface_enhancement.py`
- apenas IA polish sem mutação runtime.

## Fase 3 — Médio/alto risco

- `front_response_mode.py`
- somente após mais testes.

## Fase 4 — Alto risco

- `front_sovereign_decision.py`
- somente após estabilizar identity/discovery.

## Fase 5 — Muito alto risco

- `front_runtime_recovery.py`
- somente após mapear todos os recovery triggers.

## Fase 6 — Muito alto risco

- `front_operational_reconstruction.py`
- somente após separar geração, validação, fallback e mutação.

---

# Decisão atual

Nenhum novo módulo deve ser criado imediatamente.

O objetivo agora é usar este mapa como referência para:
- evitar extrações erradas;
- impedir mini-monólitos novos;
- preservar domínios soberanos;
- preparar modularização com segurança.

# Atualização — Boundaries após auditoria de ownership/runtime

## Nova regra de fronteira

Nenhum módulo futuro deve misturar:

- SAFE FINAL PIPELINE
com
- RUNTIME RECOVERY INFRASTRUCTURE
ou
- OPERATIONAL RECONSTRUCTION ENGINE.

## SAFE FINAL PIPELINE

Pode conter apenas operações de superfície previsíveis:

- size policy;
- sanitize;
- polish;
- spoken/reply sync;
- response surface normalization;
- unwrap superficial;
- preservação de candidato final, se não reabrir KB nem reconstruction.

Não deve conter:

- `_build_kb_show_reply`
- `_build_kb_anchor_reply`
- `_generate_micro_scene_with_model`
- `_front_build_structured_assembly_reply`
- `allow_scene_runtime`
- recovery baseado em `micro_scene_allowed`
- discovery enforcement
- response_mode arbitration.

## RUNTIME RECOVERY INFRASTRUCTURE

Domínio confirmado.

Inclui:
- late KB show injection;
- KB anchor fallback;
- candidate resurrection;
- failsafe fallback;
- scene runtime recovery;
- payload recovery.

Trechos críticos:
- 12424–12545
- 12512–12545
- 12842–12870
- 12917–12931

Classificação:
- muito alto risco.

Não extrair cedo.

## RESPONSE MODE GOVERNANCE

Domínio confirmado.

Inclui:
- promoção DIRECT → SCENE;
- degradação SCENE → DIRECT;
- força DISCOVERY;
- normalização transversal;
- bypass discovery → scene.

Classificação:
- médio/alto risco.

## SCENE GOVERNANCE

Domínio confirmado.

Gate principal:
- `micro_scene_allowed`

Runtime secundário:
- `allow_scene_runtime`

Classificação:
- alto risco.

## DISCOVERY GOVERNANCE

Domínio confirmado.

Inclui:
- discovery prompt;
- discovery early terminal;
- discovery guarantee antes de direct return;
- discovery identity guard;
- DISCOVERY terminal.

Classificação:
- alto risco.

## Terminal ownership

O `handle()` possui três terminais reais:
- Early Discovery Terminal;
- Direct Scene Early Terminal;
- Official Final Pipeline.

Qualquer extração futura precisa preservar essa diferença.

# Atualização — PURE SAFE FINAL PIPELINE

## PURE SAFE FINAL PIPELINE confirmado

Helpers:
- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Esses helpers são atualmente os candidatos mais seguros para futura extração inicial.

## SAFE/SURFACE HYBRID

Helpers:
- `_apply_final_reply_size_policy(...)`
- `_apply_final_surface_polish(...)`

Esses helpers permanecem fora da primeira extração por ainda encostarem em:
- KB snapshot;
- contract consequence generation;
- technical rescue;
- operational surface enhancement.

## Runtime Recovery Infrastructure confirmado

Trecho:
- 12423–12460

Esse trecho NÃO deve entrar em:
- `front_final_pipeline.py`

Motivo:
- reabre recovery;
- reinjeta KB;
- reativa reconstruction/runtime.

# Atualização — Operational Surface Enhancement confirmado

## Cluster confirmado

Helpers:
- `_generate_consequence_with_model(...)`
- `_build_contract_consequence(...)`
- `_upgrade_operational_reply_with_model(...)`

## Responsabilidade real

Esses helpers:
- melhoram superfície operacional;
- geram consequência contextual;
- refinam saída operacional;
- usam IA de forma localizada.

## O que NÃO fazem

Não:
- reconstruem runtime;
- alteram response_mode;
- alteram micro_scene_allowed;
- executam recovery transversal;
- geram microcena soberana.

## Classificação oficial

Domínio:
`OPERATIONAL SURFACE ENHANCEMENT`

E NÃO:
- SAFE FINAL PIPELINE
nem
- OPERATIONAL RECONSTRUCTION ENGINE.

# Atualização — RESPONSE MODE GOVERNANCE

## RESPONSE MODE INFERENCE
- `_infer_response_mode_from_signals(...)`

## RESPONSE MODE ARBITRATION
- `_apply_response_mode_arbitration(...)`

## STRUCTURAL MODE BYPASS
- `_apply_discovery_to_scene_bypass(...)`

## LATE SOVEREIGN TERMINALS
- runtime overwrites tardios:
  - 9524
  - 9678
  - 9862
  - 9910

# Atualização — DISCOVERY GOVERNANCE

## DISCOVERY STATE ENFORCEMENT
- `_apply_discovery_mode_identity_guard(...)`

## DISCOVERY STABILIZATION
- `_apply_identity_clarify_guard(...)`

## DISCOVERY VALIDATION
- `_front_identity_request_is_valid(...)`
- boundary já extraído:
  - `services/front_guards.py`

## LAST RESORT IDENTITY GENERATION
- `_front_build_identity_request(...)`

# Atualização — TERMINAL GOVERNANCE

## DIRECT SCENE EARLY TERMINAL
- trecho 9974

## FREE_MODE_FINAL_GUARD TERMINAL
- trecho 12016

## MASTER FINAL TERMINAL
- trecho 12811+

## JSON_FAIL_SAFE GOVERNANCE
- trecho 10895+

# Atualização — PURE SAFE EXTRACTION READY

## Extraction-ready boundaries

### `_apply_response_mode_surface(...)`
Boundary:
- PURE SAFE FINAL PIPELINE

### `_restore_final_candidate_if_degraded(...)`
Boundary:
- PURE SAFE FINAL PIPELINE

## Observação importante

Esses helpers representam os primeiros extraction candidates empiricamente validados da refatoração segura.

# Atualização — FIRST SAFE EXTRACTION WAVE executada

Foi criado:

- `services/front_surface.py`

Helpers extraídos:

- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Status:
- compile limpo;
- callsites preservados;
- sem alteração comportamental intencional;
- boundary classificado como PURE SAFE FINAL PIPELINE.

# Atualização — DETERMINISTIC HUMANIZATION ENGINE

## Boundary confirmado
Módulo:
- `services/front_assembly.py`

## Responsabilidade

O módulo atua como:
`DETERMINISTIC HUMANIZATION ENGINE`

Responsável por:
- humanização determinística;
- estabilização de microcena;
- limpeza estrutural;
- montagem operacional;
- normalização textual;
- composição de fluxo operacional.

## Regras confirmadas

- não chama LLM;
- não acessa Firestore;
- não altera prompts;
- não executa recovery;
- não altera response_mode;
- não executa governance soberana.

## Dependências

Somente:
- `front_utils.py`
- `front_guards.py`

