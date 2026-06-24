# ADVOCACIA_REUSABLE_COMPONENTS_V1

## Objetivo

Registrar os aprendizados reutilizáveis descobertos durante a construção inicial de Advocacia no MEI Robô.

Este documento não cria JSON.

Este documento não altera Firestore.

Este documento não altera código.

Este documento não promove componentes para padrão definitivo.

Ele existe para que futuros subsegmentos encontrem rapidamente o que Advocacia descobriu e possam reaproveitar, adaptar ou validar.

---

# 1. Regra central

Advocacia trouxe aprendizados relevantes porque é um subsegmento consultivo, sensível e regulado.

O reuso deve respeitar a diferença entre:

```text
1. conteúdo específico de Advocacia;
2. mecanismo reutilizável em outros serviços regulados;
3. padrão comercial de venda por confiança;
4. limite profissional convertido em trilho positivo.
```

Nada deste documento deve ser aplicado automaticamente em outro segmento.

Cada componente deve ser adaptado ao novo domínio.

---

# 2. Elementos específicos de Advocacia

Estes elementos permanecem específicos de Advocacia e não devem ser copiados literalmente para outros segmentos:

```text
Código de Ética da OAB
Provimento 205/2021
publicidade jurídica
captação indevida
honorários advocatícios
procuração
parecer jurídico
estratégia processual
chance de ganho
valor de indenização
áreas jurídicas específicas
registro na OAB
sociedade de advogados
sigilo profissional jurídico
```

Esses elementos podem inspirar mecanismos, mas não devem virar regras genéricas sem adaptação.

---

# 3. Componentes reutilizáveis já herdados pela Advocacia

Advocacia reaproveita componentes já validados em Ótica e Clínica de Exames Médicos:

```text
COMPONENT_NEED_DISCOVERY
COMPONENT_CONTEXT_BEFORE_RECOMMENDATION
COMPONENT_INFORMATION_GAP_DETECTION
COMPONENT_EXPERT_REFRAMING
COMPONENT_RISK_REDUCTION
COMPONENT_EXPECTATION_ALIGNMENT
COMPONENT_TRUST_BUILDING_BY_METHOD
COMPONENT_FAILURE_CAUSE_ANALYSIS
COMPONENT_SUBSCRIBER_CUSTOMIZATION_SLOTS
COMPONENT_CONSULTANT_DECISION_SEQUENCE
```

Adaptação em Advocacia:

```text
descobrir a dor jurídica antes de orientar
entender o contexto antes de sugerir caminho
identificar lacunas antes de avançar
transformar pergunta ampla em triagem segura
reduzir expectativa indevida
alinhar a necessidade de análise profissional
construir confiança por método
separar expertise-base das regras do advogado ou escritório
```

---

# 4. Novos componentes candidatos vindos de Advocacia

## COMPONENT_POSITIVE_BOUNDARY_MODELING

Status:

CANDIDATE

Origem:

Advocacia.

Função:

Transformar limites regulatórios ou profissionais em trilhos positivos de resposta.

Forma observada em Advocacia:

Em vez de depender apenas de comandos como “não dê parecer jurídico”, o runtime deve indicar o caminho seguro:

```text
quando o lead pedir conclusão jurídica
→ acolher
→ organizar o relato
→ explicar que a análise depende do advogado e dos documentos
→ conduzir para consulta ou responsável
```

Reutilização possível:

```text
saúde
psicologia
contabilidade
engenharia
arquitetura
consultorias
estética avançada
serviços técnicos regulados
```

---

## COMPONENT_REGULATED_PROFESSIONAL_BOUNDARY

Status:

CANDIDATE

Origem:

Advocacia.

Função:

Separar o que o robô pode organizar do que pertence ao profissional habilitado.

Forma observada em Advocacia:

```text
o robô organiza o contato;
o advogado realiza a análise jurídica.
```

Reutilização possível:

Segmentos onde o robô pode acolher, organizar e encaminhar, mas não substituir avaliação profissional.

---

## COMPONENT_CONFIDENTIAL_INTAKE_FLOW

Status:

CANDIDATE

Origem:

Advocacia.

Função:

Receber relatos e documentos sensíveis com cuidado, organização e encaminhamento responsável.

Forma observada em Advocacia:

```text
acolher relato sensível
coletar apenas informações úteis
organizar documentos iniciais
encaminhar ao profissional ou área responsável
preservar contexto e continuidade
```

Reutilização possível:

```text
saúde
psicologia
contabilidade
recursos humanos
consultorias
serviços financeiros
educação especializada
```

---

## COMPONENT_URGENCY_PERCEPTION_WITHOUT_DECISION

Status:

CANDIDATE

Origem:

Advocacia.

Função:

Reconhecer urgência percebida pelo cliente sem afirmar conclusão técnica.

Forma observada em Advocacia:

```text
lead relata prisão, intimação, prazo, audiência, conflito familiar ou situação sensível
→ robô acolhe com seriedade
→ identifica cidade, situação atual e forma de contato
→ encaminha ao responsável configurado
```

Reutilização possível:

Segmentos onde o cliente relata urgência, mas a gravidade técnica precisa ser definida por profissional.

---

## COMPONENT_TRUST_SELLING_BY_BOUNDARY

Status:

CANDIDATE

Origem:

Advocacia.

Função:

Vender confiança mostrando método e limite profissional, não promessa.

Forma observada em Advocacia:

```text
a confiança nasce quando o lead percebe que o robô não inventa conclusão,
organiza o caso e conduz para análise responsável.
```

Reutilização possível:

Serviços consultivos, regulados ou de alto risco de expectativa indevida.

---

## COMPONENT_EMPATHIC_TIMING

Status:

CANDIDATE

Origem:

Advocacia.

Função:

Definir que timing comercial não é insistência, mas empatia com informação útil e relevante.

Forma observada em Advocacia:

```text
acolher primeiro
entregar utilidade
perguntar apenas o necessário
conduzir para próximo passo seguro
```

Reutilização possível:

Todos os segmentos consultivos e de venda relacional.

---

## COMPONENT_REGULATED_SERVICE_CONVERSION

Status:

CANDIDATE

Origem:

Advocacia.

Função:

Conduzir para consulta, análise ou atendimento profissional sem transformar a automação em prestação técnica indevida.

Forma observada em Advocacia:

```text
lead pede resposta jurídica
→ robô organiza
→ oferece análise profissional
→ evita transformar a resposta em parecer
```

Reutilização possível:

```text
saúde
psicologia
contabilidade
engenharia
arquitetura
consultoria financeira
serviços técnicos especializados
```

---

## COMPONENT_INDIVIDUAL_VS_STRUCTURED_PROVIDER_ADAPTATION

Status:

CANDIDATE

Origem:

Advocacia.

Função:

Diferenciar profissional individual de estrutura com equipe, áreas ou responsáveis internos.

Forma observada em Advocacia:

```text
advogado individual vende confiança pessoal
escritório vende confiança institucional, método, equipe e encaminhamento correto
```

Reutilização possível:

```text
clínica individual vs clínica estruturada
profissional autônomo vs empresa
consultor individual vs consultoria
médico individual vs clínica
contador individual vs escritório contábil
```

---

## COMPONENT_CONSULTATION_BEFORE_RECOMMENDATION

Status:

CANDIDATE

Origem:

Advocacia.

Função:

Preservar que a orientação final depende de consulta, reunião ou análise profissional.

Forma observada em Advocacia:

```text
quando o lead pede conclusão,
o robô prepara a análise em vez de concluir.
```

Reutilização possível:

Segmentos em que a resposta final depende de avaliação profissional, documentos, diagnóstico, vistoria ou análise técnica.

---

# 5. Aprendizado metodológico principal

Advocacia confirmou que, em segmentos regulados, limites não devem ser modelados apenas como proibição.

Para GPT-4o-mini, o melhor formato é:

```text
estado observado
→ objetivo comercial
→ caminho seguro
→ informação útil
→ próximo passo
→ gatilho de encaminhamento
```

Exemplo genérico:

```text
quando o cliente pedir conclusão técnica
→ acolher
→ organizar informações
→ explicar que a análise depende do profissional
→ conduzir para atendimento especializado
```

---

# 6. Como usar em novos subsegmentos

Ao iniciar um novo subsegmento sensível ou consultivo, verificar se algum destes mecanismos se aplica:

```text
existe profissional habilitado?
existe risco de promessa indevida?
existe dado sensível?
existe documento importante?
existe urgência percebida?
existe diferença entre profissional individual e empresa estruturada?
existe necessidade de análise antes de recomendação?
```

Se a resposta for sim, avaliar adaptação dos componentes de Advocacia.

---

# 7. Governança

Os componentes deste documento são candidatos.

Eles não devem criar nova coleção Firestore.

Eles não devem ser promovidos para pattern formal sem recorrência em novos subsegmentos.

Eles devem ser registrados no FACTORY_REUSE_STATUS_V1 como candidatos vindos de Advocacia.

A promoção futura exige:

```text
recorrência em múltiplos subsegmentos
função clara no comportamento da IA
compatibilidade com GPT-4o-mini
ausência de conflito com a estrutura atual do Firestore
validação prática em runtime ou snapshot
```

---

# 8. Síntese

Advocacia contribui para a fábrica ao ensinar como vender confiança em serviços regulados.

O principal ganho reutilizável é transformar limites profissionais em condução positiva.

O robô não precisa parecer limitado.

O robô precisa parecer responsável, útil e orientado ao próximo passo.
