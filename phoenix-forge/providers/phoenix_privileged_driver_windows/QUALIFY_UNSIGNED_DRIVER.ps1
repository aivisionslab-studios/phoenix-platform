param([switch]$KeepBuild)
$ErrorActionPreference="Stop"
$Root=$PSScriptRoot
$BuildScript=Join-Path $Root "BUILD_WDK.ps1"
$EvidenceDir=Join-Path $Root "build_evidence"
$Evidence=Join-Path $EvidenceDir "unsigned_build_qualification.json"
New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null
$result=[ordered]@{schema="phoenix.forge.unsigned-driver-qualification/v2";generated_at=(Get-Date).ToString("o");build_requested=$true;install_requested=$false;service_start_requested=$false;signing_requested=$false;test_signing_requested=$false;preflight=$null;driver_path=$null;sha256=$null;file_size=$null;authenticode_status=$null;status="NOT_RUN"}
$preflightText=& powershell -NoProfile -ExecutionPolicy Bypass -File $BuildScript -VerifyOnly 2>&1 | Out-String
$preflightCode=$LASTEXITCODE
try{$preflight=$preflightText|ConvertFrom-Json}catch{$preflight=$null}
$result.preflight=$preflight
if($preflightCode -ne 0 -or -not $preflight -or $preflight.status -ne "WDK_ENVIRONMENT_READY"){
  $result.status=if($preflight -and $preflight.status){[string]$preflight.status}else{"WDK_PREFLIGHT_FAILED"}
  $result.exit_code=$preflightCode
  $result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $Evidence -Encoding UTF8
  $result|ConvertTo-Json -Depth 8
  exit 3
}
$buildText=& powershell -NoProfile -ExecutionPolicy Bypass -File $BuildScript -BuildUnsigned 2>&1 | Out-String
$buildCode=$LASTEXITCODE
if($buildCode -ne 0){$result.status="BUILD_FAILED";$result.exit_code=$buildCode;$result.build_output=$buildText;$result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $Evidence -Encoding UTF8;$result|ConvertTo-Json -Depth 8;exit $buildCode}
$sys=Get-ChildItem -LiteralPath $Root -Recurse -Filter PhoenixForgePrivileged.sys -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(-not $sys){$result.status="BUILD_OUTPUT_MISSING";$result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $Evidence -Encoding UTF8;$result|ConvertTo-Json -Depth 8;exit 4}
$sig=Get-AuthenticodeSignature -LiteralPath $sys.FullName
$result.driver_path=$sys.FullName;$result.sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $sys.FullName).Hash;$result.file_size=$sys.Length;$result.authenticode_status=[string]$sig.Status;$result.status="UNSIGNED_BUILD_QUALIFIED"
$result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $Evidence -Encoding UTF8
$result|ConvertTo-Json -Depth 8
if(-not $KeepBuild){Remove-Item -LiteralPath $sys.FullName -Force -ErrorAction SilentlyContinue}
exit 0
