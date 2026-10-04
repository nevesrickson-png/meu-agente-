@echo off
rem ============================================================================
rem  QUIRON - um clique: instala (1a vez), baixa a versao mais nova e abre o bot.
rem  - Pasta do programa: a pasta onde este arquivo esta (se ja for o projeto)
rem    ou %USERPROFILE%\Quiron (computador novo).
rem  - Todas as versoes ficam guardadas na pasta (historico do git).
rem  - Seus dados (.env, dados\, biblioteca\) nunca sao apagados nem enviados.
rem ============================================================================
setlocal
set "REPO=https://github.com/nevesrickson-png/meu-agente-.git"
set "RAMO=claude/determined-davinci-y9dr5i"

rem Roda a partir de uma copia temporaria: assim a atualizacao pode trocar
rem este proprio arquivo sem atrapalhar o que esta em execucao.
if "%~1"=="--copia" goto inicio
copy /y "%~f0" "%TEMP%\quiron-abrir.bat" >nul
"%TEMP%\quiron-abrir.bat" --copia "%~dp0"

:inicio
title Quiron
set "ORIGEM=%~2"
if exist "%ORIGEM%.git\" (set "PASTA=%ORIGEM:~0,-1%") else (set "PASTA=%USERPROFILE%\Quiron")
echo.
echo  QUIRON  -  pasta: %PASTA%
echo  ----------------------------------------------------------------

rem ---------- 1. Git (baixa e guarda as versoes) ----------
where git >nul 2>nul && goto tem_git
echo  [1/4] Instalando o Git (so na primeira vez)...
winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
where git >nul 2>nul && goto tem_git
echo  Nao consegui instalar o Git. Instale por https://git-scm.com/download/win e rode de novo.
pause
exit /b 1
:tem_git

rem ---------- 2. uv (roda o Python do Quiron) ----------
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul && goto tem_uv
echo  [2/4] Instalando o uv (so na primeira vez)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
where uv >nul 2>nul && goto tem_uv
echo  Nao consegui instalar o uv. Veja https://docs.astral.sh/uv/ e rode de novo.
pause
exit /b 1
:tem_uv

rem ---------- 3. Baixar / atualizar ----------
if exist "%PASTA%\.git\" goto atualizar
echo  [3/4] Baixando o Quiron pela primeira vez (pode pedir login no GitHub)...
git clone -b "%RAMO%" "%REPO%" "%PASTA%"
if errorlevel 1 (echo  Falhou o download. Confira a internet e o login do GitHub. & pause & exit /b 1)
goto baixado
:atualizar
echo  [3/4] Procurando atualizacoes...
cd /d "%PASTA%"
for /f %%v in ('git rev-parse --short HEAD') do set "ANTES=%%v"
git fetch -q origin "%RAMO%"
if errorlevel 1 (echo  Sem internet ou sem acesso ao GitHub: abrindo a versao que ja esta no PC. & goto baixado)
git switch -q "%RAMO%" 2>nul || git switch -q -c "%RAMO%" --track "origin/%RAMO%"
git merge -q --ff-only "origin/%RAMO%"
if errorlevel 1 (echo  Voce alterou arquivos do programa; mantive a sua versao. Me avise para eu ajudar a juntar. & goto baixado)
for /f %%v in ('git rev-parse --short HEAD') do set "DEPOIS=%%v"
if "%ANTES%"=="%DEPOIS%" (echo  Ja esta na versao mais nova: %DEPOIS%) else (echo  Atualizado: %ANTES% para %DEPOIS%)
:baixado
cd /d "%PASTA%"

rem ---------- 4. Chaves (.env) e atalho na Area de Trabalho ----------
echo  Preparando (na 1a vez instala tudo e demora alguns minutos)...
uv run --quiet quiron-configurar --verificar >nul 2>nul
if not errorlevel 1 goto tem_env
echo.
echo  Abrindo a tela de CONFIGURACOES no navegador.
echo  Preencha as chaves e clique em "Salvar e concluir". O Quiron liga em seguida.
uv run --quiet quiron-configurar
uv run --quiet quiron-configurar --verificar >nul 2>nul
if errorlevel 1 (echo  As configuracoes ainda estao incompletas. Abra de novo pelo atalho Quiron. & pause & exit /b 1)
:tem_env
set "ALVO=%PASTA%\Abrir Quiron.bat"
set "CONFIG=%PASTA%\Quiron Configuracoes.bat"
set "ACERVO=%PASTA%\Quiron Acervo.bat"
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $sh=New-Object -ComObject WScript.Shell; $s=$sh.CreateShortcut((Join-Path $d 'Quiron.lnk')); $s.TargetPath=$env:ALVO; $s.WorkingDirectory=$env:PASTA; $s.IconLocation='%SystemRoot%\System32\imageres.dll,76'; $s.Save(); $c=$sh.CreateShortcut((Join-Path $d 'Quiron - Configuracoes.lnk')); $c.TargetPath=$env:CONFIG; $c.WorkingDirectory=$env:PASTA; $c.IconLocation='%SystemRoot%\System32\imageres.dll,109'; $c.Save(); $v=$sh.CreateShortcut((Join-Path $d 'Quiron - Acervo.lnk')); $v.TargetPath=$env:ACERVO; $v.WorkingDirectory=$env:PASTA; $v.IconLocation='%SystemRoot%\System32\imageres.dll,112'; $v.Save()" >nul 2>nul

echo  [4/4] Abrindo o Quiron (a 1a vez demora alguns minutos instalando)...
echo  ----------------------------------------------------------------
call "%PASTA%\Quiron Telegram.bat"
