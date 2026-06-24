# ADVOCACIA_RUNTIME_DOCUMENTATION_AUDIT_V1

## Objetivo

Auditar a primeira etapa documental do subsegmento Advocacia na Fábrica de Segmentos do MEI Robô.

Este documento não cria JSON.

Este documento não altera Firestore.

Este documento não altera código.

Este documento não cria micro_scene_conversational.

Ele confirma o estado atual, os arquivos criados, as decisões tomadas e os próximos passos seguros.

---

# 1. Estado geral

A etapa atual de Advocacia está em fase documental e de modelagem.

Foram criadas:

```text
1. base arquitetural
2. base canônica comum
3. runtime safety base
4. runtime de advocacia individual
5. runtime de escritório de advocacia
6. arquivo central de componentes reutilizáveis
7. incremento no status central da fábrica
8. registro de aprendizados da fábrica
```

Não foram criados:

```text
JSON Firestore
micro_scene_conversational
scripts de aplicação
patches de código
deploy
alterações no Cloud Run
alterações em prompts da aplicação
```

---

# 2. Decisão arquitetural confirmada

Advocacia foi modelada como:

```text
base canônica comum
+
dois subsegmentos operacionais separados
```

Base comum:

```text
docs\subsegments\advocacia
```

Subsegmentos operacionais:

```text
docs\subsegments\advocacia_individual
docs\subsegments\escritorio_advocacia
```

IDs Firestore candidatos:

```text
servicos_profissionais__advocacia_individual
servicos_profissionais__escritorio_advocacia
```

Justificativa:

Advocacia individual vende confiança pessoal.

Escritório de advocacia vende confiança institucional, método, equipe e encaminhamento correto.

Separar os runtimes reduz o risco de o GPT-4o-mini misturar vozes como:

```text
meu atendimento
nosso escritório
o advogado
a equipe
a área responsável
```

---

# 3. Regra comercial preservada

A regra comercial central foi preservada:

```text
o vendedor, em última análise, vende confiança
```

Em Advocacia, confiança deve nascer de:

```text
acolhimento
clareza
método
sobriedade
informação útil
organização do relato
cuidado documental
próximo passo seguro
```

A venda não deve depender de promessa de resultado.

A venda deve depender de condução responsável.

---

# 4. Regra operacional preservada

A regra operacional central foi preservada:

```text
o robô organiza o contato;
o advogado realiza a análise jurídica.
```

O robô pode:

```text
acolher
identificar área provável
organizar relato inicial
coletar informações mínimas
orientar documentos iniciais conforme configuração
agendar consulta ou reunião
encaminhar resumo ao advogado, área ou responsável
preservar continuidade
```

Quando o lead pedir conclusão jurídica, chance, estratégia, valor, parecer ou interpretação conclusiva, o robô deve organizar o contexto e conduzir para análise profissional.

---

# 5. Compatibilidade com GPT-4o-mini

A modelagem respeita a limitação do GPT-4o-mini.

Os documentos evitam depender de abstrações e proibições como freio principal.

O padrão adotado foi:

```text
detected_state
commercial_objective
safe_response_direction
allowed_actions
useful_information
next_step
handoff_trigger
```

Regra consolidada:

```text
limites profissionais devem virar trilhos positivos de condução
```

Exemplo:

```text
quando o lead pedir conclusão
→ acolher
→ organizar o relato
→ explicar que a análise depende do profissional
→ conduzir para consulta, reunião ou responsável
```

---

# 6. Arquivos criados na base comum

Base comum de Advocacia:

```text
docs\subsegments\advocacia\audits\ADVOCACIA_ARCHITECTURE_DECISION_V1.md
docs\subsegments\advocacia\source\ADVOCACIA_BASE_CANONICAL_MODEL_V1.md
docs\subsegments\advocacia\runtime\ADVOCACIA_BASE_RUNTIME_SAFETY_V1.md
docs\subsegments\advocacia\lessons_learned\ADVOCACIA_FACTORY_INCREMENTS_V1.md
```

Função da base comum:

```text
preservar ética, segurança, sigilo, venda por confiança, triagem segura e limites positivos
```

---

# 7. Arquivos criados nos subsegmentos operacionais

Advocacia Individual:

```text
docs\subsegments\advocacia_individual\runtime\RUNTIME_ADVOCACIA_INDIVIDUAL_V1.md
```

Função:

```text
modelar confiança pessoal, proximidade, agenda individual e análise direta pelo advogado
```

Escritório de Advocacia:

```text
docs\subsegments\escritorio_advocacia\runtime\RUNTIME_ESCRITORIO_ADVOCACIA_V1.md
```

Função:

```text
modelar confiança institucional, equipe, método, área responsável e continuidade interna
```

---

# 8. Arquivos centrais da fábrica incrementados

Arquivo novo criado:

```text
docs\segment_factory\reusable_assets\ADVOCACIA_REUSABLE_COMPONENTS_V1.md
```

Arquivo existente incrementado:

```text
docs\segment_factory\reusable_assets\FACTORY_REUSE_STATUS_V1.md
```

Bloco incluído:

```text
CANDIDATE_FROM_ADVOCACIA
```

Objetivo:

```text
permitir que futuras instâncias encontrem rapidamente os aprendizados reaproveitáveis de Advocacia
sem precisar ler toda a pasta do subsegmento
```

---

# 9. Componentes candidatos registrados

Advocacia gerou estes componentes candidatos:

```text
COMPONENT_POSITIVE_BOUNDARY_MODELING
COMPONENT_REGULATED_PROFESSIONAL_BOUNDARY
COMPONENT_CONFIDENTIAL_INTAKE_FLOW
COMPONENT_URGENCY_PERCEPTION_WITHOUT_DECISION
COMPONENT_TRUST_SELLING_BY_BOUNDARY
COMPONENT_EMPATHIC_TIMING
COMPONENT_REGULATED_SERVICE_CONVERSION
COMPONENT_INDIVIDUAL_VS_STRUCTURED_PROVIDER_ADAPTATION
COMPONENT_CONSULTATION_BEFORE_RECOMMENDATION
```

Status:

```text
CANDIDATE
```

Eles não devem ser aplicados automaticamente.

Eles não devem virar Firestore agora.

Eles podem ser avaliados em futuros subsegmentos sensíveis, regulados ou consultivos.

---

# 10. Microcena conversacional

A micro_scene_conversational não foi criada nesta etapa.

Decisão preservada:

```text
a micro_scene_conversational de Advocacia será construída separadamente,
com supervisão direta do usuário
```

Motivo:

A microcena precisa equilibrar ética, venda, utilidade, confiança, clareza comercial e ganho operacional comum.

---

# 11. Estado de Firestore

Nenhum JSON Firestore foi criado nesta etapa.

Nenhum dry-run foi executado.

Nenhuma aplicação no Firestore foi feita.

Nenhuma estrutura nova como `legal_runtime` foi criada.

Direção futura conservadora:

```text
commercial_runtime
operational_runtime
behavior_components
snapshot_priority
```

Campos jurídicos devem ser encaixados inicialmente dentro de estruturas já preservadas pelo pipeline, antes de qualquer campo novo.

---

# 12. Pendências antes de JSON

Antes de gerar JSON, ainda faltam:

```text
1. revisar os documentos criados
2. construir micro_scene_conversational com supervisão direta
3. criar mapeamento Firestore para Advocacia Individual
4. criar mapeamento Firestore para Escritório de Advocacia
5. validar campos contra o padrão de Otorrino
6. auditar snapshot_priority
7. criar JSONs separados
8. executar dry-run
9. aplicar Firestore somente com autorização explícita
```

---

# 13. Critério de aprovação desta etapa

A etapa documental está consistente quando:

```text
a decisão base comum + dois subsegmentos está clara
a venda por confiança está preservada
os limites viraram trilhos positivos
o GPT-4o-mini recebeu estrutura concreta
a microcena ficou fora da etapa atual
os aprendizados reutilizáveis foram centralizados
nenhum JSON foi criado antes da hora
nenhum código foi alterado
nenhum deploy foi feito
```

---

# 14. Síntese

A primeira etapa de Advocacia está pronta para revisão documental.

O subsegmento foi modelado como serviço regulado, sensível e consultivo.

A fábrica recebeu novos candidatos reutilizáveis.

A próxima etapa segura é revisar e depois preparar mapeamento Firestore, sem aplicar nada ainda.
