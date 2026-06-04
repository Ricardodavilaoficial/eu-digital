# CLINICA_EXAMES_MATRIX_CMD_RUNBOOK_V1

## Objetivo

Incorporar a Matriz de Raciocínio Especialista V1 da Clínica de Exames Médicos ao repositório local do MEI ROBÔ usando 100% CMD.

Este runbook não aplica Firestore.
Este runbook não faz deploy.
Este runbook não altera código.
Este runbook apenas cria documentação versionada.

---

# 1. Premissa

Rodar na raiz do projeto:

```cmd
cd /d C:\Users\Ricardo d'Avila\Desktop\meu-projeto-eu-digital-final
```

# 2. Criar estrutura do subsegmento

```cmd
mkdir docs\subsegments\clinica_exames_medicos
mkdir docs\subsegments\clinica_exames_medicos\source
mkdir docs\subsegments\clinica_exames_medicos\firestore
mkdir docs\subsegments\clinica_exames_medicos\audits
mkdir docs\subsegments\clinica_exames_medicos\cmd_runbooks
```

# 3. Copiar arquivo da matriz

```cmd
copy /Y CLINICA_EXAMES_SPECIALIST_REASONING_MATRIX_V1.md docs\subsegments\clinica_exames_medicos\source\CLINICA_EXAMES_SPECIALIST_REASONING_MATRIX_V1.md
```

# 4. Conferir arquivo

```cmd
dir docs\subsegments\clinica_exames_medicos\source
type docs\subsegments\clinica_exames_medicos\source\CLINICA_EXAMES_SPECIALIST_REASONING_MATRIX_V1.md
```

# 5. Git

```cmd
git status --short
git add docs\subsegments\clinica_exames_medicos
git commit -m "docs: adiciona matriz de raciocinio especialista da clinica de exames"
git push origin main
```

# 6. O que NÃO fazer nesta etapa

Não aplicar Firestore.
Não rodar deploy.
Não alterar código.
Não alterar prompt.
Não criar coleção nova.
Não criar kb_components_v1.
Não criar kb_patterns_v1.
