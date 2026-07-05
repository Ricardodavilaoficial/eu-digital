MEI Robô — Fachada v1 (services/wa_bot.py)
=========================================

**Objetivo:** manter a *fachada* e as assinaturas estáveis enquanto migramos a lógica pesada
para módulos novos. Nada de comportamento novo forçado nesta etapa; se `NLU_MODE != "v1"`,
delegamos tudo para `services/wa_bot_legacy.py` (que já roda em produção).

Como funciona
-------------
- Flags:
  - `NLU_MODE=legacy` (padrão) → usa 100% o `wa_bot_legacy`.
  - `NLU_MODE=v1` → tenta usar o pipeline novo **se** módulos existirem; caso não existam, cai no legacy.
  - `DEMO_MODE=1` (opcional) mantido apenas como informação para logs/camadas de cima.
- Entradas principais preservadas:
  - `process_inbound(event)`
  - `reply_to_text(uid, text, ctx=None)`
  - `schedule_appointment(uid, ag, allow_fallback=True)`
  - `reschedule_appointment(uid, ag_id, updates)`

Passos para integrar
--------------------
1. Salve `services/wa_bot.py` substituindo o atual.
2. Garanta que **existe** `services/wa_bot_legacy.py` com as implementações vigentes.
3. (Opcional) Crie/esqueleto dos módulos futuros:
   - `services/nlu/intent.py`
   - `services/domain/pricing.py`
   - `services/domain/scheduling/engine.py`
4. Suba no Render. Testes rápidos:
   - Import e *healthcheck* no Python REPL do serviço:
     ```python
     from services import wa_bot
     print(wa_bot.info())
     ```
   - Webhook → deve continuar funcionando como antes (usa legacy).

Branch e deploy
---------------
- Sugestão: `feat/wa-bot-fachada-v1`
- Após commit/push, valide os logs do Render. O módulo imprime um aviso discreto caso
  o `wa_bot_legacy` não seja encontrado.

Segurança/Robustez
------------------
- A fachada **nunca estoura** exceções para fora; retorna dicionários/formas estáveis em erros.
- Sem dependências novas obrigatórias nesta fase.
