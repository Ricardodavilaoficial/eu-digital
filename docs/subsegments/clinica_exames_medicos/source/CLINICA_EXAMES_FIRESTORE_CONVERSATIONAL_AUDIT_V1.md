# CLINICA_EXAMES_FIRESTORE_CONVERSATIONAL_AUDIT_V1

## Objetivo

Ajustar o Firestore da Clínica de Exames Médicos para uso real pelo MEI Robô em Vendas, Operação, GPT-4o-mini e fallback de WhatsApp.

O ajuste não altera a arquitetura do segmento. A pesquisa, Matrix, Canonical e Runtime permanecem aprovados.

O foco é traduzir o conhecimento já produzido para linguagem mais prática, positiva, determinística, conversada e reutilizável.

---

# Decisão central

O Firestore deve guardar o patrimônio completo do subsegmento.

O snapshot deve continuar enxuto.

Portanto, a Clínica pode ter campos mais ricos no Firestore, desde que o código continue selecionando o que será enviado ao GPT-4o-mini.

---

# micro_scene

## Status

REESCREVER.

## Problema atual

A microcena atual descreve a operação, mas não vende o ganho real do MEI Robô.

## Função correta

A microcena deve ser a demonstração comercial compacta do subsegmento.

Ela deve mostrar uma cena completa, prática e recorrente, onde o SEU MEI Robô executa uma tarefa que normalmente exigiria funcionário.

## Versão recomendada

Quando um paciente envia uma mensagem pelo WhatsApp para agendar um hemograma pelo convênio, o SEU MEI Robô confirma as condições necessárias para o exame e solicita a foto da carteirinha do plano, do pedido médico e do documento de identificação. Em seguida, preenche automaticamente a solicitação de autorização previamente configurada por você, envia o e-mail para a operadora e acompanha o retorno da aprovação. Assim que a autorização é recebida, o próprio MEI Robô apresenta os horários disponíveis, confirma o agendamento com o paciente pelo WhatsApp, formaliza a confirmação por e-mail e ainda envia um lembrete antes do exame. Tudo isso sem intervenção de funcionários, mantendo o mesmo padrão de atendimento, organização e empatia em cada contato.

---

# micro_scene_conversational

## Status

REESCREVER.

## Função correta

Mostrar ao GPT-4o-mini como o robô conversa no segmento, com linguagem prática, empática, objetiva e operacional.

## Versão recomendada

Quando o paciente chama no WhatsApp perguntando sobre exame, convênio, autorização, preparo, agendamento ou resultado, o MEI Robô responde de forma objetiva e conduz a conversa para uma ação concreta. Ele solicita pedido médico, carteirinha, documento, unidade desejada, data preferida ou protocolo quando essas informações forem necessárias. Quando houver convênio ou autorização, registra a pendência, acompanha o status cadastrado e informa o paciente sobre aprovação, negativa, complementação ou próximo horário disponível. Quando houver preparo, usa apenas as orientações cadastradas pela clínica. Quando houver resultado, orienta o canal oficial ou encaminha para a equipe se existir falha de acesso, atraso ou dado sensível. Sempre que a situação depender de validação humana, o robô organiza um resumo claro para a equipe continuar sem perder contexto.

---

# real_customer_situations

## Status

EXPANDIR.

## Problema atual

O campo está correto, mas genérico. A pesquisa revelou situações muito mais concretas.

## Versão recomendada

* paciente quer agendar exame
* paciente pergunta quanto custa o exame
* paciente pergunta se a clínica faz determinado exame
* paciente envia pedido médico pelo WhatsApp
* paciente tem vários exames no mesmo pedido
* paciente quer saber se precisa pedido médico
* paciente pergunta quais documentos precisa levar
* paciente pergunta se precisa levar documento com foto
* paciente pergunta se precisa levar carteirinha do convênio
* paciente pergunta se o convênio cobre o exame
* paciente pergunta se precisa autorização
* paciente quer saber se a autorização já saiu
* paciente informa que a autorização está em análise
* paciente informa que o convênio pediu mais documentos
* paciente informa que a autorização foi negada
* paciente pergunta se pode agendar enquanto aguarda autorização
* paciente pergunta se pode fazer particular mesmo tendo convênio
* paciente informa que fará pelo SUS
* paciente informa que foi encaminhado pelo posto
* paciente informa que aguarda regulação
* paciente pergunta se pode ir por ordem de chegada
* paciente pergunta se precisa agendar antes
* paciente pergunta qual unidade atende o exame
* paciente pergunta se tem horário hoje
* paciente pergunta se tem horário amanhã
* paciente quer remarcar exame
* paciente quer cancelar exame
* paciente informa que perdeu o horário
* paciente informa que chegou atrasado
* paciente pergunta se precisa jejum
* paciente pergunta quantas horas de jejum
* paciente pergunta se pode beber água
* paciente pergunta se pode tomar remédio
* paciente informa que tomou café
* paciente informa que perdeu as orientações de preparo
* paciente pergunta se precisa remarcar por causa do preparo
* paciente pergunta prazo do resultado
* paciente pergunta se o resultado já saiu
* paciente não consegue acessar o resultado
* paciente perdeu senha do resultado
* paciente informa que o resultado não apareceu
* paciente pergunta se pode retirar resultado presencialmente
* paciente pergunta se a clínica coleta em casa
* paciente pergunta se atende o bairro dele
* paciente pergunta se há taxa de coleta domiciliar
* paciente quer marcar coleta para familiar
* paciente informa que é idoso ou tem dificuldade de locomoção
* paciente diz que está preocupado
* paciente diz que o médico pediu urgência
* paciente reclama de atraso
* paciente reclama de falta de retorno
* paciente pede para falar com atendente

---

# common_intents

## Status

EXPANDIR COM CONTROLE.

## Versão recomendada

* agendar_exame
* perguntar_preco_exame
* verificar_se_faz_exame
* enviar_pedido_medico
* consultar_documentacao
* consultar_convenio
* consultar_cobertura_convenio
* perguntar_se_precisa_autorizacao
* consultar_status_autorizacao
* informar_autorizacao_aprovada
* informar_autorizacao_pendente
* informar_autorizacao_negada
* consultar_preparo
* consultar_jejum
* informar_falha_de_preparo
* reagendar_exame
* cancelar_exame
* perguntar_ordem_de_chegada
* consultar_unidade
* consultar_resultado
* recuperar_acesso_resultado
* consultar_prazo_resultado
* solicitar_coleta_domiciliar
* informar_fluxo_sus
* registrar_reclamacao
* pedir_urgencia
* falar_com_atendente

---

# segment_status_use_cases

## Status

EXPANDIR.

## Versão recomendada

* informar autorização pendente
* informar autorização em análise
* informar autorização aprovada
* informar autorização negada
* informar autorização com complementação solicitada
* informar documentação pendente
* informar pedido médico pendente
* informar carteirinha pendente
* informar documento de identificação pendente
* informar preparo pendente
* informar preparo enviado
* informar falha de preparo
* informar necessidade de remarcação por preparo
* informar agendamento pendente
* informar exame confirmado
* informar comparecimento por ordem de chegada
* informar fluxo SUS ou regulação pendente
* informar coleta domiciliar em validação
* informar coleta domiciliar confirmada
* informar resultado disponível
* informar resultado pendente
* informar falha de acesso ao resultado
* informar resultado atrasado
* informar necessidade de atendimento humano
* informar reclamação encaminhada para equipe

---

# operational_ritual

## Status

AJUSTAR LEVEMENTE.

## Versão recomendada

* paciente chama perguntando por exame, preço, preparo, convênio, autorização, agendamento, resultado, SUS, coleta domiciliar ou atendimento humano
* robô identifica o exame solicitado ou pede foto do pedido médico
* robô identifica a forma de acesso: particular, convênio, SUS, regulação, ordem de chegada, pré-agendamento ou coleta domiciliar
* robô solicita documentos necessários conforme a situação: pedido médico, carteirinha, documento de identificação, protocolo ou dados do paciente
* robô verifica autorização, preparo, unidade, agenda ou canal de resultado quando essas informações estiverem cadastradas
* robô executa o próximo passo disponível: solicitar documentos, registrar autorização, informar status, confirmar agendamento, enviar preparo, orientar resultado ou organizar coleta domiciliar
* robô encaminha para humano quando houver interpretação clínica, dado sensível, regra não cadastrada, pendência complexa, reclamação ou decisão fora da automação
* robô organiza resumo claro para a equipe continuar o atendimento sem perder contexto

---

# Conclusão

A Clínica de Exames Médicos está aprovada para geração de CLINICA_EXAMES_FIRESTORE_JSON_V2.json.

A V2 deve preservar a arquitetura atual e substituir apenas os campos conversacionais aprovados nesta auditoria.

Status final:

CLINICA_EXAMES_READY_FOR_FIRESTORE_JSON_V2
