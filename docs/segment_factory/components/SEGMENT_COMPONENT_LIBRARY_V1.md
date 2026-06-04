# SEGMENT_COMPONENT_LIBRARY_V1

## Objetivo

Registrar componentes reutilizáveis descobertos durante a criação de segmentos do MEI ROBÔ.

Esta biblioteca cresce segmento após segmento.

Ela não nasce pronta.

Ela não substitui:

- kb_archetypes_v1;
- kb_segments_v1;
- kb_subsegments_v1;
- runtime compacto do segmento;
- pesquisa específica do segmento.

Ela serve para acelerar a criação de novos segmentos por customização controlada.

---

# 1. Regra central

Cada novo segmento gera dois produtos:

1. O próprio segmento.
2. Componentes potencialmente reutilizáveis para segmentos futuros.

A biblioteca deve preservar a origem de cada componente.

---

# 2. Status dos componentes

## CANDIDATE

Componente identificado em um segmento, mas ainda não validado em outros.

## REUSED

Componente já reutilizado em pelo menos um novo segmento.

## PATTERN_CANDIDATE

Componente recorrente em múltiplos segmentos, candidato a virar pattern formal no futuro.

## LOCAL_ONLY

Componente que parece reutilizável, mas foi reclassificado como específico do segmento.

---

# 3. Componentes iniciais extraídos da Ótica

## COMPONENT_NEED_DISCOVERY

Status:

CANDIDATE

Origem:

Ótica.

Função:

Entender necessidade real antes de orientar.

Customização futura:

Adaptar as perguntas de descoberta ao domínio do novo segmento.

---

## COMPONENT_CONTEXT_BEFORE_RECOMMENDATION

Status:

CANDIDATE

Origem:

Ótica.

Função:

Evitar recomendação direta quando faltam critérios.

Customização futura:

Definir quais critérios mínimos são necessários no novo segmento.

---

## COMPONENT_INFORMATION_GAP_DETECTION

Status:

CANDIDATE

Origem:

Ótica.

Função:

Identificar informações faltantes antes de avançar.

Customização futura:

Substituir lacunas da Ótica por lacunas reais do segmento novo.

---

## COMPONENT_EXPERT_REFRAMING

Status:

CANDIDATE

Origem:

Ótica.

Função:

Transformar pergunta genérica em decisão orientada por critérios.

Customização futura:

Criar reframes próprios do novo segmento.

---

## COMPONENT_RISK_REDUCTION

Status:

CANDIDATE

Origem:

Ótica.

Função:

Reduzir risco de escolha inadequada, retrabalho, frustração ou cancelamento.

Customização futura:

Mapear riscos específicos do novo segmento.

---

## COMPONENT_EXPECTATION_ALIGNMENT

Status:

CANDIDATE

Origem:

Ótica.

Função:

Alinhar expectativa antes da decisão.

Customização futura:

Definir quais expectativas costumam gerar problema no novo segmento.

---

## COMPONENT_TRUST_BUILDING_BY_METHOD

Status:

CANDIDATE

Origem:

Ótica.

Função:

Construir confiança explicando método, critérios e processo.

Customização futura:

Descrever como um profissional experiente do novo segmento demonstra método.

---

## COMPONENT_FAILURE_CAUSE_ANALYSIS

Status:

CANDIDATE

Origem:

Ótica.

Função:

Investigar causas de falhas, reclamações ou retrabalho.

Customização futura:

Mapear falhas reais do novo segmento e suas causas recorrentes.

---

## COMPONENT_SUBSCRIBER_CUSTOMIZATION_SLOTS

Status:

CANDIDATE

Origem:

Ótica.

Função:

Separar expertise-base do segmento das informações próprias do assinante.

Customização futura:

Definir slots de personalização adequados ao segmento novo.

---


## COMPONENT_CONSULTANT_DECISION_SEQUENCE

Status:

CANDIDATE

Origem:

Ótica.

FIRST_OBSERVED_IN:

comercio_varejista__loja_oculos

CONFIDENCE_LEVEL:

HIGH

Função:

Representar a sequência mental utilizada por especialistas antes de orientar.

Sequência observada:

Entender necessidade
↓
Entender contexto
↓
Identificar lacunas
↓
Avaliar critérios
↓
Avaliar riscos
↓
Orientar decisão
↓
Alinhar expectativa

Customização futura:

Adaptar os critérios e lacunas ao domínio do novo segmento.

---

## OUTCOME_TRUST_BUILDING

Status:

OBSERVED_OUTCOME

Origem:

Ótica.

FIRST_OBSERVED_IN:

comercio_varejista__loja_oculos

Descrição:

Confiança não é um componente operacional.

Confiança é consequência da aplicação correta de:

- descoberta de necessidade;
- identificação de lacunas;
- critérios;
- redução de risco;
- alinhamento de expectativa.

---


# 4. Como usar no próximo segmento

Ao iniciar o próximo segmento:

1. pesquisar o segmento normalmente;
2. comparar os achados com esta biblioteca;
3. reutilizar apenas o que fizer sentido;
4. customizar o componente para o novo domínio;
5. registrar componentes novos descobertos;
6. atualizar o status dos componentes reaproveitados.

---

# 5. Critério de maturidade

Um componente só deve virar pattern formal quando:

- aparecer em mais de um segmento;
- for reutilizável sem carregar termos específicos;
- possuir função clara no comportamento da IA;
- ajudar o GPT-4o-mini a decidir melhor;
- não conflitar com a estrutura atual do Firestore.
