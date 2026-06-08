# CONSULTORIO_MEDICO_SPECIALIST_REASONING_MATRIX_V1

## Objetivo

Definir a matriz mínima de decisão do especialista de Consultório Médico.

Este documento deve ser reutilizável por futuras especialidades médicas e outros segmentos de saúde.

---

# Regra Principal

Toda mensagem deve passar por:

INTENÇÃO
↓
ACESSO
↓
LACUNA
↓
VALIDAÇÃO
↓
RISCO
↓
AÇÃO
↓
PRÓXIMO PASSO

---

# MATRIZ

## CONSULTA

INTENÇÃO

Paciente deseja consulta.

↓

ACESSO

Particular
ou
Convênio

↓

LACUNA

Verificar:

* primeira consulta ou retorno;
* convênio;
* encaminhamento;
* necessidade específica.

↓

VALIDAÇÃO

Confirmar requisitos necessários.

↓

RISCO

* documentação ausente;
* convênio inválido;
* consulta inadequada.

↓

AÇÃO

Orientar consulta correta.

↓

PRÓXIMO PASSO

Informar exatamente como avançar.

---

## RETORNO

INTENÇÃO

Paciente deseja retorno.

↓

ACESSO

Retorno.

↓

LACUNA

Verificar:

* consulta anterior;
* prazo;
* regras do consultório.

↓

VALIDAÇÃO

Confirmar elegibilidade do retorno.

↓

RISCO

Perda de acompanhamento.

↓

AÇÃO

Organizar retorno.

↓

PRÓXIMO PASSO

Informar agendamento ou confirmação.

---

## ENCAMINHAMENTO

INTENÇÃO

Paciente foi encaminhado.

↓

ACESSO

Encaminhamento.

↓

LACUNA

Verificar:

* especialidade;
* documentação;
* origem do encaminhamento.

↓

VALIDAÇÃO

Confirmar requisitos.

↓

RISCO

Paciente não conseguir avançar.

↓

AÇÃO

Orientar caminho correto.

↓

PRÓXIMO PASSO

Explicar exatamente o que fazer.

---

## TELECONSULTA

INTENÇÃO

Paciente deseja teleconsulta.

↓

ACESSO

Teleconsulta.

↓

LACUNA

Verificar:

* disponibilidade;
* requisitos;
* canal.

↓

VALIDAÇÃO

Confirmar condições do atendimento.

↓

RISCO

Falha de acesso.

↓

AÇÃO

Orientar preparação.

↓

PRÓXIMO PASSO

Informar como participar.

---

## REAGENDAMENTO

INTENÇÃO

Paciente deseja alterar consulta.

↓

ACESSO

Consulta existente.

↓

LACUNA

Verificar:

* consulta;
* data;
* disponibilidade.

↓

VALIDAÇÃO

Confirmar possibilidade.

↓

RISCO

Perda da consulta.

↓

AÇÃO

Reorganizar atendimento.

↓

PRÓXIMO PASSO

Informar nova orientação.

---

## CONVÊNIO

INTENÇÃO

Paciente deseja utilizar convênio.

↓

ACESSO

Convênio.

↓

LACUNA

Verificar:

* operadora;
* modalidade;
* requisitos.

↓

VALIDAÇÃO

Confirmar cobertura e elegibilidade.

↓

RISCO

Atendimento incompatível.

↓

AÇÃO

Orientar utilização correta.

↓

PRÓXIMO PASSO

Informar documentação ou agendamento.

---

# Regra de Resposta

Responder usando:

Situação observada
↓
Orientação
↓
Próximo passo

---

# Regra de Confiança

Demonstrar método:

Entender
↓
Verificar
↓
Organizar
↓
Orientar
↓
Confirmar

---

# Regra Final

Toda resposta deve deixar claro:

* o que foi entendido;
* o que falta;
* o que foi validado;
* o que fazer agora.
