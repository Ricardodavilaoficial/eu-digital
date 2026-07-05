@echo off
setlocal ENABLEDELAYEDEXPANSION

REM === Pre-req: signed.json já existe (veio do POST /media/signed-url) ===
if not exist signed.json (
  echo ERRO: signed.json nao encontrado. Primeiro gere com /media/signed-url.
  exit /b 1
)

REM === Extrair uploadUrl e downloadUrl (robusto p/ &, :, etc.) ===
set "UPLOAD_URL="
set "DOWNLOAD_URL="

for /f tokens^=2 delims^=^" %%A in ('findstr /I "uploadUrl" signed.json') do set "UPLOAD_URL=%%A"
for /f tokens^=2 delims^=^" %%A in ('findstr /I "downloadUrl" signed.json') do set "DOWNLOAD_URL=%%A"

echo UPLOAD_URL prefix: !UPLOAD_URL:~0,110!...
echo DOWNLOAD_URL prefix: !DOWNLOAD_URL:~0,110!...

if "!UPLOAD_URL!"=="" (
  echo ERRO: uploadUrl nao foi extraido do signed.json
  type signed.json
  exit /b 2
)
if "!DOWNLOAD_URL!"=="" (
  echo ERRO: downloadUrl nao foi extraido do signed.json
  type signed.json
  exit /b 3
)

REM === PUT do arquivo ===
if "%FILE%"=="" (
  echo ERRO: a var FILE nao esta definida. Ex: set "FILE=C:\Users\Ricardo d'Avila\Desktop\voz_teste.mp3"
  exit /b 4
)
echo.
echo === Enviando arquivo com PUT (esperado 200/201/204) ===
"%SystemRoot%\System32\curl.exe" -i -X PUT -H "Content-Type: audio/mpeg" --data-binary "@%FILE%" "!UPLOAD_URL!"

echo.
echo === HEAD (esperado 200 OK) ===
"%SystemRoot%\System32\curl.exe" -I "!DOWNLOAD_URL!" | findstr /B "HTTP/"

echo.
echo === RANGE 1 byte (esperado 206 Partial Content) ===
"%SystemRoot%\System32\curl.exe" -i -H "Range: bytes=0-0" "!DOWNLOAD_URL!" | findstr /B "HTTP/"

endlocal
