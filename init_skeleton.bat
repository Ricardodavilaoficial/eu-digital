@echo off
REM MEI Robô — Passo 1 (V1.0 pré-produção): criar esqueleto de pastas/arquivos vazios
REM Não altera comportamento em produção; apenas estrutura os módulos futuros.

setlocal enableextensions enabledelayedexpansion

REM Ir para a pasta onde o .bat está salvo (assumindo raiz do projeto)
cd /d "%~dp0"

REM Pastas-alvo
set DIRS=nlu domain providers cache

for %%D in (%DIRS%) do (
  if not exist "%%D" (
    echo [+] Criando pasta: %%D
    mkdir "%%D"
  ) else (
    echo [=] Pasta ja existe: %%D
  )
)

REM Garantir __init__.py em cada pacote (para o Python reconhecer como package)
for %%D in (%DIRS%) do (
  if not exist "%%D\__init__.py" (
    echo # package> "%%D\__init__.py"
    echo [+] Criando %%D\__init__.py
  ) else (
    echo [=] Ja existe: %%D\__init__.py
  )
)

REM Arquivos vazios conforme a estrutura-alvo (não sobrescreve se já existir)
set FILES=nlu\intent.py nlu\entities.py nlu\normalizer.py ^
          domain\pricing.py domain\scheduling.py domain\faq.py ^
          providers\firestore.py providers\ycloud.py providers\tts.py ^
          cache\kv.py

for %%F in (%FILES%) do (
  if not exist "%%F" (
    echo.> "%%F"
    echo [+] Criando arquivo: %%F
  ) else (
    echo [=] Ja existe: %%F
  )
)

echo.
echo [OK] Esqueleto criado/atualizado sem alterar comportamento.
echo     Pastas: nlu, domain, providers, cache
echo     Arquivos vazios + __init__.py gerados quando necessario.
echo.
echo Dica: rode "tree /f" para inspecionar a estrutura.
endlocal
