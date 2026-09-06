param(
    [string]$Root = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

$Target = Join-Path $Root "phoenix_kernel\licensing\plans.py"
$Source = Join-Path $PSScriptRoot "PATCH_FILES\phoenix_kernel\licensing\plans.py"

if (-not (Test-Path $Target)) {
    throw "plans.py da Phoenix não encontrado: $Target"
}
if (-not (Test-Path $Source)) {
    throw "Arquivo do hotfix não encontrado: $Source"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Backup = "$Target.before_hotfix_$stamp"

Copy-Item $Target $Backup -Force
Copy-Item $Source $Target -Force

Write-Host "[OK] plans.py atualizado" -ForegroundColor Green
Write-Host "[OK] backup: $Backup" -ForegroundColor Yellow

python -m py_compile $Target
if ($LASTEXITCODE -ne 0) {
    throw "py_compile falhou. Restaure: $Backup"
}

python -c "from phoenix_kernel.licensing import RAG_PLAN_LIMITS, get_rag_limits; print('IMPORT OK'); print('PLAN KEYS =', sorted(RAG_PLAN_LIMITS.keys())); print('LIMITS =', get_rag_limits(force_refresh=True))"
if ($LASTEXITCODE -ne 0) {
    throw "Teste de import do pacote licensing falhou. Restaure: $Backup"
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " HOTFIX 01 APLICADO E IMPORT TESTADO" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Cyan
