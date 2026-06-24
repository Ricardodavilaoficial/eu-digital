# ADVOCACIA_FIRESTORE_MAPPING_DECISION_V1

## Objetivo

Registrar a decisão de mapeamento Firestore para Advocacia antes da criação de qualquer JSON.

Este documento não cria JSON.

Este documento não aplica Firestore.

Este documento não altera código.

Este documento não cria micro_scene_conversational.

Ele fixa a direção de estrutura para os futuros JSONs:

```text id="67yqnq"
ADVOCACIA_INDIVIDUAL_FIRESTORE_JSON_V1.json
ESCRITORIO_ADVOCACIA_FIRESTORE_JSON_V1.json
```

---

# 1. Diagnóstico do padrão de referência

O subsegmento Consultório Médico — Otorrinolaringologia possui documentos de mapeamento Firestore e um JSON V2 de referência.

Os arquivos de mapping mostram a estrutura clássica:

```text id="tylrrc"
id
name
segment_id
archetype_id
conversation_mode
customer_noun
service_noun
conversion_noun
primary_goal
description
one_liner
one_question
micro_scene
micro_scene_conversational
keywords
negative_keywords
common_intents
operational_ritual
handoff_format
preferred_capabilities
real_customer_situations
operational_rules
segment_status_use_cases
```

O JSON V2 de Otorrino confirma também a presença dos campos avançados:

```text id="e7y6wd"
commercial_runtime
operational_runtime
medical_runtime
behavior_components
snapshot_priority
```

Decisão:

```text id="s83v54"
Advocacia deve seguir a estrutura V2 preservada no JSON,
não apenas os mappings antigos.
```

---

# 2. Decisão central

Advocacia terá dois JSONs Firestore futuros.

```text id="1qrhzz"
servicos_profissionais__advocacia_individual
servicos_profissionais__escritorio_advocacia
```

Motivo:

Advocacia Individual e Escritório de Advocacia compartilham a base ética e operacional, mas possuem promessa comercial, linguagem, handoff e condução diferentes.

O GPT-4o-mini deve receber snapshot limpo, sem mistura entre confiança pessoal e confiança institucional.

---

# 3. Campo novo legal_runtime

Decisão inicial:

```text id="34pssm"
não criar legal_runtime nesta fase
```

Justificativa:

A estrutura V2 já preservada em Otorrino oferece campos suficientes para representar a segurança jurídica de Advocacia.

Campos preferenciais:

```text id="ki14fr"
operational_runtime
behavior_components
snapshot_priority
```

A segurança jurídica será modelada dentro de estruturas já conhecidas, evitando risco de o pipeline ignorar campo novo.

A criação de `legal_runtime` só deve ser reavaliada se houver validação técnica posterior de preservação no snapshot.

---

# 4. Equivalência entre Otorrino e Advocacia

Em Otorrino, o campo `medical_runtime` representa limites e segurança da área médica.

Em Advocacia, a camada equivalente não deve virar campo novo agora.

Equivalência conservadora:

```text id="udsd48"
medical_runtime de Otorrino
→ operational_runtime.legal_safety_limits em Advocacia
→ behavior_components.boundary_guard em Advocacia
→ snapshot_priority.operational_always_keep em Advocacia
```

Objetivo:

```text id="wx7pjg"
preservar limites profissionais e segurança jurídica
sem criar estrutura nova no Firestore
```

---

# 5. Estrutura comum dos dois JSONs futuros

Ambos os JSONs devem preservar:

```text id="tc0znp"
id
enabled
name
segment_id
archetype_id
conversation_mode
customer_noun
service_noun
conversion_noun
primary_goal
description
one_liner
one_question
micro_scene
micro_scene_conversational
keywords
negative_keywords
catalog_groups
common_intents
operational_ritual
operational_rules
preferred_capabilities
handoff_format
real_customer_situations
segment_status_use_cases
commercial_runtime
operational_runtime
behavior_components
snapshot_priority
```

O campo `medical_runtime` não deve ser usado em Advocacia.

O campo `legal_runtime` fica pendente de avaliação futura.

---

# 6. Campo micro_scene_conversational

Decisão preservada:

```text id="jaw5bp"
micro_scene_conversational não será criada nesta etapa
```

Nos JSONs futuros, esse campo só deve ser preenchido depois da construção supervisionada pelo usuário.

Enquanto isso, o mapping deve registrar:

```text id="amcgoj"
campo obrigatório para JSON final
conteúdo pendente
não preencher com texto improvisado
não copiar microcena de outro subsegmento
```

Critério futuro:

```text id="ovozvb"
representar ganho operacional comum da Advocacia
mostrar venda por confiança
mostrar acolhimento
mostrar triagem segura
mostrar encaminhamento responsável
preservar limites profissionais
manter linguagem adequada para WhatsApp
```

---

# 7. commercial_runtime

Função:

Preservar a venda por confiança.

Para Advocacia Individual:

```text id="h4qgza"
trust_model:
confiança pessoal

commercial_focus:
proximidade, análise direta, cuidado individual e organização do primeiro atendimento

conversion_path:
consulta ou análise inicial com o advogado
```

Para Escritório de Advocacia:

```text id="jlmnmf"
trust_model:
confiança institucional

commercial_focus:
método, equipe, áreas de atuação, triagem organizada e responsável adequado

conversion_path:
triagem, consulta, reunião ou encaminhamento interno
```

Regra comum:

```text id="mqd90s"
a venda acontece por acolhimento, clareza, método, informação útil e próximo passo seguro
```

---

# 8. operational_runtime

Função:

Preservar a condução operacional do atendimento.

Blocos comuns:

```text id="fpke0d"
intake_flow
area_triage
document_handling
urgency_perception
handoff_triggers
legal_safety_limits
subscriber_config_slots
```

Regra central:

```text id="ty28v4"
o robô organiza o contato;
o advogado realiza a análise jurídica
```

Estados operacionais principais:

```text id="suwld5"
lead relata dor jurídica inicial
lead pede chance de ganhar
lead pede valor de indenização ou cálculo
lead envia documento
lead relata urgência percebida
lead pergunta por honorários
lead não sabe a área jurídica
lead quer processar alguém
```

---

# 9. behavior_components

Função:

Preservar comportamento conversacional e comercial.

Componentes comuns:

```text id="bkhn8p"
empathic_timing
trust_by_method
boundary_guard
confidentiality
information_gap_detection
context_before_recommendation
positive_boundary_modeling
regulated_service_conversion
```

Para GPT-4o-mini, os componentes devem ser traduzidos em ações concretas.

Formato preferencial:

```text id="tg2iqw"
detected_state
commercial_objective
safe_response_direction
allowed_actions
useful_information
next_step
handoff_trigger
```

---

# 10. snapshot_priority

Função:

Garantir que o snapshot final preserve o que é indispensável.

Prioridade comum:

```text id="smxtk6"
venda por confiança
regra do robô organiza e advogado analisa
limites positivos para pedidos de conclusão jurídica
sigilo e cuidado documental
urgência percebida sem decisão técnica
encaminhamento para análise profissional
micro_scene_conversational pendente
```

Prioridade da Advocacia Individual:

```text id="b8pmyb"
confiança pessoal
linguagem sóbria, próxima e direta
consulta ou análise inicial com o advogado
handoff direto ao advogado
```

Prioridade do Escritório de Advocacia:

```text id="3a1aob"
confiança institucional
linguagem organizada, humana e profissional
triagem por área provável
encaminhamento para setor, área ou responsável
handoff interno com rastreabilidade
```

---

# 11. common_intents

Intents comuns:

```text id="en7z91"
perguntar se tem direito
perguntar se tem chance
querer processar alguém
pedir valor de indenização
perguntar preço ou honorários
enviar documento
relatar urgência
não saber que tipo de advogado precisa
procurar advogado por área
pedir consulta
```

Esses intents devem ser escritos em linguagem real de lead, não em abstrações.

---

# 12. real_customer_situations

Situações comuns:

```text id="q0yux7"
fui demitido e quero saber se tenho direitos
quero saber se tenho chance de ganhar
recebi uma intimação
quero entrar com uma ação
meu benefício do INSS foi negado
estou com problema de pensão ou guarda
fui negativado ou cobrado indevidamente
tenho um contrato para analisar
tenho problema com aluguel ou imóvel
enviei um documento e quero saber o que fazer
```

Função:

Ajudar o GPT-4o-mini a reconhecer o estado real do lead e conduzir para o próximo passo seguro.

---

# 13. operational_rules

As regras operacionais devem ser positivas e acionáveis.

must_do:

```text id="u2uv5a"
acolher
identificar área provável
perguntar apenas o necessário
organizar fatos e documentos
reconhecer urgência percebida
conduzir para consulta, reunião ou responsável
preservar continuidade
```

should_do:

```text id="l11mkq"
entregar informação útil antes de pedir demais
usar linguagem sóbria
respeitar o modelo individual ou escritório
resumir o caso para handoff
orientar documentos iniciais conforme configuração
```

avoid:

```text id="mj0ovs"
usar o robô como parecerista
prometer resultado
inventar honorários
interpretar documento conclusivamente
decidir estratégia
misturar voz de advogado individual com voz de escritório
```

Observação:

O campo `avoid` pode existir como apoio, mas o snapshot deve priorizar caminhos positivos.

---

# 14. handoff_format

Advocacia Individual:

```text id="soyrl7"
Nome do lead:
Área provável:
Resumo do caso:
Urgência percebida:
Prazo mencionado:
Documentos mencionados:
Próximo passo sugerido:
Canal de retorno:
```

Escritório de Advocacia:

```text id="szxz62"
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

---

# 15. subscriber customization slots

Slots comuns:

```text id="edoa0t"
áreas atendidas
áreas não atendidas
cidade ou região
consulta online ou presencial
horários
política de primeira consulta
documentos iniciais por área
preferência de contato
forma de urgência
tom de linguagem
```

Slots de Advocacia Individual:

```text id="rscxgp"
nome do advogado
OAB
agenda individual
forma de análise
```

Slots de Escritório de Advocacia:

```text id="yiliv3"
nome do escritório
OAB ou sociedade quando aplicável
advogados ou responsáveis por área
equipe de triagem
modelo de encaminhamento interno
```

---

# 16. Arquivos futuros previstos

Mapping específico futuro:

```text id="k2lz05"
docs\subsegments\advocacia_individual\firestore\ADVOCACIA_INDIVIDUAL_FIRESTORE_FIELD_MAPPING_V1.md
docs\subsegments\escritorio_advocacia\firestore\ESCRITORIO_ADVOCACIA_FIRESTORE_FIELD_MAPPING_V1.md
```

JSONs futuros:

```text id="33xfg8"
docs\subsegments\advocacia_individual\firestore\ADVOCACIA_INDIVIDUAL_FIRESTORE_JSON_V1.json
docs\subsegments\escritorio_advocacia\firestore\ESCRITORIO_ADVOCACIA_FIRESTORE_JSON_V1.json
```

---

# 17. Critério antes de gerar JSON

Antes de criar JSON:

```text id="0m01pa"
micro_scene_conversational construída com supervisão
campos comparados com JSON V2 de Otorrino
snapshot_priority auditado
sem criação de legal_runtime
sem alteração de código
sem aplicação Firestore
sem deploy
```

---

# 18. Síntese

Advocacia seguirá a estrutura Firestore V2 já observada em Otorrino.

A segurança jurídica será modelada dentro de operational_runtime, behavior_components e snapshot_priority.

Dois JSONs serão criados futuramente, um para Advocacia Individual e outro para Escritório de Advocacia.

A micro_scene_conversational permanece pendente para construção supervisionada.
