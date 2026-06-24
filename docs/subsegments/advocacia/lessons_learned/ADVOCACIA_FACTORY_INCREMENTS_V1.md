# ADVOCACIA_FACTORY_INCREMENTS_V1

## Objetivo

Registrar o que a construção inicial de Advocacia incrementou na Fábrica de Segmentos do MEI Robô.

Este documento não é JSON.

Este documento não altera Firestore.

Este documento não altera código.

Este documento não promove componentes para padrão definitivo.

Ele registra aprendizados, decisões e pontos de reaproveitamento para futuros subsegmentos.

---

# 1. Decisão arquitetural tomada

Advocacia foi modelada como:

```text
base canônica comum
+
dois subsegmentos operacionais separados
```

Base comum:

```text
docs\subsegments\advocacia
```

Subsegmentos operacionais:

```text
docs\subsegments\advocacia_individual
docs\subsegments\escritorio_advocacia
```

IDs Firestore candidatos:

```text
servicos_profissionais__advocacia_individual
servicos_profissionais__escritorio_advocacia
```

Justificativa:

A ética, o sigilo, a triagem segura e os limites profissionais são comuns.

A promessa comercial, a linguagem e a operação são diferentes.

Advocacia individual vende confiança pessoal.

Escritório de advocacia vende confiança institucional, método, equipe e encaminhamento correto.

---

# 2. Regra comercial reforçada

Advocacia reforçou uma regra soberana da fábrica:

```text
o vendedor, em última análise, vende confiança
```

Em serviços sensíveis, regulados ou consultivos, a venda não deve depender de pressão, promessa ou urgência artificial.

A venda deve acontecer por:

```text
acolhimento
clareza
método
informação útil
organização
respeito ao limite profissional
próximo passo seguro
```

---

# 3. Regra de timing reforçada

Advocacia reforçou que timing comercial não é insistência.

Timing comercial seguro é:

```text
ser empático
entregar informação útil
perguntar apenas o necessário
conduzir para a próxima etapa segura
```

Esse aprendizado pode ser reaproveitado em todos os segmentos consultivos.

---

# 4. Regra GPT-4o-mini reforçada

Advocacia confirmou que limites profissionais não devem ser modelados apenas como proibições.

Para GPT-4o-mini, o formato mais seguro é:

```text
estado observado
→ objetivo comercial
→ caminho seguro
→ informação útil
→ próximo passo
→ gatilho de encaminhamento
```

Exemplo geral:

```text
quando o cliente pedir conclusão técnica
→ acolher
→ organizar informações
→ explicar que a análise depende do profissional responsável
→ conduzir para atendimento especializado
```

---

# 5. Principal incremento metodológico

O principal incremento de Advocacia foi:

```text
transformar limites profissionais em trilhos positivos de condução
```

Em vez de depender de comandos como:

```text
não dê parecer
não prometa resultado
não interprete documento
```

A fábrica deve preferir estruturas como:

```text
quando o lead pedir conclusão
→ acolher
→ organizar o relato
→ explicar que a análise depende do profissional
→ conduzir para consulta, reunião ou responsável
```

---

# 6. Arquivos centrais incrementados

Advocacia criou o arquivo central:

```text
docs\segment_factory\reusable_assets\ADVOCACIA_REUSABLE_COMPONENTS_V1.md
```

Advocacia também incrementou:

```text
docs\segment_factory\reusable_assets\FACTORY_REUSE_STATUS_V1.md
```

Com o bloco:

```text
CANDIDATE_FROM_ADVOCACIA
```

Esse bloco aponta os componentes candidatos reaproveitáveis vindos de Advocacia.

---

# 7. Componentes candidatos gerados

Advocacia gerou estes componentes candidatos:

```text
COMPONENT_POSITIVE_BOUNDARY_MODELING
COMPONENT_REGULATED_PROFESSIONAL_BOUNDARY
COMPONENT_CONFIDENTIAL_INTAKE_FLOW
COMPONENT_URGENCY_PERCEPTION_WITHOUT_DECISION
COMPONENT_TRUST_SELLING_BY_BOUNDARY
COMPONENT_EMPATHIC_TIMING
COMPONENT_REGULATED_SERVICE_CONVERSION
COMPONENT_INDIVIDUAL_VS_STRUCTURED_PROVIDER_ADAPTATION
COMPONENT_CONSULTATION_BEFORE_RECOMMENDATION
```

Status:

```text
CANDIDATE
```

Eles não devem ser aplicados automaticamente.

Eles não devem virar Firestore agora.

Eles devem ser testados em novos subsegmentos antes de promoção.

---

# 8. Reuso provável em futuros subsegmentos

Os aprendizados de Advocacia podem ajudar especialmente em:

```text
saúde
psicologia
contabilidade
engenharia
arquitetura
consultoria financeira
serviços técnicos regulados
serviços com documentos sensíveis
serviços com urgência percebida
profissional individual vs empresa estruturada
```

---

# 9. Risco evitado

A separação entre Advocacia Individual e Escritório de Advocacia evita um risco importante:

```text
misturar confiança pessoal com confiança institucional no mesmo snapshot
```

Essa mistura poderia fazer o GPT-4o-mini alternar indevidamente entre:

```text
meu atendimento
nosso escritório
o advogado
a equipe
a área responsável
```

Por isso, a fábrica deve considerar separação semelhante quando houver diferença real entre profissional individual e organização estruturada.

---

# 10. Microcena conversacional

A micro_scene_conversational não foi criada nesta etapa.

Decisão preservada:

```text
a micro_scene_conversational de Advocacia será construída separadamente,
com supervisão direta do usuário
```

Motivo:

A microcena deve representar um ganho operacional comum forte do subsegmento e precisa ser cuidadosamente equilibrada entre ética, venda, utilidade e clareza comercial.

---

# 11. Próximos passos previstos

Depois desta etapa documental, os próximos passos são:

```text
1. revisar os documentos criados;
2. criar auditoria de runtime;
3. criar mapping futuro para Firestore;
4. construir micro_scene_conversational com supervisão;
5. gerar JSONs separados;
6. fazer dry-run;
7. aplicar Firestore somente com autorização;
8. testar respostas institucionais.
```

---

# 12. Síntese

Advocacia incrementou a fábrica ao mostrar como vender confiança em serviços regulados.

O robô deve parecer responsável, útil e orientado ao próximo passo.

O robô não precisa apenas evitar erro.

O robô precisa conduzir bem.
