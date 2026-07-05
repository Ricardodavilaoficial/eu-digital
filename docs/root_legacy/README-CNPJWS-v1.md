
# MEI Robô — Integração CNPJ.ws (API Pública) v1

**Decisão:** usar a API pública do CNPJ.ws para POC/Cliente ZERO (3 req/min/IP; sem token).
**Endpoint origem:** `GET https://publica.cnpj.ws/cnpj/{CNPJ}`
**Defasagem:** até ~45 dias.

## Rota interna (backend)
`GET /integracoes/cnpj/:cnpj?nome=...`

### Resposta (esquema canônico)

```json
{
  "fonte": "cnpj.ws_publica",
  "cnpj": "14xxxxxxxx0001yy",
  "razaoSocial": "NOME LTDA",
  "nomeFantasia": "NOME",
  "dataAbertura": "YYYY-MM-DD",
  "situacao": "ATIVA",
  "cnaePrincipal": {"codigo": "9999-9/99", "descricao": "..."},
  "cnaesSecundarios": [{"codigo": "...", "descricao": "..."}],
  "endereco": {
    "logradouro": "", "numero": "", "bairro": "",
    "municipio": "", "uf": "", "cep": "", "complemento": ""
  },
  "simples": {
    "optante": true, "mei": true,
    "dataOpcaoSimples": "YYYY-MM-DD",
    "dataOpcaoMei": "YYYY-MM-DD"
  },
  "socios": [{"nome": "FULANO", "qualificacao": "..."}],
  "atualizadoEm": "YYYY-MM-DD",
  "vinculoNome": {"entrada":"...","avaliacao":"EXATO|PROVAVEL|NAO_ENCONTRADO","origem":"RAZAO_SOCIAL|SOCIOS"}
}
```

## Heurística de vínculo por nome (v1)
- MEI/EI: compara com `razao_social`
- LTDA e afins: compara com `socios[].nome`
- Resultado: `EXATO`, `PROVAVEL`, `NAO_ENCONTRADO` (sem CPF neste v1)

## Cache
- Em memória (24h). Sugestão futura: Redis TTL 24–48h.

## Tratamento de erros
- 400: CNPJ inválido
- 404: não encontrado
- 429: limite da origem (exibe mensagem amigável; repassa `Retry-After` se houver)
- 502: falha/indisponibilidade da origem ou JSON inválido

## Passos de deploy (Preview → Produção)

### Preview (Hosting + Render)
1. **Backend (Render)**
   - Adicione `routes/cnpj_publica.py`
   - No seu `app.py`:
     ```python
     from routes.cnpj_publica import bp_cnpj_publica
     app.register_blueprint(bp_cnpj_publica)
     ```
   - Deploy sua branch de preview no Render.

2. **Frontend (Hosting)**
   - Incluir `frontend/assets/cnpj-lookup.js` no projeto (se desejar usar helper).
   - (Opcional) Vincular no HTML do cadastro/configuração.

3. **Testes**
   - CNPJ MEI ativo, não-MEI, inválido.
   - Rate limit (429).
   - Heurística por nome (exato/provável/nenhum).

### Produção
- Após validar preview, seguir seu ritual de git + `firebase deploy --only hosting` e deploy no Render.
