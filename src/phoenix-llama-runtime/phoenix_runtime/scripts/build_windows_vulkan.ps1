param(
    [switch]$NativeCpu,
    [string]$BuildDir = "build"
)
$ErrorActionPreference = "Stop"
$RuntimeRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ProjectRoot = (Resolve-Path (Join-Path $RuntimeRoot "..\..")).Path
$BuildPath = Join-Path $RuntimeRoot $BuildDir
Set-Location $RuntimeRoot

function Get-VSInstallPath {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $p = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath -latest 2>$null
        if ($p) { return [string]$p }
    }
    return $null
}

function Enter-MSVCEnvironment {
    if (Get-Command cl.exe -ErrorAction SilentlyContinue) { return $true }
    $vs = Get-VSInstallPath
    if (-not $vs) { return $false }

    # Preferred path: ask VsDevCmd.bat to emit the prepared environment, but
    # do it through a tiny temporary .cmd file.  Passing a full
    # "C:\Program Files (x86)\...\VsDevCmd.bat" command inline to cmd.exe
    # is fragile: the parentheses in Program Files (x86) can be re-parsed by
    # cmd and produce "\\Microsoft was unexpected at this time".  A .cmd
    # wrapper removes that second layer of quoting entirely.
    $vsDevCmd = Join-Path $vs "Common7\Tools\VsDevCmd.bat"
    if (Test-Path $vsDevCmd) {
        $tempCmd = Join-Path $env:TEMP ("phoenix_vsenv_{0}.cmd" -f ([Guid]::NewGuid().ToString('N')))
        try {
            $cmdText = @(
                '@echo off',
                ('call "{0}" -no_logo -arch=x64 -host_arch=x64 >nul' -f $vsDevCmd),
                'if errorlevel 1 exit /b %errorlevel%',
                'set'
            ) -join "`r`n"
            [System.IO.File]::WriteAllText($tempCmd, $cmdText, [System.Text.Encoding]::ASCII)

            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName = $env:ComSpec
            if (-not $psi.FileName) { $psi.FileName = 'cmd.exe' }
            $psi.Arguments = '/d /q /c "' + $tempCmd + '"'
            $psi.UseShellExecute = $false
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.CreateNoWindow = $true

            $proc = New-Object System.Diagnostics.Process
            $proc.StartInfo = $psi
            [void]$proc.Start()
            $stdout = $proc.StandardOutput.ReadToEnd()
            $stderr = $proc.StandardError.ReadToEnd()
            $proc.WaitForExit()

            if ($proc.ExitCode -eq 0 -and $stdout) {
                foreach ($line in ($stdout -split "`r?`n")) {
                    $idx = $line.IndexOf('=')
                    if ($idx -le 0) { continue }
                    $name = $line.Substring(0, $idx)
                    $value = $line.Substring($idx + 1)
                    if ($name) { Set-Item -Path ("Env:" + $name) -Value $value }
                }
                if (Get-Command cl.exe -ErrorAction SilentlyContinue) { return $true }
            } elseif ($stderr) {
                Write-Host ("[!] VsDevCmd falhou: " + $stderr.Trim()) -ForegroundColor Yellow
            }
        } finally {
            Remove-Item -Force $tempCmd -ErrorAction SilentlyContinue
        }
    }

    # Fallback: enter the Visual Studio developer shell in-process.  Dot-source
    # the script so PATH/INCLUDE/LIB changes persist in this PowerShell process.
    $scripts = @(
        (Join-Path $vs "Common7\Tools\Enter-VsDevShell.ps1"),
        (Join-Path $vs "Common7\Tools\Launch-VsDevShell.ps1")
    )
    foreach ($script in $scripts) {
        if (-not (Test-Path $script)) { continue }
        try {
            . $script -SkipAutomaticLocation -Arch amd64 *> $null
        } catch {}
        if (Get-Command cl.exe -ErrorAction SilentlyContinue) { return $true }
    }
    return $false
}

function Resolve-Python {
    $venv = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

Write-Host "Phoenix Llama Runtime Stable - Windows Vulkan build" -ForegroundColor Cyan
$native = if ($NativeCpu) { "ON" } else { "OFF" }
Write-Host "Source: $RuntimeRoot"
Write-Host "Build:  $BuildPath"
Write-Host "GGML_NATIVE=$native"

if (-not (Get-Command cmake.exe -ErrorAction SilentlyContinue) -and -not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "CMake nao encontrado. Rode o instalador da Phoenix ou instale Kitware.CMake."
}
if (-not (Enter-MSVCEnvironment)) {
    throw "MSVC C++ Build Tools nao encontrado/ativado. Rode o instalador da Phoenix."
}
if (-not $env:VULKAN_SDK) {
    $roots = @("C:\VulkanSDK", "${env:ProgramFiles}\VulkanSDK", "${env:ProgramFiles(x86)}\VulkanSDK")
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        $sdk = Get-ChildItem $root -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Where-Object { Test-Path (Join-Path $_.FullName "Bin\glslc.exe") } | Select-Object -First 1
        if ($sdk) { $env:VULKAN_SDK = $sdk.FullName; break }
    }
}
if ($env:VULKAN_SDK) {
    $env:PATH = (Join-Path $env:VULKAN_SDK "Bin") + ";" + $env:PATH
    Write-Host "VULKAN_SDK=$env:VULKAN_SDK" -ForegroundColor DarkGray
} else {
    throw "Vulkan SDK nao encontrado."
}

# Nunca reutiliza um CMakeCache gerado para outro source path.
$cache = Join-Path $BuildPath "CMakeCache.txt"
if (Test-Path $cache) {
    $home = Select-String -Path $cache -Pattern '^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$' -ErrorAction SilentlyContinue | ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -First 1
    if ($home -and ($home.TrimEnd('/','\') -ne $RuntimeRoot.TrimEnd('/','\'))) {
        Write-Host "[!] Cache CMake pertence a outro source; recriando build." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $BuildPath
    }
}

$generatorArgs = @()
if (Get-Command ninja.exe -ErrorAction SilentlyContinue -or Get-Command ninja -ErrorAction SilentlyContinue) {
    $generatorArgs = @('-G','Ninja','-DCMAKE_BUILD_TYPE=Release')
}

& cmake -S $RuntimeRoot -B $BuildPath @generatorArgs -DGGML_VULKAN=ON -DGGML_NATIVE=$native -DGGML_BACKEND_DL=OFF
if ($LASTEXITCODE -ne 0) { throw "CMake configure falhou ($LASTEXITCODE)." }

# Compila os binários realmente consumidos pela Phoenix. O target server puxa as DLLs GGML necessárias.
& cmake --build $BuildPath --config Release --target llama-server llama-mtmd-cli --parallel
if ($LASTEXITCODE -ne 0) { throw "Build do Phoenix Llama Runtime falhou ($LASTEXITCODE)." }

$candidates = @(
    (Join-Path $BuildPath "bin\Release\llama-server.exe"),
    (Join-Path $BuildPath "bin\llama-server.exe")
)
$server = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $server) { throw "llama-server.exe nao encontrado apos build em $BuildPath\bin." }

$python = Resolve-Python
if ($python) {
    $integrity = Join-Path $RuntimeRoot "phoenix_runtime\verify_source_integrity.py"
    if (Test-Path $integrity) {
        & $python $integrity
        if ($LASTEXITCODE -ne 0) { throw "Integridade do source Phoenix falhou." }
    }
    $contract = Join-Path $RuntimeRoot "phoenix_runtime\verify_cli_contract.py"
    if (Test-Path $contract) {
        & $python $contract --server $server
        if ($LASTEXITCODE -ne 0) { throw "Contrato CLI do Phoenix Llama Runtime falhou." }
    }
    $stateTool = Join-Path $RuntimeRoot "phoenix_runtime\runtime_install_state.py"
    if (Test-Path $stateTool) {
        & $python $stateTool write --server $server
        if ($LASTEXITCODE -ne 0) { throw "Falha gravando build stamp do Phoenix Llama Runtime." }
    }
    $bundleTool = Join-Path $RuntimeRoot "phoenix_runtime\package_windows_runtime.py"
    if (Test-Path $bundleTool) {
        $serverDir = Split-Path $server -Parent
        & $python $bundleTool --build-bin $serverDir
        if ($LASTEXITCODE -ne 0) { throw "Falha empacotando bundle Windows do Phoenix Llama Runtime." }
    }
}

& $server --version
if ($LASTEXITCODE -ne 0) { throw "llama-server --version falhou." }
& $server --list-devices
if ($LASTEXITCODE -ne 0) { throw "llama-server --list-devices falhou." }

Write-Host "[OK] Phoenix Llama Runtime Stable compilado e validado: $server" -ForegroundColor Green
exit 0
