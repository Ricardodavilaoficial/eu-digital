# CLINICA_EXAMES_COMPONENT_AUDIT_V1

## Objetivo

Auditar os componentes observados durante a construção do subsegmento Clínica de Exames Médicos.

Esta auditoria busca identificar:

* componentes reutilizados da fábrica;
* componentes específicos do segmento;
* candidatos a novos componentes;
* redundâncias;
* oportunidades de consolidação.

---

# Componentes reutilizados da Ótica

## COMPONENT_NEED_DISCOVERY

Status:

REUTILIZADO

Evidência:

Paciente frequentemente inicia com intenção vaga:

* quero fazer um exame;
* quanto custa;
* preciso marcar;
* meu médico pediu exames.

Função:

Descobrir a necessidade real antes da orientação.

---

## COMPONENT_CONTEXT_BEFORE_RECOMMENDATION

Status:

REUTILIZADO

Evidência:

A orientação depende de:

* exame;
* pedido médico;
* convênio;
* preparo;
* unidade.

Função:

Coletar contexto antes de recomendar ação.

---

## COMPONENT_INFORMATION_GAP_DETECTION

Status:

REUTILIZADO

Evidência:

O runtime trabalha continuamente com:

* GAP_EXAM_NAME
* GAP_MEDICAL_ORDER
* GAP_CONVENIO_DETAILS
* GAP_SCHEDULE

Função:

Detectar informação faltante.

---

## COMPONENT_EXPERT_REFRAMING

Status:

REUTILIZADO

Evidência:

Perguntas genéricas são convertidas em coleta objetiva.

Exemplo:

```text
quanto custa?
↓
qual exame foi solicitado?
```

---

## COMPONENT_RISK_REDUCTION

Status:

REUTILIZADO

Evidência:

Riscos modelados:

* exame errado;
* preparo errado;
* cobertura incorreta;
* agendamento incorreto.

---

## COMPONENT_EXPECTATION_ALIGNMENT

Status:

REUTILIZADO

Evidência:

O paciente é conduzido para o próximo passo viável.

Evita promessas antecipadas.

---

## COMPONENT_TRUST_BUILDING_BY_METHOD

Status:

REUTILIZADO

Evidência:

Explicação do motivo da coleta de dados.

Exemplo:

```text
envie o pedido médico para eu conferir corretamente
```

---

## COMPONENT_FAILURE_CAUSE_ANALYSIS

Status:

REUTILIZADO

Evidência:

O runtime identifica:

* atraso;
* erro de preparo;
* falha de autorização;
* dificuldade de acesso ao resultado.

---

## COMPONENT_SUBSCRIBER_CUSTOMIZATION_SLOTS

Status:

REUTILIZADO

Evidência:

Campos parametrizáveis:

* convênios;
* unidades;
* preços;
* preparos;
* coleta domiciliar;
* resultados.

---

## COMPONENT_CONSULTANT_DECISION_SEQUENCE

Status:

REUTILIZADO

Evidência:

Sequências:

* preço;
* agendamento;
* preparo;
* convênio;
* resultado.

---

# Novo componente observado

## COMPONENT_READINESS_VALIDATION

Status:

CANDIDATO

Definição:

Validar se todos os pré-requisitos necessários para uma ação estão presentes antes da execução.

Estrutura observada:

```text
ação desejada
↓
pré-requisitos
↓
validação
↓
execução
```

Exemplo:

```text
agendar exame
↓
pedido médico
↓
convênio
↓
autorização
↓
preparo
↓
agenda
```

---

# Evidência observada

Encontrado em:

* orçamento;
* agendamento;
* comparecimento;
* coleta domiciliar;
* acesso a resultado.

---

# Avaliação

Recorrência dentro do segmento:

ALTA

Recorrência entre segmentos:

AINDA NÃO COMPROVADA

Decisão:

MANTER COMO CANDIDATE

---

# Componentes específicos do segmento

## PREPARATION_GUIDANCE

Classificação:

ESPECÍFICO

Motivo:

Dependente de exame.

Não reutilizável como componente universal.

---

## CONVENIO_COVERAGE_CHECK

Classificação:

ESPECÍFICO

Motivo:

Dependente de saúde suplementar.

Não promover.

---

## RESULT_ACCESS_GUIDANCE

Classificação:

ESPECÍFICO

Motivo:

Dependente do fluxo de resultados.

Não promover.

---

# Componentes rejeitados

Nenhum identificado nesta versão.

---

# Componentes promovidos

Nenhum novo componente promovido nesta versão.

---

# Biblioteca consolidada após auditoria

## Reutilizados

* COMPONENT_NEED_DISCOVERY
* COMPONENT_CONTEXT_BEFORE_RECOMMENDATION
* COMPONENT_INFORMATION_GAP_DETECTION
* COMPONENT_EXPERT_REFRAMING
* COMPONENT_RISK_REDUCTION
* COMPONENT_EXPECTATION_ALIGNMENT
* COMPONENT_TRUST_BUILDING_BY_METHOD
* COMPONENT_FAILURE_CAUSE_ANALYSIS
* COMPONENT_SUBSCRIBER_CUSTOMIZATION_SLOTS
* COMPONENT_CONSULTANT_DECISION_SEQUENCE

## Candidatos

* COMPONENT_READINESS_VALIDATION

---

# Conclusão

Resultado:


# ADDENDUM_V2_COMPONENTS_ACCESS_PATH

## Motivo

Após a auditoria V1, foi realizada pesquisa complementar sobre convênios, autorização, SUS, ordem de chegada, preparo, confirmação de comparecimento e no-show.

Essa pesquisa revelou três mecanismos adicionais relevantes para a Clínica de Exames Médicos.

---

# Novos componentes candidatos

## COMPONENT_ACCESS_PATH_ROUTING

Status:

CANDIDATE

Função:

Identificar a trilha operacional correta antes de conduzir o paciente para agendamento, autorização, comparecimento, SUS/regulação ou ordem de chegada.

Evidências:

- atendimento particular;
- convênio sem autorização;
- convênio com autorização;
- pré-agendamento;
- SUS/regulação;
- ordem de chegada;
- atendimento presencial.

Classificação:

REUTILIZÁVEL EM POTENCIAL

Motivo:

Pode aparecer em odontologia, fisioterapia, medicina ocupacional, estética, veterinária e outros serviços com múltiplas formas de acesso.

---

## COMPONENT_AUTHORIZATION_WORKFLOW

Status:

CANDIDATE

Função:

Orquestrar coleta documental, envio, acompanhamento e retorno de autorização quando houver exigência de operadora, convênio ou terceiro validador.

Evidências:

- pedido médico;
- carteirinha;
- documento;
- laudos complementares;
- autorização pendente;
- aprovação;
- negativa;
- complementação.

Classificação:

REUTILIZÁVEL EM POTENCIAL

Motivo:

Pode aparecer em exames, odontologia, fisioterapia, cirurgias, procedimentos, seguradoras e serviços com aprovação externa.

---

## COMPONENT_EXAM_READINESS_VALIDATION

Status:

CANDIDATE

Função:

Validar se o paciente está apto para realizar o exame considerando forma de acesso, documentação, autorização, preparo e comparecimento.

Evidências:

- preparo altera validade do exame;
- documentação incompleta gera atraso;
- autorização pendente bloqueia execução;
- confirmação reduz no-show;
- ordem de chegada exige requisitos mínimos.

Classificação:

REUTILIZÁVEL COM CUSTOMIZAÇÃO

Motivo:

Pode se generalizar no futuro como SERVICE_READINESS_VALIDATION, mas nesta versão permanece específico de exames.

---

# Relação com COMPONENT_READINESS_VALIDATION

O componente V1:

COMPONENT_READINESS_VALIDATION

foi refinado em três mecanismos mais precisos:

- COMPONENT_ACCESS_PATH_ROUTING
- COMPONENT_AUTHORIZATION_WORKFLOW
- COMPONENT_EXAM_READINESS_VALIDATION

Decisão:

Manter COMPONENT_READINESS_VALIDATION como conceito guarda-chuva documental.

Usar os três novos candidatos para modelagem operacional da Clínica.

---

# Decisão da auditoria V2

Resultado:

COMPONENT_AUDIT_APPROVED_V2_WITH_ACCESS_PATH

Conclusão:

A Clínica de Exames Médicos não apenas reutiliza componentes da Ótica.

Ela adiciona novos candidatos operacionais ligados à forma de acesso, autorização e prontidão do exame.

Nenhum novo componente deve ir para Firestore como coleção separada nesta etapa.

---

COMPONENT_AUDIT_APPROVED_V1

Conclusão principal:

A Clínica de Exames Médicos reutiliza a maior parte da inteligência estrutural construída anteriormente na Ótica.

O único candidato relevante identificado nesta fase é:

```text
COMPONENT_READINESS_VALIDATION
```

A promoção deve ocorrer apenas após recorrência confirmada em novos subsegmentos.

O resultado confirma que a fábrica está acumulando patrimônio reutilizável e reduzindo dependência de pesquisa integral para cada novo segmento.
