# SUBSEGMENT_CREATION_METHOD_V1

## Objetivo

Definir o método oficial de construção de subsegmentos do projeto MEI ROBÔ.

O objetivo não é produzir FAQs.

O objetivo não é produzir textos de marketing.

O objetivo não é produzir respostas prontas.

O objetivo é capturar:

* conhecimento técnico;
* raciocínio profissional;
* critérios de decisão;
* riscos comuns;
* padrões de comportamento do cliente;
* padrões observados em especialistas reais.

Todo conteúdo deve ser estruturado para consumo eficiente pelo GPT-4o-mini.

---

# Princípio Fundamental

Pesquisar primeiro.

Modelar depois.

Nenhuma hipótese deve ser promovida diretamente para a KB.

Nenhuma opinião deve ser promovida diretamente para a KB.

Nenhuma conclusão isolada deve ser promovida diretamente para a KB.

Todo padrão deve surgir de observações repetidas em fontes reais.

---

# Etapa 1 — Escolha do Subsegmento

Exemplos:

* Loja de Óculos
* Clínica Odontológica
* Oficina Mecânica
* Academia
* Clínica Veterinária
* Imobiliária

O subsegmento deve representar uma atividade específica.

Evitar categorias excessivamente amplas.

---

# Etapa 2 — Pesquisa

Fontes prioritárias:

* treinamentos profissionais;
* cursos de formação;
* cursos de vendedores especializados;
* fabricantes;
* entidades do setor;
* especialistas reconhecidos;
* materiais de onboarding;
* conteúdos técnicos.

Evitar utilizar como fonte principal:

* propaganda;
* páginas promocionais;
* landing pages;
* textos genéricos de marketing.

Buscar principalmente:

* como especialistas trabalham;
* como especialistas tomam decisões;
* como especialistas são treinados;
* erros comuns de iniciantes;
* critérios utilizados por profissionais experientes.

---

# Etapa 3 — Extração

Separar descobertas em grupos.

## Conhecimento Técnico

Exemplos:

* produtos;
* serviços;
* processos;
* terminologias;
* limitações;
* aplicações.

## Processo Decisório

Exemplos:

* como especialistas escolhem;
* como especialistas recomendam;
* quais critérios utilizam.

## Riscos

Exemplos:

* erros comuns;
* decisões inadequadas;
* expectativas incorretas.

## Comportamentos do Cliente

Exemplos:

* objeções;
* inseguranças;
* comparações;
* dúvidas recorrentes.

---

# Etapa 4 — Validação

Classificação oficial.

1 fonte:
Curiosidade.

2 fontes:
Hipótese.

3 fontes:
Candidato a padrão.

4 ou mais fontes independentes:
Padrão validado.

Somente padrões validados devem ser considerados para a KB.

---

# Etapa 5 — Modelagem GPT-4o-mini

Transformar descobertas em estruturas determinísticas.

Preferir:

* detected_state
* next_objective
* allowed_actions
* avoid_actions

Evitar:

* abstrações;
* subjetividade;
* conceitos vagos;
* recomendações genéricas.

---

# Etapa 6 — Construção das Famílias

Todo subsegmento deve buscar preencher as seguintes famílias.

## Technical Expertise

Conhecimento técnico da atividade.

## Behavioral Clusters

Comportamentos observáveis do cliente.

## Information Gap Patterns

Informações que especialistas precisam obter antes de orientar.

## Expert Reframing Patterns

Como especialistas reformulam perguntas.

## Risk Alert Patterns

Situações que exigem atenção.

## Trust Building Patterns

Ações observadas que aumentam segurança do cliente.

## Specialist vs Beginner Patterns

Diferenças observadas entre profissionais experientes e iniciantes.

---

# Etapa 7 — Consolidação

Produzir:

SUBSEGMENT_CANONICAL_MODEL

Este documento representa a versão consolidada do subsegmento.

Somente após essa consolidação o conteúdo poderá ser preparado para Firestore.

---

# Integração Futura com o Projeto

O conteúdo do subsegmento deve apoiar:

* a IA soberana;
* o entendimento do contexto;
* a personalização por segmento;
* a geração de respostas mais próximas do comportamento de especialistas reais.

O conteúdo não substitui a IA.

A IA responde.

A KB fornece conhecimento.

O código organiza, protege e entrega.

---

# Regra Final

A qualidade do subsegmento será determinada pela qualidade da pesquisa realizada.

Quanto melhor a pesquisa sobre especialistas reais, melhor será a qualidade das respostas produzidas pelo MEI ROBÔ.
