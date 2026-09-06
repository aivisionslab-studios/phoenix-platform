# ============================================================================
# Teste manual do sd-cli.exe pra flux1-schnell, ISOLADO da Phoenix Engine.
# Objetivo: confirmar se o binário + os flags corretos (--vae-on-cpu
# --clip-on-cpu --offload-to-cpu) rodam sem crash nesta RX 580, sem depender
# de nenhum código Python (nem o patch, nem o bug do _detect_has_rocm()).
# Rode isso com a Phoenix Engine (porta 8000) e a Aviary (porta 3000)
# FECHADAS, pra não competir por VRAM/CPU.
# ============================================================================

# --- PASSO 1: localizar os arquivos (ajuste os caminhos se souber onde estão) ---

$raizProjeto = "C:\phoenix-engine"

Write-Host "Procurando sd-cli.exe..." -ForegroundColor Cyan
$sdcli = Get-ChildItem -Path "$raizProjeto\repos\stable-diffusion.cpp\build" -Recurse -Filter "sd-cli.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName

Write-Host "Procurando os 4 arquivos do Flux (isso pode demorar alguns minutos se escanear o disco inteiro)..." -ForegroundColor Cyan

# Tenta primeiro a pasta padrao da Phoenix; se nao achar, cai pro disco inteiro.
$pastasBusca = @("B:\Phoenix\Workstations\Models\Image", "$raizProjeto\data\models", "C:\", "D:\", "B:\")

function Achar-Arquivo($filtro) {
    foreach ($pasta in $pastasBusca) {
        if (Test-Path $pasta) {
            $achado = Get-ChildItem -Path $pasta -Recurse -Filter $filtro -ErrorAction SilentlyContinue |
                Select-Object -First 1 -ExpandProperty FullName
            if ($achado) { return $achado }
        }
    }
    return $null
}

$diffusionModel = Achar-Arquivo "*flux1-schnell*.gguf"
$vae            = Achar-Arquivo "ae.safetensors"
$clipL          = Achar-Arquivo "*clip_l*"
$t5xxl          = Achar-Arquivo "*t5xxl*"

Write-Host ""
Write-Host "sd-cli.exe        : $sdcli"
Write-Host "diffusion-model   : $diffusionModel"
Write-Host "vae               : $vae"
Write-Host "clip_l            : $clipL"
Write-Host "t5xxl             : $t5xxl"
Write-Host ""

if (-not $sdcli -or -not $diffusionModel -or -not $vae -or -not $clipL -or -not $t5xxl) {
    Write-Host "Faltou achar algum arquivo acima (aparece em branco). Edite este script e" -ForegroundColor Yellow
    Write-Host "cole o caminho manualmente nas variaveis correspondentes antes de rodar de novo." -ForegroundColor Yellow
    exit 1
}

# --- PASSO 2: gerar a imagem, EXATAMENTE com o split validado no benchmark ---
# 512x512, 4 steps, cfg-scale 1.0 - sao os defaults do perfil "flux1-schnell"
# no sd_cpp.py corrigido. NAO peça 1024x1024 com este arquivo (Q4_K_M,
# ~6.75GB) - already confirmado como falha conhecida no proprio projeto,
# independente deste patch.

$saida = "$raizProjeto\output\images\teste_manual_flux_schnell.png"
New-Item -ItemType Directory -Force -Path (Split-Path $saida) | Out-Null

& $sdcli `
    --diffusion-model $diffusionModel `
    --vae $vae `
    --clip_l $clipL `
    --t5xxl $t5xxl `
    -p "a phoenix bird rising from the ashes, cinematic lighting, 8k, highly detailed" `
    -o $saida `
    -W 512 -H 512 `
    --steps 4 `
    --cfg-scale 1.0 `
    --seed 42 `
    --vae-on-cpu --clip-on-cpu --offload-to-cpu

Write-Host ""
if (Test-Path $saida) {
    Write-Host "OK - imagem gerada em: $saida" -ForegroundColor Green
} else {
    Write-Host "Sem imagem gerada - o erro do sd-cli.exe deve ter aparecido acima." -ForegroundColor Red
}
