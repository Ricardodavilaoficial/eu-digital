# OTICA_FINALIZACAO_CMD_RUNBOOK_V1

## Objetivo

Orientar a incorporação dos documentos de finalização da Ótica ao repositório local do MEI ROBÔ usando 100% CMD.

Este runbook não aplica Firestore.

Este runbook não faz deploy.

Este runbook não altera código.

---

# 1. Premissas

Rodar na raiz do projeto:

C:\Users\Ricardo d'Avila\Desktop\meu-projeto-eu-digital-final

---

# 2. Criar pastas

```cmd
mkdir docs\segment_factory
mkdir docs\segment_factory\reusable_assets
mkdir docs\segment_factory\components
mkdir docs\segment_factory\governance
mkdir docs\segment_factory\pipeline
mkdir docs\segment_factory\cmd_runbooks
mkdir docs\subsegments\otica\source
```

---

# 3. Copiar os arquivos gerados

Copiar manualmente os arquivos deste pacote para as pastas correspondentes do projeto.

Estrutura esperada:

```cmd
docs\segment_factory\reusable_assets\OTICA_REUSABLE_COMPONENTS_V1.md
docs\segment_factory\components\SEGMENT_COMPONENT_LIBRARY_V1.md
docs\segment_factory\governance\COMPONENT_EXTRACTION_RULES_V1.md
docs\segment_factory\governance\SEGMENT_FACTORY_GOVERNANCE_V1.md
docs\segment_factory\pipeline\SEGMENT_FACTORY_PIPELINE_V1.md
docs\segment_factory\cmd_runbooks\OTICA_FINALIZACAO_CMD_RUNBOOK_V1.md
docs\subsegments\otica\source\OTICA_V3_CANONICAL_MODEL.md
docs\subsegments\otica\source\OTICA_RUNTIME_COMPACT_V1.md
docs\subsegments\otica\source\OTICA_LESSONS_LEARNED_V1.md
docs\subsegments\otica\source\OTICA_RUNTIME_COMPACT_AUDIT_V1.md
```

---

# 4. Conferir arquivos

```cmd
dir docs\segment_factory /s

dir docs\subsegments\otica\source
```

---

# 5. Conferir status Git

```cmd
git status --short
```

---

# 6. Commit documental

```cmd
git add docs\segment_factory docs\subsegments\otica\source

git commit -m "docs: finaliza otica como referencia da fabrica de segmentos"

git push origin main
```

---

# 7. O que NÃO fazer nesta etapa

Não rodar Cloud Run.

Não rodar deploy.

Não aplicar Firestore.

Não alterar prompt.

Não alterar código.

Não criar `kb_patterns_v1`.

Não criar `kb_components_v1`.

---

# 8. Próxima etapa depois do commit

Com a Ótica encerrada, iniciar o próximo segmento com a pergunta:

O que este segmento pode reutilizar da biblioteca da Ótica, e o que ele precisa descobrir de novo?
