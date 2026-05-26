# FRONT LOOKUP CLUSTER AUDIT

## Objetivo

Auditar os clusters de lookup do:

`services/conversational_front.py`

Este documento descreve:
- lookup helpers;
- scoring helpers;
- boundaries de lookup;
- riscos de contaminação;
- relação entre lookup e soberania runtime.

---

# Descoberta central

Lookup NÃO é:
- orchestration;
- governance;
- response arbitration;
- recovery;
- runtime authority.

Lookup é:

`MECANISMO DE LOCALIZAÇÃO E MATCH`

---

# Lookup clusters identificados

## 1. Lookup normalization cluster

Responsável por:
- normalização;
- limpeza textual;
- tokenização;
- preparação de comparação.

---

## Helpers associados

- `_normalize_lookup_key(...)`
- `_tokenize_lookup_text(...)`

---

## Classificação

`PURE SAFE`

---

# 2. Lookup scoring cluster

Responsável por:
- overlap scoring;
- ranking;
- similaridade;
- comparação estrutural.

---

## Helpers associados

- `_lookup_token_overlap_score(...)`
- `_best_doc_match(...)`

---

## Classificação

`SAFE`

---

# 3. Lookup retrieval cluster

Responsável por:
- localizar maps;
- encontrar material;
- recuperar documentos;
- estruturar match.

---

## Helpers associados

- `_find_kb_map_anywhere(...)`

---

## Classificação

`SAFE / KB MATERIALIZATION`

---

# Lookup NÃO governa runtime

## Lookup NÃO decide

- response_mode;
- discovery;
- scene eligibility;
- runtime continuity;
- orchestration flow;
- recovery.

---

## Lookup apenas fornece

- localização;
- scoring;
- ranking;
- candidate matching.

---

# Lookup NÃO valida SCENE

## Regra consolidada

Lookup encontrar material:
NÃO significa:
- grounded operational context;
- runtime legitimacy;
- valid scene activation.

---

## Portanto

Lookup:
NUNCA deve ativar SCENE sozinho.

---

# Lookup vs recovery

## Descoberta crítica

Recovery reutilizando lookup é:
`HIGH RISK`

---

## Motivo

Recovery:
- pode reinterpretar match;
- pode promover fallback;
- pode ressuscitar runtime;
- pode transformar match em authority.

---

# Lookup contamination

## Ocorre quando

- lookup começa a arbitrar;
- scoring ganha autoridade;
- matching redefine runtime;
- retrieval altera orchestration.

---

# SAFE vs HIGH RISK

## SAFE lookup

Pode:
- normalize;
- tokenize;
- score;
- rank;
- localizar material.

---

## HIGH RISK lookup usage

Perigoso quando:
- recovery usa lookup;
- orchestration delega decisão;
- scene gating depende de scoring;
- matching vira runtime authority.

---

# Lookup boundaries corretos

## Lookup layer

Responsável apenas por:
- localizar;
- comparar;
- ranquear;
- devolver candidatos.

---

## Runtime sovereign layer

Responsável por:
- decidir;
- arbitrar;
- ativar;
- validar;
- recuperar.

---

# Acoplamentos aceitáveis

## Lookup → KB materialization

Saudável:
lookup ajudando:
- runtime material selection;
- candidate retrieval;
- compact material assembly.

---

## Lookup → Utility layer

Saudável:
- normalize;
- tokenize;
- compare;
- sanitize textual.

---

# Acoplamentos perigosos

## Lookup → Recovery

Risco:
match virar:
- resurrection source;
- fallback authority;
- scene pseudo-validation.

---

## Lookup → Scene governance

Risco:
similaridade textual virar:
- operational legitimacy;
- progression validation.

---

## Lookup → Arbitration

Risco:
matching passar a decidir:
- DIRECT;
- SCENE;
- DISCOVERY.

---

# Estado atual

Os clusters lookup já demonstram:
- baixo leakage soberano;
- bom isolamento;
- alta chance de modularização segura futura.

Principalmente:
- normalization cluster;
- scoring cluster.

---

# Possível boundary futuro

## `front_lookup.py`

Poderia futuramente conter:
- normalize;
- tokenize;
- overlap scoring;
- candidate retrieval.

---

## NÃO deveria conter

- runtime arbitration;
- recovery;
- scene validation;
- orchestration;
- governance.

---

# Decisão consolidada

Lookup deve permanecer:

`CAMADA DE MATCH`

E NÃO:
- camada de decisão;
- camada de recovery;
- camada de orchestration;
- camada de legitimidade runtime.

---

# Conclusão

A auditoria confirmou:

`LOOKUP LOCALIZA. RUNTIME SOBERANO DECIDE.`

Grande parte do risco estrutural aparece quando:
- scoring;
- retrieval;
- matching;

passam a ser tratados como autoridade soberana de runtime.