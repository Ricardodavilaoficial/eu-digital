# OTICA_V4_TRAINING_RESEARCH

## Objetivo

Pesquisar e organizar conhecimentos técnicos, operacionais e comerciais encontrados em treinamentos, cursos, manuais, fabricantes e materiais reais do setor óptico.

O objetivo é tornar a base global do subsegmento Loja de Óculos mais autosuficiente, sem depender de o assinante anexar curso completo, manual técnico ou material acadêmico para que o MEI Robô tenha uma boa base inicial.

## Separação de responsabilidades

### Base global do subsegmento

Deve conter:

- conhecimento técnico-operacional seguro;
- padrões de atendimento;
- critérios de decisão;
- alertas de risco;
- limites do que a ótica pode orientar;
- raciocínio de consultor óptico.

### Acervo do assinante

Deve conter:

- cursos próprios;
- catálogos específicos;
- fabricantes e marcas trabalhadas;
- políticas comerciais;
- prazos;
- garantias;
- diferenciais;
- manuais internos;
- materiais técnicos profundos.

### Fora da base global

Evitar transformar o subsegmento em:

- curso completo de fabricação de lentes;
- manual acadêmico de óptica física;
- conteúdo médico de oftalmologia;
- diagnóstico clínico;
- tratamento de doenças oculares.

## Fontes iniciais identificadas

### Formação e consultoria óptica

- cursos de consultor óptico;
- cursos de vendedor de ótica;
- treinamentos de atendimento em óticas;
- conteúdos de consultores ópticos.

### Boas práticas

- manual de boas práticas de estabelecimentos ópticos;
- diretrizes de dispensação de armações, lentes oftálmicas, óculos solares, lentes de contato e acessórios.

### Fabricantes e laboratórios

- materiais sobre lentes progressivas/multifocais;
- materiais sobre adaptação;
- materiais sobre resina, policarbonato, alto índice e espessura;
- materiais sobre lentes fotossensíveis, antirreflexo e conforto visual.

## Temas técnicos-operacionais a aprofundar

1. papel do consultor óptico;
2. leitura segura da receita óptica;
3. diferença entre orientação óptica e diagnóstico oftalmológico;
4. armação adequada para grau alto;
5. espessura da lente;
6. índice de refração;
7. resina;
8. policarbonato;
9. alto índice;
10. multifocal/progressiva;
11. adaptação visual;
12. lente ocupacional;
13. antirreflexo;
14. fotossensível;
15. lente de contato;
16. ajuste e montagem;
17. status de pedido;
18. laboratório/montagem;
19. garantia e pós-venda;
20. condução para especialista.

## Regra de modelagem

Cada tema técnico deve virar estrutura compatível com GPT-4o-mini:

- topic
- principle
- why_it_matters
- common_customer_confusion
- decision_factors
- safe_response_direction
- boundary

## Exemplo

```json
{
  "topic": "armacao_para_grau_alto",
  "principle": "A armação influencia espessura, conforto e resultado visual em graus mais altos.",
  "why_it_matters": "A mesma receita pode gerar resultado diferente conforme tamanho, formato e material da armação.",
  "common_customer_confusion": "O cliente pode achar que qualquer armação serve para qualquer grau.",
  "decision_factors": [
    "grau",
    "tipo de lente",
    "tamanho da armação",
    "formato da armação",
    "uso diário"
  ],
  "safe_response_direction": "Explicar que a equipe pode orientar opções que equilibram estética, conforto e adequação técnica.",
  "boundary": "Não prometer resultado final sem avaliar receita, lente e armação."
}

