@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   PHOENIX - RECUPERACAO DE UPDATE INTERROMPIDO
echo ============================================
echo.

echo [i] Feche Phoenix Engine/Aviary antes de continuar.
set "PHX_RECOVERY_PY="
where python >nul 2>&1
if %ERRORLEVEL% equ 0 set "PHX_RECOVERY_PY=python"
if not defined PHX_RECOVERY_PY if exist ".venv\Scripts\python.exe" set "PHX_RECOVERY_PY=.venv\Scripts\python.exe"
if not defined PHX_RECOVERY_PY goto :no_python

%PHX_RECOVERY_PY% "upgrade_phoenix.py" recover --root "%CD%"
if %ERRORLEVEL% neq 0 goto :failed

echo.
echo [OK] Recovery gate limpo. A Phoenix pode ser iniciada normalmente.
pause
exit /b 0

:no_python
echo.
echo [X] Nenhum Python funcional encontrado para executar a recuperacao.
pause
exit /b 2

:failed
echo.
echo [X] A recuperacao nao foi concluida com seguranca.
echo     A Phoenix continuara bloqueada ate o journal ser resolvido.
echo     Consulte o transaction.json no backup de upgrades.
pause
exit /b 2
