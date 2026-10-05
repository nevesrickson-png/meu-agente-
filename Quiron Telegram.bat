@echo off
rem Compatibilidade: versoes antigas do "Abrir Quiron.bat" chamam este arquivo no fim.
rem Hoje tudo abre junto pelo atalho Quiron (Terminal + Acervo + Configuracoes + Telegram).
title Quiron
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul || (echo Rode primeiro o "Abrir Quiron.bat". & pause & exit /b 1)
uv run quiron
if errorlevel 1 pause
