param([switch]$VerifyOnly,[switch]$BuildUnsigned)
$ErrorActionPreference="Stop"
$root=$PSScriptRoot
$project=Join-Path $root "PhoenixForgePrivileged.vcxproj"
$vswhere="${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$msbuild=$null
$vsroot=$null
if(Test-Path -LiteralPath $vswhere){
  $vsroot=& $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath | Select-Object -First 1
  $msbuild=& $vswhere -latest -products * -requires Microsoft.Component.MSBuild -find "MSBuild\**\Bin\MSBuild.exe" | Select-Object -First 1
}
$kits="${env:ProgramFiles(x86)}\Windows Kits\10"
$includeRoot=Join-Path $kits "Include"
$libRoot=Join-Path $kits "Lib"
$wdmHeader=$null
if(Test-Path -LiteralPath $includeRoot){
  $wdmHeader=Get-ChildItem -LiteralPath $includeRoot -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName "km\wdm.h" } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
}
$wdmsecLib=$null
if(Test-Path -LiteralPath $libRoot){
  $wdmsecLib=Get-ChildItem -LiteralPath $libRoot -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName "km\x64\wdmsec.lib" } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
}
$kernelToolset=$null
if($vsroot){
  $candidate=Join-Path $vsroot "MSBuild\Microsoft\VC\v170\Platforms\x64\PlatformToolsets\WindowsKernelModeDriver10.0\Toolset.props"
  if(Test-Path -LiteralPath $candidate){$kernelToolset=$candidate}
  if(-not $kernelToolset){
    $kernelToolset=Get-ChildItem -LiteralPath (Join-Path $vsroot "MSBuild") -Recurse -Filter Toolset.props -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -like "*WindowsKernelModeDriver10.0*" } |
      Select-Object -First 1 -ExpandProperty FullName
  }
}
$r=[ordered]@{
  schema="phoenix.forge.privileged-driver-build/v2"
  msbuild=$msbuild
  visual_studio_root=$vsroot
  project_present=(Test-Path -LiteralPath $project)
  wdk_headers_present=[bool]$wdmHeader
  wdk_wdmsec_lib_present=[bool]$wdmsecLib
  wdk_vs_integration_present=[bool]$kernelToolset
  wdm_header=$wdmHeader
  wdmsec_lib=$wdmsecLib
  kernel_toolset=$kernelToolset
  build_requested=[bool]$BuildUnsigned
  signing_requested=$false
  driver_install_requested=$false
  status="PREFLIGHT_ONLY"
}
if(-not $msbuild){$r.status="MSBUILD_MISSING"}
elseif(-not $r.project_present){$r.status="PROJECT_MISSING"}
elseif(-not $wdmHeader){$r.status="WDK_HEADERS_MISSING"}
elseif(-not $wdmsecLib){$r.status="WDK_LIBS_MISSING"}
elseif(-not $kernelToolset){$r.status="WDK_VS_INTEGRATION_MISSING"}
else{$r.status="WDK_ENVIRONMENT_READY"}
if($VerifyOnly -or -not $BuildUnsigned){
  $r|ConvertTo-Json -Depth 6
  if($r.status -eq "WDK_ENVIRONMENT_READY"){exit 0}else{exit 3}
}
if($r.status -ne "WDK_ENVIRONMENT_READY"){$r|ConvertTo-Json -Depth 6;exit 3}
& $msbuild $project /t:Clean,Build /p:Configuration=Release /p:Platform=x64 /m
if($LASTEXITCODE -ne 0){$r.status="BUILD_FAILED";$r.exit_code=$LASTEXITCODE;$r|ConvertTo-Json -Depth 6;exit $LASTEXITCODE}
$sys=Get-ChildItem -LiteralPath $root -Recurse -Filter PhoenixForgePrivileged.sys -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(-not $sys){$r.status="BUILD_OUTPUT_MISSING";$r|ConvertTo-Json -Depth 6;exit 4}
$r.status="UNSIGNED_BUILD_OK";$r.output_sys=$sys.FullName;$r.sha256=(Get-FileHash $sys.FullName -Algorithm SHA256).Hash;$r.file_size=$sys.Length
$r|ConvertTo-Json -Depth 6
exit 0
