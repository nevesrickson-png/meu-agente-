@echo off
rem Quiron no Telegram rodando no seu PC. Feche esta janela para desligar.
rem Se cair (internet, erro), ele religa sozinho em 30 segundos.
title Quiron Telegram
cd /d "%~dp0"
where uv >nul 2>nul || (echo O uv nao esta instalado. Veja o LEIA-ME.md, secao "Rodar no seu PC". & pause & exit /b 1)
if not exist .env (echo Falta o arquivo .env com as chaves. Veja o LEIA-ME.md. & pause & exit /b 1)
:laco
echo [%date% %time%] Ligando o Quiron no Telegram...
uv run quiron-telegram
echo [%date% %time%] O Quiron parou. Religando em 30 segundos (feche a janela para desligar de vez).
timeout /t 30 /nobreak >nul
goto laco
