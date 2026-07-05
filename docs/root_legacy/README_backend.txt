
Como usar este blueprint no seu backend Flask (Render):

1) Coloque este arquivo em: backend/routes/cnpj_publica.py
2) No seu app principal (ex.: app.py), registre o blueprint:
   from routes.cnpj_publica import bp_cnpj_publica
   app.register_blueprint(bp_cnpj_publica)
3) Deploy em PREVIEW primeiro (Render + Firebase Hosting).
4) Endpoint ficará disponível em:
   GET /integracoes/cnpj/<cnpj>?nome=Fulano da Silva

Observações:
- Cache em memória (24h). Para produção, considere Redis/Memcached.
- Timeout 8s. Ajuste conforme sua estratégia de resiliência.
- Logs: registre latência e status no seu middleware padrão.
