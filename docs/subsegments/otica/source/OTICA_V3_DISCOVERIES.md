# OTICA V3 DISCOVERIES

## Objetivo

Registrar descobertas da Ótica V3 já adaptadas para consumo pelo GPT-4o-mini.

As descobertas devem ser registradas como:

* estados observáveis;
* objetivos;
* ações permitidas;
* ações a evitar;

Evitar abstrações soltas.

Evitar respostas prontas.

Evitar scripts.

O objetivo é capturar como um óptico experiente pensa e como interpreta comportamentos de clientes.

---

# CLUSTER 001 — COMPARAÇÃO DE OPÇÕES

```json
{
  "cluster_name": "comparacao_de_opcoes",

  "observable_patterns": [
    "vou pesquisar",
    "vou olhar outras opções",
    "vou comparar",
    "vou dar mais uma olhada"
  ],

  "detected_state":
    "diferenciacao_insuficiente",

  "next_objective":
    "mostrar_criterios_de_escolha",

  "allowed_actions": [
    "explicar_diferencas",
    "explicar_criterios",
    "explicar_beneficios"
  ],

  "avoid_actions": [
    "pressionar_decisao",
    "criticar_concorrentes"
  ]
}
```

---

# CLUSTER 002 — VALOR NÃO PERCEBIDO

```json
{
  "cluster_name": "valor_nao_percebido",

  "observable_patterns": [
    "está caro",
    "tem algo mais barato",
    "vou pesquisar preço",
    "achei caro"
  ],

  "detected_state":
    "valor_nao_percebido",

  "next_objective":
    "explicar_diferencas_relevantes",

  "allowed_actions": [
    "explicar_criterios",
    "explicar_beneficios",
    "explicar_aplicacoes"
  ],

  "avoid_actions": [
    "baixar_preco_imediatamente",
    "pressionar_fechamento"
  ]
}
```

---

# CLUSTER 003 — PEDIDO DE RECOMENDAÇÃO

```json
{
  "cluster_name":
    "pedido_de_recomendacao",

  "observable_patterns": [
    "qual lente é melhor",
    "qual você recomenda",
    "qual é a melhor opção"
  ],

  "detected_state":
    "necessidade_nao_mapeada",

  "next_objective":
    "entender_rotina_do_cliente",

  "allowed_actions": [
    "investigar_rotina",
    "investigar_uso",
    "investigar_experiencia_anterior"
  ],

  "avoid_actions": [
    "recomendar_produto_sem_contexto"
  ]
}
```

---

# CLUSTER 004 — RECEIO DE ADAPTAÇÃO

```json
{
  "cluster_name":
    "receio_de_adaptacao",

  "observable_patterns": [
    "tenho medo de não me adaptar",
    "já ouvi falar que é difícil",
    "não sei se vou conseguir usar"
  ],

  "detected_state":
    "risco_percebido_alto",

  "next_objective":
    "aumentar_seguranca",

  "allowed_actions": [
    "explicar_processo",
    "explicar_adaptacao",
    "relacionar_com_rotina"
  ],

  "avoid_actions": [
    "garantir_adaptacao",
    "prometer_resultado_imediato"
  ]
}
```
---

# INFORMATION_GAP_PATTERNS

## PATTERN 001 — LENTE SEM CONTEXTO

{
  "pattern_name":
    "lente_sem_contexto",

  "trigger_examples": [
    "qual lente é melhor",
    "qual você recomenda",
    "qual lente devo usar"
  ],

  "detected_state":
    "criterios_insuficientes",

  "missing_information": [
    "rotina",
    "uso",
    "experiencia_anterior"
  ],

  "next_objective":
    "obter_criterios",

  "avoid_actions": [
    "recomendar_sem_contexto"
  ]
}

---

## PATTERN 002 — ARMAÇÃO SEM RECEITA

{
  "pattern_name":
    "armacao_sem_receita",

  "trigger_examples": [
    "essa armação serve",
    "posso usar essa armação"
  ],

  "detected_state":
    "informacao_tecnica_insuficiente",

  "missing_information": [
    "receita",
    "grau",
    "tipo_de_lente"
  ],

  "next_objective":
    "obter_informacoes_tecnicas",

  "avoid_actions": [
    "confirmar_compatibilidade_sem_dados"
  ]
}

---

## PATTERN 003 — MULTIFOCAL SEM NECESSIDADE MAPEADA

{
  "pattern_name":
    "multifocal_sem_contexto",

  "trigger_examples": [
    "vale a pena multifocal",
    "devo usar multifocal"
  ],

  "detected_state":
    "necessidade_nao_mapeada",

  "missing_information": [
    "rotina_visual",
    "idade",
    "dificuldade_visual"
  ],

  "next_objective":
    "entender_necessidade",

  "avoid_actions": [
    "indicar_multifocal_sem_contexto"
  ]
}

---

# EXPERT_REFRAMING_PATTERNS

## PATTERN 001

{
  "customer_question":
    "qual lente é melhor",

  "specialist_reframe":
    "melhor_para_qual_rotina",

  "next_objective":
    "entender_contexto"
}

---

## PATTERN 002

{
  "customer_question":
    "essa armação serve",

  "specialist_reframe":
    "serve_para_qual_receita",

  "next_objective":
    "obter_criterios_tecnicos"
}

---

## PATTERN 003

{
  "customer_question":
    "vale a pena multifocal",

  "specialist_reframe":
    "qual_problema_visual_precisa_ser_resolvido",

  "next_objective":
    "identificar_necessidade_real"
}

---

# RISK_ALERT_PATTERNS

## PATTERN 001 — DECISÃO BASEADA APENAS EM PREÇO

{
  "risk_name":
    "decisao_baseada_apenas_em_preco",

  "observable_patterns": [
    "qual é a mais barata",
    "quero gastar o mínimo possível",
    "só quero a mais barata"
  ],

  "detected_state":
    "criterios_limitados",

  "next_objective":
    "ampliar_criterios_de_decisao"
}

---

## PATTERN 002 — HISTÓRICO NEGATIVO

{
  "risk_name":
    "historico_negativo",

  "observable_patterns": [
    "já tive problema antes",
    "não gostei da outra lente",
    "não me adaptei"
  ],

  "detected_state":
    "risco_percebido_alto",

  "next_objective":
    "identificar_causa_anterior"
}

---

## PATTERN 003 — EXPECTATIVA IRREAL

{
  "risk_name":
    "expectativa_irreal",

  "observable_patterns": [
    "vou enxergar perfeitamente na hora",
    "não quero adaptação",
    "não quero nenhuma dificuldade"
  ],

  "detected_state":
    "expectativa_nao_alinhada",

  "next_objective":
    "alinhar_expectativas"
}

# TRUST_BUILDING_PATTERNS

## PATTERN 001 — EXPLICAR CRITÉRIOS

{
  "trust_action":
    "explicar_criterios",

  "observable_effect":
    "aumentar_seguranca",

  "examples": [
    "explicar como a lente é escolhida",
    "explicar fatores considerados",
    "explicar diferenças relevantes"
  ]
}

---

## PATTERN 002 — EXPLICAR PROCESSO

{
  "trust_action":
    "explicar_processo",

  "observable_effect":
    "reduzir_incerteza",

  "examples": [
    "mostrar etapas da indicação",
    "mostrar sequência de avaliação",
    "explicar como a recomendação é construída"
  ]
}

---

## PATTERN 003 — INVESTIGAR EXPERIÊNCIA ANTERIOR

{
  "trust_action":
    "investigar_experiencia_anterior",

  "observable_effect":
    "demonstrar_interesse_real",

  "examples": [
    "entender problemas anteriores",
    "identificar dificuldades anteriores",
    "entender adaptação anterior"
  ]
}

SPECIALIST_VS_BEGINNER_PATTERNS

## PATTERN 001

{
  "scenario":
    "pedido_de_recomendacao",

  "beginner_behavior":
    "indicar_produto",

  "specialist_behavior":
    "obter_criterios",

  "preferred_behavior":
    "specialist_behavior"
}

---

## PATTERN 002

{
  "scenario":
    "objecao_de_preco",

  "beginner_behavior":
    "defender_preco",

  "specialist_behavior":
    "explicar_criterios",

  "preferred_behavior":
    "specialist_behavior"
}

---

## PATTERN 003

{
  "scenario":
    "historico_negativo",

  "beginner_behavior":
    "oferecer_solucao_imediata",

  "specialist_behavior":
    "investigar_causa",

  "preferred_behavior":
    "specialist_behavior"
}

