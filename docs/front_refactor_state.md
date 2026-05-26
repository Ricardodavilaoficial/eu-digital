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

---

# Consolidação — Fase de mapeamento arquitetural concluída

## Status atual

A refatoração segura do `services/conversational_front.py` avançou de uma fase de micro-extrações para uma fase de engenharia arquitetural consciente.

O arquivo ainda é grande, mas deixou de ser uma massa amorfa. Agora existem macrodomínios, subdomínios, helpers locais, zonas congeladas e contratos futuros mapeados.

## Principais conquistas

### 1. Runtime response orchestration delimitada

A região de runtime orchestration foi identificada como macrodomínio responsável por:
- seleção de material runtime;
- arbitragem de `response_mode`;
- reset estrutural de tópico;
- bypass de discovery;
- controle de `micro_scene_allowed`;
- preparação do contrato operacional antes do pipeline final.

Helpers locais já consolidados:
- `_pick_runtime_scene_material(...)`
- `_apply_current_turn_topic_reset(...)`
- `_apply_response_mode_arbitration(...)`
- `_apply_discovery_to_scene_bypass(...)`

### 2. Zonas perigosas congeladas

Foram classificadas como congeladas por enquanto:
- `micro_scene_allowed gate`;
- `late KB reinforcement`;
- `JSON_FAIL_SAFE`;
- fluxo sensível do `PACK_A_AGENDA`;
- mutações profundas do `operational_contract`.

Decisão:
não mexer nessas zonas até haver contrato melhor e testes mais seguros.

### 3. FINAL PIPELINE identificado como macrodomínio modularizável

A região `12003+` foi reconhecida como macrodomínio de pós-processamento final.

Responsabilidades:
- sanitize final;
- payload replacement;
- direct scene payload;
- compact fallback;
- scene upgrade;
- human wrapper;
- spoken/reply sync;
- final polish;
- final guard.

Conclusão:
o `FINAL PIPELINE` é hoje o candidato mais forte para futura extração em `front_final_pipeline.py`.

### 4. Dependências do FINAL PIPELINE auditadas

Dependências fortes:
- `reply_text`
- `spoken_text`
- `reply_source`
- `response_mode`

Dependências moderadas:
- `operational_contract`
- `base_operational_contract`

Dependências contextuais:
- `kb_context`
- `kb_snapshot`
- `debug_info`
- `understanding`
- `decider`
- `user_text`
- `state_summary`

### 5. Mutação do FINAL PIPELINE auditada

Saídas principais:
- `reply_text`
- `spoken_text`
- `reply_source`

Saídas secundárias:
- `name_use`
- `operational_reference`
- `debug_info`

Conclusão:
o pipeline já demonstra padrão natural de input/output.

### 6. Esboço de contrato futuro criado

Foi desenhado o agrupamento futuro:

- `FinalSurfaceState`
- `FinalDecisionContext`
- `FinalOperationalContext`
- `FinalLeadContext`
- `FinalKbContext`

Objetivo:
evitar futura função com dezenas de parâmetros soltos.

## Commits-chave desta fase

- `eb398f4` — encapsula reset de topico no front
- `25539ba` — registra reset de topico na runtime orchestration
- `7c80c4c` — encapsula arbitragem de response mode
- `53b6b63` — registra arbitragem de response mode
- `98e9564` — congela micro scene gate
- `c661f49` — registra macrodominios do front
- `9140625` — registra dependencias do final pipeline
- `4ec0fc6` — registra subdominios do final pipeline
- `fd9d292` — audita dependencias funcionais do final pipeline
- `f512d54` — registra mutacoes do final pipeline
- `cb5345c` — esboca contrato futuro do final pipeline

## Decisão estratégica

A próxima grande fase deve ser:

Preparação da primeira modularização real, provavelmente começando pelo `FINAL PIPELINE`.

Ainda NÃO criar `front_final_pipeline.py` imediatamente.

Antes disso:
- mapear leitura implícita restante;
- revisar helpers locais usados pelo final pipeline;
- decidir quais helpers sobem para módulos existentes;
- desenhar contrato mínimo de entrada/saída;
- só então fazer extração incremental.

## Regra preservada

Continuar sem corrigir bugs comportamentais durante esta fase estrutural.

As dívidas comportamentais seguem registradas em:
- `docs/front_refactor_debts.md`

---

# Atualização — Final reply size preservation pipeline

Commit:
- `3853d6d` — refactor: encapsula politica final de tamanho da resposta

## Resultado

Foi criado helper local:

`_apply_final_reply_size_policy(...)`

Responsabilidade:
- preservar política especial de resposta técnica DIRECT;
- aplicar `_preserve_technical_direct_reply_size(...)`;
- aplicar `_apply_reply_size_policy(...)`;
- sincronizar `reply_text` e `spoken_text`;
- devolver também `reply_size_policy` e `spoken_size_policy`.

## Domínio delimitado

Novo subdomínio identificado dentro do FINAL PIPELINE:

`Final reply size preservation pipeline`

## Decisão

Manter helper local por enquanto.

Ainda NÃO mover para `front_final_pipeline.py`.

Motivo:
- o FINAL PIPELINE ainda está em fase de revelação arquitetural;
- o contrato futuro já foi mapeado, mas ainda não deve ser implementado;
- a extração para módulo só deve acontecer quando mais subdomínios estiverem estabilizados.

## Segurança

Este patch não altera:
- prompts;
- response_mode;
- micro_scene_allowed;
- JSON_FAIL_SAFE;
- PACK_A_AGENDA;
- KB runtime;
- late KB reinforcement.

## Próximo alvo provável

Auditar e, se seguro, encapsular localmente o subdomínio:

`Question policy enforcement`

Região aproximada:
- após aplicação da política de tamanho;
- bloco que começa em:
  `# Regra de produto: perguntas foram abolidas, salvo exceções controladas.`

---

# Atualização — Final surface polish pipeline

Commit:
- `13ea39a` — refactor: encapsula final surface polish pipeline

## Resultado

Foi criado helper local:

`_apply_final_surface_polish(...)`

Responsabilidade:
- sanitize final;
- guardrails superficiais;
- wrap de superfície;
- spoken/reply sync;
- rescue técnico;
- cleanup final da superfície.

## Domínio delimitado

Novo subdomínio identificado dentro do SAFE FINAL PIPELINE:

`Final surface polish pipeline`

## O que este helper NÃO faz

Não:
- decide intenção;
- altera response_mode;
- controla DISCOVERY;
- controla identity flow;
- controla question policy;
- monta KB;
- gera microcena;
- altera micro_scene_allowed.

## Dependências encapsuladas

- `_try_parse_kb_json(...)`
- `_sanitize_unverified_time_claims(...)`
- `apply_sales_guardrails(...)`
- `wrap_show_response(...)`
- `_sanitize_user_facing_reply(...)`
- `_looks_like_technical_output(...)`
- `_build_contract_consequence(...)`
- `_sync_spoken_after_technical_rescue(...)`

## Decisão arquitetural

Este helper pertence ao domínio:

`SAFE FINAL PIPELINE`

e NÃO ao domínio:

`SOVEREIGN FINAL DECISION`

## Segurança

O patch preserva:
- response_mode;
- DISCOVERY;
- identity guard;
- FINAL GUARD;
- micro_scene_allowed;
- build_kb_show_reply;
- política comercial;
- runtime orchestration.

## Impacto arquitetural

O FINAL PIPELINE agora possui dois micro-pipelines soberanos claramente delimitados:

1. `Final reply size preservation pipeline`
2. `Final surface polish pipeline`

Isso reduz:
- ruído inline;
- acoplamento superficial;
- risco de mini-monólito futuro.

E aproxima a futura extração controlada de:
`front_final_pipeline.py`

---

# Atualização — Response mode surface pipeline

Commit:
- `fef2437` — refactor: encapsula superficie por response mode

## Resultado

Foi criado helper local:

`_apply_response_mode_surface(...)`

Responsabilidade:
- acabamento superficial por response_mode;
- trim/lstrip;
- sincronização básica de superfície;
- spoken/reply normalization.

## Domínio delimitado

Novo subdomínio identificado:

`Response mode surface pipeline`

## O que este helper NÃO faz

Não:
- decide intenção;
- altera response_mode;
- controla DISCOVERY;
- controla identity flow;
- controla clarify flow;
- altera política comercial;
- monta KB;
- gera microcena;
- altera micro_scene_allowed.

## Separação arquitetural descoberta

Dentro do RESPONSE MODE CONTROL PIPELINE existem agora dois domínios diferentes:

### SAFE RESPONSE SURFACE
Modularizável:
- trim;
- lstrip;
- spoken sync;
- normalize surface.

### DISCOVERY SOVEREIGN CONTROL
Ainda congelado:
- `_apply_discovery_mode_identity_guard(...)`
- `needs_clarify`
- `name_use`
- `segment_discovery_resolved`

## Impacto arquitetural

O SAFE FINAL PIPELINE agora possui três micro-pipelines explícitos:

1. `Final reply size preservation pipeline`
2. `Final surface polish pipeline`
3. `Response mode surface pipeline`

## Decisão

DISCOVERY continua fora da modularização inicial.

A futura extração para:
`front_final_pipeline.py`

deve continuar contendo apenas:
- SAFE FINAL PIPELINE;
- SAFE RESPONSE SURFACE.

E NÃO:
- DISCOVERY;
- identity;
- question policy;
- final KB force/recovery.

# Atualização — Auditoria de soberania runtime e pseudo-finais

Data: 2026-05-26

## Descoberta central

O `conversational_front.py` não é um pipeline linear. Ele funciona como uma federação de pipelines soberanos concorrentes.

Foram identificados:

- múltiplos terminais;
- múltiplos ownership layers de `reply_text`;
- runtime recovery infrastructure;
- response_mode governance distribuída;
- DISCOVERY governance;
- SCENE governance;
- terminal payload governors;
- anti-corruption governance para envelope JSON.

## Terminais identificados

### Early Discovery Terminal
Trecho aproximado:
- 10049+

Responsabilidade:
- retornar DISCOVERY cedo;
- bypassar o final pipeline oficial.

Classificação:
- terminal soberano controlado.

### Direct Scene Early Terminal
Trecho aproximado:
- 9969–10010

Responsabilidade:
- retornar `front_direct_scene` cedo quando `_continue_after_direct_scene` é falso;
- bypassar final surface polish, final guard e terminal payload governors.

Classificação:
- early terminal soberano de alto risco.

### Official Final Pipeline
Trecho aproximado:
- 12400–12935

Responsabilidade:
- final surface polish;
- final recovery;
- response mode surface;
- structured assembly tardio;
- humanization;
- payload rebuild;
- failsafe;
- unwrap final;
- sanitize terminal;
- `return result`.

Classificação:
- terminal oficial verdadeiro.

## Ownership layers identificados

### Content ownership
Quem decide ou substitui conteúdo:
- `_build_kb_show_reply`
- `_build_kb_anchor_reply`
- `_generate_micro_scene_with_model`
- `_front_build_structured_assembly_reply`
- fallbacks e recoveries.

### Surface ownership
Quem altera forma:
- `_apply_final_surface_polish`
- `_apply_response_mode_surface`
- `_front_finalize_reply_surface`
- `_front_remove_unsafe_nominal_opening`
- `_humanize_reply_with_lead_context`

### Payload ownership
Quem controla o objeto final:
- `out = {...}`
- `_sanitize_front_result_payload`
- `_unwrap_front_json_envelope`
- final payload blindagem.

## Decisão

Não iniciar extração física ainda.

Antes:
- documentar boundaries;
- congelar domínios soberanos;
- preservar SAFE FINAL PIPELINE separado de recovery/reconstruction;
- evitar mover helpers por proximidade de linha.

# Atualização — Auditoria SAFE FINAL PIPELINE

## Resultado da auditoria prática

Foi confirmado que os helpers locais possuem níveis diferentes de soberania arquitetural.

### PURE SAFE FINAL PIPELINE

Helpers:
- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Características:
- não tocam KB;
- não alteram response_mode;
- não geram conteúdo;
- não alteram micro_scene_allowed;
- não executam recovery runtime.

### SAFE/SURFACE HYBRID

Helpers:
- `_apply_final_reply_size_policy(...)`
- `_apply_final_surface_polish(...)`

Características:
- permanecem relativamente seguros;
- porém já encostam em:
  - KB parsing;
  - contract consequence generation;
  - technical rescue;
  - operational surface enhancement.

Decisão:
- ainda NÃO mover para módulo;
- manter locais;
- evitar classificá-los como PURE SAFE.

### Runtime Recovery Infrastructure confirmado

Região:
- 12423–12460

Responsabilidade:
- late KB reinjection;
- final operational recovery;
- scene/runtime resurrection via `_build_kb_show_reply(...)`.

Classificação:
- domínio soberano de recovery;
- NÃO pertence ao SAFE FINAL PIPELINE.

# Atualização — Consequence generation boundary

Foi confirmado que:

- `_generate_consequence_with_model(...)`
- `_build_contract_consequence(...)`

não pertencem ao SAFE FINAL PIPELINE.

Esses helpers:
- usam IA;
- geram consequência contextual curta;
- atuam como enhancement operacional leve;
- podem funcionar como fallback superficial quando a saída degrada para conteúdo excessivamente técnico.

Classificação:
`OPERATIONAL SURFACE ENHANCEMENT`

