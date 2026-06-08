# CONSULTORIO_OTORRINO_FACTORY_INCREMENTS_V1

## Objetivo

Registrar descobertas reutilizáveis identificadas durante a construção do subsegmento de Otorrinolaringologia.

O objetivo não é registrar conhecimento médico.

O objetivo é registrar mecanismos reutilizáveis para futuras especialidades da Família Saúde.

---

# Incremento 01

## O paciente chega pelo sintoma percebido

A pesquisa mostrou repetidamente que pacientes raramente iniciam a conversa utilizando nomes de doenças.

Mais comum:

* meu ouvido está tampado
* não consigo respirar pelo nariz
* ronco muito
* estou ouvindo um chiado

Menos comum:

* nomes técnicos
* diagnósticos formais
* terminologia médica

---

## Aplicação futura

Modelar especialidades utilizando linguagem do paciente.

Não utilizar doenças como principal estrutura de entrada.

---

# Incremento 02

## O paciente descreve consequências

Pacientes frequentemente descrevem:

* não consigo ouvir bem
* acordo cansado
* minha voz está me atrapalhando
* não consigo respirar direito

Mais do que:

* diagnósticos;
* classificações clínicas.

---

## Aplicação futura

Modelar por impacto percebido.

Não apenas por sintomas.

---

# Incremento 03

## Conversão nasce da combinação

A pesquisa apontou forte recorrência de:

* persistência;
* recorrência;
* impacto funcional.

Quando combinados, aumentam a necessidade percebida de avaliação.

---

## Aplicação futura

Utilizar esses sinais para apoiar condução para consulta.

---

# Incremento 04

## O especialista organiza antes de explicar

Os melhores consultórios observados não começam explicando doenças.

Primeiro procuram entender:

* duração;
* frequência;
* impacto;
* contexto.

Depois orientam.

---

## Aplicação futura

Priorizar organização da situação antes de fornecer explicações.

---

# Incremento 05

## O paciente procura confiança antes de decidir

Muitas conversas começam com:

* isso é normal?
* devo me preocupar?
* preciso consultar?

O paciente frequentemente procura segurança para decidir.

---

## Aplicação futura

Modelar construção de confiança como parte central da conversão.

---

# Incremento 06

## Crianças criam uma trilha própria

Casos pediátricos apresentam padrões recorrentes:

* preocupação dos pais;
* observação da escola;
* audição;
* sono;
* respiração;
* infecções recorrentes.

---

## Aplicação futura

Especialidades médicas devem considerar explicitamente situações pediátricas quando houver recorrência relevante.

---

# Incremento 07

## Frases reais sobrevivem melhor ao Snapshot

Exemplo forte:

"meu nariz vive entupido"

sobrevive melhor do que:

"obstrução nasal recorrente"

durante processos de compactação.

---

## Aplicação futura

Priorizar frases reais de pacientes em:

* Firestore;
* Runtime;
* Snapshot.

---

# Incremento 08

## O Firestore deve ser otimizado para Snapshot

Durante a construção ficou evidente que o consumidor final do Firestore não é o GPT.

O consumidor imediato é o Snapshot.

Portanto o conteúdo deve permanecer compreensível mesmo após perda parcial de contexto.

---

## Aplicação futura

Testar sempre:

"esta informação continua útil se perder metade do contexto?"

---

# Incremento 09

## Família Saúde orientada por avanço

A pesquisa reforçou um padrão recorrente:

Paciente
↓
Acolhimento
↓
Compreensão
↓
Organização
↓
Confiança
↓
Consulta
↓
Continuidade

---

## Aplicação futura

Utilizar essa sequência como referência para futuras especialidades médicas.

---

# Incremento 10

## Especialidades não substituem o Consultório Médico Base

Otorrinolaringologia confirmou que:

* agendamento;
* continuidade;
* convênios;
* confiança;
* acompanhamento;
* retorno;

continuam pertencendo ao Consultório Médico Base.

A especialidade acrescenta diferenças.

Não substitui a estrutura principal.

---

# Conclusão

A construção da Otorrinolaringologia validou a estratégia de:

reutilizar primeiro
↓
especializar depois

demonstrando redução significativa de esforço sem perda de qualidade.

A maior descoberta foi que situações reais, impactos percebidos e construção de confiança geram melhor desempenho do que modelagens centradas em doenças ou terminologia médica.
