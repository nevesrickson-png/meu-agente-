@echo off
rem Conecta o Quiron ao seu Google Agenda (uma vez so). Antes, siga docs\09-GOOGLE-AGENDA.md.
title Quiron - Google Agenda
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul || (echo Rode primeiro o "Abrir Quiron.bat". & pause & exit /b 1)
if not exist "segredos\google_oauth.json" (
  echo Falta o arquivo segredos\google_oauth.json.
  echo Siga o passo a passo em docs\09-GOOGLE-AGENDA.md e salve o arquivo baixado do Google com esse nome.
  pause
  exit /b 1
)
uv run --quiet quiron-google autorizar
echo.
pause
