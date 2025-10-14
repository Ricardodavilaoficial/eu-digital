MEI Robô — Fase 1 (Modularização Segura) — KIT
==============================================

Este kit:
- Cria a estrutura mínima de módulos (/routes e /services) para CNPJ e Voz;
- Adiciona o blueprint **cnpj_publica** com flag `CNPJ_BP_ENABLED`;
- Prepara blueprint e serviços de Voz V2 com flag `VOZ_V2_ENABLED` (DESLIGADA por padrão);
- Aplica patch no seu **app.py** SEM quebrar nada (backup automático).

⚠️ Por padrão NADA MUDA em produção, porque as flags estão OFF.
Só ao ativar `CNPJ_BP_ENABLED=true` a rota nova entra.

Como aplicar (Windows CMD)
--------------------------
1) Copie e EXTRAIA este ZIP na pasta onde está o seu backend (onde existe o app.py).
   Ex.: C:\Users\Ricardo d'Avila\Desktop\meu-projeto-eu-digital-final

2) No CMD, execute:
   chcp 65001
   python setup_routes_services.py

   - Isso criará as pastas/arquivos e vai PATCHAR o app.py com backup:
     app.py.bak-YYYYMMDD-HHMMSS

3) Reinicie o serviço no Render (deploy normal). Nada deve mudar porque as flags estão OFF.

4) Para testar o CNPJ (opcional):
   - No Render, defina a variável de ambiente: CNPJ_BP_ENABLED=true
   - Faça o deploy/restart.
   - Teste:
     curl -i "https://SEU_BACKEND/api/cnpj/48495357000114"

   Se estiver OK, resposta 200 com JSON {razaoSocial, nomeFantasia, cnae, cnaeDescricao}.

Rollback
--------
- Para "desligar" a rota CNPJ: remova/desligue a ENV `CNPJ_BP_ENABLED` e faça deploy.
- Para reverter o app.py inteiro: substitua pelo backup gerado (app.py.bak-...).
