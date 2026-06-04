# OTICA_REUSABLE_COMPONENTS_V1

## Objetivo

Encerrar a Ótica como Segmento Referência Oficial do MEI ROBÔ e separar, de forma controlada, o que permanece específico da Ótica e o que poderá ser reutilizado de forma customizada na criação dos próximos segmentos.

Este documento não cria um novo segmento.

Este documento não altera código.

Este documento não altera prompt.

Este documento não aplica nada no Firestore.

Este documento apenas prepara a Ótica para servir como origem de componentes reutilizáveis.

---

# 1. Fonte oficial utilizada

Arquivos-base:

- OTICA_V3_CANONICAL_MODEL.md
- OTICA_RUNTIME_COMPACT_V1.md
- OTICA_LESSONS_LEARNED_V1.md
- OTICA_RUNTIME_COMPACT_AUDIT_V1.md

---

# 2. Princípio de extração

A Ótica não deve virar uma biblioteca genérica por achismo.

A extração deve respeitar a diferença entre:

- conhecimento específico de ótica;
- mecanismo consultivo reutilizável;
- mecanismo operacional reutilizável;
- aprendizado metodológico aplicável à fábrica de segmentos.

Um componente só deve ser reutilizado em outro segmento se puder ser customizado sem carregar produtos, termos ou decisões exclusivas da Ótica.

---

# 3. Elementos específicos da Ótica

Estes elementos devem permanecer no subsegmento `comercio_varejista__loja_oculos`.

## 3.1 Conhecimento técnico específico

- lentes monofocais;
- lentes multifocais;
- lentes ocupacionais;
- lentes fotossensíveis;
- antirreflexo;
- índice de refração;
- espessura de lentes;
- armações;
- adaptação visual;
- compatibilidade lente x armação;
- receita;
- grau;
- laboratório óptico;
- medidas ópticas;
- relação entre lente, armação e uso visual.

## 3.2 Lacunas específicas da Ótica

- receita não conhecida;
- grau não conhecido;
- uso visual não conhecido;
- histórico de adaptação não investigado;
- compatibilidade entre receita e armação não verificada.

## 3.3 Riscos específicos da Ótica

- escolha de lente incompatível com rotina visual;
- escolha de armação incompatível com receita;
- expectativa incorreta sobre adaptação;
- compra baseada apenas em preço sem entender diferenças técnicas;
- retrabalho por falta de investigação inicial.

---

# 4. Componentes potencialmente reutilizáveis

Estes elementos nasceram na Ótica, mas podem ser customizados para outros segmentos.

## COMPONENT_NEED_DISCOVERY

Origem:

Ótica.

Mecanismo:

Antes de orientar, entender a necessidade real do cliente.

Forma observada na Ótica:

Entender cliente, necessidade, rotina, histórico, critérios e expectativa antes da recomendação.

Reutilização possível:

Clínicas, odontologia, fisioterapia, estética, serviços técnicos, advocacia, contabilidade, consultorias e outros segmentos em que a resposta correta depende do contexto.

Não carregar para outros segmentos:

Termos como lente, armação, grau, receita ou adaptação visual.

---

## COMPONENT_CONTEXT_BEFORE_RECOMMENDATION

Origem:

Ótica.

Mecanismo:

Evitar recomendação direta quando faltam critérios.

Forma observada na Ótica:

Quando o cliente pergunta “qual lente é melhor?”, o especialista primeiro descobre rotina, uso, receita e histórico.

Reutilização possível:

Todo segmento em que uma recomendação sem contexto pode gerar erro, retrabalho ou frustração.

---

## COMPONENT_INFORMATION_GAP_DETECTION

Origem:

Ótica.

Mecanismo:

Identificar informações faltantes antes de avançar.

Forma observada na Ótica:

Rotina, receita, uso principal, experiência anterior, expectativa e histórico de adaptação.

Reutilização possível:

Segmentos que dependem de dados prévios, documentos, avaliação, histórico, objetivos ou restrições.

---

## COMPONENT_EXPERT_REFRAMING

Origem:

Ótica.

Mecanismo:

Transformar uma pergunta genérica em uma pergunta orientada por critérios.

Forma observada na Ótica:

“Qual lente é melhor?” vira “melhor para qual rotina?”.

Reutilização possível:

Segmentos consultivos, técnicos ou profissionais em que o cliente faz perguntas amplas e espera orientação.

---

## COMPONENT_RISK_REDUCTION

Origem:

Ótica.

Mecanismo:

Reduzir risco antes da decisão.

Forma observada na Ótica:

Evitar decisão baseada apenas em preço, expectativa irreal ou recomendação sem critérios suficientes.

Reutilização possível:

Qualquer segmento com risco de retrabalho, cancelamento, má escolha, insatisfação ou expectativa desalinhada.

---

## COMPONENT_EXPECTATION_ALIGNMENT

Origem:

Ótica.

Mecanismo:

Alinhar expectativa antes de avançar.

Forma observada na Ótica:

Explicar adaptação, diferenças, processo e critérios antes da escolha.

Reutilização possível:

Saúde, estética, serviços técnicos, advocacia, educação, manutenção, consultoria e vendas consultivas.

---

## COMPONENT_TRUST_BUILDING_BY_METHOD

Origem:

Ótica.

Mecanismo:

Construir confiança mostrando método, critérios e processo.

Forma observada na Ótica:

O especialista não apenas recomenda; ele explica como avalia.

Reutilização possível:

Segmentos nos quais a confiança surge da percepção de método profissional.

---

## COMPONENT_FAILURE_CAUSE_ANALYSIS

Origem:

Ótica.

Mecanismo:

Usar problemas anteriores para investigar causa e evitar repetição.

Forma observada na Ótica:

Não adaptação, insatisfação e retrabalho ligados a expectativa, rotina ou histórico não investigados.

Reutilização possível:

Segmentos com pós-venda, manutenção, recorrência, tratamento, acompanhamento ou reclamação.

---

## COMPONENT_SUBSCRIBER_CUSTOMIZATION_SLOTS

Origem:

Ótica.

Mecanismo:

Separar expertise-base do segmento das informações próprias do assinante.

Forma observada na Ótica:

Marcas, produtos específicos, políticas comerciais, garantias, promoções, processos internos e especialidades adicionais ficam como slots de personalização.

Reutilização possível:

Todos os segmentos do MEI ROBÔ.

---

# 5. Aprendizados metodológicos reutilizáveis

A Ótica confirmou que:

- pesquisa e runtime devem permanecer separados;
- nem todo conteúdo útil para pesquisa deve ir ao runtime;
- o GPT-4o-mini responde melhor a estruturas determinísticas;
- sequência de decisão, critérios, estados e objetivos funcionam melhor do que abstrações vagas;
- treinamentos de especialistas são fontes valiosas;
- problemas reais de pós-venda ajudam a validar hipóteses;
- o método deve ser reaplicado em novos segmentos antes de virar padrão definitivo.

---

# 6. Decisão de governança

Os componentes acima ainda não devem virar coleção no Firestore.

Status atual:

- válidos como biblioteca documental inicial;
- úteis para customização do próximo segmento;
- ainda não validados por recorrência em múltiplos segmentos.

A cada novo segmento criado, este inventário deve ser revisado para:

- confirmar componentes já existentes;
- adaptar componentes aplicáveis;
- registrar novos componentes descobertos;
- marcar componentes recorrentes como candidatos futuros a patterns formais.

---

# 7. Resultado

A Ótica fica encerrada como:

- segmento funcional;
- segmento referência;
- origem metodológica;
- primeira fonte de componentes reutilizáveis;
- ponto de partida da Fábrica de Segmentos.
