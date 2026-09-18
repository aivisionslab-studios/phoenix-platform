param(
  [string]$Root = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
Write-Host "============================================================"
Write-Host "PHOENIX PRIVILEGED DRIVER WDK PREFLIGHT"
Write-Host "============================================================"

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$wdkRoots = @(
  "${env:ProgramFiles(x86)}\Windows Kits\10\Include",
  "${env:ProgramFiles(x86)}\Windows Kits\10\Lib"
)

$vs = $null
if (Test-Path -LiteralPath $vswhere) {
  $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
}

$wdkOk = $true
foreach ($p in $wdkRoots) {
  if (-not (Test-Path -LiteralPath $p)) { $wdkOk = $false }
}

$signingCert = $env:PHOENIX_DRIVER_SIGNING_CERT_THUMBPRINT

$result = [ordered]@{
  schema = "phoenix.forge.privileged-driver-wdk-preflight/v1"
  visual_studio = $vs
  wdk_present = $wdkOk
  signing_certificate_configured = -not [string]::IsNullOrWhiteSpace($signingCert)
  source_foundation_present = (
    (Test-Path -LiteralPath (Join-Path $Root "driver.c")) -and
    (Test-Path -LiteralPath (Join-Path $Root "phoenix_privileged_abi.h")) -and
    (Test-Path -LiteralPath (Join-Path $Root "PhoenixForgePrivileged.inf"))
  )
  production_build_ready = ($wdkOk -and -not [string]::IsNullOrWhiteSpace($signingCert))
  note = "No kernel driver binary is bundled. Build/signing is intentionally external in 0.25.0rc3."
}

$result | ConvertTo-Json -Depth 5
if (-not $result.source_foundation_present) { exit 2 }
exit 0
