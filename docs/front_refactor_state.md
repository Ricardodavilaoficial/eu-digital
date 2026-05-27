# FRONT REFACTOR STATE — conversational_front.py

## Objetivo

Refatorar o `services/conversational_front.py` de forma incremental, segura e sem regressões estruturais.

A prioridade atual NÃO é:
- corrigir bugs comportamentais;
- alterar prompts;
- alterar estratégia comercial.

A prioridade é:
- reduzir acoplamento;
- delimitar macrodomínios;
- estabilizar pipelines;
- preparar modularização futura segura;
- preservar soberania runtime.

Dívidas comportamentais permanecem registradas em:
- `docs/front_refactor_debts.md`

---

# Princípios obrigatórios

- Não alterar prompts sem decisão explícita.
- Não introduzir keyword lists hardcoded.
- Não misturar refatoração estrutural com correção comportamental.
- Não executar hero patches.
- Sempre:
  - patch pequeno;
  - compile;
  - validação;
  - commit isolado;
  - push imediato.

---

# Estado arquitetural consolidado

O `conversational_front.py` deixou de ser um bloco monolítico amorfo.

Hoje o runtime já apresenta separação arquitetural observável entre:

- Runtime orchestration
- Response mode governance
- Final pipeline
- Final polish
- Runtime recovery
- Discovery governance
- Terminal governance
- Reconstruction flows
- Deterministic assembly
- KB runtime materialization

---

# Macrodomínios identificados

## 1. Runtime Orchestration

Responsável por:
- material selection;
- response arbitration;
- scene promotion;
- discovery bypass;
- orchestration state sync.

Status:
- parcialmente delimitado;
- ainda soberano;
- NÃO modularizar agora.

---

## 2. Response Mode Governance

Responsável por:
- DIRECT / DISCOVERY / SCENE / CLOSING;
- arbitration;
- structural bypass;
- mode normalization.

Status:
- governança soberana;
- ainda congelado.

---

## 3. Discovery Governance

Responsável por:
- identity enforcement;
- clarify flow;
- discovery stabilization;
- discovery terminals.

Status:
- domínio soberano;
- NÃO mover.

---

## 4. Runtime Recovery Infrastructure

Responsável por:
- KB reinjection;
- runtime resurrection;
- fallback recovery;
- scene recovery;
- operational reconstruction tardia.

Status:
- altíssimo risco;
- proibido modularizar nesta fase.

---

## 5. FINAL PIPELINE

Responsável por:
- sanitize;
- payload shaping;
- surface normalization;
- spoken/reply sync;
- final polish;
- final guards;
- payload rebuild;
- final unwrap.

Status:
- domínio mais maduro arquiteturalmente;
- principal candidato futuro para modularização.

---

# SAFE vs SOVEREIGN

## PURE SAFE FINAL PIPELINE

Helpers:
- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Características:
- não alteram runtime;
- não alteram governance;
- não executam recovery;
- não executam reconstruction.

Classificação:
`EXTRACTION READY`

---

## SAFE/SURFACE HYBRID

Helpers:
- `_apply_final_reply_size_policy(...)`
- `_apply_final_surface_polish(...)`

Características:
- relativamente seguros;
- porém ainda encostam em:
  - KB parsing;
  - operational enhancement;
  - technical rescue.

Classificação:
- SEMI-SAFE.

---

## SOVEREIGN DOMAINS

Ainda congelados:
- Discovery governance;
- Runtime recovery;
- Scene governance;
- Response arbitration;
- Terminal governance;
- Reconstruction flows.

---

# Terminais soberanos identificados

## Early Discovery Terminal

Responsável por:
- DISCOVERY early return.

---

## Direct Scene Early Terminal

Responsável por:
- retorno antecipado de SCENE;
- bypass do final pipeline oficial.

---

## Official Final Pipeline Terminal

Responsável por:
- terminal oficial completo;
- sanitize;
- rebuild;
- unwrap;
- payload protection;
- final return.

---

# Ownership layers identificados

## Content ownership
Quem cria/substitui conteúdo:
- KB builders;
- structured assembly;
- scene generation;
- operational fallbacks.

## Surface ownership
Quem altera forma:
- polish;
- sanitize;
- wrappers;
- sync;
- normalization.

## Payload ownership
Quem controla o payload final:
- payload builders;
- unwrap;
- payload sanitize;
- terminal guards.

---

# Zonas congeladas (PROIBIDO MOVER AGORA)

- `JSON_FAIL_SAFE`
- `PACK_A_AGENDA`
- `micro_scene_allowed`
- late KB recovery
- runtime resurrection
- `_build_kb_show_reply(...)`
- reconstruction flows
- terminal governance

---

# Módulos já consolidados

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

# FIRST SAFE EXTRACTION WAVE

## Executada

Novo módulo criado:
- `services/front_surface.py`

Helpers extraídos:
- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Status:
- compile limpo;
- boundaries preservados;
- sem regressão estrutural aparente.

Conclusão:
o protocolo de refatoração segura foi validado empiricamente.

---

# Estado atual da refatoração

## Branch
- `main`

## Deploy
- funcional em produção.

## Estratégia atual

Continuar:
- helpers pequenos;
- delimitação arquitetural;
- documentação persistida;
- auditorias;
- classificação SAFE/SOVEREIGN.

Evitar:
- extrações grandes;
- refactors massivos;
- mistura de bugfix com arquitetura;
- modularização prematura.

---

# Próxima fase arquitetural

Objetivo:
preparar a primeira modularização real do FINAL PIPELINE.

Ainda NÃO:
- criar `front_final_pipeline.py`;
- mover runtime recovery;
- mover discovery governance;
- mover response governance.

Antes disso:
- consolidar boundaries;
- estabilizar contratos;
- revisar mutações;
- finalizar mapeamento restante.

---

# Commits-chave da fase arquitetural

- `7b6db70`
- `ea46007`
- `23e0312`
- `c772ba0`
- `98f4e7e`
- `cb5345c`
- `3853d6d`
- `13ea39a`
- `fef2437`

---

# Conclusão consolidada

A refatoração segura entrou oficialmente na:

`MONOLITH CORE ISOLATION PHASE`

O monólito restante concentra principalmente:
- governance;
- orchestration;
- recovery;
- reconstruction;
- terminals soberanos.

A estratégia correta agora NÃO é acelerar modularização.

A estratégia correta é:
- preservar soberania;
- estabilizar boundaries;
- continuar micro-extrações seguras;
- consolidar documentação operacional;
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

