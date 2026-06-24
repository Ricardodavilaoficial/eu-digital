# ADVOCACIA_FIRESTORE_PUBLICATION_AUDIT_V1

## Objetivo

Registrar a publicação Firestore dos subsegmentos de Advocacia no MEI Robô.

Este documento registra uma aplicação real no Firestore.

Este documento não altera código.

Este documento não faz deploy.

Este documento não altera Cloud Run.

---

# 1. Publicação realizada

Data operacional:

```text
24/06/2026
```

Script temporário utilizado:

```text
tmp_publish_advocacia_firestore.py
```

Projeto Firestore:

```text
mei-robo-prod
```

Coleções impactadas:

```text
kb_segments_v1
kb_archetypes_v1
kb_subsegments_v1
```

---

# 2. Segmento criado ou atualizado

Documento:

```text
kb_segments_v1/servicos_profissionais
```

Resultado verificado:

```text
EXISTS=True
name=Serviços profissionais
```

Função:

Representar serviços profissionais consultivos dentro da fábrica de segmentos.

---

# 3. Arquétipo criado ou atualizado

Documento:

```text
kb_archetypes_v1/servico_consultivo_profissional
```

Resultado verificado:

```text
EXISTS=True
name=Serviço consultivo profissional
```

Função:

Representar serviços em que o robô acolhe, organiza informações e encaminha para análise profissional.

---

# 4. Subsegmento publicado: Advocacia Individual

Documento:

```text
kb_subsegments_v1/servicos_profissionais__advocacia_individual
```

Resultado verificado:

```text
EXISTS=True
name=Advocacia Individual
segment_id=servicos_profissionais
archetype_id=servico_consultivo_profissional
enabled=True
micro_scene_conversational=632 caracteres
```

Arquivo JSON local gerado:

```text
docs\subsegments\advocacia_individual\firestore\ADVOCACIA_INDIVIDUAL_FIRESTORE_JSON_V1.json
```

---

# 5. Subsegmento publicado: Escritório de Advocacia

Documento:

```text
kb_subsegments_v1/servicos_profissionais__escritorio_advocacia
```

Resultado verificado:

```text
EXISTS=True
name=Escritório de Advocacia
segment_id=servicos_profissionais
archetype_id=servico_consultivo_profissional
enabled=True
micro_scene_conversational=658 caracteres
```

Arquivo JSON local gerado:

```text
docs\subsegments\escritorio_advocacia\firestore\ESCRITORIO_ADVOCACIA_FIRESTORE_JSON_V1.json
```

---

# 6. Microcenas publicadas

Advocacia Individual:

```text
Veja um exemplo prático: quando uma pessoa chama no WhatsApp procurando ajuda jurídica, o SEU MEI Robô recebe a mensagem, entende o problema, identifica a área provável e percebe se há prazo, audiência, intimação ou urgência. Pede os documentos configurados, organiza o relato e agenda a consulta com o advogado — tudo sem intervenção humana. Depois, quando chega uma movimentação ou sentença, o robô mesmo resume em linguagem simples e envia ao cliente pelo WhatsApp, com o próximo passo definido pelo advogado. Assim, reduz perguntas repetidas, evita perda de contatos e libera o advogado para atuar no que exige análise jurídica.
```

Escritório de Advocacia:

```text
Veja um exemplo prático: quando uma pessoa chama no WhatsApp procurando ajuda jurídica, o SEU MEI Robô recebe a mensagem, entende o problema, identifica a área provável e percebe se há prazo, audiência, intimação ou urgência. Pede os documentos configurados, organiza o relato e agenda a consulta ou encaminha para o advogado responsável — tudo sem intervenção humana. Depois, quando chega uma movimentação ou sentença, o robô mesmo resume em linguagem simples e envia ao cliente pelo WhatsApp, com o próximo passo definido pelo escritório. Assim, reduz perguntas repetidas, evita perda de contatos e libera a equipe para atuar no que exige análise jurídica.
```

---

# 7. Decisões preservadas

A publicação preservou:

```text
dois subsegmentos separados
sem legal_runtime
sem medical_runtime em Advocacia
uso de commercial_runtime
uso de operational_runtime
uso de behavior_components
uso de snapshot_priority
micro_scene_conversational abaixo de 680 caracteres
venda por confiança
limites profissionais em trilhos positivos
```

---

# 8. Observação sobre JSONs

Os JSONs foram gerados localmente, mas o `.gitignore` ignora arquivos `*.json`.

Para versionar estes dois artefatos canônicos, é necessário usar `git add -f` somente nos JSONs aprovados.

---

# 9. Estado técnico

Não houve alteração de código.

Não houve deploy.

Não houve alteração em Cloud Run.

Não houve alteração em prompt da aplicação.

A alteração aplicada foi exclusivamente Firestore KB e documentação/JSON local.

---

# 10. Próximo passo recomendado

Próxima etapa segura:

```text
testar respostas institucionais com os novos subsegmentos
validar se o front encontra os documentos no Firestore
avaliar telemetria de kbUsed, kbDocPath, response_mode e micro_scene_conversational
```
