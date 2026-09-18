# install/powershell.ps1
# Garante que o PowerShell 7 LTS está instalado.

param (
    [Parameter(Mandatory=$true)]
    [string]$BootstrapPath
)

 $MinimumPwshVersion = [Version]"7.4.0"

function Test-Pwsh {
    return ($PSVersionTable.PSVersion -ge $MinimumPwshVersion)
}

function Install-Pwsh {
    $installed = $false
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            & winget install --id Microsoft.PowerShell --source winget --accept-package-agreements --accept-source-agreements --silent 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { $installed = $true }
        } catch {}
    }

    if (-not $installed) {
        try {
            $msiUrl = "https://github.com/PowerShell/PowerShell/releases/download/v7.4.7/PowerShell-7.4.7-win-x64.msi"
            $msiPath = "$env:TEMP\PowerShell-LTS.msi"
            Invoke-WebRequest -Uri $msiUrl -OutFile $msiPath -UseBasicParsing
            Start-Process msiexec.exe -ArgumentList "/i `"$msiPath`" /quiet" -Wait
            Remove-Item $msiPath -Force
            $installed = $true
        } catch {
            return $false
        }
    }
    return $installed
}

# Se já está no PS7, retorna sucesso
if (Test-Pwsh) {
    return @{ 
        Name="PowerShell"; Version=$PSVersionTable.PSVersion.ToString(); Success=$true; ErrorCode=""; 
        Warnings=@(); Errors=@(); RestartRequired=$false; Artifacts=@("pwsh.exe"); Timestamp=Get-Date 
    }
}

# Se não está no PS7, instala
Write-Host "[*] PowerShell 7 LTS ausente. Iniciando instalação..." -ForegroundColor Yellow
 $success = Install-Pwsh

if ($success) {
    # Avisa o orquestrador que precisa reiniciar, em vez de morrer abruptamente
    return @{ 
        Name="PowerShell"; Version="N/A"; Success=$true; ErrorCode=""; 
        Warnings=@(); Errors=@(); RestartRequired=$true; Artifacts=@(); Timestamp=Get-Date 
    }
}

# Se falhou
return @{ 
    Name="PowerShell"; Version="N/A"; Success=$false; ErrorCode="PX001"; 
    Warnings=@(); Errors=@("Falha ao instalar PowerShell 7."); RestartRequired=$false; Artifacts=@(); Timestamp=Get-Date 
}
