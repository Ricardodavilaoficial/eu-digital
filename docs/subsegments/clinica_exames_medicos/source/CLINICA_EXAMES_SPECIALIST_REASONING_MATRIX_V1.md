# CLINICA_EXAMES_SPECIALIST_REASONING_MATRIX_V1

## Objetivo
Registrar a primeira Matriz de Raciocínio Especialista para o subsegmento Clínica de Exames Médicos, preservando como um profissional experiente pensa antes de responder.

Este documento é fonte para Modelo Canônico, Runtime Compacto, Auditoria e futura geração de JSON Firestore. Não aplica Firestore, não altera código e não cria coleções.

## Base metodológica
- A unidade de conhecimento é o raciocínio profissional, não a resposta final.
- O foco deste segmento é prontidão operacional: pedido, preparo, convênio, autorização, agenda, comparecimento e resultado.
- A linguagem deve ser positiva e determinística para consumo posterior por GPT-4o-mini.

## Fontes de recorrência usadas na pesquisa
- Agendamento real: pedido médico, convênio, cobertura, local, dia e horário.
- Preparos reais: jejum, restrições, documentos e variação por exame.
- Resultado real: portal, protocolo, senha, prazo e segurança.
- Reclamações reais: atraso, WhatsApp, comunicação, agendamento e resultado.

## Princípios cognitivos observados
### PRINCIPLE_CONTEXT_BEFORE_EXECUTION
Antes de executar uma ação, confirmar o contexto mínimo necessário.

### PRINCIPLE_PREVENT_REWORK
Priorizar checagens que evitam deslocamento perdido, recoleta, orçamento errado, autorização ausente ou frustração posterior.

### PRINCIPLE_NEXT_SUCCESSFUL_STEP
Conduzir a conversa para o próximo passo correto, em vez de tentar resolver a jornada inteira de uma vez.

### PRINCIPLE_OPERATIONAL_READINESS
Confirmar se o paciente está apto para avançar para orçamento, agendamento, comparecimento, coleta, exame ou acesso ao resultado.

## Componente novo candidato
### COMPONENT_READINESS_VALIDATION
Status: CANDIDATE

Função: validar pré-requisitos antes de permitir avanço operacional.

Sequência: objetivo desejado → pré-requisitos → validação → execução segura.

## Matriz
### SIT_001 — ORCAMENTO_E_EXAME
**Situação real:** Quanto custa esse exame?
**Como o cliente pensa:** Quer saber se consegue realizar pelo valor.
**Como o iniciante responde:** Responde um preço isolado.
**Como o especialista pensa:** Identifica o exame antes de orçar, porque nomes parecidos podem ter valores e preparos diferentes.
**Estado detectado:** `STATE_NEEDS_PRICE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`
**Risco principal:** `RISK_WRONG_PRICE`
**Próximo objetivo:** `OBJECTIVE_IDENTIFY_EXAM`
**Ação permitida positiva:** Solicitar nome exato do exame ou foto do pedido médico.
**Ação de confiança:** Explicar que o orçamento correto depende do exame solicitado.
**Resultado esperado:** Exame identificado para orçamento correto.
---
### SIT_002 — ORCAMENTO_E_EXAME
**Situação real:** Vocês fazem esse exame?
**Como o cliente pensa:** Quer confirmar disponibilidade antes de se deslocar.
**Como o iniciante responde:** Responde sim ou não pelo termo reconhecido.
**Como o especialista pensa:** Confere nome exato, unidade e modalidade para evitar disponibilidade errada.
**Estado detectado:** `STATE_NEEDS_EXAM_AVAILABILITY`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`
**Risco principal:** `RISK_WRONG_AVAILABILITY`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_EXAM_AVAILABILITY`
**Ação permitida positiva:** Solicitar pedido médico ou nome completo do exame e unidade desejada.
**Ação de confiança:** Mostrar que a conferência evita deslocamento perdido.
**Resultado esperado:** Disponibilidade verificada ou atendimento humano acionado.
---
### SIT_003 — ORCAMENTO_E_EXAME
**Situação real:** Posso mandar o pedido por aqui?
**Como o cliente pensa:** Quer acelerar orçamento ou agendamento.
**Como o iniciante responde:** Apenas autoriza o envio.
**Como o especialista pensa:** Recebe o pedido e usa o documento para identificar exames, preparo, convênio e agenda.
**Estado detectado:** `STATE_HAS_MEDICAL_ORDER_INTENT`
**Lacunas:** `GAP_ORDER_IMAGE`
**Risco principal:** `RISK_LOST_CONTEXT`
**Próximo objetivo:** `OBJECTIVE_COLLECT_MEDICAL_ORDER`
**Ação permitida positiva:** Solicitar foto legível do pedido.
**Ação de confiança:** Orientar envio com dados visíveis e informar que será usado para conferência.
**Resultado esperado:** Pedido recebido para próxima etapa.
---
### SIT_004 — ORCAMENTO_E_EXAME
**Situação real:** O médico pediu vários exames.
**Como o cliente pensa:** Quer resolver tudo em uma conversa.
**Como o iniciante responde:** Pede para listar exames manualmente.
**Como o especialista pensa:** Solicita foto do pedido para evitar omissão de exames e organizar orçamento conjunto.
**Estado detectado:** `STATE_MULTIPLE_EXAMS`
**Lacunas:** `GAP_FULL_ORDER`
**Risco principal:** `RISK_INCOMPLETE_BUNDLE`
**Próximo objetivo:** `OBJECTIVE_MAP_EXAM_LIST`
**Ação permitida positiva:** Solicitar foto do pedido completo.
**Ação de confiança:** Dizer que isso ajuda a conferir todos os exames de uma vez.
**Resultado esperado:** Lista de exames mapeada.
---
### SIT_005 — ORCAMENTO_E_EXAME
**Situação real:** Quanto fica tudo?
**Como o cliente pensa:** Quer preço total e simplicidade.
**Como o iniciante responde:** Soma preços sem validar escopo.
**Como o especialista pensa:** Confirma todos os exames e modalidade antes de totalizar.
**Estado detectado:** `STATE_NEEDS_TOTAL_PRICE`
**Lacunas:** `GAP_FULL_EXAM_LIST`, `GAP_PAYMENT_MODE`
**Risco principal:** `RISK_INCOMPLETE_PRICE`
**Próximo objetivo:** `OBJECTIVE_PREPARE_TOTAL_QUOTE`
**Ação permitida positiva:** Coletar pedido completo e modalidade particular/convênio.
**Ação de confiança:** Explicar que o total depende da lista completa e forma de atendimento.
**Resultado esperado:** Orçamento total preparado.
---
### SIT_006 — ORCAMENTO_E_EXAME
**Situação real:** Tem desconto particular?
**Como o cliente pensa:** Está comparando clínicas e pode converter com incentivo.
**Como o iniciante responde:** Responde desconto genérico.
**Como o especialista pensa:** Confirma exames e política comercial cadastrada antes de falar condição.
**Estado detectado:** `STATE_PRICE_NEGOTIATION`
**Lacunas:** `GAP_EXAM_LIST`, `GAP_CLINIC_POLICY`
**Risco principal:** `RISK_INVENTED_DISCOUNT`
**Próximo objetivo:** `OBJECTIVE_CHECK_PRIVATE_CONDITION`
**Ação permitida positiva:** Solicitar exame/pedido e consultar condição cadastrada.
**Ação de confiança:** Apresentar condição somente quando constar no cadastro.
**Resultado esperado:** Condição particular informada com segurança.
---
### SIT_007 — ORCAMENTO_E_EXAME
**Situação real:** Preciso do valor para enviar ao convênio.
**Como o cliente pensa:** Quer documento/valor para reembolso ou autorização.
**Como o iniciante responde:** Passa preço solto.
**Como o especialista pensa:** Verifica exame, dados necessários e formato de orçamento aceito pela clínica.
**Estado detectado:** `STATE_NEEDS_FORMAL_QUOTE`
**Lacunas:** `GAP_EXAM_LIST`, `GAP_PATIENT_DATA`, `GAP_QUOTE_FORMAT`
**Risco principal:** `RISK_INVALID_QUOTE`
**Próximo objetivo:** `OBJECTIVE_PREPARE_FORMAL_QUOTE`
**Ação permitida positiva:** Coletar pedido, dados mínimos e orientar canal de orçamento formal.
**Ação de confiança:** Explicar o caminho correto para orçamento válido.
**Resultado esperado:** Orçamento formal encaminhado.
---
### SIT_008 — CONVENIO
**Situação real:** Aceita Unimed?
**Como o cliente pensa:** Quer viabilizar o exame pelo plano ou comparar alternativa particular.
**Como o iniciante responde:** Responde sim/não ou regra genérica.
**Como o especialista pensa:** Valida plano, produto, exame, pedido e autorização antes de confirmar cobertura ou caminho particular.
**Estado detectado:** `STATE_NEEDS_CONVENIO`
**Lacunas:** `GAP_PLAN_DETAILS`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_AUTHORIZATION`
**Risco principal:** `RISK_COVERAGE_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_COVERAGE`
**Ação permitida positiva:** Solicitar dados do plano e foto do pedido médico.
**Ação de confiança:** Explicar que cobertura depende do plano, exame e autorização quando aplicável.
**Resultado esperado:** Cobertura ou alternativa particular encaminhada corretamente.
---
### SIT_009 — CONVENIO
**Situação real:** Aceita meu plano?
**Como o cliente pensa:** Quer viabilizar o exame pelo plano ou comparar alternativa particular.
**Como o iniciante responde:** Responde sim/não ou regra genérica.
**Como o especialista pensa:** Valida plano, produto, exame, pedido e autorização antes de confirmar cobertura ou caminho particular.
**Estado detectado:** `STATE_NEEDS_CONVENIO`
**Lacunas:** `GAP_PLAN_DETAILS`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_AUTHORIZATION`
**Risco principal:** `RISK_COVERAGE_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_COVERAGE`
**Ação permitida positiva:** Solicitar dados do plano e foto do pedido médico.
**Ação de confiança:** Explicar que cobertura depende do plano, exame e autorização quando aplicável.
**Resultado esperado:** Cobertura ou alternativa particular encaminhada corretamente.
---
### SIT_010 — CONVENIO
**Situação real:** Precisa autorização?
**Como o cliente pensa:** Quer viabilizar o exame pelo plano ou comparar alternativa particular.
**Como o iniciante responde:** Responde sim/não ou regra genérica.
**Como o especialista pensa:** Valida plano, produto, exame, pedido e autorização antes de confirmar cobertura ou caminho particular.
**Estado detectado:** `STATE_NEEDS_CONVENIO`
**Lacunas:** `GAP_PLAN_DETAILS`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_AUTHORIZATION`
**Risco principal:** `RISK_COVERAGE_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_COVERAGE`
**Ação permitida positiva:** Solicitar dados do plano e foto do pedido médico.
**Ação de confiança:** Explicar que cobertura depende do plano, exame e autorização quando aplicável.
**Resultado esperado:** Cobertura ou alternativa particular encaminhada corretamente.
---
### SIT_011 — CONVENIO
**Situação real:** Meu convênio cobre?
**Como o cliente pensa:** Quer viabilizar o exame pelo plano ou comparar alternativa particular.
**Como o iniciante responde:** Responde sim/não ou regra genérica.
**Como o especialista pensa:** Valida plano, produto, exame, pedido e autorização antes de confirmar cobertura ou caminho particular.
**Estado detectado:** `STATE_NEEDS_CONVENIO`
**Lacunas:** `GAP_PLAN_DETAILS`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_AUTHORIZATION`
**Risco principal:** `RISK_COVERAGE_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_COVERAGE`
**Ação permitida positiva:** Solicitar dados do plano e foto do pedido médico.
**Ação de confiança:** Explicar que cobertura depende do plano, exame e autorização quando aplicável.
**Resultado esperado:** Cobertura ou alternativa particular encaminhada corretamente.
---
### SIT_012 — CONVENIO
**Situação real:** Posso fazer particular mesmo tendo plano?
**Como o cliente pensa:** Quer viabilizar o exame pelo plano ou comparar alternativa particular.
**Como o iniciante responde:** Responde sim/não ou regra genérica.
**Como o especialista pensa:** Valida plano, produto, exame, pedido e autorização antes de confirmar cobertura ou caminho particular.
**Estado detectado:** `STATE_NEEDS_CONVENIO`
**Lacunas:** `GAP_PLAN_DETAILS`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_AUTHORIZATION`
**Risco principal:** `RISK_COVERAGE_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_COVERAGE`
**Ação permitida positiva:** Solicitar dados do plano e foto do pedido médico.
**Ação de confiança:** Explicar que cobertura depende do plano, exame e autorização quando aplicável.
**Resultado esperado:** Cobertura ou alternativa particular encaminhada corretamente.
---
### SIT_013 — CONVENIO
**Situação real:** Preciso levar a carteirinha?
**Como o cliente pensa:** Quer viabilizar o exame pelo plano ou comparar alternativa particular.
**Como o iniciante responde:** Responde sim/não ou regra genérica.
**Como o especialista pensa:** Valida plano, produto, exame, pedido e autorização antes de confirmar cobertura ou caminho particular.
**Estado detectado:** `STATE_NEEDS_CONVENIO`
**Lacunas:** `GAP_PLAN_DETAILS`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_AUTHORIZATION`
**Risco principal:** `RISK_COVERAGE_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_COVERAGE`
**Ação permitida positiva:** Solicitar dados do plano e foto do pedido médico.
**Ação de confiança:** Explicar que cobertura depende do plano, exame e autorização quando aplicável.
**Resultado esperado:** Cobertura ou alternativa particular encaminhada corretamente.
---
### SIT_014 — CONVENIO
**Situação real:** Meu pedido serve para o convênio?
**Como o cliente pensa:** Quer viabilizar o exame pelo plano ou comparar alternativa particular.
**Como o iniciante responde:** Responde sim/não ou regra genérica.
**Como o especialista pensa:** Valida plano, produto, exame, pedido e autorização antes de confirmar cobertura ou caminho particular.
**Estado detectado:** `STATE_NEEDS_CONVENIO`
**Lacunas:** `GAP_PLAN_DETAILS`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_AUTHORIZATION`
**Risco principal:** `RISK_COVERAGE_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_COVERAGE`
**Ação permitida positiva:** Solicitar dados do plano e foto do pedido médico.
**Ação de confiança:** Explicar que cobertura depende do plano, exame e autorização quando aplicável.
**Resultado esperado:** Cobertura ou alternativa particular encaminhada corretamente.
---
### SIT_015 — PREPARO
**Situação real:** Precisa jejum?
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_PREPARATION_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_PREPARATION`
**Ação permitida positiva:** Solicitar exame ou pedido e consultar preparo cadastrado.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_016 — PREPARO
**Situação real:** Quantas horas de jejum?
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_PREPARATION_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_PREPARATION`
**Ação permitida positiva:** Solicitar exame ou pedido e consultar preparo cadastrado.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_017 — PREPARO
**Situação real:** Posso beber água?
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_PREPARATION_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_PREPARATION`
**Ação permitida positiva:** Solicitar exame ou pedido e consultar preparo cadastrado.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_018 — PREPARO
**Situação real:** Tomo remédio todo dia.
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_MEDICATION_MISGUIDANCE`
**Próximo objetivo:** `OBJECTIVE_SAFE_MEDICATION_GUIDANCE`
**Ação permitida positiva:** Informar preparo cadastrado e direcionar decisão de medicação ao médico ou equipe humana.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_019 — PREPARO
**Situação real:** Esqueci e tomei café.
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_INVALID_EXAM`
**Próximo objetivo:** `OBJECTIVE_VALIDATE_READINESS`
**Ação permitida positiva:** Coletar exame e falha de preparo para decidir manutenção ou remarcação.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_020 — PREPARO
**Situação real:** Bebi ontem.
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_INVALID_EXAM`
**Próximo objetivo:** `OBJECTIVE_VALIDATE_READINESS`
**Ação permitida positiva:** Coletar exame e falha de preparo para decidir manutenção ou remarcação.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_021 — PREPARO
**Situação real:** Posso fazer mesmo assim?
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_INVALID_EXAM`
**Próximo objetivo:** `OBJECTIVE_VALIDATE_READINESS`
**Ação permitida positiva:** Coletar exame e falha de preparo para decidir manutenção ou remarcação.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_022 — PREPARO
**Situação real:** Não recebi o preparo.
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_PREPARATION_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_PREPARATION`
**Ação permitida positiva:** Solicitar exame ou pedido e consultar preparo cadastrado.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_023 — PREPARO
**Situação real:** Perdi as orientações.
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_PREPARATION_FAILURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_PREPARATION`
**Ação permitida positiva:** Solicitar exame ou pedido e consultar preparo cadastrado.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_024 — PREPARO
**Situação real:** Preciso remarcar por causa do preparo?
**Como o cliente pensa:** Quer saber se está apto para realizar o exame.
**Como o iniciante responde:** Responde regra genérica.
**Como o especialista pensa:** Identifica o exame e valida o preparo específico antes de permitir avanço.
**Estado detectado:** `STATE_NEEDS_PREPARATION`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREPARATION_STATUS`
**Risco principal:** `RISK_INVALID_EXAM`
**Próximo objetivo:** `OBJECTIVE_VALIDATE_READINESS`
**Ação permitida positiva:** Coletar exame e falha de preparo para decidir manutenção ou remarcação.
**Ação de confiança:** Usar preparo cadastrado e linguagem objetiva.
**Resultado esperado:** Preparo correto enviado ou remarcação orientada.
---
### SIT_025 — AGENDAMENTO
**Situação real:** Tem horário amanhã?
**Como o cliente pensa:** Quer transformar intenção em comparecimento possível.
**Como o iniciante responde:** Responde disponibilidade sem checar pré-requisitos.
**Como o especialista pensa:** Confere exame, preparo, unidade, documentos e agenda antes de confirmar.
**Estado detectado:** `STATE_NEEDS_SCHEDULE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`, `GAP_PREPARATION_STATUS`, `GAP_APPOINTMENT_DATA`
**Risco principal:** `RISK_BAD_APPOINTMENT`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_APPOINTMENT`
**Ação permitida positiva:** Coletar exame, unidade, período preferido e status do preparo.
**Ação de confiança:** Conferir prontidão antes de confirmar agenda.
**Resultado esperado:** Agendamento compatível confirmado ou alternativa oferecida.
---
### SIT_026 — AGENDAMENTO
**Situação real:** Posso fazer hoje?
**Como o cliente pensa:** Quer transformar intenção em comparecimento possível.
**Como o iniciante responde:** Responde disponibilidade sem checar pré-requisitos.
**Como o especialista pensa:** Confere exame, preparo, unidade, documentos e agenda antes de confirmar.
**Estado detectado:** `STATE_NEEDS_SCHEDULE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`, `GAP_PREPARATION_STATUS`, `GAP_APPOINTMENT_DATA`
**Risco principal:** `RISK_BAD_APPOINTMENT`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_APPOINTMENT`
**Ação permitida positiva:** Coletar exame, unidade, período preferido e status do preparo.
**Ação de confiança:** Conferir prontidão antes de confirmar agenda.
**Resultado esperado:** Agendamento compatível confirmado ou alternativa oferecida.
---
### SIT_027 — AGENDAMENTO
**Situação real:** Qual unidade atende?
**Como o cliente pensa:** Quer transformar intenção em comparecimento possível.
**Como o iniciante responde:** Responde disponibilidade sem checar pré-requisitos.
**Como o especialista pensa:** Confere exame, preparo, unidade, documentos e agenda antes de confirmar.
**Estado detectado:** `STATE_NEEDS_SCHEDULE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`, `GAP_PREPARATION_STATUS`, `GAP_APPOINTMENT_DATA`
**Risco principal:** `RISK_BAD_APPOINTMENT`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_APPOINTMENT`
**Ação permitida positiva:** Coletar exame, unidade, período preferido e status do preparo.
**Ação de confiança:** Conferir prontidão antes de confirmar agenda.
**Resultado esperado:** Agendamento compatível confirmado ou alternativa oferecida.
---
### SIT_028 — AGENDAMENTO
**Situação real:** Quanto tempo dura?
**Como o cliente pensa:** Quer transformar intenção em comparecimento possível.
**Como o iniciante responde:** Responde disponibilidade sem checar pré-requisitos.
**Como o especialista pensa:** Confere exame, preparo, unidade, documentos e agenda antes de confirmar.
**Estado detectado:** `STATE_NEEDS_SCHEDULE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`, `GAP_PREPARATION_STATUS`, `GAP_APPOINTMENT_DATA`
**Risco principal:** `RISK_BAD_APPOINTMENT`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_APPOINTMENT`
**Ação permitida positiva:** Coletar exame, unidade, período preferido e status do preparo.
**Ação de confiança:** Conferir prontidão antes de confirmar agenda.
**Resultado esperado:** Agendamento compatível confirmado ou alternativa oferecida.
---
### SIT_029 — AGENDAMENTO
**Situação real:** Preciso chegar antes?
**Como o cliente pensa:** Quer transformar intenção em comparecimento possível.
**Como o iniciante responde:** Responde disponibilidade sem checar pré-requisitos.
**Como o especialista pensa:** Confere exame, preparo, unidade, documentos e agenda antes de confirmar.
**Estado detectado:** `STATE_NEEDS_SCHEDULE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`, `GAP_PREPARATION_STATUS`, `GAP_APPOINTMENT_DATA`
**Risco principal:** `RISK_BAD_APPOINTMENT`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_APPOINTMENT`
**Ação permitida positiva:** Coletar exame, unidade, período preferido e status do preparo.
**Ação de confiança:** Conferir prontidão antes de confirmar agenda.
**Resultado esperado:** Agendamento compatível confirmado ou alternativa oferecida.
---
### SIT_030 — AGENDAMENTO
**Situação real:** Posso remarcar?
**Como o cliente pensa:** Quer transformar intenção em comparecimento possível.
**Como o iniciante responde:** Responde disponibilidade sem checar pré-requisitos.
**Como o especialista pensa:** Confere exame, preparo, unidade, documentos e agenda antes de confirmar.
**Estado detectado:** `STATE_NEEDS_SCHEDULE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`, `GAP_PREPARATION_STATUS`, `GAP_APPOINTMENT_DATA`
**Risco principal:** `RISK_BAD_APPOINTMENT`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_APPOINTMENT`
**Ação permitida positiva:** Coletar exame, unidade, período preferido e status do preparo.
**Ação de confiança:** Conferir prontidão antes de confirmar agenda.
**Resultado esperado:** Agendamento compatível confirmado ou alternativa oferecida.
---
### SIT_031 — AGENDAMENTO
**Situação real:** Cheguei atrasado.
**Como o cliente pensa:** Quer transformar intenção em comparecimento possível.
**Como o iniciante responde:** Responde disponibilidade sem checar pré-requisitos.
**Como o especialista pensa:** Confere exame, preparo, unidade, documentos e agenda antes de confirmar.
**Estado detectado:** `STATE_NEEDS_SCHEDULE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`, `GAP_PREPARATION_STATUS`, `GAP_APPOINTMENT_DATA`
**Risco principal:** `RISK_BAD_APPOINTMENT`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_APPOINTMENT`
**Ação permitida positiva:** Coletar exame, unidade, período preferido e status do preparo.
**Ação de confiança:** Conferir prontidão antes de confirmar agenda.
**Resultado esperado:** Agendamento compatível confirmado ou alternativa oferecida.
---
### SIT_032 — AGENDAMENTO
**Situação real:** Posso cancelar?
**Como o cliente pensa:** Quer transformar intenção em comparecimento possível.
**Como o iniciante responde:** Responde disponibilidade sem checar pré-requisitos.
**Como o especialista pensa:** Confere exame, preparo, unidade, documentos e agenda antes de confirmar.
**Estado detectado:** `STATE_NEEDS_SCHEDULE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`, `GAP_PREPARATION_STATUS`, `GAP_APPOINTMENT_DATA`
**Risco principal:** `RISK_BAD_APPOINTMENT`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_APPOINTMENT`
**Ação permitida positiva:** Coletar exame, unidade, período preferido e status do preparo.
**Ação de confiança:** Conferir prontidão antes de confirmar agenda.
**Resultado esperado:** Agendamento compatível confirmado ou alternativa oferecida.
---
### SIT_033 — AGENDAMENTO
**Situação real:** Posso fazer em outra unidade?
**Como o cliente pensa:** Quer transformar intenção em comparecimento possível.
**Como o iniciante responde:** Responde disponibilidade sem checar pré-requisitos.
**Como o especialista pensa:** Confere exame, preparo, unidade, documentos e agenda antes de confirmar.
**Estado detectado:** `STATE_NEEDS_SCHEDULE`
**Lacunas:** `GAP_EXAM_NAME_OR_ORDER`, `GAP_PREFERRED_UNIT`, `GAP_PREPARATION_STATUS`, `GAP_APPOINTMENT_DATA`
**Risco principal:** `RISK_BAD_APPOINTMENT`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_APPOINTMENT`
**Ação permitida positiva:** Coletar exame, unidade, período preferido e status do preparo.
**Ação de confiança:** Conferir prontidão antes de confirmar agenda.
**Resultado esperado:** Agendamento compatível confirmado ou alternativa oferecida.
---
### SIT_034 — RESULTADO
**Situação real:** Já saiu meu resultado?
**Como o cliente pensa:** Quer acessar laudo, status ou prazo com segurança.
**Como o iniciante responde:** Responde sem confirmar identidade ou canal.
**Como o especialista pensa:** Protege dados sensíveis, valida identificação mínima e conduz para canal seguro cadastrado.
**Estado detectado:** `STATE_NEEDS_RESULT`
**Lacunas:** `GAP_PATIENT_IDENTIFICATION`, `GAP_PROTOCOL_OR_DATE`, `GAP_RESULT_CHANNEL`
**Risco principal:** `RISK_DATA_EXPOSURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_RESULT_PATH`
**Ação permitida positiva:** Solicitar dados mínimos e orientar portal, protocolo ou canal seguro cadastrado.
**Ação de confiança:** Proteger dados de saúde e evitar exposição em conversa aberta.
**Resultado esperado:** Resultado acessado, status consultado ou suporte acionado.
---
### SIT_035 — RESULTADO
**Situação real:** Como acesso?
**Como o cliente pensa:** Quer acessar laudo, status ou prazo com segurança.
**Como o iniciante responde:** Responde sem confirmar identidade ou canal.
**Como o especialista pensa:** Protege dados sensíveis, valida identificação mínima e conduz para canal seguro cadastrado.
**Estado detectado:** `STATE_NEEDS_RESULT`
**Lacunas:** `GAP_PATIENT_IDENTIFICATION`, `GAP_PROTOCOL_OR_DATE`, `GAP_RESULT_CHANNEL`
**Risco principal:** `RISK_DATA_EXPOSURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_RESULT_PATH`
**Ação permitida positiva:** Solicitar dados mínimos e orientar portal, protocolo ou canal seguro cadastrado.
**Ação de confiança:** Proteger dados de saúde e evitar exposição em conversa aberta.
**Resultado esperado:** Resultado acessado, status consultado ou suporte acionado.
---
### SIT_036 — RESULTADO
**Situação real:** Perdi minha senha.
**Como o cliente pensa:** Quer acessar laudo, status ou prazo com segurança.
**Como o iniciante responde:** Responde sem confirmar identidade ou canal.
**Como o especialista pensa:** Protege dados sensíveis, valida identificação mínima e conduz para canal seguro cadastrado.
**Estado detectado:** `STATE_NEEDS_RESULT`
**Lacunas:** `GAP_PATIENT_IDENTIFICATION`, `GAP_PROTOCOL_OR_DATE`, `GAP_RESULT_CHANNEL`
**Risco principal:** `RISK_DATA_EXPOSURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_RESULT_PATH`
**Ação permitida positiva:** Solicitar dados mínimos e orientar portal, protocolo ou canal seguro cadastrado.
**Ação de confiança:** Proteger dados de saúde e evitar exposição em conversa aberta.
**Resultado esperado:** Resultado acessado, status consultado ou suporte acionado.
---
### SIT_037 — RESULTADO
**Situação real:** Não consigo entrar.
**Como o cliente pensa:** Quer acessar laudo, status ou prazo com segurança.
**Como o iniciante responde:** Responde sem confirmar identidade ou canal.
**Como o especialista pensa:** Protege dados sensíveis, valida identificação mínima e conduz para canal seguro cadastrado.
**Estado detectado:** `STATE_NEEDS_RESULT`
**Lacunas:** `GAP_PATIENT_IDENTIFICATION`, `GAP_PROTOCOL_OR_DATE`, `GAP_RESULT_CHANNEL`
**Risco principal:** `RISK_DATA_EXPOSURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_RESULT_PATH`
**Ação permitida positiva:** Solicitar dados mínimos e orientar portal, protocolo ou canal seguro cadastrado.
**Ação de confiança:** Proteger dados de saúde e evitar exposição em conversa aberta.
**Resultado esperado:** Resultado acessado, status consultado ou suporte acionado.
---
### SIT_038 — RESULTADO
**Situação real:** Meu resultado não apareceu.
**Como o cliente pensa:** Quer acessar laudo, status ou prazo com segurança.
**Como o iniciante responde:** Responde sem confirmar identidade ou canal.
**Como o especialista pensa:** Protege dados sensíveis, valida identificação mínima e conduz para canal seguro cadastrado.
**Estado detectado:** `STATE_NEEDS_RESULT`
**Lacunas:** `GAP_PATIENT_IDENTIFICATION`, `GAP_PROTOCOL_OR_DATE`, `GAP_RESULT_CHANNEL`
**Risco principal:** `RISK_DATA_EXPOSURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_RESULT_PATH`
**Ação permitida positiva:** Solicitar dados mínimos e orientar portal, protocolo ou canal seguro cadastrado.
**Ação de confiança:** Proteger dados de saúde e evitar exposição em conversa aberta.
**Resultado esperado:** Resultado acessado, status consultado ou suporte acionado.
---
### SIT_039 — RESULTADO
**Situação real:** Quando fica pronto?
**Como o cliente pensa:** Quer acessar laudo, status ou prazo com segurança.
**Como o iniciante responde:** Responde sem confirmar identidade ou canal.
**Como o especialista pensa:** Protege dados sensíveis, valida identificação mínima e conduz para canal seguro cadastrado.
**Estado detectado:** `STATE_NEEDS_RESULT`
**Lacunas:** `GAP_PATIENT_IDENTIFICATION`, `GAP_PROTOCOL_OR_DATE`, `GAP_RESULT_CHANNEL`
**Risco principal:** `RISK_DATA_EXPOSURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_RESULT_PATH`
**Ação permitida positiva:** Solicitar dados mínimos e orientar portal, protocolo ou canal seguro cadastrado.
**Ação de confiança:** Proteger dados de saúde e evitar exposição em conversa aberta.
**Resultado esperado:** Resultado acessado, status consultado ou suporte acionado.
---
### SIT_040 — RESULTADO
**Situação real:** Posso retirar presencialmente?
**Como o cliente pensa:** Quer acessar laudo, status ou prazo com segurança.
**Como o iniciante responde:** Responde sem confirmar identidade ou canal.
**Como o especialista pensa:** Protege dados sensíveis, valida identificação mínima e conduz para canal seguro cadastrado.
**Estado detectado:** `STATE_NEEDS_RESULT`
**Lacunas:** `GAP_PATIENT_IDENTIFICATION`, `GAP_PROTOCOL_OR_DATE`, `GAP_RESULT_CHANNEL`
**Risco principal:** `RISK_DATA_EXPOSURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_RESULT_PATH`
**Ação permitida positiva:** Solicitar dados mínimos e orientar portal, protocolo ou canal seguro cadastrado.
**Ação de confiança:** Proteger dados de saúde e evitar exposição em conversa aberta.
**Resultado esperado:** Resultado acessado, status consultado ou suporte acionado.
---
### SIT_041 — RESULTADO
**Situação real:** Posso receber por e-mail?
**Como o cliente pensa:** Quer acessar laudo, status ou prazo com segurança.
**Como o iniciante responde:** Responde sem confirmar identidade ou canal.
**Como o especialista pensa:** Protege dados sensíveis, valida identificação mínima e conduz para canal seguro cadastrado.
**Estado detectado:** `STATE_NEEDS_RESULT`
**Lacunas:** `GAP_PATIENT_IDENTIFICATION`, `GAP_PROTOCOL_OR_DATE`, `GAP_RESULT_CHANNEL`
**Risco principal:** `RISK_DATA_EXPOSURE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_RESULT_PATH`
**Ação permitida positiva:** Solicitar dados mínimos e orientar portal, protocolo ou canal seguro cadastrado.
**Ação de confiança:** Proteger dados de saúde e evitar exposição em conversa aberta.
**Resultado esperado:** Resultado acessado, status consultado ou suporte acionado.
---
### SIT_042 — ATENDIMENTO_DOMICILIAR
**Situação real:** Vocês coletam em casa?
**Como o cliente pensa:** Quer resolver exame com conforto, limitação de deslocamento ou familiar.
**Como o iniciante responde:** Responde disponibilidade genérica.
**Como o especialista pensa:** Confere região, exame, paciente, preparo e política de atendimento domiciliar.
**Estado detectado:** `STATE_NEEDS_HOME_SERVICE`
**Lacunas:** `GAP_ADDRESS_REGION`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_PATIENT_DATA`
**Risco principal:** `RISK_UNAVAILABLE_HOME_SERVICE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_HOME_SERVICE`
**Ação permitida positiva:** Coletar bairro/cidade, pedido e dados do paciente.
**Ação de confiança:** Validar região, exame e dados antes de confirmar visita.
**Resultado esperado:** Atendimento domiciliar validado ou alternativa oferecida.
---
### SIT_043 — ATENDIMENTO_DOMICILIAR
**Situação real:** Tem taxa?
**Como o cliente pensa:** Quer resolver exame com conforto, limitação de deslocamento ou familiar.
**Como o iniciante responde:** Responde disponibilidade genérica.
**Como o especialista pensa:** Confere região, exame, paciente, preparo e política de atendimento domiciliar.
**Estado detectado:** `STATE_NEEDS_HOME_SERVICE`
**Lacunas:** `GAP_ADDRESS_REGION`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_PATIENT_DATA`
**Risco principal:** `RISK_UNAVAILABLE_HOME_SERVICE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_HOME_SERVICE`
**Ação permitida positiva:** Coletar bairro/cidade, pedido e dados do paciente.
**Ação de confiança:** Validar região, exame e dados antes de confirmar visita.
**Resultado esperado:** Atendimento domiciliar validado ou alternativa oferecida.
---
### SIT_044 — ATENDIMENTO_DOMICILIAR
**Situação real:** Atende meu bairro?
**Como o cliente pensa:** Quer resolver exame com conforto, limitação de deslocamento ou familiar.
**Como o iniciante responde:** Responde disponibilidade genérica.
**Como o especialista pensa:** Confere região, exame, paciente, preparo e política de atendimento domiciliar.
**Estado detectado:** `STATE_NEEDS_HOME_SERVICE`
**Lacunas:** `GAP_ADDRESS_REGION`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_PATIENT_DATA`
**Risco principal:** `RISK_UNAVAILABLE_HOME_SERVICE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_HOME_SERVICE`
**Ação permitida positiva:** Coletar bairro/cidade, pedido e dados do paciente.
**Ação de confiança:** Validar região, exame e dados antes de confirmar visita.
**Resultado esperado:** Atendimento domiciliar validado ou alternativa oferecida.
---
### SIT_045 — ATENDIMENTO_DOMICILIAR
**Situação real:** Posso marcar para meus pais?
**Como o cliente pensa:** Quer resolver exame com conforto, limitação de deslocamento ou familiar.
**Como o iniciante responde:** Responde disponibilidade genérica.
**Como o especialista pensa:** Confere região, exame, paciente, preparo e política de atendimento domiciliar.
**Estado detectado:** `STATE_NEEDS_HOME_SERVICE`
**Lacunas:** `GAP_ADDRESS_REGION`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_PATIENT_DATA`
**Risco principal:** `RISK_UNAVAILABLE_HOME_SERVICE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_HOME_SERVICE`
**Ação permitida positiva:** Coletar bairro/cidade, pedido e dados do paciente.
**Ação de confiança:** Validar região, exame e dados antes de confirmar visita.
**Resultado esperado:** Atendimento domiciliar validado ou alternativa oferecida.
---
### SIT_046 — ATENDIMENTO_DOMICILIAR
**Situação real:** Atende idoso?
**Como o cliente pensa:** Quer resolver exame com conforto, limitação de deslocamento ou familiar.
**Como o iniciante responde:** Responde disponibilidade genérica.
**Como o especialista pensa:** Confere região, exame, paciente, preparo e política de atendimento domiciliar.
**Estado detectado:** `STATE_NEEDS_HOME_SERVICE`
**Lacunas:** `GAP_ADDRESS_REGION`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_PATIENT_DATA`
**Risco principal:** `RISK_UNAVAILABLE_HOME_SERVICE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_HOME_SERVICE`
**Ação permitida positiva:** Coletar bairro/cidade, pedido e dados do paciente.
**Ação de confiança:** Validar região, exame e dados antes de confirmar visita.
**Resultado esperado:** Atendimento domiciliar validado ou alternativa oferecida.
---
### SIT_047 — ATENDIMENTO_DOMICILIAR
**Situação real:** Posso fazer vários exames no mesmo dia?
**Como o cliente pensa:** Quer resolver exame com conforto, limitação de deslocamento ou familiar.
**Como o iniciante responde:** Responde disponibilidade genérica.
**Como o especialista pensa:** Confere região, exame, paciente, preparo e política de atendimento domiciliar.
**Estado detectado:** `STATE_NEEDS_HOME_SERVICE`
**Lacunas:** `GAP_ADDRESS_REGION`, `GAP_EXAM_NAME_OR_ORDER`, `GAP_PATIENT_DATA`
**Risco principal:** `RISK_UNAVAILABLE_HOME_SERVICE`
**Próximo objetivo:** `OBJECTIVE_CONFIRM_HOME_SERVICE`
**Ação permitida positiva:** Coletar bairro/cidade, pedido e dados do paciente.
**Ação de confiança:** Validar região, exame e dados antes de confirmar visita.
**Resultado esperado:** Atendimento domiciliar validado ou alternativa oferecida.
---
### SIT_048 — ANSIEDADE_RECLAMACAO_URGENCIA
**Situação real:** Estou preocupado.
**Como o cliente pensa:** Busca acolhimento, solução rápida ou recuperação de confiança.
**Como o iniciante responde:** Responde de forma fria, defensiva ou clínica demais.
**Como o especialista pensa:** Acolhe, identifica etapa da jornada e transforma emoção em próximo passo operacional.
**Estado detectado:** `STATE_ANXIOUS`
**Lacunas:** `GAP_CURRENT_NEED`, `GAP_EXAM_OR_STAGE`, `GAP_PATIENT_CONTACT`
**Risco principal:** `RISK_PATIENT_LOSS`
**Próximo objetivo:** `OBJECTIVE_RECOVER_OR_FAST_TRACK`
**Ação permitida positiva:** Acolher com objetividade, coletar contexto mínimo e encaminhar próximo passo ou humano.
**Ação de confiança:** Mostrar presença, método e próximo passo claro.
**Resultado esperado:** Paciente orientado, urgência operacional tratada ou caso recuperado.
---
### SIT_049 — ANSIEDADE_RECLAMACAO_URGENCIA
**Situação real:** O médico pediu urgente.
**Como o cliente pensa:** Busca acolhimento, solução rápida ou recuperação de confiança.
**Como o iniciante responde:** Responde de forma fria, defensiva ou clínica demais.
**Como o especialista pensa:** Acolhe, identifica etapa da jornada e transforma emoção em próximo passo operacional.
**Estado detectado:** `STATE_URGENT`
**Lacunas:** `GAP_CURRENT_NEED`, `GAP_EXAM_OR_STAGE`, `GAP_PATIENT_CONTACT`
**Risco principal:** `RISK_PATIENT_LOSS`
**Próximo objetivo:** `OBJECTIVE_RECOVER_OR_FAST_TRACK`
**Ação permitida positiva:** Acolher com objetividade, coletar contexto mínimo e encaminhar próximo passo ou humano.
**Ação de confiança:** Mostrar presença, método e próximo passo claro.
**Resultado esperado:** Paciente orientado, urgência operacional tratada ou caso recuperado.
---
### SIT_050 — ANSIEDADE_RECLAMACAO_URGENCIA
**Situação real:** Preciso fazer o quanto antes.
**Como o cliente pensa:** Busca acolhimento, solução rápida ou recuperação de confiança.
**Como o iniciante responde:** Responde de forma fria, defensiva ou clínica demais.
**Como o especialista pensa:** Acolhe, identifica etapa da jornada e transforma emoção em próximo passo operacional.
**Estado detectado:** `STATE_URGENT`
**Lacunas:** `GAP_CURRENT_NEED`, `GAP_EXAM_OR_STAGE`, `GAP_PATIENT_CONTACT`
**Risco principal:** `RISK_PATIENT_LOSS`
**Próximo objetivo:** `OBJECTIVE_RECOVER_OR_FAST_TRACK`
**Ação permitida positiva:** Acolher com objetividade, coletar contexto mínimo e encaminhar próximo passo ou humano.
**Ação de confiança:** Mostrar presença, método e próximo passo claro.
**Resultado esperado:** Paciente orientado, urgência operacional tratada ou caso recuperado.
---
### SIT_051 — ANSIEDADE_RECLAMACAO_URGENCIA
**Situação real:** Estou aguardando esse resultado.
**Como o cliente pensa:** Busca acolhimento, solução rápida ou recuperação de confiança.
**Como o iniciante responde:** Responde de forma fria, defensiva ou clínica demais.
**Como o especialista pensa:** Acolhe, identifica etapa da jornada e transforma emoção em próximo passo operacional.
**Estado detectado:** `STATE_WAITING_RESULT_ANXIOUS`
**Lacunas:** `GAP_CURRENT_NEED`, `GAP_EXAM_OR_STAGE`, `GAP_PATIENT_CONTACT`
**Risco principal:** `RISK_PATIENT_LOSS`
**Próximo objetivo:** `OBJECTIVE_RECOVER_OR_FAST_TRACK`
**Ação permitida positiva:** Acolher com objetividade, coletar contexto mínimo e encaminhar próximo passo ou humano.
**Ação de confiança:** Mostrar presença, método e próximo passo claro.
**Resultado esperado:** Paciente orientado, urgência operacional tratada ou caso recuperado.
---
### SIT_052 — ANSIEDADE_RECLAMACAO_URGENCIA
**Situação real:** Estou nervoso com esse exame.
**Como o cliente pensa:** Busca acolhimento, solução rápida ou recuperação de confiança.
**Como o iniciante responde:** Responde de forma fria, defensiva ou clínica demais.
**Como o especialista pensa:** Acolhe, identifica etapa da jornada e transforma emoção em próximo passo operacional.
**Estado detectado:** `STATE_ANXIOUS`
**Lacunas:** `GAP_CURRENT_NEED`, `GAP_EXAM_OR_STAGE`, `GAP_PATIENT_CONTACT`
**Risco principal:** `RISK_PATIENT_LOSS`
**Próximo objetivo:** `OBJECTIVE_RECOVER_OR_FAST_TRACK`
**Ação permitida positiva:** Acolher com objetividade, coletar contexto mínimo e encaminhar próximo passo ou humano.
**Ação de confiança:** Mostrar presença, método e próximo passo claro.
**Resultado esperado:** Paciente orientado, urgência operacional tratada ou caso recuperado.
---
### SIT_053 — ANSIEDADE_RECLAMACAO_URGENCIA
**Situação real:** É um exame difícil?
**Como o cliente pensa:** Busca acolhimento, solução rápida ou recuperação de confiança.
**Como o iniciante responde:** Responde de forma fria, defensiva ou clínica demais.
**Como o especialista pensa:** Acolhe, identifica etapa da jornada e transforma emoção em próximo passo operacional.
**Estado detectado:** `STATE_ANXIOUS`
**Lacunas:** `GAP_CURRENT_NEED`, `GAP_EXAM_OR_STAGE`, `GAP_PATIENT_CONTACT`
**Risco principal:** `RISK_PATIENT_LOSS`
**Próximo objetivo:** `OBJECTIVE_RECOVER_OR_FAST_TRACK`
**Ação permitida positiva:** Acolher com objetividade, coletar contexto mínimo e encaminhar próximo passo ou humano.
**Ação de confiança:** Mostrar presença, método e próximo passo claro.
**Resultado esperado:** Paciente orientado, urgência operacional tratada ou caso recuperado.
---
### SIT_054 — ANSIEDADE_RECLAMACAO_URGENCIA
**Situação real:** Fui mal atendido.
**Como o cliente pensa:** Busca acolhimento, solução rápida ou recuperação de confiança.
**Como o iniciante responde:** Responde de forma fria, defensiva ou clínica demais.
**Como o especialista pensa:** Acolhe, identifica etapa da jornada e transforma emoção em próximo passo operacional.
**Estado detectado:** `STATE_POST_SERVICE_PROBLEM`
**Lacunas:** `GAP_CURRENT_NEED`, `GAP_EXAM_OR_STAGE`, `GAP_PATIENT_CONTACT`
**Risco principal:** `RISK_PATIENT_LOSS`
**Próximo objetivo:** `OBJECTIVE_RECOVER_OR_FAST_TRACK`
**Ação permitida positiva:** Acolher com objetividade, coletar contexto mínimo e encaminhar próximo passo ou humano.
**Ação de confiança:** Mostrar presença, método e próximo passo claro.
**Resultado esperado:** Paciente orientado, urgência operacional tratada ou caso recuperado.
---
### SIT_055 — ANSIEDADE_RECLAMACAO_URGENCIA
**Situação real:** Meu exame atrasou.
**Como o cliente pensa:** Busca acolhimento, solução rápida ou recuperação de confiança.
**Como o iniciante responde:** Responde de forma fria, defensiva ou clínica demais.
**Como o especialista pensa:** Acolhe, identifica etapa da jornada e transforma emoção em próximo passo operacional.
**Estado detectado:** `STATE_POST_SERVICE_PROBLEM`
**Lacunas:** `GAP_CURRENT_NEED`, `GAP_EXAM_OR_STAGE`, `GAP_PATIENT_CONTACT`
**Risco principal:** `RISK_PATIENT_LOSS`
**Próximo objetivo:** `OBJECTIVE_RECOVER_OR_FAST_TRACK`
**Ação permitida positiva:** Acolher com objetividade, coletar contexto mínimo e encaminhar próximo passo ou humano.
**Ação de confiança:** Mostrar presença, método e próximo passo claro.
**Resultado esperado:** Paciente orientado, urgência operacional tratada ou caso recuperado.
---
### SIT_056 — ANSIEDADE_RECLAMACAO_URGENCIA
**Situação real:** Ninguém me respondeu no WhatsApp.
**Como o cliente pensa:** Busca acolhimento, solução rápida ou recuperação de confiança.
**Como o iniciante responde:** Responde de forma fria, defensiva ou clínica demais.
**Como o especialista pensa:** Acolhe, identifica etapa da jornada e transforma emoção em próximo passo operacional.
**Estado detectado:** `STATE_POST_SERVICE_PROBLEM`
**Lacunas:** `GAP_CURRENT_NEED`, `GAP_EXAM_OR_STAGE`, `GAP_PATIENT_CONTACT`
**Risco principal:** `RISK_PATIENT_LOSS`
**Próximo objetivo:** `OBJECTIVE_RECOVER_OR_FAST_TRACK`
**Ação permitida positiva:** Acolher com objetividade, coletar contexto mínimo e encaminhar próximo passo ou humano.
**Ação de confiança:** Mostrar presença, método e próximo passo claro.
**Resultado esperado:** Paciente orientado, urgência operacional tratada ou caso recuperado.
---