# install/Bootstrap.Contracts.ps1
# Define o contrato estrito de comunicação entre o Bootstrap e os módulos.

class BootstrapResult {
    [string]$Name
    [bool]$Success
    [string]$ErrorCode
    [string[]]$Warnings
    [string[]]$Errors
    [bool]$RestartRequired
    [double]$Duration
    [datetime]$Timestamp
    [string[]]$Artifacts
    [string]$Version

    BootstrapResult() {
        $this.Success = $false
        $this.ErrorCode = ""
        $this.Warnings = @()
        $this.Errors = @()
        $this.RestartRequired = $false
        $this.Duration = 0
        $this.Timestamp = Get-Date
        $this.Artifacts = @()
        $this.Version = "N/A"
        $this.Name = "Unknown"
    }
}