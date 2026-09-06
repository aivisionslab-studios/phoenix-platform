<#
============================================================
 PHOENIX 3.0 - organize_and_push.ps1
============================================================
 O que faz:
  1. MOVE (nunca apaga) os arquivos soltos na raiz pra dentro das
     pastas que ja existem no projeto (docs/, install/, tools/).
  2. Isola .bak e arquivos vazios/acidentais numa pasta _backup/
     (que o .gitignore ja exclui do Git - fica no seu disco, so
     nao sobe pra nuvem).
  3. Roda em modo SIMULACAO por padrao - so IMPRIME o que faria.
     Nada e movido de verdade ate voce rodar com -Executar.
  4. Depois de organizado, mostra o status do Git e os comandos
     pra commitar e subir.

 COMO USAR:
   1) Copie este arquivo e o .gitignore pra raiz do projeto
      (E:\PHOENIX\AIVisions Platform\PHOENIX 3.0\)
   2) Abra PowerShell nessa pasta
   3) Rode PRIMEIRO em modo simulacao (seguro, so mostra o plano):
        .\organize_and_push.ps1
   4) Se o plano fizer sentido, rode de verdade:
        .\organize_and_push.ps1 -Executar
============================================================
#>

param(
    [switch]$Executar
)

$ErrorActionPreference = "Stop"
$raiz = Get-Location

function Move-Seguro {
    param([string]$Origem, [string]$DestinoPasta)

    if (-not (Test-Path $Origem)) { return }

    if (-not (Test-Path $DestinoPasta)) {
        if ($Executar) {
            New-Item -ItemType Directory -Path $DestinoPasta -Force | Out-Null
        }
    }

    $nomeArquivo = Split-Path $Origem -Leaf
    $destinoFinal = Join-Path $DestinoPasta $nomeArquivo

    if ($Executar) {
        Move-Item -Path $Origem -Destination $destinoFinal -Force
        Write-Host "  [MOVIDO] $nomeArquivo -> $DestinoPasta" -ForegroundColor Green
    } else {
        Write-Host "  [SIMULACAO] $nomeArquivo -> $DestinoPasta" -ForegroundColor Yellow
    }
}

Write-Host ""
if ($Executar) {
    Write-Host "=== MODO EXECUCAO - arquivos serao movidos de verdade ===" -ForegroundColor Red
} else {
    Write-Host "=== MODO SIMULACAO - nada sera movido, so mostra o plano ===" -ForegroundColor Cyan
    Write-Host "    (rode com -Executar quando estiver de acordo com o plano)" -ForegroundColor Cyan
}
Write-Host ""

# ------------------------------------------------------------
# 1. Documentacao solta -> docs/
# ------------------------------------------------------------
Write-Host "--- Documentacao (raiz -> docs/) ---"
$docsDestino = Join-Path $raiz "docs"
@(
    "ARCHITECTURE_V1",
    "CHANGES_GPU_FIX",
    "DOMAIN_MODEL",
    "TERMINOLOGY",
    "VISION",
    "PHOENIX_PROJECT_MAP",
    "PHOENIX_CALL_GRAPH",
    "PHOENIX_DEPENDENCY_GRAPH.json",
    "migration_report",
    "models_migration_report",
    "phoenix_models_migration",
    "phoenix_runtime_migration",
    "ERRO PHOENIX"
) | ForEach-Object {
    $candidato = Join-Path $raiz $_
    if (Test-Path $candidato) {
        Move-Seguro -Origem $candidato -DestinoPasta $docsDestino
    } else {
        # tenta com extensao comum, caso o Explorer tenha ocultado
        Get-ChildItem -Path $raiz -Filter "$_*" -File -ErrorAction SilentlyContinue | ForEach-Object {
            Move-Seguro -Origem $_.FullName -DestinoPasta $docsDestino
        }
    }
}

# ------------------------------------------------------------
# 2. Scripts de instalacao/setup -> install/
# ------------------------------------------------------------
Write-Host ""
Write-Host "--- Instaladores (raiz -> install/) ---"
$installDestino = Join-Path $raiz "install"
@(
    "Instalar_Phoenix",
    "install_phoenix",
    "install_phoenix_kernel",
    "setup_environment",
    "setup_platform"
) | ForEach-Object {
    Get-ChildItem -Path $raiz -Filter "$_*" -File -ErrorAction SilentlyContinue | ForEach-Object {
        Move-Seguro -Origem $_.FullName -DestinoPasta $installDestino
    }
}

# ------------------------------------------------------------
# 3. Ferramentas de manutencao -> tools/
# ------------------------------------------------------------
Write-Host ""
Write-Host "--- Ferramentas (raiz -> tools/) ---"
$toolsDestino = Join-Path $raiz "tools"
@(
    "generate_phoenix_map",
    "build_call_graph"
) | ForEach-Object {
    Get-ChildItem -Path $raiz -Filter "$_*" -File -ErrorAction SilentlyContinue | ForEach-Object {
        Move-Seguro -Origem $_.FullName -DestinoPasta $toolsDestino
    }
}

# ------------------------------------------------------------
# 4. Backups e arquivos acidentais -> _backup/ (fica so local, gitignored)
# ------------------------------------------------------------
Write-Host ""
Write-Host "--- Backups e arquivos acidentais (raiz -> _backup/, NAO sobe pro Git) ---"
$backupDestino = Join-Path $raiz "_backup"
Get-ChildItem -Path $raiz -Filter "*.bak" -File -ErrorAction SilentlyContinue | ForEach-Object {
    Move-Seguro -Origem $_.FullName -DestinoPasta $backupDestino
}
Get-ChildItem -Path $raiz -Filter "Novo*Documento*Texto*" -File -ErrorAction SilentlyContinue | ForEach-Object {
    Move-Seguro -Origem $_.FullName -DestinoPasta $backupDestino
}

# ------------------------------------------------------------
# 5. Limpar __pycache__ espalhados (sempre regeneravel)
# ------------------------------------------------------------
Write-Host ""
Write-Host "--- Limpando __pycache__ (sempre regeneravel pelo Python) ---"
Get-ChildItem -Path $raiz -Filter "__pycache__" -Directory -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
    if ($Executar) {
        Remove-Item -Path $_.FullName -Recurse -Force
        Write-Host "  [REMOVIDO] $($_.FullName)" -ForegroundColor Green
    } else {
        Write-Host "  [SIMULACAO] removeria $($_.FullName)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "============================================================"
if (-not $Executar) {
    Write-Host "Isso foi so uma SIMULACAO. Revise o plano acima." -ForegroundColor Cyan
    Write-Host "Se estiver de acordo, rode:  .\organize_and_push.ps1 -Executar" -ForegroundColor Cyan
    Write-Host "============================================================"
    exit 0
}
Write-Host "Organizacao concluida." -ForegroundColor Green
Write-Host "============================================================"

# ------------------------------------------------------------
# 6. Git: mostrar status e dar o proximo passo
# ------------------------------------------------------------
Write-Host ""
Write-Host "--- Verificando o repositorio Git ---"

if (-not (Test-Path (Join-Path $raiz ".git"))) {
    Write-Host "Este pasta ainda NAO e um repositorio Git." -ForegroundColor Yellow
    Write-Host "Rode: git init" -ForegroundColor Yellow
    exit 0
}

# Copia o .gitignore atualizado se ele estiver ao lado deste script
$gitignoreOrigem = Join-Path $PSScriptRoot ".gitignore"
$gitignoreDestino = Join-Path $raiz ".gitignore"
if ((Test-Path $gitignoreOrigem) -and ($gitignoreOrigem -ne $gitignoreDestino)) {
    Copy-Item -Path $gitignoreOrigem -Destination $gitignoreDestino -Force
    Write-Host "[OK] .gitignore atualizado copiado pra raiz do projeto." -ForegroundColor Green
}

Write-Host ""
Write-Host "IMPORTANTE: se 'repos/', '.venv/', 'output/' ou 'logs/' ja" -ForegroundColor Yellow
Write-Host "estavam sendo rastreados pelo Git ANTES deste .gitignore," -ForegroundColor Yellow
Write-Host "o .gitignore sozinho nao remove eles do repositorio. Rode" -ForegroundColor Yellow
Write-Host "isso UMA VEZ pra destravar (nao apaga do disco, so para de" -ForegroundColor Yellow
Write-Host "rastrear no Git):" -ForegroundColor Yellow
Write-Host ""
Write-Host "  git rm -r --cached repos/ .venv/ output/ logs/ 2>`$null" -ForegroundColor White
Write-Host ""

git status

Write-Host ""
Write-Host "--- Proximos passos pra subir pro GitHub ---" -ForegroundColor Cyan
Write-Host "  git add ." -ForegroundColor White
Write-Host "  git commit -m `"chore: organiza estrutura de pastas e atualiza .gitignore`"" -ForegroundColor White
Write-Host "  git push origin main" -ForegroundColor White
Write-Host ""
Write-Host "(se o remoto ainda nao estiver configurado, primeiro:)" -ForegroundColor Cyan
Write-Host "  git remote add origin https://github.com/aivisionslab-studios/phoenix-engine.git" -ForegroundColor White