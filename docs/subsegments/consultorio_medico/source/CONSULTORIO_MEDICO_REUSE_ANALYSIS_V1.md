# CONSULTORIO_MEDICO_REUSE_ANALYSIS_V1

## Objetivo

Analisar quais componentes, mecanismos e descobertas já existentes na Fábrica podem ser reutilizados na construção do subsegmento Consultório Médico.

Este documento não cria o modelo canônico.

Este documento não cria runtime.

Este documento não cria Firestore.

Este documento existe para impedir redescoberta, reduzir retrabalho e orientar a pesquisa específica do Consultório Médico.

---

# 1. Contexto

A Fábrica já possui patrimônio reutilizável observado principalmente em:

* Ótica;
* Clínica de Exames Médicos;
* documentos de governança;
* biblioteca de componentes;
* status de reutilização da Fábrica.

O Consultório Médico deve nascer a partir desse patrimônio.

A pesquisa do segmento deve validar, adaptar ou rejeitar mecanismos existentes antes de propor componentes novos.

---

# 2. Regra de uso

Antes de modelar Consultório Médico, considerar:

1. componentes já reutilizados;
2. candidatos vindos da Clínica de Exames;
3. descobertas canônicas da Fábrica;
4. compatibilidade com snapshot para GPT-4o-mini;
5. compatibilidade com linguagem operacional e conversacional.

O objetivo não é criar FAQ.

O objetivo é construir um especialista digital capaz de conduzir a jornada do paciente.

---

# 3. Componentes REUSED aplicáveis

## COMPONENT_NEED_DISCOVERY

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

Paciente frequentemente chega com necessidade vaga:

* quero marcar uma consulta;
* não sei qual médico procurar;
* preciso de retorno;
* fui encaminhado;
* estou preocupado;
* quero saber se atende meu convênio.

Função no Consultório Médico:

Entender a necessidade real antes de conduzir para agendamento, retorno, teleconsulta, encaminhamento ou atendimento humano.

Decisão:

REUTILIZAR.

---

## COMPONENT_CONTEXT_BEFORE_RECOMMENDATION

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

A orientação depende de contexto mínimo:

* primeira consulta ou retorno;
* presencial ou teleconsulta;
* particular ou convênio;
* encaminhamento existente;
* urgência percebida;
* documentos necessários;
* disponibilidade real da agenda.

Função no Consultório Médico:

Evitar orientação prematura quando faltam critérios para o próximo passo.

Decisão:

REUTILIZAR.

---

## COMPONENT_INFORMATION_GAP_DETECTION

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

Lacunas recorrentes:

* motivo da consulta não informado;
* forma de acesso indefinida;
* convênio não informado;
* retorno ou primeira consulta não identificado;
* encaminhamento ausente;
* documentos não confirmados;
* canal de consulta não definido;
* paciente não sabe o próximo passo.

Função no Consultório Médico:

Detectar informações faltantes antes de conduzir a jornada.

Decisão:

REUTILIZAR.

---

## COMPONENT_EXPERT_REFRAMING

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

Perguntas genéricas devem ser transformadas em condução operacional.

Exemplos:

"Quero uma consulta"
↓
"É primeira consulta, retorno ou encaminhamento?"

"Atende meu convênio?"
↓
"Vamos conferir o convênio e o tipo de consulta para orientar o caminho certo."

Função no Consultório Médico:

Transformar pergunta ampla em caminho de decisão.

Decisão:

REUTILIZAR.

---

## COMPONENT_RISK_REDUCTION

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

Riscos recorrentes:

* no-show;
* atraso;
* falta de documentos;
* convênio não validado;
* retorno perdido;
* paciente inseguro;
* consulta marcada no fluxo errado;
* teleconsulta sem link ou orientação;
* abandono de acompanhamento.

Função no Consultório Médico:

Reduzir risco de perda de consulta, retrabalho, frustração ou abandono.

Decisão:

REUTILIZAR.

---

## COMPONENT_EXPECTATION_ALIGNMENT

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

Paciente precisa entender:

* o que levar;
* qual horário;
* qual canal;
* se é primeira consulta ou retorno;
* se depende de convênio;
* se precisa encaminhamento;
* o que acontece depois da consulta;
* quando deve retornar.

Função no Consultório Médico:

Alinhar expectativa antes, durante e depois da consulta.

Decisão:

REUTILIZAR.

---

## COMPONENT_TRUST_BUILDING_BY_METHOD

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

A confiança aumenta quando o paciente percebe método:

* entender motivo;
* confirmar forma de acesso;
* organizar documentos;
* validar consulta;
* orientar próximo passo;
* preservar retorno.

Função no Consultório Médico:

Mostrar condução profissional sem linguagem técnica excessiva.

Decisão:

REUTILIZAR.

---

## COMPONENT_FAILURE_CAUSE_ANALYSIS

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

Quando há falta, atraso, reclamação, abandono ou não retorno, o especialista deve investigar causa provável:

* esquecimento;
* dificuldade de acesso;
* medo;
* falta de entendimento;
* problema de convênio;
* atraso;
* falta de retorno;
* comunicação ruim.

Função no Consultório Médico:

Entender a causa da ruptura antes de reorganizar a jornada.

Decisão:

REUTILIZAR.

---

## COMPONENT_SUBSCRIBER_CUSTOMIZATION_SLOTS

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

Devem ficar como personalização do assinante:

* médicos disponíveis;
* especialidades atendidas;
* horários;
* convênios;
* valores;
* política de retorno;
* teleconsulta;
* endereço;
* documentos exigidos;
* formas de pagamento;
* canais humanos;
* regras internas.

Função no Consultório Médico:

Separar expertise-base do segmento das informações próprias do consultório.

Decisão:

REUTILIZAR.

---

## COMPONENT_CONSULTANT_DECISION_SEQUENCE

Status na Fábrica:

REUSED

Aplicação em Consultório Médico:

Sequência mental esperada:

frase do paciente
↓
necessidade real
↓
forma de acesso
↓
lacunas
↓
risco principal
↓
próximo objetivo
↓
ação permitida
↓
ação de confiança
↓
resposta final

Função no Consultório Médico:

Dar estrutura determinística ao GPT-4o-mini.

Decisão:

REUTILIZAR.

---

# 4. Candidatos da Clínica de Exames reforçados pela pesquisa

## COMPONENT_ACCESS_PATH_ROUTING

Origem:

Clínica de Exames Médicos.

Status anterior:

CANDIDATE.

Evidência em Consultório Médico:

O paciente pode entrar por diferentes caminhos:

* particular;
* convênio;
* retorno;
* primeira consulta;
* encaminhamento;
* teleconsulta;
* SUS ou regulação;
* atendimento humano.

Função observada:

Identificar a porta de entrada antes de conduzir o paciente.

Decisão provisória:

FORTE EVIDÊNCIA INTERSEGMENTO.

Não promover ainda sem auditoria final.

---

## COMPONENT_READINESS_VALIDATION

Origem:

Clínica de Exames Médicos.

Status anterior:

CANDIDATE.

Evidência em Consultório Médico:

Antes da consulta, podem ser necessários:

* documento;
* carteirinha;
* guia;
* autorização;
* encaminhamento;
* cadastro;
* link de teleconsulta;
* confirmação de horário;
* orientação prévia.

Função observada:

Validar se o paciente está pronto para realizar a consulta.

Decisão provisória:

FORTE EVIDÊNCIA INTERSEGMENTO.

Pode futuramente generalizar para SERVICE_READINESS_VALIDATION.

Não promover ainda sem auditoria final.

---

## COMPONENT_AUTHORIZATION_WORKFLOW

Origem:

Clínica de Exames Médicos.

Status anterior:

CANDIDATE.

Evidência em Consultório Médico:

Reaparece em situações envolvendo:

* convênio;
* guia;
* elegibilidade;
* autorização;
* senha;
* encaminhamento;
* validação prévia.

Função observada:

Organizar fluxo quando a consulta depende de validação externa.

Decisão provisória:

EVIDÊNCIA INTERSEGMENTO MODERADA A FORTE.

Exige auditoria cuidadosa para separar o que é saúde suplementar, regra do assinante e mecanismo reutilizável.

---

## COMPONENT_EXAM_READINESS_VALIDATION

Origem:

Clínica de Exames Médicos.

Status anterior:

CANDIDATE.

Aplicação em Consultório Médico:

Não reutilizar literalmente.

Motivo:

O termo "exam" é específico da Clínica de Exames.

Possível generalização:

SERVICE_READINESS_VALIDATION

ou

APPOINTMENT_READINESS_VALIDATION

Decisão provisória:

NÃO REUTILIZAR COMO NOME FINAL.

Usar apenas como evidência de generalização futura.

---

# 5. Resultado observado: continuidade

## OUTCOME_CONTINUITY_OF_CARE

A pesquisa mostrou alta recorrência de:

* no-show;
* abandono;
* perda de retorno;
* falta de acompanhamento;
* paciente que não entende o próximo passo;
* paciente que não volta;
* paciente que não completa encaminhamento.

Análise:

Continuidade parece ser resultado desejado, não componente isolado.

A continuidade ocorre quando funcionam:

* descoberta de necessidade;
* roteamento de acesso;
* validação de prontidão;
* alinhamento de expectativa;
* redução de risco;
* análise de causa de falha;
* construção de confiança;
* próximo passo explícito.

Decisão:

NÃO criar componente novo neste momento.

Registrar como OUTCOME observado.

---

# 6. Núcleo operacional provisório

Paciente procura ajuda
↓
descobrir necessidade real
↓
identificar forma de acesso
↓
validar requisitos
↓
agendar ou orientar caminho correto
↓
confirmar comparecimento
↓
realizar consulta
↓
definir próximo passo
↓
preservar retorno, encaminhamento ou acompanhamento

---

# 7. Componentes que devem entrar no Consultório Médico Core

Reutilizar diretamente:

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

Reutilizar como candidatos reforçados:

* COMPONENT_ACCESS_PATH_ROUTING
* COMPONENT_READINESS_VALIDATION
* COMPONENT_AUTHORIZATION_WORKFLOW

Não reutilizar literalmente:

* COMPONENT_EXAM_READINESS_VALIDATION

Tratar como outcome:

* OUTCOME_CONTINUITY_OF_CARE

---

# 8. O que não deve ser feito

Não transformar Consultório Médico em catálogo de especialidades.

Não pesquisar doenças nesta fase.

Não pesquisar tratamentos nesta fase.

Não criar FAQ.

Não criar componente novo apenas porque a palavra aparece com frequência.

Não promover componente sem auditoria.

Não colocar biblioteca de componentes diretamente no Firestore.

---

# 9. Decisão final desta análise

O Consultório Médico deve ser construído como núcleo operacional universal.

A especialidade médica entra depois como extensão.

A pesquisa confirma que grande parte da inteligência estrutural já existe na Fábrica e pode ser reutilizada.

O foco da próxima etapa deve ser transformar este núcleo em:

* modelo canônico;
* estados;
* lacunas;
* riscos;
* objetivos;
* ações permitidas;
* ações de confiança;
* artefatos conversacionais compatíveis com snapshot e GPT-4o-mini.

---

# 10. Próximo artefato recomendado

Criar:

docs\subsegments\consultorio_medico\source\CONSULTORIO_MEDICO_CANONICAL_MODEL_V1.md

Objetivo:

Transformar a pesquisa e a análise de reutilização em estrutura canônica operacional.
