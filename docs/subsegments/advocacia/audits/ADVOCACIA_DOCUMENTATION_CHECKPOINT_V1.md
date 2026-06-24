# ADVOCACIA_DOCUMENTATION_CHECKPOINT_V1

## Objetivo

Registrar o checkpoint documental da construção inicial de Advocacia na Fábrica de Segmentos do MEI Robô.

Este documento não cria JSON.

Este documento não aplica Firestore.

Este documento não altera código.

Este documento não cria micro_scene_conversational.

---

# 1. Estado atual

A fase atual é documental.

Foram criados documentos de:

```text
decisão arquitetural
modelo canônico
runtime safety base
runtime de advocacia individual
runtime de escritório de advocacia
mapeamento Firestore base
mapeamento Firestore individual
mapeamento Firestore escritório
notas de pesquisa-fonte
componentes reutilizáveis
incrementos de fábrica
auditoria documental
```

---

# 2. Arquivos criados na base comum

```text
docs\subsegments\advocacia\audits\ADVOCACIA_ARCHITECTURE_DECISION_V1.md
docs\subsegments\advocacia\audits\ADVOCACIA_RUNTIME_DOCUMENTATION_AUDIT_V1.md
docs\subsegments\advocacia\source\ADVOCACIA_BASE_CANONICAL_MODEL_V1.md
docs\subsegments\advocacia\source\ADVOCACIA_SOURCE_RESEARCH_NOTES_V1.md
docs\subsegments\advocacia\runtime\ADVOCACIA_BASE_RUNTIME_SAFETY_V1.md
docs\subsegments\advocacia\firestore\ADVOCACIA_FIRESTORE_MAPPING_DECISION_V1.md
docs\subsegments\advocacia\lessons_learned\ADVOCACIA_FACTORY_INCREMENTS_V1.md
```

---

# 3. Arquivos criados nos subsegmentos operacionais

Advocacia Individual:

```text
docs\subsegments\advocacia_individual\runtime\RUNTIME_ADVOCACIA_INDIVIDUAL_V1.md
docs\subsegments\advocacia_individual\firestore\ADVOCACIA_INDIVIDUAL_FIRESTORE_FIELD_MAPPING_V1.md
```

Escritório de Advocacia:

```text
docs\subsegments\escritorio_advocacia\runtime\RUNTIME_ESCRITORIO_ADVOCACIA_V1.md
docs\subsegments\escritorio_advocacia\firestore\ESCRITORIO_ADVOCACIA_FIRESTORE_FIELD_MAPPING_V1.md
```

---

# 4. Arquivos centrais da fábrica

Arquivo criado:

```text
docs\segment_factory\reusable_assets\ADVOCACIA_REUSABLE_COMPONENTS_V1.md
```

Arquivo incrementado:

```text
docs\segment_factory\reusable_assets\FACTORY_REUSE_STATUS_V1.md
```

Bloco incluído:

```text
CANDIDATE_FROM_ADVOCACIA
```

---

# 5. Decisões preservadas

Advocacia será modelada como:

```text
base comum
+
dois subsegmentos operacionais
```

Subsegmentos futuros:

```text
servicos_profissionais__advocacia_individual
servicos_profissionais__escritorio_advocacia
```

Regra central:

```text
o robô organiza o contato;
o advogado realiza a análise jurídica.
```

Regra comercial:

```text
o vendedor vende confiança.
```

Regra GPT-4o-mini:

```text
limites profissionais devem virar trilhos positivos de condução.
```

---

# 6. Itens ainda pendentes

Ainda não foram criados:

```text
micro_scene_conversational
JSON Firestore
scripts de aplicação
dry-run
aplicação no Firestore
deploy
alteração de código
alteração de prompt da aplicação
```

---

# 7. Decisão sobre micro_scene_conversational

A micro_scene_conversational de Advocacia permanece pendente.

Ela será construída separadamente, com supervisão direta do usuário.

Não improvisar.

Não copiar microcena de outro subsegmento.

Não preencher JSON antes dessa etapa.

---

# 8. Decisão sobre Firestore

A estrutura futura deve seguir o padrão V2 observado em Otorrino:

```text
commercial_runtime
operational_runtime
behavior_components
snapshot_priority
```

Decisão conservadora:

```text
não criar legal_runtime agora
não usar medical_runtime em Advocacia
modelar segurança jurídica dentro de operational_runtime, behavior_components e snapshot_priority
```

---

# 9. Próxima etapa recomendada

A próxima etapa segura é:

```text
1. revisar documentação criada
2. construir micro_scene_conversational com supervisão direta
3. validar segment_id e archetype_id reais
4. gerar JSONs separados
5. executar dry-run
6. aplicar Firestore somente com autorização explícita
```

---

# 10. Síntese

A fase documental inicial de Advocacia está pronta para checkpoint.

A fábrica recebeu novos componentes candidatos.

A arquitetura preserva ética, venda por confiança, utilidade de informação e compatibilidade com GPT-4o-mini.

A próxima fase não deve começar por JSON.

A próxima fase deve começar pela micro_scene_conversational supervisionada ou por revisão documental.
