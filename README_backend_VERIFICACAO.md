# MEI Robô — Verificação de Autoridade (Fase 1 — Backend Preview)

> **Objetivo:** ativar a base de verificação de autoridade **sem quebrar nada**. Tudo atrás de **feature flag** e liberado primeiro em **preview**.

## Flags de ambiente

```
# Produção (Render - Service principal)
VERIFICACAO_AUTORIDADE=false

# Preview (Render - Service preview)
VERIFICACAO_AUTORIDADE=true
```

Opcional (anti-abuso simples):
```
VERIF_AUT_MAX_PER_MINUTE=20
```

## Arquivos incluídos (novos)

- `routes/verificacao_autoridade.py` — Blueprint com:
  - `GET /conta/status` → `{ statusConta, expiracao?, motivos: [], flagAtiva }`
  - `POST /verificacao/autoridade` → `{ metodo, resultado, statusConta, expiracao?, detalhes }`
    - `declaracao` → aprova `verified_basic (90d)`
    - `upload(tipo="cracha")` → **reprova automática**
    - `upload` (outros tipos) → **pendente**
    - `convite` → **pendente** (gera `token`; aceite entra na **v1.1**)
  - `GET /verificacao/convite/:token` → stub v1 (pendente)
- `middleware/authority_gate.py` — Gate aplicado **apenas quando a flag estiver ON**.
- `models/user_status.py` — Enum + helpers de status e logs (**memória** no preview).

## Registro no app

No seu `app.py` (ou factory equivalente), registre o blueprint e o middleware:

```python
# app.py (exemplo)
from flask import Flask
from routes.verificacao_autoridade import verificacao_bp
from middleware.authority_gate import init_authority_gate

def create_app():
    app = Flask(__name__)

    # ... sua configuração existente ...

    # 1) Blueprint (rotas novas, não colidem com existentes)
    app.register_blueprint(verificacao_bp)

    # 2) Authority Gate — proteja apenas rotas "oficiais"
    init_authority_gate(app, restricted_patterns=[
        r"^/api/cupons/.*",
        r"^/api/importar-precos$",
        r"^/admin/.*",
        r"^/webhook/.*"
    ])

    return app
```

> **Importante:** quando `VERIFICACAO_AUTORIDADE=false`, o middleware é **NO-OP** (não muda nada).

## Comandos — Git e PR de preview

No seu repositório backend:

```bat
:: copie os arquivos para as pastas correspondentes e execute:
git add routes/verificacao_autoridade.py middleware/authority_gate.py models/user_status.py README_backend_VERIFICACAO.md
git commit -m "feat(verificacao): Fase 1 — blueprint + middleware (flag) + stubs em memória"
git push -u origin feat/verificacao-fase1
```

Abra o Pull Request da branch `feat/verificacao-fase1` para `main` e crie um **Preview Deploy** no Render.

## Render — variáveis de ambiente e deploy

1. **Service Preview** (ou Environment de preview):
   - `VERIFICACAO_AUTORIDADE=true`
   - (opcional) `VERIF_AUT_MAX_PER_MINUTE=20`
   - Faça **Manual Deploy** (botão *Deploy*)

2. **Service Produção**:
   - `VERIFICACAO_AUTORIDADE=false`
   - Não é necessário redeploy imediato (NO-OP), mas pode sincronizar normalmente.

## Testes via cURL (Preview)

Defina a URL do preview e um usuário de teste pelo cabeçalho `X-Debug-User`:

```bat
set ORIGIN=https://URL-DO-PREVIEW.onrender.com
set USER=ricardo-preview
```

1) **Consultar status** (deve iniciar como `guest_unverified`):

```bat
curl -i %ORIGIN%/conta/status -H "X-Debug-User: %USER%"
```

2) **Declaração** → promove para `verified_basic` por 90 dias:

```bat
curl -i -X POST %ORIGIN%/verificacao/autoridade ^
  -H "Content-Type: application/json" -H "X-Debug-User: %USER%" ^
  -d "{\"metodo\":\"declaracao\",\"dados\":{\"texto\":\"Sou autorizado(a)...\"}}"
```

3) **Upload com tipo=cracha** → reprovação automática (continua bloqueado):

```bat
curl -i -X POST %ORIGIN%/verificacao/autoridade ^
  -H "Content-Type: application/json" -H "X-Debug-User: %USER%" ^
  -d "{\"metodo\":\"upload\",\"dados\":{\"tipo\":\"cracha\",\"nomeArquivo\":\"foto.jpg\"}}"
```

4) **Convite** → pendente (gera token):

```bat
curl -i -X POST %ORIGIN%/verificacao/autoridade ^
  -H "Content-Type: application/json" -H "X-Debug-User: %USER%" ^
  -d "{\"metodo\":\"convite\",\"dados\":{\"socioNome\":\"FULANO\",\"contato\":\"fulano@empresa.com\"}}"
```

5) **Stub do convite** (v1.1 futuro): 

```bat
curl -i %ORIGIN%/verificacao/convite/SEU_TOKEN -H "X-Debug-User: %USER%"
```

## Comportamento do Gate (flag ON)

- Usuários com `guest_unverified` **não acessam** rotas oficiais (403 + payload de guia).
- Após `declaracao`, passam a `verified_basic` e **liberam** o acesso.
- `upload` com `tipo=cracha` marca **motivo de reprovação**.
- `upload` outros tipos e `convite` ficam **pendentes**.

## Segurança/Observações

- Este pacote **não altera** rotas existentes além da proteção condicional via middleware.
- Armazenamento **em memória** para PREVIEW — **não** persistente.
- Em produção real: integrar com Firestore/DB, auth real (JWT/session), e filas de revisão.
