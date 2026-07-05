# PROJETO PONTE / MEI ROBO WEB

## CAPTACAO EM MARKETPLACES E PLATAFORMAS — POC READ-ONLY V1

### 1. Objetivo do documento

Este documento define a primeira prova de conceito operacional do Projeto Ponte, com foco em captacao de oportunidades vindas de marketplaces, plataformas de freelas, portais de projetos e canais similares.

A primeira plataforma pratica sera a Workana, preferencialmente a partir de notificacoes recebidas por e-mail/Gmail.

Entretanto, a arquitetura desta POC nao deve nascer exclusiva da Workana. O objetivo e criar um modelo reaproveitavel para outras plataformas futuras, incluindo plataformas nacionais, plataformas setoriais e plataformas internacionais em outros idiomas.

A POC deve comecar em modo read-only, sem envio de proposta, sem inicio de conversa, sem clique automatico, sem scraping agressivo, sem automacao de navegador e sem qualquer acao que possa afetar reputacao, conta, entregabilidade ou relacionamento comercial do usuario.

---

### 2. Relacao com os documentos oficiais do Projeto Ponte

Este documento complementa os documentos oficiais ja existentes:

- docs\projeto_ponte\PROJETO_PONTE_MARCO_ZERO_ARQUITETURA_V1.md
- docs\projeto_ponte\PROJETO_PONTE_CONVERGENCIA_3_VERTENTES_V1.md

Esses documentos continuam soberanos.

Esta POC segue os principios ja definidos:

- Projeto Ponte e a vertente WEB do MEI Robo;
- WEB e Base sao irmaos operacionais;
- WEB nao deve chamar diretamente wa_bot, conversational_front ou customer_final.generate_reply;
- o nucleo Ponte deve nascer read-only por padrao;
- acoes reais so podem ocorrer com politica explicita;
- logs, auditoria, deduplicacao e humano-no-loop sao obrigatorios desde o inicio;
- a arquitetura deve preservar separacao entre Base, Institucional e WEB.

---

### 3. Escopo da POC

A POC inicial deve processar oportunidades de plataformas externas de forma segura.

Entrada inicial recomendada:

- texto copiado manualmente de notificacoes;
- e-mails exportados ou anonimizados;
- fixtures locais;
- amostras internas sem dados sensiveis;
- exemplos artificiais inspirados em oportunidades reais.

Primeira fonte real planejada:

- notificacoes Workana recebidas por Gmail.

Fontes futuras previstas:

- plataforma 02 nacional;
- plataforma 03 nacional ou setorial;
- plataforma 04 internacional, em outro idioma;
- outros canais de oportunidades por e-mail, portal ou navegador.

A POC deve produzir:

- evento normalizado;
- extracao dos dados principais;
- classificacao de aderencia;
- resumo da oportunidade;
- riscos;
- sugestao de abordagem;
- rascunho de proposta;
- status de aprovacao humana.

---

### 4. O que esta POC pode fazer

Nesta fase, a POC pode:

1. Ler texto fornecido manualmente em arquivo local.
2. Processar fixtures locais.
3. Identificar se o texto parece uma oportunidade.
4. Extrair titulo, descricao, orcamento, prazo, categoria, idioma e link quando existirem.
5. Classificar aderencia ao perfil do usuario.
6. Detectar sinais de risco.
7. Sugerir se vale responder, ignorar ou revisar.
8. Gerar rascunho de proposta.
9. Gerar relatorio local.
10. Registrar logs locais nao sensiveis.
11. Manter tudo em dry-run.
12. Solicitar aprovacao humana antes de qualquer acao externa.

---

### 5. O que esta POC nao pode fazer

Nesta fase, a POC nao pode:

1. Enviar proposta.
2. Responder cliente.
3. Abrir conversa em chat.
4. Clicar em links.
5. Acessar Workana por navegador.
6. Acessar qualquer marketplace por navegador.
7. Fazer login em plataforma externa.
8. Fazer scraping.
9. Baixar anexos automaticamente.
10. Gravar em Firestore.
11. Gravar em Storage.
12. Criar agenda.
13. Enviar e-mail.
14. Criar orcamento.
15. Mexer no MEI Robo Base.
16. Mexer no MEI Robo Institucional.
17. Usar wa_bot.reply_to_text.
18. Usar customer_final.generate_reply.
19. Usar conversational_front.handle.
20. Fazer deploy.
21. Abrir ou expor secrets, tokens, cookies ou envs.

---

### 6. Motivo para comecar offline

Comecar offline reduz risco de:

- prejudicar reputacao em marketplaces;
- iniciar conversa que nao sera atendida;
- parecer comportamento automatizado inadequado;
- enviar proposta incompleta;
- clicar em projeto errado;
- duplicar candidatura;
- violar regras de plataforma;
- misturar dados pessoais ou sensiveis;
- comprometer conta real;
- acoplar o Ponte cedo demais ao runtime do MEI Robo Base.

A primeira validacao deve provar que o nucleo entende oportunidades e gera bons relatorios antes de qualquer integracao real.

---

### 7. Modelo multi-plataforma

A POC deve tratar Workana como primeira plataforma, mas nao como centro fixo da arquitetura.

Cada oportunidade deve ter campos genericos:

- source_platform
- source_channel
- source_language
- source_country
- source_currency
- external_opportunity_id
- external_thread_id
- external_contact_id
- platform_url

Exemplo Workana:

    source_platform = "workana"
    source_channel = "gmail_notification"
    source_language = "pt-BR"
    source_country = "BR"
    source_currency = "BRL"

Exemplo plataforma internacional futura:

    source_platform = "international_platform_01"
    source_channel = "email_notification"
    source_language = "en"
    source_country = "US"
    source_currency = "USD"

A logica deve separar:

1. camada comum de oportunidade;
2. camada especifica da plataforma;
3. camada especifica do idioma;
4. camada especifica da estrategia comercial.

---

### 8. Evento normalizado

Contrato conceitual do evento:

    ponte_opportunity_event = {
      event_id,
      event_type,
      source_platform,
      source_channel,
      source_language,
      source_country,
      source_currency,
      received_at,
      external_opportunity_id,
      external_thread_id,
      external_contact_id,
      state_key,
      dedupe_key,
      raw_subject,
      raw_text,
      raw_html_available,
      links,
      extracted,
      classification,
      risk_flags,
      permission_policy,
      processing_status
    }

Para Workana via Gmail:

    event_type = "marketplace_opportunity"
    source_platform = "workana"
    source_channel = "gmail_notification"
    source_language = "pt-BR"
    source_country = "BR"
    source_currency = "BRL"

Para plataforma internacional futura:

    event_type = "marketplace_opportunity"
    source_platform = "international_platform_01"
    source_channel = "email_notification"
    source_language = "en"
    source_country = "US"
    source_currency = "USD"

---

### 9. Campos extraidos

A extracao deve tentar preencher:

    extracted = {
      opportunity_title,
      category,
      subcategory,
      budget_raw,
      budget_min,
      budget_max,
      currency,
      deadline_raw,
      deadline_days,
      description,
      required_skills,
      client_context,
      project_link,
      platform_project_id,
      language,
      country,
      urgency_level,
      complexity_level,
      estimated_effort,
      unclear_points
    }

Campos podem ficar vazios quando nao existirem no texto.

A ausencia de dado deve gerar unclear_points, nao invencao.

---

### 10. Classificacao de aderencia

A classificacao inicial deve produzir:

    classification = {
      fit_score,
      fit_level,
      fit_reason,
      opportunity_type,
      commercial_potential,
      delivery_risk,
      reputation_risk,
      recommended_action
    }

Escala sugerida:

    fit_score: 0 a 100

    fit_level:
    - alto
    - medio
    - baixo
    - rejeitar

Acoes recomendadas:

    recommended_action:
    - preparar_proposta
    - revisar_manualmente
    - ignorar
    - coletar_mais_contexto

---

### 11. Criterios de aderencia inicial

A aderencia deve considerar:

1. compatibilidade com MEI Robo, automacao, IA, atendimento, WhatsApp e web;
2. clareza do projeto;
3. orcamento provavel;
4. prazo;
5. risco de escopo indefinido;
6. risco de cliente problematico;
7. exigencia tecnica fora do dominio atual;
8. necessidade de integracao sensivel;
9. idioma;
10. capacidade real de entrega;
11. potencial de gerar cliente para o Projeto Ponte;
12. risco reputacional de responder sem estar pronto.

A POC deve ser conservadora quando houver risco reputacional.

---

### 12. Politica de permissoes da POC

A primeira POC deve operar em modo seguro, local e read-only.

Politica inicial:

    can_read_local_fixture = true
    can_extract_data = true
    can_classify = true
    can_generate_summary = true
    can_generate_draft = true
    can_save_local_report = true

    can_read_gmail_real = false
    can_open_platform_url = false
    can_login_platform = false
    can_click = false
    can_type = false
    can_send_message = false
    can_submit_proposal = false
    can_send_email = false
    can_write_firestore = false
    can_deploy = false

    requires_human_approval = true
    dry_run = true

Qualquer avanco deve alterar a politica de forma explicita, primeiro em documento e somente depois em codigo.

---

### 13. Deduplicacao e identificacao

A POC deve evitar processar a mesma oportunidade mais de uma vez.

Componentes possiveis do dedupe_key:

- source_platform
- source_channel
- platform_project_id
- project_link
- raw_subject_normalized
- opportunity_title_normalized
- description_hash
- received_date

Regra inicial:

- se houver link de projeto, ele sera o principal identificador;
- se nao houver link, usar hash de titulo + descricao + plataforma;
- se houver Gmail thread_id no futuro, usar como apoio;
- nunca gerar duas propostas para o mesmo dedupe_key.

---

### 14. Relatorio gerado

Para cada oportunidade processada, gerar relatorio com este formato:

    OPORTUNIDADE DETECTADA

    Plataforma:
    Canal:
    Idioma:
    Pais:
    Moeda:

    Titulo:
    Categoria:
    Orcamento:
    Prazo:
    Link:

    Resumo:
    Aderencia:
    Pontuacao:
    Motivo da pontuacao:

    Riscos:
    Pontos obscuros:
    Perguntas que talvez precisem ser respondidas:

    Acao recomendada:
    Status:

    Rascunho de proposta:

Status possiveis:

- aguardando_revisao_humana
- aprovada_para_edicao
- rejeitada
- duplicada
- baixo_fit
- risco_alto

---

### 15. Rascunho de proposta

O rascunho de proposta pode ser gerado, mas nunca enviado automaticamente.

Ele deve conter:

1. saudacao profissional;
2. demonstracao de entendimento do projeto;
3. conexao com experiencia relevante;
4. proposta de caminho inicial;
5. perguntas objetivas quando necessario;
6. fechamento com disponibilidade;
7. tom adequado a plataforma e ao idioma.

Para Workana em portugues, o tom deve ser profissional, direto, cordial, sem exagero, sem prometer o que ainda nao esta pronto e sem parecer mensagem automatica.

Para plataformas internacionais, o tom deve respeitar idioma, cultura e expectativa comercial da plataforma.

---

### 16. Idiomas

A POC deve nascer preparada para mais de um idioma.

Campos minimos:

- source_language
- output_language
- proposal_language
- translation_needed

Regra inicial:

- oportunidade em portugues: relatorio e proposta em portugues;
- oportunidade em ingles: relatorio interno pode ser portugues, proposta deve ser em ingles;
- oportunidade em espanhol: relatorio interno pode ser portugues, proposta pode ser espanhol se aprovado;
- duvidas de idioma devem ser sinalizadas, nao escondidas.

---

### 17. Humano no loop

O humano deve aprovar antes de qualquer envio real.

O robo deve fazer o trabalho preparatorio completo:

- extrair;
- resumir;
- classificar;
- apontar risco;
- sugerir abordagem;
- gerar rascunho.

O humano decide:

- ignorar;
- revisar;
- aprovar;
- editar;
- responder manualmente;
- autorizar proxima fase.

O humano no loop nao deve ser desculpa para o robo parar cedo.

O robo deve chegar ate a borda da acao externa, mas nao atravessar sem permissao.

---

### 18. Logs e auditoria

Cada processamento deve registrar:

- timestamp
- source_platform
- source_channel
- dedupe_key
- event_id
- input_fixture_name
- classification.fit_score
- classification.fit_level
- recommended_action
- risk_flags
- status
- blocked_actions

Nao registrar:

- tokens;
- cookies;
- secrets;
- dados pessoais desnecessarios;
- conversas privadas completas quando nao for necessario;
- links sensiveis em logs publicos.

---

### 19. Estrutura futura sugerida

A estrutura futura deve ser separada do runtime Base e Institucional.

Sugestao conceitual:

    services\ponte\
      __init__.py
      opportunity_event.py
      permission_policy.py
      marketplace_parser.py
      opportunity_classifier.py
      proposal_drafter.py
      audit_log.py

    tests\ponte\
      test_marketplace_fixture_parser.py
      test_opportunity_dedupe.py
      test_permission_policy.py

    tests\fixtures\ponte\
      workana_email_001.txt
      workana_email_002.txt
      international_platform_001.txt

Essa estrutura so deve ser criada depois de aprovacao documental e varredura read-only.

---

### 20. CRITERIOS PARA AVANCAR PARA CODIGO

So avancar para codigo quando:

1. este documento estiver salvo;
2. os documentos Marco Zero e Convergencia forem respeitados;
3. houver confirmacao de que a implementacao sera isolada;
4. houver definicao dos fixtures iniciais;
5. houver politica read-only clara;
6. houver confirmacao de que nao sera usado Gmail real no primeiro teste;
7. houver confirmacao de que nao sera usado navegador;
8. houver confirmacao de que nao havera envio;
9. houver plano de testes locais;
10. houver autorizacao explicita do usuario.

---

### 21. CRITERIOS PARA AVANCAR PARA GMAIL REAL

So conectar Gmail real quando:

1. parser offline estiver validado;
2. deduplicacao estiver funcionando;
3. logs estiverem seguros;
4. relatorios estiverem uteis;
5. rascunhos estiverem bons;
6. filtros de busca forem conservadores;
7. nenhuma acao de envio existir no fluxo;
8. leitura for explicitamente autorizada;
9. dados sensiveis forem minimizados;
10. houver modo de desligar imediatamente.

---

### 22. CRITERIOS PARA AVANCAR PARA NAVEGADOR

So pensar em navegador quando:

1. nucleo read-only estiver funcional;
2. politica de permissoes estiver testada;
3. logs estiverem auditaveis;
4. deduplicacao estiver madura;
5. humano no loop estiver funcionando;
6. risco reputacional estiver controlado;
7. cada plataforma tiver regras proprias;
8. houver autorizacao explicita;
9. houver plano contra clique errado;
10. houver watchdog e parada segura.

---

### 23. Diretriz final

A primeira POC do Projeto Ponte nao e sobre automatizar a Workana.

E sobre criar uma base segura de captacao inteligente de oportunidades.

A Workana sera a primeira fonte, mas a arquitetura deve nascer pronta para outras plataformas, inclusive internacionais e em outros idiomas.

A ordem correta e:

    fixture local
    evento normalizado
    extracao
    classificacao
    relatorio
    rascunho
    aprovacao humana
    somente depois integracao real

O objetivo e gerar valor sem afetar reputacao, sem tocar plataformas reais no inicio e sem interferir no restante da aplicacao MEI Robo.