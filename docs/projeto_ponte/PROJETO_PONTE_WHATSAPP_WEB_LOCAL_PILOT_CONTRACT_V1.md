# PROJETO PONTE / MEI ROBO WEB

## CONTRATO WHATSAPP WEB LOCAL PILOT V1

### 1. Objetivo

Este documento define o contrato do piloto local WhatsApp Web do Projeto Ponte.

O objetivo do piloto e permitir que, futuramente, o MEI Robo leia mensagens de um WhatsApp Web autorizado pelo cliente, no computador local do operador, gere respostas usando o cerebro do MEI Robo Base/Vendedor e execute acoes somente dentro de limites seguros.

Este contrato nao autoriza abrir navegador, ler WhatsApp Web real, digitar ou enviar mensagens. Ele apenas registra o modo correto para chegar la.

---

### 2. Separacao entre Produto Base e Ponte

Produto Base SaaS:

- uso padrao por WhatsApp API oficial/YCloud/Cloud API;
- assinatura;
- pagamento;
- configuracao pelo proprio cliente;
- operacao regular e escalavel.

Projeto Ponte / WhatsApp Web Pilot:

- projeto especial;
- cliente especifico;
- autorizacao especifica;
- ambiente controlado;
- testes locais antes de nuvem;
- politicas de seguranca e aprovacao humana;
- nao deve contaminar o Base oficial.

Regra central:

`WhatsApp API = produto padrao. WhatsApp Web = piloto especial autorizado.`

---

### 3. Meta pratica do piloto

Fluxo desejado no futuro:

`WhatsApp Web local -> evento Ponte -> MEI Robo Base/Vendedor -> resposta sugerida -> politica de seguranca -> envio aprovado ou fila humana`

O Ponte deve atuar como camada de canal e seguranca.

O MEI Robo Base/Vendedor deve atuar como cerebro comercial.

---

### 4. Escada de implementacao

A ordem correta das ondas e:

1. WW-0: contrato do piloto WhatsApp Web local;
2. WW-1: adapter local de mensagem WhatsApp Web simulada;
3. WW-2: fila local unificada para eventos WhatsApp/Gmail/Workana/CRM;
4. WW-3: observador local read-only do navegador;
5. WW-4: gerar resposta sugerida sem digitar;
6. WW-5: preencher campo de texto sem enviar;
7. WW-6: enviar somente com aprovacao humana explicita;
8. WW-7: preparar execucao em nuvem/servidor dedicado.

Nenhuma onda deve pular a anterior.

---

### 5. Modos operacionais

#### 5.1 LOCAL_SIMULATION

Entrada simulada em arquivo ou dicionario local.

Permitido:

- criar evento;
- classificar;
- gerar resposta sugerida;
- colocar em fila;
- rodar testes.

Bloqueado:

- WhatsApp Web real;
- navegador;
- clique;
- digitacao;
- envio.

#### 5.2 LOCAL_READONLY_BROWSER

Fase futura.

Permitido somente depois de nova autorizacao:

- abrir navegador local;
- observar mensagens;
- capturar texto visivel;
- gerar evento.

Bloqueado:

- digitar;
- enviar;
- clicar em links;
- baixar midia;
- alterar contatos;
- responder grupos sem regra propria.

#### 5.3 LOCAL_DRAFT_ONLY

Fase futura.

Permitido somente depois de read-only validado:

- gerar resposta;
- preencher campo de texto, se for seguro;
- parar antes de enviar.

Bloqueado:

- apertar Enter;
- clicar enviar;
- enviar midia;
- responder conversa errada.

#### 5.4 LOCAL_APPROVED_SEND

Fase futura.

Permitido somente com aprovacao humana clara:

- enviar resposta aprovada;
- registrar auditoria.

Obrigatorio:

- limite de envios;
- botao/parada manual;
- dedupe;
- logs;
- pausa imediata.

#### 5.5 CLOUD_ASSISTED_PILOT

Fase futura.

Permitido somente depois do piloto local estar estavel.

Requisitos:

- servidor dedicado;
- sessao controlada;
- reconexao;
- logs;
- watchdog;
- parada emergencial;
- limite de horario;
- politica de privacidade;
- aprovacao do cliente.

---

### 6. Evento canonico WhatsApp Web

Nome conceitual:

`whatsapp_web_message_event`

Campos minimos:

    source_platform = "whatsapp_web"
    source_channel = "local_browser"
    pilot_mode
    client_authorization_ref
    chat_title
    chat_type
    chat_identifier_hash
    message_text
    message_direction
    message_timestamp
    message_index
    conversation_id
    dedupe_key
    received_at
    requires_human_approval
    dry_run
    can_send_message

Campos opcionais:

    sender_label
    visible_phone_masked
    last_messages_context
    attachment_present
    audio_present
    unread_count
    browser_session_id
    operator_note

Campos que nao devem ser registrados em log publico:

    numero completo sem necessidade
    dados sensiveis do cliente final
    cookies
    tokens
    QR code
    credenciais
    prints de tela com dados pessoais
    mensagens completas fora do necessario para debug controlado

---

### 7. Politica inicial de permissao

Estado atual deste contrato:

    can_read_whatsapp_web_real = false
    can_open_browser = false
    can_click = false
    can_type = false
    can_send_message = false
    can_download_media = false
    can_open_link = false
    can_modify_contact = false
    can_delete_message = false
    can_write_firestore = false
    can_deploy = false

    can_process_local_simulation = true
    can_generate_suggested_reply = true
    can_build_review_queue = true

    requires_human_approval = true
    dry_run = true

Qualquer mudanca em permissao exige documento/onda propria.

---

### 8. Regras anti-erro de conversa

Antes de qualquer envio futuro, o Ponte deve proteger contra:

1. responder conversa errada;
2. responder grupo sem permissao;
3. responder mensagem antiga;
4. responder mensagem duplicada;
5. responder mensagem propria;
6. entrar em loop bot-bot;
7. enviar texto incompleto;
8. enviar resposta para lead sem contexto suficiente;
9. clicar em link;
10. processar anexo automaticamente.

---

### 9. Regras de parada

O piloto deve prever parada imediata.

Sinais de parada:

- usuario digita comando manual de pausa;
- operador desativa execucao;
- erro de navegador;
- troca inesperada de conversa;
- muitas mensagens em curto periodo;
- resposta incerta;
- dado sensivel detectado;
- pedido humano explicito;
- risco comercial/reputacional.

Na duvida, nao enviar.

---

### 10. Relacao com MEI Robo Base/Vendedor

O WhatsApp Web Pilot nao deve virar um segundo cerebro.

Ele deve entregar ao MEI Robo Base/Vendedor um evento limpo:

`chegou esta mensagem neste chat, neste contexto, com estas restricoes`

O MEI Robo Base/Vendedor deve devolver:

`resposta sugerida, objetivo comercial, nivel de confianca, necessidade de aprovacao`

O Ponte aplica a politica:

`enviar, colocar em fila, pedir aprovacao ou bloquear`

---

### 11. Relacao com Workana e CRM

O WhatsApp Web Pilot deve ser compativel com o mesmo padrao ja usado para Gmail/Workana:

- evento normalizado;
- dedupe;
- classificacao;
- trava de risco;
- fila humana;
- auditoria;
- permissao explicita.

Para CRM, preferir API/conector oficial quando existir.

Navegador deve ser usado somente quando nao houver alternativa mais segura.

---

### 12. Proxima etapa depois deste contrato

A proxima etapa tecnica recomendada e WW-1:

`adapter local de mensagem WhatsApp Web simulada`

Ele deve receber uma mensagem local simulada e converter para evento Ponte, sem abrir navegador real.

So depois disso pensar em observador local read-only.

---

### 13. Modo operante de retomada

Ao retomar o Projeto Ponte para WhatsApp Web:

1. abrir este documento;
2. confirmar ultimo commit;
3. confirmar status limpo;
4. rodar testes Ponte;
5. rodar fila local;
6. revisar a escada WW;
7. executar apenas a proxima onda pequena;
8. commitar;
9. atualizar README;
10. nunca pular direto para navegador real.

Comandos de retomada:

`git --no-pager log --oneline -10`

`git --no-pager status --short`

`python -m unittest discover -s tests\ponte -p "test_*.py"`

`python -m services.ponte.batch_fixture_runner tests\fixtures\ponte`

---

### 14. Diretriz final

Este piloto existe para permitir que o MEI Robo Base/Vendedor atue em um WhatsApp Web autorizado, primeiro localmente e depois talvez em nuvem.

A prioridade e vender/atender melhor sem quebrar seguranca, reputacao ou o produto Base oficial.

O produto padrao continua sendo WhatsApp API.

O WhatsApp Web e uma ponte especial, controlada e auditavel.
