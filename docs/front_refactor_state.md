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

---

# Atualização — Classificação dos helpers locais

## Helpers locais atuais

### _apply_discovery_mode_identity_guard
Domínio:
- guard
- identity
- discovery

Status:
- manter local por enquanto.

### _sync_spoken_after_technical_rescue
Domínio:
- rescue
- surface
- spoken sync

Status:
- manter local por enquanto.

### _apply_non_empty_reply_guard
Domínio:
- final guard
- anti-empty

Status:
- manter local por enquanto.

### _pick_runtime_scene_material
Domínio:
- runtime orchestration
- material selection

Status:
- manter local por enquanto.

### _apply_discovery_to_scene_bypass
Domínio:
- runtime orchestration
- response mode arbitration

Status:
- manter local por enquanto.

### _apply_identity_clarify_guard
Domínio:
- guard
- identity
- clarify

Status:
- manter local por enquanto.

## Decisão

Nenhum helper local deve ser movido para módulo agora.

Motivo:
eles ainda dependem fortemente do contexto do `handle()` e servem como etapa intermediária de estabilização estrutural.

---

# Estado arquitetural observado — macrodomínios emergentes

## Runtime orchestration

Faixa aproximada:
- 8900–9185

Responsabilidades:
- runtime material selection;
- response_mode arbitration;
- discovery bypass;
- scene promotion;
- micro_scene gating;
- orchestration state sync.

Status:
- parcialmente modularizado;
- helpers locais já extraídos;
- ainda congelado para divisão real.

---

## Final pipeline

Faixa aproximada:
- 12003+

Responsabilidades:
- sanitize final;
- payload replacement;
- direct scene payload;
- compact fallback;
- scene upgrade;
- human wrapper;
- spoken/reply sync;
- post-processing final.

Status:
- estruturalmente mais maduro;
- fronteiras claras;
- forte candidato futuro para `front_final_pipeline.py`.

---

# Auditoria de dependências — FINAL PIPELINE

Faixa auditada:
- 12003–12130

## Dependências fortes identificadas

- response_mode
- reply_text
- spoken_text
- reply_source

## Dependências moderadas

- operational_contract
- base_operational_contract

## Dependências fracas

- has_real_operational_context
- micro_scene_allowed

## Conclusão arquitetural

O FINAL PIPELINE demonstrou baixo acoplamento estrutural comparado ao runtime orchestration.

O domínio parece majoritariamente:
- pós-processamento;
- payload shaping;
- sanitize;
- fallback replacement;
- sync de superfície.

Fortíssimo candidato futuro para:
`front_final_pipeline.py`

---

# Subdomínios internos observados — FINAL PIPELINE

## 1. Scene upgrade / humanization
Faixa:
- 12123–12142

Responsabilidade:
- upgrade operacional;
- humanização;
- evitar payload estrutural cru.

---

## 2. Name discovery post-pass
Faixa:
- 12146–12155

Responsabilidade:
- garantir descoberta de nome no turno 0.

---

## 3. Reply size preservation + policy
Faixa:
- 12158–12188

Responsabilidade:
- preservar densidade técnica;
- aplicar size policy;
- spoken sync.

---

## 4. Question policy enforcement
Faixa:
- 12190–12232

Responsabilidade:
- bloquear perguntas fora da política.

---

## 5. Final guardrails
Faixa:
- 12236–12295

Responsabilidade:
- anti-invenção;
- sanitize;
- spoken sync;
- rescue técnico;
- final polish.

---

## 6. Final empty guard
Faixa:
- 12298+

Responsabilidade:
- impedir saída vazia;
- fallback final.

---

## Conclusão arquitetural

O FINAL PIPELINE demonstrou:
- forte separação interna de responsabilidades;
- baixa dependência externa;
- alta modularizabilidade futura.

É atualmente o macrodomínio mais próximo de virar módulo real.

---

# Auditoria funcional — FINAL PIPELINE

Faixa auditada:
- 12003–12320

## Dependências externas já modularizadas

### front_policies
- _apply_reply_size_policy
- _preserve_technical_direct_reply_size

### front_assembly
- _build_direct_scene_payload
- _humanize_scene_flow
- _looks_like_structural_scene_payload
- _sanitize_user_facing_reply
- wrap_show_response

### front_kb
- _try_parse_kb_json

## Dependências ainda locais no conversational_front.py

- _sanitize_unverified_time_claims
- _should_allow_question
- _sync_spoken_after_technical_rescue
- _build_kb_show_reply
- _upgrade_operational_reply_with_model
- _build_contract_consequence

## Conclusão

O FINAL PIPELINE é modularizável, mas ainda não deve ser movido inteiro.

Antes de criar `front_final_pipeline.py`, é necessário:
- definir contrato de entrada/saída;
- mapear mutações de reply_text, spoken_text e reply_source;
- decidir se helpers locais permanecem locais ou sobem para módulos existentes.

---

# Auditoria de mutações — FINAL PIPELINE

Faixa auditada:
- 12003–12320

## Saídas principais mutadas

- reply_text
- spoken_text
- reply_source

## Saídas secundárias mutadas

- name_use
- operational_reference
- debug_info

## Estados transitórios internos

Variáveis iniciadas com `_` parecem transitórias e provavelmente não precisariam atravessar o contrato futuro do módulo.

Exemplos:
- _contract_for_direct
- _valid_real_scene
- _valid_compact_fallback
- _should_run_late_payload
- _raw_scene_exit
- _humanized_exit
- _kb_obj

## Conclusão arquitetural

O FINAL PIPELINE já demonstra:
- mutação centralizada;
- ciclo de vida consistente;
- padrão natural de input/output.

Fortíssimo indicativo de futura transformação em:
- FrontFinalPipelineInput
- FrontFinalPipelineResult
- front_final_pipeline.py

---

# Esboço de contrato futuro — FINAL PIPELINE

## Objetivo

Preparar futura extração para `front_final_pipeline.py` sem criar função com dezenas de parâmetros soltos.

## Grupo 1 — FinalSurfaceState

Campos:
- reply_text
- spoken_text
- reply_source
- name_use
- debug_info

## Grupo 2 — FinalDecisionContext

Campos:
- response_mode
- next_step
- topic
- confidence
- question_type
- ai_turns
- msg_type
- ia_accepted
- free_mode

## Grupo 3 — FinalOperationalContext

Campos:
- operational_contract
- base_operational_contract
- has_real_operational_context
- operational_reference
- reference_example
- effective_segment
- operational_family

## Grupo 4 — FinalLeadContext

Campos:
- user_text
- state_summary
- name_hint
- has_name
- is_lead
- segment_hint

## Grupo 5 — FinalKbContext

Campos:
- kb_context
- kb_snapshot
- kb_anchor_strong
- decider
- understanding

## Conclusão

A futura extração do FINAL PIPELINE não deve receber dezenas de parâmetros diretos.

Deve receber objetos/contextos agrupados para preservar legibilidade, reduzir acoplamento e permitir testes isolados.
