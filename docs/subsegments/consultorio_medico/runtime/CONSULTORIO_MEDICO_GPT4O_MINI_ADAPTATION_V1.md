# CONSULTORIO_MEDICO_GPT4O_MINI_ADAPTATION_V1

## Objetivo

Adaptar o conhecimento do Consultório Médico para o padrão de interpretação do GPT-4o-mini utilizado pelo MEI Robô.

Este documento não substitui:

* pesquisa;
* modelo canônico;
* runtime.

Este documento define como o conhecimento deve ser transformado para aumentar previsibilidade de comportamento.

---

# 1. Princípio Fundamental

O GPT-4o-mini responde melhor a:

* ações;
* verificações;
* situações;
* sequências;
* próximos passos.

O GPT-4o-mini responde pior a:

* abstrações;
* conceitos amplos;
* teorias;
* explicações excessivamente conceituais.

---

# 2. Regra de Construção

Transformar conceitos em ações observáveis.

---

Exemplo:

Conceito:

Preservar continuidade.

---

Forma adaptada:

Explicar o próximo passo.

Orientar quando retornar.

Orientar quem procurar.

Orientar como continuar.

---

Exemplo:

Conceito:

Reduzir ansiedade.

---

Forma adaptada:

Explicar claramente:

* o que acontece agora;
* o que acontece depois;
* o que o paciente precisa fazer.

---

Exemplo:

Conceito:

Identificar necessidade real.

---

Forma adaptada:

Descobrir se a pessoa deseja:

* consulta;
* retorno;
* encaminhamento;
* teleconsulta;
* informação operacional.

---

# 3. Linguagem Positiva

Preferir instruções afirmativas.

---

Exemplo inadequado:

Não responder de forma genérica.

---

Forma adaptada:

Responder usando:

* situação observada;
* ação recomendada;
* próximo passo.

---

Exemplo inadequado:

Não usar linguagem acadêmica.

---

Forma adaptada:

Usar linguagem simples.

Usar linguagem conversacional.

Usar exemplos observáveis.

---

Exemplo inadequado:

Não expandir explicações.

---

Forma adaptada:

Explicar apenas o necessário para orientar a próxima ação.

---

# 4. Estrutura Preferencial de Resposta

Situação observada
↓
Orientação
↓
Próximo passo

---

Exemplo:

Paciente deseja retorno.

↓

Explicar como funciona o retorno.

↓

Orientar o próximo passo para agendamento ou confirmação.

---

# 5. Estrutura Preferencial de Raciocínio

Mensagem recebida
↓
Objetivo
↓
Acesso
↓
Informação faltante
↓
Validação
↓
Ação
↓
Próximo passo

---

# 6. Informações que Devem Receber Alta Prioridade

* objetivo do paciente;
* tipo de consulta;
* retorno;
* encaminhamento;
* convênio;
* documentação;
* próximo passo.

---

# 7. Informações que Devem Gerar Perguntas

Quando faltarem informações importantes:

Perguntar diretamente.

Perguntar de forma objetiva.

Perguntar uma coisa de cada vez quando possível.

---

Exemplos:

"É primeira consulta ou retorno?"

"Você utilizará convênio ou atendimento particular?"

"Existe encaminhamento?"

---

# 8. Respostas Mais Compatíveis com o Modelo

Explicar:

* o que fazer;
* quando fazer;
* como fazer;
* quem procurar;
* qual é o próximo passo.

---

# 9. Construção de Confiança

Demonstrar método.

Sequência recomendada:

Entender
↓
Verificar
↓
Organizar
↓
Orientar
↓
Confirmar

---

# 10. Compatibilidade com Snapshot

Priorizar:

* situações;
* intenções;
* ações;
* riscos;
* próximos passos.

Reduzir:

* teoria;
* narrativa extensa;
* explicações abstratas.

---

# 11. Compatibilidade com Micro Scene Conversational

Considerar que alguns conteúdos podem ser utilizados diretamente em fallback.

Portanto produzir textos:

* humanos;
* conversacionais;
* acolhedores;
* objetivos;
* orientados à ação;
* compatíveis com WhatsApp.

---

# 12. Regra de Ouro

Sempre transformar:

conceito
↓
ação

explicação
↓
orientação

dúvida
↓
próximo passo

informação
↓
condução

---

# 13. Definição Final

O GPT-4o-mini produz melhores resultados quando recebe:

situações claras
↓
ações claras
↓
próximos passos claros

Todo artefato futuro do Consultório Médico deve respeitar esse padrão.
