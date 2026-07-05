# PROJETO PONTE / MEI ROBO WEB

## INDICE OPERACIONAL DOS DOCUMENTOS

Este README e o ponto de entrada da pasta `docs\projeto_ponte`.

Sempre que uma nova instancia, o Codex ou o usuario retomarem o Projeto Ponte, este arquivo deve ser lido primeiro.

Objetivo deste indice:

- mostrar quais documentos oficiais existem;
- explicar quando cada documento deve ser usado;
- evitar documentos soltos que depois ninguem encontra;
- preservar a separacao entre MEI Robo Base, MEI Robo Institucional e MEI Robo WEB;
- indicar o proximo passo operacional seguro.

---

## 1. Documentos oficiais existentes

### 1.1. PROJETO_PONTE_MARCO_ZERO_ARQUITETURA_V1.md

Caminho:

`docs\projeto_ponte\PROJETO_PONTE_MARCO_ZERO_ARQUITETURA_V1.md`

Quando usar:

- antes de qualquer decisao arquitetural do Projeto Ponte;
- antes de criar codigo;
- antes de conectar navegador, Gmail, Workana, WhatsApp Web, CRM ou qualquer sistema externo;
- quando houver duvida sobre o que o Projeto Ponte e ou nao e;
- quando houver risco de misturar o WEB com Base ou Institucional.

Funcao:

- define o Projeto Ponte / MEI Robo WEB;
- separa Base, Institucional e WEB;
- define que Base e WEB sao irmaos operacionais;
- define arquitetura correta: observador, evento normalizado, nucleo read-only, politica, executor e logs;
- proibe comecar chamando diretamente `wa_bot`, `conversational_front` ou `customer_final.generate_reply`;
- define que o nucleo Ponte nasce read-only por padrao.

Status:

- documento arquitetural soberano;
- deve ser respeitado antes de qualquer implementacao.

---

### 1.2. PROJETO_PONTE_CONVERGENCIA_3_VERTENTES_V1.md

Caminho:

`docs\projeto_ponte\PROJETO_PONTE_CONVERGENCIA_3_VERTENTES_V1.md`

Quando usar:

- quando houver duvida sobre a relacao entre Base, Institucional e WEB;
- quando for necessario preservar qualidade equivalente entre as vertentes;
- quando for discutir inteligencia setorial compartilhada;
- quando houver risco de misturar atendimento operacional do cliente com venda institucional da plataforma.

Funcao:

- explica as tres vertentes do ecossistema MEI Robo;
- define qualidade unica percebida;
- mostra que as vertentes podem ter codigos diferentes, mas devem compartilhar padroes;
- define a inteligencia setorial compartilhada como apoio futuro, nunca como substituta dos dados especificos do cliente;
- reforca que o WEB deve ter caminho proprio, sem herdar cegamente handlers vivos do Base.

Status:

- documento de convergencia soberano;
- deve orientar decisoes entre Base, Institucional e WEB.

---

### 1.3. PROJETO_PONTE_CAPTACAO_MARKETPLACES_READONLY_POC_V1.md

Caminho:

`docs\projeto_ponte\PROJETO_PONTE_CAPTACAO_MARKETPLACES_READONLY_POC_V1.md`

Quando usar:

- antes de iniciar a primeira POC operacional do Projeto Ponte;
- antes de trabalhar com Workana;
- antes de usar notificacoes Gmail;
- antes de criar fixtures de oportunidades;
- antes de criar parser, classificador, relatorio ou rascunho de proposta;
- antes de pensar em plataformas nacionais ou internacionais de captacao.

Funcao:

- define a primeira POC read-only de captacao de oportunidades;
- trata Workana como primeira fonte, mas nao como centro fixo da arquitetura;
- prepara o Projeto Ponte para outras plataformas, inclusive internacionais e em outros idiomas;
- define o que a POC pode fazer e o que nao pode fazer;
- define evento normalizado de oportunidade;
- define politica de permissoes;
- define deduplicacao;
- define relatorio gerado;
- define rascunho de proposta;
- define criterios para avancar para codigo, Gmail real e navegador.

Status:

- documento operacional da Onda 1;
- deve ser usado antes de qualquer implementacao da POC de captacao.

---

## 2. Ordem correta de leitura

Para qualquer retomada do Projeto Ponte, ler nesta ordem:

1. `docs\projeto_ponte\README.md`
2. `docs\projeto_ponte\PROJETO_PONTE_MARCO_ZERO_ARQUITETURA_V1.md`
3. `docs\projeto_ponte\PROJETO_PONTE_CONVERGENCIA_3_VERTENTES_V1.md`
4. `docs\projeto_ponte\PROJETO_PONTE_CAPTACAO_MARKETPLACES_READONLY_POC_V1.md`

---

## 3. Estado atual do Projeto Ponte

Estado atual:

- Marco Zero arquitetural ja existe;
- Convergencia das 3 vertentes ja existe;
- POC de captacao em marketplaces read-only foi definida;
- Workana sera a primeira fonte pratica;
- a arquitetura deve nascer multi-plataforma;
- outras tres plataformas futuras estao previstas, incluindo uma internacional em outro idioma.

Proximo passo operacional:

1. validar e commitar este indice e o documento da POC;
2. pedir uma varredura read-only ao Codex para localizar pontos seguros de criacao da estrutura isolada do Ponte;
3. criar estrutura separada apenas depois da varredura;
4. iniciar com fixtures locais, sem Gmail real, sem Workana real, sem navegador e sem envio.

---

## 4. Regra para novos documentos

Nenhum novo documento do Projeto Ponte deve ficar solto.

Sempre que um documento novo for criado em `docs\projeto_ponte`, este README deve ser atualizado com:

- nome do documento;
- caminho;
- quando usar;
- funcao;
- status;
- relacao com a fase atual.

Se o documento nao tiver uso claro, ele nao deve ser criado.

---

## 5. Modo operacional obrigatorio

Para qualquer acao local no Projeto Ponte:

- usar 100% Windows CMD;
- nao usar PowerShell;
- nao usar IDE;
- nao usar `git add .`;
- nao fazer deploy sem autorizacao;
- nao abrir secrets, envs, tokens ou cookies;
- nao tocar Firestore, Cloud Run, Storage, Gmail real, agenda ou navegador sem autorizacao explicita;
- fazer analise de risco antes de cada onda;
- executar uma onda pequena por vez;
- validar antes e depois;
- preservar separacao entre Base, Institucional e WEB.

---

## 6. Regras da primeira POC

A primeira POC e de captacao read-only.

Permitido:

- fixtures locais;
- textos anonimizados;
- exemplos artificiais;
- extracao;
- classificacao;
- resumo;
- rascunho;
- relatorio local;
- dry-run.

Bloqueado:

- envio de proposta;
- abertura de chat;
- clique em link;
- scraping;
- login em plataforma;
- Workana por navegador;
- Gmail real sem autorizacao futura;
- Firestore;
- Storage;
- Cloud Run;
- deploy;
- alteracao no MEI Robo Base;
- alteracao no MEI Robo Institucional.

---

## 7. Diretriz final

Este README deve impedir que o Projeto Ponte vire uma colecao de documentos esquecidos.

A regra e:

`documento criado -> documento registrado no indice -> uso claro -> proxima acao definida`

O Projeto Ponte deve avancar com seguranca, rastreabilidade e separacao clara das demais vertentes do MEI Robo.