# Auditoria — Late KB Reinforcement / Structured Assembly

Objetivo:
Mapear onde o conversational_front.py reinjeta material de platform_kb após a IA/assembly já terem produzido uma resposta operacional rica.

Bug observado:
Resposta DIRECT + AGENDA + platform_kb_pack duplica value_one_liner/micro_scene e termina truncada após FRONT_STRUCTURED_FINAL_TRIM.

Regra buscada:
Se a resposta já tem densidade operacional suficiente, late KB reinforcement não deve reconstruir nem concatenar material redundante.

## Descoberta — structured assembly duplicado

Foi confirmado que `_front_build_structured_assembly_reply(...)` roda em dois pontos do `conversational_front.py`:

- primeiro no FREE_MODE técnico, em torno da linha 10772;
- depois novamente no pipeline/reconstruction tardio, em torno da linha 12518.

Sintoma observado:
- primeira montagem gera resposta válida;
- `FRONT_STRUCTURED_FINAL_TRIM` limita para ~817 caracteres;
- depois o runtime continua vivo;
- a montagem estruturada roda novamente;
- material de `platform_kb_pack` é reinjetado;
- a resposta duplica `value_one_liner` / `runtime_short`;
- o texto final termina truncado.

Conclusão:
O bug atual não é prompt, KB, IA ou segmentação.
É reconstrução tardia duplicando uma resposta estruturada já aceita no FREE_MODE técnico.

Regra de correção:
Se `reply_source == "front_structured_python_assembly"` e o fluxo já está em `DIRECT` técnico com `platform_kb`, a segunda chamada de `_front_build_structured_assembly_reply(...)` deve ser pulada para preservar a resposta já validada.

Escopo:
- sem alterar prompts;
- sem alterar KB;
- sem alterar lookup/segmentação;
- sem desligar platform pack;
- sem mexer em micro_scene_allowed;
- patch pequeno e reversível.
