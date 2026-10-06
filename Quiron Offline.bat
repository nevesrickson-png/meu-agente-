@echo off
rem Quiron OFFLINE: sem internet, com modelo local (Ollama) e os clientes reais no cofre criptografado.
rem Feche esta janela para desligar. Guia: docs\10-OFFLINE.md
title Quiron Offline
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Programs\Ollama;%PATH%"
set "QUIRON_MODO=offline"
set "UV_OFFLINE=1"
where uv >nul 2>nul || (echo Rode primeiro o "Abrir Quiron.bat" - com internet, uma vez. & pause & exit /b 1)
where ollama >nul 2>nul || (echo Instale o Ollama: https://ollama.com/download - depois rode: ollama pull qwen2.5:3b & pause & exit /b 1)
curl -s http://127.0.0.1:11434/api/tags >nul 2>nul || (start "" /min ollama serve & timeout /t 5 >nul)
echo Conferindo a versao offline...
uv run --offline --quiet quiron-offline verificar
if errorlevel 1 (echo. & echo Corrija o item marcado com X acima e abra de novo. & pause & exit /b 1)
echo.
echo Abrindo o Quiron offline no navegador (CLI = clientes, BIB = biblioteca, CHAT = Quiron local)...
echo Para voltar ao normal: CONFIGURACOES - Versao offline - Voltar ao modo normal.
uv run --offline --quiet quiron --offline
if errorlevel 1 pause
