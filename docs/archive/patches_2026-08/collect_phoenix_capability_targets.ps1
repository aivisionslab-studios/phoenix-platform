param(
    [string]$Root = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

$targets = @(
    "api_server.py",
    "platform_source\src\components\RagDrawer.tsx",
    "phoenix_kernel\intelligence\chroma_rag_backend.py",
    "phoenix_kernel\licensing\entitlements.py",
    "phoenix_kernel\licensing\plans.py",
    "phoenix_kernel\licensing\capability_protocol.py",
    "phoenix_kernel\licensing\capability_client.py",
    "phoenix_kernel\licensing\commercial_guard.py",
    "phoenix_kernel\security\rag_consensus.py",
    "phoenix_kernel\security\rag_integrity.py",
    "phoenix_kernel\security\rag_integrity_manifest.py",
    "phoenix_kernel\security\rag_usage_ledger.py"
)

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$temp = Join-Path $env:TEMP "phoenix_capability_targets_$stamp"
$zip  = Join-Path $Root "PHOENIX_CAPABILITY_TARGETS_$stamp.zip"

New-Item -ItemType Directory -Path $temp -Force | Out-Null

$copied = @()
$missing = @()

foreach ($rel in $targets) {
    $src = Join-Path $Root $rel
    if (Test-Path $src) {
        $dst = Join-Path $temp $rel
        $dstDir = Split-Path $dst -Parent
        New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
        Copy-Item $src $dst -Force
        $copied += $rel
    } else {
        $missing += $rel
    }
}

# Guarda também a saída atual do scanner.
$scan = Join-Path $Root "scan_capability_integration.py"
if (Test-Path $scan) {
    try {
        python $scan 2>&1 | Out-File -FilePath (Join-Path $temp "SCAN_RESULT.txt") -Encoding utf8
    } catch {
        $_ | Out-File -FilePath (Join-Path $temp "SCAN_RESULT_ERROR.txt") -Encoding utf8
    }
}

@"
PHOENIX CAPABILITY INTEGRATION TARGETS

COPIADOS:
$($copied -join "`r`n")

AUSENTES:
$($missing -join "`r`n")
"@ | Out-File -FilePath (Join-Path $temp "MANIFEST.txt") -Encoding utf8

if (Test-Path $zip) {
    Remove-Item $zip -Force
}

Compress-Archive -Path (Join-Path $temp "*") -DestinationPath $zip -CompressionLevel Optimal

Remove-Item $temp -Recurse -Force

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " ZIP CRIADO:" -ForegroundColor Green
Write-Host " $zip" -ForegroundColor Yellow
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Arquivos copiados: $($copied.Count)"
Write-Host "Arquivos ausentes: $($missing.Count)"
if ($missing.Count -gt 0) {
    $missing | ForEach-Object { Write-Host "  AUSENTE: $_" -ForegroundColor DarkYellow }
}
