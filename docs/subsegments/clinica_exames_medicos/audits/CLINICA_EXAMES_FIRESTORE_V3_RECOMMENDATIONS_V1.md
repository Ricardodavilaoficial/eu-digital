# CLINICA_EXAMES_FIRESTORE_V3_RECOMMENDATIONS_V1

## Objetivo

Definir recomendações para eventual construção do Firestore V3 da Clínica de Exames Médicos.

Este documento não autoriza alterações imediatas.

Seu objetivo é orientar futuras evoluções preservando compatibilidade com:

* GPT-4o-mini;
* fallback WhatsApp;
* runtime compacto;
* governança da Fábrica;
* arquitetura atual.

---

# Conclusão Principal

A auditoria conclui que o Firestore V2 possui estrutura adequada.

Não foi identificada necessidade de:

* nova coleção;
* novo componente;
* novo runtime;
* nova arquitetura.

A principal oportunidade de evolução encontra-se no enriquecimento qualitativo do patrimônio operacional já existente.

---

# Blocos Que Devem Permanecer Inalterados

## Estrutura Geral

Manter:

* segment_id
* archetype_id
* conversation_mode
* customer_noun
* service_noun
* conversion_noun
* primary_goal

---

## Catálogo

Manter:

* keywords
* negative_keywords
* catalog_groups

---

## Capacidades

Manter:

* preferred_capabilities

---

## Runtime

Manter:

* runtime_compact
* core_sequence
* main_states
* main_risks

Nenhuma alteração recomendada nesta auditoria.

---

# Blocos Que Merecem Evolução

## real_customer_situations

Este é o principal candidato à evolução.

Motivo:

Hoje registra situações reais observadas.

Entretanto ainda registra predominantemente:

* ocorrência;
* evento;
* problema.

A auditoria recomenda capturar também:

* objetivo do especialista;
* condução esperada;
* próximo passo;
* lógica de escalada.

---

# Modelo Recomendado

Modelo conceitual:

Situação

↓

Objetivo

↓

Condução

↓

Próximo Passo

↓

Escalada

---

Exemplo Conceitual

Situação:

Paciente perdeu senha do resultado.

Objetivo:

Restabelecer acesso ao resultado.

Condução:

Assumir responsabilidade pela continuidade.

Próximo Passo:

Iniciar recuperação de acesso.

Escalada:

Responsável interno quando não houver recuperação automática.

---

# Priorização de Situações

Prioridade Alta

Situações com:

* risco de perda de paciente;
* risco de abandono;
* risco de reclamação;
* risco de venda perdida;
* ansiedade elevada.

Exemplos:

* autorização negada;
* autorização pendente;
* perdeu senha;
* resultado indisponível;
* atraso;
* urgência;
* reclamação;
* reagendamento.

---

Prioridade Média

Situações relacionadas a:

* documentação;
* convênio;
* preparo;
* cobertura.

---

Prioridade Baixa

Situações puramente informativas.

---

# micro_scene

Recomendação:

Auditar representatividade.

Pergunta orientadora:

A micro_scene representa a missão principal da Clínica ou apenas um fluxo relevante?

Caso seja mantida:

Nenhuma ação necessária.

Caso seja revisada:

Priorizar representação da jornada completa do paciente.

---

# micro_scene_conversational

Recomendação:

Manter.

A auditoria considera o bloco alinhado com:

* demonstração comercial;
* apresentação do especialista digital;
* linguagem natural.

Não utilizar como resposta pronta.

Utilizar apenas como contexto conversacional.

---

# operational_ritual

Recomendação:

Manter.

O bloco encontra-se compatível com a pesquisa realizada.

Representa adequadamente o fluxo operacional observado.

---

# operational_rules

Recomendação:

Fortalecer princípios já existentes.

Especial atenção para:

* assumir condução;
* apresentar próximo passo;
* preservar continuidade.

---

# segment_status_use_cases

Recomendação:

Manter.

Estrutura adequada.

Pode receber exemplos futuros, mas não demanda revisão estrutural.

---

# Princípios Consolidados

## Continuidade

Enquanto existir alternativa operacional válida, a jornada continua.

---

## Próximo Passo

Nunca entregar um problema sem entregar um próximo passo.

---

## Condução

O usuário deve perceber que alguém assumiu a situação.

---

## Confiança

A confiança nasce da condução.

Não da quantidade de informação.

---

## Empatia

A empatia é a estrada que leva até a confiança.

---

## Venda

Vender não é encurralar.

Vender é mostrar a luz.

---

# Critério de Aprovação para V3

Uma alteração só deve entrar no Firestore V3 se:

* melhorar a condução;
* melhorar a capacidade de resolução;
* melhorar a compatibilidade com GPT-4o-mini;
* melhorar fallback WhatsApp;
* preservar simplicidade operacional.

---

# Recomendação Final

A Clínica de Exames Médicos encontra-se madura para servir como referência da Fábrica.

A evolução recomendada não é estrutural.

A evolução recomendada é comportamental.

O próximo estágio consiste em transformar situações observadas em patrimônio de condução profissional, permitindo que o MEI Robô se aproxime cada vez mais do comportamento de especialistas experientes sem perder compatibilidade operacional.
