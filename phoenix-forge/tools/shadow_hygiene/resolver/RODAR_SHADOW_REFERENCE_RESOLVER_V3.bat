@echo off
setlocal
title PHOENIX SHADOW REFERENCE RESOLVER V3
cd /d "%~dp0"
echo ============================================================
echo PHOENIX SHADOW REFERENCE RESOLVER V3
echo READ-ONLY - separa referencia operacional de ruido/teste/auditoria
echo ============================================================
echo.
set "ROOT=C:\PROJETO COMPLETO\PHOENIX 4.5"
if not exist "%ROOT%\" (
  echo [ERRO] Raiz nao encontrada: %ROOT%
  pause
  exit /b 2
)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%~dp0RESOLVER_REFERENCIAS_SHADOW_V3.py" "%ROOT%"
) else (
  python "%~dp0RESOLVER_REFERENCIAS_SHADOW_V3.py" "%ROOT%"
)
set "EC=%ERRORLEVEL%"
echo.
echo Codigo final: %EC%
echo Esta janela permanecera aberta para leitura.
pause
exit /b %EC%
