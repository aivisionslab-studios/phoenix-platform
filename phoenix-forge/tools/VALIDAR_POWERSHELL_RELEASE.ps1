param(
  [Parameter(Mandatory=$true)][string]$Root
)
$ErrorActionPreference='Stop'
$failures=@()
$files=@(Get-ChildItem -LiteralPath $Root -Recurse -File -Filter '*.ps1' -ErrorAction Stop)
foreach($f in $files){
  $tokens=$null; $errors=$null
  [System.Management.Automation.Language.Parser]::ParseFile($f.FullName,[ref]$tokens,[ref]$errors)|Out-Null
  if(@($errors).Count -gt 0){
    foreach($e in @($errors)){
      $failures += [ordered]@{file=$f.FullName;message=$e.Message;extent=$e.Extent.Text;line=$e.Extent.StartLineNumber}
      Write-Host ("[PS-PARSER][FAIL] {0}:{1} {2}" -f $f.FullName,$e.Extent.StartLineNumber,$e.Message) -ForegroundColor Red
    }
  }
}
if($failures.Count -gt 0){
  throw ("PowerShell parser gate FAILED: {0} parser error(s)." -f $failures.Count)
}
Write-Host ("[PS-PARSER][PASS] {0} PowerShell file(s) parsed successfully." -f $files.Count) -ForegroundColor Green
