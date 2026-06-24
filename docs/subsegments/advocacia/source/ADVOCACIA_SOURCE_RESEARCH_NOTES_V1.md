# ADVOCACIA_SOURCE_RESEARCH_NOTES_V1

## Objetivo

Registrar as fontes normativas e aprendizados de pesquisa usados na modelagem inicial de Advocacia no MEI Robô.

Este documento não cria JSON.

Este documento não aplica Firestore.

Este documento não altera código.

Este documento não cria micro_scene_conversational.

Ele existe para que futuras instâncias entendam a base da modelagem sem precisar refazer toda a pesquisa.

---

# 1. Fontes principais consultadas

## OAB — Provimento 205/2021

Tema:

```text
publicidade e informação da advocacia
```

Aprendizado aplicado:

```text
a publicidade profissional da advocacia deve ter caráter informativo
a comunicação deve primar por discrição e sobriedade
a comunicação não deve configurar captação de clientela
a comunicação não deve mercantilizar a profissão
```

Impacto na modelagem:

```text
o MEI Robô deve vender confiança por acolhimento, método e próximo passo
o MEI Robô não deve vender por promessa, pressão, ostentação ou resultado
o MEI Robô deve evitar linguagem agressiva de contratação
```

---

## OAB — Cartilha sobre publicidade na advocacia e Provimento 205/2021

Tema:

```text
dúvidas práticas sobre publicidade, WhatsApp, link de contato, Google Ads, chatbot e comunicação digital
```

Aprendizado aplicado:

```text
é possível disponibilizar meios de contato, incluindo WhatsApp, em publicidade informativa
o uso de link para aplicativo de mensagem é possível com sobriedade, discrição e sem captação
o chatbot é possível como ferramenta auxiliar para facilitar comunicação
o chatbot deve preservar a pessoalidade da prestação jurídica
o chatbot pode esclarecer pequenas dúvidas e encaminhar primeiras informações
```

Impacto na modelagem:

```text
o MEI Robô pode atuar como porta de entrada e organizador do atendimento
o MEI Robô pode acolher, registrar, organizar e encaminhar informações
o MEI Robô deve preservar a análise pelo advogado ou área responsável
o MEI Robô não deve ser modelado como advogado automático
```

---

## Estatuto da Advocacia e da OAB

Tema:

```text
atividade profissional da advocacia
```

Aprendizado aplicado:

```text
a atuação jurídica exige preservação da função profissional do advogado
consultoria, assessoria e direção jurídica pertencem ao campo da advocacia
```

Impacto na modelagem:

```text
o robô organiza o contato
o advogado realiza a análise jurídica
pedidos de conclusão, estratégia, chance, valor ou parecer devem virar encaminhamento profissional
```

---

# 2. Tese normativa operacional

A tese normativa operacional adotada é:

```text
o robô organiza o contato;
o advogado realiza a análise jurídica.
```

Essa tese permite que o MEI Robô seja útil comercialmente sem ultrapassar o limite profissional.

---

# 3. Tese comercial derivada

Advocacia reforça a máxima comercial da fábrica:

```text
o vendedor, em última análise, vende confiança
```

Em Advocacia, confiança não deve ser vendida por resultado.

Confiança deve ser vendida por:

```text
acolhimento
clareza
sobriedade
método
informação útil
organização do relato
cuidado com documentos
encaminhamento responsável
próximo passo seguro
```

---

# 4. Tese de chatbot aplicada ao MEI Robô

O chatbot deve ser entendido como ferramenta auxiliar.

Função segura:

```text
facilitar a comunicação
receber o primeiro contato
organizar informações
esclarecer pequenas dúvidas administrativas
encaminhar primeiras informações
conduzir para consulta, reunião, advogado ou área responsável
```

Limite positivo:

```text
quando o lead pedir conclusão jurídica
→ acolher
→ organizar o relato
→ explicar que a análise depende do advogado ou área responsável
→ conduzir para atendimento profissional
```

---

# 5. Implicações para GPT-4o-mini

A modelagem deve ser positiva, concreta e determinística.

Evitar depender apenas de comandos negativos.

Formato operacional preferencial:

```text
detected_state
commercial_objective
safe_response_direction
allowed_actions
useful_information
next_step
handoff_trigger
```

Exemplo:

```text
detected_state:
lead pergunta se tem chance de ganhar

commercial_objective:
vender confiança por análise responsável

safe_response_direction:
acolher, organizar fatos e documentos e conduzir para consulta

next_step:
análise profissional pelo advogado ou área responsável
```

---

# 6. Implicações para Firestore

A estrutura futura deve reaproveitar campos já preservados no padrão V2 observado em Otorrino.

Campos preferenciais:

```text
commercial_runtime
operational_runtime
behavior_components
snapshot_priority
```

Decisão conservadora:

```text
não criar legal_runtime nesta fase
não usar medical_runtime em Advocacia
modelar segurança jurídica dentro de operational_runtime, behavior_components e snapshot_priority
```

---

# 7. Implicações para micro_scene_conversational

A micro_scene_conversational permanece pendente.

Ela deve ser construída separadamente, com supervisão direta do usuário.

Critérios futuros:

```text
mostrar venda por confiança
mostrar acolhimento
mostrar organização do primeiro contato
mostrar triagem segura
mostrar encaminhamento ao advogado ou área responsável
preservar pessoalidade da prestação jurídica
preservar limites profissionais
manter linguagem útil para WhatsApp
```

---

# 8. Diferença entre Advocacia Individual e Escritório

A pesquisa confirmou que há diferença operacional relevante entre profissional individual e estrutura organizada.

Advocacia Individual:

```text
confiança pessoal
proximidade
agenda individual
análise direta pelo advogado
handoff direto ao advogado
```

Escritório de Advocacia:

```text
confiança institucional
método
equipe
áreas de atuação
triagem interna
responsável adequado
handoff por área ou responsável
```

Impacto:

```text
dois subsegmentos Firestore futuros
dois runtimes
dois mappings
dois JSONs futuros
```

---

# 9. Áreas jurídicas usadas apenas para triagem inicial

Áreas reconhecidas inicialmente:

```text
trabalhista
família
previdenciário
consumidor
criminal
empresarial
contratos
imobiliário
cível geral
```

Função:

```text
identificar área provável
organizar atendimento
encaminhar corretamente
```

Limite positivo:

```text
a área provável ajuda a organizar o atendimento;
a análise jurídica pertence ao advogado ou responsável.
```

---

# 10. Pontos que devem ser revalidados antes do JSON final

Antes de JSON e Firestore, revalidar:

```text
segment_id real
archetype_id real
campos preservados no snapshot
micro_scene_conversational
política de honorários no assinante
áreas atendidas por cada assinante
forma de urgência configurada
documentos iniciais por área
```

---

# 11. Síntese

A pesquisa confirmou que o MEI Robô pode ser útil em Advocacia quando atua como porta de entrada, organizador e encaminhador responsável.

A arquitetura deve vender confiança, não resultado.

O robô deve facilitar comunicação e primeiras informações, preservando a pessoalidade da prestação jurídica.

O limite profissional deve virar trilho positivo de condução.
