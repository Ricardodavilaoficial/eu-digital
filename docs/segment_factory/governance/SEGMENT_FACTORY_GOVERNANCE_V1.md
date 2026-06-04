# SEGMENT_FACTORY_GOVERNANCE_V1

## Objetivo

Definir a governança da Fábrica de Segmentos do MEI ROBÔ.

---

# 1. Pilares preservados

- IA soberana;
- KB como fonte de verdade;
- sem palavras-chave rígidas;
- sem árvores de decisão manuais;
- sem lógica procedural excessiva;
- preservar o que funciona;
- análise de risco antes de qualquer alteração;
- não alterar prompts sem validação prévia;
- não alterar arquitetura sem necessidade comprovada.

---

# 2. O que é obrigatório por segmento

- pesquisa real;
- modelo canônico;
- runtime compacto;
- auditoria do runtime;
- mapeamento Firestore;
- runbook de aplicação;
- lessons learned;
- auditoria de componentes reutilizáveis.

---

# 3. O que é opcional

- criação de novos componentes;
- promoção de componente para pattern formal;
- nova coleção Firestore;
- alteração arquitetural.

Esses itens exigem validação adicional.

---

# 4. O que vai para Firestore

Por padrão, apenas o runtime compacto transformado em JSON validado.

---

# 5. O que não vai para Firestore

- pesquisa bruta;
- documentação extensa;
- auditorias;
- lessons learned;
- biblioteca de componentes;
- hipóteses não validadas;
- patterns candidatos.

---

# 6. Quando considerar uma coleção futura

Uma coleção como `kb_patterns_v1` ou `kb_components_v1` só deve ser considerada quando:

- houver recorrência real em múltiplos segmentos;
- o runtime já precisar consumir essa camada;
- a arquitetura atual não resolver o problema de forma simples;
- houver análise de risco aprovada;
- houver dry-run e plano de rollback.

---

# 7. Modo operacional

O modo operacional continua 100% CMD:

- sem PowerShell;
- sem backups manuais `.bak`;
- alterações por arquivos controlados;
- validação antes de aplicação;
- Git como histórico;
- Firestore apenas com dry-run antes de apply;
- Cloud Run apenas quando houver alteração de código ou configuração de runtime.
