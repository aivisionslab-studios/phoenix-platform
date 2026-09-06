from __future__ import annotations
import asyncio
import logging
import platform
import unicodedata
import psutil
from pathlib import Path
from datetime import datetime, timezone

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeStatus, RuntimeState
from phoenix_kernel.paths import PhoenixPaths

logger = logging.getLogger(__name__)
_UTC = timezone.utc


def _detect_has_cuda() -> bool:
    """Detecção leve de CUDA — só verifica nvidia-smi, sem importar torch."""
    import shutil, subprocess
    if shutil.which('nvidia-smi'):
        try:
            r = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                               capture_output=True, text=True, timeout=5)
            return r.returncode == 0 and bool(r.stdout.strip())
        except Exception:
            pass
    return False



# PHX-FIX (31/08, investigacao da RECORRENCIA do crash 0xC0000005 no
# flux1-schnell DEPOIS do patch anterior ja estar aplicado byte-a-byte
# no ambiente do usuario - achado so foi possivel lendo o repomix
# completo do projeto, nao so o pytest): esta funcao aceitava
# `hipconfig --version` como prova de "esta maquina tem ROCm utilizavel".
# Isso esta errado - "hipconfig" so reporta a VERSAO DO SDK/RUNTIME HIP
# instalado no sistema, nunca verifica se a GPU DE VERDADE da maquina e
# compativel com ROCm. A RX 580 desta maquina e Polaris/GCN4 (gfx803) -
# o ROCm NUNCA teve suporte oficial pra essa geracao (o minimo suportado
# e GCN5/Vega10, gfx900+). Se qualquer software AMD (suite de driver,
# HIP SDK instalado por outro motivo, etc) deixou "hipconfig.exe" no
# PATH do Windows, essa funcao retornava True mesmo SEM nenhuma GPU
# ROCm-capaz presente - e o bloco logo abaixo neste arquivo
# ("PHX-NEW: backend de aceleracao...") usava esse True pra REMOVER
# "--vae-on-cpu"/"--clip-on-cpu"/"--offload-to-cpu" do comando, undoing
# exatamente a restauracao feita no MODEL_PROFILES (ver PHX-FIX de 31/08
# nos perfis Flux acima) - sem tocar em nenhuma linha do MODEL_PROFILES,
# por isso o diff do arquivo continuava batendo 100% com o patch ja
# aplicado enquanto o crash voltava a acontecer.
#
# Correcao: "hipconfig" removido como sinal (nao prova nada sobre a GPU
# real). "rocm-smi" agora exige que o stdout tenha conteudo de
# dispositivo de verdade (nao so returncode==0 - um rocm-smi instalado
# sem nenhuma GPU visivel ao driver ROCm tipicamente retorna 0 com saida
# vazia/"No devices found"). Alem disso, mesmo com um dispositivo
# listado, uma GPU Polaris/GCN4 conhecida (RX 580/570/560/550/480/470/460,
# familia gfx803) e tratada como NAO-ROCm, seguindo o mesmo padrao de
# denylist ja usado em _check_known_failure() pra combinacoes conhecidas
# como inseguras nesta classe de hardware.
_ROCM_UNSUPPORTED_GCN4_MARKERS = (
    "rx 580", "rx580", "rx 570", "rx570", "rx 560", "rx560",
    "rx 550", "rx550", "rx 480", "rx480", "rx 470", "rx470", "rx 460", "rx460",
    "polaris", "gfx803",
)


def _detect_has_rocm() -> bool:
    """Detecção leve de ROCm — só rocm-smi, exigindo dispositivo real e
    recusando GPUs Polaris/GCN4 conhecidas como não suportadas pelo ROCm
    (ver PHX-FIX acima para o motivo completo)."""
    import shutil, subprocess
    if not shutil.which('rocm-smi'):
        return False
    try:
        r = subprocess.run(['rocm-smi', '--showid'],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0 or not r.stdout.strip():
            return False
        # Tem dispositivo listado - mas confirma que NAO é uma GPU
        # Polaris/GCN4 conhecida antes de confiar na detecção.
        try:
            name_check = subprocess.run(['rocm-smi', '--showproductname'],
                                        capture_output=True, text=True, timeout=5)
            lowered_name = name_check.stdout.lower() if name_check.returncode == 0 else ""
        except Exception:
            lowered_name = ""
        if any(marker in lowered_name for marker in _ROCM_UNSUPPORTED_GCN4_MARKERS):
            logger.info("SdCppDriver: rocm-smi presente mas GPU é Polaris/GCN4 (não suportada pelo ROCm) — tratando como sem ROCm.")
            return False
        return True
    except Exception:
        return False


def _sanitize_prompt_for_cli(prompt: str) -> tuple[str, bool]:
    """
    PHX-FIX: o Windows converte a linha de comando (UTF-16 interno) para a
    codepage ANSI do sistema ANTES de entregar pro argv do sd-cli.exe.
    Remove acentos (NFKD) antes de montar o comando pra evitar prompt
    corrompido. Só aplica no Windows — no Linux o subprocess já lida com
    UTF-8 nativamente.
    """
    if platform.system() != "Windows":
        return prompt, False
    normalized = unicodedata.normalize("NFKD", prompt)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only, ascii_only != prompt


def _discover_project_root(start_file: Path) -> Path:
    current = start_file.resolve()
    for _ in range(8):
        current = current.parent
        candidate = current / "repos" / "stable-diffusion.cpp"
        if candidate.exists():
            logger.info(f"SdCppDriver: raiz do projeto encontrada em '{current}'")
            return current
    fallback = start_file.resolve().parent.parent.parent.parent
    logger.warning(
        f"SdCppDriver: NAO achei 'repos/stable-diffusion.cpp' subindo a arvore a partir de "
        f"'{start_file}'. Usando fallback '{fallback}'."
    )
    return fallback


# ---------------------------------------------------------------------------
# PHX-FIX: Perfis por familia de modelo.
#
# Antes deste fix, o driver so sabia montar UM formato de comando (Flux
# generico com steps=4 fixo e cfg-scale=1.0 fixo), o que nao bate com os
# comandos validados manualmente pra Kontext, Flux Q8, Flux.2, Juggernaut
# XL (SDXL) e SD 3.5 Large. Cada familia tem encoders diferentes, flags de
# offload diferentes, cfg-scale diferente e resolucao padrao diferente -
# entao cada uma precisa do proprio perfil, na ordem certa de deteccao
# (mais especifico primeiro: "kontext" tem que casar antes de "flux1-dev"
# generico).
#
# "match": substrings (case-insensitive) procuradas no nome do arquivo do
#          modelo pra escolher o perfil.
# "diffusion_flag": True usa --diffusion-model (arquitetura Flux
#          desacoplada), False usa -m (checkpoint unico, SDXL/SD1.5/SD3.5).
# "components": lista de (nome_do_flag_cli, [substrings pra achar o arquivo]).
#          Todos sao obrigatorios - se faltar um, falha com erro claro.
# "extra_flags": flags fixas de offload/qualidade desse perfil.
# "cfg_scale": valor de --cfg-scale, ou None se o perfil nao usa a flag.
# "default_resolution": (largura, altura) usada se o plano nao especificar.
# ---------------------------------------------------------------------------
MODEL_PROFILES = [
    {
        # flux1-schnell (Q4_K_M ou Q8_0): arquitetura desacoplada com
        # diffusion GGUF + VAE flux + CLIP-L + T5-XXL separados.
        # Configuracao validada na RX 580 8GB + 32GB RAM:
        # - mmap=True: leitura mapeada em memória (mais rápida que disk-seek)
        # - stream_layers=False: NUNCA usar streaming de camadas no Flux —
        #   causa o 0xC0000005/BrokenPipeError no worker nativo
        # - --offload-to-cpu: pesos dos parâmetros em RAM, diffusion na GPU
        # - --clip-on-cpu + --vae-on-cpu: encoders leves na CPU liberam VRAM
        # - --vae-tiling: obrigatório pra não causar OOM no decode VAE
        #
        # O PhoenixDiffusionDriver tem lógica própria de fallback por
        # placement (hybrid-cpu-gpu → auto-fit → hybrid-streaming →
        # text-encoder-disk) que usa esses native_overrides como base.
        "name": "flux1-schnell",
        "match": ["flux1-schnell", "flux1_schnell", "flux-schnell",
                  "flux1-dev", "flux1_dev", "flux-dev",
                  "flux-kontext", "flux_kontext",
                  "flux1-q4", "flux1-q8", "flux-q4", "flux-q8"],
        "diffusion_flag": True,
        "components": [
            ("--vae",    ["ae.safetensors", "flux-vae", "ae_flux", "ae-flux"]),
            ("--clip_l", ["clip_l", "clip-l"]),
            ("--t5xxl",  ["t5xxl", "t5-xxl", "t5_xxl"]),
        ],
        "extra_flags": ["--clip-on-cpu", "--vae-on-cpu", "--offload-to-cpu", "--vae-tiling"],
        "native_overrides": {"mmap": True, "stream_layers": False},
        "diffusion_flash_attn": False,
        "cfg_scale": "1.0",
        "default_resolution": (512, 512),
        "default_steps": 4,
    },
    {
        # Z-Image-Turbo é uma alternativa moderna ao Flux Schnell que o
        # fork vendorizado do stable-diffusion.cpp já suporta. Ele usa um
        # diffusion GGUF, o VAE Flux e um Qwen3-4B separado como encoder.
        "name": "z-image-turbo",
        "match": ["z_image_turbo", "z-image-turbo", "z image turbo"],
        "diffusion_flag": True,
        "components": [
            ("--vae", ["ae.safetensors", "flux-vae"]),
            ("--llm", ["qwen3-4b-instruct-2507", "qwen_3_4b"]),
        ],
        "extra_flags": ["--vae-on-cpu", "--clip-on-cpu", "--offload-to-cpu"],
        "native_overrides": {"mmap": True, "stream_layers": False},
        "diffusion_flash_attn": True,
        "vae_format": 0,  # SD_VAE_FORMAT_FLUX
        "cfg_scale": "1.0",
        "default_resolution": (512, 512),
        "default_steps": 8,
    },
    {
        # Juggernaut XL e outros fine-tunes SDXL: checkpoint unico + vae
        # separado (fix fp16), sem clip/t5xxl - so precisa do vae na CPU.
        # PHX-FIX (achado real via log do usuario - OOM de VRAM na RX 580
        # gerando com o checkpoint SDXL de verdade): o nome REAL do
        # checkpoint baixado pelo proprio catalogo e
        # "sd_xl_base_1.0.safetensors" (com underscore entre "sd" e
        # "xl") - a keyword "sdxl" (grudada, sem separador) NUNCA batia
        # nesse nome, entao caia sempre no DEFAULT_PROFILE
        # ("generic-checkpoint": sem --vae-on-cpu, sem separar o VAE).
        # Sem o offload do VAE pra CPU, o decode do VAE tentava alocar o
        # buffer de computo inteiro na GPU de 8GB via Vulkan e estourava
        # ("ggml_vulkan: ... ErrorOutOfDeviceMemory" / "vae: failed to
        # allocate the compute buffer") - o mesmo tipo de bug de
        # underscore ja achado e corrigido em
        # resident_manager.py/_IMAGE_ARCH_PATTERNS, so que esta e uma
        # lista de match SEPARADA (duplicada), que nao foi sincronizada
        # junto da outra na hora.
        "name": "sdxl-checkpoint",
        "match": ["juggernaut", "sdxl", "sd_xl", "dreamshaper"],
        "diffusion_flag": False,
        "components": [
            ("--vae", ["sdxl_vae-fp16-fix", "sdxl-vae"]),
        ],
        # PHX-FIX (31/08, ENTAO CORRIGIDO DE NOVO no mesmo dia com nova
        # evidencia): a rodada anterior deste fix REMOVEU "--clip-on-cpu"
        # daqui, com a teoria de que o SDXL carrega o CLIP embutido no
        # proprio checkpoint (via "-m") e nao teria "contexto CLIP externo"
        # pra mover - e que passar a flag sem esse contexto causaria o
        # segfault 0xC0000005. Essa teoria NUNCA foi confirmada por um
        # crash reproduzido de verdade no perfil sdxl-checkpoint (o unico
        # crash real observado sempre foi no flux1-schnell, por causa da
        # falta de "--offload-to-cpu" nos perfis Flux - ver PHX-FIX acima).
        # Documentacao externa do proprio usuario (guia AIVisionsLab,
        # secao 26 "SDXL 1024x1024 na RX 580 via Vulkan") traz um comando
        # de producao REAL, testado e com imagem gerada com sucesso nesta
        # mesma RX 580, usando exatamente "-m sd_xl_base_1.0.safetensors
        # --vae sdxl_vae-fp16-fix.safetensors --clip-on-cpu --vae-on-cpu
        # --vae-tiling -H 1024 -W 1024" - ou seja, "--clip-on-cpu" FUNCIONA
        # normalmente com o SDXL carregado via "-m", mesmo sem um
        # "--clip_l" separado: o sd.cpp aplica a flag ao contexto CLIP
        # que existe internamente (vindo do checkpoint), nao exige que ele
        # tenha sido carregado por um arquivo externo. A teoria de
        # "ponteiro nao inicializado" da rodada anterior estava errada.
        # Restaurada, alinhada com o comando real validado.
        "extra_flags": ["--vae-on-cpu", "--clip-on-cpu", "--vae-tiling"],
        "cfg_scale": None,
        "default_resolution": (1024, 1024),
        "default_steps": 20,
    },
]

# Perfil de fallback quando nenhum padrao acima casa - mantem o
# comportamento antigo (checkpoint simples, sem encoders extras) pra nao
# quebrar modelos SD1.5 e outros checkpoints "-m" puros.
DEFAULT_PROFILE = {
    "name": "generic-checkpoint",
    "match": [],
    "diffusion_flag": False,
    "components": [],
    "extra_flags": [],
    "cfg_scale": None,
    "default_resolution": (512, 512),
    "default_steps": 20,
}


def _select_profile(model_name: str) -> dict:
    lowered = model_name.lower()
    for profile in MODEL_PROFILES:
        if any(token in lowered for token in profile["match"]):
            return profile
    return DEFAULT_PROFILE


# ---------------------------------------------------------------------------
# PHX-FIX: Bloqueios rigidos - combinacoes CONFIRMADAS como falha nesta
# maquina (RX 580 8GB + Xeon E5, 32GB RAM), extraidas de um dia inteiro de
# benchmark manual documentado em transcript real. Cada uma foi tentada
# com as flags de offload/split disponiveis no sd-cli e falhou do mesmo
# jeito todas as vezes - nao e falta de flag, e limite fisico do hardware.
#
# Isso NAO e uma lista de "cuidado" - e uma lista de "nunca tentar de
# novo". A pior das cinco (SD 3.5 Large) nao deu OOM controlado: travou
# a maquina inteira (RAM saturada, tela preta, precisou resetar). Por
# isso o check roda ANTES de qualquer subprocess ser aberto, nao depois.
# ---------------------------------------------------------------------------
_MACHINE_FREEZE_MARKERS = (
    "sd3.5_large", "sd35_large", "sd3_5_large", "sd-3.5-large",
    "stable-diffusion-3.5-large", "sd35large",
)


def _check_known_failure(profile: dict, model_path: Path, width: int, height: int) -> str | None:
    # PHX-FIX (2026-09-03, auditoria ChatGPT) removeu este bloqueio
    # alegando que "os known-failures eram todos sobre Flux" - isso
    # contradiz o proprio comentario do bloco acima, que cita SD 3.5
    # Large como o PIOR dos cinco casos (travamento total da maquina,
    # nao um OOM controlado do Flux). SD 3.5 Large nao tem perfil em
    # MODEL_PROFILES, entao cairia no DEFAULT_PROFILE sem nenhuma flag
    # de offload - restaurando exatamente a combinacao que travou a
    # maquina. Bloqueio reintroduzido especificamente pra esse caso ate
    # existir um perfil validado (com offload) pra esse modelo.
    lowered = str(model_path).lower()
    if any(marker in lowered for marker in _MACHINE_FREEZE_MARKERS):
        return (
            "SD 3.5 Large e uma combinacao CONFIRMADA de travar a maquina "
            "inteira nesta configuracao de hardware (RAM saturada, sem "
            "recuperacao - precisa reset fisico). Bloqueado ate existir um "
            "perfil com offload validado em MODEL_PROFILES."
        )
    return None


# O executor CLI legado foi removido na Phoenix 4.5.
# Este módulo conserva apenas os perfis e bloqueios de segurança já validados
# em hardware RX 580; a execução é feita por PhoenixDiffusionDriver através
# da bridge nativa em processo isolado.
