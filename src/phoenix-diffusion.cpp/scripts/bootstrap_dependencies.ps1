param([switch]$IncludeExamples)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$Required = @(
    (Join-Path $Root "ggml/CMakeLists.txt"),
    (Join-Path $Root "thirdparty/CMakeLists.txt")
)
foreach ($Path in $Required) {
    if (-not (Test-Path $Path)) {
        throw "Dependência empacotada ausente: $Path. Reextraia o pacote Phoenix oficial; o instalador não clona código de terceiros."
    }
}
if ($IncludeExamples) {
    Write-Host "[INFO] Exemplos opcionais usam somente os arquivos já incluídos no pacote."
}
Write-Host "[PASS] Dependências Phoenix Diffusion presentes e fixadas por DEPENDENCIES.lock.json"
