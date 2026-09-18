$ErrorActionPreference='Stop'
Write-Host '=== Phoenix Forge v0.15.0 ===' -ForegroundColor Cyan

if (!(Test-Path .venv)) { python -m venv .venv }

& .\.venv\Scripts\python.exe -m pip install -U pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with exit code $LASTEXITCODE" }

& .\.venv\Scripts\python.exe -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "Phoenix Forge Python core installation failed with exit code $LASTEXITCODE" }
Write-Host 'Python core installed.' -ForegroundColor Green

if (Get-Command cmake -ErrorAction SilentlyContinue) {
  Push-Location native
  try {
    cmake -S . -B build
    if ($LASTEXITCODE -ne 0) { throw "CMake configure failed with exit code $LASTEXITCODE" }
    cmake --build build --config Release
    if ($LASTEXITCODE -ne 0) { throw "Native build failed with exit code $LASTEXITCODE" }
  } finally { Pop-Location }
  $installed=$false
  $candidates = @('.\native\build\Release\phoenix-forge-native.exe','.\native\build\phoenix-forge-native.exe')
  foreach($c in $candidates){
    if(Test-Path $c){
      Copy-Item $c .\.venv\Scripts\phoenix-forge-native.exe -Force
      Write-Host "Native helper installed: $c" -ForegroundColor Green
      if(Test-Path '.\native\build\stress.spv'){
        Copy-Item '.\native\build\stress.spv' '.\.venv\Scripts\stress.spv' -Force
        Copy-Item '.\native\build\stress.spv' (Join-Path (Split-Path $c -Parent) 'stress.spv') -Force
        Write-Host 'Vulkan compute shader installed beside both native helpers.' -ForegroundColor Green
      }
      $installed=$true
      break
    }
  }
  if(-not $installed){ throw 'Native build completed but phoenix-forge-native.exe was not found.' }

  if (!(Test-Path '.\.venv\Scripts\phoenix-forge-native.exe')) { throw 'Native helper copy validation failed.' }
  & .\.venv\Scripts\phoenix-forge-native.exe --help
  if ($LASTEXITCODE -ne 0) { throw "Native helper smoke test failed with exit code $LASTEXITCODE" }

  if (!(Test-Path '.\.venv\Scripts\stress.spv')) {
    throw 'Vulkan compute shader stress.spv was not installed.'
  }
} else {
  Write-Warning 'CMake not found; native Vulkan tests will be unavailable.'
}

Write-Host ''
Write-Host 'Smoke test:' -ForegroundColor Cyan
& .\.venv\Scripts\phoenix-forge.exe detect
if ($LASTEXITCODE -ne 0) { throw "Phoenix Forge smoke test failed with exit code $LASTEXITCODE" }
Write-Host ''
Write-Host 'Ready. Activate with: .\.venv\Scripts\Activate.ps1' -ForegroundColor Green
Write-Host 'Inspect: phoenix-forge inspect' -ForegroundColor Green
Write-Host 'VRAM: phoenix-forge vram-map --chunk-mb 512 --target-mb 6144 --adaptive --min-chunk-mb 128 --reserve-mb 512 --passes 1' -ForegroundColor Green
Write-Host 'GPU compute: phoenix-forge gpu-compute-stress --seconds 20 --mb 256 --rounds 64' -ForegroundColor Green
Write-Host 'Watchdog: phoenix-forge whea --minutes 60' -ForegroundColor Green
