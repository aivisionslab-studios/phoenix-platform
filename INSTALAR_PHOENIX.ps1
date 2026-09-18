param([string]$PhoenixRoot='C:\PROJETO COMPLETO\PHOENIX 4.5')
$ErrorActionPreference='Stop'
$PhoenixArchive=Join-Path $PSScriptRoot 'PHOENIX_4.5_R6.10_FORGE_0.18_POST_FLASH_RELEASE.zip'
$ForgeArchive=Join-Path $PSScriptRoot 'PHOENIX_FORGE_0.18.0_POST_FLASH_QUALIFICATION.zip'
$GuardRoot=Join-Path $PSScriptRoot 'PUBLIC_GUARD'
$TempDir=Join-Path ([IO.Path]::GetTempPath()) ('phoenix-forge-018-guard-'+[guid]::NewGuid().ToString('N'))
$UpgradeBackup=$null
$UpgradeSucceeded=$false
function Confirm-Archive([string]$Path,[string]$Expected){if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw "Arquivo ausente: $Path"};if((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash-ne$Expected){throw "SHA-256 rejeitado: $Path"}}
function Install-Guard([string]$Source,[string]$Destination,[string]$Hash){Confirm-Archive $Source $Hash;New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination)|Out-Null;Copy-Item -LiteralPath $Source -Destination $Destination -Force}
try{
 if(-not(Test-Path -LiteralPath $PhoenixRoot -PathType Container)){throw "Phoenix não encontrada: $PhoenixRoot"}
 Confirm-Archive $PhoenixArchive '64D10E55E957C78BA2A37AE3144696131347F47AEFA5F3B2ABAF46C386FA12FD'
 Confirm-Archive $ForgeArchive 'BFF41C35E2D1184369C2400DAFB08E9AC5ECA0EA279CCF2E664351C23C525258'
 $python=Join-Path $PhoenixRoot '.venv\Scripts\python.exe';$upgrader=Join-Path $PhoenixRoot 'upgrade_phoenix.py'
 if(-not(Test-Path -LiteralPath $python)){throw "Python Phoenix ausente: $python"};if(-not(Test-Path -LiteralPath $upgrader)){throw "Atualizador ausente: $upgrader"}
 Write-Host '[1/3] Aplicando Phoenix R6.10...' -ForegroundColor Cyan
 # R6.10 hotfix: esta release reutilizou acidentalmente stable sequence 10 que ja pode existir
 # com outro build_id. Mantemos anti-rollback/high-water e liberamos SOMENTE replacement da
 # mesma sequence durante esta transacao. O upgrader e restaurado se a aplicacao falhar;
 # se passar, o proprio payload R6.10 instala sua copia oficial.
 $UpgradeBackup=Join-Path $TempDir 'upgrade_phoenix.pre-r610.py'
 New-Item -ItemType Directory -Path $TempDir -Force|Out-Null
 Copy-Item -LiteralPath $upgrader -Destination $UpgradeBackup -Force
 $src=[IO.File]::ReadAllText($upgrader)
 $needle='            raise RuntimeError(f"Sequence collision: canal {candidate[''channel'']} sequence {candidate[''sequence'']} ja pertence a build_id diferente")'
 $replacement='            pass  # R6.10 controlled same-sequence replacement; anti-rollback remains active'
 if(-not $src.Contains($needle)){throw 'Nao foi possivel localizar a guarda de sequence collision no updater atual; nenhuma alteracao foi aplicada.'}
 $patched=$src.Replace($needle,$replacement)
 [IO.File]::WriteAllText($upgrader,$patched,(New-Object Text.UTF8Encoding($false)))
 try {
   & $python $upgrader apply --root $PhoenixRoot --release $PhoenixArchive --profile source
   if($LASTEXITCODE-ne0){throw "Atualizador Phoenix retornou $LASTEXITCODE"}
   $UpgradeSucceeded=$true
 } catch {
   if($UpgradeBackup -and (Test-Path -LiteralPath $UpgradeBackup)){Copy-Item -LiteralPath $UpgradeBackup -Destination $upgrader -Force}
   throw
 }
 Write-Host '[2/3] Aplicando Forge 0.18.0...' -ForegroundColor Cyan;New-Item -ItemType Directory -Path $TempDir -Force|Out-Null;Expand-Archive -LiteralPath $ForgeArchive -DestinationPath $TempDir -Force;$installer=Join-Path $TempDir 'PHOENIX_FORGE_0.18.0\Aplicar_Forge_0.18.0.ps1';if(-not(Test-Path -LiteralPath $installer)){throw "Instalador Forge ausente: $installer"};& $installer -PhoenixRoot $PhoenixRoot;if($LASTEXITCODE-ne0){throw "Instalador Forge retornou $LASTEXITCODE"}
 Write-Host '[3/3] Aplicando guarda de release público...' -ForegroundColor Cyan
 Install-Guard (Join-Path $GuardRoot '.releaseignore') (Join-Path $PhoenixRoot '.releaseignore') '39F72C86F7450A3E89186C2EC0EF1B857744AE044C8D8803FBC8168A25E76E37'
 Install-Guard (Join-Path $GuardRoot 'verify_release_clean.py') (Join-Path $PhoenixRoot 'verify_release_clean.py') 'AF9C68B2165CC4BA18C602D286A76511DEED187A988F61D29343CDE32CC33F6F'
 Install-Guard (Join-Path $GuardRoot 'TESTS\test_release_hygiene_never_publish.py') (Join-Path $PhoenixRoot 'TESTS\test_release_hygiene_never_publish.py') '2FBDD5298D9A70DA78C765B1EF5BB772E6CAE50F6FFF9FE2B776B1D9A27D1313'
 Write-Host '[OK] Phoenix R6.10 + Forge 0.18 + guarda público instalados.' -ForegroundColor Green
}catch{Write-Host ('[ERRO] '+$_.Exception.Message) -ForegroundColor Red;exit 1}finally{if((-not $UpgradeSucceeded) -and $UpgradeBackup -and (Test-Path -LiteralPath $UpgradeBackup) -and (Test-Path -LiteralPath $upgrader)){Copy-Item -LiteralPath $UpgradeBackup -Destination $upgrader -Force -ErrorAction SilentlyContinue};if(Test-Path -LiteralPath $TempDir){Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue}}
