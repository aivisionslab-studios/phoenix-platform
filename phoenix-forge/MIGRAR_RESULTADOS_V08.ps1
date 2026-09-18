param(
  [string]$Source = "..\phoenix-forge-v0.8.0",
  [string]$DeviceName = "AMD Radeon RX 580 2048SP"
)
$ErrorActionPreference='Stop'
$forge='.\.venv\Scripts\phoenix-forge.exe'
if(!(Test-Path $forge)){throw 'Execute BUILD_WINDOWS.ps1 primeiro.'}
$reports=@(
  'resultado-vram-full.json',
  'resultado-vram-confirmacao.json',
  'resultado-vram-terceiro.json',
  'resultado-vram-bandwidth.json',
  'resultado-gpu-compute-2.json'
)
foreach($name in $reports){
  $path=Join-Path $Source $name
  if(Test-Path $path){& $forge ledger-ingest $path --device-name $DeviceName}
  else{Write-Warning "Não encontrado: $path"}
}
& $forge ledger-external --device-name $DeviceName --tool OCCT --status MEMORY_ERROR --errors 1191355 --evidence 'OCCT Personal 17.1.0 VRAM test supplied by user'
& $forge gpu-ledger --device-name $DeviceName
& $forge route llm --device-name $DeviceName --mode AUTO
& $forge route image --device-name $DeviceName --mode AUTO
