$ErrorActionPreference="Stop"
$root=$PSScriptRoot
Write-Host "=== PHOENIX FORGE WDK DIAGNOSTICS ==="
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "BUILD_WDK.ps1") -VerifyOnly
$code=$LASTEXITCODE
if($code -ne 0){
  Write-Host ""
  Write-Host "[BLOCKED] O Windows SDK/WDK esta parcial ou sem integracao do kernel toolset no Visual Studio."
  Write-Host "[CHECK] WindowsKernelModeDriver10.0 precisa existir no MSBuild PlatformToolsets."
  Write-Host "[SAFE] Nenhum driver foi instalado ou iniciado."
}
exit $code
