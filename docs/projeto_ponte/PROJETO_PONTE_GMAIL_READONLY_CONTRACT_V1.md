# PROJETO PONTE / MEI ROBO WEB

## CONTRATO GMAIL READ-ONLY V1

### 1. Objetivo

Este documento define o contrato da futura etapa Gmail read-only do Projeto Ponte.

A etapa Gmail read-only sera a primeira conexao real planejada depois da POC offline.

Ela deve permitir que o Projeto Ponte leia, de forma controlada, notificacoes recebidas no Gmail, principalmente oportunidades da Workana e futuramente de outras plataformas.

A etapa nao deve enviar, responder, clicar, arquivar, marcar, baixar anexos, abrir links, abrir Workana ou alterar qualquer dado.

---

### 2. Relacao com o estado atual

O Projeto Ponte ja possui uma POC offline capaz de:

- ler fixtures locais;
- extrair dados de oportunidades;
- normalizar eventos;
- gerar dedupe key;
- classificar aderencia;
- aplicar trava de risco;
- gerar rascunho;
- gerar relatorio;
- montar fila local de revisao humana.

A etapa Gmail read-only deve apenas substituir a origem da entrada:

`fixture local -> texto de e-mail lido em modo read-only`

Todo o restante deve continuar usando o nucleo Ponte ja existente.

---

### 3. Escopo permitido

Na primeira fase Gmail read-only, sera permitido:

1. buscar e-mails candidatos com filtro conservador;
2. ler metadados basicos;
3. ler assunto;
4. ler remetente;
5. ler snippet/corpo textual quando autorizado;
6. identificar possiveis notificacoes Workana;
7. transformar e-mail em evento Ponte;
8. classificar oportunidade;
9. gerar rascunho local;
10. gerar relatorio;
11. colocar em fila de revisao humana.

---

### 4. Escopo bloqueado

Na primeira fase Gmail read-only, e proibido:

1. enviar e-mail;
2. criar rascunho no Gmail;
3. responder e-mail;
4. encaminhar e-mail;
5. arquivar;
6. deletar;
7. marcar como lido;
8. aplicar label;
9. baixar anexo;
10. abrir link;
11. abrir Workana;
12. fazer login em plataforma;
13. usar navegador;
14. clicar;
15. enviar proposta;
16. abrir chat;
17. gravar Firestore;
18. gravar Storage;
19. chamar Cloud Run;
20. tocar MEI Robo Base;
21. tocar MEI Robo Institucional.

---

### 5. Conta de teste futura

Conta autorizada para teste futuro, somente quando a fase Gmail read-only for explicitamente iniciada:

`ricardodavilaoficial@gmail.com`

Esta autorizacao nao libera envio, alteracao ou acesso a navegador.

Ela permite apenas planejar uma futura leitura controlada.

Antes de qualquer leitura real, deve haver nova confirmacao operacional no CMD.

---

### 6. Politica de permissao Gmail read-only

Politica conceitual da fase:

    can_read_gmail_real = true
    can_search_gmail = true
    can_read_email_metadata = true
    can_read_email_text = true

    can_send_email = false
    can_create_gmail_draft = false
    can_forward_email = false
    can_archive_email = false
    can_delete_email = false
    can_mark_read = false
    can_apply_label = false
    can_download_attachment = false
    can_open_link = false
    can_open_workana = false
    can_login_platform = false
    can_click = false
    can_type = false
    can_submit_proposal = false
    can_write_firestore = false
    can_deploy = false

    requires_human_approval = true
    dry_run = true

---

### 7. Filtro inicial conservador

O filtro inicial deve ser restrito a possiveis notificacoes Workana.

Exemplos conceituais de busca, a validar antes de uso real:

    from:(workana) newer_than:30d

ou

    (from:(workana) OR subject:(Workana)) newer_than:30d

Limites iniciais:

- maximo de poucos e-mails por teste;
- preferir e-mails recentes;
- nao ler caixa inteira;
- nao usar busca ampla;
- nao processar anexos;
- nao abrir links.

---

### 8. Dados permitidos por e-mail

Campos permitidos na primeira leitura:

    gmail_message_id
    gmail_thread_id
    sender
    subject
    date
    snippet
    body_text_limited
    has_attachment
    link_candidates_as_text_only

Campos que nao devem ser registrados em log publico:

    tokens
    cookies
    dados pessoais desnecessarios
    corpo completo quando nao for necessario
    anexos
    links sensiveis em relatorios publicos

---

### 9. Conversao Gmail para evento Ponte

Um e-mail candidato deve ser convertido para evento Ponte assim:

    source_platform = "workana" ou plataforma detectada
    source_channel = "gmail_readonly"
    source_language = idioma detectado
    source_country = pais inferido
    source_currency = moeda inferida
    external_thread_id = gmail_thread_id
    external_contact_id = sender
    raw_subject = subject
    raw_text = snippet + corpo textual limitado
    dedupe_key = link do projeto, se existir, ou hash de titulo + descricao + remetente + thread

A conversao deve alimentar o mesmo parser/classificador offline ja existente.

---

### 10. Deduplicacao com Gmail real

Regra inicial:

1. se houver link de projeto, ele e o identificador principal;
2. se nao houver link, usar titulo + descricao + plataforma;
3. gmail_thread_id ajuda, mas nao deve ser o unico identificador;
4. nunca gerar duas propostas para a mesma oportunidade;
5. se o mesmo e-mail reaparecer, marcar como duplicado na fila local.

---

### 11. Saida esperada

A saida da fase Gmail read-only deve ser igual ao fluxo offline:

    oportunidade detectada
    evento normalizado
    classificacao
    riscos
    dedupe key
    rascunho de proposta
    status aguardando_revisao_humana
    nenhuma acao externa executada

---

### 12. Criterios para iniciar leitura real

Antes da primeira leitura real, confirmar:

1. working tree limpo;
2. testes Ponte passando;
3. fila offline funcionando;
4. filtro Gmail definido;
5. limite maximo de e-mails definido;
6. leitura real explicitamente autorizada no momento;
7. nenhuma funcao de envio sera chamada;
8. nenhuma funcao de alteracao sera chamada;
9. nenhum link sera aberto;
10. nenhum anexo sera baixado.

---

### 13. Criterios para avancar alem de read-only

So pensar em rascunho no Gmail ou interacao real quando:

1. leitura read-only estiver validada;
2. dedupe real estiver funcionando;
3. relatorios forem uteis;
4. falsos positivos estiverem controlados;
5. houver aprovacao humana clara;
6. houver logs seguros;
7. nao houver risco de acao involuntaria;
8. houver documento proprio para a nova permissao.

Enviar e-mail ou proposta continua fora de escopo.

---

### 14. Diretriz final

A etapa Gmail read-only e uma ponte entre a POC offline e fontes reais.

Ela deve provar que o Projeto Ponte consegue ler oportunidades reais com seguranca, sem interagir, sem enviar e sem afetar reputacao.

A ordem correta e:

    POC offline saudavel
    contrato Gmail read-only
    filtro conservador
    leitura limitada
    fila de revisao humana
    analise manual
    so depois novas permissoes

Nenhuma etapa de navegador, Workana real ou WhatsApp Web deve comecar antes de Gmail read-only estar seguro e auditavel.
