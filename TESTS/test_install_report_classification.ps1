# test_install_report_classification.ps1
#
# PHX-NEW (auditoria 2026-08-20, "Runtime policy / LM Studio opcional /
# portas corretas" - Target 1, Seção 8/17): teste standalone (mesmo
# padrão dos test_*.py na raiz - roda com execução real, não só leitura
# de código) que prova a classificação CORE_REQUIRED vs OPTIONAL do
# relatório final do instalador.
#
# IMPORTANTE: em vez de copiar a lógica de $__OptionalWarningPatterns /
# Get-OptionalWarningLabel manualmente aqui (o que criaria risco de
# "drift" - o teste continuar passando mesmo que o arquivo real mude),
# este script EXTRAI e EXECUTA o trecho real de ../install_phoenix.ps1
# via parser de AST do PowerShell. Se alguém editar a classificação em
# install_phoenix.ps1 sem atualizar o comportamento esperado abaixo, os
# testes quebram - não silenciosamente ficam desatualizados.
#
# Rodar: pwsh -NoProfile -File tests/test_install_report_classification.ps1

$__installScriptPath = Join-Path $PSScriptRoot "../install_phoenix.ps1"
$__installTokens = $null
$__installErrs = $null
$__ast = [System.Management.Automation.Language.Parser]::ParseFile($__installScriptPath, [ref]$__installTokens, [ref]$__installErrs)
if ($__installErrs.Count -gt 0) {
    Write-Host "FALHOU: install_phoenix.ps1 tem erro de sintaxe - não dá pra extrair a lógica real." -ForegroundColor Red
    exit 1
}

# Extrai a atribuição de $__OptionalWarningPatterns e a função
# Get-OptionalWarningLabel do AST real, pelo texto exato (Extent), e
# executa esse texto neste escopo - é literalmente o código de produção
# rodando, não uma cópia à mão.
$__patternsAssignStmt = $__ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$__OptionalWarningPatterns'
}, $true)
$__funcDef = $__ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Get-OptionalWarningLabel'
}, $true)

if (-not $__patternsAssignStmt -or -not $__funcDef) {
    Write-Host "FALHOU: não achei \$__OptionalWarningPatterns / Get-OptionalWarningLabel em install_phoenix.ps1 (renomeado?)." -ForegroundColor Red
    exit 1
}

Invoke-Expression $__patternsAssignStmt.Extent.Text
Invoke-Expression $__funcDef.Extent.Text

# PHX-NOTE: a função Show-Report abaixo É uma reconstrução manual do
# bloco de impressão dentro do `finally { }` de install_phoenix.ps1 (esse
# trecho não é uma function nomeada lá - é inline num script block, sem
# um nó de AST fácil de extrair isoladamente sem also puxar
# Stop-Transcript/Read-Host, que não fazem sentido rodar num teste). A
# extração acima (Get-OptionalWarningLabel + $__OptionalWarningPatterns)
# cobre a parte que decide "isso é opcional ou não" - a parte que decide
# "onde é que essa classificação aparece no relatório impresso" abaixo é
# testada por espelhamento estrutural (mesma sequência de passos), não
# por extração de AST.
function Show-Report {
    param([array]$report)

    $warningCount = 0
    Write-Host "`n-- CORE STATUS (obrigatorio para a Phoenix rodar) --" -ForegroundColor Cyan
    $optionalBuckets = @{}
    $genericWarnings = @()
    $coreFailures = @()

    foreach ($entry in $report) {
        $status = if ($entry.Success) { "OK" } else { "Failed" }
        $color = if ($entry.Success) { "Green" } else { "Red" }
        Write-Host ("[{0}] {1,-12} Tempo: {2}s" -f $status, "$($entry.Name)...", $entry.Duration) -ForegroundColor $color
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
    }

    Write-Host "`n-- OPTIONAL STATUS (nao bloqueia a Phoenix) --" -ForegroundColor Cyan
    if ($optionalBuckets.Count -eq 0) { Write-Host "    (nenhum aviso de componente opcional)" -ForegroundColor Gray }
    else { foreach ($label in $optionalBuckets.Keys) { Write-Host ("[WARN] {0}: {1}" -f $label, ($optionalBuckets[$label] -join " | ")) -ForegroundColor Yellow } }

    Write-Host "`n-- WARNINGS (genericos) --" -ForegroundColor Cyan
    if ($genericWarnings.Count -eq 0) { Write-Host "    (nenhum)" -ForegroundColor Gray }
    else { foreach ($w in $genericWarnings) { Write-Host "[WARN] $w" -ForegroundColor Yellow } }

    Write-Host "`n-- ACTION REQUIRED --" -ForegroundColor Cyan
    if ($coreFailures.Count -gt 0) { Write-Host ("[X] Modulo(s) CORE falharam: {0}." -f ($coreFailures -join ", ")) -ForegroundColor Red }
    else { Write-Host "Nenhuma acao critica para rodar Phoenix." -ForegroundColor Green }

    return @{ OptionalBuckets = $optionalBuckets; GenericWarnings = $genericWarnings; CoreFailures = $coreFailures; WarningCount = $warningCount }
}

Write-Host "=== CENARIO 1: instalacao real do usuario (LM Studio ausente, Docker ok, tudo mais ok) ===" -ForegroundColor Magenta
$scenario1 = @(
    @{ Name = "PowerShell"; Success = $true; Duration = 1.2; Warnings = @() }
    @{ Name = "Storage"; Success = $true; Duration = 0.5; Warnings = @() }
    @{ Name = "OS"; Success = $true; Duration = 45.3; Warnings = @("Self-test 'LM Studio CLI' falhou", "Self-test 'PowerToys' falhou") }
    @{ Name = "Common"; Success = $true; Duration = 120.7; Warnings = @() }
)
$r1 = Show-Report -report $scenario1
$t1ok = ($r1.CoreFailures.Count -eq 0) -and ($r1.OptionalBuckets.ContainsKey("LM Studio")) -and ($r1.OptionalBuckets.ContainsKey("PowerToys")) -and ($r1.GenericWarnings.Count -eq 0)

Write-Host "`n=== CENARIO 2: Docker ausente (achado grave desta auditoria) ===" -ForegroundColor Magenta
$scenario2 = @(
    @{ Name = "PowerShell"; Success = $true; Duration = 1.0; Warnings = @() }
    @{ Name = "Storage"; Success = $true; Duration = 0.4; Warnings = @() }
    @{ Name = "OS"; Success = $true; Duration = 30.1; Warnings = @("Docker Desktop nao instalado (winget falhou). Recursos opcionais (Ollama/Open WebUI) indisponiveis - Phoenix continua com llama.cpp nativo.") }
    @{ Name = "Common"; Success = $true; Duration = 60.0; Warnings = @("Docker nao encontrado - Ollama e Open WebUI (opcionais) nao foram provisionados. Phoenix continua com llama.cpp nativo.", "Docker nao encontrado - SearXNG (busca web, opcional) nao foi provisionado.") }
)
$r2 = Show-Report -report $scenario2
$t2ok = ($r2.CoreFailures.Count -eq 0) -and ($r2.OptionalBuckets.ContainsKey("Docker/WSL2")) -and ($r2.OptionalBuckets["Docker/WSL2"].Count -eq 3) -and ($r2.GenericWarnings.Count -eq 0)

Write-Host "`n=== CENARIO 3: falha real de um modulo CORE (ex: Storage) ===" -ForegroundColor Magenta
$scenario3 = @(
    @{ Name = "PowerShell"; Success = $true; Duration = 1.0; Warnings = @() }
    @{ Name = "Storage"; Success = $false; Duration = 0.2; Warnings = @() }
)
$r3 = Show-Report -report $scenario3
$t3ok = ($r3.CoreFailures.Count -eq 1) -and ($r3.CoreFailures[0] -eq "Storage")

Write-Host "`n=== CENARIO 4: warning generico nao classificado (nao deve sumir) ===" -ForegroundColor Magenta
$scenario4 = @(
    @{ Name = "Common"; Success = $true; Duration = 10.0; Warnings = @("Algum aviso totalmente novo que nenhum padrao conhece") }
)
$r4 = Show-Report -report $scenario4
$t4ok = ($r4.GenericWarnings.Count -eq 1) -and ($r4.OptionalBuckets.Count -eq 0)

Write-Host "`n=== RESULTADOS ===" -ForegroundColor Cyan
$all = @(
    @{n="Cenario 1 (LM Studio/PowerToys ausentes, sem falha core)"; ok=$t1ok},
    @{n="Cenario 2 (Docker ausente, 3 warnings agrupados sob Docker/WSL2)"; ok=$t2ok},
    @{n="Cenario 3 (falha real de modulo CORE detectada em ACTION REQUIRED)"; ok=$t3ok},
    @{n="Cenario 4 (warning generico nao classificado preservado)"; ok=$t4ok}
)
$passed = ($all | Where-Object { $_.ok }).Count
$failed = ($all | Where-Object { -not $_.ok }).Count
foreach ($t in $all) { Write-Host "$(if ($t.ok) {'OK  '} else {'FAIL'}) $($t.n)" -ForegroundColor $(if ($t.ok) {'Green'} else {'Red'}) }
Write-Host "`n$passed passaram, $failed falharam"
if ($failed -gt 0) { exit 1 }
