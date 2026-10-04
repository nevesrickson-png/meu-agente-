@echo off
rem Quiron no Telegram rodando no seu PC. Feche esta janela para desligar.
rem Se cair (internet, erro), ele religa sozinho em 30 segundos.
title Quiron Telegram
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul || (echo O uv nao esta instalado. Veja o LEIA-ME.md, secao "Rodar no seu PC". & pause & exit /b 1)
uv run --quiet quiron-configurar --verificar >nul 2>nul
if errorlevel 1 (echo Faltam configuracoes: abrindo a tela de Configuracoes no navegador... & uv run --quiet quiron-configurar)
:laco
echo [%date% %time%] Ligando o Quiron no Telegram...
uv run quiron-telegram
echo [%date% %time%] O Quiron parou. Religando em 30 segundos (feche a janela para desligar de vez).
timeout /t 30 /nobreak >nul
goto laco
