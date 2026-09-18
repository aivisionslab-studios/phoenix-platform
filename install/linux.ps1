# install/linux.ps1
# Camada exclusiva do LINUX (Ubuntu/Debian)

 $currentUid = (id -u)
if ($currentUid -ne "0") {
    Write-Host "[X] Este instalador precisa rodar como root." -ForegroundColor Red
    Write-Host "    Rode novamente com: sudo pwsh ./install_phoenix.ps1" -ForegroundColor Yellow
    return @{ 
        Name="Linux"; Version="N/A"; Success=$false; ErrorCode="PX005"; 
        Warnings=@(); Errors=@("Root requerido"); RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date 
    }
}

Write-Host "[OK] Executando como root em: $PWD" -ForegroundColor Green

if (-not (Get-Command apt-get -ErrorAction SilentlyContinue)) {
    return @{ 
        Name="Linux"; Version="N/A"; Success=$false; ErrorCode="PX006"; 
        Warnings=@(); Errors=@("apt-get nao encontrado"); RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date 
    }
}

Write-Host "`n=== INSTALACAO DE PRE-REQUISITOS (APT) ===" -ForegroundColor Cyan
apt-get update -y 2>&1 | Out-Null

 $AptPackages = @(
    # CORREÇÃO ARQUITETURAL: Git foi movido pro install_phoenix.ps1 (bootstrap).
    @{Name="Docker Engine"; Pkg="docker.io"; Cmd="docker"},
    @{Name="Docker Compose Plugin"; Pkg="docker-compose-v2"; Cmd=$null},
    @{Name="Build Essential"; Pkg="build-essential"; Cmd="gcc"},
    @{Name="Python3 do sistema + pip"; Pkg="python3 python3-pip"; Cmd="python3"},
    @{Name="Vulkan Tools"; Pkg="vulkan-tools"; Cmd="vulkaninfo"},
    @{Name="Mesa Vulkan Drivers (RADV)"; Pkg="mesa-vulkan-drivers"; Cmd=$null},
    @{Name="CMake (Para compilar IA)"; Pkg="cmake"; Cmd="cmake"},
    @{Name="FFmpeg"; Pkg="ffmpeg"; Cmd="ffmpeg"},
    @{Name="Tesseract OCR"; Pkg="tesseract-ocr"; Cmd="tesseract"},
    @{Name="NodeJS + npm"; Pkg="nodejs npm"; Cmd="node"},
    @{Name="lm-sensors"; Pkg="lm-sensors"; Cmd="sensors"},
    @{Name="pciutils"; Pkg="pciutils"; Cmd="lspci"}
)

 $warnings = @()

foreach ($pkg in $AptPackages) {
    $already = $false
    if ($pkg.Cmd) { $already = [bool](Get-Command $pkg.Cmd -ErrorAction SilentlyContinue) }
    if ($already) {
        Write-Host "[OK] $($pkg.Name) ja instalado." -ForegroundColor Green
    } else {
        Write-Host "[*] Instalando $($pkg.Name)..." -ForegroundColor Yellow
        $pkgList = $pkg.Pkg -split " "
        apt-get install -y @pkgList 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $warnings += "$($pkg.Name): apt retornou codigo $LASTEXITCODE" }
    }
}

# =====================================================================
# PYTHON RUNTIME DA PHOENIX (separado do Python do sistema)
# =====================================================================
Write-Host "`n=== PYTHON RUNTIME DA PHOENIX ===" -ForegroundColor Cyan

$env:PHOENIX_PYTHON = $null
$phoenixPythonCandidates = @("python3.12", "python3.13", "python3.11", "python3.10")

foreach ($candidate in $phoenixPythonCandidates) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }

    try {
        $versionText = (& $cmd.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
        $version = [version]$versionText
        if ($version -ge [version]"3.10" -and $version -lt [version]"3.14") {
            $env:PHOENIX_PYTHON = $cmd.Source
            break
        }
    } catch {}
}

if (-not $env:PHOENIX_PYTHON) {
    foreach ($minor in @("3.12", "3.13", "3.11", "3.10")) {
        $pkg = "python$minor"
        $venvPkg = "python$minor-venv"

        & apt-cache show $pkg *> $null
        if ($LASTEXITCODE -ne 0) { continue }

        Write-Host "[*] Instalando Python $minor para o runtime da Phoenix via APT..." -ForegroundColor Yellow
        & apt-get install -y $pkg $venvPkg 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) { continue }

        $cmd = Get-Command "python$minor" -ErrorAction SilentlyContinue
        if ($cmd) {
            $env:PHOENIX_PYTHON = $cmd.Source
            break
        }
    }
}

# Ubuntu 26.04 usa Python 3.14 como padrão e pode não oferecer 3.10-3.13
# nos repositórios configurados. Nesse caso a Phoenix instala um CPython
# 3.12 privado em /opt/phoenix/python312, sem alterar /usr/bin/python3.
if (-not $env:PHOENIX_PYTHON) {
    $privatePythonRoot = "/opt/phoenix/python312"
    $privatePythonExe = Join-Path $privatePythonRoot "bin/python3.12"

    if (Test-Path $privatePythonExe) {
        try {
            $privateVersionText = (& $privatePythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
            $privateVersion = [version]$privateVersionText
            if ($privateVersion -ge [version]"3.10" -and $privateVersion -lt [version]"3.14") {
                $env:PHOENIX_PYTHON = $privatePythonExe
                Write-Host "[OK] Runtime Python privado da Phoenix encontrado: $privatePythonExe (v$privateVersionText)" -ForegroundColor Green
            }
        } catch {
            Write-Host "[!] Runtime Python privado existente está inválido; será reconstruído." -ForegroundColor Yellow
        }
    }

    if (-not $env:PHOENIX_PYTHON) {
        $pythonSourceVersion = "3.12.14"
        $pythonSourceUrl = "https://www.python.org/ftp/python/$pythonSourceVersion/Python-$pythonSourceVersion.tar.xz"
        $pythonBuildRoot = "/tmp/phoenix-python-build"
        $pythonTarball = Join-Path $pythonBuildRoot "Python-$pythonSourceVersion.tar.xz"
        $pythonSourceDir = Join-Path $pythonBuildRoot "Python-$pythonSourceVersion"

        Write-Host "[*] Nenhum Python 3.10-3.13 disponível via APT." -ForegroundColor Yellow
        Write-Host "[*] Instalando Python $pythonSourceVersion privado da Phoenix em $privatePythonRoot ..." -ForegroundColor Yellow

        $pythonBuildPackages = @(
            "wget",
            "ca-certificates",
            "xz-utils",
            "libssl-dev",
            "zlib1g-dev",
            "libbz2-dev",
            "libreadline-dev",
            "libsqlite3-dev",
            "libffi-dev",
            "liblzma-dev",
            "libncurses-dev",
            "uuid-dev"
        )

        & apt-get install -y @pythonBuildPackages 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) {
            return @{
                Name="Linux"; Version="N/A"; Success=$false; ErrorCode="PX007";
                Warnings=$warnings;
                Errors=@("Falha ao instalar dependências necessárias para compilar o Python privado da Phoenix.");
                RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date
            }
        }

        if (Test-Path $pythonBuildRoot) {
            Remove-Item -Recurse -Force $pythonBuildRoot -ErrorAction SilentlyContinue
        }
        New-Item -ItemType Directory -Force -Path $pythonBuildRoot | Out-Null
        New-Item -ItemType Directory -Force -Path (Split-Path $privatePythonRoot -Parent) | Out-Null

        Write-Host "[*] Baixando CPython $pythonSourceVersion oficial..." -ForegroundColor Yellow
        & wget -q --show-progress -O $pythonTarball $pythonSourceUrl 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $pythonTarball)) {
            return @{
                Name="Linux"; Version="N/A"; Success=$false; ErrorCode="PX007";
                Warnings=$warnings;
                Errors=@("Falha ao baixar CPython $pythonSourceVersion de python.org.");
                RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date
            }
        }

        Write-Host "[*] Extraindo CPython $pythonSourceVersion..." -ForegroundColor Yellow
        & tar -xJf $pythonTarball -C $pythonBuildRoot 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $pythonSourceDir)) {
            return @{
                Name="Linux"; Version="N/A"; Success=$false; ErrorCode="PX007";
                Warnings=$warnings;
                Errors=@("Falha ao extrair o código-fonte do CPython $pythonSourceVersion.");
                RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date
            }
        }

        Push-Location $pythonSourceDir
        try {
            Write-Host "[*] Configurando CPython $pythonSourceVersion..." -ForegroundColor Yellow
            & ./configure "--prefix=$privatePythonRoot" "--with-ensurepip=install" 2>&1 | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "configure do CPython retornou código $LASTEXITCODE"
            }

            $buildJobs = 1
            if (Get-Command nproc -ErrorAction SilentlyContinue) {
                $buildJobsText = (& nproc).Trim()
                if ($buildJobsText -match '^\d+$') { $buildJobs = [int]$buildJobsText }
            }

            Write-Host "[*] Compilando CPython com $buildJobs threads..." -ForegroundColor Yellow
            & make "-j$buildJobs" 2>&1 | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "make do CPython retornou código $LASTEXITCODE"
            }

            Write-Host "[*] Instalando runtime privado com make altinstall..." -ForegroundColor Yellow
            & make altinstall 2>&1 | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "make altinstall retornou código $LASTEXITCODE"
            }
        } catch {
            Pop-Location
            return @{
                Name="Linux"; Version="N/A"; Success=$false; ErrorCode="PX007";
                Warnings=$warnings;
                Errors=@("Falha ao compilar/instalar Python privado da Phoenix: $($_.Exception.Message)");
                RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date
            }
        }
        Pop-Location

        if (-not (Test-Path $privatePythonExe)) {
            return @{
                Name="Linux"; Version="N/A"; Success=$false; ErrorCode="PX007";
                Warnings=$warnings;
                Errors=@("Compilação terminou, mas $privatePythonExe não foi criado.");
                RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date
            }
        }

        try {
            & $privatePythonExe -m ensurepip --upgrade 2>&1 | Out-Host
            & $privatePythonExe -m pip install --upgrade pip setuptools wheel 2>&1 | Out-Host
        } catch {
            $warnings += "Python privado instalado, mas atualização inicial do pip/setuptools/wheel falhou: $($_.Exception.Message)"
        }

        $env:PHOENIX_PYTHON = $privatePythonExe
        $privateFullVersion = (& $privatePythonExe -c "import sys; print(sys.version.split()[0])").Trim()
        Write-Host "[OK] Python privado da Phoenix instalado: $privatePythonExe (v$privateFullVersion)" -ForegroundColor Green

        Remove-Item -Recurse -Force $pythonBuildRoot -ErrorAction SilentlyContinue
    }
}

if (-not $env:PHOENIX_PYTHON) {
    return @{
        Name="Linux"; Version="N/A"; Success=$false; ErrorCode="PX007";
        Warnings=$warnings;
        Errors=@("Nenhum Python compativel com a Phoenix foi encontrado. Necessario Python >=3.10 e <3.14 (preferencia: 3.12).");
        RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date
    }
}

$phoenixPythonVersion = (& $env:PHOENIX_PYTHON -c "import sys; print(sys.version.split()[0])").Trim()
Write-Host "[OK] Python da Phoenix: $env:PHOENIX_PYTHON (v$phoenixPythonVersion)" -ForegroundColor Green

Write-Host "`n=== DOCKER ENGINE ===" -ForegroundColor Cyan
# PHX-FIX (auditoria 2026-08-20, "Runtime policy / LM Studio opcional /
# portas corretas" - Seção 7): Docker e OPCIONAL (só serve pros
# containers Ollama/Open WebUI/SearXNG, todos opcionais - ver
# common.ps1). Antes, "& docker info" era chamado sem checar se o
# comando "docker" existe - numa máquina sem Docker instalado, isso
# levanta um erro TERMINANTE (comando não encontrado) que abortaria o
# módulo Linux inteiro, e com ele o boot inteiro da Phoenix. Agora só
# tenta usar o Docker Engine se o comando existir; se não existir, é só
# um aviso - llama.cpp/Aviary nativos não dependem disso.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "[WARN] Docker nao encontrado. Recursos opcionais baseados em container (Ollama, Open WebUI, SearXNG) nao serao iniciados." -ForegroundColor Yellow
    Write-Host "[OK] Phoenix Engine continua operando com llama.cpp nativo." -ForegroundColor Green
    $warnings += "Docker nao encontrado - recursos opcionais baseados em container nao serao provisionados. Phoenix continua com llama.cpp nativo."
} else {
    & docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        if (Get-Command systemctl -ErrorAction SilentlyContinue) {
            systemctl enable --now docker 2>&1 | Out-Null
        }
        $dockerReady = $false
        for ($i = 1; $i -le 20; $i++) {
            Start-Sleep -Seconds 2
            & docker info 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break }
        }
        if (-not $dockerReady) { $warnings += "Docker daemon nao respondeu (recurso opcional - Ollama/Open WebUI/SearXNG nao vao subir, Phoenix continua com llama.cpp nativo)" }
    }
}

Write-Host "`n=== ATALHO DE APLICATIVO (MENU + AREA DE TRABALHO) ===" -ForegroundColor Cyan
try {
    $iconPath = Join-Path $PhoenixRoot "assets/phoenix_engine.png"
    $launcherPath = Join-Path $PhoenixRoot "Iniciar_Phoenix.sh"

    # CORREÇÃO CRÍTICA: o script inteiro roda como root (via sudo, exigido
    # no topo deste arquivo). $env:HOME aqui aponta pra "/root", NAO pra
    # pasta do usuario real - o atalho seria criado num lugar que o usuario
    # nunca ve. $env:SUDO_USER e setado automaticamente pelo sudo com o
    # nome do usuario original; resolvemos a home real dele via getent.
    $targetUser = $env:SUDO_USER
    $targetHome = $null

    if ($targetUser) {
        $passwdEntry = getent passwd $targetUser 2>$null
        if ($passwdEntry) {
            $targetHome = ($passwdEntry -split ":")[5]
        }
    }
    if (-not $targetHome) {
        # Nao rodou via sudo (ex: ja e root de verdade) - usa $env:HOME mesmo.
        $targetUser = $env:USER
        $targetHome = $env:HOME
        Write-Host "[!] SUDO_USER nao definido - usando HOME atual ($targetHome). Se isso nao for a pasta do usuario certo, o atalho pode nao aparecer." -ForegroundColor Yellow
    }

    if ((Test-Path $iconPath) -and (Test-Path $launcherPath) -and $targetHome -and (Test-Path $targetHome)) {
        chmod +x $launcherPath 2>&1 | Out-Null

        $desktopEntry = @"
[Desktop Entry]
Type=Application
Name=Phoenix Engine
Comment=Hardware nao morre - so espera o software certo.
Exec=$launcherPath
Icon=$iconPath
Terminal=true
Categories=Development;Utility;
"@

        $createdPaths = @()

        # Menu de aplicativos (aparece na busca do GNOME/KDE etc.)
        $appsDir = Join-Path $targetHome ".local/share/applications"
        if (-not (Test-Path $appsDir)) { New-Item -ItemType Directory -Force -Path $appsDir | Out-Null }
        $appsEntryPath = Join-Path $appsDir "phoenix-engine.desktop"
        Set-Content -Path $appsEntryPath -Value $desktopEntry -Encoding UTF8
        chmod +x $appsEntryPath 2>&1 | Out-Null
        $createdPaths += $appsEntryPath

        # Area de Trabalho - roda xdg-user-dir COMO O USUARIO REAL (via
        # "su -l"), pra respeitar o nome localizado da pasta (ex: "Área de
        # Trabalho" em PT-BR) - rodando como root, xdg-user-dir nao teria
        # o contexto/config correto do usuario.
        $desktopDir = $null
        if (Get-Command xdg-user-dir -ErrorAction SilentlyContinue) {
            $xdgDesktop = (su -l $targetUser -c "xdg-user-dir DESKTOP" 2>$null).Trim()
            if ($xdgDesktop -and (Test-Path $xdgDesktop)) { $desktopDir = $xdgDesktop }
        }
        if (-not $desktopDir) {
            $fallback = Join-Path $targetHome "Desktop"
            if (Test-Path $fallback) { $desktopDir = $fallback }
        }

        if ($desktopDir) {
            $desktopEntryPath = Join-Path $desktopDir "phoenix-engine.desktop"
            Set-Content -Path $desktopEntryPath -Value $desktopEntry -Encoding UTF8
            chmod +x $desktopEntryPath 2>&1 | Out-Null
            $createdPaths += $desktopEntryPath
            # Sem isso o GNOME mostra "Launcher nao confiavel" e exige
            # clique manual em "Confiar e Iniciar" na primeira vez.
            if (Get-Command gio -ErrorAction SilentlyContinue) {
                gio set $desktopEntryPath "metadata::trusted" true 2>&1 | Out-Null
            }
        }

        # Como tudo foi criado como root, devolve a posse pro usuario real -
        # senao ele nem consegue apagar/editar o proprio atalho depois.
        foreach ($p in $createdPaths) {
            chown "${targetUser}:${targetUser}" $p 2>&1 | Out-Null
        }

        if (Get-Command update-desktop-database -ErrorAction SilentlyContinue) {
            update-desktop-database $appsDir 2>&1 | Out-Null
        }

        $suffix = if ($desktopDir) { " e na Area de Trabalho" } else { "" }
        Write-Host "[OK] Atalho criado no menu de aplicativos$suffix (usuario: $targetUser)." -ForegroundColor Green
    } else {
        Write-Host "[!] assets/phoenix_engine.png, Iniciar_Phoenix.sh ou pasta do usuario nao encontrados - atalho nao criado." -ForegroundColor Yellow
        $warnings += "Atalho de aplicativo nao criado (icone, launcher ou home do usuario ausente)."
    }
} catch {
    Write-Host "[!] Falha ao criar atalho: $($_.Exception.Message)" -ForegroundColor Yellow
    $warnings += "Falha ao criar atalho de aplicativo: $($_.Exception.Message)"
}

# Contrato de Retorno Estrito
return @{
    Name = "Linux"
    Version = "1.0.0"
    Success = $true
    ErrorCode = ""
    Warnings = $warnings
    Errors = @()
    RestartRequired = $false
    Artifacts = @("python3", $env:PHOENIX_PYTHON, "git", "docker", "node", "cmake")
    Timestamp = Get-Date
}