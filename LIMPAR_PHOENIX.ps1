# ============================================================================
# LIMPAR_PHOENIX.ps1 — organiza a raiz da PHOENIX 4.5, deixando só o essencial.
#
# SEGURO: NÃO apaga nada. MOVE os arquivos descartáveis para uma pasta
# "_LIXO_LIMPEZA" na raiz. Você confere lá dentro e, se estiver tudo certo,
# apaga a pasta _LIXO_LIMPEZA inteira de uma vez (ou restaura o que quiser).
#
# Rode dentro de C:\PROJETO COMPLETO\PHOENIX 4.5:
#     powershell -ExecutionPolicy Bypass -File LIMPAR_PHOENIX.ps1
# ============================================================================

$lixo = "_LIXO_LIMPEZA"
if (-not (Test-Path $lixo)) { New-Item -ItemType Directory -Path $lixo | Out-Null }

function Mover($padrao, $motivo) {
    Get-ChildItem -Path . -Filter $padrao -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -ne $lixo) {
            Write-Host ("  [{0}] {1}" -f $motivo, $_.Name)
            Move-Item -LiteralPath $_.FullName -Destination $lixo -Force -ErrorAction SilentlyContinue
        }
    }
}

Write-Host "=== Movendo scripts de TESTE que o Claude entregou (nao sao do projeto) ==="
Mover "TESTAR_*.py"         "teste"
Mover "test_aviary_swarm_dispatch*" "teste-solto"
Mover "test_ollama_second_option*"  "teste-solto"
Mover "bissecao_lipton*"    "debug"
Mover "lipton_payload_*.json" "debug"
Mover "check_cloud_sync*"   "debug"
Mover "inspecionar_docx_estrutural*" "debug"
Mover "phoenix_diagnostic*" "debug"
Mover "COLAR_no_*.py"       "trecho-pra-colar"

Write-Host "`n=== Movendo LEIA-MEs e notas dos patches (ja aplicados) ==="
Mover "LEIA-ME_*"           "leia-me-de-patch"
Mover "LEIA-ME.md"          "leia-me-de-patch"
Mover "PATCH_NOTES*"        "nota-de-patch"
Mover "APLICAR_PATCH*"      "script-de-patch"

Write-Host "`n=== Movendo MANIFESTOS e verificadores de release (regeneraveis) ==="
Mover "MANIFEST_*"          "manifesto"
Mover "verify_release_clean*" "release"
Mover "build_release_zip*"  "release"
Mover "VERIFIED_UNCHANGED_SHA256*" "release"

Write-Host "`n=== Movendo BENCHMARKS e docs de auditoria pontuais ==="
Mover "BENCHMARK_PARALELISMO*" "benchmark"
Mover "benchmark_image_models*" "benchmark"
Mover "AUDITORIA_FLUX_RX580*" "auditoria"
Mover "PHOENIX_EXECUTION_ARBITER_NOTES*" "nota"
Mover "PHOENIX_GPU_ONLY_EXCLUSIVE_POLICY*" "nota"
Mover "PHOENIX_RX580_PIPELINE_FIX*" "nota"
Mover "PHOENIX_STATUS*"     "nota"
Mover "taxonomy_benchmark_*" "benchmark-data"

Write-Host "`n=== Movendo RESULTADOS de teste e bundles antigos ==="
Mover "RESULTADO_*.xlsx"    "resultado-de-teste"
Mover "*.bundle"            "bundle-antigo"
Mover "organizar_pasta_phoenix*" "script-organizador"

Write-Host "`n=== Movendo pastas de backup/cache descartaveis ==="
foreach ($p in @("backup_patch_vulkan_router_20260830-125800", "PATCH_FILES", "patches", "__pycache__", ".pytest_cache")) {
    if (Test-Path $p) {
        Write-Host ("  [pasta] {0}" -f $p)
        Move-Item -LiteralPath $p -Destination $lixo -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "`n============================================================"
Write-Host " PRONTO. Tudo foi movido para: $lixo"
Write-Host " Confira essa pasta. Se estiver tudo certo, apague-a:"
Write-Host "   Remove-Item -Recurse -Force $lixo"
Write-Host "============================================================"
