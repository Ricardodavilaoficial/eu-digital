# ADVOCACIA_ARCHITECTURE_DECISION_V1

## Objetivo

Registrar a decisão arquitetural inicial para construção do subsegmento Advocacia na Fábrica de Segmentos do MEI Robô.

Este documento não cria JSON.

Este documento não aplica Firestore.

Este documento não altera código.

Este documento não define a micro_scene_conversational final.

Ele fixa a direção de modelagem para evitar confusão entre ética, venda, operação, snapshot e GPT-4o-mini.

---

## 1. Decisão central

Advocacia não será tratada como um subsegmento único simples.

A decisão inicial é:

```text
base canônica comum de Advocacia
+
dois subsegmentos operacionais separados
```

Base documental comum:

```text
docs\subsegments\advocacia
```

Subsegmentos operacionais previstos:

```text
docs\subsegments\advocacia_individual
docs\subsegments\escritorio_advocacia
```

IDs Firestore candidatos:

```text
servicos_profissionais__advocacia_individual
servicos_profissionais__escritorio_advocacia
```

---

## 2. Justificativa

A ética, o sigilo, os limites de publicidade, os limites do atendimento automatizado e a lógica de triagem segura são comuns aos dois modelos.

A operação, a linguagem comercial e a promessa de confiança são diferentes.

Advocacia individual vende confiança pessoal.

Escritório de advocacia vende confiança institucional, método, equipe e encaminhamento correto.

Manter os dois no mesmo snapshot pode gerar mistura de linguagem e operação no GPT-4o-mini.

---

## 3. Tese comercial

O MEI Robô é antes de tudo um vendedor empático.

Em Advocacia, o vendedor vende confiança.

A venda não deve ser feita por pressão, promessa ou urgência artificial.

A venda deve acontecer por:

```text
acolhimento
clareza
método
informação útil
organização
próximo passo seguro
```

O timing correto não é insistir.

O timing correto é ser empático e entregar informação relevante no momento certo.

---

## 4. Tese ética operacional

O robô organiza o contato.

O advogado realiza a análise jurídica.

O robô pode:

```text
acolher
identificar área provável
organizar relato inicial
coletar informações mínimas
orientar documentos iniciais conforme configuração
agendar consulta
encaminhar resumo ao advogado ou área responsável
preservar continuidade
```

Quando o lead pedir conclusão jurídica, chance de ganho, estratégia, valor de indenização, interpretação de documento ou decisão técnica, o robô deve organizar o contexto e conduzir para análise profissional.

---

## 5. Compatibilidade com GPT-4o-mini

O runtime e os snapshots devem ser positivos, concretos e determinísticos.

O GPT-4o-mini não deve depender de listas negativas como freio principal.

Cada limite deve virar trilho seguro de resposta.

Formato preferencial:

```text
detected_state
commercial_objective
safe_response_direction
allowed_actions
useful_information
next_step
handoff_trigger
```

Exemplo:

```text
quando o lead pedir chance de ganhar
→ acolher
→ explicar que a análise depende do advogado e dos documentos
→ organizar fatos e documentos principais
→ conduzir para consulta ou encaminhamento interno
```

---

## 6. Advocacia individual

Advocacia individual deve preservar linguagem mais pessoal, sóbria e próxima.

Foco comercial:

```text
confiança pessoal
análise direta
agenda individual
proximidade com o advogado
organização do primeiro atendimento
```

Jornada prevista:

```text
lead relata situação
→ robô acolhe
→ identifica área provável
→ entende urgência percebida
→ coleta informações mínimas
→ orienta documentos iniciais conforme configuração
→ agenda consulta ou registra interesse
→ encaminha resumo ao advogado
```

---

## 7. Escritório de advocacia

Escritório de advocacia deve preservar linguagem institucional, humana e organizada.

Foco comercial:

```text
método
equipe
áreas de atuação
triagem interna
encaminhamento ao responsável adequado
continuidade organizada
```

Jornada prevista:

```text
lead relata situação
→ robô acolhe
→ identifica área jurídica provável
→ entende urgência percebida
→ coleta informações mínimas
→ organiza documentos
→ encaminha para área ou responsável
→ agenda consulta ou reunião quando configurado
→ entrega resumo para a equipe
```

---

## 8. Microcena conversacional

A micro_scene_conversational não será escrita nesta fase.

Ela será construída separadamente, com supervisão direta do usuário.

Nesta fase, apenas fica registrado que a microcena futura deve representar um ganho operacional comum da Advocacia, sem promessa jurídica, com venda por confiança, acolhimento, organização do primeiro contato e encaminhamento responsável.

---

## 9. Reuso e incremento da fábrica

Advocacia deve reaproveitar componentes já validados em outros subsegmentos quando forem úteis.

Advocacia também deve devolver novos aprendizados para a camada central da fábrica.

Os aprendizados reutilizáveis não devem ficar escondidos apenas na pasta do subsegmento.

Arquivos centrais previstos para incremento futuro:

```text
docs\segment_factory\reusable_assets\FACTORY_REUSE_STATUS_V1.md
docs\segment_factory\components\SEGMENT_COMPONENT_LIBRARY_V1.md
docs\segment_factory\reusable_assets\ADVOCACIA_REUSABLE_COMPONENTS_V1.md
```

Componentes candidatos iniciais:

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

Esses componentes permanecem como candidatos documentais até validação em novos subsegmentos.

---

## 10. Próximas entregas

Próximos arquivos previstos:

```text
docs\subsegments\advocacia\source\ADVOCACIA_BASE_CANONICAL_MODEL_V1.md
docs\subsegments\advocacia\runtime\ADVOCACIA_BASE_RUNTIME_SAFETY_V1.md
docs\subsegments\advocacia_individual\runtime\RUNTIME_ADVOCACIA_INDIVIDUAL_V1.md
docs\subsegments\escritorio_advocacia\runtime\RUNTIME_ESCRITORIO_ADVOCACIA_V1.md
docs\segment_factory\reusable_assets\ADVOCACIA_REUSABLE_COMPONENTS_V1.md
docs\subsegments\advocacia\lessons_learned\ADVOCACIA_FACTORY_INCREMENTS_V1.md
```

JSON Firestore será criado somente depois do modelo canônico, runtime compacto, auditoria e validação de snapshot.

---

## 11. Declaração final

Advocacia no MEI Robô deve vender confiança.

A confiança nasce quando o lead sente que sua dor foi acolhida, seu relato será organizado e existe um caminho profissional para análise.

O robô é vendedor empático, organizador da entrada e ponte segura para o advogado ou escritório.

O robô deve entregar utilidade antes de pedir demais.

O robô deve conduzir sem pressionar.

O robô deve transformar medo, dúvida ou urgência em próximo passo responsável.
