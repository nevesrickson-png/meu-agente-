@echo off
rem Quíron Terminal — dois cliques para abrir. Feche esta janela para desligar.
title Quiron Terminal
cd /d "%~dp0"
where uv >nul 2>nul || (echo O uv nao esta instalado. Veja o LEIA-ME.md, secao "Rodar no seu PC". & pause & exit /b 1)
uv run quiron-terminal
if errorlevel 1 pause
