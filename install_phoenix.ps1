# install_phoenix.ps1
# Bootstrapper Oficial da Phoenix Engine 5.0 - Enterprise Grade

# =====================================================================
# PHOENIX RESOURCE POLICY (revisada 31/08 - ver
# PHOENIX_GPU_ONLY_EXCLUSIVE_POLICY.md) - chat/documentos usam CPU por
# padrão nesta GPU (RX 580/Polaris: Vulkan corrompe texto, bug confirmado
# por bisseção manual); GPU só entra como instância explícita e
# auto-testada (sanity_check()), nunca como default silencioso. Imagem
# (sd.cpp/Flux) continua GPU pura - sem caminho CPU viável, bug conhecido
# ali é outro (crash de argumento/arquitetura, corrigido em 31/08).
# Antes de iniciar outra carga de IA, encerra os demais runtimes gerenciados.
# =====================================================================
 $env:PHOENIX_LLM_DEVICE = "CPU"
 $env:PHOENIX_IMAGE_DEVICE = "GPU"
 $env:PHOENIX_LLM_NGL = "0"
 $env:PHOENIX_LLM_GPU_DEVICE = "Vulkan0"
 $env:PHOENIX_DOCUMENT_LLM_POLICY = "cpu"
 # PHX-FIX (31/08): estava "999" (full offload) - o próprio
 # document_llm_worker.py documenta que essa combinação sozinha ainda
 # corrompeu a geração em teste real; "1" é o valor que, combinado com o
 # override output.weight=CPU (fixo no código, não configurável aqui),
 # restaurou correctness. O self-test continua sendo o gate real de
 # qualquer forma - isto só evita gastar uma tentativa GPU inteira numa
 # configuração já sabida como pior.
 $env:PHOENIX_DOCUMENT_GPU_NGL = "1"
 $env:PHOENIX_DOCUMENT_GPU_DEVICE = "Vulkan0"

# PHX-NEW (2026-08-23, pedido do usuário: "esta rodando via cpu, mas
# podemos pensar em rodar via gpu, nao?" - ele viu o audiolivro sintetizando
# bloco por bloco em CPU pura e perguntou sobre GPU): o pacote kokoro-onnx
# (ver phoenix_kernel/runtime/drivers/kokoro_tts.py) já detecta sozinho, em
# tempo de execução, se existe uma distribuição acelerada do onnxruntime
# instalada (ver kokoro_onnx/session.py::resolve_providers()) - não precisa
# de NENHUMA mudança no nosso código, só trocar QUAL pacote onnxruntime é
# instalado. onnxruntime-directml funciona com qualquer GPU DirectX 12 no
# Windows (inclusive a RX 580 do usuário - AMD sem CUDA/ROCm, mas com
# suporte DX12 completo, o mesmo caminho já usado pelo Vulkan do
# stable-diffusion.cpp) - mas é MUTUAMENTE EXCLUSIVO com o onnxruntime
# normal (mesmo módulo Python, só pode ter um instalado) e só existe wheel
# pra Windows (confirmado nesta auditoria: 'pip download
# onnxruntime-directml --platform manylinux2014_x86_64' não acha nada,
# só win_amd64). Por isso é "CPU" por padrão aqui - troque pra "GPU" nesta
# linha se quiser que o instalador (install/common.ps1) instale a variante
# DirectML em vez da normal na próxima vez que rodar.
#
# ATUALIZAÇÃO (2026-08-23, MESMO DIA - teste real na máquina do usuário,
# RX 580 + driver AMD atual): GPU=ON foi testado de verdade e FALHOU em
# TODOS os blocos de um audiolivro - o onnxruntime-directml não consegue
# executar o nó ConvTranspose do vocoder do Kokoro nesta GPU/driver
# (erro nativo do Windows "Parâmetro incorreto", HRESULT 80070057, visível
# no terminal do Phoenix Engine como "[E:onnxruntime...
# DmlExecutionProvider..."). Ou seja: hoje, nesta combinação de hardware,
# GPU=ON não é "mais lento" - é "não sintetiza nada" (o audiolivro termina
# com "nenhum bloco foi sintetizado com sucesso"). Deixado como "CPU" com
# ainda mais convicção agora - só mude pra "GPU" se quiser testar de novo
# depois de uma atualização de driver AMD ou do próprio onnxruntime-directml
# que resolva esse gap de suporte a operadores.
 $env:PHOENIX_TTS_DEVICE = "CPU"

# CORREÇÃO BUG-001: Força UTF-8 no PS 5.1 para não quebrar acentos na fase inicial
if ($PSVersionTable.PSVersion.Major -lt 6) {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
}

 $ErrorActionPreference = "Stop"
 $ProgressPreference = "SilentlyContinue"
 $env:GIT_TERMINAL_PROMPT = "0"

 $PhoenixRoot = $PSScriptRoot
 $InstallDir = Join-Path $PhoenixRoot "install"
Set-Location $PhoenixRoot

# Setup de Logs
 $logDir = Join-Path $PhoenixRoot "logs/install"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
 $logFile = Join-Path $logDir "install_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
 $jsonLogFile = Join-Path $logDir "install_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
Start-Transcript -Path $logFile -Force | Out-Null

 $report = @()
 $needsRestart = $false
 $warningCount = 0
 $osRestartPending = $false
 $fatalError = $false

function Write-StructuredLog {
    param([hashtable]$Result)
    $logEntry = @{
        timestamp = $Result.Timestamp
        module = $Result.Name
        success = $Result.Success
        error_code = $Result.ErrorCode
        duration = $Result.Duration
        warnings = $Result.Warnings
    }
    $logEntry | ConvertTo-Json -Compress | Out-File -FilePath $jsonLogFile -Append -Encoding utf8
}

# PHX-NEW (auditoria 2026-08-20, "Runtime policy / LM Studio opcional /
# portas corretas" - Seções 3 e 8): classificação formal CORE_REQUIRED vs
# OPTIONAL. Achado real do usuário: o relatório final jogava TODOS os
# warnings de TODOS os módulos numa única linha "Warnings: X, Y, Z"
# ilegível, misturando coisas que realmente impedem a Phoenix de rodar
# (nenhuma, no fluxo atual - todo o Common é best-effort) com coisas
# totalmente opcionais (winget do LM Studio falhou, Docker offline,
# PowerToys/VLC/Firefox/Chrome não instalados). Isso fazia o usuário
# achar que a instalação tinha falhado quando na verdade só um componente
# OPCIONAL não estava disponível. Esta lista de padrões classifica cada
# string de warning (texto livre vindo de common.ps1/windows.ps1/
# storage_scanner.ps1) como pertencente a um componente OPCIONAL
# conhecido; qualquer warning que não bater com nenhum padrão continua
# sendo um warning "genérico" (mostrado à parte, não escondido).
# PHX-FIX (verificação real com pwsh, não só leitura): a ordem importa -
# um warning como "Docker nao encontrado - Ollama e Open WebUI
# (opcionais) nao foram provisionados" MENCIONA "Ollama" mas a causa raiz
# é Docker ausente. "Docker/WSL2" tem que ser checado ANTES de
# Ollama/OpenWebUI/LM Studio, senão esses warnings (que citam os
# componentes afetados pelo nome, pra clareza do usuário) caem no bucket
# errado. Confirmado por teste real (não só leitura de código) rodando
# esta função com strings reais geradas pelo restante desta auditoria.
$__OptionalWarningPatterns = @(
    @{ Label = "Docker/WSL2"; Pattern = "docker|wsl2?|virtualiza|vt-x|amd-v" },
    @{ Label = "LM Studio";  Pattern = "lm ?studio|lmstudio|\blms\b|localhost:1234|:1234\b" },
    @{ Label = "Ollama";     Pattern = "ollama|:11434\b" },
    @{ Label = "OpenWebUI";  Pattern = "open ?web ?ui|:8010\b" },
    @{ Label = "PowerToys";  Pattern = "powertoys" },
    @{ Label = "VLC";        Pattern = "\bvlc\b" },
    @{ Label = "Firefox";    Pattern = "firefox" },
    @{ Label = "Chrome";     Pattern = "\bchrome\b" }
)

function Get-OptionalWarningLabel {
    param([string]$WarningText)
    foreach ($p in $__OptionalWarningPatterns) {
        if ($WarningText -match $p.Pattern) { return $p.Label }
    }
    return $null
}

function Invoke-Step {
    param([string]$Name, [string]$ScriptPath, [hashtable]$Arguments = @{})
    
    if (-not (Test-Path $ScriptPath)) {
        return @{ Name = $Name; Success = $false; ErrorCode = "PX000"; Errors = @("Arquivo nao encontrado: $ScriptPath"); Warnings = @(); RestartRequired = $false; Duration = 0; Timestamp = Get-Date; Artifacts = @(); Version = "N/A" }
    }

    $sw = [Diagnostics.Stopwatch]::StartNew()
    $rawResult = & $ScriptPath @Arguments
    $sw.Stop()
    
    # Validação estrita do contrato (Hashtable com chaves obrigatórias)
    $requiredKeys = @("Success", "Errors", "Warnings", "Artifacts", "RestartRequired")
    $isValid = $true
    
    if ($rawResult -isnot [System.Collections.IDictionary]) {
        $isValid = $false
    } else {
        foreach ($key in $requiredKeys) {
            if (-not $rawResult.ContainsKey($key)) { $isValid = $false; break }
        }
    }

    if (-not $isValid) {
        $rawResult = @{ Success = $false; ErrorCode = "PX002"; Errors = @("Modulo nao retornou um contrato Hashtable valido."); Warnings = @(); RestartRequired = $false; Artifacts = @(); Version = "N/A" }
    }

    $rawResult.Name = $Name
    $rawResult.Duration = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    if (-not $rawResult.Timestamp) { $rawResult.Timestamp = Get-Date }
    if (-not $rawResult.ErrorCode) { $rawResult.ErrorCode = "PX000" }
    
    Write-StructuredLog -Result $rawResult
    return $rawResult
}

try {
    Write-Host "==================================" -ForegroundColor Cyan
    Write-Host "   PHOENIX ENGINE 5.0 BOOTSTRAP   " -ForegroundColor Cyan
    Write-Host "==================================" -ForegroundColor Cyan
    Write-Host " -> Politica de Hardware: LLM=CPU | IMAGE=GPU" -ForegroundColor Yellow

    # CORREÇÃO: Git é o PRIMEIRO passo de todos, antes até do PowerShell 7.
    # winget/apt-get não dependem de PS7 pra funcionar, e sem Git nada mais
    # (nem a clonagem dos 45 repos no common.ps1) tem como acontecer.
    # Detecção de plataforma "PS5.1-safe": Windows PowerShell 5.1 só existe
    # no Windows, então nesse caso $__isWinEarly é sempre $true sem precisar
    # de $IsWindows (que nem existe no PS 5.1).
    $__isWinEarly = ($PSVersionTable.PSVersion.Major -lt 6) -or ($IsWindows -eq $true)
    $__isLinuxEarly = ($PSVersionTable.PSVersion.Major -ge 6) -and ($IsLinux -eq $true)

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "[*] Git nao encontrado. Instalando (primeiro passo do bootstrap)..." -ForegroundColor Yellow
        if ($__isWinEarly) {
            if (Get-Command winget -ErrorAction SilentlyContinue) {
                & winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
            } else {
                Write-Host "[X] winget nao encontrado - nao e possivel instalar o Git automaticamente." -ForegroundColor Red
            }
        } elseif ($__isLinuxEarly) {
            $needsSudo = (id -u) -ne "0"
            $aptPrefix = if ($needsSudo -and (Get-Command sudo -ErrorAction SilentlyContinue)) { "sudo" } else { "" }
            Invoke-Expression "$aptPrefix apt-get update -y" 2>&1 | Out-Null
            Invoke-Expression "$aptPrefix apt-get install -y git" 2>&1 | Out-Null
        }
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            throw "[PX001] Git nao pode ser instalado automaticamente. Instale manualmente (winget install Git.Git / apt-get install git) e rode o instalador novamente."
        }
    }
    Write-Host "[OK] Git disponivel em: $((Get-Command git).Source)" -ForegroundColor Green

    # 0. GARANTIR POWERSHELL 7 LTS (Passa o caminho do bootstrap explicitamente)
    $psResult = Invoke-Step "PowerShell" (Join-Path $InstallDir "powershell.ps1") -Arguments @{ BootstrapPath = $PSCommandPath }
    $report += $psResult
    
    # Se o módulo avisar que precisa reiniciar (porque acabou de instalar o PS7)
    if ($psResult.RestartRequired) {
        $pwshPath = "$env:ProgramFiles\PowerShell\7\pwsh.exe"
        if (Test-Path $pwshPath) {
            Write-Host "[*] Reexecutando bootstrap no PowerShell 7..." -ForegroundColor Green
            Stop-Transcript | Out-Null
            
            # CORREÇÃO BUG-001: -NoNewWindow faz o PS7 rodar nesta mesma janela.
            # -Wait faz o PS5.1 segurar a janela até o PS7 terminar toda a instalação.
            Start-Process $pwshPath -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"" -Wait -NoNewWindow
            
            # Saída limpa após o PS7 concluir
            exit
        }
    }

    if (-not $psResult.Success) { throw "[$($psResult.ErrorCode)] $($psResult.Errors[0])" }

    # CORREÇÃO DO BUG "Sistema operacional nao suportado" no Windows puro:
    # se chegamos até aqui ainda no PS 5.1 (o step PowerShell reportou
    # sucesso mas não reiniciou pra PS7 de verdade - ex: winget do PS7
    # falhou silenciosamente), $IsWindows/$IsLinux NÃO EXISTEM no PS 5.1
    # e sempre caem no "else". Windows PowerShell 5.1 só roda no Windows,
    # então tratamos isso como Windows em vez de travar o provisionamento.
    if ($PSVersionTable.PSVersion.Major -ge 6) {
        $osScriptName = if ($IsWindows) { "windows.ps1" } elseif ($IsLinux) { "linux.ps1" } else { throw "Sistema operacional nao suportado (PS7 sem IsWindows/IsLinux)." }
    } else {
        Write-Host "[!] Continuando em Windows PowerShell 5.1 (upgrade pro PS7 nao foi confirmado). Alguns recursos podem ficar limitados." -ForegroundColor Yellow
        $osScriptName = "windows.ps1"

        # CORREÇÃO CRÍTICA: storage_scanner.ps1 (2x) e common.ps1 (13x)
        # checam $IsWindows diretamente, não passam pelo $osScriptName.
        # Em PS 5.1 essa variável nunca existiu de verdade (é $null),
        # então mesmo sabendo aqui que é Windows, esses dois arquivos
        # cairiam no branch Linux por engano. Definindo manualmente em
        # escopo global, qualquer script chamado depois (mesmo em scope
        # filho via '&') enxerga o valor certo.
        $global:IsWindows = $true
        $global:IsLinux = $false
        $global:IsMacOS = $false
    }

    # 1. SCANNER DE ARMAZENAMENTO
    $report += Invoke-Step "Storage" (Join-Path $InstallDir "storage_scanner.ps1")
    if (-not $report[-1].Success) { throw "[$($report[-1].ErrorCode)] $($report[-1].Errors[0])" }

    # 2. CAMADA ESPECIFICA DO SO
    $report += Invoke-Step "OS" (Join-Path $InstallDir $osScriptName)
    if (-not $report[-1].Success) { throw "[$($report[-1].ErrorCode)] $($report[-1].Errors[0])" }

    # CORREÇÃO BUG-002: se o modulo OS instalou algo que exige reinicio/relogin
    # (ex: Docker Desktop recem-instalado no Windows), paramos AQUI em vez de
    # seguir pro Common e tentar usar um Docker que ainda nao terminou de subir.
    if ($report[-1].RestartRequired) {
        Write-Host "`n[!] Pre-requisitos foram instalados e precisam de reinicio/relogin antes de continuar." -ForegroundColor Yellow
        Write-Host "    (Normalmente: Docker Desktop recem-instalado. Abra-o manualmente uma vez e faça login.)" -ForegroundColor Yellow
        Write-Host "    Depois disso, rode o instalador novamente para concluir o provisionamento." -ForegroundColor Yellow
        $needsRestart = $true
        $osRestartPending = $true
        Stop-Transcript | Out-Null
        exit
    }

    # 3. CAMADA COMUM
    $report += Invoke-Step "Common" (Join-Path $InstallDir "common.ps1")
    if (-not $report[-1].Success) { throw "[$($report[-1].ErrorCode)] $($report[-1].Errors[0])" }

} catch {
    Write-Host "`n[X] ERRO FATAL DURANTE O PROVISIONAMENTO:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    $fatalError = $true
} finally {
    # Se estamos reiniciando, não imprimimos o relatório ainda (ele será impresso no final do PS7)
    if (-not (($psResult -and $psResult.RestartRequired) -or $osRestartPending)) {
        # PHX-FIX (auditoria 2026-08-20, "Runtime policy / LM Studio opcional
        # / portas corretas" - Seção 8): relatório final reescrito pra
        # separar CORE STATUS / OPTIONAL STATUS / WARNINGS / ACTION REQUIRED
        # em vez de uma única linha "Warnings: X, Y, Z" ilegível por módulo.
        # Os módulos (PowerShell/Storage/OS/Common) em si SÃO todos
        # CORE_REQUIRED (são a fundação do bootstrap - sem eles a Phoenix
        # não instala) - o que muda é que os WARNINGS que cada um relata
        # internamente são, na maioria, sobre componentes OPCIONAIS (LM
        # Studio, Ollama, OpenWebUI, Docker/WSL2, PowerToys, VLC, Firefox,
        # Chrome) que nunca deveriam ler como "a Phoenix falhou".
        Write-Host "`n===================================" -ForegroundColor Cyan
        Write-Host "      PHOENIX INSTALL REPORT        " -ForegroundColor Cyan
        Write-Host "===================================" -ForegroundColor Cyan
        Write-Host "PowerShell ......... $($PSVersionTable.PSVersion.ToString())" -ForegroundColor Gray

        Write-Host "`n-- CORE STATUS (obrigatorio para a Phoenix rodar) --" -ForegroundColor Cyan
        $optionalBuckets = @{}
        $genericWarnings = @()
        $coreFailures = @()

        foreach ($entry in $report) {
            $status = if ($entry.Success) { "OK" } else { "Failed" }
            $color = if ($entry.Success) { "Green" } else { "Red" }
            $time = $entry.Duration
            $version = if ($entry.Version -and $entry.Version -ne "N/A") { "v$($entry.Version)" } else { "" }

            Write-Host ("[{0}] {1,-12} {2,-10} Tempo: {3}s" -f $status, "$($entry.Name)...", $version, $time) -ForegroundColor $color
            if (-not $entry.Success) { $coreFailures += $entry.Name }

            foreach ($w in $entry.Warnings) {
                $warningCount++
                $label = Get-OptionalWarningLabel -WarningText $w
                if ($label) {
                    if (-not $optionalBuckets.ContainsKey($label)) { $optionalBuckets[$label] = @() }
                    $optionalBuckets[$label] += $w
                } else {
                    $genericWarnings += "[$($entry.Name)] $w"
                }
            }
            if ($entry.RestartRequired) { $needsRestart = $true }
        }

        Write-Host "`n-- OPTIONAL STATUS (nao bloqueia a Phoenix - llama.cpp/Aviary continuam) --" -ForegroundColor Cyan
        if ($optionalBuckets.Count -eq 0) {
            Write-Host "    (nenhum aviso de componente opcional)" -ForegroundColor Gray
        } else {
            foreach ($label in $optionalBuckets.Keys) {
                Write-Host ("[WARN] {0}: {1}" -f $label, ($optionalBuckets[$label] -join " | ")) -ForegroundColor Yellow
            }
        }

        Write-Host "`n-- WARNINGS (nao classificados como componente opcional conhecido) --" -ForegroundColor Cyan
        if ($genericWarnings.Count -eq 0) {
            Write-Host "    (nenhum)" -ForegroundColor Gray
        } else {
            foreach ($w in $genericWarnings) {
                Write-Host "[WARN] $w" -ForegroundColor Yellow
            }
        }

        Write-Host "`n-- ACTION REQUIRED --" -ForegroundColor Cyan
        if ($coreFailures.Count -gt 0) {
            Write-Host ("[X] Modulo(s) CORE falharam: {0}. Veja o log para detalhes." -f ($coreFailures -join ", ")) -ForegroundColor Red
        } else {
            Write-Host "Nenhuma acao critica para rodar Phoenix." -ForegroundColor Green
        }

        Write-Host "-----------------------------------" -ForegroundColor Cyan
        Write-Host "Restart Required .. $(if ($needsRestart) {'YES'} else {'NO'})" -ForegroundColor $(if ($needsRestart) {'Yellow'} else {'Gray'})
        Write-Host "Warnings totais ... $warningCount ($($optionalBuckets.Count) categoria(s) opcional(is), $($genericWarnings.Count) generico(s))" -ForegroundColor $(if ($warningCount -gt 0) {'Yellow'} else {'Gray'})
        Write-Host "Log (Texto) ....... $logFile" -ForegroundColor DarkGray
        Write-Host "Log (JSON) ........ $jsonLogFile" -ForegroundColor DarkGray
        Write-Host "===================================`n" -ForegroundColor Cyan

        Stop-Transcript | Out-Null

        # Saída limpa
        if ($Host.Name -eq "ConsoleHost") { Read-Host "Pressione ENTER para sair" }
    }
}

# CORREÇÃO: sem isso, o processo sempre terminava com exit code 0, mesmo
# apos um erro fatal (a excecao era capturada e so impressa, nunca
# repropagada). Qualquer .bat/.sh que chame este script e cheque
# ERRORLEVEL/$? nunca detectava falha real - inclusive o Iniciar_Phoenix.bat.
if ($fatalError) {
    exit 1
}
# Phoenix Engine 3.0 © 2026
