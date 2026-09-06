param([string]$UpstreamBranch = "master")
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Lock = Join-Path $Root "DEPENDENCIES.lock.json"
if (-not (Test-Path $Lock)) { throw "DEPENDENCIES.lock.json ausente." }
Write-Host "[INFO] Atualização automática desativada para preservar o fork Phoenix Diffusion."
Write-Host "[INFO] Branch solicitada: $UpstreamBranch (somente informativa)."
Write-Host "[PASS] Use revisão manual, atualize o lock e execute os testes antes de importar código externo."
