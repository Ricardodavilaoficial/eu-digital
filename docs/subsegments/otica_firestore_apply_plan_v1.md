# Ótica — Plano de Aplicação Futura no Firestore

## Objetivo
Aplicar futuramente a camada de expertise ampliada no documento:

kb_subsegments_v1/comercio_varejista__loja_oculos

sem mexer agora em Cloud Run, runtime ou produção.

## Arquivos preparados

- docs/subsegments/otica_expertise_blueprint_v1.md
- tools/subsegments/comercio_varejista__loja_oculos_expertise_patch.json

## Estratégia de aplicação

1. Manter o subsegmento atual como base.
2. Aplicar os novos campos por merge.
3. Não sobrescrever campos operacionais existentes.
4. Não remover campos atuais.
5. Validar JSON antes de aplicar.
6. Rodar primeiro em modo dry-run.
7. Aplicar no Firestore somente quando o ambiente estiver disponível.
8. Testar se o snapshot carrega os novos campos.
9. Testar WhatsApp com perguntas técnicas, comerciais e objeções.

## Campos novos

- domain_expertise
- common_misconceptions
- decision_factors
- common_objections
- adaptation_scenarios
- customer_psychology
- risk_points
- specialist_topics
- sales_principles
- account_customization_slots

## Regra arquitetural

A KB não responde pelo robô.
A IA responde usando a KB.

Portanto, os novos campos devem ser usados como raciocínio profissional estruturado, não como script fixo.

## Risco principal

O front pode ainda não incluir automaticamente os novos campos no snapshot enviado à IA.

## Validação futura necessária

Depois de aplicar o patch no Firestore, verificar nos logs/snapshot se os campos novos aparecem para o front.

Se não aparecerem, fazer ajuste mínimo no pipeline de KB, provavelmente em front_kb.py ou no ponto de montagem do snapshot em wa_bot.py/conversational_front.py.

## Testes obrigatórios

1. Cliente: "Como sei se uma armação serve para minha lente?"
2. Cliente: "Por que essa lente é mais cara?"
3. Cliente: "Tenho medo de não me adaptar ao multifocal."
4. Cliente: "Qual lente é melhor para quem usa computador?"
5. Cliente: "Posso usar minha receita antiga?"
6. Cliente: "Essa promoção vale até quando?"
7. Cliente: "Quero a armação mais bonita, mas meu grau é alto."

## Resultado esperado

A resposta deve parecer consultiva, segura e específica de ótica, sem inventar preço, prazo, marca, promoção ou disponibilidade.