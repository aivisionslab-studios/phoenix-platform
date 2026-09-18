[CmdletBinding()]
param(
    # Recria somente a pasta de build da Phoenix Diffusion. Não toca em
    # modelos, .venv, llama.cpp nem dados do usuário.
    [switch]$Force,
    # Limita o paralelismo para não esgotar RAM durante shaders/templates.
    [ValidateRange(1, 16)]
    [int]$Jobs = 4
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PhoenixRoot = (Resolve-Path (Join-Path $Root "..\..")).Path
# PHX-FIX (teste real RX 580/Windows): o GGML cria um ExternalProject para
# vulkan-shaders-gen e acrescenta mais de 150 caracteres ao diretório de
# build. Dentro de "C:\PROJETO COMPLETO\PHOENIX 4.5\src\..." o MSBuild
# FileTracker ultrapassou o limite e falhou com FTK1011, mesmo com long paths
# habilitados. Só o BUILD TEMPORÁRIO vai para um caminho curto; a fonte,
# modelos e a DLL promovida continuam na pasta normal do projeto.
$ShortBuildRoot = Join-Path $env:SystemDrive "pxb"
$BuildDir = Join-Path $ShortBuildRoot "phxsd"
$StableBinDir = Join-Path $PhoenixRoot "bin"
$StableDll = Join-Path $StableBinDir "phoenix_sd_bridge.dll"

function Find-PhoenixCMake {
    $command = Get-Command cmake.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $candidates = @(
        "C:\Program Files\CMake\bin\cmake.exe",
        "C:\Program Files (x86)\CMake\bin\cmake.exe"
    )
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $vsPath = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath -latest 2>$null
        if ($vsPath) {
            $candidates += (Join-Path $vsPath "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe")
        }
    }
    return ($candidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
}

function Get-PhoenixVsGenerator {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        throw "Visual Studio Build Tools não encontrado (vswhere.exe ausente)."
    }
    $installationPath = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath -latest 2>$null
    if (-not $installationPath) {
        throw "Visual Studio C++ Build Tools x64 não está instalado."
    }

    $line = & $vswhere -products * -path $installationPath -property catalog_productLineVersion 2>$null
    if (-not $line) {
        $version = & $vswhere -products * -path $installationPath -property installationVersion 2>$null
        if ($version) {
            $major = [int]($version.Split('.')[0])
            $line = switch ($major) {
                { $_ -ge 18 } { "2026"; break }
                17 { "2022"; break }
                16 { "2019"; break }
                default { "2022" }
            }
        }
    }
    $generator = switch ([string]$line) {
        "2026" { "Visual Studio 18 2026" }
        "2019" { "Visual Studio 16 2019" }
        default { "Visual Studio 17 2022" }
    }
    return $generator
}

function Find-PhoenixVulkanSdk {
    if ($env:VULKAN_SDK -and (Test-Path (Join-Path $env:VULKAN_SDK "Bin\glslc.exe"))) {
        return $env:VULKAN_SDK
    }
    foreach ($sdkRoot in @("C:\VulkanSDK", "$env:ProgramFiles\VulkanSDK", "${env:ProgramFiles(x86)}\VulkanSDK")) {
        if (-not (Test-Path $sdkRoot)) { continue }
        foreach ($versionDir in (Get-ChildItem $sdkRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
            if (Test-Path (Join-Path $versionDir.FullName "Bin\glslc.exe")) { return $versionDir.FullName }
        }
    }
    return $null
}

if ($env:OS -ne "Windows_NT") {
    throw "Este reparador é exclusivo do Windows."
}
if (-not $env:SystemDrive -or $BuildDir -notmatch '^[A-Za-z]:\\pxb\\phxsd$') {
    throw "Nao foi possivel resolver o diretorio temporario seguro C:\pxb\phxsd."
}
if (-not (Test-Path (Join-Path $Root "ggml\CMakeLists.txt"))) {
    throw "GGML vendorizado ausente. Reextraia o pacote completo da Phoenix."
}

$CMakeExe = Find-PhoenixCMake
if (-not $CMakeExe) { throw "CMake não encontrado. Instale com: winget install Kitware.CMake" }
$Generator = Get-PhoenixVsGenerator
$VulkanSdk = Find-PhoenixVulkanSdk
if (-not $VulkanSdk) { throw "Vulkan SDK não encontrado. Instale com: winget install KhronosGroup.VulkanSDK" }
$env:VULKAN_SDK = $VulkanSdk
$VulkanBin = Join-Path $VulkanSdk "Bin"
$env:Path = "$VulkanBin;$env:Path"

# Se a DLL está ausente, qualquer cache sobrevivente pode pertencer a outra
# pasta/versão do ZIP. Recriar só C:\pxb\phxsd elimina o
# CMAKE_HOME_DIRECTORY antigo e também evita o FTK1011 do FileTracker.
if ($Force -or -not (Test-Path $StableDll)) {
    if (Test-Path $BuildDir) {
        Write-Host "[*] Removendo cache antigo da Phoenix Diffusion..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $BuildDir
    }
}

New-Item -ItemType Directory -Force -Path $ShortBuildRoot | Out-Null
Write-Host "[*] Configurando Phoenix Diffusion com $Generator + Vulkan em $BuildDir..." -ForegroundColor Cyan
& $CMakeExe -S $Root -B $BuildDir -G $Generator -A x64 `
    -DSD_VULKAN=ON `
    -DSD_CUDA=OFF `
    -DSD_HIPBLAS=OFF `
    -DSD_METAL=OFF `
    -DSD_OPENCL=OFF `
    -DSD_BUILD_EXAMPLES=OFF `
    -DSD_WEBP=OFF `
    -DSD_WEBM=OFF `
    -DSD_BUILD_SHARED_LIBS=OFF `
    -DSD_BUILD_SHARED_GGML_LIB=OFF `
    -DGGML_BACKEND_DL=OFF `
    -DGGML_CPU_ALL_VARIANTS=OFF `
    -DGGML_NATIVE=OFF `
    '-DCMAKE_CXX_FLAGS=/bigobj /EHsc' `
    -DPHOENIX_BUILD_BRIDGE=ON `
    -DPHOENIX_STABLE_PROFILE=ON
if ($LASTEXITCODE -ne 0) { throw "CMake falhou ao configurar Phoenix Diffusion (código $LASTEXITCODE)." }

Write-Host "[*] Compilando phoenix_sd_bridge.dll..." -ForegroundColor Cyan
& $CMakeExe --build $BuildDir --config Release --target phoenix_sd_bridge --parallel $Jobs
if ($LASTEXITCODE -ne 0) { throw "CMake falhou ao compilar Phoenix Diffusion (código $LASTEXITCODE)." }

$Dll = Get-ChildItem $BuildDir -Recurse -Filter "phoenix_sd_bridge.dll" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $Dll -or $Dll.Length -le 0) {
    throw "A compilação terminou sem produzir phoenix_sd_bridge.dll."
}

New-Item -ItemType Directory -Force -Path $StableBinDir | Out-Null
Copy-Item -Force $Dll.FullName $StableDll
if (-not (Test-Path $StableDll) -or (Get-Item $StableDll).Length -le 0) {
    throw "A DLL foi compilada, mas não pôde ser promovida para $StableDll."
}

$PythonExe = @(
    (Join-Path $PhoenixRoot ".venv\Scripts\python.exe"),
    (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $PythonExe) {
    Remove-Item -Force $StableDll -ErrorAction SilentlyContinue
    throw "Python não encontrado para validar a ABI da Phoenix Diffusion."
}
& $PythonExe (Join-Path $PSScriptRoot "verify_bridge.py") $StableDll
if ($LASTEXITCODE -ne 0) {
    Remove-Item -Force $StableDll -ErrorAction SilentlyContinue
    throw "A bridge foi compilada, mas falhou ao carregar/validar a ABI (código $LASTEXITCODE)."
}

Write-Host "[PASS] Phoenix Diffusion pronta: $StableDll" -ForegroundColor Green
