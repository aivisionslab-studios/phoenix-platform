# install/storage_scanner.ps1
# Phoenix Engine 5.0
# Storage Scanner Multiplataforma
# PowerShell 7+
# Windows / Linux Debian / Ubuntu

Write-Host ""
Write-Host "=== SCANNER DE ARMAZENAMENTO ===" -ForegroundColor Cyan


$Global:PhoenixStorage = @()


function Get-DiskScore {

    param(
        [string]$Kind,
        [double]$FreeGB
    )


    $score = 10


    switch ($Kind) {

        "NVMe" {
            $score = 100
        }

        "SSD" {
            $score = 70
        }

        "HDD" {
            $score = 40
        }

    }


    if ($FreeGB -lt 20) {

        $score = [math]::Floor($score * 0.3)

    }
    elseif ($FreeGB -lt 50) {

        $score = [math]::Floor($score * 0.7)

    }


    return $score
}



function Add-PhoenixDisk {

    param(
        [string]$Path,
        [string]$Kind,
        [double]$FreeGB,
        [double]$TotalGB,
        [bool]$IsSystem = $false
    )


    $Global:PhoenixStorage += [PSCustomObject]@{

        Path = $Path

        Kind = $Kind

        FreeGB = $FreeGB

        TotalGB = $TotalGB

        IsSystem = $IsSystem

        Score = Get-DiskScore `
            -Kind $Kind `
            -FreeGB $FreeGB

    }

}



#
# WINDOWS SCANNER
#

if ($IsWindows) {


    try {


        $volumes =
            Get-Volume |
            Where-Object {
                $_.DriveLetter -and
                $_.Size -gt 0
            }



        foreach ($volume in $volumes) {


            $free =
                [math]::Round(
                    $volume.SizeRemaining / 1GB,
                    1
                )


            $total =
                [math]::Round(
                    $volume.Size / 1GB,
                    1
                )


            $type = "HDD"
            $isSystemVol = $false


            try {


                $partition =
                    Get-Partition `
                    -DriveLetter $volume.DriveLetter


                $disk =
                    Get-Disk `
                    -Number $partition.DiskNumber

                # CORREÇÃO: BusType "SATA" NÃO significa SSD - um HD mecânico
                # comum também conecta via SATA. Antes isso classificava HDs
                # de verdade como "SSD", furando a prioridade NVMe > SSD > HDD
                # bem no tipo de disco mais lento. Usa o MediaType real do
                # Storage Management (Get-PhysicalDisk), que distingue
                # SSD/HDD de verdade independente do barramento.
                $physicalDisk = $disk | Get-PhysicalDisk -ErrorAction SilentlyContinue

                if ($disk.BusType -eq "NVMe") {

                    $type = "NVMe"

                }
                elseif ($physicalDisk -and $physicalDisk.MediaType -eq "SSD") {

                    $type = "SSD"

                }
                elseif ($physicalDisk -and $physicalDisk.MediaType -eq "HDD") {

                    $type = "HDD"

                }
                elseif ($disk.BusType -eq "SATA") {

                    # MediaType indisponivel (disco antigo/driver sem suporte)
                    # - mantem o fallback antigo como ultimo recurso.
                    $type = "SSD"

                }

                # O scanner descobre sozinho qual e o disco de sistema via
                # a propriedade nativa IsBoot da particao - nao assume
                # nenhuma letra fixa (nem "C:", nem variavel de ambiente).
                $isSystemVol = [bool]$partition.IsBoot


            }
            catch {

            }



            Add-PhoenixDisk `
                -Path "$($volume.DriveLetter):\" `
                -Kind $type `
                -FreeGB $free `
                -TotalGB $total `
                -IsSystem $isSystemVol


        }


    }
    catch {


        Write-Host `
        "[!] Erro Windows scanner: $($_.Exception.Message)" `
        -ForegroundColor Yellow


    }

}



#
# LINUX SCANNER
#

elseif ($IsLinux) {


    try {


        $json =
            lsblk `
            -d `
            -b `
            -J `
            -o NAME,ROTA,SIZE,TYPE `
            2>$null



        $devices =
            $json |
            ConvertFrom-Json



        $root =
            df -B1 / |
            Select-Object -Skip 1



        $freeBytes = 0
        $rootDiskName = $null



        if ($root) {


            $parts =
                $root -split "\s+" |
                Where-Object {
                    $_ -ne ""
                }



            if ($parts.Count -ge 4) {

                $freeBytes =
                    [double]$parts[3]

            }

            # O scanner descobre sozinho qual disco fisico e o de sistema:
            # pega o device montado em "/" (ex: /dev/nvme0n1p2) e extrai o
            # nome do disco pai (nvme0n1) pra comparar com o lsblk abaixo -
            # nao assume nenhum path fixo tipo "/".
            if ($parts.Count -ge 1) {
                $rootDevice = ($parts[0] -replace "^/dev/", "")
                if ($rootDevice -match '^(nvme\d+n\d+)p\d+$') {
                    $rootDiskName = $matches[1]
                } elseif ($rootDevice -match '^([a-z]+)\d+$') {
                    $rootDiskName = $matches[1]
                } else {
                    # Ja e o disco inteiro (sem particao) - ex: root direto
                    # em /dev/nvme0n1 sem sufixo p1. Mantem como esta.
                    $rootDiskName = $rootDevice
                }
            }

        }



        foreach ($device in $devices.blockdevices) {


            if ($device.type -ne "disk") {

                continue

            }



            $type = "HDD"



            if ($device.name -like "nvme*") {

                $type = "NVMe"

            }
            elseif ($device.rota -eq 0) {

                $type = "SSD"

            }

            $isSystemDisk = ($rootDiskName -and $device.name -eq $rootDiskName)



            Add-PhoenixDisk `
                -Path "/dev/$($device.name)" `
                -Kind $type `
                -FreeGB ([math]::Round($freeBytes / 1GB,1)) `
                -TotalGB ([math]::Round(([double]$device.size)/1GB,1)) `
                -IsSystem $isSystemDisk


        }


    }
    catch {


        Write-Host `
        "[!] Erro Linux scanner: $($_.Exception.Message)" `
        -ForegroundColor Yellow


    }

}
#
# MOSTRAR DISCOS ENCONTRADOS
#

if ($Global:PhoenixStorage.Count -eq 0) {

    Write-Host "[!] Nenhum disco encontrado." -ForegroundColor Yellow

}
else {


    foreach ($disk in $Global:PhoenixStorage) {


        Write-Host (
            "    {0,-15} {1,-6} {2,8} GB livres / {3,8} GB total (score {4})" -f
            $disk.Path,
            $disk.Kind,
            $disk.FreeGB,
            $disk.TotalGB,
            $disk.Score
        ) -ForegroundColor Gray


    }


}



#
# ESCOLHER MELHOR DISCO
# Política explícita:
#   1) Entre os discos com pelo menos 40GB livres, escolhe o mais rápido
#      (NVMe > SSD > HDD); empate de tipo -> mais espaço livre.
#   2) Se NENHUM disco tem 40GB livres, cai pro HDD com mais espaço livre
#      como último recurso (mesmo abaixo do mínimo).
#   3) Se nem HDD existir, usa o disco com mais espaço livre entre
#      absolutamente todos, só pra não travar o provisionamento.
#

$Global:PhoenixBestDisk = $null
$MinFreeGB = 40
$TypeRank = @{ "NVMe" = 3; "SSD" = 2; "HDD" = 1 }

if ($Global:PhoenixStorage.Count -gt 0) {

    $eligible = $Global:PhoenixStorage | Where-Object { $_.FreeGB -ge $MinFreeGB }

    if ($eligible.Count -gt 0) {

        $Global:PhoenixBestDisk =
            $eligible |
            Sort-Object -Property `
                @{Expression = { $TypeRank[$_.Kind] }; Descending = $true}, `
                @{Expression = { $_.FreeGB }; Descending = $true} |
            Select-Object -First 1

    } else {

        Write-Host "[!] Nenhum disco com os $MinFreeGB GB minimos recomendados." -ForegroundColor Yellow

        $hddCandidates = $Global:PhoenixStorage | Where-Object { $_.Kind -eq "HDD" }

        if ($hddCandidates.Count -gt 0) {
            $Global:PhoenixBestDisk = $hddCandidates | Sort-Object -Property FreeGB -Descending | Select-Object -First 1
            Write-Host "[!] Usando HDD como ultimo recurso: $($Global:PhoenixBestDisk.Path) ($($Global:PhoenixBestDisk.FreeGB) GB livres)" -ForegroundColor Yellow
        } else {
            $Global:PhoenixBestDisk = $Global:PhoenixStorage | Sort-Object -Property FreeGB -Descending | Select-Object -First 1
            Write-Host "[!] Nenhum HDD encontrado tambem. Usando o disco com mais espaco livre mesmo assim: $($Global:PhoenixBestDisk.Path)" -ForegroundColor Red
        }
    }
}



#
# CONFIGURAÇÃO DE CAMINHOS
#

if ($Global:PhoenixBestDisk) {

    # O disco de sistema e o que o SCANNER marcou como IsSystem durante a
    # varredura (Get-Partition.IsBoot no Windows / device montado em "/"
    # no Linux) - nao e assumido por letra fixa nem variavel de ambiente.
    $systemDisk = $Global:PhoenixStorage | Where-Object { $_.IsSystem } | Select-Object -First 1

    if ($IsWindows) {


        $workspacePath =
            Join-Path `
            $Global:PhoenixBestDisk.Path `
            "Phoenix\Workstations"


        $phoenixRoot =
            Join-Path `
            $env:ProgramData `
            "Phoenix"


        $systemPath = if ($systemDisk) { $systemDisk.Path } else { $null }

        $logsPath =
            Join-Path `
            $phoenixRoot `
            "Logs"


        # CORREÇÃO: antes hardcoded como "D:\PhoenixBackup" - quebrava se a
        # letra da unidade mudasse (exatamente o que aconteceu). Agora o
        # backup fica dentro do próprio disco que o scanner escolheu.
        $backupPath =
            Join-Path `
            $workspacePath `
            "backup"


    }
    else {


        $workspacePath =
            "/mnt/phoenix/workstations"


        $phoenixRoot =
            "/etc/phoenix"


        $systemPath = if ($systemDisk) { $systemDisk.Path } else { $null }


        $logsPath =
            "/var/log/phoenix"


        $backupPath =
            "/mnt/phoenix/backup"


    }

    if (-not $systemPath) {
        Write-Host "[!] Scanner nao conseguiu identificar o disco de sistema (IsBoot/mountpoint). systemPath ficara vazio no storage.json." -ForegroundColor Yellow
    }



    Write-Host ""

    Write-Host `
    "[OK] Disco recomendado: $($Global:PhoenixBestDisk.Path)" `
    -ForegroundColor Green


    Write-Host `
    "[i] Tipo: $($Global:PhoenixBestDisk.Kind)" `
    -ForegroundColor Cyan


    Write-Host `
    "[i] Espaço livre: $($Global:PhoenixBestDisk.FreeGB) GB" `
    -ForegroundColor Cyan



    #
    # CRIAR DIRETÓRIO PHOENIX
    #

    if (-not (Test-Path $phoenixRoot)) {


        New-Item `
            -ItemType Directory `
            -Force `
            -Path $phoenixRoot |
            Out-Null


    }



    #
    # STORAGE MAP
    #

    $storageMap = @{



        system = $systemPath


        workspace = $workspacePath


        models =
            Join-Path `
            $workspacePath `
            "models"



        docker =
            Join-Path `
            $workspacePath `
            "docker"



        rag =
            Join-Path `
            $workspacePath `
            "rag"



        cache =
            Join-Path `
            $workspacePath `
            "cache"



        logs = $logsPath


        backup = $backupPath


    }



    #
    # SALVAR JSON
    #

    $storageFile =
        Join-Path `
        $phoenixRoot `
        "storage.json"



    $storageMap |
        ConvertTo-Json -Depth 5 |
        Out-File `
        -FilePath $storageFile `
        -Encoding utf8 `
        -Force



    Write-Host `
    "[OK] storage.json criado em:" `
    -ForegroundColor Green


    Write-Host $storageFile `
    -ForegroundColor DarkGray



}
else {

    # CORREÇÃO DE BUG: antes esse ramo só imprimia um aviso e o script
    # seguia até o "return @{ Success = $true; ... }" do final mesmo
    # assim - ou seja, "sucesso" era reportado mesmo sem nenhum disco
    # encontrado, sem storage.json criado e sem nenhum path definido.
    Write-Host `
    "[X] Nenhum disco foi encontrado pelo scanner - impossivel definir onde a Phoenix vai instalar." `
    -ForegroundColor Red

    return @{
        Name = "Storage_Scanner"
        Version = "2.1.0"
        Success = $false
        ErrorCode = "PX020"
        Warnings = @()
        Errors = @("Nenhum disco foi encontrado durante o escaneamento de armazenamento.")
        RestartRequired = $false
        Artifacts = @()
        Timestamp = Get-Date
    }

}



#
# CONTRATO DE RETORNO PHOENIX
#

return @{


    Name = "Storage_Scanner"


    Version = "2.1.0"


    Success = $true


    ErrorCode = ""


    Warnings = @()


    Errors = @()


    RestartRequired = $false


    Artifacts = @(
        "storage.json"
    )


    Timestamp = Get-Date


}