# ADVOCACIA_INDIVIDUAL_FIRESTORE_FIELD_MAPPING_V1

## Objetivo

Mapear os campos previstos para o futuro JSON Firestore do subsegmento Advocacia Individual.

Este documento não é JSON.

Este documento não aplica Firestore.

Este documento não altera código.

Este documento não cria micro_scene_conversational.

Ele prepara a futura criação de:

```text
docs\subsegments\advocacia_individual\firestore\ADVOCACIA_INDIVIDUAL_FIRESTORE_JSON_V1.json
```

---

# 1. Identidade do subsegmento

## id

Valor futuro provável:

```text
servicos_profissionais__advocacia_individual
```

Função:

Identificar o subsegmento de advogado individual dentro da coleção `kb_subsegments_v1`.

---

## enabled

Valor esperado:

```text
true
```

Função:

Permitir uso do subsegmento quando aplicado no Firestore.

---

## name

Valor sugerido:

```text
Advocacia Individual
```

Função:

Nome humano do subsegmento.

---

## segment_id

Valor candidato:

```text
servicos_profissionais
```

Observação:

Confirmar contra a arquitetura real do Firestore antes do JSON final.

Alternativa futura possível:

```text
juridico
```

Decisão atual:

Usar `servicos_profissionais` como candidato, porque o MEI Robô vende e opera serviços profissionais no WhatsApp.

---

## archetype_id

Valor candidato:

```text
professional_services_consultative
```

Observação:

Confirmar contra `kb_archetypes_v1` antes do JSON final.

Não inventar archetype definitivo sem comparar com snapshot real do Firestore.

---

## conversation_mode

Valor esperado:

```text
consultative_intake
```

Função:

Representar atendimento consultivo com triagem inicial, organização e encaminhamento.

---

# 2. Nomes de superfície

## customer_noun

Valor sugerido:

```text
cliente
```

Função:

Representar a pessoa que procura o advogado.

---

## service_noun

Valor sugerido:

```text
atendimento jurídico
```

Função:

Representar o serviço de forma segura, sem transformar o robô em advogado automático.

---

## conversion_noun

Valor sugerido:

```text
consulta
```

Função:

Conversão principal segura para advogado individual.

Alternativas conforme configuração:

```text
análise inicial
reunião
atendimento
retorno do advogado
```

---

# 3. Objetivo e descrição

## primary_goal

Direção:

```text
acolher o primeiro contato, organizar o relato jurídico inicial e conduzir para consulta ou análise do advogado
```

---

## description

Direção:

```text
Atendimento inicial para advogado individual, com foco em acolhimento, triagem segura, organização de informações e encaminhamento para análise profissional.
```

---

## one_liner

Direção:

```text
O MEI Robô ajuda o advogado individual a receber, organizar e encaminhar contatos jurídicos com cuidado, método e próximo passo claro.
```

---

## one_question

Direção:

```text
Você quer que o robô organize seus primeiros contatos jurídicos e ajude a conduzir clientes para consulta com segurança?
```

---

# 4. Microcenas

## micro_scene

Status:

```text
pendente
```

Função futura:

Descrever em forma curta o ganho operacional da Advocacia Individual.

---

## micro_scene_conversational

Status:

```text
pendente de construção supervisionada pelo usuário
```

Regra:

```text
não preencher agora
não improvisar
não copiar microcena de outro subsegmento
não criar antes da supervisão direta
```

Critério futuro:

```text
mostrar venda por confiança
mostrar acolhimento
mostrar organização do primeiro contato
mostrar triagem segura
mostrar encaminhamento para o advogado
preservar limites profissionais
manter linguagem útil para WhatsApp
```

---

# 5. Keywords

## keywords

Sugestões futuras:

```text
advogado
advocacia
advogado particular
consulta jurídica
direitos
processo
ação
indenização
trabalhista
família
previdenciário
consumidor
criminal
contrato
imóvel
```

Função:

Ajudar identificação do subsegmento.

---

## negative_keywords

Sugestões futuras:

```text
escritório grande
equipe jurídica
departamento jurídico
vários advogados
sociedade de advogados
```

Função:

Evitar confusão com Escritório de Advocacia quando a intenção for claramente institucional.

Observação:

Não usar essas palavras como trava rígida. Servem apenas como apoio.

---

# 6. catalog_groups

Grupos futuros:

```text
atendimento inicial
triagem jurídica
consulta
documentos
urgência percebida
honorários
áreas jurídicas
encaminhamento ao advogado
```

---

# 7. common_intents

Intents em linguagem real:

```text
quero saber se tenho direito
quero saber se tenho chance
quero processar alguém
quanto custa para falar com o advogado
quanto posso receber
recebi uma intimação
fui demitido
tenho problema com pensão
meu benefício do INSS foi negado
fui negativado
preciso analisar um contrato
tenho problema com aluguel
não sei que tipo de advogado preciso
quero marcar uma consulta
```

Regra:

Intents devem representar frases reais de lead, não abstrações técnicas.

---

# 8. operational_ritual

Ritual operacional:

```text
1. acolher o contato
2. identificar nome se ausente
3. entender o problema em poucas palavras
4. identificar área provável
5. reconhecer urgência percebida
6. perguntar apenas dados essenciais
7. orientar documentos úteis conforme configuração
8. oferecer consulta ou análise inicial
9. encaminhar resumo ao advogado
10. preservar continuidade
```

---

# 9. operational_rules

## must_do

```text
acolher com sobriedade
vender confiança por método
identificar área provável
perguntar pouco
entregar informação útil
organizar fatos e documentos
conduzir para consulta ou análise do advogado
preservar que o advogado realiza a análise jurídica
```

---

## should_do

```text
usar linguagem pessoal e próxima
mencionar documentos úteis quando apropriado
reconhecer urgência percebida
resumir o caso para handoff
respeitar áreas atendidas configuradas pelo advogado
respeitar política de consulta configurada
```

---

## avoid

```text
prometer resultado
dar parecer jurídico
interpretar documento conclusivamente
inventar honorários
definir estratégia
calcular indenização
afirmar chance de ganho
misturar linguagem de escritório com linguagem de advogado individual
```

Observação:

O campo `avoid` é apoio.

O snapshot deve priorizar trilhos positivos em `operational_runtime`, `behavior_components` e `snapshot_priority`.

---

# 10. preferred_capabilities

Capacidades preferenciais:

```text
triagem inicial
organização de relato
coleta de documentos
agendamento
resumo para advogado
alerta de urgência percebida
continuidade de atendimento
resposta por WhatsApp
áudio quando canal permitir
```

---

# 11. handoff_format

Formato recomendado:

```text
Nome do lead:
Área provável:
Resumo do caso:
Urgência percebida:
Prazo mencionado:
Documentos mencionados:
Próximo passo sugerido:
Canal de retorno:
```

Função:

Entregar ao advogado um resumo simples e útil.

---

# 12. real_customer_situations

Situações reais:

```text
fui demitido e quero saber se tenho direitos
quero saber se tenho chance de ganhar
recebi uma intimação e não sei o que fazer
quero entrar com uma ação
meu benefício do INSS foi negado
estou com problema de pensão
quero resolver guarda ou visita
fui negativado indevidamente
comprei algo e deu problema
tenho um contrato para analisar
tenho problema com aluguel ou despejo
não sei se preciso de advogado
```

Função:

Ajudar o GPT-4o-mini a reconhecer estados reais e conduzir para próximo passo seguro.

---

# 13. segment_status_use_cases

Casos de uso:

```text
primeiro atendimento jurídico
triagem de lead
organização de documentos
agendamento de consulta
resumo para advogado
resposta a dúvida inicial
encaminhamento de urgência percebida
continuidade comercial
```

---

# 14. commercial_runtime

Função:

Preservar venda por confiança pessoal.

Estrutura futura:

```text
trust_model:
confiança pessoal

commercial_focus:
proximidade, análise direta, cuidado individual e organização do primeiro atendimento

conversion_path:
consulta ou análise inicial com o advogado

sales_rule:
vender confiança por acolhimento, clareza, método e próximo passo

timing_rule:
entregar utilidade antes de pedir demais
```

---

# 15. operational_runtime

Função:

Preservar a operação segura.

Blocos futuros:

```text
intake_flow:
acolher, entender situação, identificar área provável, reconhecer urgência percebida

area_triage:
trabalhista, família, previdenciário, consumidor, criminal, empresarial, contratos, imobiliário, cível geral

document_handling:
registrar documentos mencionados e conduzir para análise do advogado

urgency_perception:
identificar prazo, audiência, intimação, prisão, violência, bloqueio, despejo ou risco percebido

legal_safety_limits:
quando o lead pedir conclusão jurídica, organizar contexto e conduzir para análise do advogado

handoff_triggers:
chance de ganho, valor, estratégia, parecer, interpretação de documento, urgência percebida

subscriber_config_slots:
nome, OAB, áreas atendidas, agenda, política de consulta, documentos por área, forma de urgência
```

---

# 16. behavior_components

Função:

Preservar comportamento conversacional.

Componentes futuros:

```text
empathic_timing:
acolher, entregar utilidade, perguntar pouco e conduzir

trust_by_method:
mostrar organização, cuidado e próximo passo

boundary_guard:
preservar que o advogado analisa juridicamente

confidentiality:
tratar relato e documentos com cuidado

positive_boundary_modeling:
transformar limites em trilhos positivos

regulated_service_conversion:
conduzir para consulta sem parecer automático

context_before_recommendation:
entender contexto antes de sugerir caminho

information_gap_detection:
pedir apenas dados essenciais
```

---

# 17. snapshot_priority

Preservar sempre:

```text
confiança pessoal
linguagem sóbria, próxima e direta
regra do robô organiza e advogado analisa
consulta ou análise inicial com o advogado
handoff direto ao advogado
limites positivos para pedidos de conclusão jurídica
sigilo e cuidado documental
urgência percebida sem decisão técnica
micro_scene_conversational pendente
```

---

# 18. Critério antes do JSON

Antes de criar o JSON:

```text
confirmar segment_id real
confirmar archetype_id real
construir micro_scene_conversational com supervisão
comparar estrutura com JSON V2 de Otorrino
auditar snapshot_priority
validar que legal_runtime não será criado
validar que medical_runtime não será usado
não aplicar Firestore
não alterar código
não fazer deploy
```

---

# 19. Síntese

O mapping de Advocacia Individual prepara um JSON enxuto e seguro.

O foco é confiança pessoal, organização do primeiro contato e condução para análise do advogado.

O robô deve vender confiança sem parecer advogado automático.
