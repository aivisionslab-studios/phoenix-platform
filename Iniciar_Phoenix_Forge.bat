@echo off
setlocal
REM Phoenix Forge v0.12 API/Delivery Guard - somente loopback :8787.
REM Defina PHOENIX_FORGE_ROOT se o Forge estiver fora da pasta irmã padrão.

set "FORGE_ROOT=%PHOENIX_FORGE_ROOT%"
if defined FORGE_ROOT goto :root_found
if exist "%~dp0..\PHOENIX FORGE\phoenix-forge\phoenix_forge\api\app.py" set "FORGE_ROOT=%~dp0..\PHOENIX FORGE\phoenix-forge"
if not defined FORGE_ROOT if exist "%~dp0..\PHOENIX FORGE\phoenix-forge-v0.11.0\phoenix_forge\api\app.py" set "FORGE_ROOT=%~dp0..\PHOENIX FORGE\phoenix-forge-v0.11.0"
if exist "%~dp0..\PHOENIX FORGE\phoenix_forge\api\app.py" set "FORGE_ROOT=%~dp0..\PHOENIX FORGE"

:root_found
if not defined FORGE_ROOT goto :missing
if not exist "%FORGE_ROOT%\phoenix_forge\api\app.py" goto :missing
if not exist "%FORGE_ROOT%\.venv\Scripts\python.exe" goto :venv_missing

powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',8787); exit 0}catch{exit 1}finally{$c.Dispose()}" >nul 2>&1
if %ERRORLEVEL% equ 0 (
  echo [OK] Phoenix Forge ja esta online em http://127.0.0.1:8787
  exit /b 0
)

echo [i] Iniciando Phoenix Forge em http://127.0.0.1:8787 ...
start "Phoenix Forge" /D "%FORGE_ROOT%" "%FORGE_ROOT%\.venv\Scripts\python.exe" -m uvicorn phoenix_forge.api.app:app --host 127.0.0.1 --port 8787
exit /b 0

:venv_missing
echo [X] Ambiente do Forge ausente: "%FORGE_ROOT%\.venv\Scripts\python.exe"
echo     Execute BUILD_WINDOWS.ps1 na raiz do Phoenix Forge.
exit /b 2

:missing
echo [X] Phoenix Forge v0.12/v0.11 nao localizado.
echo     Defina, por exemplo:
echo     set "PHOENIX_FORGE_ROOT=C:\PROJETO COMPLETO\PHOENIX FORGE\phoenix-forge"
exit /b 1
