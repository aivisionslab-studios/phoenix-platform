@echo off
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if "%~1"=="" (
  echo Transacoes disponiveis:
  "%PY%" upgrade_phoenix.py list
  echo.
  set /p PHX_CONFIRM=Digite ROLLBACK para reverter a ultima atualizacao committed: 
  if /I not "%PHX_CONFIRM%"=="ROLLBACK" exit /b 1
  "%PY%" upgrade_phoenix.py rollback
) else (
  set /p PHX_CONFIRM=Digite ROLLBACK para reverter a transacao %~1: 
  if /I not "%PHX_CONFIRM%"=="ROLLBACK" exit /b 1
  "%PY%" upgrade_phoenix.py rollback --transaction-id "%~1"
)
exit /b %errorlevel%
