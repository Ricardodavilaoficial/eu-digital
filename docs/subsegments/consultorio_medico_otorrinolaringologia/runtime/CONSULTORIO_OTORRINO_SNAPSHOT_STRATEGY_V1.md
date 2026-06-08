# CONSULTORIO_OTORRINO_SNAPSHOT_STRATEGY_V1

## Objetivo

Garantir que o Snapshot preserve os elementos que realmente influenciam o comportamento do especialista após a compactação realizada pela aplicação.

O objetivo do Snapshot não é reproduzir todo o Firestore.

O objetivo é preservar contexto suficiente para que o GPT-4o-mini continue:

* acolhendo;
* organizando;
* gerando confiança;
* conduzindo para consulta;
* preservando continuidade.

---

# Princípio Fundamental

O especialista de Otorrinolaringologia deve ser lembrado por situações reais, não por terminologia médica.

Priorizar:

* situações percebidas;
* impactos percebidos;
* preocupações percebidas;
* próximos passos.

---

# O Que Deve Sobreviver

## Famílias Principais

* ouvido
* nariz
* garganta
* voz
* sono
* equilíbrio

---

## Situações Frequentes

Exemplos:

* meu ouvido está tampado
* estou ouvindo um chiado
* acho que estou ouvindo menos
* meu nariz vive entupido
* não consigo respirar pelo nariz
* minha garganta inflama toda hora
* estou rouco há semanas
* ronco muito
* acordo cansado
* estou tendo crises de tontura

---

## Situações Pediátricas

Exemplos:

* meu filho vive com dor de ouvido
* acho que meu filho não está ouvindo bem
* a escola comentou que meu filho parece não ouvir bem
* meu filho respira pela boca
* meu filho ronca muito

---

## Informações Mais Importantes

Preservar principalmente:

* duração
* recorrência
* impacto
* idade
* relação com o paciente
* tentativas anteriores

---

## Impactos Relevantes

O Snapshot deve lembrar que o especialista presta atenção especial quando existe impacto em:

* audição
* respiração
* sono
* voz
* rotina diária

---

## Estados Comportamentais

Preservar:

* sempre fui assim
* vou esperar mais um pouco
* acho que não preciso consultar
* isso está me preocupando
* estou preocupado com meu filho

---

## Conversão

O Snapshot deve lembrar que a consulta é o principal mecanismo de avanço.

O especialista procura conduzir naturalmente para consulta quando identifica:

* persistência
* recorrência
* impacto funcional
* preocupação relevante

---

# O Que Pode Ser Perdido

O Snapshot não precisa preservar:

* explicações médicas extensas
* terminologia técnica
* descrições acadêmicas
* protocolos especializados
* detalhes clínicos aprofundados

Esses conteúdos pertencem ao Storage.

---

# O Que Nunca Deve Ser Perdido

Mesmo em compressão agressiva, preservar:

* acolhimento
* organização
* confiança
* consulta
* continuidade

Esses elementos representam a essência do especialista.

---

# Teste de Qualidade

Se o Snapshot for reduzido drasticamente, o GPT-4o-mini ainda deve ser capaz de compreender:

Paciente relata situação
↓
Especialista acolhe
↓
Especialista organiza
↓
Especialista entende impacto
↓
Especialista reduz insegurança
↓
Especialista conduz para consulta
↓
Especialista preserva continuidade

Se essa sequência sobreviver, o Snapshot continua funcional.

---

# Regra de Ouro

Frases reais de pacientes sobrevivem melhor à compactação do que abstrações.

Por isso devem ser priorizadas em toda a cadeia:

Firestore
↓
Snapshot
↓
GPT-4o-mini
↓
WhatsApp
