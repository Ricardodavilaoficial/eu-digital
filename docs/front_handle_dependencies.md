# FRONT HANDLE DEPENDENCIES

## Objetivo

Mapear as dependências internas do `handle()` em:

`services/conversational_front.py`

Este documento descreve:
- dependências críticas;
- acoplamentos internos;
- zonas SAFE;
- zonas SOVEREIGN;
- riscos de extração;
- pontos que ainda impedem modularização direta.

---

# Descoberta central

O `handle()` concentra dependências porque ainda é o:

`SOVEREIGN RUNTIME CORE`

Ele coordena:
- input;
- understanding;
- KB material;
- orchestration;
- discovery;
- response_mode;
- recovery;
- final pipeline;
- terminals.

---

# Dependências estruturais principais

## 1. Runtime state

Inclui:
- response_mode;
- reply_text;
- spoken_text;
- reply_source;
- next_step;
- topic;
- confidence;
- question_type.

Classificação:
`SOVEREIGN`

---

## 2. Lead context

Inclui:
- user_text;
- state_summary;
- name_hint;
- has_name;
- segment_hint;
- is_lead;
- effective_segment.

Classificação:
`SOVEREIGN CONTEXT`

---

## 3. KB context

Inclui:
- kb_context;
- kb_snapshot;
- operational_contract;
- base_operational_contract;
- runtime_short;
- runtime_long;
- material packs.

Classificação:
`MIXED`

Pode ser:
- SAFE materialization;
- HIGH RISK recovery source.

---

## 4. Operational context

Inclui:
- operational_reference;
- reference_example;
- operational_family;
- has_real_operational_context;
- micro_scene_allowed.

Classificação:
`HIGH RISK SOVEREIGN`

---

## 5. Debug / telemetry

Inclui:
- debug_info;
- decision markers;
- policy markers;
- source markers.

Classificação:
`SUPPORTING CONTEXT`

---

# Dependências SAFE

## Surface dependencies

Podem ser isoladas quando:
- apenas normalizam;
- apenas limpam;
- apenas sincronizam;
- não alteram runtime.

Exemplo:
- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Status:
- já extraídas para `services/front_surface.py`.

---

## Utility dependencies

Podem ser compartilhadas quando:
- não carregam estado;
- não decidem;
- não fazem recovery.

---

# Dependências SOVEREIGN

## Discovery dependencies

Incluem:
- identity;
- clarify;
- discovery enforcement;
- discovery terminal.

Não mover agora.

---

## Response arbitration dependencies

Incluem:
- response_mode;
- promotion;
- degradation;
- bypasses.

Não mover agora.

---

## Scene dependencies

Incluem:
- `micro_scene_allowed`;
- `allow_scene_runtime`;
- grounded scene validation;
- scene activation.

Não mover agora.

---

## Recovery dependencies

Incluem:
- `_build_kb_show_reply(...)`;
- `_build_kb_anchor_reply(...)`;
- `_build_last_resort_operational_reply(...)`;
- runtime resurrection.

Não mover agora.

---

# Dependências que impedem extração direta do handle()

## Mutação distribuída

Variáveis como:
- reply_text;
- spoken_text;
- reply_source;
- response_mode;
- operational_reference;

são mutadas em múltiplas fases.

---

## Terminais múltiplos

O `handle()` possui:
- early discovery terminal;
- direct scene early terminal;
- official final terminal.

---

## Recovery transversal

Recovery pode ocorrer:
- antes do final pipeline;
- dentro do final pipeline;
- próximo ao terminal.

---

## KB como material e recovery source

O KB aparece como:
- material estruturado;
- fallback;
- recovery;
- pseudo-scene risk.

---

# Contrato futuro desejável

A extração futura não deve passar dezenas de parâmetros soltos.

Deve agrupar contexto em objetos conceituais:

## SurfaceState

Campos:
- reply_text;
- spoken_text;
- reply_source.

---

## DecisionContext

Campos:
- response_mode;
- next_step;
- topic;
- confidence;
- question_type.

---

## LeadContext

Campos:
- user_text;
- state_summary;
- name_hint;
- has_name;
- segment_hint;
- is_lead.

---

## OperationalContext

Campos:
- operational_contract;
- base_operational_contract;
- has_real_operational_context;
- operational_reference;
- micro_scene_allowed.

---

## KbContext

Campos:
- kb_context;
- kb_snapshot;
- runtime material;
- packs.

---

# SAFE vs SOVEREIGN

## SAFE

Pode:
- limpar;
- normalizar;
- sincronizar;
- preservar superfície.

---

## SOVEREIGN

Controla:
- runtime;
- arbitration;
- discovery;
- recovery;
- terminals;
- scene governance.

---

# Zonas congeladas

## PROIBIDO MOVER AGORA

- discovery flow;
- response arbitration;
- scene gating;
- runtime recovery;
- terminal governance;
- KB recovery source;
- JSON_FAIL_SAFE.

---

# Estado atual

O `handle()` já está mais compreensível porque:
- macrodomínios foram mapeados;
- helpers SAFE foram extraídos;
- módulos auxiliares foram estabilizados;
- o core soberano foi isolado conceitualmente.

Mas ainda não deve ser quebrado fisicamente.

---

# Decisão consolidada

A próxima redução segura do `handle()` deve ocorrer por:
- contratos agrupados;
- helpers pequenos;
- extrações SAFE;
- sem alterar ordem runtime.

---

# Conclusão

O `handle()` ainda deve permanecer como:

`SOVEREIGN RUNTIME CORE`

até que:
- recovery seja melhor isolado;
- terminals sejam explicitamente preservados;
- mutações sejam agrupadas;
- contratos de entrada/saída estejam claros.