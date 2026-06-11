# CLINICA_EXAMES_FIRESTORE_MAPPING_V1

## Objetivo

Mapear os artefatos documentais do subsegmento Clínica de Exames Médicos para a estrutura efetivamente carregável no Firestore.

Este documento não cria novos comportamentos.

Ele apenas define:

* o que será carregado;
* o que permanecerá apenas como documentação da fábrica;
* o que será utilizado pelo runtime conversacional.

---

# Documento Firestore alvo

Collection:

kb_subsegments_v1

Document ID:

saude__clinica_exames_medicos

---

# Origem dos dados

## Specialist Matrix

Origem:

CLINICA_EXAMES_SPECIALIST_REASONING_MATRIX_V1.md

Destino:

NÃO CARREGAR

Uso:

Documentação da fábrica.

---

## Canonical Model

Origem:

CLINICA_EXAMES_CANONICAL_MODEL_V1.md

Destino:

NÃO CARREGAR

Uso:

Patrimônio metodológico da fábrica.

---

## Runtime Compact

Origem:

CLINICA_EXAMES_RUNTIME_COMPACT_V1.md

Destino:

CARREGAR

Uso:

Base cognitiva resumida utilizada pelo runtime.

---

# Campos Firestore

## id

Valor:

saude__clinica_exames_medicos

---

## name

Valor:

Clínica de Exames Médicos

---

## segment_id

Valor:

saude

---

## archetype_id

Valor:

atendimento_diagnostico_agendado

---

## enabled

Valor:

true

---

## conversation_mode

Valor:

consultivo

---

## customer_noun

Valor:

paciente

---

## service_noun

Valor:

exame

---

## conversion_noun

Valor:

agendamento confirmado

---

## primary_goal

Valor:

conduzir_para_agendamento_ou_execucao_segura

---

## description

Origem:

Canonical Model

---

## one_liner

Origem:

Runtime Compact

---

## one_question

Origem:

Runtime Compact

---

## micro_scene

Origem:

Runtime Compact

---

## micro_scene_conversational

Origem:

Runtime Compact

---

# Operational Rules

Origem:

Runtime Compact

Destino:

operational_rules

---

# Real Customer Situations

Origem:

Runtime Compact

Destino:

real_customer_situations

---

# Common Intents

Origem:

Runtime Compact

Destino:

common_intents

---

# Keywords

Origem:

Runtime Compact

Destino:

keywords

---

# Negative Keywords

Origem:

Runtime Compact

Destino:

negative_keywords

---

# Runtime Compact

Origem:

CLINICA_EXAMES_RUNTIME_COMPACT_V1.md

Destino:

runtime_compact

Formato:

texto único consolidado

---

# Componentes candidatos

## COMPONENT_ACCESS_PATH_ROUTING

Destino:

NÃO CARREGAR

Motivo:

Patrimônio da fábrica.

---

## COMPONENT_AUTHORIZATION_WORKFLOW

Destino:

NÃO CARREGAR

Motivo:

Patrimônio da fábrica.

---

## COMPONENT_EXAM_READINESS_VALIDATION

Destino:

NÃO CARREGAR

Motivo:

Patrimônio da fábrica.

---

# Auditorias

Destino:

NÃO CARREGAR

Arquivos:

* Runtime Audit
* Component Audit
* Reuse Analysis
* Lessons Learned
* Final Segment Audit

Uso:

Governança interna.

---

# Decisão final

Resultado:

CLINICA_EXAMES_FIRESTORE_MAPPING_APPROVED_V1

Apenas o runtime compacto e os metadados do subsegmento devem ser enviados ao Firestore.

Os artefatos metodológicos permanecem fora do banco e continuam como patrimônio da fábrica.
