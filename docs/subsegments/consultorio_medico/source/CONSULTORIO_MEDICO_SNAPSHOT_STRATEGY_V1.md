# CONSULTORIO_MEDICO_SNAPSHOT_STRATEGY_V1

## Objetivo

Determinar quais conhecimentos do Consultório Médico realmente precisam sobreviver até o Snapshot enviado ao GPT-4o-mini.

Este documento existe para evitar transportar informação de construção que não gera benefício operacional.

---

# 1. Princípio Fundamental

Nem tudo que é importante para construir o segmento é importante para o Snapshot.

Existem dois grupos distintos:

CONHECIMENTO DE CONSTRUÇÃO

e

CONHECIMENTO DE EXECUÇÃO

---

# 2. Conhecimento de Construção

Utilizado para:

* pesquisa;
* auditoria;
* validação;
* reutilização;
* governança da Fábrica.

Exemplos:

* pesquisas completas;
* auditorias;
* validações de componentes;
* hipóteses rejeitadas;
* comparações entre segmentos;
* documentos de decisão.

Importância:

Muito alta para a Fábrica.

Baixa para o Snapshot.

---

# 3. Conhecimento de Execução

Utilizado para:

* interpretar mensagens;
* decidir próximos passos;
* responder usuários;
* conduzir jornadas.

Importância:

Muito alta para o Snapshot.

---

# 4. O que Deve Chegar ao Snapshot

## Intenções

Exemplos:

* primeira consulta;
* retorno;
* reagendamento;
* cancelamento;
* teleconsulta;
* convênio;
* encaminhamento;
* documentação;
* informação operacional.

---

## Formas de acesso

Exemplos:

* particular;
* convênio;
* retorno;
* encaminhamento;
* teleconsulta;
* atendimento humano.

---

## Informações críticas

Exemplos:

* objetivo da consulta;
* retorno ou primeira consulta;
* convênio;
* encaminhamento;
* documentação;
* próximo passo.

---

## Riscos

Exemplos:

* no-show;
* documentação ausente;
* convênio inválido;
* retorno perdido;
* abandono;
* ansiedade.

---

## Ações

Exemplos:

* solicitar informação;
* orientar documentação;
* orientar acesso;
* orientar consulta;
* orientar retorno;
* orientar encaminhamento.

---

## Próximos passos

Sempre priorizar:

o que fazer agora.

---

# 5. O que Não Precisa Chegar ao Snapshot

* histórico da pesquisa;
* justificativas de auditoria;
* comparações de segmentos;
* análises de recorrência;
* documentação da Fábrica;
* decisões arquiteturais.

Esses elementos devem permanecer na documentação.

---

# 6. Artefatos com Maior Valor para Snapshot

## specialist_reasoning_matrix

Alta prioridade.

Define como interpretar situações.

---

## runtime_compact

Alta prioridade.

Define comportamento operacional.

---

## real_customer_situations

Alta prioridade.

Fornece exemplos observáveis.

---

## micro_scene

Prioridade média.

Fortalece contexto mental.

---

## micro_scene_conversational

Prioridade muito alta.

Pode atuar diretamente em respostas de fallback.

---

# 7. Micro Scene Conversational

Critério especial.

Considerar que o conteúdo pode ser utilizado diretamente pelo usuário final.

Portanto escrever usando:

* linguagem humana;
* linguagem conversacional;
* acolhimento;
* clareza;
* objetividade;
* condução.

Pensar em:

WhatsApp

e não em:

documentação.

---

# 8. Regra para Conteúdo Conversacional

Transformar:

informação
↓
orientação

explicação
↓
condução

dúvida
↓
próximo passo

---

# 9. Compressão Recomendada

Pesquisa
↓
Research Synthesis
↓
Canonical Model
↓
Reasoning Model
↓
Runtime Compact
↓
Snapshot

A cada etapa reduzir complexidade e aumentar operacionalidade.

---

# 10. Regra de Ouro

Pergunta obrigatória antes de incluir qualquer informação no Firestore:

"Esta informação ajuda o GPT-4o-mini a decidir, orientar ou conduzir?"

Se a resposta for:

SIM

pode sobreviver.

Se a resposta for:

NÃO

deve permanecer apenas na documentação da Fábrica.

---

# 11. Conclusão

O Snapshot deve carregar:

* intenções;
* estados;
* riscos;
* ações;
* próximos passos;
* situações observáveis;
* conteúdo conversacional útil.

O Snapshot não deve carregar conhecimento de construção.

O objetivo é maximizar utilidade operacional com o menor volume possível.
