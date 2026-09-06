# install/common.ps1
# =====================================================================
# PHOENIX COMMON 7.1 — Enterprise Bootstrap (Windows + Multi-distro Linux)
# =====================================================================

 $env:PHOENIX_LLM_DEVICE   = "CPU"
 $env:PHOENIX_IMAGE_DEVICE = "GPU"
 $env:PHOENIX_LLM_GPU_DEVICE = "Vulkan0"
 $env:PHOENIX_DOCUMENT_LLM_POLICY = "cpu"
 # PHX-FIX (31/08): ver comentário completo em install_phoenix.ps1 - "999"
 # (full offload) é a pior combinação já documentada nesta GPU; "1" é o
 # valor testado que restaurou correctness junto do override fixo no
 # código (output.weight=CPU).
 $env:PHOENIX_DOCUMENT_GPU_NGL = "1"
 $env:PHOENIX_DOCUMENT_GPU_DEVICE = "Vulkan0"
 $env:PHOENIX_TTS_DEVICE = "CPU"
 $env:PHOENIX_LLM_NGL      = "0"

if (Test-Path Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

if (-not (Get-Command Pause -ErrorAction SilentlyContinue)) {
    function Pause {
        Write-Host "`nPressione Enter para continuar..." -ForegroundColor DarkGray
        Read-Host | Out-Null
    }
}

Set-Location $PhoenixRoot
Write-Host "[OK] Diretorio de trabalho: $PWD" -ForegroundColor Green

 $PhoenixWorkspace   = $null
 $PhoenixStorageData = $null

 # PHX-FIX (2026-08-26): ProgramData existe apenas no Windows.
 # Mantém exatamente o caminho legado no Windows e usa /etc/phoenix no Linux,
 # alinhado ao storage_scanner.ps1.
 if ($IsWindows) {
     $_phoenixConfigRoot = Join-Path $env:ProgramData "Phoenix"
 } elseif ($IsLinux) {
     $_phoenixConfigRoot = "/etc/phoenix"
 } else {
     # Fallback defensivo para plataformas futuras/PowerShell sem flags esperadas.
     $_phoenixConfigRoot = Join-Path $HOME ".phoenix"
 }

 $_storagePath = Join-Path $_phoenixConfigRoot "storage.json"
if (Test-Path $_storagePath) {
    try {
        $PhoenixStorageData = Get-Content $_storagePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $PhoenixWorkspace   = $PhoenixStorageData.workspace
        if ($PhoenixWorkspace) {
            Write-Host "[OK] storage.json lido: workspace = $PhoenixWorkspace" -ForegroundColor Green
        }
    } catch {
        Write-Host "[!] Falha ao ler storage.json: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

 $failContract = {
    param([string]$errMsg, [string]$code)
    return @{ Name="Common"; Version="N/A"; Success=$false; ErrorCode=$code; Warnings=@(); Errors=@($errMsg); RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date }
}

# PHX-NEW (auditoria 2026-08-20, "Runtime policy / LM Studio opcional /
# portas corretas" - Seção 7): antes deste array, o retorno de sucesso no
# fim deste script sempre mandava `Warnings=@()` fixo, mesmo quando algo
# opcional (Docker ausente, containers pulados) tinha acontecido no meio
# do caminho - o relatório final nunca sabia disso. Agora os avisos reais
# de componentes opcionais são acumulados aqui e entram no contrato de
# retorno no final.
 $commonWarnings = @()

function Update-SessionPath {
    if ($IsWindows) {
        $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $userPath    = [System.Environment]::GetEnvironmentVariable("Path", "User")
        $env:Path = "$machinePath;$userPath"
    } elseif ($IsLinux) {
        $candidatePaths = @("/usr/local/bin", "/usr/local/sbin", "/usr/bin", "/usr/sbin", "/bin", "/sbin", "$HOME/.local/bin")
        $sep = ':'
        $current = $env:Path -split [regex]::Escape($sep)
        foreach ($p in $candidatePaths) {
            if ((Test-Path $p) -and ($current -notcontains $p)) {
                $env:Path = "$env:Path$sep$p"
                $current = $env:Path -split [regex]::Escape($sep)
            }
        }
    }
}

# =====================================================================
# PHX-RECREATE POLICY
# Runtime/build/processos gerenciados pela Phoenix sao recriados em toda
# execucao do instalador. Dados persistentes NAO sao apagados.
# =====================================================================

function Get-PhoenixPortOwner {
    param([int]$Port)

    if ($IsWindows) {
        try {
            $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $conn) { return $null }
            $pidValue = [int]$conn.OwningProcess
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
            return @{
                Pid = $pidValue
                CommandLine = if ($proc) { [string]$proc.CommandLine } else { "" }
                Executable = if ($proc) { [string]$proc.ExecutablePath } else { "" }
                Cwd = ""
            }
        } catch { return $null }
    }

    if ($IsLinux) {
        try {
            $pidValue = $null
            if (Get-Command lsof -ErrorAction SilentlyContinue) {
                $rawPid = (& lsof -t "-iTCP:$Port" -sTCP:LISTEN 2>$null | Select-Object -First 1)
                if ($rawPid -and "$rawPid" -match '^\d+$') { $pidValue = [int]$rawPid }
            }
            if (-not $pidValue -and (Get-Command ss -ErrorAction SilentlyContinue)) {
                $ssLine = (& ss -ltnp "sport = :$Port" 2>$null | Select-Object -Skip 1 -First 1)
                if ($ssLine -and "$ssLine" -match 'pid=(\d+)') { $pidValue = [int]$Matches[1] }
            }
            if (-not $pidValue) { return $null }

            $cmdLine = ""
            $cwd = ""
            $cmdPath = "/proc/$pidValue/cmdline"
            $cwdPath = "/proc/$pidValue/cwd"
            if (Test-Path $cmdPath) {
                try {
                    $bytes = [System.IO.File]::ReadAllBytes($cmdPath)
                    $cmdLine = ([System.Text.Encoding]::UTF8.GetString($bytes) -replace "`0", " ").Trim()
                } catch {}
            }
            if (Test-Path $cwdPath) {
                try { $cwd = (& readlink -f $cwdPath 2>$null).Trim() } catch {}
            }
            return @{ Pid=$pidValue; CommandLine=$cmdLine; Executable=""; Cwd=$cwd }
        } catch { return $null }
    }

    return $null
}

function Test-IsPhoenixManagedProcess {
    param([hashtable]$Owner, [string[]]$ExpectedMarkers = @())
    if (-not $Owner) { return $false }

    $rootNormalized = ([string]$PhoenixRoot).Replace('\','/').ToLowerInvariant()
    $haystack = ("$($Owner.CommandLine) $($Owner.Executable) $($Owner.Cwd)").Replace('\','/').ToLowerInvariant()

    if ($rootNormalized -and $haystack.Contains($rootNormalized)) { return $true }
    foreach ($marker in $ExpectedMarkers) {
        if ($marker -and $haystack.Contains($marker.ToLowerInvariant())) { return $true }
    }
    return $false
}

function Stop-PhoenixManagedPort {
    param([int]$Port, [string]$Name, [string[]]$ExpectedMarkers = @())

    $owner = Get-PhoenixPortOwner -Port $Port
    if (-not $owner) {
        Write-Host "[OK] Porta $Port livre para $Name." -ForegroundColor DarkGray
        return $true
    }

    if (-not (Test-IsPhoenixManagedProcess -Owner $owner -ExpectedMarkers $ExpectedMarkers)) {
        Write-Host "[X] Porta $Port ocupada por processo NAO gerenciado pela Phoenix (PID $($owner.Pid))." -ForegroundColor Red
        Write-Host "    Comando: $($owner.CommandLine)" -ForegroundColor DarkYellow
        return $false
    }

    Write-Host "[*] Encerrando instancia anterior de $Name na porta $Port (PID $($owner.Pid))..." -ForegroundColor Yellow
    try {
        Stop-Process -Id $owner.Pid -Force -ErrorAction Stop
    } catch {
        Write-Host "[X] Nao foi possivel encerrar PID $($owner.Pid): $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }

    for ($i=0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 250
        if (-not (Get-PhoenixPortOwner -Port $Port)) {
            Write-Host "[OK] Porta $Port liberada." -ForegroundColor Green
            return $true
        }
    }
    Write-Host "[X] Porta $Port continuou ocupada." -ForegroundColor Red
    return $false
}

function Add-ToSessionPath {
    param([string]$Dir)
    if ([string]::IsNullOrWhiteSpace($Dir) -or -not (Test-Path $Dir)) { return $false }
    $normalized = $Dir.TrimEnd('\', '/')
    $sep = if ($IsWindows) { ';' } else { ':' }
    $current = $env:Path -split [regex]::Escape($sep)
    if ($current -notcontains $normalized) {
        $env:Path = "$env:Path$sep$normalized"
        return $true
    }
    return $false
}

function Resolve-PhoenixGit {
    Write-Host "`n=== RESOLUÇÃO DO GIT ===" -ForegroundColor Cyan
    if (Get-Command git -ErrorAction SilentlyContinue) { return $true }
    Write-Host "[!] Git não encontrado. Instalando..." -ForegroundColor Yellow
    if ($IsWindows) {
        & winget install --id Git.Git -e --source winget --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Host
        Update-SessionPath
        if (Get-Command git -ErrorAction SilentlyContinue) { return $true }
    }
    return $false
}

function Get-LatestWingetPythonId {
    try {
        $raw = & winget search --id "Python.Python.3." --source winget 2>&1
        $ids = [regex]::Matches(($raw -join "`n"), "Python\.Python\.3\.\d+") | ForEach-Object { $_.Value } | Select-Object -Unique
        if (-not $ids -or $ids.Count -eq 0) { return $null }
        return $ids | Sort-Object { [int]($_ -replace 'Python\.Python\.3\.', '') } -Descending | Select-Object -First 1
    } catch { return $null }
}

function Resolve-PhoenixPython {
    Write-Host "`n=== RESOLUÇÃO DO PYTHON ===" -ForegroundColor Cyan

    if ($env:PHOENIX_PYTHON) {
        $explicit = Get-Command $env:PHOENIX_PYTHON -ErrorAction SilentlyContinue
        if ($explicit) {
            try {
                $vText = (& $explicit.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
                $v = [version]$vText
                if ($v -ge [version]"3.10" -and $v -lt [version]"3.14") {
                    Write-Host "[OK] Usando Python selecionado para a Phoenix: $($explicit.Source) (v$vText)" -ForegroundColor Green
                    return $explicit.Source
                }
            } catch {}
        }
    }

    if ($IsWindows) {
        Update-SessionPath

        # PHX-FIX 2026-08-26: Kokoro/onnx stack atual exige Python <3.14.
        # Nao usar simplesmente "python" do PATH, porque uma maquina com 3.14
        # faria a .venv nova nascer incompatível em toda reinstalacao.
        $windowsCandidates = @(
            "python3.12",
            "python3.13",
            "python3.11",
            "python3.10",
            "python"
        )

        foreach ($candidate in $windowsCandidates) {
            $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
            if (-not $cmd) { continue }

            try {
                $vText = (& $cmd.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
                $v = [version]$vText
                if ($v -ge [version]"3.10" -and $v -lt [version]"3.14") {
                    Write-Host "[OK] Python Windows compativel encontrado: $($cmd.Source) (v$vText)" -ForegroundColor Green
                    return $cmd.Source
                }
            } catch {}
        }

        Write-Host "[!] Nenhum Python Windows compativel (>=3.10,<3.14) encontrado. Instalando Python 3.12..." -ForegroundColor Yellow
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            & winget install -e --id "Python.Python.3.12" --scope machine --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Host
            Update-SessionPath

            # O alias python3.12 pode nao existir imediatamente; procura via
            # py launcher e pelos caminhos de instalacao conhecidos.
            $cmd = Get-Command python3.12 -ErrorAction SilentlyContinue
            if ($cmd) {
                return $cmd.Source
            }

            $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
            if ($pyLauncher) {
                try {
                    $resolved = (& $pyLauncher.Source -3.12 -c "import sys; print(sys.executable)").Trim()
                    if ($resolved -and (Test-Path $resolved)) { return $resolved }
                } catch {}
            }

            $knownRoots = @(
                "$env:ProgramFiles\Python312\python.exe",
                "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
            )
            foreach ($candidatePath in $knownRoots) {
                if ($candidatePath -and (Test-Path $candidatePath)) { return $candidatePath }
            }
        }

        return $null
    }

    if ($IsLinux) {
        foreach ($candidate in @("python3.12", "python3.13", "python3.11", "python3.10")) {
            $linuxPython = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($linuxPython) { return $linuxPython.Source }
        }

        Write-Host "[!] Nenhum Python Linux compatível (>=3.10,<3.14) foi encontrado." -ForegroundColor Yellow
        return $null
    }

    return $null
}

function Test-PhoenixPythonBinary {
    param([string]$PythonExe)
    if (-not $PythonExe) { return $false }
    try {
        $versionOutput = & $PythonExe --version 2>&1
        if ($LASTEXITCODE -ne 0) { return $false }
        return $true
    } catch { return $false }
}

function Test-PhoenixVenvModule {
    param([string]$PythonExe)
    try {
        & $PythonExe -c "import venv" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
    } catch {}
    if ($IsLinux) {
        $sudo = if (Get-Command sudo -ErrorAction SilentlyContinue) { "sudo" } else { "" }
        if (Get-Command apt-get -ErrorAction SilentlyContinue) {
            if ($sudo) { & sudo apt-get install -y python3-venv 2>&1 | Out-Host } else { & apt-get install -y python3-venv 2>&1 | Out-Host }
        }
    }
    try {
        & $PythonExe -c "import venv" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
    } catch {}
    return $false
}

if (-not (Resolve-PhoenixGit)) { return (& $failContract "Git não foi encontrado e não pode ser instalado." "PX020") }
if (-not (Test-Path ".\api_server.py")) { return (& $failContract "api_server.py nao encontrado" "PX010") }

# PHX-FIX: Limpeza automática do ChromaDB para resolver mismatch de dimensões (768 vs 384)
 $_chromaDbPath = Join-Path $PhoenixRoot "data\chroma_db"
if (Test-Path $_chromaDbPath) {
    Write-Host "[*] Limpando cache do ChromaDB (mismatch de dimensões)..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $_chromaDbPath -ErrorAction SilentlyContinue
}

 $VenvDir      = ".venv"
 $VenvActivate = if ($IsWindows) { Join-Path $VenvDir "Scripts\Activate.ps1" } else { Join-Path $VenvDir "bin/Activate.ps1" }
 $VenvPython   = if ($IsWindows) { Join-Path $VenvDir "Scripts\python.exe" } else { Join-Path $VenvDir "bin/python" }

# PHX-RECREATE: .venv e descartavel e e recriada em TODA instalacao.
if (Test-Path $VenvDir) {
    Write-Host "[*] PHX-RECREATE: removendo .venv anterior..." -ForegroundColor Yellow
    try {
        Remove-Item -Recurse -Force $VenvDir -ErrorAction Stop
    } catch {
        return (& $failContract "Nao foi possivel remover a .venv anterior: $($_.Exception.Message)" "PX024")
    }
}

if (-not (Test-Path $VenvActivate)) {
    $pythonExeToUse = Resolve-PhoenixPython
    if (-not $pythonExeToUse) { return (& $failContract "Python não encontrado." "PX019") }
    if (-not (Test-PhoenixPythonBinary -PythonExe $pythonExeToUse)) { return (& $failContract "Interpretador corrompido." "PX023") }
    if (-not (Test-PhoenixVenvModule -PythonExe $pythonExeToUse)) { return (& $failContract "Módulo venv indisponível." "PX022") }
    & $pythonExeToUse -m venv $VenvDir 2>&1 | Out-Host
    if (-not (Test-Path $VenvActivate)) { return (& $failContract "Falha ao criar venv." "PX021") }
}
. $VenvActivate

Write-Host "`n=== DEPENDÊNCIAS PYTHON COMUNS ===" -ForegroundColor Cyan
& python -m pip install --upgrade pip 2>&1 | Out-Host
# PHX-NEW: pymupdf/pymupdf4llm (PDF), python-docx (DOCX), openpyxl (XLSX)
# e python-pptx (PPTX) - cobrem os 4 formatos que a Document Engine lê e
# edita (ver phoenix_kernel/documents/engine.py). Tudo puro Python, sem
# container Docker novo.
# Fonte única de dependências e versões mínimas validadas pela suíte.
& python -m pip install -r (Join-Path $PhoenixRoot "requirements.txt") 2>&1 | Out-Host

# PHX-FIX (achado real do usuário 2026-08-28, na sequência da auditoria de
# segurança/qualidade completa: pediu pra rodar `pytest` numa correção
# entregue e tomou "No module named 'pytest'" - mesmo com a pasta TESTS/
# tendo mais de 250 testes, incluindo vários adicionados por esta própria
# auditoria). Causa raiz confirmada (não suposta): `pytest`/`pytest-asyncio`
# nunca apareceram em NENHUM install/*.ps1 nem em requirements.txt - e,
# diferente de google-auth/cryptography/huggingface_hub (que PARECEM
# ausentes mas na prática já chegam como dependência transitiva de
# chromadb/google-cloud-firestore - verificado com
# `pip install --dry-run --report` antes de mexer aqui, pra não "corrigir"
# algo que já funcionava), pytest e pytest-asyncio NÃO são dependência de
# ninguém da lista acima - são só ferramenta de teste, então nenhum pacote
# de produção os traz de brinde. Resultado real: TODA instalação feita via
# install/common.ps1 (a .venv é recriada do zero em toda instalação -
# ver PHX-RECREATE acima) ficava sem conseguir rodar a suíte de testes do
# próprio projeto, obrigando a instalar isso manualmente toda vez.
Write-Host "[*] Instalando dependências de teste (pytest)..." -ForegroundColor Cyan
& python -m pip install pytest pytest-asyncio 2>&1 | Out-Host

# PHX-FIX (2026-08-23, achado real do usuário: rodou o instalador oficial,
# abriu "Documento -> Audiolivro" e tomou "No module named 'py3langid'" -
# Kokoro-82M virou o motor de voz PADRÃO de toda a Phoenix desde a v47
# (phoenix_kernel/runtime/drivers/kokoro_tts.py e documents/audiobook.py),
# e requirements.txt já lista os pacotes certos há duas versões... mas
# requirements.txt NUNCA foi lido por este instalador (ver comentário no
# topo do próprio arquivo) - o `pip install` de verdade que roda na máquina
# do usuário é só a linha acima, que nunca ganhou os pacotes do Kokoro. Ou
# seja: todo mundo que rodou install/common.ps1 desde a v46/v47 instalou a
# Phoenix SEM o motor de voz funcionar, mesmo com o código já certo -
# funcionava só no ambiente de teste desta auditoria porque os pacotes
# foram instalados manualmente ali, não pelo instalador real.
Write-Host "[*] Instalando dependências do motor de voz Kokoro-82M (TTS + detecção de idioma)..." -ForegroundColor Cyan
& python -m pip install "kokoro-onnx>=0.6.1" "phonemizer>=3.4.0" "espeakng-loader>=0.2.4" "py3langid>=0.3.0" "soundfile>=0.14.0" 2>&1 | Out-Host

# PHX-NEW (2026-08-23, pedido do usuário: "esta rodando via cpu, mas
# podemos pensar em rodar via gpu, nao?"): onnxruntime (a peça que executa
# o modelo em si) vira uma escolha separada em vez de fixa - kokoro-onnx já
# troca sozinho pra GPU quando detecta uma distribuição acelerada instalada
# (ver kokoro_onnx/session.py::resolve_providers(), lido de verdade nesta
# auditoria - zero mudança necessária no nosso kokoro_tts.py). onnxruntime
# normal e onnxruntime-directml são MUTUAMENTE EXCLUSIVOS (mesmo módulo
# Python) - por isso desinstala o que não for usado antes de instalar o
# escolhido, evitando metadados de pacote furados de uma troca futura.
# PHOENIX_TTS_DEVICE é "CPU" por padrão (ver install_phoenix.ps1) - troque
# pra "GPU" lá se quiser tentar a variante DirectML (Windows + qualquer GPU
# DX12, inclusive AMD sem CUDA/ROCm - não existe wheel Linux/Mac, por isso
# o fallback abaixo se alguém setar GPU fora do Windows).
if ($env:PHOENIX_TTS_DEVICE -eq "GPU" -and $IsWindows) {
    Write-Host "[*] PHOENIX_TTS_DEVICE=GPU - instalando onnxruntime-directml (Kokoro via GPU, experimental)..." -ForegroundColor Cyan
    & python -m pip uninstall -y onnxruntime 2>&1 | Out-Host
    & python -m pip install "onnxruntime-directml" 2>&1 | Out-Host
} else {
    if ($env:PHOENIX_TTS_DEVICE -eq "GPU" -and -not $IsWindows) {
        Write-Host "[!] PHOENIX_TTS_DEVICE=GPU pedido, mas onnxruntime-directml só existe pra Windows - instalando a versão CPU normal." -ForegroundColor Yellow
    }
    & python -m pip uninstall -y onnxruntime-directml 2>&1 | Out-Host
    & python -m pip install "onnxruntime>=1.29.0" 2>&1 | Out-Host
}

if ($IsWindows) {
    & python -m pip install pythonnet HardwareMonitor wmi pywin32 2>&1 | Out-Host
}

# PHX-FIX CRÍTICO: instala o pacote local hardware_engine (aivisions-hardware-discovery-core)
# que está na raiz do projeto (pyproject.toml). Sem este passo, o import
# phoenix_kernel/ahde/telemetry_bridge.py falha com:
#   ModuleNotFoundError: No module named 'hardware_engine'
# ...que derruba toda a cadeia kernel.py → facade.py → telemetry_bridge.py
# e impede o api_server.py de subir. Causa raiz do erro [PX012] confirmada
# no log LOGS_DA_ULTIMA_TENTATIVA_DE_INSTALAÇÃO.txt linha 5991.
Write-Host "[*] Instalando pacote local hardware_engine (aivisions-hardware-discovery-core)..." -ForegroundColor Cyan
Push-Location $PhoenixRoot
& python -m pip install -e . 2>&1 | Out-Host
$hwEngineInstalled = ($LASTEXITCODE -eq 0)
Pop-Location
if ($hwEngineInstalled) {
    Write-Host "[OK] hardware_engine instalado com sucesso." -ForegroundColor Green
} else {
    Write-Host "[!] AVISO: pip install -e . falhou. Tentando verificar se o pyproject.toml existe..." -ForegroundColor Yellow
    if (-not (Test-Path (Join-Path $PhoenixRoot "pyproject.toml"))) {
        Write-Host "[!] pyproject.toml nao encontrado em $PhoenixRoot. Certifique-se de que o projeto foi extraido corretamente." -ForegroundColor Red
    }
}

Write-Host "`n=== CLONANDO REPOSITORIOS BASE (AVIARY) ===" -ForegroundColor Cyan
 $env:GIT_TERMINAL_PROMPT = "0"
if (-not (Test-Path ".\repos")) { New-Item -ItemType Directory -Force -Path ".\repos" | Out-Null }
 $Repos = @{
    "llama.cpp" = "https://github.com/ggml-org/llama.cpp"
    "phoenix_studio" = "https://github.com/aivisionslab-studios/phoenix-engine.git"
    "ComfyUI" = "https://github.com/comfyanonymous/ComfyUI"
    "stable-diffusion-webui" = "https://github.com/AUTOMATIC1111/stable-diffusion-webui"
    "stable-diffusion-webui-forge" = "https://github.com/lllyasviel/stable-diffusion-webui-forge"
    # PHX-FIX (auditoria completa): WhisperDriver (phoenix_kernel/runtime/drivers/whisper.py)
    # já foi implementado e procura o binário em repos\whisper.cpp\build\bin\... - mas o repo
    # nunca era clonado aqui (só "faster-whisper", que é outro projeto/linguagem, caminho
    # diferente). Sem isso, o driver sempre falha com "whisper-cli não encontrado".
    "whisper.cpp" = "https://github.com/ggml-org/whisper.cpp"
    "InvokeAI" = "https://github.com/invoke-ai/InvokeAI"
    "SwarmUI" = "https://github.com/mcmonkeyprojects/SwarmUI"
    "open-interpreter" = "https://github.com/OpenInterpreter/open-interpreter"
    "OpenHands" = "https://github.com/All-Hands-AI/OpenHands"
    "OpenDevin" = "https://github.com/OpenDevin/OpenDevin"
    "devika" = "https://github.com/stitionai/devika"
    "bolt.diy" = "https://github.com/stackblitz-labs/bolt.diy"
    "continue" = "https://github.com/continuedev/continue"
    "crewAI" = "https://github.com/crewAIInc/crewAI"
    "autogen" = "https://github.com/microsoft/autogen"
    "semantic-kernel" = "https://github.com/microsoft/semantic-kernel"
    "langgraph" = "https://github.com/langchain-ai/langgraph"
    "openai-agents-python" = "https://github.com/openai/openai-agents-python"
    "OpenWebUI" = "https://github.com/open-webui/open-webui"
    "LibreChat" = "https://github.com/danny-avila/LibreChat"
    "anything-llm" = "https://github.com/Mintplex-Labs/anything-llm"
    "lobe-chat" = "https://github.com/lobehub/lobe-chat"
    "Flowise" = "https://github.com/FlowiseAI/Flowise"
    "big-AGI" = "https://github.com/enricoros/big-AGI"
    "SillyTavern" = "https://github.com/SillyTavern/SillyTavern"
    "chatbox" = "https://github.com/chatboxai/chatbox"
    "gpt4all" = "https://github.com/nomic-ai/gpt4all"
    "cherry-studio" = "https://github.com/CherryHQ/cherry-studio"
    "enchanted" = "https://github.com/AugustDev/enchanted"
    "jan" = "https://github.com/janhq/jan"
    "faster-whisper" = "https://github.com/SYSTRAN/faster-whisper"
    "Coqui-TTS" = "https://github.com/idiap/coqui-ai-TTS"
    "Kokoro" = "https://github.com/hexgrad/kokoro"
    "Applio" = "https://github.com/IAHispano/Applio"
}
if ($IsWindows) { $Repos["LibreHardwareMonitor"] = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor.git" }

# PHX-FIX 2026-08-30 - build reprodutível do llama.cpp.
# Antes, cada instalação executava `git pull` no HEAD e apagava o build
# anterior antes de recompilar. Isso permitia que uma regressão upstream
# entrasse silenciosamente e também destruía o último binário conhecido.
# O ref pode ser substituído explicitamente por PHOENIX_LLAMA_CPP_REF.
$LlamaCppPinnedRef = if ($env:PHOENIX_LLAMA_CPP_REF) { $env:PHOENIX_LLAMA_CPP_REF.Trim() } else { "0b5be7e4a" }

function Set-LlamaCppPinnedRef {
    param([string]$Dest, [string]$Ref)
    if (-not (Test-Path $Dest)) { return $false }
    $dirty = (& git -C $Dest status --porcelain 2>$null | Out-String).Trim()
    if ($dirty) {
        Write-Host "[!] llama.cpp possui alterações locais; não vou trocar checkout automaticamente. Ref atual será preservado." -ForegroundColor Yellow
        return $true
    }
    & git -C $Dest fetch --tags --prune origin 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { return $false }
    & git -C $Dest checkout --detach $Ref 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] Não foi possível checkout do llama.cpp ref '$Ref'." -ForegroundColor Red
        return $false
    }
    $resolved = (& git -C $Dest rev-parse --short=12 HEAD 2>$null | Out-String).Trim()
    Write-Host "[OK] llama.cpp fixado em $resolved (pedido: $Ref)." -ForegroundColor Green
    return $true
}

foreach ($repo in $Repos.Keys) {
    $dest = Join-Path ".\repos" $repo
    if (!(Test-Path $dest)) { 
        & git clone $Repos[$repo] $dest 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[!] Falha clonando $repo." -ForegroundColor Yellow
            continue
        }
        if ($repo -eq "llama.cpp") {
            Set-LlamaCppPinnedRef -Dest $dest -Ref $LlamaCppPinnedRef | Out-Null
        }
    } else { 
        if ($repo -eq "llama.cpp") {
            # Não seguir HEAD automaticamente: reproduzibilidade primeiro.
            Set-LlamaCppPinnedRef -Dest $dest -Ref $LlamaCppPinnedRef | Out-Null
        } else {
            & git -C $dest pull 2>&1 | Out-Null
        }
    }
}

# =====================================================================
# TOOLCHAIN E COMPILAÇÃO DO LLAMA.CPP
# =====================================================================
# PHX-FIX (achado real do usuário 2026-08-24, "se piper nao funciona e
# kokoro é melhor, jogar fora o piper de vez"): bloco de download do
# binário Piper TTS + 6 vozes neurais removido daqui. O Kokoro-82M
# substituiu o Piper como motor de voz padrão da Phoenix desde 2026-08-23
# (traz seu próprio eSpeak-NG embutido, não precisa deste download
# separado) - o PiperDriver que consumia esses arquivos já estava morto no
# código (drivers/piper.py removido nesta mesma versão). Quem já tinha
# rodado uma versão anterior da Phoenix pode ter `repos\Piper\` e
# `Workstations\Models\Voice\Piper\` ainda no disco - não são mais
# gerenciados por este instalador e podem ser apagados manualmente pra
# liberar espaço, sem afetar nada (o Kokoro fica em
# `Workstations\Models\Voice\Kokoro\`, pasta separada).
Write-Host "`n=== VERIFICANDO TOOLCHAIN DE COMPILACAO (CMake + C++) ===" -ForegroundColor Cyan

 $vsGenerator = $null
 $vsToolsAvailable = $false

function Get-VSBuildToolsPath {
    $vswhereExe = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhereExe) { return (& $vswhereExe -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath -latest 2>$null) }
    return $null
}

function Get-VSGeneratorName {
    param([string]$VsInstallPath)
    $vswhereExe = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $catalogVersion = $null
    if ((Test-Path $vswhereExe) -and $VsInstallPath) {
        try { $catalogVersion = (& $vswhereExe -products * -path $VsInstallPath -property catalog_productLineVersion 2>$null) } catch {}
    }
    if (-not $catalogVersion -and (Test-Path $vswhereExe) -and $VsInstallPath) {
        try {
            $verString = (& $vswhereExe -products * -path $VsInstallPath -property installationVersion 2>$null)
            if ($verString) {
                $major = [int]($verString.Split('.')[0])
                $catalogVersion = switch ($major) { { $_ -ge 18 } { "2026" } 17 { "2022" } 16 { "2019" } 15 { "2017" } default { $null } }
            }
        } catch {}
    }
    $generatorMap = @{ "2026"="Visual Studio 18 2026"; "2022"="Visual Studio 17 2022"; "2019"="Visual Studio 16 2019"; "2017"="Visual Studio 15 2017" }
    if ($catalogVersion -and $generatorMap.ContainsKey([string]$catalogVersion)) { return $generatorMap[[string]$catalogVersion] }
    return "Visual Studio 17 2022"
}

function Find-CMakeOnDisk {
    $candidates = @("C:\Program Files\CMake\bin\cmake.exe", "C:\Program Files (x86)\CMake\bin\cmake.exe")
    $vsPath = Get-VSBuildToolsPath
    if ($vsPath) { $candidates += (Join-Path $vsPath "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe") }
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

if ($IsWindows) {
    Update-SessionPath
    $vsPath = Get-VSBuildToolsPath
    if (-not $vsPath) {
        & winget install --id Microsoft.VisualStudio.2022.BuildTools --silent --force --accept-package-agreements --accept-source-agreements --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --includeRecommended" 2>&1 | Out-Host
        Update-SessionPath
        $vsPath = Get-VSBuildToolsPath
    }
    $vsToolsAvailable = [bool]$vsPath
    if ($vsPath) { Add-ToSessionPath -Dir (Join-Path $vsPath "MSBuild\Current\Bin") | Out-Null }
    $vsGenerator = Get-VSGeneratorName -VsInstallPath $vsPath

    if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
        & winget install --id Kitware.CMake --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Host
        Update-SessionPath
    }
    if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
        $cmakeOnDisk = Find-CMakeOnDisk
        if ($cmakeOnDisk) { Add-ToSessionPath -Dir (Split-Path $cmakeOnDisk -Parent) | Out-Null }
    }
    
    if (-not (Get-Command ninja -ErrorAction SilentlyContinue)) {
        & winget install --id Ninja-build.Ninja --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Host
        Update-SessionPath
    }

    Write-Host "`n=== VERIFICANDO VULKAN SDK ===" -ForegroundColor Cyan

    # PHX-FIX: Blindagem contra 'Cannot bind argument to parameter Path because it is null'.
    # Get-ChildItem pode retornar $null (pasta vazia/inexistente) - iterar com foreach
    # em vez de Select-Object -First 1 evita o Join-Path explodir com $v nulo.
    function Find-VulkanSdk {
        $roots = @("C:\VulkanSDK", "${env:ProgramFiles}\VulkanSDK", "${env:ProgramFiles(x86)}\VulkanSDK")
        foreach ($root in $roots) {
            if (-not (Test-Path $root)) { continue }
            $vDirs = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
            foreach ($v in $vDirs) {
                $glslcPath = Join-Path $v.FullName "Bin\glslc.exe"
                if (Test-Path $glslcPath) { return $v.FullName }
            }
        }
        return $null
    }

    if (-not $env:VULKAN_SDK) { $env:VULKAN_SDK = Find-VulkanSdk }

    if (-not $env:VULKAN_SDK) {
        Write-Host "[*] Vulkan SDK nao encontrado. Instalando via winget..." -ForegroundColor Yellow
        & winget install --id KhronosGroup.VulkanSDK --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Host
        Update-SessionPath
        # PHX-FIX: re-escaneia apos o install - sem isso $env:VULKAN_SDK ficava vazio
        # na mesma sessao mesmo com o SDK recem-instalado, e o CMake compilava sem Vulkan.
        $env:VULKAN_SDK = Find-VulkanSdk
    }

    if ($env:VULKAN_SDK) {
        Add-ToSessionPath -Dir (Join-Path $env:VULKAN_SDK "Bin") | Out-Null
        Write-Host "[OK] VULKAN_SDK definido para: $env:VULKAN_SDK" -ForegroundColor Green
    } else {
        Write-Host "[!] AVISO CRITICO: Vulkan SDK nao encontrado. A compilacao do llama.cpp e Phoenix Diffusion com Vulkan provavelmente falhara." -ForegroundColor Red
    }

} elseif ($IsLinux) {
    $requiredPkgs = @("build-essential", "cmake", "pkg-config", "ninja-build", "libvulkan-dev", "vulkan-tools", "glslang-tools", "spirv-tools")
    $missingPkgs = @()
    foreach ($pkg in $requiredPkgs) { & dpkg -s $pkg *> $null; if ($LASTEXITCODE -ne 0) { $missingPkgs += $pkg } }
    if ($missingPkgs.Count -gt 0) {
        $aptPrefix = if (Get-Command sudo -ErrorAction SilentlyContinue) { "sudo" } else { "" }
        if ($aptPrefix) { & sudo apt-get update -y 2>&1 | Out-Host; & sudo apt-get install -y $missingPkgs 2>&1 | Out-Host } else { & apt-get update -y 2>&1 | Out-Host; & apt-get install -y $missingPkgs 2>&1 | Out-Host }
    }
}

Write-Host "`n=== COMPILANDO LLAMA.CPP (Backend Vulkan para CPU/GPU) ===" -ForegroundColor Cyan
 $llamaDir = Join-Path $PhoenixRoot "repos\llama.cpp"
 $llamaCppBuildOk = $false
 $llamaServerBinResolved = $null
 # PHX-REVERT (a pedido explícito): volta a compilar DENTRO de repos\llama.cpp\build,
 # não mais em C:\pxb\llama. O risco de MAX_PATH que motivou o pxb continua existindo
 # em tese se $PhoenixRoot for muito longo/fundo - mitigar isso agora é responsabilidade
 # de manter o caminho da instalação curto (ex: "C:\PHOENIX 3.0", sem pastas extras no meio),
 # não mais responsabilidade do script de build.
 $llamaBuildDir = Join-Path $llamaDir "build"

function Get-LlamaServerBinCandidates {
    param([string]$LlamaBuildDir, [bool]$IsWin)
    if ($IsWin) { return @((Join-Path $LlamaBuildDir "bin\llama-server.exe"), (Join-Path $LlamaBuildDir "bin\Release\llama-server.exe")) }
    else { return @((Join-Path $LlamaBuildDir "bin/llama-server")) }
}

if (Test-Path $llamaDir) {
    Push-Location $llamaDir
    try {
        $llamaBuildBackupDir = "$llamaBuildDir.previous"
        if (Test-Path $llamaBuildBackupDir) { Remove-Item -Recurse -Force $llamaBuildBackupDir -ErrorAction SilentlyContinue }
        if (Test-Path $llamaBuildDir) {
            Write-Host "[*] Preservando build anterior do llama.cpp como rollback temporário..." -ForegroundColor Yellow
            Move-Item -Force $llamaBuildDir $llamaBuildBackupDir -ErrorAction Stop
        }
        if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
            Write-Host "[!] CMake indisponível." -ForegroundColor Yellow
        } elseif ($IsWindows -and -not $vsToolsAvailable) {
            Write-Host "[!] VS Build Tools indisponível." -ForegroundColor Yellow
        } else {
            $cacheFile = Join-Path $llamaBuildDir "CMakeCache.txt"
            if (Test-Path $cacheFile) {
                $cachedHome = (Select-String -Path $cacheFile -Pattern '^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$' -ErrorAction SilentlyContinue | ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -First 1)
                if ($cachedHome -and ($cachedHome.TrimEnd('/','\') -ne $llamaDir.TrimEnd('/','\'))) {
                    Remove-Item -Recurse -Force $llamaBuildDir -ErrorAction SilentlyContinue
                }
            }

            $configureOk = $false
            $buildOk = $false

            if ($IsWindows) {
                $ninjaAvailable = [bool](Get-Command ninja -ErrorAction SilentlyContinue)
                if ($ninjaAvailable) {
                    Write-Host "[*] Usando generator: Ninja" -ForegroundColor DarkGray
                    
                    $vsDevShell = $null
                    if ($vsPath) {
                        $devShellScripts = @(
                            (Join-Path $vsPath "Common7\Tools\Launch-VsDevShell.ps1"),
                            (Join-Path $vsPath "Common7\Tools\Enter-VsDevShell.ps1")
                        )
                        foreach ($script in $devShellScripts) {
                            if (Test-Path $script) { $vsDevShell = $script; break }
                        }
                    }

                    if ($vsDevShell) {
                        Write-Host "[*] Ativando ambiente MSVC via: $vsDevShell" -ForegroundColor DarkGray
                        # PHX-FIX: Launch-VsDevShell.ps1/Enter-VsDevShell.ps1 pode emitir objetos
                        # para o pipeline (nao so Write-Host). Sem suprimir, esses objetos vazam
                        # para o retorno do proprio common.ps1, quebrando o contrato Hashtable
                        # (erro PX002: "Modulo nao retornou um contrato Hashtable valido").
                        & $vsDevShell -SkipAutomaticLocation -Arch amd64 *>&1 | Out-Host
                        
                        $clCheck = Get-Command cl.exe -ErrorAction SilentlyContinue
                        if ($clCheck) {
                            Write-Host "[OK] cl.exe resolvido em: $($clCheck.Source)" -ForegroundColor Green
                            & cmake -B "$llamaBuildDir" -G "Ninja" -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DCMAKE_CXX_FLAGS="/bigobj" 2>&1 | Out-Host
                            $configureOk = ($LASTEXITCODE -eq 0)
                            if ($configureOk) {
                                Write-Host "[*] Compilando llama.cpp no Windows (Ninja)..."
                                & cmake --build "$llamaBuildDir" 2>&1 | Out-Host
                                $buildOk = ($LASTEXITCODE -eq 0)
                            }
                        } else {
                            Write-Host "[!] cl.exe NAO encontrado. Tentando fallback MSBuild..." -ForegroundColor Red
                            & cmake -B "$llamaBuildDir" -G $vsGenerator -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DCMAKE_CXX_FLAGS="/bigobj" 2>&1 | Out-Host
                            $configureOk = ($LASTEXITCODE -eq 0)
                            if ($configureOk) { & cmake --build "$llamaBuildDir" --config Release 2>&1 | Out-Host; $buildOk = ($LASTEXITCODE -eq 0) }
                        }
                    } else {
                        Write-Host "[!] VsDevShell.ps1 não encontrado. Tentando CMake sem ambiente MSVC..." -ForegroundColor Yellow
                        & cmake -B "$llamaBuildDir" -G "Ninja" -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DCMAKE_CXX_FLAGS="/bigobj" 2>&1 | Out-Host
                        $configureOk = ($LASTEXITCODE -eq 0)
                        if ($configureOk) { & cmake --build "$llamaBuildDir" 2>&1 | Out-Host; $buildOk = ($LASTEXITCODE -eq 0) }
                    }
                } else {
                    Write-Host "[!] Ninja não encontrado - usando fallback: $vsGenerator" -ForegroundColor DarkYellow
                    & cmake -B "$llamaBuildDir" -G $vsGenerator -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DCMAKE_CXX_FLAGS="/bigobj" 2>&1 | Out-Host
                    $configureOk = ($LASTEXITCODE -eq 0)
                    if ($configureOk) { & cmake --build "$llamaBuildDir" --config Release 2>&1 | Out-Host; $buildOk = ($LASTEXITCODE -eq 0) }
                }
            } else {
                & cmake -B "$llamaBuildDir" -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON 2>&1 | Out-Host
                $configureOk = ($LASTEXITCODE -eq 0)
                if ($configureOk) { $cores = (nproc); & cmake --build "$llamaBuildDir" --config Release -j $cores 2>&1 | Out-Host; $buildOk = ($LASTEXITCODE -eq 0) }
            }

            if ($configureOk -and $buildOk) {
                $llamaServerBin = (Get-LlamaServerBinCandidates -LlamaBuildDir $llamaBuildDir -IsWin $IsWindows) | Where-Object { Test-Path $_ } | Select-Object -First 1
                if ($llamaServerBin -and (Get-Item $llamaServerBin).Length -gt 0) {
                    Write-Host "[OK] llama.cpp compilado com Vulkan nativo! Binario: $llamaServerBin" -ForegroundColor Green
                    $llamaCppBuildOk = $true
                    $llamaServerBinResolved = $llamaServerBin
                }
            }
        }
    } catch {
        Write-Host "[!] Erro na compilação: $($_.Exception.Message)" -ForegroundColor Yellow
    } finally {
        Pop-Location
    }

    # Promoção transacional: só descarta o build anterior depois de um novo
    # llama-server válido. Se a compilação falhou, restaura automaticamente.
    $llamaBuildBackupDir = "$llamaBuildDir.previous"
    if ($llamaCppBuildOk) {
        if (Test-Path $llamaBuildBackupDir) { Remove-Item -Recurse -Force $llamaBuildBackupDir -ErrorAction SilentlyContinue }
        if ($llamaServerBinResolved) {
            Write-Host "[*] llama-server --version:" -ForegroundColor DarkGray
            & $llamaServerBinResolved --version 2>&1 | Out-Host
            Write-Host "[*] Dispositivos enumerados pelo llama-server:" -ForegroundColor DarkGray
            & $llamaServerBinResolved --list-devices 2>&1 | Out-Host
        }
    } elseif (Test-Path $llamaBuildBackupDir) {
        Write-Host "[!] Novo build do llama.cpp falhou; restaurando build anterior conhecido." -ForegroundColor Yellow
        if (Test-Path $llamaBuildDir) { Remove-Item -Recurse -Force $llamaBuildDir -ErrorAction SilentlyContinue }
        Move-Item -Force $llamaBuildBackupDir $llamaBuildDir
        $restored = (Get-LlamaServerBinCandidates -LlamaBuildDir $llamaBuildDir -IsWin $IsWindows) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($restored) {
            $llamaCppBuildOk = $true
            $llamaServerBinResolved = $restored
            Write-Host "[OK] Rollback do llama.cpp restaurado: $restored" -ForegroundColor Green
        }
    }
}

# =====================================================================
# COMPILAÇÃO DO PHOENIX DIFFUSION NATIVO
# =====================================================================
Write-Host "`n=== COMPILANDO PHOENIX DIFFUSION (bridge nativa Vulkan) ===" -ForegroundColor Cyan
 $phoenixDiffusionDir = Join-Path $PhoenixRoot "src\phoenix-diffusion.cpp"
 $phoenixDiffusionBuildOk = $false
 $phoenixDiffusionBridgeResolved = $null

if (-not (Test-Path (Join-Path $phoenixDiffusionDir "ggml\CMakeLists.txt"))) {
    Write-Host "[ERRO] Dependência GGML incluída no pacote está ausente. Reextraia o pacote oficial Phoenix 4.5." -ForegroundColor Red
    $commonWarnings += "Phoenix Diffusion Bridge ausente - código-fonte GGML incompleto no pacote."
} elseif (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    Write-Host "[ERRO] CMake indisponível para compilar Phoenix Diffusion." -ForegroundColor Red
    $commonWarnings += "Phoenix Diffusion Bridge ausente - CMake não foi encontrado."
} elseif ($IsWindows -and -not $vsToolsAvailable) {
    Write-Host "[ERRO] Visual Studio Build Tools indisponível para compilar Phoenix Diffusion." -ForegroundColor Red
    $commonWarnings += "Phoenix Diffusion Bridge ausente - Visual Studio C++ Build Tools não foi encontrado."
} else {
    try {
        if ($IsWindows) {
            & (Join-Path $phoenixDiffusionDir "scripts\build_windows_rx580.ps1") -Force 2>&1 | Out-Host
            $bridgeCandidates = @(
                (Join-Path $PhoenixRoot "bin\phoenix_sd_bridge.dll"),
                (Join-Path $phoenixDiffusionDir "build\windows-rx580-vulkan\bin\Release\phoenix_sd_bridge.dll"),
                (Join-Path $phoenixDiffusionDir "build\windows-rx580-vulkan\bin\phoenix_sd_bridge.dll")
            )
        } else {
            $buildDir = Join-Path $phoenixDiffusionDir "build"
            & cmake -S $phoenixDiffusionDir -B $buildDir -DCMAKE_BUILD_TYPE=Release -DSD_VULKAN=ON -DGGML_NATIVE=OFF -DPHOENIX_BUILD_BRIDGE=ON 2>&1 | Out-Host
            if ($LASTEXITCODE -eq 0) { & cmake --build $buildDir --target phoenix_sd_bridge --parallel 4 2>&1 | Out-Host }
            $bridgeCandidates = @((Join-Path $buildDir "bin\libphoenix_sd_bridge.so"), (Join-Path $buildDir "bin\libphoenix_sd_bridge.dylib"))
        }
        if ($LASTEXITCODE -eq 0) {
            $phoenixDiffusionBridgeResolved = $bridgeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
            $phoenixDiffusionBuildOk = [bool]$phoenixDiffusionBridgeResolved
        }
        if ($phoenixDiffusionBuildOk) {
            $stableBridgeDir = Join-Path $PhoenixRoot "bin"
            $stableBridge = Join-Path $stableBridgeDir "phoenix_sd_bridge.dll"
            if ($IsWindows) {
                New-Item -ItemType Directory -Force -Path $stableBridgeDir | Out-Null
                Copy-Item -Force $phoenixDiffusionBridgeResolved $stableBridge
                $phoenixDiffusionBridgeResolved = $stableBridge
            }
            Write-Host "[OK] Phoenix Diffusion compilado: $phoenixDiffusionBridgeResolved" -ForegroundColor Green
        } else {
            Write-Host "[ERRO] A compilação não produziu a bridge Phoenix Diffusion." -ForegroundColor Red
            $commonWarnings += "Phoenix Diffusion Bridge ausente - geração de imagens indisponível até o reparo automático do launcher concluir."
        }
    } catch {
        Write-Host "[ERRO] Falha compilando Phoenix Diffusion: $($_.Exception.Message)" -ForegroundColor Red
        $commonWarnings += "Phoenix Diffusion Bridge falhou ao compilar: $($_.Exception.Message)"
    }
}

# =====================================================================
# COMPILAÇÃO DO WHISPER.CPP (STT)
# =====================================================================
# PHX-NEW (auditoria completa): WhisperDriver (phoenix_kernel/runtime/drivers/whisper.py)
# já existia mas nunca tinha bloco de build - o repo era clonado (a partir do fix acima)
# só que nunca compilado, então _find_executable() nunca achava whisper-cli. Mesmo padrão
# de build do llama.cpp/Phoenix Diffusion acima (Ninja + MSVC no Windows, GGML_VULKAN=ON
# pra rodar no mesmo backend Vulkan que o resto da Phoenix já usa nesta GPU).
Write-Host "`n=== COMPILANDO WHISPER.CPP (STT via Vulkan/CPU) ===" -ForegroundColor Cyan
 $whisperDir = Join-Path $PhoenixRoot "repos\whisper.cpp"
 $whisperBuildOk = $false
 $whisperCliBinResolved = $null

function Get-WhisperCliBinCandidates {
    param([string]$WhisperDir, [bool]$IsWin)
    if ($IsWin) { return @((Join-Path $WhisperDir "build\bin\whisper-cli.exe"), (Join-Path $WhisperDir "build\bin\Release\whisper-cli.exe")) }
    else { return @((Join-Path $WhisperDir "build/bin/whisper-cli")) }
}

if (Test-Path $whisperDir) {
    Push-Location $whisperDir
    try {
        $whisperBuildDir = Join-Path $whisperDir "build"
        if (Test-Path $whisperBuildDir) {
            Write-Host "[*] PHX-RECREATE: removendo build anterior do whisper.cpp..." -ForegroundColor Yellow
            Remove-Item -Recurse -Force $whisperBuildDir -ErrorAction Stop
        }
        if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
            Write-Host "[!] CMake indisponível para whisper.cpp." -ForegroundColor Yellow
        } elseif ($IsWindows -and -not $vsToolsAvailable) {
            Write-Host "[!] VS Build Tools indisponível para whisper.cpp." -ForegroundColor Yellow
        } else {
            $cacheFile = Join-Path $whisperDir "build\CMakeCache.txt"
            if (Test-Path $cacheFile) {
                $cachedHome = (Select-String -Path $cacheFile -Pattern '^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$' -ErrorAction SilentlyContinue | ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -First 1)
                if ($cachedHome -and ($cachedHome.TrimEnd('/','\') -ne $whisperDir.TrimEnd('/','\'))) {
                    Remove-Item -Recurse -Force (Join-Path $whisperDir "build") -ErrorAction SilentlyContinue
                }
            }

            $configureOk = $false
            $buildOk = $false

            if ($IsWindows) {
                $ninjaAvailable = [bool](Get-Command ninja -ErrorAction SilentlyContinue)
                if ($ninjaAvailable) {
                    Write-Host "[*] Usando generator: Ninja (whisper.cpp)" -ForegroundColor DarkGray

                    $vsDevShell = $null
                    if ($vsPath) {
                        $devShellScripts = @(
                            (Join-Path $vsPath "Common7\Tools\Launch-VsDevShell.ps1"),
                            (Join-Path $vsPath "Common7\Tools\Enter-VsDevShell.ps1")
                        )
                        foreach ($script in $devShellScripts) {
                            if (Test-Path $script) { $vsDevShell = $script; break }
                        }
                    }

                    if ($vsDevShell) {
                        Write-Host "[*] Ativando ambiente MSVC via: $vsDevShell" -ForegroundColor DarkGray
                        & $vsDevShell -SkipAutomaticLocation -Arch amd64 *>&1 | Out-Host

                        $clCheck = Get-Command cl.exe -ErrorAction SilentlyContinue
                        if ($clCheck) {
                            Write-Host "[OK] cl.exe resolvido para whisper.cpp." -ForegroundColor Green
                            & cmake -B build -G "Ninja" -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DCMAKE_CXX_FLAGS="/bigobj" 2>&1 | Out-Host
                            $configureOk = ($LASTEXITCODE -eq 0)
                            if ($configureOk) {
                                Write-Host "[*] Compilando whisper.cpp no Windows (Ninja)..."
                                & cmake --build build 2>&1 | Out-Host
                                $buildOk = ($LASTEXITCODE -eq 0)
                            }
                        } else {
                            Write-Host "[!] cl.exe NAO encontrado. Tentando fallback MSBuild..." -ForegroundColor Red
                            & cmake -B build -G $vsGenerator -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DCMAKE_CXX_FLAGS="/bigobj" 2>&1 | Out-Host
                            $configureOk = ($LASTEXITCODE -eq 0)
                            if ($configureOk) { & cmake --build build --config Release 2>&1 | Out-Host; $buildOk = ($LASTEXITCODE -eq 0) }
                        }
                    } else {
                        Write-Host "[!] VsDevShell.ps1 não encontrado. Tentando CMake sem ambiente MSVC..." -ForegroundColor Yellow
                        & cmake -B build -G "Ninja" -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DCMAKE_CXX_FLAGS="/bigobj" 2>&1 | Out-Host
                        $configureOk = ($LASTEXITCODE -eq 0)
                        if ($configureOk) { & cmake --build build 2>&1 | Out-Host; $buildOk = ($LASTEXITCODE -eq 0) }
                    }
                } else {
                    Write-Host "[!] Ninja não encontrado - usando fallback: $vsGenerator" -ForegroundColor DarkYellow
                    & cmake -B build -G $vsGenerator -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DCMAKE_CXX_FLAGS="/bigobj" 2>&1 | Out-Host
                    $configureOk = ($LASTEXITCODE -eq 0)
                    if ($configureOk) { & cmake --build build --config Release 2>&1 | Out-Host; $buildOk = ($LASTEXITCODE -eq 0) }
                }
            } else {
                & cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON 2>&1 | Out-Host
                $configureOk = ($LASTEXITCODE -eq 0)
                if ($configureOk) { $cores = (nproc); & cmake --build build --config Release -j $cores 2>&1 | Out-Host; $buildOk = ($LASTEXITCODE -eq 0) }
            }

            if ($configureOk -and $buildOk) {
                $whisperCliBin = (Get-WhisperCliBinCandidates -WhisperDir $whisperDir -IsWin $IsWindows) | Where-Object { Test-Path $_ } | Select-Object -First 1
                if ($whisperCliBin -and (Get-Item $whisperCliBin).Length -gt 0) {
                    Write-Host "[OK] whisper.cpp compilado! Binario: $whisperCliBin" -ForegroundColor Green
                    $whisperBuildOk = $true
                    $whisperCliBinResolved = $whisperCliBin
                }
            }
        }
    } catch {
        Write-Host "[!] Erro na compilação do whisper.cpp: $($_.Exception.Message)" -ForegroundColor Yellow
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[!] Repositório whisper.cpp não encontrado. Pulando compilação." -ForegroundColor DarkYellow
}

# =====================================================================
# CONTAINERS DOCKER (Ollama + Open WebUI + SearXNG)
# =====================================================================
Write-Host "`n=== PROVISIONAMENTO DE CONTAINERS ===" -ForegroundColor Cyan

# PHX-FIX (auditoria 2026-08-20, "Runtime policy / LM Studio opcional /
# portas corretas" - Seção 7): achado real e grave - antes, `& docker ...`
# era chamado direto, sem checar se o comando `docker` existe. Docker
# Desktop virou OPCIONAL nesta auditoria (ver install/windows.ps1,
# $PackageCategories - Docker não tem mais Required=$true), então numa
# máquina sem Docker instalado (ou onde o winget do Docker falhou, agora
# um WARN e não mais um erro fatal), `& docker volume create ...` levanta
# um erro de "comando não encontrado" - um erro TERMINANTE em PowerShell
# (diferente de exit code != 0, que $PSNativeCommandUseErrorActionPreference
# = $false já neutraliza) - que abortaria o script Common inteiro, e com
# ele o boot inteiro da Phoenix. Ollama e Open WebUI são OPCIONAIS
# (Seções 3 e 7): se Docker não está disponível, pula os dois containers
# com um aviso claro e a Phoenix continua com llama.cpp nativo.
$dockerAvailable = [bool](Get-Command docker -ErrorAction SilentlyContinue)
if (-not $dockerAvailable) {
    Write-Host "[WARN] Docker nao encontrado. Recursos opcionais baseados em container (Ollama, Open WebUI) nao serao iniciados." -ForegroundColor Yellow
    Write-Host "[OK] Phoenix Engine continua operando com llama.cpp nativo." -ForegroundColor Green
    $commonWarnings += "Docker nao encontrado - Ollama e Open WebUI (opcionais) nao foram provisionados. Phoenix continua com llama.cpp nativo."
}

if ($dockerAvailable) {
    Write-Host "[*] Provisionando Ollama (porta 11434)..."
    & docker volume create ollama 2>&1 | Out-Null
    & docker rm -f ollama 2>&1 | Out-Null
    & docker run -d --name ollama --restart unless-stopped -p 11434:11434 -e OLLAMA_ORIGINS="*" -v ollama:/root/.ollama ollama/ollama 2>&1 | Out-Null

    if (-not $llamaCppBuildOk) {
        Write-Host "[*] llama.cpp indisponivel - baixando qwen3:8b pro Ollama..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
        & docker exec ollama ollama pull qwen3:8b 2>&1 | Out-Null
    }
}

 # PHX-FIX (auditoria 2026-08-20, "Golden Baseline"): este arquivo é
 # SÓ um relatório de diagnóstico do instalador (o que o instalador
 # detectou nesta máquina durante o setup) - NUNCA foi, e não é, a
 # preferência de engine que o Phoenix usa em runtime. A preferência
 # real e viva fica em `data/text_engine_preference.json`, lida e
 # escrita por `ResidentManager._load_text_engine_preference()` /
 # `get_text_engine_preference()` / `set_text_engine_preference()`
 # (default = "llama.cpp"). Confirmado por busca exaustiva: nenhum
 # código Python lê este arquivo em ProgramData de volta.
 #
 # Antes, este bloco usava os nomes `engine_preference.json` /
 # `preferred_llm_engine` - IDÊNTICOS ao padrão de um arquivo legado já
 # removido do fluxo real, o que gerou falsos positivos repetidos em
 # auditorias anteriores (alguém grepa "preferred_llm_engine",
 # encontra isso aqui, e erra ao concluir que é uma regressão do
 # Golden Baseline). Renomeado para deixar explícito que é só
 # diagnóstico do instalador, não uma declaração de default ativo.
 $installDiagPath = Join-Path $_phoenixConfigRoot "install_diagnostics.json"
 $installDiagDir = Split-Path $installDiagPath -Parent
if (-not (Test-Path $installDiagDir)) { New-Item -ItemType Directory -Force -Path $installDiagDir | Out-Null }
 $binExists = $false
if ($llamaServerBinResolved -and (Test-Path $llamaServerBinResolved) -and (Get-Item $llamaServerBinResolved).Length -gt 0) {
    $binExists = $true
} else {
    # Fallback: usa os candidatos de $llamaBuildDir (repos\llama.cpp\build,
    # após o revert do pxb) caso $llamaServerBinResolved não tenha sido
    # setado antes por algum motivo.
    $candidatesForCheck = Get-LlamaServerBinCandidates -LlamaBuildDir $llamaBuildDir -IsWin $IsWindows
    foreach ($c in $candidatesForCheck) {
        if ((Test-Path $c) -and (Get-Item $c).Length -gt 0) { $binExists = $true; $llamaServerBinResolved = $c; break }
    }
}
 $installerDetectedEngine = if ($binExists) { "llama.cpp" } else { "ollama" }
@{
    _comment = "Relatorio de diagnostico do INSTALADOR (o que foi detectado durante o setup). NAO controla runtime. A preferencia real fica em data/text_engine_preference.json, gerenciada pelo ResidentManager."
    installer_detected_engine = $installerDetectedEngine
    llama_cpp_build_ok = $binExists
    llama_server_bin_path = $llamaServerBinResolved
} | ConvertTo-Json | Set-Content -Path $installDiagPath -Encoding UTF8

if ($dockerAvailable) {
    Write-Host "[*] Provisionando Open WebUI (porta 8010)..."
    & docker volume create open-webui 2>&1 | Out-Null
    & docker rm -f open_webui 2>&1 | Out-Null
    & docker run -d --name open_webui --restart unless-stopped -p 8010:8080 --add-host=host.docker.internal:host-gateway -e OLLAMA_BASE_URL=http://host.docker.internal:11434 -e OPENAI_API_BASE_URL=http://host.docker.internal:8081/v1 -e OPENAI_API_KEY=llama-cpp-local -v open-webui:/app/backend/data ghcr.io/open-webui/open-webui:main 2>&1 | Out-Null
}

# PHX-REVERT: ONLYOFFICE Docs Server removido. A Document Engine da Phoenix
# (pymupdf4llm/python-docx/openpyxl/python-pptx) cobre leitura, resumo,
# edição e criação de documentos programaticamente via IA - sem editor visual
# embutido. O ONLYOFFICE estava consumindo ~1.25GB de RAM e ~43% de CPU
# sem ter nenhuma rota no api_server.py apontando pra ele.
# Se um editor visual tipo Word-no-browser virar requisito no futuro,
# reintroduzir aqui com a rota de integração correspondente.

# PHX-REVERT: Apache Tika Server removido. A extração de texto usa
# pymupdf4llm (PDF), python-docx (DOCX), openpyxl (XLSX), python-pptx (PPTX)
# - tudo Python puro, sem container extra. O Tika estava ocupando ~227MB
# de RAM sem nenhum consumidor real no projeto.

# =====================================================================
# PHOENIX STUDIO / AVIARY (Node.js) — PHX-RECREATE
# =====================================================================
Write-Host "`n=== INICIANDO PHOENIX STUDIO (NODE.JS) ===" -ForegroundColor Cyan

 $studioDir = Join-Path $PhoenixRoot "platform_source"
if (-not (Test-Path $studioDir)) { $studioDir = Join-Path $PhoenixRoot "repos\phoenix_studio" }

if (Test-Path $studioDir) {
    $aviaryPortReady = Stop-PhoenixManagedPort -Port 3000 -Name "Phoenix Aviary" -ExpectedMarkers @(
        "platform_source", "phoenix_studio", "npm run dev", "vite", "server.ts"
    )
    if (-not $aviaryPortReady) {
        return (& $failContract "Porta 3000 ocupada por processo externo; Aviary nao pode ser recriada com seguranca." "PX030")
    }

    Push-Location $studioDir
    try {
        if (-not (Test-Path "package.json")) {
            return (& $failContract "package.json da Aviary nao encontrado." "PX035")
        }

        foreach ($runtimeDir in @("node_modules", "dist", ".vite")) {
            if (Test-Path $runtimeDir) {
                Write-Host "[*] PHX-RECREATE: removendo $runtimeDir anterior da Aviary..." -ForegroundColor Yellow
                Remove-Item -Recurse -Force $runtimeDir -ErrorAction Stop
            }
        }

        Write-Host "[*] Recriando dependencias do Node.js..."
        & npm install 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) { return (& $failContract "npm install da Aviary falhou." "PX031") }

        & npm install multer @types/multer 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) { return (& $failContract "Dependencias adicionais da Aviary falharam." "PX032") }

        $scripts = (Get-Content package.json | ConvertFrom-Json).scripts
        if (-not $scripts.dev) { return (& $failContract "Script 'dev' nao encontrado no package.json da Aviary." "PX033") }

        Write-Host "[OK] Iniciando Aviary Studio limpa (npm run dev)..."
        if ($IsWindows) {
            $aviaryProc = Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory $studioDir -WindowStyle Hidden -PassThru
        } else {
            $aviaryProc = Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory $studioDir -NoNewWindow -PassThru
        }
        Write-Host "[OK] Aviary iniciada com PID $($aviaryProc.Id)." -ForegroundColor Green
    } finally {
        Pop-Location
    }
} else {
    return (& $failContract "Pasta da Aviary nao encontrada." "PX036")
}

# =====================================================================
# SEARXNG
# =====================================================================
Write-Host "`n=== CONFIGURANDO STACK SEARXNG ===" -ForegroundColor Cyan
# PHX-FIX (auditoria 2026-08-20, Seção 7): SearXNG (busca web, porta 8080)
# também é 100% baseado em container Docker - mesma proteção aplicada
# acima pra Ollama/Open WebUI. Sem Docker, a Phoenix perde só a busca web
# opcional; llama.cpp/Aviary continuam intactos.
if (-not $dockerAvailable) {
    Write-Host "[WARN] Docker nao encontrado. Stack SearXNG (busca web opcional) nao sera iniciada." -ForegroundColor Yellow
    Write-Host "[OK] Phoenix Engine continua operando normalmente (busca web e um recurso opcional)." -ForegroundColor Green
    $commonWarnings += "Docker nao encontrado - SearXNG (busca web, opcional) nao foi provisionado."
} else {
 $searxBase = Join-Path $PhoenixRoot "searxng-docker"
docker stop searxng searxng-phoenix searxng-webui 2>$null | Out-Null
docker rm searxng searxng-phoenix searxng-webui 2>$null | Out-Null
Remove-Item -Recurse -Force $searxBase -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $searxBase | Out-Null
Set-Content -Path (Join-Path $searxBase "docker-compose.yml") -Encoding UTF8 -Value @"
services:
  searxng-phoenix:
    container_name: searxng-phoenix
    image: searxng/searxng:latest
    ports: ["8080:8080"]
    volumes: ["./searxng-phoenix:/etc/searxng:rw"]
    restart: unless-stopped
  searxng-webui:
    container_name: searxng-webui
    image: searxng/searxng:latest
    ports: ["8088:8080"]
    volumes: ["./searxng-webui:/etc/searxng:rw"]
    restart: unless-stopped
"@

# PHX-FIX: Escreve o settings.yml ANTES do primeiro boot do container.
# O entrypoint do searxng/searxng só gera o default se o arquivo não existir;
# o default NÃO habilita o formato "json" em search.formats, causando 403
# em toda requisição da Phoenix que usa ?format=json (a busca web do modelo).
# Sem este fix, o 403 volta em TODA reinstalação limpa porque o Remove-Item
# acima apaga a pasta inteira, incluindo qualquer settings.yml corrigido
# manualmente. A secret_key é gerada aleatoriamente a cada instalação.
$_searxSecret = -join ((1..32) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
$_searxSettings = @"
use_default_settings: true

server:
  secret_key: "$_searxSecret"

search:
  formats:
    - html
    - json
"@
foreach ($_inst in @("searxng-phoenix", "searxng-webui")) {
    $_instPath = Join-Path $searxBase $_inst
    New-Item -ItemType Directory -Force -Path $_instPath | Out-Null
    Set-Content -Path (Join-Path $_instPath "settings.yml") -Encoding UTF8 -Value $_searxSettings
}
Write-Host "[OK] settings.yml com json habilitado escrito antes do boot (evita 403 na busca web)." -ForegroundColor Green

Push-Location $searxBase
docker compose up -d 2>&1 | Out-Null
Start-Sleep -Seconds 10
Pop-Location
}

# =====================================================================
# DOWNLOAD DOS MODELOS GGUF
# =====================================================================
Write-Host "`n=== PREPARANDO MODELOS GGUF (LLM + VISAO) ===" -ForegroundColor Cyan
 $workspaceDir = if ($PhoenixWorkspace) { $PhoenixWorkspace } elseif ($env:PHOENIX_WORKSPACE) { $env:PHOENIX_WORKSPACE } else { Join-Path $PhoenixRoot "Workstations" }
 $modelsBaseDir = Join-Path $workspaceDir "Models\Chat\GGUF"
if (-not (Test-Path $modelsBaseDir)) { New-Item -ItemType Directory -Force -Path $modelsBaseDir | Out-Null }

function Download-GGUF {
    param([string]$Name, [string]$Url, [string]$Dest)
    if (Test-Path $Dest) {
        $fileSize = (Get-Item $Dest).Length / 1GB
        Write-Host "[OK] $Name já existe em disco ($([math]::Round($fileSize, 2)) GB)." -ForegroundColor Green
        return
    }
    Write-Host "[*] Baixando $Name..." -ForegroundColor Yellow
    try {
        if ($IsWindows) { Start-BitsTransfer -Source $Url -Destination $Dest }
        else { Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing }
        Write-Host "[OK] $Name baixado com sucesso!" -ForegroundColor Green
    } catch {
        Write-Host "[X] Falha ao baixar ${Name}: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# 1. Qwen3 8B (Modelo LLM principal para raciocínio em CPU)
Download-GGUF -Name "Qwen3 8B (LLM)" `
    -Url "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf" `
    -Dest (Join-Path $modelsBaseDir "qwen3-8b-q4_k_m.gguf")

# 2. MiniCPM-V 2.6 (Modelo Multimodal para Visão)
Download-GGUF -Name "MiniCPM-V 2.6 (Vision)" `
    -Url "https://huggingface.co/bartowski/MiniCPM-V-2_6-GGUF/resolve/main/MiniCPM-V-2_6-Q6_K_L.gguf?download=true" `
    -Dest (Join-Path $modelsBaseDir "MiniCPM-V-2_6-Q6_K_L.gguf")

# 3. MMProj (Projetor de Imagens - OBRIGATÓRIO para o MiniCPM-V enxergar)
Download-GGUF -Name "MMProj (Vision Encoder)" `
    -Url "https://huggingface.co/openbmb/MiniCPM-V-2_6-gguf/resolve/main/mmproj-model-f16.gguf?download=true" `
    -Dest (Join-Path $modelsBaseDir "mmproj-model-f16.gguf")

# =====================================================================
# DOWNLOAD DOS MODELOS DE IMAGEM (Flux/SDXL) + CATÁLOGO DO ASSET MANAGER
# =====================================================================
# PHX-FIX: O bootstrapper nunca baixava modelos de imagem - só LLM/visão.
# Isso deixava o disco vazio na primeira execução, e quando uma missão
# pedia "flux" o resident_manager caía num ModelManager legado (feito só
# pra tags Ollama) que sempre respondia "nao gerou arquivo local
# (ollama-only)" e abortava. Pré-baixando o Flux Schnell + SDXL + VAE fix
# ANTES do boot, a verificação em disco do resident_manager (_resolve_
# image_model_target) encontra o arquivo pronto e pula o download inteiro
# - o bug do ModelManager legado nunca chega a ser acionado, porque o
# passo de download só roda quando NADA é achado no disco.
# NOTA: o Flux.1-schnell Q4_K_M (repo Unsloth, apache-2.0, não-gated) tem
# tamanho em disco parecido com o Q4_0 ja testado manualmente (~6.9GB vs
# ~6.8GB) - mas o consumo real de VRAM desse quant especifico ainda nao
# foi medido nesta maquina. Se der OOM em 512x512, cair pro Q4_0 ou Q3_K_S
# (ambos ja validados) e mais seguro.
Write-Host "`n=== PREPARANDO MODELOS DE IMAGEM (FLUX + SDXL) ===" -ForegroundColor Cyan
 $imageModelsDir = Join-Path $workspaceDir "Models\Image"
if (-not (Test-Path $imageModelsDir)) { New-Item -ItemType Directory -Force -Path $imageModelsDir | Out-Null }

# --- Flux.1-schnell Q4_K_M (não-gated, apache-2.0, verificado: repo Unsloth AI,
# hash SHA256 09f32f18619f6bdb8f199c6bb107f8389429e1711312c36022c452af6866d9fa) ---
Download-GGUF -Name "Flux.1-schnell Q4_K_M (Imagem)" `
    -Url "https://huggingface.co/unsloth/FLUX.1-schnell-GGUF/resolve/main/flux1-schnell-Q4_K_M.gguf?download=true" `
    -Dest (Join-Path $imageModelsDir "flux1-schnell-Q4_K_M.gguf")

# --- Componentes obrigatórios do Flux (sem eles a bridge nativa recusa o carregamento) ---
# PHX-FIX (auditoria 2026-08-20, Secao 14, Rodada 17 -> Rodada 18): esta URL
# apontava pro repo OFICIAL black-forest-labs/FLUX.1-schnell - a Rodada 17
# tinha assumido (com base num comentario mais acima nesta mesma secao,
# sobre o CHECKPOINT do repo Unsloth, nao sobre este VAE) que esse repo era
# nao-gated. Confirmado (auditoria externa + revalidacao direta na pagina do
# Hugging Face) que black-forest-labs/FLUX.1-schnell E gated ("You need to
# agree to share your contact information to access this model") - um
# Invoke-WebRequest/Start-BitsTransfer sem sessao autenticada aqui sempre
# recebe HTTP 401, travando a instalacao automatica. Trocado pra
# camenduru/FLUX.1-dev (mirror comunitario revalidado: pagina sem aviso de
# gated, contem ae.safetensors de 335MB) - unica fonte confirmada como
# baixavel sem login neste momento. Ver catalog/assets/flux_vae.json (mesma
# correcao) e catalog/assets/flux_vae_mirror.json (guarda a fonte oficial
# gated, pra quem preferir baixar manualmente autenticado).
Download-GGUF -Name "Flux VAE (ae.safetensors)" `
    -Url "https://huggingface.co/camenduru/FLUX.1-dev/resolve/main/ae.safetensors" `
    -Dest (Join-Path $imageModelsDir "ae.safetensors")

Download-GGUF -Name "Flux CLIP-L Encoder" `
    -Url "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" `
    -Dest (Join-Path $imageModelsDir "clip_l.safetensors")

Download-GGUF -Name "Flux T5XXL FP8 Encoder" `
    -Url "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors" `
    -Dest (Join-Path $imageModelsDir "t5xxl_fp8_e4m3fn.safetensors")

# --- SDXL Base 1.0 + VAE fix (sem o fix, gera imagem preta - confirmado em teste manual) ---
Download-GGUF -Name "SDXL Base 1.0" `
    -Url "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" `
    -Dest (Join-Path $imageModelsDir "sd_xl_base_1.0.safetensors")

# PHX-FIX (auditoria 2026-08-20, Secao 14): a URL apontava pra
# ".../resolve/main/sdxl_vae-fp16-fix.safetensors", mas esse nome de
# arquivo nao existe no repo madebyollin/sdxl-vae-fp16-fix - o arquivo
# real la se chama "sdxl_vae.safetensors" (confirmado pela auditoria
# externa: HTTP 404). O nome LOCAL (-Dest) continua "sdxl_vae-fp16-fix.
# safetensors" de proposito - e a substring que
# phoenix_kernel/runtime/drivers/sd_cpp.py._find_component() procura pro
# perfil "sdxl-checkpoint" (Juggernaut/SDXL/DreamShaper); so o segmento
# REMOTO da URL precisava mudar.
Download-GGUF -Name "SDXL VAE Fix" `
    -Url "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl_vae.safetensors" `
    -Dest (Join-Path $imageModelsDir "sdxl_vae-fp16-fix.safetensors")

# --- catalog/assets/*.json: mesmo schema que o AssetManager espera (schema/type/name/
# provider/provider_data/filename). Cria também um "flux.json" e "sdxl.json" genéricos
# (alias), porque quando uma missão pede o alvo genérico "flux"/"sdxl" sem quantização
# especifica, é esse nome de arquivo que o AssetManager vai procurar no catálogo.
 $catalogAssetsDir = Join-Path $PhoenixRoot "catalog\assets"
if (-not (Test-Path $catalogAssetsDir)) { New-Item -ItemType Directory -Force -Path $catalogAssetsDir | Out-Null }

function Write-AssetCatalogEntry {
    param([string]$AssetId, [string]$Name, [string]$Url, [string]$Filename, [string]$TargetDir)
    $entry = [ordered]@{
        schema        = "1.0"
        type          = "asset"
        name          = $Name
        provider      = "http"
        provider_data = @{ url = $Url }
        filename      = $Filename
        target_dir    = $TargetDir
    }
    $entry | ConvertTo-Json | Set-Content -Path (Join-Path $catalogAssetsDir "$AssetId.json") -Encoding UTF8
}

Write-AssetCatalogEntry -AssetId "flux" -Name "Flux.1-schnell Q4_K_M (default)" `
    -Url "https://huggingface.co/unsloth/FLUX.1-schnell-GGUF/resolve/main/flux1-schnell-Q4_K_M.gguf?download=true" `
    -Filename "flux1-schnell-Q4_K_M.gguf" -TargetDir $imageModelsDir

Write-AssetCatalogEntry -AssetId "flux1-schnell-Q4_K_M" -Name "Flux.1-schnell Q4_K_M GGUF" `
    -Url "https://huggingface.co/unsloth/FLUX.1-schnell-GGUF/resolve/main/flux1-schnell-Q4_K_M.gguf?download=true" `
    -Filename "flux1-schnell-Q4_K_M.gguf" -TargetDir $imageModelsDir

Write-AssetCatalogEntry -AssetId "sdxl" -Name "SDXL Base 1.0 (default)" `
    -Url "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" `
    -Filename "sd_xl_base_1.0.safetensors" -TargetDir $imageModelsDir

Write-Host "[OK] Modelos de imagem e catalogo do AssetManager prontos em $imageModelsDir" -ForegroundColor Green

# =====================================================================
# BOOT DA API — PHX-RECREATE
# =====================================================================
Write-Host "`n=== INICIANDO PHOENIX ENGINE ===" -ForegroundColor Green
 $pythonExe = if ($IsWindows) { ".\.venv\Scripts\python.exe" } else { ".\.venv/bin/python" }

$apiPortReady = Stop-PhoenixManagedPort -Port 8000 -Name "Phoenix Engine API" -ExpectedMarkers @(
    "api_server.py", "phoenix-engine", "phoenix_engine"
)
if (-not $apiPortReady) {
    return (& $failContract "Porta 8000 ocupada por processo externo; Phoenix API nao pode ser recriada com seguranca." "PX034")
}

 $proc = Start-Process $pythonExe -ArgumentList "api_server.py" -WorkingDirectory $PhoenixRoot -PassThru -NoNewWindow

 $apiReady = $false
for ($i = 1; $i -le 150; $i++) {
    Start-Sleep -Seconds 2
    if ($proc.HasExited) { return (& $failContract "api_server encerrou prematuramente." "PX012") }
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:8000/health" -Method GET -TimeoutSec 2
        if ($response.status -eq "healthy") { $apiReady = $true; break }
    } catch {}
}

if ($apiReady) {
    $commonArtifacts = @("api_server", "llama_cpp_vulkan", "python_runtime", "searxng-phoenix", "searxng-webui", "phoenix_studio", "open_webui")
    if ($phoenixDiffusionBuildOk) { $commonArtifacts += "phoenix_diffusion_vulkan" }
    return @{ Name="Common"; Version="7.2.1"; Success=$true; ErrorCode=""; Warnings=$commonWarnings; Errors=@(); RestartRequired=$false; Artifacts=$commonArtifacts; Timestamp=Get-Date }
} else {
    return (& $failContract "API nao respondeu ao health check." "PX013")
}
