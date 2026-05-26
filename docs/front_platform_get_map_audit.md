# FRONT PLATFORM GET MAP AUDIT

## Objetivo

Auditar os fluxos de GET MAP dentro do:

`services/conversational_front.py`

Este documento descreve:
- retrieval de maps;
- boundaries corretos;
- riscos de contaminação;
- relação entre map retrieval e runtime sovereignty.

---

# Descoberta central

GET MAP NÃO é:
- orchestration;
- runtime governance;
- recovery;
- arbitration;
- scene validation.

GET MAP é:

`RETRIEVAL ESTRUTURAL DE MATERIAL`

---

# Responsabilidade legítima do GET MAP

## Pode

- localizar maps;
- recuperar material;
- hidratar payload;
- estruturar dados;
- devolver candidates.

---

## NÃO pode

- arbitrar runtime;
- validar scene;
- promover response_mode;
- executar recovery;
- ativar SCENE;
- alterar terminals.

---

# Retrieval flow

## 1. Lookup

O runtime:
- localiza maps;
- identifica candidatos;
- executa matching.

---

## 2. Retrieval

O runtime:
- recupera material;
- hidrata estrutura;
- organiza payload.

---

## 3. Material availability

O material fica disponível para:
- assembly;
- enrichment;
- compact fallback;
- operational density.

---

## 4. Runtime decision

Somente depois:
- orchestration;
- governance;
- arbitration;

decidem:
- uso;
- activation;
- continuidade.

---

# GET MAP NÃO governa runtime

## Regra consolidada

Encontrar material:
NÃO significa:
- runtime legitimacy;
- operational validity;
- scene authorization;
- recovery permission.

---

# Retrieval contamination

## Ocorre quando

- retrieval vira authority;
- map matching redefine runtime;
- hydration altera orchestration;
- retrieval bypassa governance.

---

# GET MAP vs SCENE

## GET MAP

Pode:
- encontrar material;
- localizar contracts;
- hidratar payload.

---

## SCENE

Exige:
- grounded operational context;
- orchestration soberana;
- progression legítima;
- gating válido.

---

## Regra crítica

GET MAP:
NUNCA valida SCENE sozinho.

---

# GET MAP vs RECOVERY

## Descoberta crítica

Recovery reutilizando retrieval é:
`HIGH RISK`

---

## Motivo

Recovery pode:
- reinterpretar material;
- ressuscitar fallback;
- reabrir SCENE;
- transformar retrieval em pseudo-authority.

---

# GET MAP vs ORCHESTRATION

## GET MAP NÃO decide

- response_mode;
- activation;
- continuity;
- degradation;
- promotion;
- runtime trajectory.

---

## ORCHESTRATION decide

- activation;
- arbitration;
- continuity;
- runtime flow.

---

# SAFE vs HIGH RISK

## SAFE retrieval

Pode:
- localizar;
- hidratar;
- estruturar;
- devolver material.

---

## HIGH RISK retrieval usage

Perigoso quando:
- retrieval vira recovery source;
- matching vira authority;
- hydration altera governance;
- retrieval ativa scene implicitamente.

---

# Acoplamentos aceitáveis

## Retrieval → KB materialization

Saudável:
- lookup;
- retrieval;
- hydration;
- compact support.

---

## Retrieval → Assembly

Saudável:
- structured material usage;
- operational density;
- enrichment auxiliar.

---

# Acoplamentos perigosos

## Retrieval → Recovery

Risco:
- resurrection;
- fallback bleed;
- pseudo-contract recovery.

---

## Retrieval → Scene governance

Risco:
- retrieval virar legitimacy source;
- material virar pseudo-scene.

---

## Retrieval → Arbitration

Risco:
- match passar a decidir runtime trajectory.

---

# Estado atual

Os fluxos GET MAP já demonstram:
- boundaries razoáveis;
- baixo leakage direto;
- bom potencial de modularização futura.

Porém:
- recovery ainda pode reinterpretar material;
- orchestration ainda reutiliza retrieval contextualmente;
- fallback ainda pode contaminar runtime.

---

# Possível boundary futuro

## `front_lookup.py`

Poderia futuramente concentrar:
- lookup;
- retrieval;
- candidate matching;
- hydration auxiliar.

---

## NÃO deveria conter

- recovery;
- arbitration;
- scene governance;
- orchestration;
- runtime continuity.

---

# Decisão consolidada

GET MAP deve permanecer:

`CAMADA DE RETRIEVAL`

E NÃO:
- camada de decisão;
- camada de legitimacy;
- camada de recovery;
- camada de orchestration.

---

# Conclusão

A auditoria confirmou:

`GET MAP RECUPERA. RUNTIME SOBERANO DECIDE.`

Grande parte dos riscos estruturais aparece quando:
- retrieval;
- hydration;
- matching;

passam a ser tratados como autoridade soberana de runtime.