# RUNTIME RESPONSE ORCHESTRATION MAP

## Objetivo

Mapear a orchestration runtime do:

`services/conversational_front.py`

Este documento descreve:
- coordenação de fluxo;
- arbitration;
- material selection;
- response progression;
- runtime sync;
- scene activation;
- orchestration ownership.

Não descreve:
- extraction protocol;
- modularização física;
- discovery governance completa;
- terminal governance completa.

---

# Descoberta central

A runtime orchestration NÃO é:
- apenas response_mode;
- apenas pipeline;
- apenas fallback.

Ela funciona como:

`CAMADA SOBERANA DE COORDENAÇÃO`

entre:
- discovery;
- scene;
- KB runtime;
- final pipeline;
- operational progression;
- runtime recovery.

---

# Responsabilidades principais

## Runtime material selection

Selecionar:
- melhor material operacional;
- runtime_short;
- runtime_long;
- micro_scene;
- compact fallback;
- operational references.

---

## Response arbitration

Decidir:
- DIRECT;
- DISCOVERY;
- SCENE;
- CLOSING;
- promotion;
- degradation;
- bypasses.

---

## Scene activation

Controlar:
- scene eligibility;
- grounded operational context;
- runtime scene activation;
- discovery → scene transition.

---

## Orchestration state sync

Sincronizar:
- topic;
- operational state;
- response_mode;
- progression state;
- runtime continuity.

---

# Helpers principais

## `_pick_runtime_scene_material(...)`

Responsável por:
- seleção do melhor material operacional runtime;
- escolha contextual;
- evitar mutação indevida de contrato.

Classificação:
`SOVEREIGN ORCHESTRATION`

---

## `_apply_discovery_to_scene_bypass(...)`

Responsável por:
- permitir:
  `DISCOVERY → SCENE`
- apenas quando há contrato operacional demonstrável.

Classificação:
`SOVEREIGN ORCHESTRATION`

---

## `_apply_response_mode_arbitration(...)`

Responsável por:
- arbitration estrutural;
- promotion/degradation;
- fallback de modo.

Classificação:
`SOVEREIGN`

---

## `_apply_current_turn_topic_reset(...)`

Responsável por:
- reset estrutural de tópico;
- evitar contaminação de continuidade.

Classificação:
`SOVEREIGN ORCHESTRATION`

---

# Runtime orchestration flow

## 1. Material inspection

O runtime avalia:
- operational contract;
- runtime material;
- KB hydration;
- scene viability.

---

## 2. Arbitration

Decide:
- qual modo prevalece;
- se DISCOVERY deve permanecer;
- se SCENE pode emergir;
- se DIRECT deve ser preservado.

---

## 3. Runtime synchronization

Atualiza:
- estado contextual;
- continuidade;
- progression state;
- operational coherence.

---

## 4. Final handoff

Entrega para:
- FINAL PIPELINE;
- terminal governance;
- final polish.

---

# Scene orchestration

## Requisitos para SCENE

SCENE só pode emergir quando:
- existe contexto operacional real;
- há material runtime válido;
- `micro_scene_allowed` permite;
- não há fallback contaminado;
- a promoção é estruturalmente segura.

---

## Gates principais

- `micro_scene_allowed`
- `allow_scene_runtime`

---

## Riscos

- tutorialização;
- falso contexto operacional;
- scene resurrection;
- runtime contamination;
- PACK_A bleed.

---

# Runtime continuity

## Objetivo

Evitar:
- drift contextual;
- continuidade falsa;
- mistura de tópicos;
- persistência indevida de scene;
- herança incorreta de discovery.

---

## Controle associado

- topic reset;
- response arbitration;
- orchestration sync;
- runtime progression control.

---

# Relação com FINAL PIPELINE

## Runtime orchestration NÃO é final pipeline

A orchestration:
- decide;
- coordena;
- arbitra;
- promove;
- degrada;
- sincroniza.

O FINAL PIPELINE:
- sanitize;
- polish;
- normalize;
- sync;
- unwrap;
- finaliza superfície.

---

# SAFE vs SOVEREIGN

## SAFE

Pode:
- normalize;
- sanitize;
- polish;
- sync.

---

## SOVEREIGN ORCHESTRATION

Controla:
- arbitration;
- promotion;
- degradation;
- runtime continuity;
- scene activation;
- operational progression.

Nunca mover cedo.

---

# Zonas congeladas

## PROIBIDO MOVER AGORA

- arbitration runtime;
- scene activation;
- `micro_scene_allowed`;
- runtime progression;
- discovery → scene bypass;
- orchestration recovery;
- runtime resurrection.

---

# Estado atual

A orchestration:
- já está parcialmente delimitada;
- possui helpers locais claros;
- já demonstra macrodomínio consistente.

Porém:
- ainda depende fortemente do core;
- ainda toca governanças soberanas;
- ainda encosta em recovery runtime.

---

# Decisão consolidada

A runtime orchestration deve permanecer no core nesta fase.

Antes de qualquer extração:
- consolidar boundaries;
- estabilizar governance;
- reduzir recovery implícito;
- finalizar mapeamento de ownership runtime.

---

# Conclusão

A runtime orchestration é:

`CAMADA SOBERANA DE COORDENAÇÃO DO FRONT`

Ela:
- conecta governanças;
- coordena runtime;
- arbitra modos;
- ativa cenas;
- protege continuidade operacional.

A modularização prematura desta camada teria alto risco de:
- regressão estrutural;
- runtime contamination;
- resurrection bugs;
- perda de integridade operacional.