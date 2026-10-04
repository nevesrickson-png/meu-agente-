@echo off
rem Faz o Quiron ligar sozinho quando voce entra no Windows (e impede o PC de dormir na tomada).
rem Rode UMA vez com dois cliques. Para desfazer: rode de novo e escolha "R".
title Quiron - inicio automatico
cd /d "%~dp0"
set "ATALHO=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Quiron.lnk"
if exist "%ATALHO%" (
  choice /c SR /m "O inicio automatico ja esta ligado. [S]air ou [R]emover"
  if errorlevel 2 (del "%ATALHO%" & echo Inicio automatico removido. & pause & exit /b 0)
  exit /b 0
)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:ATALHO); $s.TargetPath='%~dp0Abrir Quiron.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
powercfg /change standby-timeout-ac 0
echo.
echo Pronto: o Quiron liga sozinho (janela minimizada) quando voce entra no Windows.
echo O PC nao vai mais dormir enquanto estiver na tomada (a tela ainda apaga normalmente).
echo Para o briefing das 7h30 chegar, o PC precisa estar ligado nesse horario.
pause
