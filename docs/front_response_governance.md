# MEI ROBÔ — Governança de resposta do Front

## Regra central

A IA soberana é responsável por:
- entender a intenção do lead;
- identificar se precisa de esclarecimento;
- interpretar nome, segmento, tema e momento comercial;
- redigir a resposta humanizada final com base nos fatos recebidos.

O Python é responsável por:
- buscar e organizar fatos no Firestore/KB;
- validar contrato mínimo da resposta;
- proteger contra erro técnico, JSON, resposta vazia, nome inseguro e promessa sem base;
- sincronizar texto e áudio;
- aplicar fallback apenas quando houver falha objetiva.

## Divisão de autoridade

IA soberana = entendimento + redação comercial-humanizada.

Python = fatos + auditoria + segurança + superfície + fallback rastreado.

## Regra de ownership

Uma resposta válida da IA não deve ser reescrita por assembly, continuity ou fallback sem motivo objetivo registrado.

Python pode vetar.
Python pode corrigir superfície.
Python pode aplicar fallback rastreado.
Python não deve disputar a redação final quando a resposta soberana passou no contrato mínimo.

## Fluxo-alvo

1. IA entende intenção.
2. Python hidrata fatos no Firestore/KB.
3. IA monta resposta humanizada.
4. Python audita contrato mínimo.
5. Se aprovada, preserva ownership da IA.
6. Se falhar, fallback determinístico curto, rastreado e justificado.

## Risco que estamos corrigindo

O `handle()` atual permite múltiplas mutações tardias de:
- reply_text;
- spoken_text;
- reply_source;
- response_mode;
- accepted;
- ia_accepted;
- needs_clarify.

Isso causa perda de ownership: a resposta nasce na IA, mas pode ser reavaliada, reconstruída, reclassificada ou sobrescrita depois.

## Regra para próximos patches

Antes de alterar comportamento:
- mapear quem altera a resposta;
- registrar motivo;
- preservar resposta válida;
- aplicar patch pequeno;
- compilar;
- inspecionar diff;
- commit isolado.

Sem alteração de prompt.
Sem palavra-chave rígida.
Sem frase pronta em código.
Sem fallback mágico.
Sem `.bak`.
Sem PowerShell.