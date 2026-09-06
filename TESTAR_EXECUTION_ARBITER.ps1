$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

Write-Host "[1/3] py_compile..." -ForegroundColor Cyan
& $Py -m py_compile `
  api_server.py `
  phoenix_kernel\kernel.py `
  phoenix_kernel\orchestration\execution_arbiter.py `
  phoenix_kernel\resident\resident_manager.py `
  phoenix_kernel\documents\document_llm_worker.py `
  phoenix_kernel\runtime\drivers\llama_cpp.py

Write-Host "[2/3] testes do árbitro + contratos..." -ForegroundColor Cyan
& $Py -m pytest `
  TESTS\test_execution_arbiter.py `
  TESTS\test_arbiter_wiring_contracts.py `
  TESTS\test_llama_cpp_launch_policy.py `
  TESTS\test_source_contracts.py `
  -q

Write-Host "[3/3] decisão de regressão Phoenix Self..." -ForegroundColor Cyan
& $Py -c "from phoenix_kernel.orchestration.execution_arbiter import default_execution_arbiter as a; print(a.intercept('Crie um documento TXT com um relatório de 5 parágrafos sobre os recursos atuais da Phoenix Engine.').to_dict())"

Write-Host "OK. Agora inicie a Phoenix e repita o pedido de regressão na Aviary." -ForegroundColor Green
