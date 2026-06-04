# SEGMENT_FACTORY_PIPELINE_V1

## Objetivo

Definir o fluxo oficial da Fábrica de Segmentos do MEI ROBÔ a partir da Ótica.

---

# 1. Princípio

A construção de segmento deve gerar:

1. um runtime compacto para o próprio segmento;
2. aprendizado reutilizável para acelerar segmentos futuros.

---

# 2. Pipeline oficial

## 2.1 Pesquisa

Pesquisar fontes reais:

- treinamentos;
- especialistas;
- entidades;
- fabricantes;
- materiais técnicos;
- reclamações reais;
- problemas de pós-venda;
- causas de retrabalho;
- causas de insatisfação.

Objetivo:

Descobrir mecanismos reais, não apenas serviços.

---

## 2.2 Modelagem canônica

Criar modelo amplo do segmento.

Deve conter:

- expertise técnica;
- comportamento do cliente;
- lacunas de informação;
- riscos;
- padrões de confiança;
- diferença entre iniciante e especialista;
- princípios operacionais.

---

## 2.3 Runtime compacto

Destilar o modelo para estruturas adequadas ao GPT-4o-mini.

Priorizar:

- detected_state;
- next_objective;
- allowed_actions;
- avoid_actions;
- sequências de decisão;
- critérios;
- estados;
- objetivos.

---

## 2.4 Auditoria do runtime

Verificar:

- compactação;
- determinismo;
- separação pesquisa/runtime;
- cobertura mínima;
- risco de excesso;
- risco de genericidade.

---

## 2.5 Extração de componentes

Separar:

- exclusivo do segmento;
- reutilizável por customização;
- componentes herdados de segmentos anteriores;
- componentes novos descobertos.

---

## 2.6 Atualização da biblioteca

Atualizar:

- SEGMENT_COMPONENT_LIBRARY_V1.md;
- status dos componentes;
- origem;
- segmentos candidatos;
- restrições de customização.

---

## 2.7 Firestore

Somente depois da fase de conteúdo estar encerrada:

- criar JSON compacto do runtime;
- rodar validação local;
- rodar dry-run;
- aplicar com merge=True;
- testar no WhatsApp.

---

# 3. Ordem correta

Nunca pular diretamente da pesquisa para o Firestore.

Ordem obrigatória:

Pesquisa
↓
Modelo Canônico
↓
Runtime Compacto
↓
Auditoria
↓
Extração de Componentes
↓
JSON Compacto
↓
Dry-run
↓
Firestore
↓
Teste

---

# 4. Regra de continuidade da fábrica

O segundo segmento deve usar a biblioteca da Ótica quando fizer sentido.

Ao terminar, o segundo segmento também deve doar novos componentes.

O terceiro segmento deve usar:

- componentes da Ótica;
- componentes do segundo segmento;
- componentes próprios descobertos na pesquisa.

Esse ciclo continua até que muitos segmentos passem a ser montagem estrutural customizada do que já existe.
