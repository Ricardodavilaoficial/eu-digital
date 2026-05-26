# FRONT RUNTIME GOVERNANCE MAP

## Objetivo

Mapear a governança soberana do runtime do:

`services/conversational_front.py`

Este documento NÃO descreve:
- modularização física;
- extraction protocol;
- boundaries futuros.

Ele descreve:
- ownership runtime;
- soberania;
- orchestration;
- recovery;
- terminals;
- arbitration;
- governança estrutural real.

---

# Descoberta central

O `conversational_front.py` NÃO funciona como pipeline linear.

O runtime opera como:

`FEDERAÇÃO DE PIPELINES SOBERANOS`

Com:
- múltiplos ownership layers;
- múltiplos terminals;
- múltiplos recovery paths;
- arbitration distribuída;
- governança concorrente.

---

# Macrogovernanças identificadas

## 1. RESPONSE MODE GOVERNANCE

Responsável por:
- DIRECT;
- DISCOVERY;
- SCENE;
- CLOSING;
- arbitration;
- structural bypass;
- promotion/degradation de modo.

### Runtime controlado
- response_mode
- scene promotion
- discovery bypass
- direct fallback

### Classificação
`SOVEREIGN`

---

## 2. DISCOVERY GOVERNANCE

Responsável por:
- identity enforcement;
- clarify flow;
- discovery integrity;
- discovery stabilization;
- discovery terminals.

### Runtime controlado
- identity flow
- clarify necessity
- discovery enforcement
- lead identity integrity

### Classificação
`SOVEREIGN`

---

## 3. SCENE GOVERNANCE

Responsável por:
- micro_scene_allowed;
- allow_scene_runtime;
- grounded operational progression;
- runtime scene activation.

### Gates principais
- `micro_scene_allowed`
- `allow_scene_runtime`

### Classificação
`HIGH RISK SOVEREIGN`

---

## 4. RUNTIME RECOVERY GOVERNANCE

Responsável por:
- runtime resurrection;
- fallback recovery;
- KB reinjection;
- operational reconstruction;
- late runtime salvage.

### Runtime controlado
- degraded outputs
- fallback rebuilding
- recovery injection
- runtime resurrection

### Classificação
`HIGH RISK SOVEREIGN`

---

## 5. TERMINAL GOVERNANCE

Responsável por:
- early returns;
- guarded terminals;
- official terminal;
- runtime bypasses.

### Classificação
`SOVEREIGN`

---

# Ownership layers identificados

## CONTENT OWNERSHIP

Quem cria/substitui conteúdo:
- structured assembly;
- KB builders;
- scene generators;
- operational fallbacks.

---

## SURFACE OWNERSHIP

Quem altera forma:
- sanitize;
- wrappers;
- polish;
- sync;
- normalization.

---

## PAYLOAD OWNERSHIP

Quem controla payload final:
- payload builders;
- unwrap;
- sanitize final;
- terminal protection.

---

# Runtime orchestration

## Responsabilidades

- runtime material selection;
- response arbitration;
- scene activation;
- orchestration state sync;
- topic reset;
- response normalization.

---

## Helpers identificados

- `_apply_response_mode_arbitration(...)`
- `_apply_discovery_to_scene_bypass(...)`
- `_apply_current_turn_topic_reset(...)`
- `_pick_runtime_scene_material(...)`

---

## Classificação

`SOVEREIGN ORCHESTRATION`

---

# Runtime recovery infrastructure

## Responsabilidades

- late KB reinjection;
- candidate resurrection;
- scene/runtime recovery;
- fallback rebuilding;
- recovery after degradation.

---

## Helpers associados

- `_build_kb_show_reply(...)`
- `_build_kb_anchor_reply(...)`
- `_build_last_resort_operational_reply(...)`

---

## Risco

Muito alto.

Pode explicar:
- fallback fantasma;
- PACK_A bleed;
- runtime contamination;
- scene resurrection bugs.

---

# Terminais reais identificados

## Early Discovery Terminal

Responsável por:
- DISCOVERY early return.

### Classificação
`SOVEREIGN TERMINAL`

---

## Direct Scene Early Terminal

Responsável por:
- retorno antecipado de SCENE;
- bypass do final pipeline oficial.

### Classificação
`HIGH RISK TERMINAL`

---

## Official Final Pipeline Terminal

Responsável por:
- sanitize;
- payload rebuild;
- final unwrap;
- final recovery;
- terminal payload protection.

### Classificação
`MASTER TERMINAL`

---

# FINAL PIPELINE

## Responsabilidades

- sanitize final;
- surface normalization;
- final polish;
- spoken/reply sync;
- payload shaping;
- unwrap final;
- terminal cleanup.

---

## Estado arquitetural

É o domínio mais:
- delimitado;
- modularizável;
- previsível.

Principal candidato futuro para:
`front_final_pipeline.py`

---

# SAFE vs SOVEREIGN

## PURE SAFE

Pode:
- normalize;
- polish;
- sanitize;
- sync;
- preservar superfície.

Não pode:
- recovery;
- orchestration;
- governance;
- reconstruction.

---

## SOVEREIGN

Controla:
- runtime;
- arbitration;
- discovery;
- recovery;
- terminals;
- scene governance.

Nunca mover cedo.

---

# Zonas congeladas

## PROIBIDO MOVER AGORA

- `JSON_FAIL_SAFE`
- `PACK_A_AGENDA`
- `micro_scene_allowed`
- late KB recovery
- reconstruction flows
- terminal governance
- runtime resurrection

---

# Estado atual da refatoração

Fase atual:

`MONOLITH CORE ISOLATION PHASE`

O núcleo restante concentra:
- governance;
- orchestration;
- recovery;
- reconstruction;
- sovereign terminals.

---

# Decisão arquitetural consolidada

A prioridade correta NÃO é:
- acelerar modularização;
- reduzir linhas rapidamente.

A prioridade correta é:
- preservar soberania;
- estabilizar governanças;
- separar ownerships;
- consolidar boundaries;
- reduzir risco runtime antes da divisão física do core.