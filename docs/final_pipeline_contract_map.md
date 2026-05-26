# FINAL PIPELINE CONTRACT MAP — conversational_front.py

## Objetivo

Preparar a futura extração segura do FINAL PIPELINE para `front_final_pipeline.py`.

Nesta fase:
- NÃO mover código;
- NÃO corrigir bugs comportamentais;
- NÃO alterar prompts;
- NÃO alterar regras de response_mode;
- NÃO mexer em JSON_FAIL_SAFE;
- NÃO tocar no micro_scene gate.

O objetivo é apenas mapear contrato, entradas, saídas, helpers e riscos.

---

## Região alvo

Arquivo:
- `services/conversational_front.py`

Faixa aproximada:
- `12003–12320+`

Macrodomínio:
- FINAL PIPELINE

Responsabilidades:
- sanitize final;
- payload replacement;
- direct scene payload;
- compact fallback;
- scene upgrade;
- human wrapper;
- spoken/reply sync;
- reply size preservation;
- question policy enforcement;
- final guardrails;
- final empty guard.

---

## Saídas principais mutadas

- `reply_text`
- `spoken_text`
- `reply_source`

---

## Saídas secundárias mutadas

- `name_use`
- `operational_reference`
- `debug_info`

---

## Dependências fortes

- `response_mode`
- `reply_text`
- `spoken_text`
- `reply_source`

---

## Dependências operacionais

- `operational_contract`
- `base_operational_contract`
- `has_real_operational_context`
- `micro_scene_allowed`
- `operational_reference`
- `reference_example`
- `effective_segment`
- `operational_family`

---

## Dependências de contexto

- `kb_context`
- `kb_snapshot`
- `decider`
- `understanding`
- `user_text`
- `state_summary`
- `msg_type`
- `ai_turns`
- `next_step`
- `topic`
- `confidence`
- `question_type`
- `free_mode`

---

## Helpers externos já envolvidos

### services/front_assembly.py

Responsável por:
- limpeza textual;
- humanização determinística;
- payload scene;
- wrapper final;
- sanitize de resposta ao usuário.

Helpers relevantes:
- `_build_direct_scene_payload`
- `_humanize_scene_flow`
- `_looks_like_structural_scene_payload`
- `_sanitize_user_facing_reply`
- `wrap_show_response`

### services/front_policies.py

Responsável por:
- política de tamanho;
- preservação de resposta técnica;
- truncamento seguro.

Helpers relevantes:
- `_apply_reply_size_policy`
- `_preserve_technical_direct_reply_size`

### services/front_kb.py

Responsável por:
- parsing de snapshot KB;
- composição de material runtime pack;
- aplicação de slots.

Helpers relevantes:
- `_try_parse_kb_json`

### services/front_guards.py

Responsável por:
- guards estruturais;
- validação de formato;
- densidade operacional;
- segurança de resposta.

### services/front_utils.py

Responsável por:
- utilitários puros;
- normalização;
- extração JSON;
- truncamento simples;
- formatação.

---

## Helpers ainda locais usados ou próximos do FINAL PIPELINE

- `_sanitize_unverified_time_claims`
- `_should_allow_question`
- `_sync_spoken_after_technical_rescue`
- `_build_kb_show_reply`
- `_upgrade_operational_reply_with_model`
- `_build_contract_consequence`
- `_apply_non_empty_reply_guard`
- `_restore_final_candidate_if_degraded`
- `_apply_identity_clarify_guard`

Decisão atual:
- manter locais por enquanto;
- não mover para módulo antes de mapear dependências reais.

---

## Subdomínios internos do FINAL PIPELINE

### 1. Scene upgrade / humanization

Responsabilidade:
- evitar saída estrutural crua;
- humanizar cena quando há payload operacional.

### 2. Name discovery post-pass

Responsabilidade:
- garantir solicitação de nome quando necessário;
- evitar desperdício do turno inicial.

### 3. Reply size preservation

Responsabilidade:
- preservar densidade técnica em DIRECT;
- aplicar política de tamanho correta;
- sincronizar spoken/reply.

### 4. Question policy enforcement

Responsabilidade:
- impedir perguntas fora da política;
- preservar apenas perguntas permitidas:
  - nome;
  - segmento;
  - esclarecimento de intenção.

### 5. Final guardrails

Responsabilidade:
- sanitize final;
- anti-invenção;
- rescue técnico;
- sync spoken/reply;
- evitar degradação.

### 6. Final empty guard

Responsabilidade:
- impedir resposta vazia;
- fallback final mínimo.

---

## Contrato futuro sugerido

A futura extração NÃO deve receber dezenas de parâmetros soltos.

Agrupar em estruturas conceituais:

### FinalSurfaceState

Campos:
- `reply_text`
- `spoken_text`
- `reply_source`
- `name_use`
- `debug_info`

### FinalDecisionContext

Campos:
- `response_mode`
- `next_step`
- `topic`
- `confidence`
- `question_type`
- `ai_turns`
- `msg_type`
- `ia_accepted`
- `free_mode`

### FinalOperationalContext

Campos:
- `operational_contract`
- `base_operational_contract`
- `has_real_operational_context`
- `micro_scene_allowed`
- `operational_reference`
- `reference_example`
- `effective_segment`
- `operational_family`

### FinalLeadContext

Campos:
- `user_text`
- `state_summary`
- `name_hint`
- `has_name`
- `is_lead`
- `segment_hint`

### FinalKbContext

Campos:
- `kb_context`
- `kb_snapshot`
- `kb_anchor_strong`
- `decider`
- `understanding`

---

## Riscos conhecidos

### 1. Criar mini-monólito novo

Risco:
- mover o FINAL PIPELINE inteiro para outro arquivo sem contrato claro.

Decisão:
- proibido nesta fase.

### 2. Misturar refatoração com correção comportamental

Risco:
- corrigir PACK_A_AGENDA, JSON_FAIL_SAFE ou identity bugs no meio da extração.

Decisão:
- proibido nesta fase.

### 3. Quebrar sync reply/spoken

Risco:
- texto e áudio divergirem.

Decisão:
- qualquer futura extração deve retornar explicitamente `reply_text` e `spoken_text`.

### 4. Perder reply_source

Risco:
- telemetria e diagnóstico ficarem cegos.

Decisão:
- `reply_source` deve fazer parte do contrato de saída.

### 5. Mover helper local cedo demais

Risco:
- helper ainda depender de variáveis implícitas do `handle()`.

Decisão:
- primeiro mapear, depois mover.

---

## Zonas congeladas

Não mexer agora:
- `JSON_FAIL_SAFE`
- `PACK_A_AGENDA`
- `micro_scene_allowed gate`
- `late KB reinforcement`
- mutações profundas de `operational_contract`
- regras de `response_mode`

---

## Próxima etapa após este documento

1. Auditar no código o trecho `12003–12320+`.
2. Confirmar se os grupos de contrato estão completos.
3. Identificar qual subdomínio pode virar primeiro helper local.
4. Fazer micro-patch local, ainda dentro de `conversational_front.py`.
5. Rodar `py_compile`.
6. Commit isolado.
7. Push.

---

## Decisão atual

A próxima ação de código ainda NÃO é criar `front_final_pipeline.py`.

A próxima ação de código deve ser apenas encapsular localmente um subdomínio pequeno do FINAL PIPELINE, preservando comportamento.

---

# Descoberta arquitetural — SAFE FINAL PIPELINE vs SOVEREIGN FINAL DECISION

## Observação

Durante a auditoria do bloco de `Question policy enforcement`, foi identificado que o FINAL PIPELINE possui dois tipos muito diferentes de responsabilidade.

---

## 1. SAFE FINAL PIPELINE

Responsabilidades:
- sanitize;
- size policy;
- spoken/reply sync;
- wrappers;
- humanização superficial;
- empty guard;
- final polish;
- payload shaping.

Características:
- baixo risco comportamental;
- não decide intenção;
- não altera response_mode;
- não controla discovery;
- não altera política comercial;
- altamente modularizável.

Exemplos já delimitados:
- `_apply_final_reply_size_policy(...)`
- `_apply_reply_size_policy(...)`
- `_preserve_technical_direct_reply_size(...)`
- wrappers de sanitize/humanização.

---

## 2. SOVEREIGN FINAL DECISION

Responsabilidades:
- policy de perguntas;
- discovery permission;
- clarify permission;
- identity permission;
- decisão sobre remoção de perguntas;
- controle final de comportamento conversacional.

Características:
- alto risco;
- altera experiência do lead;
- altera comportamento comercial;
- encosta em DISCOVERY;
- encosta em identity flow;
- encosta em ambiguity handling;
- não deve ser modularizado cedo.

Exemplo principal:
- `_should_allow_question(...)`

---

## Decisão arquitetural

A futura extração para `front_final_pipeline.py` deve inicialmente conter apenas o domínio:

`SAFE FINAL PIPELINE`

A camada:
`SOVEREIGN FINAL DECISION`

deve permanecer temporariamente dentro do `conversational_front.py` até:
- maior estabilização arquitetural;
- isolamento futuro de identity/discovery/clarify policies;
- separação mais clara de decisões soberanas.

---

## Impacto estratégico

Essa separação reduz drasticamente o risco de:

- mover comportamento soberano cedo demais;
- quebrar DISCOVERY;
- quebrar política comercial;
- quebrar fluxo de identidade;
- transformar o novo módulo em mini-monólito comportamental.

---

# Auditoria — FINAL GUARD

## Região auditada

Arquivo:
- `services/conversational_front.py`

Região aproximada:
- `12423–12529`

## Conclusão

O FINAL GUARD não é um domínio único e simples.

Ele se divide em pelo menos três subdomínios:

---

## 1. Empty output recovery

Responsabilidade:
- impedir resposta vazia;
- impedir resposta curta demais;
- tentar reconstrução operacional.

Risco:
- alto.

Motivo:
- toca `micro_scene_allowed`;
- lê `operational_contract`;
- lê `base_operational_contract`;
- depende de contexto KB;
- pode alterar completamente a superfície final.

Decisão:
- congelado.

---

## 2. KB show / anchor recovery

Responsabilidade:
- reconstruir resposta via:
  - `_build_kb_show_reply(...)`;
  - `_build_kb_anchor_reply(...)`.

Risco:
- muito alto.

Motivo:
- pode recriar cena operacional;
- pode reintroduzir fallback global;
- pode mascarar falhas anteriores do pipeline;
- encosta nos bugs conhecidos de PACK_A_AGENDA/tutorialização.

Decisão:
- congelado.

---

## 3. Final candidate restoration

Helper:
- `_restore_final_candidate_if_degraded(...)`

Responsabilidade:
- restaurar `_final_candidate` quando `reply_text` degradou para vazio ou curto.

Características:
- não chama modelo;
- não toca KB;
- não altera política;
- não decide response_mode;
- não mexe em identity/discovery;
- apenas preserva melhor versão já produzida.

Risco:
- baixo.

Decisão:
- pertence ao SAFE FINAL PIPELINE;
- já está encapsulado;
- não precisa patch agora.

---

## Decisão arquitetural

Não extrair FINAL GUARD nesta fase.

A futura extração para `front_final_pipeline.py` pode considerar apenas:
- final candidate restoration;
- surface polish;
- size policy;
- response surface.

Mas deve excluir por enquanto:
- empty output recovery;
- KB show recovery;
- KB anchor recovery;
- qualquer reconstrução operacional baseada em `micro_scene_allowed`.

---

## Próximo trabalho futuro

Antes de mexer no FINAL GUARD, será necessário auditar separadamente:

- `_build_kb_show_reply(...)`;
- `_build_kb_anchor_reply(...)`;
- `allow_scene_runtime`;
- `kb_show_reply_seed`;
- relação com PACK_A_AGENDA;
- relação com `micro_scene_allowed`.

---

# Auditoria profunda — Operational Reconstruction Engine

## Descoberta arquitetural crítica

Durante a auditoria profunda do FINAL GUARD e dos mecanismos de recuperação operacional, foi identificado que o front possui um núcleo soberano separado do SAFE FINAL PIPELINE.

Esse núcleo foi classificado como:

`OPERATIONAL RECONSTRUCTION ENGINE`

---

# Camadas arquiteturais reais identificadas

## 1. SAFE FINAL PIPELINE

Responsabilidade:
- sanitize;
- size policy;
- surface polish;
- spoken sync;
- response surface normalization;
- preservação superficial.

Características:
- sem mutação soberana;
- sem reconstrução operacional;
- sem geração estrutural;
- modularização segura.

Helpers já identificados:
- `_apply_final_reply_size_policy(...)`
- `_apply_final_surface_polish(...)`
- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

---

## 2. OPERATIONAL SURFACE ENHANCEMENT

Responsabilidade:
- reescrever superfície operacional já válida;
- melhorar fluidez;
- melhorar legibilidade;
- gerar consequência final curta.

Características:
- usa IA;
- mas não reconstrói runtime;
- não muta contract;
- não altera response_mode;
- não altera micro_scene_allowed;
- risco médio/baixo.

Helpers identificados:
- `_upgrade_operational_reply_with_model(...)`
- `_generate_consequence_with_model(...)`
- `_build_contract_consequence(...)`

---

## 3. OPERATIONAL RECONSTRUCTION ENGINE

Responsabilidade:
- reconstrução operacional soberana;
- regeneração de microcena;
- fallback operacional;
- recovery de runtime;
- mutação de contrato operacional;
- controle de scene runtime.

Características:
- altamente sensível;
- altamente acoplado;
- muta estado soberano;
- altera response_mode;
- altera topic;
- altera intent;
- altera micro_scene_allowed;
- pode resetar runtime operacional.

Helper central identificado:
- `_generate_micro_scene_with_model(...)`

---

# Descoberta crítica — mutações soberanas

Foi identificado que `_generate_micro_scene_with_model(...)`:

- altera `topic`;
- altera `intent`;
- altera `response_mode`;
- altera `micro_scene_allowed`;
- altera `global_pack_fallback`;
- remove campos runtime do `operational_contract`.

Trecho crítico identificado:

```python
operational_contract["micro_scene_allowed"] = False
operational_contract["global_pack_fallback"] = False

---

# Descoberta arquitetural — Runtime Recovery Infrastructure

## Conclusão crítica

Foi identificado que o front atual possui uma infraestrutura transversal de recuperação runtime.

Essa infraestrutura NÃO pertence:
- ao SAFE FINAL PIPELINE;
- ao assembly;
- ao response surface;
- ao sanitize pipeline.

Ela forma um domínio arquitetural separado.

Classificação:

`RUNTIME RECOVERY INFRASTRUCTURE`

---

# Núcleo central identificado

Helper central:

`_build_kb_anchor_reply(...)`

Classificação:
- Runtime Recovery Entry Point.

---

# Responsabilidade real

O helper `_build_kb_anchor_reply(...)` atua como:

- fallback operacional transversal;
- recovery runtime;
- reanimação operacional;
- reconstrução de superfície;
- restaurador de cena operacional.

---

# Descoberta crítica

O sistema atual segue implicitamente a seguinte lógica:

```text
Se o pipeline degrada →
    chama _build_kb_anchor_reply →
        que pode:
            gerar microcena;
            reconstruir runtime;
            restaurar superfície operacional;
            reanimar fluxo.
