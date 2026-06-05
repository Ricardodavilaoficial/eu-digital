# CLINICA_EXAMES_CANONICAL_MODEL_V1

## Objetivo

Consolidar o modelo canônico do subsegmento Clínica de Exames Médicos para a Fábrica de Segmentos do MEI ROBÔ.

Este documento transforma pesquisa real e matriz de raciocínio especialista em estrutura de conhecimento profissional.

Este documento não aplica Firestore.

Este documento não altera código.

Este documento não substitui o runtime compacto.

---

# 1. Identidade do subsegmento

## Nome

Clínica de exames médicos

## ID sugerido

saude__clinica_exames_medicos

## Tipo de operação

Atendimento consultivo-operacional em saúde.

## Objetivo prático

Conduzir o paciente da intenção inicial até a realização correta do exame, com preparo, documentação, convênio, agendamento e acesso ao resultado bem orientados.

---

# 2. Tese central

O produto real da clínica de exames não é apenas o exame.

O produto real é a prontidão segura para realizar o exame.

O paciente geralmente chega com uma dúvida simples, mas o profissional experiente pensa em pré-requisitos.

Intenção do paciente
↓
exame correto
↓
pedido médico
↓
convênio ou particular
↓
autorização
↓
preparo
↓
agenda
↓
comparecimento
↓
resultado

---

# 3. Papel do profissional experiente

O profissional experiente atua como:

* vendedor consultivo empático;
* recepcionista especializada;
* organizador de documentos;
* validador de preparo;
* condutor de agendamento;
* redutor de erros operacionais;
* protetor da confiança do paciente.

Ele não responde apenas à pergunta literal.

Ele identifica o que precisa estar pronto para o próximo passo acontecer corretamente.

---

# 4. Raciocínio dominante

## OBJECTIVE_ENABLE_EXECUTION

O raciocínio dominante deste segmento é habilitar a execução.

A pergunta mental central é:

O paciente está pronto para avançar?

Essa prontidão depende de:

* exame identificado;
* pedido médico recebido;
* preparo conhecido;
* convênio ou forma particular definida;
* autorização validada quando aplicável;
* unidade e horário compatíveis;
* canal de resultado conhecido.

---

# 5. Sequência mental especialista

frase_do_cliente
↓
intenção real
↓
estado operacional
↓
informações faltantes
↓
risco principal
↓
próximo objetivo
↓
ação positiva permitida
↓
ação de confiança
↓
resposta final

---

# 6. Estados principais

## STATE_NEEDS_PRICE

Paciente quer saber valor.

Lacunas comuns:

* nome exato do exame;
* pedido médico;
* quantidade de exames;
* modalidade particular ou convênio.

Próximo objetivo:

OBJECTIVE_IDENTIFY_EXAM_FOR_QUOTE

---

## STATE_NEEDS_SCHEDULE

Paciente quer agendar.

Lacunas comuns:

* exame;
* pedido médico;
* unidade;
* horário;
* preparo;
* convênio;
* autorização.

Próximo objetivo:

OBJECTIVE_VALIDATE_READINESS_FOR_SCHEDULE

---

## STATE_NEEDS_PREPARATION

Paciente quer saber preparo.

Lacunas comuns:

* nome exato do exame;
* data pretendida;
* instrução cadastrada;
* condição relatada pelo paciente.

Próximo objetivo:

OBJECTIVE_CONFIRM_PREPARATION

---

## STATE_NEEDS_CONVENIO

Paciente quer saber sobre convênio.

Lacunas comuns:

* nome do plano;
* tipo de plano;
* pedido médico;
* exame solicitado;
* autorização.

Próximo objetivo:

OBJECTIVE_CONFIRM_COVERAGE_PATH

---

## STATE_NEEDS_RESULT

Paciente quer resultado.

Lacunas comuns:

* identificação;
* protocolo;
* data de realização;
* canal oficial;
* prazo informado.

Próximo objetivo:

OBJECTIVE_GUIDE_RESULT_ACCESS

---

## STATE_NEEDS_RESCHEDULE

Paciente quer remarcar ou cancelar.

Lacunas comuns:

* exame;
* data atual;
* nova data desejada;
* preparo;
* política da clínica.

Próximo objetivo:

OBJECTIVE_UPDATE_APPOINTMENT_PATH

---

## STATE_HAS_OPERATIONAL_PROBLEM

Paciente relata problema.

Exemplos:

* atraso;
* resultado pendente;
* preparo incorreto;
* dificuldade de acesso;
* atendimento sem retorno.

Próximo objetivo:

OBJECTIVE_RECOVER_TRUST_AND_ROUTE

---

## STATE_ANXIOUS_OR_URGENT

Paciente demonstra ansiedade, medo ou urgência.

Próximo objetivo:

OBJECTIVE_ACKNOWLEDGE_AND_MOVE_TO_NEXT_STEP

---

# 7. Lacunas estruturais

## GAP_EXAM_NAME

Nome exato do exame ausente.

## GAP_MEDICAL_ORDER

Pedido médico ausente.

## GAP_PREPARATION

Preparo ainda não confirmado.

## GAP_CONVENIO_DETAILS

Dados do convênio ausentes.

## GAP_AUTHORIZATION

Autorização ainda não validada.

## GAP_UNIT

Unidade desejada ausente.

## GAP_SCHEDULE

Horário desejado ausente.

## GAP_PATIENT_IDENTIFICATION

Dados para localizar atendimento ausentes.

## GAP_RESULT_PROTOCOL

Protocolo ou canal de resultado ausente.

---

# 8. Riscos principais

## RISK_WRONG_EXAM

Orçamento, preparo ou agendamento baseado em exame incorreto.

## RISK_PREPARATION_FAILURE

Paciente comparece sem preparo adequado.

## RISK_DOCUMENTATION_FAILURE

Paciente comparece sem pedido, documento ou guia necessária.

## RISK_COVERAGE_FAILURE

Convênio ou autorização não viabiliza o exame.

## RISK_EXPECTATION_MISMATCH

Paciente espera prazo, preço ou disponibilidade diferente.

## RISK_RESULT_ACCESS_FAILURE

Paciente não consegue acessar o resultado.

## RISK_PATIENT_LOSS

Paciente abandona o atendimento por demora, fricção ou insegurança.

---

# 9. Objetivos operacionais

## OBJECTIVE_IDENTIFY_EXAM

Identificar corretamente o exame.

## OBJECTIVE_COLLECT_MEDICAL_ORDER

Solicitar pedido médico ou foto da solicitação.

## OBJECTIVE_CONFIRM_PREPARATION

Orientar preparo cadastrado.

## OBJECTIVE_CONFIRM_COVERAGE_PATH

Coletar dados para validação de convênio.

## OBJECTIVE_VALIDATE_AUTHORIZATION

Direcionar conferência de autorização quando aplicável.

## OBJECTIVE_CONFIRM_SCHEDULE

Conduzir para data, unidade e horário.

## OBJECTIVE_GUIDE_RESULT_ACCESS

Orientar acesso ao resultado pelo canal oficial.

## OBJECTIVE_RECOVER_TRUST_AND_ROUTE

Acolher problema e encaminhar para resolução humana ou operacional.

---

# 10. Princípios de resposta

## PRINCIPLE_CONTEXT_BEFORE_EXECUTION

Quando faltar contexto mínimo, coletar contexto antes de avançar.

## PRINCIPLE_PREVENT_REWORK

Quando uma resposta direta puder gerar retrabalho, conduzir para validação.

## PRINCIPLE_NEXT_SUCCESSFUL_STEP

Quando a jornada for longa, orientar apenas o próximo passo correto.

## PRINCIPLE_OPERATIONAL_READINESS

Quando o paciente quiser realizar algo, validar se ele está apto para avançar.

## PRINCIPLE_EMPATHIC_CONVERSION

Quando houver dúvida, ansiedade ou pressa, acolher e conduzir para uma ação concreta.

---

# 11. Ações positivas permitidas

* solicitar foto do pedido médico;
* pedir nome exato do exame;
* perguntar convênio ou modalidade particular;
* perguntar unidade desejada;
* perguntar melhor dia ou horário;
* enviar preparo cadastrado;
* orientar canal oficial de resultado;
* registrar interesse;
* encaminhar para atendente humano;
* organizar resumo para a equipe;
* explicar o próximo passo com clareza.

---

# 12. Ações de confiança

* explicar por que o pedido médico ajuda a evitar erro;
* informar que preparo depende do exame;
* dizer que convênio precisa de conferência por exame e plano;
* orientar que resultado deve ser acessado pelo canal seguro da clínica;
* acolher ansiedade e transformar em próximo passo;
* confirmar dados antes de prometer agenda, preço ou prazo.

---

# 13. Situações reais centrais

* quanto custa esse exame;
* vocês fazem esse exame;
* posso mandar o pedido por aqui;
* o médico pediu vários exames;
* aceita meu convênio;
* precisa autorização;
* precisa jejum;
* posso beber água;
* tomei café, posso fazer;
* tem horário amanhã;
* posso fazer hoje;
* qual unidade atende;
* já saiu meu resultado;
* perdi minha senha;
* meu resultado não apareceu;
* vocês coletam em casa;
* atende idoso;
* estou preocupado;
* preciso fazer urgente;
* estou aguardando esse resultado.

---

# 14. Slots de personalização do assinante

Devem ficar fora da expertise-base e ser preenchidos pelo assinante:

* exames oferecidos;
* unidades;
* horários;
* preços;
* convênios aceitos;
* preparos por exame;
* coleta domiciliar;
* bairros atendidos;
* prazo de resultados;
* canal de resultado;
* políticas de autorização;
* política de cancelamento;
* contatos humanos;
* campanhas e promoções.

---

# 15. Componentes reutilizados da Ótica

* COMPONENT_NEED_DISCOVERY
* COMPONENT_CONTEXT_BEFORE_RECOMMENDATION
* COMPONENT_INFORMATION_GAP_DETECTION
* COMPONENT_EXPERT_REFRAMING
* COMPONENT_RISK_REDUCTION
* COMPONENT_EXPECTATION_ALIGNMENT
* COMPONENT_TRUST_BUILDING_BY_METHOD
* COMPONENT_FAILURE_CAUSE_ANALYSIS
* COMPONENT_SUBSCRIBER_CUSTOMIZATION_SLOTS

---

# ADDENDUM_V2_ACCESS_PATH_AND_EXAM_READINESS

## Objetivo

Registrar a descoberta complementar de que a Clínica de Exames Médicos precisa identificar a forma de acesso ao exame antes de conduzir para agendamento, autorização, comparecimento ou resultado.

Esta seção preserva o Modelo Canônico V1 e adiciona a camada operacional descoberta na pesquisa complementar.

---

# Novos estados canônicos

## STATE_ACCESS_PATH_UNDEFINED

Paciente deseja realizar exame, mas ainda não está definida a forma de acesso.

Possibilidades:

- particular;
- convênio sem autorização;
- convênio com autorização;
- pré-agendamento com validação posterior;
- SUS/regulação;
- ordem de chegada;
- atendimento exclusivamente presencial.

Próximo objetivo:

OBJECTIVE_DEFINE_ACCESS_PATH

---

## STATE_PATH_PRIVATE

Paciente pretende realizar exame particular.

Próximo objetivo:

OBJECTIVE_CONFIRM_PRIVATE_FLOW

---

## STATE_PATH_CONVENIO

Paciente pretende usar convênio.

Próximo objetivo:

OBJECTIVE_CONFIRM_COVERAGE_AND_AUTHORIZATION_PATH

---

## STATE_PATH_SUS

Paciente menciona SUS, regulação, posto de saúde, secretaria de saúde ou central de marcação.

Próximo objetivo:

OBJECTIVE_ROUTE_SUS_REGULATION

---

## STATE_PATH_WALK_IN

Exame ou unidade opera por ordem de chegada ou atendimento presencial.

Próximo objetivo:

OBJECTIVE_CONFIRM_WALK_IN_REQUIREMENTS

---

## STATE_NEEDS_DOCUMENT_VALIDATION

Paciente ainda precisa enviar ou apresentar documentos necessários para seguir.

Próximo objetivo:

OBJECTIVE_VALIDATE_DOCUMENT_SET

---

## STATE_AUTHORIZATION_PENDING

Autorização foi solicitada ou precisa de retorno da operadora.

Próximo objetivo:

OBJECTIVE_TRACK_AUTHORIZATION_STATUS

---

## STATE_PREPARATION_UNCONFIRMED

Paciente ainda não confirmou preparo necessário.

Próximo objetivo:

OBJECTIVE_CONFIRM_EXAM_PREPARATION

---

## STATE_READY_FOR_EXAM

Paciente possui trilha definida, documentação suficiente, preparo confirmado e próximo passo claro.

Próximo objetivo:

OBJECTIVE_CONFIRM_EXECUTION_STEP

---

# Novas lacunas canônicas

## GAP_ACCESS_PATH

Forma de acesso ao exame ainda não definida.

## GAP_AUTHORIZATION_DOCUMENTS

Documentos necessários para autorização ainda ausentes ou incompletos.

## GAP_COVERAGE_INFORMATION

Informações do plano, cobertura ou operadora ainda insuficientes.

## GAP_WALK_IN_RULES

Regras de ordem de chegada ou comparecimento presencial ainda não confirmadas.

## GAP_SUS_ROUTING

Fluxo de regulação, posto, secretaria ou central de marcação ainda não definido.

---

# Novos riscos canônicos

## RISK_WRONG_ACCESS_PATH

Conduzir o paciente para trilha operacional incorreta.

## RISK_AUTHORIZATION_DELAY

Atraso por documentação incompleta, análise pendente ou complementação solicitada.

## RISK_INVALID_DOCUMENTATION

Paciente apresentar documento incorreto, vencido, divergente ou insuficiente.

## RISK_NO_SHOW

Paciente faltar por esquecimento, conflito de agenda, preparo incorreto ou falta de confirmação.

## RISK_EXAM_NOT_READY

Paciente chegar ao exame sem preparo, autorização, documentação ou condição operacional adequada.

---

# Novos objetivos canônicos

## OBJECTIVE_DEFINE_ACCESS_PATH

Identificar se o exame seguirá por particular, convênio, SUS, ordem de chegada ou outro fluxo da clínica.

## OBJECTIVE_CONFIRM_COVERAGE_AND_AUTHORIZATION_PATH

Confirmar se o convênio cobre, se exige autorização e quais documentos são necessários.

## OBJECTIVE_ROUTE_SUS_REGULATION

Orientar a rota adequada quando o atendimento depender de SUS, regulação ou central de marcação.

## OBJECTIVE_CONFIRM_WALK_IN_REQUIREMENTS

Orientar documentos, preparo, horários e condições para atendimento por ordem de chegada.

## OBJECTIVE_VALIDATE_DOCUMENT_SET

Conferir se o conjunto documental está suficiente para seguir.

## OBJECTIVE_TRACK_AUTHORIZATION_STATUS

Acompanhar o status da autorização até aprovação, pendência, negativa ou complementação.

## OBJECTIVE_CONFIRM_EXAM_PREPARATION

Confirmar preparo necessário antes do comparecimento.

## OBJECTIVE_CONFIRM_EXECUTION_STEP

Confirmar o próximo passo operacional para realizar o exame.

---

# Novos componentes candidatos

## COMPONENT_ACCESS_PATH_ROUTING

Função:

Identificar a trilha operacional correta antes de conduzir o paciente para agendamento, autorização, comparecimento ou regulação.

Status:

CANDIDATE

---

## COMPONENT_AUTHORIZATION_WORKFLOW

Função:

Orquestrar coleta documental, envio, acompanhamento e retorno de autorização quando houver exigência de operadora ou fluxo regulado.

Status:

CANDIDATE

---

## COMPONENT_EXAM_READINESS_VALIDATION

Função:

Validar se o paciente está apto para realizar o exame com documentação, autorização, preparo e comparecimento adequados.

Status:

CANDIDATE

---

# 16. Componente novo candidato

## COMPONENT_READINESS_VALIDATION

Status:

CANDIDATE

Origem:

Clínica de exames médicos.

Função:

Validar se o paciente possui os pré-requisitos necessários para avançar para a próxima etapa.

Sequência:

objetivo desejado
↓
pré-requisitos
↓
validação
↓
execução

Exemplos:

Agendamento:

pedido médico
↓
convênio
↓
autorização
↓
preparo
↓
agenda

Resultado:

identificação
↓
protocolo
↓
canal oficial
↓
acesso

Este componente ainda não deve ir para Firestore.

---

# 17. Conclusão canônica

Clínica de exames médicos não deve ser modelada como lista de exames.

Deve ser modelada como jornada de prontidão operacional.

O MEI Robô precisa pensar como um profissional experiente que acolhe, organiza, valida pré-requisitos e conduz o paciente ao próximo passo seguro.

O sucesso do atendimento ocorre quando o paciente entende o que precisa fazer agora para realizar o exame corretamente.
