# EXTRACTION EXECUTION PROTOCOL

## Objetivo

Definir o protocolo oficial da refatoração segura do:

`services/conversational_front.py`

Este documento governa:
- extraction waves;
- critérios de segurança;
- rollback;
- compile chain;
- soberania arquitetural;
- boundaries permitidos.

---

# Regra máxima da refatoração segura

Primeiro:
mapear soberania.

Depois:
extrair.

Nunca o contrário.

---

# Princípios obrigatórios

## 1. A arquitetura soberana vem antes da modularização

Nenhuma extraction wave pode:
- alterar runtime governance;
- alterar terminals;
- alterar recovery;
- alterar discovery governance;
- alterar response governance;
- alterar orchestration order.

---

## 2. Pequenas waves

Cada wave deve mover:
- no máximo 1–3 helpers.

Nunca:
- blocos grandes;
- múltiplos domínios;
- refactors massivos.

---

## 3. Somente PURE SAFE HELPERS

Extraction-ready atual:

- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Status:
- extraídos;
- compile limpo;
- boundaries preservados.

---

## 4. Proibido extrair nesta fase

Domínios congelados:

- Runtime Recovery Infrastructure
- Operational Reconstruction Engine
- Discovery Governance
- Response Mode Governance
- Terminal Governance
- KB Runtime Governance

---

## 5. Nunca misturar

Uma wave nunca pode combinar:
- refatoração estrutural;
- bugfix;
- alteração comportamental;
- ajuste de prompt;
- ajuste de KB;
- mudança comercial.

---

# Critérios oficiais de EXTRACTION READY

Um helper só pode ser classificado como:
`EXTRACTION READY`

quando:

- não chama IA;
- não consulta KB runtime;
- não altera response_mode;
- não altera micro_scene_allowed;
- não executa recovery;
- não executa reconstruction;
- não depende de terminals;
- não possui mutações soberanas;
- possui boundaries estáveis;
- possui callsites claros.

---

# Processo obrigatório da extraction wave

## Antes da wave

Obrigatório:
- auditoria de dependências;
- auditoria de soberania;
- auditoria de terminals;
- atualização documental.

---

## Durante a wave

Obrigatório:
- compile incremental;
- imports explícitos;
- commit isolado;
- preservação dos callsites;
- boundaries documentados.

Nunca:
- mover helpers por proximidade;
- misturar múltiplos domínios;
- alterar fluxo runtime.

---

## Depois da wave

Obrigatório:
- compile final;
- validação runtime;
- push imediato;
- documentação da wave.

---

# Rollback obrigatório

Toda extraction wave deve possuir:
- commit isolado;
- rollback simples;
- boundaries registrados;
- callsites rastreáveis.

---

# Ordem oficial das waves

## FIRST SAFE EXTRACTION WAVE
Domínio:
`PURE SAFE FINAL PIPELINE`

Resultado:
- validada;
- concluída;
- compile limpo.

Extrações:
- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Novo módulo:
- `services/front_surface.py`

---

## SECOND SAFE EXTRACTION WAVE
Objetivo:
- guards puros;
- validators puros.

Status:
- ainda não iniciada.

---

## THIRD SAFE EXTRACTION WAVE
Objetivo:
- surface helpers híbridos.

Pré-requisito:
- nova auditoria de soberania.

---

# PURE SAFE vs SOVEREIGN

## PURE SAFE

Pode:
- sanitize;
- sync;
- normalize;
- polish;
- preservar superfície.

Não pode:
- recovery;
- orchestration;
- governance;
- reconstruction;
- runtime mutation.

---

## SOVEREIGN

Inclui:
- discovery governance;
- response arbitration;
- runtime recovery;
- reconstruction;
- terminals;
- scene governance.

Nunca mover cedo.

---

# Compile chain obrigatória

Sempre executar:

```cmd
python -m py_compile services\conversational_front.py
```

E, quando necessário:

```cmd
python -m py_compile services\front_surface.py
python -m py_compile services\front_kb.py
python -m py_compile services\front_policies.py
python -m py_compile services\front_assembly.py
python -m py_compile services\front_guards.py
```

---

# Regras operacionais CMD

Sempre:
- `git add` específico;
- commit pequeno;
- push imediato;
- rollback simples.

Nunca:
- `git add .`
- múltiplas waves juntas;
- múltiplas extrações sem compile.

---

# Protocolo validado empiricamente

A FIRST SAFE EXTRACTION WAVE confirmou que:

- micro-extrações funcionam;
- compile incremental é suficiente;
- boundaries soberanos podem ser preservados;
- imports assimétricos temporários são aceitáveis;
- documentação simultânea reduz risco arquitetural.

---

# Estado atual da refatoração

Fase atual:

`MONOLITH CORE ISOLATION PHASE`

O monólito restante concentra:
- runtime governance;
- orchestration;
- recovery;
- reconstruction;
- sovereign terminals.

A estratégia correta continua sendo:
- estabilizar boundaries;
- consolidar documentação;
- reduzir risco;
- preservar soberania antes da modularização física.