# FRONT KB RUNTIME HUBS

## Objetivo

Mapear os hubs KB/runtime do:

`services/conversational_front.py`

Este documento identifica:
- pontos de concentração de material KB;
- hubs de hidratação;
- hubs de fallback;
- hubs de recovery;
- riscos de acoplamento;
- fronteiras entre KB materialization e runtime sovereignty.

---

# Descoberta central

Nem todo ponto que usa KB pertence ao `front_kb.py`.

Existem dois tipos de hubs:

## PURE KB HUBS
Responsáveis por:
- parse;
- estruturação;
- compactação;
- materialização;
- serialização.

## SOVEREIGN RUNTIME HUBS
Responsáveis por:
- recovery;
- arbitration;
- scene activation;
- operational resurrection;
- fallback runtime.

---

# PURE KB HUBS

## Responsabilidade

Podem:
- ler material KB;
- estruturar campos;
- compactar payloads;
- preparar runtime material;
- devolver dados sem decidir fluxo.

---

## Classificação

`SAFE / KB MATERIALIZATION`

---

# SOVEREIGN RUNTIME HUBS

## Responsabilidade

Podem:
- usar KB;
- reabrir recovery;
- recompor resposta;
- ativar scene;
- reconstruir operação;
- alterar trajetória runtime.

---

## Classificação

`HIGH RISK SOVEREIGN`

---

# Hubs legítimos do front_kb.py

## Parsing hub

Responsável por:
- `_try_parse_kb_json(...)`;
- leitura segura de material KB;
- normalização estrutural.

---

## Compact material hub

Responsável por:
- compactar material runtime;
- preparar fallback compacto;
- organizar runtime_short/runtime_long.

---

## Slot/material hub

Responsável por:
- preencher slots;
- estruturar frases;
- serializar material operacional.

---

# Hubs que NÃO pertencem ao front_kb.py

## Runtime recovery hub

Inclui:
- `_build_kb_show_reply(...)`
- `_build_kb_anchor_reply(...)`
- `_build_last_resort_operational_reply(...)`

Motivo:
- executam recovery;
- recompõem resposta;
- podem ressuscitar cena;
- alteram trajetória runtime.

Classificação:
`RUNTIME RECOVERY GOVERNANCE`

---

## Scene reconstruction hub

Inclui:
- `_generate_micro_scene_with_model(...)`
- `_compose_grounded_scene_with_progression(...)`
- `_select_structured_scene_steps(...)`

Motivo:
- geram progressão;
- montam cena;
- reconstroem operação;
- dependem de governança soberana.

Classificação:
`OPERATIONAL RECONSTRUCTION ENGINE`

---

## Response orchestration hub

Inclui:
- `_pick_runtime_scene_material(...)`
- `_apply_discovery_to_scene_bypass(...)`
- `_apply_response_mode_arbitration(...)`

Motivo:
- escolhem trajetória;
- promovem/degradam modo;
- sincronizam runtime;
- não apenas materializam dados.

Classificação:
`SOVEREIGN ORCHESTRATION`

---

# Riscos principais

## 1. PACK_A bleed

Ocorre quando:
- material genérico vira fonte soberana;
- fallback invade cena;
- compact material ganha autoridade runtime indevida.

---

## 2. Tutorialização indevida

Ocorre quando:
- fallback operacional é tratado como cena validada;
- KB genérica vira demonstração;
- runtime ignora gating.

---

## 3. Scene resurrection

Ocorre quando:
- recovery usa KB para reabrir cena;
- runtime final ressuscita conteúdo operacional indevido;
- fallback reativa fluxo que deveria permanecer DIRECT.

---

## 4. Runtime contamination

Ocorre quando:
- materialization;
- recovery;
- reconstruction;
- orchestration;

ficam misturados no mesmo helper.

---

# Regras de separação

## KB ENGINE pode

- parsear;
- normalizar;
- compactar;
- estruturar;
- serializar;
- devolver material.

---

## KB ENGINE não pode

- decidir modo;
- ativar cena;
- executar recovery;
- reconstruir operação;
- alterar runtime;
- controlar terminal.

---

# SAFE vs HIGH RISK

## SAFE KB HUB

Características:
- sem IA;
- sem Firestore;
- sem response_mode mutation;
- sem recovery;
- sem terminal decision.

---

## HIGH RISK HUB

Características:
- gera conteúdo;
- altera fluxo;
- executa recovery;
- ativa scene;
- toca response_mode;
- recompõe payload final.

---

# Estado atual

`services/front_kb.py` é saudável quando limitado a:

`KB RUNTIME MATERIALIZATION`

O risco aparece quando material KB é usado por:
- recovery;
- reconstruction;
- orchestration;
- terminal governance.

---

# Decisão consolidada

O objetivo não é mover todo uso de KB para `front_kb.py`.

O objetivo é:
- manter `front_kb.py` como engine pura;
- deixar recovery no core;
- deixar reconstruction no core;
- deixar orchestration no core;
- só mover hubs materializadores puros.

---

# Conclusão

A regra arquitetural é:

`KB PODE MATERIALIZAR. KB NÃO PODE GOVERNAR.`

Qualquer helper que usa KB para decidir, recuperar, reconstruir ou ativar cena pertence ao core soberano até nova auditoria.