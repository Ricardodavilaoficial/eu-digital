# EXTRACTION EXECUTION PROTOCOL

## Objetivo

Definir o protocolo oficial de extrações da refatoração segura do `conversational_front.py`.

---

# PRINCÍPIOS

## 1. A arquitetura soberana vem antes da modularização

Nenhuma extração pode:
- alterar ordem soberana;
- alterar terminals;
- alterar recovery;
- alterar bypasses;
- alterar discovery governance;
- alterar response governance.

---

## 2. Pequenas waves

Cada extraction wave deve mover:
- no máximo 1–3 helpers.

Nunca grandes blocos.

---

## 3. Somente PURE SAFE HELPERS

Extraction-ready atual:

- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

---

## 4. Proibido extrair

Domínios proibidos nesta fase:

- RUNTIME RECOVERY INFRASTRUCTURE
- OPERATIONAL RECONSTRUCTION ENGINE
- DISCOVERY GOVERNANCE
- RESPONSE MODE GOVERNANCE
- TERMINAL GOVERNANCE
- KB RUNTIME

---

## 5. Toda extração exige

### Antes
- auditoria de dependências;
- auditoria de soberania;
- auditoria de terminals;
- atualização documental.

### Durante
- compile incremental;
- compile reverso;
- imports explícitos;
- commit isolado.

### Depois
- validação runtime;
- push imediato;
- documentação da wave.

---

## 6. Rollback obrigatório

Toda wave deve possuir:
- commit isolado;
- rollback simples;
- boundaries documentados.

---

## 7. Extração nunca pode misturar

Nunca combinar:
- refactor estrutural;
- correção comportamental;
- ajustes de prompt;
- ajustes de KB.

---

## 8. Ordem oficial das futuras waves

### FIRST SAFE EXTRACTION WAVE
- PURE SAFE FINAL PIPELINE helpers

### SECOND SAFE EXTRACTION WAVE
- guards puros
- validators puros

### THIRD SAFE EXTRACTION WAVE
- surface helpers híbridos
(apenas após nova auditoria)

---

## 9. Critérios de EXTRACTION READY

Um helper só pode ser classificado como EXTRACTION READY quando:

- não chama IA;
- não consulta KB;
- não altera response_mode;
- não altera micro_scene_allowed;
- não executa recovery;
- não depende de terminals;
- não executa reconstruction;
- não possui mutações soberanas;
- possui callsites claros;
- possui boundaries estáveis.

---

## 10. Regra máxima da refatoração segura

Primeiro:
mapear soberania.

Depois:
extrair.

Nunca o contrário.

# Atualização — FIRST SAFE EXTRACTION WAVE executada

Foi criado:

- `services/front_surface.py`

Helpers extraídos:

- `_apply_response_mode_surface(...)`
- `_restore_final_candidate_if_degraded(...)`

Status:
- compile limpo;
- callsites preservados;
- sem alteração comportamental intencional;
- boundary classificado como PURE SAFE FINAL PIPELINE.

