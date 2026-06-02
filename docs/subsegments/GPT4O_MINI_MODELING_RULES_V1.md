# GPT-4o-mini — Regras de Modelagem para Subsegmentos

## Objetivo

Modelar os subsegmentos do MEI ROBÔ para que o GPT-4o-mini consiga usar o conhecimento com consistência, objetividade e boa resposta comercial.

O foco não é escrever para humanos.
O foco é estruturar conhecimento para o modelo consumir bem.

## Regra central

Sempre que possível, transformar conhecimento em:

- detected_state
- next_objective
- allowed_actions
- avoid_actions

## Evitar

- abstrações soltas;
- textos enciclopédicos;
- instruções subjetivas;
- excesso de possibilidades;
- verbos vagos como interpretar, considerar, avaliar, refletir.

## Preferir

- padrões observáveis;
- estados claros;
- objetivos diretos;
- ações permitidas;
- ações a evitar;
- direção segura de resposta.

## Exemplo ruim

```json
{
  "customer_psychology": "cliente inseguro"
}