@echo off
rem Quiron Acervo - abre a tela para enviar livros e materiais por area de conhecimento.
rem Feche esta janela para desligar (o Terminal e o Acervo usam o mesmo programa).
title Quiron Acervo
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul || (echo Rode primeiro o "Abrir Quiron.bat". & pause & exit /b 1)
uv run quiron-terminal --abrir /acervo
if errorlevel 1 pause
