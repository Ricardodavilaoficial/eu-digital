# FRONT DEMO / SIMULATION REPLY — DECISÃO ARQUITETURAL V1

Projeto: MEI Robô  
Área: Conversational Front  
Arquivo principal atual: services/conversational_front.py

## 1. Decisão central

A funcionalidade atual será tratada como o primeiro tijolo da futura Camada de Demonstração Conversacional do MEI Robô.

A implementação imediata, porém, ficará restrita a:

simulation_reply

Ou seja: quando o lead pergunta como o MEI Robô responderia um cliente, paciente, usuário, morador, aluno ou outro destinatário final que disse determinada mensagem.

## 2. Contrato conceitual

simulation é intenção.

DIRECT é superfície de resposta.

Portanto:

question_type = simulation  
response_mode = DIRECT  
demo_kind interno = simulation_reply

Não será criado response_mode=SIMULATION.

A criação de response_mode=SIMULATION misturaria intenção com forma de resposta e aumentaria risco de regressão sobre SCENE, DIRECT, broad e punctual.

## 3. Preservação obrigatória

O modo broad/SCENE fica congelado.

A micro_scene_conversational continua sendo usada integralmente quando o lead faz pergunta ampla sobre como o MEI Robô ajuda.

A funcionalidade simulation_reply não deve acionar microcena comercial longa.

## 4. Objetivo do simulation_reply

Quando o lead pergunta:

"Como o MEI Robô responderia um cliente/paciente que diz X?"

A resposta final deve ser a própria mensagem que o destinatário simulado leria.

Ela deve ser direta, natural, humanizada, comercialmente útil e compatível com o segmento.

Ela não deve ser explicação em terceira pessoa.

## 5. Separação de papéis

A arquitetura deve distinguir:

- lead / dono do negócio;
- contexto do negócio;
- destinatário simulado;
- sujeito citado na situação;
- autor da mensagem simulada;
- destinatário final da resposta;
- mensagem simulada;
- resposta final.

Exemplo:

Entrada:

"Sou José, atendo num consultório de otorrinolaringologia. Como o MEI Robô responderia um paciente que diz: meu filho de 10 anos está com dor de garganta, você atende?"

Papéis:

- José = lead / dono do negócio;
- consultório de otorrinolaringologia = contexto do negócio;
- responsável pela criança = destinatário simulado;
- filho de 10 anos = sujeito citado;
- mensagem simulada = "meu filho de 10 anos está com dor de garganta, você atende?";
- resposta final = mensagem dirigida ao responsável, sem chamar o destinatário de José.

## 6. Papel do código e da IA

O código deve organizar contexto, papéis, limites, modo de resposta e proteção contra regressões.

A IA continua soberana para entender a intenção, redigir com naturalidade, acolher a situação e escolher uma próxima pergunta útil.

O código não deve substituir a inteligência conversacional por hardcodes frágeis.

O GPT-4o-mini usado na aplicação é leve. Portanto, a solução deve reduzir ambiguidade, usar orientação determinística e positivista, e evitar prompt longo, abstrato ou contraditório.

## 7. Evitar hardcode de saúde

A solução não deve ser presa a paciente, saúde ou otorrino.

Saúde entra por contexto, KB, contrato e regras de segurança do domínio.

A mesma arquitetura deve permitir futuramente simulações em lancheria, ótica, escritório, escola, assistência técnica, política, serviços locais e outros segmentos.

## 8. Fora do escopo imediato

Não implementar agora:

- operational_demo;
- workflow_demo;
- capability_test;
- envio real de e-mail;
- execução real de ferramenta;
- novo services/front_demo.py;
- alteração em Firestore;
- alteração em wa_bot.py, salvo necessidade absoluta comprovada.

## 9. Futuro front_demo.py

Um módulo futuro services/front_demo.py poderá existir quando houver pelo menos um segundo tipo real de demonstração.

Possíveis tipos futuros:

- simulation_reply;
- operational_demo;
- workflow_demo;
- capability_test.

Por enquanto, a estabilização fica dentro de services/conversational_front.py.

## 10. Critérios de sucesso

Mensagem broad/SCENE deve permanecer funcionalmente preservada:

- question_type=broad;
- response_mode=SCENE;
- uso integral da micro_scene_conversational;
- sem regressão da resposta comercial atual.

Mensagem simulation_reply deve produzir:

- question_type=simulation;
- response_mode=DIRECT;
- resposta direta ao destinatário simulado;
- sem "O MEI Robô responderia...";
- sem microcena longa;
- sem usar nome do lead como vocativo do destinatário;
- acolhimento adequado;
- próxima pergunta útil para conversão ou avanço do atendimento;
- limites do segmento preservados.

## 11. Critérios de rollback

Reverter a alteração se ocorrer:

- broad/SCENE perder a micro_scene_conversational;
- simulation virar SCENE;
- simulation acionar microcena longa;
- nome do lead virar vocativo do destinatário;
- resposta voltar para terceira pessoa;
- resposta prometer execução real sem autorização/ferramenta;
- saúde contaminar outros segmentos;
- pós-processamento deformar a resposta simulada.