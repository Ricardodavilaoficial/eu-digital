# RESPONSE MODE MAP

## Objetivo

Mapear a governança de `response_mode` dentro do:

`services/conversational_front.py`

Este documento descreve:
- modos possíveis;
- ownership do modo;
- pontos de risco;
- zonas SAFE;
- zonas SOVEREIGN;
- decisões já consolidadas.

---

# Modos reconhecidos

## DIRECT

Resposta direta.

Usado quando:
- a intenção está clara;
- há contexto suficiente;
- não há necessidade de descoberta;
- não há cena operacional validada.

Classificação:
`SAFE / DEFAULT`

---

## DISCOVERY

Resposta de descoberta.

Usado quando:
- falta nome;
- falta segmento;
- falta clareza de intenção;
- há necessidade de proteger integridade de identidade.

Classificação:
`SOVEREIGN`

---

## SCENE

Resposta com demonstração operacional.

Usado quando:
- há contrato operacional demonstrável;
- há material runtime confiável;
- `micro_scene_allowed` permite;
- a cena não nasce de fallback genérico contaminado.

Classificação:
`HIGH RISK SOVEREIGN`

---

## CLOSING

Resposta de fechamento.

Usado quando:
- há intenção de conversão;
- há próxima ação comercial;
- fluxo deve avançar sem fricção.

Classificação:
`SOVEREIGN / COMMERCIAL`

---

# Governança do response_mode

## Responsabilidades

A governança de modo controla:
- formato da resposta;
- permissões de cena;
- discovery enforcement;
- bypasses;
- fallback de modo;
- promoção ou degradação estrutural.

---

# RESPONSE MODE GOVERNANCE

## Funções relacionadas

- `_infer_response_mode_from_signals(...)`
- `_apply_response_mode_arbitration(...)`
- `_apply_discovery_to_scene_bypass(...)`
- `_apply_current_turn_topic_reset(...)`

---

## Classificação

`SOVEREIGN`

Motivo:
alterar `response_mode` altera diretamente:
- comportamento comercial;
- estrutura da resposta;
- uso de discovery;
- possibilidade de cena;
- terminal runtime.

---

# SAFE RESPONSE SURFACE

## Função já extraída

- `_apply_response_mode_surface(...)`

Novo módulo:
- `services/front_surface.py`

## Responsabilidade

Apenas:
- acabamento superficial;
- trim;
- lstrip;
- normalização de superfície;
- sync básico de `reply_text` / `spoken_text`.

## O que NÃO faz

Não:
- decide modo;
- altera `response_mode`;
- executa discovery;
- executa scene governance;
- acessa KB;
- executa recovery;
- altera micro_scene_allowed.

## Classificação

`PURE SAFE FINAL PIPELINE`

---

# DISCOVERY GOVERNANCE

DISCOVERY não é apenas uma pergunta.

DISCOVERY protege:
- identidade;
- clareza;
- segmento;
- intenção;
- integridade de continuidade.

## Funções relacionadas

- `_apply_discovery_mode_identity_guard(...)`
- `_apply_identity_clarify_guard(...)`
- `_front_identity_request_is_valid(...)`
- `_front_build_identity_request(...)`

## Classificação

`SOVEREIGN`

---

# SCENE GOVERNANCE

SCENE depende de:
- contrato operacional;
- material runtime;
- contexto real;
- gating;
- ausência de contaminação por fallback genérico.

## Gates principais

- `micro_scene_allowed`
- `allow_scene_runtime`

## Riscos

- PACK_A bleed;
- tutorialização indevida;
- scene resurrection;
- falso contexto operacional;
- fallback fantasma.

## Classificação

`HIGH RISK SOVEREIGN`

---

# Response mode arbitration

A arbitragem de modo decide quando:
- DIRECT permanece DIRECT;
- DISCOVERY é imposto;
- DISCOVERY pode virar SCENE;
- SCENE deve cair para DIRECT;
- CLOSING deve ser preservado.

## Regra de segurança

Não mover arbitragem enquanto:
- discovery governance não estiver isolada;
- scene governance não estiver estabilizada;
- recovery runtime ainda puder reabrir conteúdo.

---

# Discovery to Scene Bypass

## Helper

- `_apply_discovery_to_scene_bypass(...)`

## Responsabilidade

Permitir promoção:
`DISCOVERY → SCENE`

somente quando já existe contrato operacional demonstrável.

## Classificação

`SOVEREIGN ORCHESTRATION`

Não é PURE SAFE.

---

# Zonas congeladas

## PROIBIDO MOVER AGORA

- response arbitration;
- discovery identity guard;
- discovery terminals;
- `micro_scene_allowed`;
- `allow_scene_runtime`;
- scene promotion;
- scene degradation;
- runtime recovery ligado a modo.

---

# Estado atual

Já foi extraído com segurança:

- `_apply_response_mode_surface(...)`

Ainda ficam no core:

- inferência;
- arbitragem;
- discovery enforcement;
- scene governance;
- terminal decisions.

---

# Decisão consolidada

Apenas a superfície de modo é SAFE.

A decisão de modo continua SOVEREIGN.

Portanto:
- `front_surface.py` pode conter normalização superficial;
- `front_response_mode.py` ainda NÃO deve nascer;
- response arbitration deve permanecer no core até nova auditoria.

---

# Conclusão

`response_mode` é uma das chaves centrais da soberania runtime.

A modularização futura deve separar:

## SAFE
- acabamento superficial por modo.

## SOVEREIGN
- inferência;
- arbitragem;
- discovery;
- scene;
- terminals;
- recovery ligado a modo.

A regra atual é:

`SUPERFÍCIE PODE SAIR. DECISÃO FICA.`