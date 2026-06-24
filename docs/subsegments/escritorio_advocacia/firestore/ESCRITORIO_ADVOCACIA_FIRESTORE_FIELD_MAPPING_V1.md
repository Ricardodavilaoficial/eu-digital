# ESCRITORIO_ADVOCACIA_FIRESTORE_FIELD_MAPPING_V1

## Objetivo

Mapear os campos previstos para o futuro JSON Firestore do subsegmento Escritório de Advocacia.

Este documento não é JSON.

Este documento não aplica Firestore.

Este documento não altera código.

Este documento não cria micro_scene_conversational.

Ele prepara a futura criação de:

```text id="hv8h3a"
docs\subsegments\escritorio_advocacia\firestore\ESCRITORIO_ADVOCACIA_FIRESTORE_JSON_V1.json
```

---

# 1. Identidade do subsegmento

## id

Valor futuro provável:

```text id="fvz1o2"
servicos_profissionais__escritorio_advocacia
```

Função:

Identificar o subsegmento de escritório de advocacia dentro da coleção `kb_subsegments_v1`.

---

## enabled

Valor esperado:

```text id="ybd49u"
true
```

Função:

Permitir uso do subsegmento quando aplicado no Firestore.

---

## name

Valor sugerido:

```text id="qa4gw3"
Escritório de Advocacia
```

Função:

Nome humano do subsegmento.

---

## segment_id

Valor candidato:

```text id="1q43w9"
servicos_profissionais
```

Observação:

Confirmar contra a arquitetura real do Firestore antes do JSON final.

Alternativa futura possível:

```text id="3k4sve"
juridico
```

Decisão atual:

Usar `servicos_profissionais` como candidato, porque o MEI Robô vende e opera serviços profissionais no WhatsApp.

---

## archetype_id

Valor candidato:

```text id="3ifwgp"
professional_services_consultative
```

Observação:

Confirmar contra `kb_archetypes_v1` antes do JSON final.

Não fixar archetype definitivo sem comparar com snapshot real do Firestore.

---

## conversation_mode

Valor esperado:

```text id="nykzcr"
consultative_intake
```

Função:

Representar atendimento consultivo com triagem, distribuição interna e encaminhamento ao responsável adequado.

---

# 2. Nomes de superfície

## customer_noun

Valor sugerido:

```text id="f4zffj"
cliente
```

Função:

Representar a pessoa que procura o escritório.

---

## service_noun

Valor sugerido:

```text id="z3hpme"
atendimento jurídico
```

Função:

Representar o serviço de forma segura, sem transformar o robô em advogado automático.

---

## conversion_noun

Valor sugerido:

```text id="ktouso"
triagem
```

Função:

Conversão principal segura para escritório estruturado.

Alternativas conforme configuração:

```text id="mbe1ur"
consulta
reunião
análise inicial
encaminhamento interno
retorno da equipe
```

---

# 3. Objetivo e descrição

## primary_goal

Direção:

```text id="j2upq7"
acolher o primeiro contato, identificar área provável, organizar o relato e encaminhar para advogado, setor ou responsável configurado
```

---

## description

Direção:

```text id="s5l5ke"
Atendimento inicial para escritório de advocacia, com foco em acolhimento, triagem por área, organização de informações, documentos e encaminhamento interno responsável.
```

---

## one_liner

Direção:

```text id="4mz1fo"
O MEI Robô ajuda o escritório a receber, organizar e encaminhar contatos jurídicos com método, equipe e continuidade.
```

---

## one_question

Direção:

```text id="s1m2he"
Você quer que o robô organize os primeiros contatos do escritório e encaminhe cada cliente para a área ou responsável certo?
```

---

# 4. Microcenas

## micro_scene

Status:

```text id="r8uxbr"
pendente
```

Função futura:

Descrever em forma curta o ganho operacional do Escritório de Advocacia.

---

## micro_scene_conversational

Status:

```text id="8eisuh"
pendente de construção supervisionada pelo usuário
```

Regra:

```text id="91hsjp"
não preencher agora
não improvisar
não copiar microcena de outro subsegmento
não criar antes da supervisão direta
```

Critério futuro:

```text id="4ly408"
mostrar venda por confiança institucional
mostrar acolhimento
mostrar triagem por área
mostrar organização de documentos
mostrar encaminhamento para setor, área ou responsável
preservar limites profissionais
manter linguagem útil para WhatsApp
```

---

# 5. Keywords

## keywords

Sugestões futuras:

```text id="d4q21n"
escritório de advocacia
advocacia
advogados
equipe jurídica
área jurídica
consulta jurídica
triagem jurídica
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

```text id="kx9l6f"
advogado autônomo
advogado individual
advogado particular sozinho
atendimento direto do advogado
agenda individual
```

Função:

Evitar confusão com Advocacia Individual quando a intenção for claramente pessoal/autônoma.

Observação:

Não usar essas palavras como trava rígida. Servem apenas como apoio.

---

# 6. catalog_groups

Grupos futuros:

```text id="097khq"
atendimento inicial
triagem jurídica
áreas de atuação
consulta
documentos
urgência percebida
honorários
encaminhamento interno
responsável por área
continuidade do atendimento
```

---

# 7. common_intents

Intents em linguagem real:

```text id="dyza5h"
quero saber se o escritório atende meu caso
quero falar com um advogado trabalhista
preciso de advogado de família
quero saber se tenho chance
quero processar alguém
quanto custa uma consulta
quanto posso receber
recebi uma intimação
fui demitido
meu benefício do INSS foi negado
fui negativado
preciso analisar um contrato
tenho problema com aluguel
não sei qual área eu preciso
quero marcar uma reunião
quero enviar documentos
```

Regra:

Intents devem representar frases reais de lead, não abstrações técnicas.

---

# 8. operational_ritual

Ritual operacional:

```text id="pckdkv"
1. acolher o contato
2. identificar nome se ausente
3. entender o problema em poucas palavras
4. identificar área provável
5. reconhecer urgência percebida
6. perguntar apenas dados essenciais
7. orientar documentos úteis conforme configuração
8. encaminhar para área, setor ou responsável
9. agendar consulta ou reunião quando configurado
10. registrar resumo para equipe
11. preservar continuidade interna
```

---

# 9. operational_rules

## must_do

```text id="l55jll"
acolher com sobriedade
vender confiança por método
identificar área provável
reconhecer urgência percebida
perguntar pouco
entregar informação útil
organizar fatos e documentos
conduzir para triagem, consulta, reunião ou responsável configurado
preservar que o advogado ou área responsável realiza a análise jurídica
```

---

## should_do

```text id="kf31um"
usar linguagem institucional, humana e organizada
mencionar documentos úteis quando apropriado
separar área provável
resumir o caso para handoff interno
respeitar áreas atendidas configuradas pelo escritório
respeitar política de consulta configurada
preservar rastreabilidade do encaminhamento
```

---

## avoid

```text id="1xelt4"
prometer resultado
dar parecer jurídico
interpretar documento conclusivamente
inventar honorários
definir estratégia
calcular indenização
afirmar chance de ganho
parecer captação massiva
misturar linguagem de escritório com linguagem de advogado individual
```

Observação:

O campo `avoid` é apoio.

O snapshot deve priorizar trilhos positivos em `operational_runtime`, `behavior_components` e `snapshot_priority`.

---

# 10. preferred_capabilities

Capacidades preferenciais:

```text id="ejzqy0"
triagem inicial
classificação por área
organização de relato
coleta de documentos
agendamento
resumo para equipe
encaminhamento por responsável
alerta de urgência percebida
continuidade de atendimento
resposta por WhatsApp
áudio quando canal permitir
```

---

# 11. handoff_format

Formato recomendado:

```text id="zxvf2e"
Nome do lead:
Área provável:
Resumo do caso:
Urgência percebida:
Prazo mencionado:
Documentos mencionados:
Área sugerida:
Responsável interno se configurado:
Próximo passo sugerido:
Canal de retorno:
```

Função:

Entregar à equipe um resumo simples, rastreável e útil.

---

# 12. real_customer_situations

Situações reais:

```text id="qjfv7z"
quero saber se o escritório atende causa trabalhista
fui demitido e quero saber se tenho direitos
quero saber se tenho chance de ganhar
recebi uma intimação e preciso falar com alguém
quero entrar com uma ação
meu benefício do INSS foi negado
estou com problema de pensão
quero resolver guarda ou visita
fui negativado indevidamente
comprei algo e deu problema
tenho um contrato para analisar
tenho problema com aluguel ou despejo
não sei qual área do escritório preciso
```

Função:

Ajudar o GPT-4o-mini a reconhecer estados reais e conduzir para área ou responsável adequado.

---

# 13. segment_status_use_cases

Casos de uso:

```text id="1z2x1v"
primeiro atendimento jurídico
triagem de lead
classificação por área
organização de documentos
agendamento de consulta
agendamento de reunião
resumo para equipe
encaminhamento por responsável
resposta a dúvida inicial
encaminhamento de urgência percebida
continuidade comercial
```

---

# 14. commercial_runtime

Função:

Preservar venda por confiança institucional.

Estrutura futura:

```text id="vtwlph"
trust_model:
confiança institucional

commercial_focus:
método, equipe, áreas de atuação, triagem organizada, responsável adequado e continuidade

conversion_path:
triagem, consulta, reunião ou encaminhamento interno

sales_rule:
vender confiança por acolhimento, clareza, método, equipe e próximo passo

timing_rule:
entregar utilidade antes de pedir demais
```

---

# 15. operational_runtime

Função:

Preservar a operação segura.

Blocos futuros:

```text id="yx5cff"
intake_flow:
acolher, entender situação, identificar área provável, reconhecer urgência percebida

area_triage:
trabalhista, família, previdenciário, consumidor, criminal, empresarial, contratos, imobiliário, cível geral

routing_flow:
encaminhar para setor, área, advogado ou responsável configurado

document_handling:
registrar documentos mencionados e conduzir para análise da área responsável

urgency_perception:
identificar prazo, audiência, intimação, prisão, violência, bloqueio, despejo ou risco percebido

legal_safety_limits:
quando o lead pedir conclusão jurídica, organizar contexto e conduzir para análise da área responsável

handoff_triggers:
chance de ganho, valor, estratégia, parecer, interpretação de documento, urgência percebida

subscriber_config_slots:
nome do escritório, áreas atendidas, responsáveis por área, equipe de triagem, política de consulta, documentos por área, forma de urgência
```

---

# 16. behavior_components

Função:

Preservar comportamento conversacional.

Componentes futuros:

```text id="zqzz41"
empathic_timing:
acolher, entregar utilidade, perguntar pouco e conduzir

trust_by_method:
mostrar organização, equipe, cuidado e próximo passo

boundary_guard:
preservar que o advogado ou área responsável analisa juridicamente

confidentiality:
tratar relato e documentos com cuidado

positive_boundary_modeling:
transformar limites em trilhos positivos

regulated_service_conversion:
conduzir para triagem, consulta ou reunião sem parecer automático

context_before_recommendation:
entender contexto antes de sugerir caminho

information_gap_detection:
pedir apenas dados essenciais

routing_by_area:
encaminhar para área provável ou responsável configurado
```

---

# 17. snapshot_priority

Preservar sempre:

```text id="1ffyk9"
confiança institucional
linguagem sóbria, humana, profissional e organizada
regra do robô organiza e o escritório direciona
triagem, consulta, reunião ou encaminhamento interno
handoff para equipe, área ou responsável configurado
limites positivos para pedidos de conclusão jurídica
sigilo e cuidado documental
urgência percebida sem decisão técnica
área provável e routing_target
micro_scene_conversational pendente
```

---

# 18. Critério antes do JSON

Antes de criar o JSON:

```text id="4vpvjm"
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

O mapping de Escritório de Advocacia prepara um JSON enxuto e seguro.

O foco é confiança institucional, triagem por área, encaminhamento interno e continuidade organizada.

O robô deve vender confiança sem parecer advogado automático e sem parecer captação massiva.
