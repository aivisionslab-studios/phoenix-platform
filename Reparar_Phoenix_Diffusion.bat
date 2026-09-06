@echo off
REM Reparo isolado da bridge nativa de imagens. Nao reinstala .venv,
REM modelos, banco RAG, Docker nem a Phoenix Aviary Platform.
cd /d "%~dp0"

echo.
echo ==========================================
echo   REPARO DA PHOENIX DIFFUSION - VULKAN
echo ==========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\phoenix-diffusion.cpp\scripts\build_windows_rx580.ps1" -Force
if %ERRORLEVEL% neq 0 (
    echo.
    echo [X] O reparo falhou. Leia a ultima mensagem acima: ela informa
    echo     se falta CMake, Visual Studio C++ Build Tools ou Vulkan SDK.
    echo.
    pause
    exit /b 1
)

if not exist "bin\phoenix_sd_bridge.dll" (
    echo.
    echo [X] O compilador terminou, mas bin\phoenix_sd_bridge.dll nao existe.
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] Phoenix Diffusion reparada. Agora abra Iniciar_Phoenix.bat.
echo.
pause
exit /b 0
