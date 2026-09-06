param(
  [string]$RemoteUrl = ""
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $Root
if (Test-Path .git) { throw "This directory already contains .git" }
git init -b main
git add .
git commit -m "Phoenix Diffusion.cpp: frozen stable base + native Phoenix bridge"
if ($RemoteUrl) {
    git remote add origin $RemoteUrl
    Write-Host "Remote configured. Push with: git push -u origin main"
}
Pop-Location
