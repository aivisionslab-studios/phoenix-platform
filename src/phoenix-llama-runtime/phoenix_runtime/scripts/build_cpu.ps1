param([string]$BuildDir = "build-phoenix-cpu")
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
cmake -S . -B $BuildDir -DGGML_VULKAN=OFF -DGGML_NATIVE=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build $BuildDir --config Release -j
$server = Join-Path $Root "$BuildDir\bin\Release\llama-server.exe"
if (-not (Test-Path $server)) { $server = Join-Path $Root "$BuildDir\bin\llama-server.exe" }
py "$Root\phoenix_runtime\verify_cli_contract.py" --server "$server"
Write-Host "[OK] Phoenix CPU runtime compilado: $server" -ForegroundColor Green
