# PROJETO PONTE / MEI ROBÔ WEB

## MARCO ZERO ARQUITETURAL V1

### 1. Objetivo do documento

Este documento consolida o entendimento, as decisões arquiteturais e o caminho inicial para construção do **MEI Robô WEB**, também chamado de **Projeto Ponte**.

O objetivo do Projeto Ponte é criar um subproduto do MEI Robô capaz de operar canais e sistemas via navegador, especialmente quando não existe API oficial disponível ou quando o cliente utiliza WhatsApp Business comum, WhatsApp Web, CRM, Workana, Gmail, portais ou aplicações web próprias.

O MEI Robô WEB deve atuar como assistente comercial e operacional do cliente, lendo mensagens/eventos em tela, compreendendo o contexto, gerando respostas, sugerindo ações e, quando permitido, executando ações no navegador como um humano faria.

O produto deve nascer robusto, auditável, seguro e separado do MEI Robô oficial que já opera via WhatsApp Business API/YCloud.

---

### 2. Os três eixos do ecossistema MEI Robô

O ecossistema MEI Robô possui três vertentes principais:

1. **MEI Robô Base**
2. **MEI Robô Institucional**
3. **MEI Robô WEB / Projeto Ponte**

Essas três vertentes não devem ser misturadas no código nem na arquitetura, embora possam compartilhar inteligência, padrões de qualidade, contratos e fontes de conhecimento.

---

### 3. MEI Robô Base

O MEI Robô Base é o produto principal atual.

Uma empresa, profissional ou MEI se cadastra na plataforma, configura sua conta, seu jeito de atender, seus produtos, serviços, contatos, regras, documentos, imagens, cursos, materiais e acervo.

As informações ficam principalmente em estruturas como:

* `profissionais/{uid}`;
* subcoleções de produtos e serviços;
* contatos/clientes do profissional;
* regras operacionais;
* agenda;
* Storage/acervo;
* configurações de persona, tom e atendimento.

Esse produto foi projetado para operar pelo **WhatsApp Business API/YCloud**, atendendo clientes finais do profissional ou empresa cadastrada.

O MEI Robô Base é operacional: responde, orienta, consulta informações do cliente, usa acervo, pode lidar com agenda, orçamento, memória de contato e demais funcionalidades do produto.

---

### 4. MEI Robô Institucional

O MEI Robô Institucional é o robô da própria plataforma MEI Robô.

Ele não atende o cliente final do profissional cadastrado. Ele atende leads, usuários e clientes da própria plataforma.

Possui modos como:

* Vendas;
* Suporte;
* Configuração de voz.

O modo Vendas usa estruturas como:

* `platform_kb/sales`;
* `kb_archetypes_v1`;
* `kb_segments_v1`;
* `kb_subsegments_v1`;
* microcenas comerciais;
* lógica institucional de venda do MEI Robô.

Esse eixo tem papel diferente do Base e do WEB. Ele vende, explica, suporta e configura o MEI Robô.

Contudo, a estrutura segmentada construída no Institucional pode futuramente virar uma camada de **inteligência setorial compartilhada**, abastecendo também o Base e o WEB com informações qualificadas de segmentos e subsegmentos.

---

### 5. MEI Robô WEB / Projeto Ponte

O MEI Robô WEB é um novo subproduto.

Ele deve permitir que o MEI Robô opere canais e sistemas acessados por navegador, como:

* WhatsApp Web;
* WhatsApp Business comum;
* CRM do cliente;
* Workana;
* Gmail;
* portais;
* sistemas internos;
* aplicações web com login e senha.

O MEI Robô WEB é irmão operacional do MEI Robô Base.

A diferença principal entre Base e WEB não está no raciocínio do robô, mas no canal de captura e resposta.

O Base recebe e responde via WhatsApp Business API/YCloud.

O WEB observa e atua via navegador, lendo tela, extraindo eventos, digitando, clicando e executando ações sob política.

Assim, o WEB deve poder acessar as mesmas famílias de informação operacional do Base:

* conta do profissional;
* produtos e serviços;
* contatos;
* histórico;
* regras;
* documentos;
* Storage;
* acervo;
* agenda;
* contexto do negócio;
* inteligência setorial permitida.

---

### 6. Objetivo operacional do MEI Robô WEB

O objetivo é permitir que empresários, MEIs e entidades tenham um assistente de vendas e operação funcionando mesmo quando não usam API oficial.

O MEI Robô WEB deve:

1. observar conversas e eventos em sistemas web;
2. identificar mensagens novas;
3. entender o cliente, a intenção e o contexto;
4. consultar dados permitidos do cliente;
5. gerar resposta adequada;
6. sugerir ações;
7. executar ações somente quando permitido;
8. registrar logs e rastreabilidade;
9. recuperar-se de quedas, travamentos e falhas de sessão;
10. acionar humano apenas como última instância real.

A intenção comercial e operacional é substituir ao máximo a intervenção humana, mas sem irresponsabilidade. O handoff humano existe, porém deve ser raro, criterioso e reservado a exceções fortes.

---

### 7. Princípio central

O MEI Robô WEB deve separar rigorosamente:

```text
observar ≠ entender ≠ responder ≠ executar ≠ gravar ≠ enviar ≠ agendar
```

O núcleo inicial deve calcular e retornar uma resposta ou plano de ação.

A execução real — clique, envio, agenda, e-mail, orçamento, memória, CRM — deve ocorrer apenas se a política permitir explicitamente.

---

### 8. Arquitetura conceitual correta

A arquitetura correta do MEI Robô WEB é:

```text
Canal WEB / Navegador
↓
Observador de tela
↓
Evento normalizado
↓
Núcleo Ponte read-only/controlado
↓
Resposta ou plano de ação
↓
Executor com política
↓
Logs, auditoria e recuperação
```

O erro arquitetural a evitar é:

```text
WhatsApp Web
↓
texto extraído
↓
customer_final.generate_reply
↓
digita resposta
```

Esse caminho parece rápido, mas é frágil porque o handler operacional atual mistura resposta, estado, memória, acervo, Firestore, OpenAI, orçamento, agenda e e-mail.

---

### 9. Descobertas técnicas da auditoria

A auditoria do repositório atual mostrou que:

1. `services/wa_bot.py::reply_to_text` não é uma boa entrada para o Projeto Ponte, pois mistura canal oficial WhatsApp/YCloud, suporte, vendas, legacy, SEND_LINK e pós-processamento.

2. `services/conversational_front.py::handle` é um motor conversacional importante, mas não deve ser chamado cru. Ele depende de `state_summary` e `kb_snapshot` corretos e pode chamar OpenAI.

3. `services/bot_handlers/customer_final.py::generate_reply` é o melhor mapa operacional encontrado abaixo de YCloud, mas não é um adapter seguro para Ponte.

4. `customer_final.generate_reply` pode acionar efeitos reais:

   * Firestore;
   * speaker state;
   * contact memory;
   * cache/kv;
   * acervo;
   * Storage/GCS;
   * embeddings;
   * OpenAI/LLM;
   * orçamento;
   * e-mail;
   * agenda.

5. `force_operational=True` apenas pula o bloco `conversational_front`; não bloqueia acervo, catálogo, LLM econômico, memória, preço, agenda, orçamento ou e-mail.

6. O sistema atual usa `waKey` como chave prática de continuidade, mas isso é WhatsApp/telefone-oriented. Em pontos como `speaker_state`, a chave é normalizada para dígitos, o que pode causar vazio ou colisão para canais como Workana, Gmail ou CRM.

---

### 10. Decisões arquiteturais consolidadas

#### PONTE-ARQ-001

O Projeto Ponte não deve começar chamando YCloud, `wa_bot` ou `conversational_front` cru.

`customer_final.generate_reply` é o candidato operacional mais promissor encontrado, mas somente como referência arquitetural, não como adapter direto.

#### PONTE-ARQ-002

O Projeto Ponte não deve executar `customer_final.generate_reply` contra ambiente vivo enquanto não existir política explícita de segurança.

O runtime atual permite efeitos reais por fluxo interno.

#### PONTE-ARQ-003

`customer_final.generate_reply` não será usado como adapter direto do Projeto Ponte.

Ele será tratado como mapa do atendimento operacional atual.

#### PONTE-ARQ-004

O Projeto Ponte deverá nascer com um núcleo próprio, read-only por padrão, usando apenas funções puras ou loaders explicitamente permitidos.

#### PONTE-ARQ-005

O MEI Robô WEB deve ser tratado como irmão operacional do MEI Robô Base.

A diferença principal entre Base e WEB é o canal de entrada e execução, não a natureza da inteligência operacional.

#### PONTE-ARQ-006

A estrutura de segmentos e subsegmentos desenvolvida para o Institucional poderá futuramente alimentar Base e WEB como camada de inteligência setorial compartilhada, desde que exista contrato claro de leitura, prioridade e governança.

---

### 11. Helpers reaproveitáveis do `customer_final`

#### Reaproveitáveis diretamente ou como inspiração segura

* `_get_robot_persona(ctx)`
  Lê `ctx["robotPersona"]` e retorna dict. Seguro.

* `_format_catalog_brief(snapshot)`
  Formata um snapshot já carregado em texto curto. Seguro.

#### Reaproveitáveis apenas para compatibilidade legada

* `_wa_key_digits`;
* `_get_contact_key`.

Esses helpers são puros, mas telefônicos/WhatsApp-oriented. Não devem ser usados como identidade canônica do Ponte.

#### Reaproveitáveis somente com gates explícitos

* `_load_prof_catalog_snapshot`
  Lê Firestore. Pode ser útil no futuro, mas o núcleo inicial deve preferir snapshot injetado.

* `_try_acervo`
  Pode consultar Firestore, Storage/GCS, embeddings e LLM auxiliar. Útil, mas não entra no núcleo read-only inicial.

#### Fora do núcleo inicial

* `_get_and_bump_turns`;
* `_maybe_record_contact_event`;
* `_llm_extract_memory_event`;
* `_call_llm_min`;
* orçamento;
* agenda;
* e-mail;
* escrita de memória;
* escrita de estado.

---

### 12. Identidade de conversa no Projeto Ponte

O Projeto Ponte não deve usar `waKey` como identidade universal.

A identidade precisa ser abstrata e segura para múltiplos canais.

Contrato conceitual:

```text
channel
external_contact_id
external_thread_id
contact_key_raw
state_key
display_contact
```

Exemplos:

```text
channel = "whatsapp_web"
external_contact_id = "+555199999999"
external_thread_id = "+555199999999"
state_key = hash("whatsapp_web|+555199999999|+555199999999")
```

```text
channel = "workana"
external_contact_id = "buyer_123"
external_thread_id = "project_456"
state_key = hash("workana|buyer_123|project_456")
```

```text
channel = "gmail"
external_contact_id = "cliente@email.com"
external_thread_id = "thread_abc"
state_key = hash("gmail|cliente@email.com|thread_abc")
```

A compatibilidade com `waKey` antigo deve ser tratada apenas em adaptadores legados, nunca como identidade central do Projeto Ponte.

---

### 13. Núcleo Ponte read-only

O primeiro núcleo do Projeto Ponte deve ser read-only por padrão.

Ele não deve:

* escrever Firestore;
* escrever memória;
* escrever cache;
* enviar e-mail;
* criar orçamento;
* criar agenda;
* clicar em tela;
* enviar mensagem;
* chamar LLM externo sem permissão;
* consultar Storage/embeddings sem permissão.

Entrada conceitual:

```python
{
    "uid_owner": "...",
    "channel": "...",
    "external_thread_id": "...",
    "external_contact_id": "...",
    "state_key": "...",
    "user_text": "...",
    "persona": {},
    "catalog_snapshot": {},
    "context_snapshot": {},
    "sector_snapshot": {},
    "policy": {}
}
```

Saída conceitual:

```python
{
    "ok": True,
    "reply_text": "...",
    "understanding": {},
    "suggested_actions": [],
    "blocked_actions": [],
    "sources_used": [],
    "risk_flags": [],
    "confidence": 0.0,
    "handoff_recommendation": False,
    "telemetry": {}
}
```

---

### 14. Política de permissões

A política deve existir desde o primeiro desenho.

Padrão inicial:

```python
{
    "dry_run": True,
    "allow_firestore_read": False,
    "allow_firestore_write": False,
    "allow_storage_read": False,
    "allow_embeddings": False,
    "allow_llm": False,
    "allow_memory_write": False,
    "allow_budget_create": False,
    "allow_budget_send": False,
    "allow_schedule_propose": False,
    "allow_schedule_create": False,
    "allow_email": False,
    "allow_external_send": False
}
```

O núcleo não deve executar ações reais. Ele deve apenas retornar ações sugeridas ou bloqueadas.

---

### 15. Fontes de informação do MEI Robô WEB

O MEI Robô WEB deverá usar, em fases progressivas, fontes parecidas com o Base:

1. snapshot injetado no primeiro teste;
2. conta do profissional;
3. produtos e serviços;
4. regras de atendimento;
5. contato/histórico do cliente;
6. agenda;
7. acervo/Storage;
8. documentos e materiais do cliente;
9. inteligência setorial compartilhada;
10. contexto extraído da tela;
11. CRM ou sistema externo, se permitido.

No primeiro núcleo read-only, a fonte deve ser preferencialmente injetada via `catalog_snapshot`, `context_snapshot` e `sector_snapshot`, sem leitura direta de Firestore/Storage.

---

### 16. Inteligência setorial compartilhada

A estrutura segmentada do Institucional poderá futuramente ajudar Base e WEB.

Exemplo:

```text
subsegmento = "escritório de advocacia"
↓
dores típicas
serviços comuns
linguagem adequada
riscos de atendimento
perguntas frequentes
processos típicos
cuidados comerciais e operacionais
↓
Base e WEB podem usar como fonte auxiliar
```

Essa inteligência não substitui os dados do cliente.

A prioridade deve ser:

```text
1. dados específicos do cliente
2. acervo/documentos do cliente
3. regras e configurações do cliente
4. inteligência setorial compartilhada
5. conhecimento geral permitido
```

Assim, o robô não responde genericamente quando o cliente tem dados próprios configurados.

---

### 17. Níveis de autonomia

O MEI Robô WEB deve evoluir por níveis.

| Nível | Descrição                                       |
| ----- | ----------------------------------------------- |
| 0     | Só observa a tela e registra eventos            |
| 1     | Sugere resposta para aprovação humana           |
| 2     | Envia respostas simples de baixo risco sozinho  |
| 3     | Executa ações operacionais simples              |
| 4     | Agenda, orçamento e CRM com permissão explícita |
| 5     | Operação autônoma com supervisão por exceção    |

O piloto inicial no Workana deve começar no Nível 1 ou Nível 2, não no Nível 5.

---

### 18. Handoff humano

O handoff humano deve existir, mas como última instância real.

Ele não deve ser saída fácil.

Critérios possíveis de handoff:

* baixa confiança persistente;
* emergência;
* risco jurídico;
* risco financeiro;
* conflito;
* ameaça;
* pedido fora do escopo;
* dado sensível;
* tela travada;
* sessão caída sem recuperação;
* risco de responder na conversa errada;
* ação que exige permissão não concedida.

Preferência operacional:

```text
bloquear → sugerir → pedir supervisão → handoff
```

O humano não deve ser acionado quando o robô apenas poderia fazer uma pergunta objetiva ou responder com segurança.

---

### 19. Arquitetura em fases

#### Fase 0 — Marco Zero Arquitetural

Consolidar decisões, limites, contratos, riscos, fases, política e primeira arquitetura.

#### Fase 1 — Núcleo Ponte read-only

Criar o núcleo seguro, sem navegador, sem execução real e com snapshots injetados.

#### Fase 2 — Observador WEB

Ler tela/eventos sem agir.

Primeiro alvo provável: WhatsApp Web.

Funções:

* detectar mensagem nova;
* identificar conversa;
* extrair texto;
* evitar duplicidade;
* normalizar evento;
* registrar logs.

#### Fase 3 — Executor controlado

Permitir que o robô escreva ou envie resposta sob política.

Primeiro com aprovação humana, depois com autonomia baixa.

#### Fase 4 — Piloto Workana supervisionado

O usuário será o primeiro supervisor.

Objetivo do piloto:

* validar leitura;
* validar resposta;
* evitar duplicidade;
* evitar conversa errada;
* recuperar queda;
* manter logs;
* medir confiança.

#### Fase 5 — Robustez de nuvem

Preparar execução em servidor.

Requisitos:

* sessão persistente por cliente;
* isolamento por cliente;
* credenciais em cofre;
* watchdog;
* heartbeat;
* fila;
* deduplicação;
* reconexão;
* detecção de logout;
* detecção de QR code;
* logs auditáveis;
* screenshots/snapshots quando necessário;
* política de recuperação.

#### Fase 6 — Autonomia progressiva

Aumentar permissões conforme confiança e testes.

---

### 20. Robustez e segurança

O MEI Robô WEB deve nascer considerando:

* quedas de conexão;
* logout do WhatsApp Web;
* expiração de QR code;
* navegador travado;
* mudança de layout;
* delays de carregamento;
* anexos parcialmente carregados;
* risco de resposta duplicada;
* risco de responder conversa errada;
* risco de credencial exposta;
* risco de sessão cruzada entre clientes;
* risco de execução sem permissão.

Requisitos mínimos:

1. credenciais em cofre;
2. logs por cliente/canal/thread;
3. deduplicação por mensagem/evento;
4. fila de eventos;
5. watchdog de sessão;
6. heartbeat do worker;
7. screenshots/snapshots em falhas;
8. política de parada segura;
9. recuperação automática quando possível;
10. aviso ao supervisor quando necessário.

---

### 21. Primeiro piloto

O primeiro piloto será supervisionado pelo usuário.

Cenário previsto:

* cliente captado via Workana;
* MEI Robô WEB acoplado ao ambiente do cliente;
* uso inicial em WhatsApp Web, CRM ou aplicação indicada;
* usuário acompanha a operação;
* robô começa em autonomia baixa;
* logs e exceções são analisados;
* handoff humano é exceção real.

Objetivo do piloto:

```text
provar que o robô lê certo, entende certo, responde certo, não duplica, não se perde, não envia na conversa errada e avisa quando não consegue seguir com segurança.
```

---

### 22. O que não fazer no início

Não iniciar por:

* Playwright direto;
* login em WhatsApp Web;
* envio automático;
* agenda real;
* orçamento real;
* e-mail real;
* `customer_final.generate_reply` cru;
* `wa_bot.reply_to_text`;
* `conversational_front.handle` cru;
* ações em produção sem núcleo seguro;
* deploy;
* refatoração ampla do MEI Robô oficial.

---

### 23. Próxima etapa após este Marco Zero

A próxima etapa técnica deverá ser planejada com cuidado.

Caminho recomendado:

1. criar um módulo separado para o Projeto Ponte;
2. criar contrato de evento normalizado;
3. criar contrato de política;
4. criar núcleo read-only mínimo;
5. usar snapshot injetado, sem Firestore no primeiro teste;
6. retornar resposta estruturada;
7. não executar ação real;
8. escrever testes locais;
9. só depois conectar observador WEB.

---

### 24. Diretriz final

O MEI Robô WEB deve ser construído como subproduto robusto, não como gambiarra de navegador.

Ele deve usar a inteligência e aprendizados do MEI Robô atual, mas não deve se acoplar diretamente aos handlers vivos que gravam, enviam, agendam ou disparam efeitos reais.

A arquitetura correta é:

```text
Canal WEB
↓
Observador
↓
Evento normalizado
↓
Núcleo Ponte read-only/controlado
↓
Resposta/plano
↓
Executor com política
↓
Logs, auditoria e recuperação
```

O primeiro objetivo é provar o núcleo seguro.

Depois vem a automação de navegador.
