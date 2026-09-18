@echo off
setlocal
cd /d "%~dp0"

set "PHX_PY="
if exist ".venv\Scripts\python.exe" set "PHX_PY=.venv\Scripts\python.exe"
if not defined PHX_PY where python >nul 2>&1 && set "PHX_PY=python"

if not defined PHX_PY (
  echo [X] Python nao encontrado. Nao foi possivel verificar a integridade da instalacao.
  exit /b 2
)

set "PHX_REFRESH="
if /I "%~1"=="REFRESH" set "PHX_REFRESH=--refresh"
if /I "%~1"=="FULL" set "PHX_REFRESH=--refresh"

%PHX_PY% startup_integrity.py verify --root "%CD%" %PHX_REFRESH%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [X] Integridade da instalacao Phoenix FALHOU.
  echo     O startup tambem sera bloqueado ate o problema ser corrigido.
  exit /b %RC%
)

echo.
echo [OK] Integridade da instalacao Phoenix validada.
exit /b 0
