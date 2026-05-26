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

