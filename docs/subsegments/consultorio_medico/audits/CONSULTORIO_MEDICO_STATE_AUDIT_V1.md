# CONSULTORIO_MEDICO_STATE_AUDIT_V1

## Objetivo

Determinar se NEEDS_VALIDATION representa um estado operacional independente ou apenas uma subetapa de NEEDS_INFORMATION.

Esta decisão impactará:

* Runtime Compact;
* Firestore;
* Snapshot;
* GPT-4o-mini;
* futuros subsegmentos de saúde.

---

# 1. Problema Observado

Estrutura atual:

NEEDS_DISCOVERY
↓
NEEDS_ACCESS_PATH
↓
NEEDS_INFORMATION
↓
READY_FOR_APPOINTMENT

A pesquisa mostrou situações recorrentes onde:

* as informações já foram coletadas;
* porém o paciente ainda não pode avançar.

Exemplos:

* convênio não validado;
* encaminhamento não confirmado;
* guia não verificada;
* retorno não identificado;
* teleconsulta não configurada;
* documentação não conferida.

---

# 2. Teste Conceitual

Pergunta:

O paciente já forneceu as informações necessárias?

Resposta:

SIM.

---

Pergunta:

O paciente já está apto para avançar?

Resposta:

NÃO.

---

Conclusão:

Existe uma etapa intermediária.

---

# 3. Exemplos Observados

## Exemplo 1

Paciente:

"Quero marcar consulta."

Informações coletadas:

* convênio;
* especialidade;
* retorno ou primeira consulta.

Situação:

Ainda é necessário verificar elegibilidade.

Resultado:

Não está em NEEDS_INFORMATION.

Também não está em READY_FOR_APPOINTMENT.

---

## Exemplo 2

Paciente:

"Fui encaminhado."

Informações coletadas:

* encaminhamento informado.

Situação:

Ainda é necessário verificar documentação.

Resultado:

Não está em NEEDS_INFORMATION.

Também não está em READY_FOR_APPOINTMENT.

---

## Exemplo 3

Paciente:

"Quero teleconsulta."

Informações coletadas:

* objetivo informado.

Situação:

Ainda é necessário validar requisitos do atendimento.

Resultado:

Existe etapa intermediária.

---

# 4. Definição Proposta

## NEEDS_INFORMATION

Objetivo:

Coletar informações faltantes.

Pergunta principal:

"O que ainda preciso saber?"

---

## NEEDS_VALIDATION

Objetivo:

Verificar se as condições para avançar estão satisfeitas.

Pergunta principal:

"Posso avançar com segurança?"

---

## READY_FOR_APPOINTMENT

Objetivo:

Permitir execução da próxima etapa.

Pergunta principal:

"Já pode seguir."

---

# 5. Compatibilidade com a Pesquisa

A pesquisa identificou repetidamente:

* convênios;
* autorizações;
* encaminhamentos;
* documentação;
* retorno;
* teleconsulta;
* requisitos prévios.

Todos exigem validação.

Nem todos exigem coleta adicional de informação.

Resultado:

Evidência favorável à existência de NEEDS_VALIDATION.

---

# 6. Compatibilidade com GPT-4o-mini

NEEDS_VALIDATION possui vantagem operacional.

Permite ao modelo raciocinar:

informação recebida
↓
verificar requisitos
↓
seguir

Sem misturar:

coleta
e
validação.

Resultado:

Compatível com snapshot compacto.

---

# 7. Impacto na Fábrica

Caso aprovado:

Fluxo passa a ser:

NEEDS_DISCOVERY
↓
NEEDS_ACCESS_PATH
↓
NEEDS_INFORMATION
↓
NEEDS_VALIDATION
↓
READY_FOR_APPOINTMENT

A mudança tende a beneficiar:

* Consultório Médico;
* Clínica de Exames;
* futuras especialidades médicas;
* futuros segmentos de saúde.

---

# 8. Conclusão

Resultado da auditoria:

NEEDS_VALIDATION apresenta evidência suficiente para ser tratado como estado operacional independente.

Justificativa:

A pesquisa demonstrou múltiplas situações onde:

* as informações já existem;
* porém ainda é necessário validar condições antes de avançar.

Decisão recomendada:

APROVAR NEEDS_VALIDATION como estado independente para a construção do Runtime Compact.
