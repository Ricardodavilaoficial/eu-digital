# COMPONENT_EXTRACTION_RULES_V1

## Objetivo

Definir quando um elemento de um segmento pode ser extraído como componente reutilizável para a Fábrica de Segmentos do MEI ROBÔ.

---

# 1. Regra principal

Não extrair conteúdo porque parece interessante.

Extrair apenas mecanismos que possam ajudar outros segmentos.

---

# 2. Pode virar componente quando

Um elemento pode virar componente quando:

- descreve um mecanismo, não apenas um produto;
- pode ser customizado para outro segmento;
- melhora a condução da conversa;
- ajuda a reduzir erro, retrabalho ou expectativa desalinhada;
- ajuda o GPT-4o-mini com estrutura determinística;
- não depende de termos exclusivos do segmento original;
- possui função clara no processo decisório.

---

# 3. Não deve virar componente quando

Um elemento não deve virar componente quando:

- é produto específico;
- é serviço específico;
- é norma técnica restrita ao segmento;
- só faz sentido com vocabulário local;
- depende de uma política comercial de assinante;
- é pesquisa bruta;
- é explicação longa;
- é exemplo promocional;
- não melhora o runtime.

---

# 4. Exemplo com Ótica

Não extrair:

- lente multifocal;
- antirreflexo;
- armação;
- grau;
- receita;
- compatibilidade lente x armação.

Pode extrair:

- descobrir necessidade antes de recomendar;
- identificar lacunas de informação;
- alinhar expectativa;
- reduzir risco;
- reformular pergunta genérica;
- demonstrar método;
- separar expertise-base de personalização do assinante.

---

# 5. Ciclo por segmento

Cada segmento deve terminar com uma auditoria de extração:

1. o que ficou exclusivo;
2. o que pode ser reutilizado;
3. o que foi reutilizado de segmentos anteriores;
4. o que é novo;
5. o que deve ir para a biblioteca;
6. o que ainda não deve virar Firestore.

---

# 6. Firestore

Componentes não vão automaticamente para o Firestore.

Por padrão:

- documentação fica em docs;
- runtime compacto do segmento vai para JSON;
- JSON compacto pode ir para Firestore;
- componentes permanecem documentais até maturidade suficiente.

---

# 7. Compatibilidade arquitetural

A Fábrica de Segmentos deve preservar:

- kb_archetypes_v1;
- kb_segments_v1;
- kb_subsegments_v1;
- platform_kb;
- platform_kb_action_maps;
- platform_kb_support_articles.

Componentes são camada de criação e governança.

Não são substituição da arquitetura atual.
