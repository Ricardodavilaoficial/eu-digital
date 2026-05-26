# FRONT RUNTIME GOVERNANCE MAP

Data: 2026-05-26

## Objetivo

Registrar as soberanias runtime descobertas no `conversational_front.py`.

Este documento orienta futuras refatorações seguras e impede extrações por proximidade de linha.

---

# 1. Descoberta central

O `conversational_front.py` não possui um único pipeline.

Ele possui múltiplas governanças runtime concorrentes:

- response_mode governance;
- DISCOVERY governance;
- SCENE governance;
- runtime recovery infrastructure;
- terminal payload governance;
- JSON anti-corruption governance.

---

# 2. Response Mode Governance

`response_mode` é o state machine principal do front.

Ele é:
- inferido;
- promovido;
- degradado;
- normalizado;
- forçado;
- reescrito.

Pontos observados:
- DIRECT → SCENE;
- SCENE → DIRECT;
- DISCOVERY → SCENE;
- CLOSING → DIRECT;
- force DISCOVERY.

Decisão:
não mover ainda para módulo físico.

---

# 3. Discovery Governance

DISCOVERY é um sistema soberano, não apenas um modo.

Inclui:
- DISCOVERY prompt;
- early terminal;
- discovery guarantee;
- identity guard;
- terminal enforcement.

Decisão:
não misturar DISCOVERY com SAFE FINAL PIPELINE.

---

# 4. Scene Governance

SCENE é controlado por:

- `micro_scene_allowed`;
- `allow_scene_runtime`;
- `operational_contract`;
- `base_operational_contract`.

`micro_scene_allowed` é gate soberano.

Ele pode:
- nascer;
- ser resetado;
- ser reativado;
- ser copiado entre contratos;
- bloquear ou ressuscitar SCENE.

Decisão:
não extrair SCENE governance até mapear todos os callsites.

---

# 5. Runtime Recovery Infrastructure

Recovery não é fallback simples.

Ele inclui:
- `_build_kb_show_reply`;
- `_build_kb_anchor_reply`;
- `_restore_final_candidate_if_degraded`;
- fallback final;
- failsafe payload;
- technical output guard;
- late KB injection.

Trecho mais crítico:
- 12424–12545

Decisão:
congelar.

---

# 6. Terminal Payload Governance

O payload final é reconstruído tardiamente.

Elementos:
- `out = {...}`;
- `_sanitize_front_result_payload`;
- `_unwrap_front_json_envelope`;
- terminal blindagem;
- `return result`.

Trecho:
- 12768–12935

Decisão:
não extrair antes de definir contrato de terminal output.

---

# 7. Multi-terminal architecture

Foram identificados três terminais:

## Early Discovery Terminal
Bypass do final pipeline.

## Direct Scene Early Terminal
Bypass soberano de alto risco.

## Official Final Pipeline
Terminal verdadeiro com `return result`.

Decisão:
qualquer modularização futura precisa preservar os três caminhos ou convergi-los conscientemente.

---

# 8. Regra de ouro

Não mover helpers por proximidade.

Mover apenas quando:
- domínio estiver claro;
- side-effects forem conhecidos;
- ownership for explícito;
- recovery triggers estiverem mapeados;
- contrato de entrada/saída estiver definido.

# Atualização — Response mode sovereignty

Foi confirmado que `response_mode` é governança distribuída.

O runtime possui:
- inference layer;
- arbitration layer;
- structural bypass layer;
- late sovereign terminals.

O estado final de `response_mode` depende da ordem soberana dessas camadas.

# Atualização — DISCOVERY GOVERNANCE

## Discovery NÃO é geração de pergunta

Foi confirmado que o domínio DISCOVERY atua como:

`identity integrity governance`

e não apenas como mecanismo de perguntas.

## Camadas identificadas

### DISCOVERY STATE ENFORCEMENT
- `_apply_discovery_mode_identity_guard(...)`

Responsabilidade:
- preservar estado clarify;
- preservar obrigatoriedade de identidade.

---

### DISCOVERY STABILIZATION
- `_apply_identity_clarify_guard(...)`

Responsabilidade:
- preservar pergunta já existente;
- estabilizar append;
- controlar orçamento estrutural.

Importante:
- opera em múltiplos passes no mesmo ramo runtime.

---

### DISCOVERY VALIDATION
- `_front_identity_request_is_valid(...)`
- `services/front_guards.py`

Responsabilidade:
- validar perguntas de identidade;
- impedir discovery inválido.

---

### LAST RESORT IDENTITY GENERATION
- `_front_build_identity_request(...)`

Responsabilidade:
- gerar pergunta mínima apenas quando nenhuma pergunta válida existir.

