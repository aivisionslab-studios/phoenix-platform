@echo off
setlocal
title PHOENIX SHADOW TREE DEEP ANALYZER V2
cd /d "%~dp0"
echo ============================================================
echo PHOENIX SHADOW TREE DEEP ANALYZER V2
echo READ-ONLY - diff semantico + referencias externas
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
  py -3 "%~dp0ANALISAR_SHADOW_TREE_DEEP_V2.py" "%ROOT%"
) else (
  python "%~dp0ANALISAR_SHADOW_TREE_DEEP_V2.py" "%ROOT%"
)
set "EC=%ERRORLEVEL%"
echo.
echo Codigo final: %EC%
echo Esta janela permanecera aberta para leitura.
pause
exit /b %EC%
