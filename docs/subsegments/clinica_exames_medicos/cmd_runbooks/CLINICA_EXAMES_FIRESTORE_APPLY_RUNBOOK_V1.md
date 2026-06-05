# CLINICA_EXAMES_FIRESTORE_APPLY_RUNBOOK_V1

## Objetivo

Documentar o procedimento oficial para aplicação do subsegmento Clínica de Exames Médicos no Firestore quando o billing estiver regularizado.

Este runbook segue integralmente o Modo Operante Oficial da Fábrica de Segmentos.

---

# Pré-requisitos

## Billing

Status necessário:

ATIVO

---

## Runtime aprovado

Necessário:

* CLINICA_EXAMES_RUNTIME_COMPACT_V1.md

Status:

APROVADO

---

## Mapping aprovado

Necessário:

* CLINICA_EXAMES_FIRESTORE_MAPPING_V1.md

Status:

APROVADO

---

## JSON aprovado

Necessário:

* CLINICA_EXAMES_FIRESTORE_JSON_V1.json

Status:

APROVADO

---

# Documento alvo

Collection:

kb_subsegments_v1

Document ID:

saude__clinica_exames_medicos

---

# Fase 1 — Inspeção

Validar existência dos artefatos:

```cmd
dir docs\subsegments\clinica_exames_medicos\source
```

Confirmar presença de:

* Runtime Compact
* Mapping
* JSON

---

# Fase 2 — Validação JSON

Executar:

```cmd
python -m json.tool docs\subsegments\clinica_exames_medicos\source\CLINICA_EXAMES_FIRESTORE_JSON_V1.json > nul
```

Resultado esperado:

Sem erros.

---

# Fase 3 — Dry Run

Objetivo:

Validar estrutura antes da escrita definitiva.

Regras:

* não sobrescrever outros documentos;
* não alterar coleções existentes;
* validar schema;
* registrar resultado.

Status esperado:

DRY_RUN_APPROVED

---

# Fase 4 — Aplicação

Regras obrigatórias:

* utilizar merge=True;
* preservar compatibilidade;
* não remover campos existentes sem auditoria.

Documento:

saude__clinica_exames_medicos

Coleção:

kb_subsegments_v1

---

# Fase 5 — Verificação pós-aplicação

Validar:

* documento criado;
* campos carregados;
* runtime_compact presente;
* operational_rules presentes;
* keywords presentes;
* common_intents presentes;
* real_customer_situations presentes.

Resultado esperado:

FIRESTORE_DOCUMENT_APPROVED

---

# Fase 6 — Rollback

Caso necessário:

```cmd
git log --oneline -10
```

Localizar versão aprovada.

Aplicar correção controlada.

Nunca remover diretamente sem auditoria.

---

# Restrições

Não carregar:

* Matrix
* Canonical
* Runtime Audit
* Component Audit
* Reuse Analysis
* Lessons Learned
* Final Segment Audit

Esses artefatos pertencem à governança da fábrica.

---

# Resultado esperado

Status final:

CLINICA_EXAMES_FIRESTORE_APPLIED_V1

Coleção:

kb_subsegments_v1

Documento:

saude__clinica_exames_medicos

---

# Observação arquitetural

Os componentes:

* COMPONENT_ACCESS_PATH_ROUTING
* COMPONENT_AUTHORIZATION_WORKFLOW
* COMPONENT_EXAM_READINESS_VALIDATION

permanecem como patrimônio metodológico da fábrica.

Eles não devem gerar coleções próprias nesta etapa.

O Firestore recebe apenas o runtime operacional consolidado do subsegmento.
