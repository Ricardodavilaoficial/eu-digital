# PROJETO PONTE / MEI ROBÔ WEB

## CONVERGÊNCIA DAS 3 VERTENTES: BASE, INSTITUCIONAL E WEB — V1

### 1. Objetivo do documento

Este documento explica como as três vertentes do ecossistema MEI Robô devem se relacionar:

1. **MEI Robô Base**
2. **MEI Robô Institucional**
3. **MEI Robô WEB / Projeto Ponte**

A principal diretriz é que, embora cada vertente tenha canais, fontes e objetivos diferentes, todas devem entregar uma percepção de qualidade equivalente para o usuário.

Aos olhos de quem conversa com o robô, ele deve parecer o mesmo MEI Robô inteligente, útil, contextual e confiável.

---

### 2. Princípio de qualidade única

As três vertentes devem entregar:

```text
resposta útil
↓
contexto correto
↓
tom adequado
↓
ação segura
↓
continuidade de conversa
↓
clareza sobre o próximo passo
```

A diferença entre as vertentes deve estar na arquitetura interna, no canal e na fonte de informação, não na qualidade percebida.

---

### 3. Visão geral das vertentes

| Vertente      | Quem atende                                     | Canal principal                              | Fonte principal                                                    | Papel                                             |
| ------------- | ----------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------- |
| Base          | Cliente final do profissional/empresa           | WhatsApp Business API/YCloud                 | `profissionais/{uid}`, contatos, acervo, agenda, serviços          | Atendimento comercial e operacional               |
| Institucional | Lead, usuário ou cliente da plataforma MEI Robô | WhatsApp API ou canais institucionais        | `platform_kb`, segmentos, subsegmentos                             | Venda, suporte e configuração da plataforma       |
| WEB/Ponte     | Cliente final em ambiente sem API               | Navegador, WhatsApp Web, CRM, Workana, Gmail | Conta do profissional, tela, snapshots, acervo, contexto permitido | Atendimento comercial e operacional via navegador |

---

### 4. MEI Robô Base

O MEI Robô Base atende o cliente final do profissional ou empresa cadastrada.

Fluxo conceitual:

```text
cliente chama o WhatsApp do profissional
↓
MEI Robô recebe via WhatsApp Business API/YCloud
↓
identifica profissional/uid
↓
consulta conta, serviços, contatos, agenda, acervo e regras
↓
responde como assistente daquele negócio
```

Características:

* canal principal: WhatsApp Business API/YCloud;
* fonte principal: `profissionais/{uid}`;
* dados complementares: contatos, produtos, serviços, agenda, Storage, acervo;
* papel: atendimento comercial e operacional do cliente cadastrado;
* risco principal: responder sem contexto correto, perder persistência ou executar ação real sem confirmação/política.

---

### 5. MEI Robô Institucional

O MEI Robô Institucional atende leads, usuários e clientes da própria plataforma MEI Robô.

Fluxo conceitual:

```text
lead pergunta como o MEI Robô funciona
↓
Institucional identifica intenção comercial, suporte ou voz
↓
consulta platform_kb, segmentos e subsegmentos
↓
responde vendendo, explicando, orientando ou configurando
```

Características:

* canal principal atual: WhatsApp Business API/YCloud;
* fonte principal: `platform_kb/sales`;
* fontes segmentadas: `kb_archetypes_v1`, `kb_segments_v1`, `kb_subsegments_v1`;
* papel: vender, explicar, suportar e configurar o próprio MEI Robô;
* risco principal: misturar venda institucional com operação real do cliente final.

---

### 6. MEI Robô WEB / Projeto Ponte

O MEI Robô WEB leva a capacidade operacional do MEI Robô para ambientes sem API oficial.

Fluxo conceitual:

```text
cliente usa WhatsApp Web, CRM, Workana ou outro sistema
↓
MEI Robô WEB observa a tela
↓
normaliza o evento
↓
identifica contato, thread e contexto
↓
consulta fontes permitidas
↓
gera resposta ou plano
↓
executa no navegador somente se permitido
```

Características:

* canal: navegador;
* fontes: conta do profissional, contatos, acervo, Storage, contexto da tela, CRM, snapshots, inteligência setorial permitida;
* papel: assistente comercial e operacional em sistemas web;
* risco principal: clicar/enviar/gravar em ambiente errado, perder sessão, duplicar resposta, usar credenciais sem segurança ou acionar humano cedo demais.

---

### 7. Base e WEB como irmãos operacionais

O MEI Robô Base e o MEI Robô WEB têm raciocínio operacional semelhante.

Ambos devem ajudar o cliente cadastrado a atender seus próprios clientes.

Ambos podem usar:

* dados do profissional;
* produtos e serviços;
* contatos;
* histórico;
* acervo;
* documentos;
* imagens;
* regras de atendimento;
* agenda;
* materiais do Storage;
* inteligência setorial auxiliar.

A diferença principal está no canal.

| Aspecto                        | Base                 | WEB                                                            |
| ------------------------------ | -------------------- | -------------------------------------------------------------- |
| Captura da mensagem            | webhook/API          | observação de tela/navegador                                   |
| Envio da resposta              | API/YCloud           | digitação/clique/navegador                                     |
| Identidade de conversa         | uid + telefone/waKey | channel + external_contact_id + external_thread_id + state_key |
| Risco de tela                  | não                  | sim                                                            |
| Risco de sessão                | baixo/médio          | alto                                                           |
| Acesso a sistemas externos     | limitado             | amplo, conforme login e permissão                              |
| Necessidade de watchdog visual | não                  | sim                                                            |

Assim, o WEB deve herdar o padrão operacional do Base, mas não deve herdar cegamente os handlers do Base.

---

### 8. Institucional como fonte de inteligência setorial futura

O Institucional usa estruturas segmentadas para vender e explicar o MEI Robô por área de atuação.

Essas estruturas podem futuramente ajudar Base e WEB.

Exemplo:

```text
subsegmento: escritório de advocacia
↓
dores típicas
serviços comuns
linguagem adequada
cuidados de atendimento
perguntas frequentes
restrições operacionais
processos habituais
↓
Base e WEB usam como apoio para responder melhor
```

Essa camada pode ser chamada de:

```text
Inteligência Setorial Compartilhada
```

Ela não substitui os dados do cliente. Ela complementa.

---

### 9. Prioridade das fontes de informação

Quando Base ou WEB forem responder, a prioridade deve ser:

```text
1. dados específicos do cliente/profissional
2. regras configuradas pelo cliente
3. acervo e documentos do cliente
4. histórico e contexto do contato
5. dados operacionais de agenda/serviços
6. inteligência setorial compartilhada
7. conhecimento geral permitido
```

A inteligência setorial é uma camada de enriquecimento, não a fonte soberana quando há dado específico do cliente.

---

### 10. Caminhos diferentes, qualidade equivalente

As três vertentes podem ter códigos diferentes.

O objetivo não é chamar a mesma função a qualquer custo.

O objetivo é compartilhar padrões:

```text
mesmo padrão de contexto
mesmo padrão de resposta
mesmo padrão de segurança
mesmo padrão de continuidade
mesmo padrão de telemetria
mesmo padrão de qualidade
```

Arquiteturas conceituais:

```text
WhatsApp API
↓
adapter Base
↓
runtime operacional
```

```text
WhatsApp API / lead
↓
adapter Institucional
↓
runtime institucional
```

```text
Navegador / tela
↓
adapter Ponte
↓
núcleo Ponte
↓
executor WEB
```

---

### 11. Contrato comum de qualidade

Toda vertente deve responder com base em cinco pilares.

#### 11.1 Contexto

A resposta precisa saber de onde está falando:

* é lead da plataforma?
* é cliente final do profissional?
* é usuário em canal web?
* é suporte?
* é configuração?
* é operação?

#### 11.2 Fonte de verdade

A resposta deve saber qual fonte consultar:

* Base: conta do profissional, acervo, contatos, agenda;
* Institucional: platform_kb, segmentos, subsegmentos;
* WEB: conta do profissional, evento normalizado, snapshot injetado, contexto permitido, fonte WEB observada.

#### 11.3 Política

Antes de agir, a vertente precisa saber o que pode fazer:

* pode só responder?
* pode sugerir?
* pode enviar?
* pode gravar?
* pode agendar?
* pode mandar e-mail?
* precisa aprovação?

#### 11.4 Continuidade

O robô não deve tratar cada mensagem como conversa nova.

Cada vertente precisa preservar continuidade conforme sua realidade:

* Base: cliente/telefone/uid;
* Institucional: lead/conversa/turnos comerciais;
* WEB: `channel`, `external_contact_id`, `external_thread_id`, `state_key`.

#### 11.5 Rastreabilidade

Cada resposta precisa deixar rastro suficiente para auditoria:

* qual contexto usou;
* qual fonte consultou;
* qual política permitiu;
* qual ação foi sugerida;
* qual ação foi bloqueada;
* se houve risco;
* se houve necessidade de supervisor.

---

### 12. Matriz de equivalência de qualidade

| Critério                  | Base                         | Institucional              | WEB                                |
| ------------------------- | ---------------------------- | -------------------------- | ---------------------------------- |
| Entende quem está falando | cliente final                | lead/usuário da plataforma | contato em tela/canal              |
| Usa fonte correta         | conta/acervo do profissional | platform_kb/segmentos      | conta/contexto WEB/snapshot/acervo |
| Preserva conversa         | por uid/telefone             | por lead/turno             | por state_key/thread               |
| Responde com tom adequado | persona do profissional      | tom comercial MEI Robô     | persona/contexto do cliente        |
| Executa ações             | sim, conforme fluxo          | comercial/configuração     | só com política                    |
| Evita ação perigosa       | necessário                   | necessário                 | crítico                            |
| Tem logs                  | necessário                   | necessário                 | obrigatório                        |
| Handoff humano            | exceção                      | exceção                    | última instância estrita           |

---

### 13. Modelo mental comum

Mesmo que os códigos sejam diferentes, as três vertentes devem se aproximar de um modelo mental comum:

```text
mensagem/evento
↓
identidade da conversa
↓
contexto permitido
↓
fonte de verdade
↓
intenção
↓
informações faltantes
↓
risco
↓
resposta
↓
ação sugerida ou executada
↓
telemetria
```

Esse modelo evita que cada vertente vire um produto completamente diferente.

---

### 14. O erro arquitetural a evitar no WEB

O erro seria tentar fazer o MEI Robô WEB nascer assim:

```text
WhatsApp Web
↓
texto extraído
↓
customer_final.generate_reply
↓
digita resposta
```

Esse caminho parece rápido, mas é frágil porque `customer_final.generate_reply` mistura:

* resposta;
* estado;
* memória;
* acervo;
* Firestore;
* OpenAI;
* orçamento;
* agenda;
* e-mail.

O caminho correto é:

```text
WhatsApp Web / CRM / Workana
↓
observador
↓
evento normalizado
↓
núcleo Ponte read-only/controlado
↓
resposta/plano
↓
executor com política
↓
logs/auditoria
```

---

### 15. Primeira meta prática do WEB

A primeira meta prática não é operação 100% autônoma.

A primeira meta é:

```text
dado um evento normalizado de uma conversa WEB,
o núcleo Ponte deve gerar uma resposta segura,
com ações sugeridas e bloqueadas,
sem executar nenhum efeito real.
```

Exemplo de entrada:

```python
{
    "uid_owner": "cliente_teste",
    "channel": "whatsapp_web",
    "external_contact_id": "+555199999999",
    "external_thread_id": "+555199999999",
    "state_key": "hash_estavel",
    "user_text": "Oi, queria saber como funciona o atendimento",
    "persona": {
        "tone": "educado, direto e profissional"
    },
    "catalog_snapshot": {
        "displayName": "Clínica Exemplo",
        "produtosEServicos": [
            {"nome": "Consulta inicial", "preco": "150", "duracaoMin": "40"}
        ]
    },
    "context_snapshot": {},
    "sector_snapshot": {
        "subsegment": "clinica_exames_medicos",
        "common_questions": [],
        "operational_cautions": []
    },
    "policy": {
        "dry_run": True,
        "allow_firestore_read": False,
        "allow_firestore_write": False,
        "allow_llm": False,
        "allow_external_send": False
    }
}
```

Exemplo de saída:

```python
{
    "ok": True,
    "reply_text": "Olá! A consulta inicial dura em média 40 minutos e custa R$ 150. Posso te explicar os próximos passos ou verificar opções de horário.",
    "suggested_actions": [
        {
            "type": "ASK_FOLLOWUP",
            "reason": "cliente demonstrou interesse, mas ainda não pediu agendamento"
        }
    ],
    "blocked_actions": [],
    "risk_flags": [],
    "confidence": 0.86,
    "handoff_recommendation": False
}
```

---

### 16. Papel do humano no piloto

No piloto Workana, o humano será supervisor, não atendente principal.

O robô deve tentar resolver.

O humano observa exceções.

O objetivo do piloto é validar:

* leitura correta da tela;
* resposta adequada;
* ausência de duplicidade;
* manutenção de contexto;
* bloqueio de ações perigosas;
* recuperação de queda;
* qualidade de logs;
* baixa necessidade de handoff.

O handoff deve ser tratado como evento de aprendizado e melhoria do sistema, não como comportamento normal.

---

### 17. Síntese final

As três vertentes devem parecer o mesmo MEI Robô em qualidade, mas não precisam compartilhar o mesmo caminho interno.

A convergência deve acontecer por:

```text
contratos
políticas
contexto
telemetria
segurança
tom
continuidade
inteligência setorial
```

O MEI Robô Base continuará operando pelo caminho API/YCloud.

O MEI Robô Institucional continuará operando pelo caminho platform_kb/segmentos.

O MEI Robô WEB nascerá com caminho próprio, usando o aprendizado dos outros dois, mas com núcleo seguro, read-only por padrão, preparado para navegador, robustez e operação supervisionada.

A estrutura segmentada do Institucional poderá futuramente enriquecer Base e WEB, desde que respeite a prioridade dos dados específicos do cliente e seja acessada por contrato claro.
