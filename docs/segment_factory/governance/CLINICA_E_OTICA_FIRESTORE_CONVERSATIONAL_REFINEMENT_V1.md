# CLINICA_E_OTICA_FIRESTORE_CONVERSATIONAL_REFINEMENT_V1

## Objetivo

Definir ajustes de Firestore para aumentar a taxa de acerto do GPT-4o-mini e melhorar a qualidade dos fallbacks sem alterar a arquitetura cognitiva da fábrica.

## Princípios aprovados

1. Preservar Matrix, Canonical Model e Runtime.
2. Reforçar apenas a camada conversacional do Firestore.
3. Priorizar linguagem real de WhatsApp.
4. Preferir frases curtas e concretas.
5. Evitar abstrações quando houver equivalente conversacional.
6. Microcenas podem ser mais longas que os demais campos.
7. Microcenas devem ser narrativas, não diagramas.
8. Todo conhecimento que altera resposta deve possuir tradução conversacional.

---

## Regra para common_intents

Ruim:
- verificar_autorizacao

Melhor:
- perguntar_se_precisa_autorizacao
- verificar_se_autorizacao_foi_aprovada
- perguntar_se_pode_agendar_sem_autorizacao

---

## Regra para real_customer_situations

Trocar categorias genéricas por situações reais.

Exemplos:

- aceita Unimed
- meu plano cobre esse exame
- preciso de autorização
- a autorização ainda não saiu
- posso agendar enquanto aguardo
- esqueci e tomei café
- perdi as orientações
- posso beber água
- já saiu meu resultado
- perdi minha senha
- meu resultado não apareceu
- fui encaminhado pelo SUS
- estou aguardando regulação

---

## Regra para micro_scene

Formato recomendado:

Narrativa curta, objetiva e natural.

Exemplo Clínica:

Quando o paciente entra em contato para realizar um exame, pedir orçamento, verificar convênio ou entender o preparo necessário, o robô identifica o exame solicitado ou pede uma foto do pedido médico. Depois entende se o atendimento será particular, convênio, SUS, ordem de chegada ou outro fluxo da clínica. Com a trilha definida, organiza documentos, autorização quando necessária e preparo do exame. Quando tudo estiver pronto, conduz para agendamento, comparecimento ou acesso ao resultado. Se houver pendências ou situações fora das regras cadastradas, organiza o contexto e encaminha para a equipe humana.

---

## Regra para micro_scene_conversational

Formato recomendado:

Narrativa operacional mais rica, utilizável como fallback.

Exemplo Clínica:

Quando o paciente chama no WhatsApp perguntando preço, convênio, preparo, resultado ou agendamento, o MEI Robô identifica primeiro qual exame foi solicitado e utiliza as informações cadastradas pela clínica para orientar o próximo passo. Ele pode ajudar a organizar pedido médico, documentos, autorização, preparo, unidade e forma de atendimento. Também pode orientar acesso ao resultado, remarcações e dúvidas operacionais quando essas informações estiverem cadastradas. Se surgir uma situação que dependa de avaliação humana, interpretação clínica ou validação não disponível no sistema, o robô prepara um resumo claro e encaminha para a equipe continuar o atendimento.

---

## Regra para futura evolução da Ótica

Traduzir conhecimento abstrato para linguagem real de cliente.

Exemplos:

Em vez de:
- customer_psychology

Usar situações como:
- cliente tem medo de multifocal
- cliente acha a lente cara
- cliente quer usar receita antiga
- cliente usa computador o dia inteiro

Em vez de:
- decision_factors

Usar situações como:
- cliente compara duas lentes
- cliente pergunta por que uma lente custa mais
- cliente quer entender a diferença entre as opções

---

## Novo princípio da fábrica

PRINCIPLE_KNOWLEDGE_TRANSLATION

Todo conhecimento relevante deve existir em duas formas:

1. Forma cognitiva (Matrix, Canonical, Runtime).
2. Forma conversacional (Firestore).

A camada conversacional deve ser escrita para que o GPT-4o-mini consiga utilizá-la sem precisar reconstruir o raciocínio especialista.
