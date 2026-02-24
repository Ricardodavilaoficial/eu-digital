🛡️ Estrutura recomendada da cartilha oficial
1️⃣ RUNBOOK_CLOUD_RUN.md

Explica:

Arquitetura (webhook vs worker)

APP_ROLE

Região

Projeto

Como funciona deploy

O que é proibido

2️⃣ DEPLOY_PROCEDURE.md (a regra de ouro)

Aqui entra exatamente o que definimos:

Deploy permitido
gcloud run services update --image ...
Proibido
gcloud run deploy --set-env-vars ...
gcloud run services replace ...
Pós-deploy obrigatório

Checks de tráfego + health.

3️⃣ ENV_POLICY.md

Curto e direto:

ENV é gerenciada exclusivamente pela UI

Nunca via CLI

Mudança de ENV requer teste manual imediato

Sempre registrar no CHANGELOG

4️⃣ CHANGELOG.md

Toda vez que mexer em ENV ou infra:

## 2026-02-24
- Ajustado CLOUD_TASKS_TARGET_URL
- Confirmado APP_ROLE separação webhook/worker

Isso evita “ah, quem mexeu nisso?”