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



---

### 1.4. PROJETO_PONTE_GMAIL_READONLY_CONTRACT_V1.md

Caminho:

`docs\projeto_ponte\PROJETO_PONTE_GMAIL_READONLY_CONTRACT_V1.md`

Quando usar:

- antes de qualquer leitura real do Gmail;
- antes de buscar notificacoes Workana no Gmail;
- antes de conectar a conta `ricardodavilaoficial@gmail.com`;
- quando houver duvida sobre o que e permitido na fase Gmail read-only;
- antes de qualquer tentativa de avancar para navegador, Workana real ou WhatsApp Web.

Funcao:

- define o contrato da fase Gmail read-only;
- separa leitura de qualquer acao externa;
- define politica de permissao;
- define filtros conservadores;
- define conversao de e-mail para evento Ponte;
- define deduplicacao com Gmail real;
- define criterios para iniciar leitura real.

Status:

- documento de preparacao da Onda 2;
- nao autoriza leitura real sozinho;
- exige confirmacao operacional antes de qualquer acesso ao Gmail.


## 2. Ordem correta de leitura

Para qualquer retomada do Projeto Ponte, ler nesta ordem:

1. `docs\projeto_ponte\README.md`
2. `docs\projeto_ponte\PROJETO_PONTE_MARCO_ZERO_ARQUITETURA_V1.md`
3. `docs\projeto_ponte\PROJETO_PONTE_CONVERGENCIA_3_VERTENTES_V1.md`
4. `docs\projeto_ponte\PROJETO_PONTE_CAPTACAO_MARKETPLACES_READONLY_POC_V1.md`
5. `docs\projeto_ponte\PROJETO_PONTE_GMAIL_READONLY_CONTRACT_V1.md`

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

---

## 8. Como rodar a POC offline atual

A primeira POC executavel do Projeto Ponte roda somente com fixtures locais.

Ela usa:

`services\ponte\fixture_report_runner.py`

Comando Workana fixture:

`python -m services.ponte.fixture_report_runner tests\fixtures\ponte\workana_email_001.txt --platform workana`

Comando plataforma internacional fixture:

`python -m services.ponte.fixture_report_runner tests\fixtures\ponte\international_platform_001.txt --platform international_platform_01`

O que este runner faz:

- le fixture local `.txt`;
- normaliza evento;
- classifica aderencia;
- gera rascunho de proposta;
- gera relatorio legivel;
- mostra politica de bloqueio;
- mostra auditoria;
- opera em dry-run/read-only.

O que este runner nao faz:

- nao acessa Gmail real;
- nao acessa Workana real;
- nao abre navegador;
- nao clica em link;
- nao envia proposta;
- nao abre chat;
- nao grava Firestore;
- nao usa Cloud Run;
- nao toca Base ou Institucional.

Uso esperado:

- validar a POC offline;
- testar fixtures anonimizadas;
- avaliar qualidade do parser, classificador e rascunho;
- preparar futuras ondas antes de qualquer integracao real.

Observacao:

A fixture internacional ja roda em ingles, mas a classificacao ainda e conservadora. Melhorias de idioma devem ser feitas em onda propria.

---

## 9. Como rodar a fila local de revisao humana

A fila local de revisao humana processa todas as fixtures `.txt` de uma pasta e mostra uma lista consolidada de oportunidades.

Comando:

`python -m services.ponte.batch_fixture_runner tests\fixtures\ponte`

O que este runner faz:

- le varias fixtures locais;
- infere a plataforma pelo nome do arquivo;
- normaliza eventos;
- classifica aderencia;
- aplica trava de risco;
- gera status `aguardando_revisao_humana`;
- mostra dedupe key;
- confirma politica dry-run/read-only;
- bloqueia envio e mensagem.

O que este runner nao faz:

- nao acessa Gmail real;
- nao acessa Workana real;
- nao abre navegador;
- nao clica em link;
- nao envia proposta;
- nao abre chat;
- nao grava Firestore;
- nao usa Cloud Run;
- nao toca Base ou Institucional.

Uso esperado:

- validar varias oportunidades offline;
- simular a futura fila de aprovacao humana;
- preparar a etapa futura de Gmail read-only;
- manter o Projeto Ponte pronto para multiplas plataformas.

---

## 10. Estado atual pratico do Projeto Ponte

Estado atual apos a Onda 1G:

- existe documentacao oficial indexada em `docs\projeto_ponte`;
- existe nucleo offline isolado em `services\ponte`;
- existem testes locais em `tests\ponte`;
- existem fixtures versionadas em `tests\fixtures\ponte`;
- existe runner de relatorio individual;
- existe runner de fila local de revisao humana;
- existe classificacao em portugues e ingles;
- existe dedupe key para oportunidades;
- existe trava contra oportunidades com termos de risco;
- existe rascunho de proposta sempre em dry-run;
- existe politica bloqueando envio, clique, Gmail real, plataforma real e Firestore.

O Projeto Ponte, neste estado, ainda nao faz:

- acesso a Gmail real;
- acesso a Workana real;
- acesso a qualquer plataforma real;
- login;
- navegador;
- clique;
- envio de proposta;
- abertura de chat;
- escrita em Firestore;
- uso de Cloud Run;
- uso de Storage;
- alteracao no MEI Robo Base;
- alteracao no MEI Robo Institucional.

Resumo pratico:

`fixture local -> parser -> evento normalizado -> dedupe -> classificacao -> trava de risco -> rascunho -> relatorio -> fila de revisao humana`

---

## 11. Comandos canonicos da POC offline

Rodar todos os testes Ponte:

`python -m unittest discover -s tests\ponte -p "test_*.py"`

Rodar relatorio individual Workana:

`python -m services.ponte.fixture_report_runner tests\fixtures\ponte\workana_email_001.txt --platform workana`

Rodar relatorio individual de plataforma internacional:

`python -m services.ponte.fixture_report_runner tests\fixtures\ponte\international_platform_001.txt --platform international_platform_01`

Rodar fila local de revisao humana:

`python -m services.ponte.batch_fixture_runner tests\fixtures\ponte`

Validar py_compile dos modulos Ponte:

`for %f in (services\ponte\*.py) do python -m py_compile "%f"`

---

## 12. Proxima fronteira planejada

A proxima fronteira tecnica do Projeto Ponte e preparar Gmail read-only.

Antes de acessar Gmail real, ainda deve existir uma onda de desenho e seguranca contendo:

- filtro de busca Gmail conservador;
- escopo de leitura;
- regra para nao baixar anexo automaticamente;
- regra para nao clicar em links;
- regra para nao enviar e-mail;
- regra para nao abrir Workana por navegador;
- criterio de deduplicacao com dados reais;
- plano de desligamento imediato;
- confirmacao explicita do usuario antes de qualquer leitura real.

Conta autorizada para teste futuro, somente quando a fase Gmail read-only for iniciada com aprovacao explicita:

`ricardodavilaoficial@gmail.com`

Mesmo com essa conta registrada, o estado atual permanece offline. Nenhum acesso real deve ser feito antes de nova autorizacao operacional.

---

## 13. Regra de continuidade

Ao retomar o Projeto Ponte em qualquer instancia:

1. ler este README;
2. confirmar o ultimo commit;
3. rodar testes Ponte;
4. rodar a fila local;
5. so entao decidir a proxima onda.

Comandos de retomada:

`git --no-pager log --oneline -10`

`git --no-pager status --short`

`python -m unittest discover -s tests\ponte -p "test_*.py"`

`python -m services.ponte.batch_fixture_runner tests\fixtures\ponte`

Se esses comandos passarem, a base offline esta saudavel.

---

## 14. Adapter local Gmail read-only

A Onda 2B adiciona um adapter local para simular a futura entrada Gmail read-only sem acessar Gmail real.

Modulo:

`services\ponte\gmail_readonly_adapter.py`

O que ele faz:

- recebe um dicionario local representando um e-mail ja lido;
- normaliza metadados basicos;
- limita o corpo textual;
- preserva links apenas como texto;
- detecta plataforma provavel;
- converte o e-mail em evento Ponte;
- aplica politica Gmail read-only;
- mantem envio, clique, anexo, Workana real e navegador bloqueados.

O que ele nao faz:

- nao acessa Gmail real;
- nao usa API Gmail;
- nao envia e-mail;
- nao cria rascunho no Gmail;
- nao baixa anexo;
- nao abre link;
- nao abre Workana;
- nao usa navegador.

Comando de teste relacionado:

`python -m unittest discover -s tests\ponte -p "test_*.py"`

Este adapter prepara a forma tecnica da futura leitura real, mas nao autoriza acesso real por si so.

