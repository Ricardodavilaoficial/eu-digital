# FRONT REFACTOR STATE — conversational_front.py

## Objetivo

Refatorar o conversational_front.py de forma incremental, segura e sem regressões comportamentais.

A prioridade NÃO é corrigir comportamento agora.
A prioridade é:
- reduzir acoplamento;
- criar zonas arquiteturais;
- encapsular micro-pipelines;
- preparar futura modularização segura.

Bugs comportamentais conhecidos ficam registrados em:
- docs/front_refactor_debts.md

---

# Princípios obrigatórios

- Não alterar prompts sem decisão explícita.
- Não introduzir keyword lists hardcoded.
- Não misturar refatoração estrutural com correção comportamental.
- Não fazer hero patches.
- Sempre:
  - patch pequeno;
  - compile;
  - validação;
  - commit isolado;
  - push.

---

# Módulos já extraídos

## services/front_utils.py
Helpers utilitários gerais.

## services/front_policies.py
Políticas e regras estruturais.

## services/front_guards.py
Guards estruturais reutilizáveis.

## services/front_kb.py
Lógica KB parcialmente desacoplada.

## services/front_assembly.py
Assembly/pipelines auxiliares.

---

# Helpers locais já consolidados no conversational_front.py

## Guards / rescue cluster

### _apply_discovery_mode_identity_guard
Commit:
- e9b537e
- 2cb07af

### _sync_spoken_after_technical_rescue
Commit:
- b753421
- 9b1eb41
- 9ba85a6

### _apply_non_empty_reply_guard
Commit:
- 9557b9d
- 5e573da

### _restore_final_candidate_if_degraded
Commit:
- 33c4a3e (helper criado)
- 23e0312 (uso aplicado)

### _apply_identity_clarify_guard
Helper consolidado localmente.

---

# Zonas arquiteturais já identificadas

## FINAL PIPELINE
Pós-processamento principal da resposta.

## FINAL POLISH
- sanitize
- wrap
- spoken sync
- technical rescue

## FINAL GUARD
- anti-empty
- anti-degradation
- fallback estrutural

## response_mode control
Fluxo:
- DIRECT
- DISCOVERY
- SCENE
- CLOSING

---

# Zonas congeladas (não mexer agora)

## JSON_FAIL_SAFE
Ainda acoplado ao fluxo inteiro.

## PACK_A_AGENDA
Ainda gera tutorialização indevida.

## runtime_short / runtime_long
Ainda dependem da hidratação KB atual.

## _build_kb_show_reply
Muito acoplado ao rescue estrutural.

## final kb rescue
Ainda sensível.

---

# Estratégia atual

A estratégia atual NÃO é extrair módulos grandes.

A estratégia é:
1. mapear zonas;
2. criar helpers locais seguros;
3. delimitar pipelines;
4. reduzir duplicação;
5. preparar extrações futuras.

---

# Próximo foco previsto

Mapear melhor:
- FINAL GUARD
- response_mode control
- final polish pipeline

Objetivo:
identificar futuros submódulos naturais.

---

# Regras de operação CMD

Sempre usar:
- git add específico
- py_compile antes de commit
- commits pequenos
- push frequente

Nunca:
- git add .
- refatoração massiva
- múltiplas mudanças sem compile

---

# Estado atual

Branch:
- main

Deploy:
- funcional em produção

Status:
- refatoração incremental segura em andamento
- sem regressão estrutural aparente
- comportamento ainda possui dívidas registradas separadamente

---

# Atualização — 2026-05-26

## Commits recentes

- 23e0312 — aplica helper no restore final candidate
- 8f79189 — registra estado estrutural da refatoração front
- c772ba0 — delimita pipeline de response mode

## Nova zona delimitada

### RESPONSE MODE CONTROL PIPELINE

Responsável por acabamento estrutural por modo:
- DIRECT
- DISCOVERY
- SCENE
- CLOSING

Ainda NÃO extraído para módulo.

Decisão:
- manter dentro de conversational_front.py por enquanto;
- usar como zona arquitetural mapeada;
- futura extração só depois de mapear os usos anteriores de response_mode espalhados no arquivo.

---

# Atualização — 2026-05-26 (Runtime Orchestration)

## Runtime orchestration iniciou extrações reais

### _apply_discovery_to_scene_bypass
Commits:
- 4aefeed
- 98f4e7e

Responsabilidade:
- promover DISCOVERY → SCENE quando já existe contrato operacional demonstrável.

Status:
- helper local consolidado.

---

### _pick_runtime_scene_material
Commits:
- 2ed9322
- 71d9e8c

Responsabilidade:
- selecionar melhor material operacional em runtime sem mutar contrato.

Status:
- helper local consolidado.

---

# Estado arquitetural atualizado

O conversational_front.py agora possui separação visível entre:

- Runtime response orchestration
- Response mode control pipeline
- Final pipeline
- Final polish
- Final guard
- Rescue helpers
- Runtime material selection

---

# Estratégia atual

Continuar:
- helpers pequenos;
- extrações locais;
- delimitação arquitetural;
- documentação persistida.

Evitar:
- módulos novos grandes;
- mudanças comportamentais;
- refactors massivos.

