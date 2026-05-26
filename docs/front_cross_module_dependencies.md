# FRONT CROSS MODULE DEPENDENCIES

## Objetivo

Mapear as dependências cruzadas entre os módulos da refatoração do:

`services/conversational_front.py`

Este documento descreve:
- dependências legítimas;
- acoplamentos aceitáveis;
- leakage soberano;
- dependências perigosas;
- regras de separação arquitetural.

---

# Descoberta central

A refatoração segura NÃO depende apenas de:
- mover helpers;
- reduzir linhas.

Ela depende principalmente de:
`PRESERVAR BOUNDARIES`

---

# Módulos atuais

## `services/front_utils.py`
Classificação:
`PURE UTILITY ENGINE`

---

## `services/front_guards.py`
Classificação:
`GUARD / VALIDATION ENGINE`

---

## `services/front_policies.py`
Classificação:
`POLICY ORCHESTRATION ENGINE`

---

## `services/front_assembly.py`
Classificação:
`DETERMINISTIC HUMANIZATION ENGINE`

---

## `services/front_surface.py`
Classificação:
`PURE SAFE FINAL PIPELINE ENGINE`

---

## `services/front_kb.py`
Classificação:
`KB RUNTIME MATERIALIZATION ENGINE`

---

## `services/conversational_front.py`
Classificação:
`SOVEREIGN CORE`

---

# Dependências saudáveis

## front_assembly.py

Pode depender de:
- `front_utils.py`
- `front_guards.py`

Porque:
- executa humanização determinística;
- não governa runtime;
- não executa recovery.

---

## front_surface.py

Pode depender de:
- `front_utils.py`
- `front_policies.py`

Porque:
- atua apenas em superfície;
- normalize;
- sanitize;
- polish;
- sync.

---

## front_policies.py

Pode depender parcialmente de:
- `front_utils.py`

Porque:
- executa budgets;
- truncamento;
- políticas estruturais.

---

## front_kb.py

Dependências legítimas:
- `json`
- `re`
- `typing`

Boundary saudável:
- sem IA;
- sem Firestore;
- sem governance;
- sem orchestration.

---

# Dependências perigosas

## Recovery → KB → Governance

Risco:
recovery usando KB como autoridade soberana.

Efeito:
- resurrection;
- PACK bleed;
- tutorialização;
- fallback contaminando orchestration.

---

## Surface → Governance

Risco:
helpers superficiais começarem a decidir:
- response_mode;
- discovery;
- scene;
- recovery.

---

## Assembly → Recovery

Risco:
humanização determinística começar a:
- reconstruir runtime;
- reabrir recovery;
- alterar orchestration.

---

## KB → Runtime arbitration

Risco:
material KB começar a:
- promover SCENE;
- validar runtime;
- arbitrar modos.

---

# Leakage soberano

## Definição

Leakage ocorre quando:
um módulo SAFE começa a carregar responsabilidade SOVEREIGN.

---

# Exemplos de leakage

## front_surface.py

Leakage ocorreria se:
- executasse recovery;
- alterasse response_mode;
- ativasse SCENE.

---

## front_kb.py

Leakage ocorreria se:
- arbitrasse runtime;
- executasse discovery;
- controlasse scene gating.

---

## front_assembly.py

Leakage ocorreria se:
- chamasse IA;
- executasse resurrection;
- alterasse runtime continuity.

---

# SAFE vs SOVEREIGN

## SAFE MODULES

Características:
- determinísticos;
- sem recovery;
- sem orchestration;
- sem runtime mutation;
- sem terminal governance.

---

## SOVEREIGN CORE

Controla:
- runtime;
- arbitration;
- discovery;
- recovery;
- terminals;
- orchestration;
- reconstruction.

---

# Dependências proibidas

## front_surface.py NÃO deve depender de

- recovery runtime;
- orchestration soberana;
- discovery governance;
- scene governance.

---

## front_kb.py NÃO deve depender de

- IA;
- Firestore;
- runtime governance;
- response arbitration.

---

## front_assembly.py NÃO deve depender de

- recovery;
- terminals;
- orchestration;
- runtime resurrection.

---

# Acoplamentos aceitáveis

## Utils shared layer

É aceitável:
- múltiplos módulos dependerem de `front_utils.py`.

Porque:
- utilitários são neutros;
- não carregam soberania.

---

## Guards shared layer

É aceitável:
- assembly;
- policies;
- surface;

utilizarem:
- `front_guards.py`

Porque:
- validação é transversal;
- não governa runtime.

---

# Acoplamentos perigosos

## Recovery transversal

Recovery tocando:
- assembly;
- surface;
- packs;
- KB;
- orchestration;

é atualmente o maior risco estrutural.

---

## Runtime arbitration transversal

Arbitration atravessando:
- fallback;
- packs;
- KB;
- scene generation;

também é risco elevado.

---

# Estado atual

A refatoração já conseguiu:
- reduzir leakage;
- estabilizar boundaries;
- separar módulos SAFE;
- isolar melhor o core soberano.

Porém:
- recovery ainda é transversal;
- orchestration ainda concentra soberania;
- terminals ainda permanecem no core.

---

# Decisão consolidada

A prioridade correta NÃO é:
- reduzir linhas rapidamente;
- criar muitos módulos.

A prioridade correta é:
- impedir leakage soberano;
- preservar ownership;
- estabilizar dependências;
- consolidar boundaries.

---

# Conclusão

A refatoração segura depende mais de:

`DEPENDÊNCIAS SAUDÁVEIS`

do que de:
- quantidade de módulos;
- quantidade de extrações;
- redução artificial de linhas.

O objetivo arquitetural correto é:

`SAFE MODULES AO REDOR. CORE SOBERANO NO CENTRO.`