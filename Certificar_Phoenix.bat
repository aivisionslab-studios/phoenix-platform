@echo off
setlocal
cd /d "%~dp0"

set "PHX_PYTHON=.venv\Scripts\python.exe"
if not exist "%PHX_PYTHON%" set "PHX_PYTHON=python"

echo.
echo ===========================================
echo   PHOENIX POST-INSTALL CERTIFICATION 7F
echo ===========================================
echo.

"%PHX_PYTHON%" certify_phoenix_install.py --root "%~dp0" --profile windows-ready
set "PHX_CERT_EXIT=%ERRORLEVEL%"

echo.
if "%PHX_CERT_EXIT%"=="0" (
  echo [OK] Certificacao concluida.
) else (
  echo [X] Certificacao encontrou falha CORE. Veja o relatorio em logs\certification\latest.json
)
echo.
echo Para gerar um pacote de diagnostico compartilhavel: Criar_Pacote_Suporte.bat
echo.
pause
exit /b %PHX_CERT_EXIT%
