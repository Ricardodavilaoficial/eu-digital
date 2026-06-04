@echo off
setlocal

mkdir docs\subsegments\clinica_exames_medicos 2>nul
mkdir docs\subsegments\clinica_exames_medicos\source 2>nul
mkdir docs\subsegments\clinica_exames_medicosirestore 2>nul
mkdir docs\subsegments\clinica_exames_medicosudits 2>nul
mkdir docs\subsegments\clinica_exames_medicos\cmd_runbooks 2>nul

copy /Y CLINICA_EXAMES_SPECIALIST_REASONING_MATRIX_V1.md docs\subsegments\clinica_exames_medicos\source\CLINICA_EXAMES_SPECIALIST_REASONING_MATRIX_V1.md
copy /Y CLINICA_EXAMES_MATRIX_CMD_RUNBOOK_V1.md docs\subsegments\clinica_exames_medicos\cmd_runbooks\CLINICA_EXAMES_MATRIX_CMD_RUNBOOK_V1.md

dir docs\subsegments\clinica_exames_medicos\source

git status --short
git add docs\subsegments\clinica_exames_medicos
git commit -m "docs: adiciona matriz de raciocinio especialista da clinica de exames"
git push origin main

del APLICAR_CLINICA_EXAMES_MATRIX_V1.cmd
endlocal
