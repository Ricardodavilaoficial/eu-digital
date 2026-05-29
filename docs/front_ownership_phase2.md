# MEI ROBÔ — Refatoração Segura — Ownership Phase 2

## Fase 1 concluída

Foi aplicado o commit `e9fb9c2`:

refactor: centraliza governanca de continuidade no front

Resultado observado:
- broad inicial continuou broad/comercial;
- pergunta pontual continuou curta e objetiva;
- continuidade final deixou de rodar em broad;
- reclassificação tardia `broad -> continuity` foi removida;
- não houve regressão evidente no teste inicial.

## Diagnóstico consolidado

O problema arquitetural principal permanece sendo ownership fragmentado.

A regra-alvo é:

IA soberana:
- entende intenção;
- decide se precisa esclarecer;
- redige resposta humanizada.

Python:
- hidrata fatos;
- audita contrato;
- protege superfície;
- aplica fallback apenas em falha objetiva;
- não disputa autoria sem necessidade.

## Descoberta da fase 2

A `Structured Assembly` não parece ser a origem do problema.

Ela foi criada para:
- enriquecer com KB;
- organizar fatos;
- preservar resposta atual quando possível;
- não usar prompt;
- não usar palavra-chave rígida.

Porém hoje ela ainda assume ownership total em dois pontos:

FREE_MODE:
- `reply_source = "front_structured_python_assembly"`

Caminho comum:
- `reply_source = "front_structured_python_assembly"`

Isso significa que ela atua como enriquecedora, mas é registrada e tratada como autora.

## Risco identificado

Não devemos remover a Structured Assembly agora.

Ela provavelmente sustenta respostas comerciais mais densas, principalmente quando o GPT-4o-mini responde curto demais.

O risco de remover ou bloquear esse bloco é perder:
- densidade operacional;
- apoio factual do platform_kb;
- respostas de 600–800 caracteres;
- robustez em cenário sem documento segmentado.

## Próxima meta arquitetural

FASE 2 — GOVERNANÇA DA STRUCTURED ASSEMBLY

Objetivo:
transformar a Structured Assembly de autora final implícita em enriquecedora/auditora rastreada.

Direção provável:
- preservar resposta IA quando já aprovada;
- permitir assembly complementar quando houver ganho factual claro;
- registrar se houve enriquecimento ou substituição;
- evitar que `reply_source` esconda a origem conversacional real;
- manter fallback apenas para falha objetiva.

## Não fazer agora

- Não mexer em prompt.
- Não mexer em KB.
- Não mexer em trim/acabamento.
- Não remover Structured Assembly.
- Não trocar lógica por palavra-chave.
- Não aplicar patch grande.

## Próximo passo sugerido

Mapear os dois pontos de chamada da Structured Assembly:

1. FREE_MODE em torno de `10824`.
2. Caminho comum em torno de `12589`.

Perguntas da próxima fase:
- quando ela deve enriquecer?
- quando ela pode substituir?
- como registrar owner original e owner final?
- como manter IA como autora quando a resposta dela passou no contrato mínimo?