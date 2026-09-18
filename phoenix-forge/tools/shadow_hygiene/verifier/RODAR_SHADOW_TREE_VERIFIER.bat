@echo off
setlocal
title PHOENIX SHADOW TREE VERIFIER V1
cd /d "%~dp0"
echo ============================================================
echo PHOENIX SHADOW TREE VERIFIER V1
echo READ-ONLY - compara phoenix_project\phoenix_kernel com phoenix_kernel
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
  py -3 "%~dp0VERIFICAR_SHADOW_TREE_PHOENIX.py" "%ROOT%"
) else (
  python "%~dp0VERIFICAR_SHADOW_TREE_PHOENIX.py" "%ROOT%"
)
set "EC=%ERRORLEVEL%"
echo.
echo Codigo final: %EC%
echo Esta janela permanecera aberta para leitura.
pause
exit /b %EC%
