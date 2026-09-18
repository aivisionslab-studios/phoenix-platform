@echo off
setlocal
cd /d "%~dp0"

set "PY=python"
where python >nul 2>&1
if errorlevel 1 set "PY=.venv\Scripts\python.exe"

if "%~1"=="" (
  echo Uso: Atualizar_Phoenix.bat ^<release.zip^> [source^|windows-ready]
  echo.
  echo A Phoenix e a Aviary devem estar encerradas antes da atualizacao.
  exit /b 2
)

set "PROFILE=%~2"
if "%PROFILE%"=="" set "PROFILE=windows-ready"
set "SIGFLAG="
if /I "%PHOENIX_REQUIRE_SIGNED_RELEASE%"=="1" set "SIGFLAG=--require-signature"
set "TRUSTFLAG="
if not "%PHOENIX_RELEASE_TRUST_STORE%"=="" set TRUSTFLAG=--trust-store ^"%PHOENIX_RELEASE_TRUST_STORE%^"
set "DOWNGRADEFLAG="
if /I "%PHOENIX_ALLOW_DOWNGRADE%"=="1" set "DOWNGRADEFLAG=--allow-downgrade"
set "CHANNELFLAG="
if /I "%PHOENIX_ALLOW_CHANNEL_SWITCH%"=="1" set "CHANNELFLAG=--allow-channel-switch"

"%PY%" upgrade_phoenix.py plan --release "%~1" --profile "%PROFILE%" %SIGFLAG% %TRUSTFLAG% %DOWNGRADEFLAG% %CHANNELFLAG%
if errorlevel 1 exit /b %errorlevel%

echo.
set /p PHX_CONFIRM=Digite ATUALIZAR para aplicar a transacao: 
if /I not "%PHX_CONFIRM%"=="ATUALIZAR" (
  echo Atualizacao cancelada.
  exit /b 1
)

"%PY%" upgrade_phoenix.py apply --release "%~1" --profile "%PROFILE%" %SIGFLAG% %TRUSTFLAG% %DOWNGRADEFLAG% %CHANNELFLAG%
exit /b %errorlevel%
