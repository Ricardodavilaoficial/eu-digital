# FRONT RUNTIME PACK FLOW

## Objetivo

Mapear o fluxo dos runtime packs dentro do:

`services/conversational_front.py`

Este documento descreve:
- uso de packs;
- fluxo de material runtime;
- fallback pack flow;
- riscos de contaminação;
- relação entre packs e orchestration.

---

# Descoberta central

Runtime packs NÃO são:
- governance;
- orchestration;
- discovery;
- response arbitration;
- scene authority.

Runtime packs são:

`MATERIAL OPERACIONAL AUXILIAR`

---

# Responsabilidade legítima dos packs

## Packs podem

- fornecer material operacional;
- enriquecer resposta;
- fornecer exemplos;
- fornecer fallback textual;
- alimentar compact material;
- apoiar structured assembly.

---

## Packs NÃO podem

- forçar SCENE;
- alterar response_mode;
- executar recovery soberano;
- substituir orchestration;
- ativar runtime resurrection;
- validar contexto operacional real.

---

# Runtime pack flow

## 1. Material hydration

O runtime:
- lê material KB;
- hidrata runtime_short/runtime_long;
- organiza compact material;
- prepara packs auxiliares.

---

## 2. Runtime availability

Os packs ficam disponíveis para:
- fallback;
- enrichment;
- structured assembly;
- operational enhancement.

---

## 3. Runtime usage

O runtime pode:
- reutilizar material;
- montar fallback compacto;
- reforçar densidade operacional;
- alimentar resposta DIRECT.

---

## 4. Final runtime consumption

O material pode chegar ao:
- FINAL PIPELINE;
- operational enhancement;
- structured assembly.

Mas NÃO deve:
- virar autoridade soberana.

---

# PACK_A_AGENDA

## Descoberta crítica

`PACK_A_AGENDA`
foi historicamente tratado de forma excessivamente soberana.

---

## Problemas observados

- tutorialização indevida;
- scene falsa;
- operacionalização artificial;
- resurrection de agenda;
- bleed estrutural;
- fallback contaminando SCENE.

---

## Causa estrutural

O pack passou a:
- agir como contrato operacional;
- agir como runtime authority;
- agir como scene source.

Quando deveria atuar apenas como:
`MATERIAL AUXILIAR`

---

# Runtime contamination

## Ocorre quando

- pack vira autoridade;
- compact material ganha soberania;
- fallback vira source principal;
- orchestration perde controle;
- recovery reutiliza pack indevidamente.

---

# PACK vs SCENE

## PACK

É:
- apoio operacional;
- material auxiliar;
- enrichment;
- fallback.

---

## SCENE

Exige:
- contexto real;
- progression válida;
- grounded operational flow;
- governance soberana;
- gating.

---

## Regra crítica

PACK sozinho:
NUNCA valida SCENE.

---

# PACK vs ORCHESTRATION

## PACK NÃO decide

- response_mode;
- scene activation;
- discovery;
- runtime continuity;
- orchestration flow.

---

## ORCHESTRATION decide

- promotion;
- degradation;
- activation;
- continuity;
- runtime trajectory.

---

# Runtime fallback flow

## Uso legítimo

Fallback pode:
- reutilizar material pack;
- montar compact reply;
- enriquecer DIRECT;
- preservar densidade.

---

## Uso ilegítimo

Fallback NÃO pode:
- ressuscitar SCENE;
- inventar contexto operacional;
- bypassar gating;
- transformar DIRECT em tutorial.

---

# Compact runtime material

## Objetivo legítimo

- reduzir payload;
- preservar densidade operacional;
- alimentar fallback seguro.

---

## Risco

Compact material pode:
- virar pseudo-authority;
- contaminar orchestration;
- gerar bleed estrutural.

---

# SAFE vs HIGH RISK

## SAFE

Uso seguro:
- enrichment;
- compact fallback;
- operational density;
- structured assembly auxiliar.

---

## HIGH RISK

Uso perigoso:
- recovery soberano;
- resurrection;
- fake scene activation;
- governance indireta;
- bypass de arbitration.

---

# Zonas congeladas

## PROIBIDO MOVER AGORA

- PACK_A_AGENDA runtime flow;
- recovery baseado em packs;
- resurrection via compact material;
- fallback que ativa SCENE;
- packs ligados a governance.

---

# Estado atual

O runtime já reconhece melhor:
- PACK ≠ SCENE;
- PACK ≠ governance;
- PACK ≠ orchestration.

Porém:
- recovery ainda pode reutilizar material indevidamente;
- compact material ainda pode contaminar fallback;
- PACK_A ainda exige estabilização.

---

# Decisão consolidada

Runtime packs devem permanecer:

`MATERIAL OPERACIONAL AUXILIAR`

E NÃO:
- authority layer;
- governance layer;
- orchestration layer;
- scene authority.

---

# Conclusão

A regra arquitetural consolidada é:

`PACK APOIA. GOVERNANÇA DECIDE.`

Grande parte dos bugs históricos ocorreu quando:
- fallback;
- compact material;
- recovery;
- orchestration;

passaram a tratar packs como fonte soberana de runtime.