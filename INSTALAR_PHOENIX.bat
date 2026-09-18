@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALAR_PHOENIX.ps1" %*
set "rc=%errorlevel%"
echo.
if not "%rc%"=="0" echo Falha na instalacao. Codigo: %rc%
pause
exit /b %rc%
