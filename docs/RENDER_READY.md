# MEI Robo - Render Ready (Monolitico)
## Objetivo
Rodar no Render sem Cloud Tasks e sem split webhook/worker.
## Pre-requisito
Render com pagamento ativo (permitir deploy e editar ENVs).
## Passo-a-passo no Render (clique a clique)
1) New + > Web Service
2) Conectar GitHub repo e escolher branch main
3) Runtime: Docker (usa Dockerfile)
4) Start Command: deixar vazio (usa CMD do Dockerfile)
5) Environment Vars: ajustar 3 chaves obrigatorias:
   - QUEUE_MODE=inline
   - APP_ROLE=all
   - BACKEND_BASE_URL=https://SEU-SERVICO.onrender.com
6) Garantir secrets essenciais (colocar no Render, nao no repo):
   - FIREBASE_SERVICE_ACCOUNT_JSON
   - OPENAI_API_KEY
   - YCLOUD_API_KEY
   - YCLOUD_WA_FROM_E164
   - (se usar assinatura) YCLOUD_WEBHOOK_SIGNING_SECRET
7) Deploy
## YCloud (painel)
Webhook URL:
https://SEU-SERVICO.onrender.com/integracoes/ycloud/webhook
Ping:
https://SEU-SERVICO.onrender.com/integracoes/ycloud/ping
## Confirmacoes rapidas (apos deploy)
- Abrir /integracoes/ycloud/ping e ver {"ok": true}
- Enviar uma mensagem teste pelo WhatsApp e ver resposta
## Start Command (se o Render exigir explicitamente)
sh -c "exec gunicorn app:app --bind 0.0.0.0:${PORT:-8080} $GUNICORN_CMD_ARGS"
