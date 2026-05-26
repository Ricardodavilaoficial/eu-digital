# FRONT KB RUNTIME BOUNDARY

## Objetivo

Mapear os limites arquiteturais entre:

- KB runtime materialization;
- runtime governance;
- orchestration;
- recovery;
- operational reconstruction.

Este documento descreve:
- o que pertence ao `front_kb.py`;
- o que NÃO pertence;
- boundaries SAFE;
- boundaries SOVEREIGN;
- riscos de contaminação runtime.

---

# Descoberta central

O KB runtime NÃO é:
- discovery governance;
- response arbitration;
- runtime recovery;
- orchestration soberana;
- scene governance.

O KB runtime é:

`MATERIALIZAÇÃO OPERACIONAL`

---

# Boundary confirmado

## Módulo

`services/front_kb.py`

## Classificação

`KB RUNTIME MATERIALIZATION ENGINE`

---

# Responsabilidades legítimas do KB ENGINE

## Parsing de KB runtime

Responsável por:
- parsing de `kb_snapshot`;
- parsing de material runtime;
- leitura de payload KB;
- serialização estrutural.

---

## Material selection auxiliar

Responsável por:
- composição de material operacional;
- compact fallback material;
- runtime_short;
- runtime_long;
- slot filling estrutural.

---

## Estruturação operacional

Responsável por:
- montagem de material textual;
- serialização compacta;
- organização estrutural do runtime material.

---

# O que o KB ENGINE NÃO deve fazer

## NÃO deve executar

- discovery governance;
- response arbitration;
- scene governance;
- runtime recovery;
- orchestration soberana;
- terminals;
- operational reconstruction;
- recovery injection.

---

## NÃO deve decidir

- response_mode;
- discovery;
- scene eligibility;
- clarify necessity;
- runtime continuity;
- scene promotion;
- scene degradation.

---

# PURE KB vs SOVEREIGN

## PURE KB

Pode:
- parse;
- serialize;
- compact;
- structure;
- organize material runtime.

---

## SOVEREIGN

Controla:
- governance;
- arbitration;
- orchestration;
- recovery;
- runtime resurrection;
- scene activation.

Nunca misturar.

---

# Runtime hydration boundary

## Responsabilidade legítima

O KB runtime pode:
- hidratar material;
- disponibilizar payload;
- estruturar runtime material.

---

## O que NÃO pode fazer

Não pode:
- ativar scene;
- forçar SCENE;
- reabrir recovery;
- executar resurrection;
- alterar arbitration.

---

# Runtime recovery boundary

## Descoberta crítica

Recovery runtime NÃO pertence ao:
- `front_kb.py`

Mesmo quando usa material KB.

---

## Recovery pertence a

`RUNTIME RECOVERY GOVERNANCE`

---

## Helpers associados

- `_build_kb_show_reply(...)`
- `_build_kb_anchor_reply(...)`
- `_build_last_resort_operational_reply(...)`

---

## Motivo

Esses helpers:
- executam recovery;
- alteram runtime;
- executam resurrection;
- podem reabrir orchestration;
- podem mutar conteúdo soberano.

---

# Operational reconstruction boundary

## Descoberta crítica

Micro_scene generation NÃO pertence ao:
- KB ENGINE.

---

## Reconstruction pertence a

`OPERATIONAL RECONSTRUCTION ENGINE`

---

## Motivo

Reconstruction:
- gera progressão;
- cria sequência operacional;
- produz narrativa operacional;
- depende de governança soberana.

---

# Runtime orchestration boundary

## Descoberta crítica

Runtime orchestration NÃO pertence ao:
- KB ENGINE.

---

## Orchestration pertence a

`SOVEREIGN ORCHESTRATION`

---

## Helpers associados

- `_apply_response_mode_arbitration(...)`
- `_apply_discovery_to_scene_bypass(...)`
- `_pick_runtime_scene_material(...)`

---

# Risks conhecidos

## PACK_A bleed

Pode ocorrer quando:
- material KB invade governance;
- fallback runtime contamina orchestration;
- compact fallback vira source soberana indevida.

---

## Scene resurrection

Pode ocorrer quando:
- recovery runtime reutiliza material KB;
- resurrection reabre scene indevidamente;
- orchestration perde controle de gating.

---

## Runtime contamination

Pode ocorrer quando:
- hydration;
- recovery;
- orchestration;
- reconstruction;

misturam ownerships.

---

# SAFE vs HIGH RISK

## SAFE

Pode:
- parse;
- serialize;
- structure;
- compact;
- hydrate.

---

## HIGH RISK

Nunca mover cedo:
- recovery runtime;
- reconstruction;
- arbitration;
- scene activation;
- governance.

---

# Dependências confirmadas do front_kb.py

## Dependências saudáveis

- `json`
- `re`
- `typing`

---

## Ausências importantes

O módulo NÃO:
- chama IA;
- acessa Firestore;
- executa recovery;
- executa terminals;
- executa orchestration soberana.

---

# Estado atual

O `front_kb.py` já demonstra:
- boundary estável;
- baixo leakage soberano;
- separação saudável;
- modularização segura.

É atualmente um dos módulos mais saudáveis da refatoração.

---

# Decisão consolidada

O KB runtime deve permanecer:

`ENGINE DE MATERIALIZAÇÃO`

E NÃO:
- engine de decisão;
- engine de recovery;
- engine de reconstruction;
- engine de orchestration.

---

# Conclusão

O boundary correto do KB runtime é:

`ESTRUTURAR MATERIAL`

e NÃO:
- governar runtime;
- arbitrar modos;
- ativar scenes;
- executar recovery;
- reconstruir fluxo operacional.

Misturar esses domínios foi uma das principais causas históricas de:
- PACK_A bleed;
- tutorialização;
- resurrection bugs;
- runtime contamination.