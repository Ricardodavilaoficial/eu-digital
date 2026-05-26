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
