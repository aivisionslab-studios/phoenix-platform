param(
    [string]$Root = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$PatchRoot = Join-Path $PSScriptRoot "PATCH_FILES"

if (-not (Test-Path (Join-Path $Root "api_server.py"))) {
    throw "A raiz informada não parece ser a Phoenix: $Root"
}

if (-not (Test-Path $PatchRoot)) {
    throw "PATCH_FILES não encontrado ao lado deste script."
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$parent = Split-Path $Root -Parent
$backup = Join-Path $parent "PHOENIX_CAPABILITY_BACKUP_$stamp"

$files = @(
    "api_server.py",
    "platform_source\src\components\RagDrawer.tsx",
    "phoenix_kernel\intelligence\chroma_rag_backend.py",
    "phoenix_kernel\licensing\capability_protocol.py",
    "phoenix_kernel\licensing\capability_client.py",
    "phoenix_kernel\licensing\commercial_guard.py",
    "phoenix_kernel\licensing\entitlements.py",
    "phoenix_kernel\licensing\plans.py",
    "phoenix_kernel\security\rag_consensus.py",
    "phoenix_kernel\security\rag_integrity_manifest.py"
)

Write-Host ""
Write-Host "Phoenix Capability V4 - aplicando patch" -ForegroundColor Cyan
Write-Host "Projeto: $Root"
Write-Host "Backup : $backup" -ForegroundColor Yellow
Write-Host ""

foreach ($rel in $files) {
    $current = Join-Path $Root $rel
    $source  = Join-Path $PatchRoot $rel
    if (-not (Test-Path $source)) {
        throw "Arquivo do patch ausente: $rel"
    }

    if (Test-Path $current) {
        $backupFile = Join-Path $backup $rel
        New-Item -ItemType Directory -Path (Split-Path $backupFile -Parent) -Force | Out-Null
        Copy-Item $current $backupFile -Force
    }

    New-Item -ItemType Directory -Path (Split-Path $current -Parent) -Force | Out-Null
    Copy-Item $source $current -Force
    Write-Host "[OK] $rel" -ForegroundColor Green
}

# Nunca copia PRIVATE_SERVER_REFERENCE para a Phoenix.
# A chave privada/servidor comercial ficam fora do cliente.

Write-Host ""
Write-Host "Verificando sintaxe Python..." -ForegroundColor Cyan
$pyFiles = @(
    "api_server.py",
    "phoenix_kernel\intelligence\chroma_rag_backend.py",
    "phoenix_kernel\licensing\capability_protocol.py",
    "phoenix_kernel\licensing\capability_client.py",
    "phoenix_kernel\licensing\commercial_guard.py",
    "phoenix_kernel\licensing\entitlements.py",
    "phoenix_kernel\licensing\plans.py",
    "phoenix_kernel\security\rag_consensus.py",
    "phoenix_kernel\security\rag_integrity_manifest.py"
)

foreach ($rel in $pyFiles) {
    python -m py_compile (Join-Path $Root $rel)
    if ($LASTEXITCODE -ne 0) {
        throw "py_compile falhou em $rel. Backup preservado em $backup"
    }
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " CAPABILITY V4 APLICADA COM SUCESSO" -ForegroundColor Green
Write-Host " Backup: $backup" -ForegroundColor Yellow
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Sem servidor/chave/token valido, Phoenix permanece FREE." -ForegroundColor Gray
Write-Host "A chave PRIVADA nunca deve ser copiada para o projeto." -ForegroundColor Gray
