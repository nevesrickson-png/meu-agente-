@echo off
rem Abre a tela de Configuracoes do Quiron (chaves, seu ID do Telegram) no navegador.
title Quiron - Configuracoes
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul || (echo Rode primeiro o "Abrir Quiron.bat". & pause & exit /b 1)
uv run --quiet quiron-configurar
echo.
echo Se o Quiron ja estava aberto, feche a janela dele e abra de novo pelo atalho Quiron.
timeout /t 8 >nul
