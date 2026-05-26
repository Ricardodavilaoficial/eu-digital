# RUNTIME RESPONSE ORCHESTRATION MAP

## Objetivo

Mapear o bloco de orquestração estrutural do `conversational_front.py`.

Este documento NÃO é para correção comportamental.
É para preparar futura extração segura.

---

# Zona principal

Arquivo:
- services/conversational_front.py

Região atual aproximada:
- 8775–9185+

Nome arquitetural:
- RUNTIME RESPONSE ORCHESTRATION

Responsabilidade:
- selecionar material operacional em runtime;
- arbitrar `response_mode`;
- controlar `micro_scene_allowed`;
- aplicar bypass estrutural de DISCOVERY;
- reforçar material tardio do `platform_kb`;
- preparar `operational_contract` antes do `FINAL PIPELINE`.

---

# Subdomínios identificados

## 1. Runtime material selection

Responsável por escolher o melhor material do pack:
- `direct_scene`
- `runtime_long_text`
- `runtime_short_reply`
- `runtime_compact_reply`
- `micro_scene`

Observação:
- quando `has_real_operational_context=True`, permite material mais rico;
- quando `has_real_operational_context=False`, tenta preservar material compacto e evitar proceduralismo pesado.

---

## 2. Response mode arbitration

Responsável por rebaixar/elevar modo:

- `SEND_LINK` → `CLOSING`
- `global_pack_scene_ready` → `SCENE`
- `needs_clarify/clarify_q` → `DISCOVERY`
- pergunta `punctual/continuity` → força `DIRECT`
- temas institucionais/preço/social/voz → evitam `SCENE`

Observação:
esta região parece ser o centro soberano atual de decisão estrutural.

---

## 3. Discovery bypass

Responsável por permitir que contrato operacional real prevaleça sobre `DISCOVERY` quando já existe base demonstrativa suficiente.

Sinais:
- `has_real_operational_context`
- contrato com referência prática
- sem `SEND_LINK`
- sem `needs_clarify`
- sem `clarify_q`

---

## 4. Micro scene gating

Responsável por calcular `micro_scene_allowed`.

Sinais:
- `response_mode == "SCENE"`
- `segment_for_prompt`
- `kb_anchor_strong`
- `global_pack_scene_ready`
- contrato hidratado com base operacional

Também força `micro_scene_allowed=False` para:
- `DIRECT`
- `DISCOVERY`
- `CLOSING`

---

## 5. Direct scene / wrapper shaping

Responsável por permitir wrapper humano em fallback DIRECT compacto.

Importante:
não reabre SCENE procedural.
Apenas permite camada humana sobre material compacto.

---

## 6. Late KB reinforcement

Responsável por reforçar material do `platform_kb` antes do retorno direto.

Funções:
- busca `_platform_pack_material`
- escolhe `_best_scene`
- limpa campos pesados quando não há contexto real
- preserva núcleo compacto humanizável
- sincroniza flags em `operational_contract`

Risco:
alto. Não extrair sem testes e leitura completa.

---

# Zonas congeladas

Não mexer ainda:

- lógica de `global_pack_scene_ready`
- cálculo de `micro_scene_allowed`
- late KB reinforcement
- limpeza de campos em `operational_contract`
- decisão `DIRECT ↔ SCENE`
- fallback compacto
- JSON_FAIL_SAFE próximo ao bloco

---

# Próximo trabalho

Classificar cada subdomínio como:

- EXTRAÍVEL AGORA
- EXTRAÍVEL DEPOIS
- CONGELADO
- LEGADO
- DUPLICADO
- CRÍTICO

---

# Decisão atual

Ainda não extrair para módulo.

Manter como zona delimitada dentro do `conversational_front.py` até:
- mapear duplicações;
- entender dependências;
- validar com deploy controlado.

---

# Classificação inicial de risco — 2026-05-26

## Runtime material selection
Risco: médio.

Pode ser extraível depois, mas ainda depende de:
- `selected_pack_id`
- `_platform_pack_material`
- `has_real_operational_context`
- `operational_contract`
- `runtime_*`

Decisão:
não extrair agora.

## Response mode arbitration
Risco: médio/alto.

Parece ser o centro soberano atual de decisão estrutural.
Qualquer alteração pode mudar DIRECT/SCENE/DISCOVERY/CLOSING.

Decisão:
congelado para extração por enquanto.

## Discovery bypass
Risco: médio.

É pequeno, mas altera DISCOVERY para SCENE quando há contrato operacional.
Pode ser helper futuro, mas só após testes.

Decisão:
mapear mais antes.

## Micro scene gating
Risco: alto.

Controla `micro_scene_allowed` e pode reabrir tutorialização indevida.

Decisão:
não extrair agora.

## Direct scene / wrapper shaping
Risco: médio.

Pode ser isolado futuramente, mas depende de:
- `has_structured_scene`
- `global_pack_fallback`
- `runtime_compact_reply`
- `question_type`

Decisão:
aguardar.

## Late KB reinforcement
Risco: alto.

Muito acoplado a platform_kb, fallback compacto e limpeza do contrato.

Decisão:
congelado.

---

# Atualização — Discovery bypass extraído

Commits:
- 4aefeed — adiciona helper de discovery scene bypass
- 98f4e7e — aplica helper no discovery scene bypass

## Resultado

O subdomínio “Discovery bypass” foi encapsulado em helper local:

`_apply_discovery_to_scene_bypass(...)`

Responsabilidade:
- promover `DISCOVERY` para `SCENE` quando já existe contrato operacional demonstrável;
- limpar `needs_clarify`;
- limpar `clarify_q`;
- marcar `micro_scene_allowed=True`;
- atualizar `response_mode` no contrato.

## Decisão

Manter helper local por enquanto.
Não mover para módulo ainda.

---

# Atualização — Runtime scene material extraído

Commits:
- 2ed9322 — adiciona helper de runtime scene material
- 71d9e8c — usa helper no runtime scene material

## Resultado

A seleção do melhor material operacional em runtime foi encapsulada em:

`_pick_runtime_scene_material(...)`

Responsabilidade:
- escolher o melhor texto entre:
  - `direct_scene`
  - `runtime_long_text`
  - `runtime_short_reply`
  - `runtime_compact_reply`
  - `micro_scene`

Importante:
- o helper NÃO muta `operational_contract`;
- NÃO altera `response_mode`;
- NÃO chama modelo;
- NÃO consulta KB;
- apenas preserva a prioridade de seleção já existente.

## Decisão

Manter helper local por enquanto.
A mutação do contrato operacional continua congelada dentro do bloco principal.

---

# Atualização — Current turn topic reset extraído

Commit:
- eb398f4 — refactor: encapsula reset de topico no front

## Resultado

O reset estrutural de tópico foi encapsulado em helper local:

`_apply_current_turn_topic_reset(...)`

Responsabilidade:
- quando `current_turn_topic_reset=True`, força `response_mode="DIRECT"`;
- desliga `micro_scene_allowed`;
- marca `topic="OTHER"` no contrato;
- limpa `has_practical_scene`;
- limpa `global_pack_fallback`.

## Decisão

Manter helper local por enquanto.

Não mover para módulo ainda.

## Observação

O próximo bloco candidato seria `global_pack_scene_ready`, mas ele permanece congelado porque encosta diretamente em:
- fallback global;
- promoção para `SCENE`;
- bug conhecido do PACK_A_AGENDA tutorializando respostas.
