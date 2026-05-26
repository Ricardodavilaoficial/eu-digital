# FRONT HANDLE FLOW TRACE

## Objetivo

Mapear o fluxo estrutural do:

`services/conversational_front.py`

Este documento descreve:
- sequência macro do runtime;
- ownership de fluxo;
- handoffs;
- terminals;
- recovery;
- governanças envolvidas.

Não descreve:
- modularização física;
- extraction protocol;
- boundaries futuros.

---

# Descoberta central

O `handle()` NÃO é:
- pipeline linear simples;
- fluxo único;
- cadeia determinística única.

Ele funciona como:

`RUNTIME SOBERANO MULTI-PIPELINE`

com:
- arbitration;
- bypasses;
- early terminals;
- runtime recovery;
- reconstruction;
- final governance.

---

# Fluxo macro consolidado

## 1. Input normalization

Responsável por:
- leitura inicial;
- normalização estrutural;
- preparação do contexto;
- preparação de estado runtime.

### Resultado
O runtime entra em estado processável.

---

## 2. Understanding / signal extraction

Responsável por:
- topic;
- intent;
- confidence;
- question_type;
- segment signals;
- lead signals;
- operational hints.

### Governança associada
- discovery governance;
- response governance.

---

## 3. Runtime orchestration

Responsável por:
- arbitration;
- material selection;
- scene viability;
- orchestration sync;
- runtime continuity.

### Helpers associados

- `_apply_response_mode_arbitration(...)`
- `_pick_runtime_scene_material(...)`
- `_apply_discovery_to_scene_bypass(...)`
- `_apply_current_turn_topic_reset(...)`

### Classificação
`SOVEREIGN ORCHESTRATION`

---

## 4. Discovery governance

Responsável por:
- identity integrity;
- clarify necessity;
- discovery stabilization;
- enforcement de descoberta.

### Helpers associados

- `_apply_discovery_mode_identity_guard(...)`
- `_apply_identity_clarify_guard(...)`

### Resultado
O runtime decide:
- discovery;
- continuidade;
- bloqueio;
- clarificação.

---

## 5. Scene governance

Responsável por:
- scene eligibility;
- grounded operational progression;
- runtime scene activation;
- scene gating.

### Gates principais

- `micro_scene_allowed`
- `allow_scene_runtime`

### Classificação
`HIGH RISK SOVEREIGN`

---

## 6. Content ownership

Responsável por:
- geração estrutural;
- structured assembly;
- operational payload;
- scene composition;
- fallback operacional.

### Ownership principal

- KB builders;
- structured assembly;
- operational reconstruction;
- scene generation.

---

## 7. Early terminals

## Early Discovery Terminal

Executa:
- DISCOVERY early return.

---

## Direct Scene Early Terminal

Executa:
- retorno antecipado de SCENE;
- bypass do final pipeline oficial.

### Risco
Pode bypassar:
- final polish;
- sanitize final;
- terminal recovery;
- payload protection.

---

# Runtime recovery infrastructure

## Responsabilidades

- late KB reinjection;
- fallback rebuilding;
- runtime resurrection;
- operational recovery;
- candidate resurrection.

---

## Helpers associados

- `_build_kb_show_reply(...)`
- `_build_kb_anchor_reply(...)`
- `_build_last_resort_operational_reply(...)`

---

## Classificação

`HIGH RISK SOVEREIGN`

---

# FINAL PIPELINE

## Responsabilidades

- sanitize;
- normalize;
- spoken/reply sync;
- payload shaping;
- final polish;
- unwrap;
- terminal cleanup;
- final guards.

---

## SAFE helpers conhecidos

- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

### Novo módulo
- `services/front_surface.py`

---

## Estado arquitetural

É atualmente:
- o domínio mais delimitado;
- o mais previsível;
- o principal candidato futuro para modularização.

---

# Payload governance

## Responsável por

- payload final;
- unwrap;
- envelope protection;
- sanitize terminal;
- payload integrity.

---

## Ownership

Quem controla o payload final:
- payload builders;
- unwrap runtime;
- terminal guards;
- payload sanitize.

---

# Official Final Terminal

## Responsabilidades

- payload rebuild;
- sanitize final;
- unwrap;
- final sync;
- terminal protection;
- return final.

---

## Classificação

`MASTER TERMINAL`

---

# SAFE vs SOVEREIGN

## SAFE

Pode:
- sanitize;
- normalize;
- sync;
- polish;
- preservar superfície.

---

## SOVEREIGN

Controla:
- runtime;
- orchestration;
- arbitration;
- discovery;
- recovery;
- terminals;
- scene governance.

---

# Zonas congeladas

## PROIBIDO MOVER AGORA

- `JSON_FAIL_SAFE`
- runtime recovery
- scene resurrection
- terminal governance
- `micro_scene_allowed`
- late KB reinjection
- orchestration recovery

---

# Estado atual da refatoração

Fase atual:

`MONOLITH CORE ISOLATION PHASE`

O core restante concentra:
- governance;
- orchestration;
- recovery;
- reconstruction;
- sovereign terminals.

---

# Decisão consolidada

A prioridade correta NÃO é:
- dividir rapidamente o `handle()`;
- acelerar modularização.

A prioridade correta é:
- estabilizar governanças;
- consolidar ownerships;
- reduzir recovery implícito;
- preservar soberania runtime.

---

# Conclusão

O `handle()` funciona como:

`ORQUESTRADOR SOBERANO MULTI-PIPELINE`

Ele:
- coordena governanças;
- arbitra modos;
- ativa cenas;
- executa recovery;
- protege terminals;
- controla payload final.

Qualquer modularização futura precisa preservar:
- ownership;
- sovereignty;
- orchestration order;
- terminal integrity.