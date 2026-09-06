#!/usr/bin/env python3
"""
setup_vision.py
================
Monta o ambiente de VISAO NATIVA (MiniCPM-V-4.6 via llama-mtmd-cli) na Phoenix.

O QUE ESTE SCRIPT FAZ (tudo idempotente - pode rodar quantas vezes quiser
sem duplicar nada):

  1. Cria a estrutura de pastas necessaria:
       phoenix_kernel/runtime/drivers/
       catalog/
       temp/vision/                     (scratch para imagens recebidas via API)
       <workspace>/Models/Chat/GGUF/    (onde os .gguf de visao/texto ficam)

  2. Escreve phoenix_kernel/runtime/drivers/mtmd_driver.py
     (driver que chama o llama-mtmd-cli, mesmo padrao do sd_cpp.py)

  3. Atualiza (ou cria) catalog/models.json, adicionando a entrada
     "minicpmv" (com o componente obrigatorio "mmproj") sem apagar nada
     que ja exista no catalogo.

  4. Tenta aplicar patch em phoenix_kernel/runtime/engine.py
     (registra o MtmdDriver como runtime "vision").
     Se o arquivo nao existir ou os pontos de ancoragem esperados nao
     forem encontrados, NADA e alterado - o script gera em vez disso um
     arquivo de instrucoes manuais em patches/ENGINE_PATCH_MANUAL.txt.

  5. Tenta aplicar patch em api_server.py
     (adiciona a rota POST /api/describe-image).
     Mesma logica de seguranca do item 4 - se falhar, gera
     patches/API_SERVER_PATCH_MANUAL.txt em vez de arriscar quebrar o
     arquivo.

  6. Opcionalmente baixa os arquivos .gguf de visao (--download-models).
     Por padrao NAO baixa nada (os arquivos somam ~1.4 GB - 529 MB do
     modelo principal confirmados na pagina oficial + ~0.85 GB do mmproj,
     estimado, ver nota no MODEL_CATALOG) - so avisa
     onde eles devem ficar. Isso tambem ja e feito pela Secao 8 do
     common.ps1, entao rodar os dois nao duplica trabalho (ambos
     verificam Test-Path / os.path.exists antes de baixar).

USO:
    python setup_vision.py
    python setup_vision.py --download-models
    python setup_vision.py --root "Z:\\Phoenix"          (se rodar de outro lugar)
    python setup_vision.py --workspace "Z:\\Phoenix\\Workstations"

Rode a partir da raiz do projeto Phoenix (mesma pasta do api_server.py),
ou passe --root apontando pra ela.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import shutil
import urllib.request
from pathlib import Path
from datetime import datetime


# =====================================================================
# CORES DE TERMINAL (com fallback seguro se o terminal nao suportar)
# =====================================================================
class C:
    OK = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    INFO = "\033[96m"
    DIM = "\033[90m"
    ENDC = "\033[0m"


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if sys.platform == "win32":
        # Windows Terminal / PowerShell 7+ / cmd com VT habilitado suportam.
        # cmd.exe antigo simplesmente vai imprimir os codigos crus, mas
        # nao quebra a execucao - por isso nao desligamos por padrao.
        return True
    return sys.stdout.isatty()


_COLOR = _supports_color()


def p(level: str, msg: str) -> None:
    tags = {
        "OK": (C.OK, "[OK]"),
        "WARN": (C.WARN, "[!]"),
        "FAIL": (C.FAIL, "[X]"),
        "INFO": (C.INFO, "[*]"),
    }
    color, tag = tags.get(level, ("", "[?]"))
    if _COLOR:
        print(f"{color}{tag} {msg}{C.ENDC}")
    else:
        print(f"{tag} {msg}")


def section(title: str) -> None:
    line = "=" * 70
    if _COLOR:
        print(f"\n{C.INFO}{line}\n{title}\n{line}{C.ENDC}")
    else:
        print(f"\n{line}\n{title}\n{line}")


# =====================================================================
# CONTEUDO: DRIVER DE VISAO (phoenix_kernel/runtime/drivers/mtmd_driver.py)
# =====================================================================
MTMD_DRIVER_CODE = '''# phoenix_kernel/runtime/drivers/mtmd_driver.py
#
# Driver de VISAO NATIVA da Phoenix.
# Usa o llama-mtmd-cli (ja incluso no llama.cpp compilado com Vulkan) -
# nenhum fork/compilacao extra e necessaria. Mesmo padrao de design do
# sd_cpp.py: CLI de um tiro (roda, processa, sai), acha binario e modelo
# sozinho, timeout defensivo.
#
# Gerado automaticamente por setup_vision.py em {generated_at}

from __future__ import annotations

import asyncio
import logging
import platform
from pathlib import Path
from datetime import datetime, timezone

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeStatus, RuntimeState
from phoenix_kernel.paths import PhoenixPaths

logger = logging.getLogger(__name__)
_UTC = timezone.utc


class MtmdDriver:
    """
    Driver para o llama-mtmd-cli (Visao).
    Usa o mesmo binario compilado do llama.cpp (build com GGML_VULKAN=ON),
    mas em modo CLI pontual - nao mantem um servidor HTTP em background.
    """

    def __init__(self, *args, **kwargs) -> None:
        # drivers/ -> runtime/ -> phoenix_kernel/ -> raiz do projeto
        self._project_root = Path(__file__).resolve().parent.parent.parent.parent

    @property
    def name(self) -> str:
        return "mtmd"

    # -----------------------------------------------------------------
    # Descoberta de binario e arquivos de modelo
    # -----------------------------------------------------------------
    def _find_executable(self) -> str | None:
        repo_dir = self._project_root / "repos" / "llama.cpp"
        exe_names = (
            ["llama-mtmd-cli.exe", "llama-mtmd-cli"]
            if platform.system() == "Windows"
            else ["llama-mtmd-cli"]
        )
        for name in exe_names:
            candidates = [
                repo_dir / "build" / "bin" / "Release" / name,
                repo_dir / "build" / "bin" / name,
            ]
            for c in candidates:
                if c.exists():
                    return str(c)
        return None

    def _find_model_file(self, model_name: str) -> Path | None:
        clean = model_name.split(":")[0].replace("/", "-").lower()
        chat_dir = PhoenixPaths.get_category_path("Chat", "GGUF")
        if not chat_dir.exists():
            return None
        matches = list(chat_dir.glob(f"*{{clean}}*.gguf"))
        for match in matches:
            # >50MB e sem "mmproj" no nome = provavelmente o modelo principal,
            # nao o projetor de imagem (que costuma ter ~1GB tambem, entao
            # o filtro de nome e o que realmente distingue os dois).
            if match.stat().st_size > 50 * 1024 * 1024 and "mmproj" not in match.name.lower():
                return match
        return None

    def _find_mmproj_file(self) -> Path | None:
        chat_dir = PhoenixPaths.get_category_path("Chat", "GGUF")
        if not chat_dir.exists():
            return None
        matches = list(chat_dir.glob("*mmproj*.gguf"))
        return matches[0] if matches else None

    # -----------------------------------------------------------------
    # Ciclo de vida (o runtime "vision" nao mantem processo persistente,
    # entao start/stop/status so reportam disponibilidade do binario)
    # -----------------------------------------------------------------
    async def start(self, plan: ExecutionPlan | None = None) -> bool:
        return self._find_executable() is not None

    async def stop(self) -> bool:
        return True

    async def status(self) -> RuntimeStatus:
        state = RuntimeState.RUNNING if self._find_executable() else RuntimeState.STOPPED
        return RuntimeStatus(name=self.name, state=state)

    # -----------------------------------------------------------------
    # Execucao real: roda o llama-mtmd-cli sobre uma imagem
    # -----------------------------------------------------------------
    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        exe_path = self._find_executable()
        if not exe_path:
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=["llama-mtmd-cli nao encontrado. Compile o llama.cpp com Vulkan (GGML_VULKAN=ON)."],
            )

        model_name = plan.model if plan.model else "minicpmv"
        model_path = self._find_model_file(model_name)
        mmproj_path = self._find_mmproj_file()

        if not model_path or not mmproj_path:
            missing = []
            if not model_path:
                missing.append(f"modelo '{{model_name}}'")
            if not mmproj_path:
                missing.append("mmproj-model-f16.gguf")
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=[f"Arquivos de visao ausentes no disco: {{', '.join(missing)}}"],
            )

        image_path = plan.parameters.get("image_path")
        prompt = plan.parameters.get("prompt", "Descreva esta imagem em detalhes.")

        if not image_path or not Path(image_path).exists():
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=[f"Imagem nao encontrada em: {{image_path}}"],
            )

        cmd = [
            exe_path,
            "-m", str(model_path),
            "--mmproj", str(mmproj_path),
            "-i", str(image_path),
            "-p", prompt,
            "-ngl", "0",  # CPU - deixa a GPU livre pro sd-server (mesma logica do qwen3:8b)
            "-c", "4096",
        ]

        logger.info("MtmdDriver: executando analise de imagem: %s", " ".join(cmd))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(exe_path).parent),
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ExecutionResult(
                    plan_id=plan.id,
                    status=ExecutionStatus.FAILED,
                    errors=["Timeout: a analise da imagem demorou mais de 3 minutos."],
                )

            output_text = stdout.decode("utf-8", errors="replace").strip()

            # O mtmd-cli costuma imprimir logs de carregamento no stdout
            # antes da resposta de verdade - se houver o marcador padrao
            # do template de chat, pegamos so a parte depois dele.
            if "ASSISTANT:" in output_text:
                output_text = output_text.split("ASSISTANT:")[-1].strip()

            if output_text:
                logger.info("MtmdDriver: imagem analisada com sucesso.")
                return ExecutionResult(
                    plan_id=plan.id,
                    status=ExecutionStatus.SUCCESS,
                    output=output_text,
                    started_at=datetime.now(_UTC),
                    finished_at=datetime.now(_UTC),
                )

            err_text = stderr.decode("utf-8", errors="replace").strip()
            logger.error("MtmdDriver: saida vazia. stderr: %s", err_text)
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=[f"Saida vazia do mtmd-cli. stderr: {{err_text[-500:]}}"],
            )

        except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer falha do subprocess
            logger.exception("MtmdDriver: erro inesperado")
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=[f"Erro ao executar mtmd-cli: {{exc}}"],
            )
'''


# =====================================================================
# CONTEUDO: PATCH DO engine.py
# =====================================================================
ENGINE_IMPORT_ANCHOR = "from .drivers.sd_cpp import SdCppDriver"
ENGINE_IMPORT_LINE = "from .drivers.mtmd_driver import MtmdDriver  # Visao nativa (setup_vision.py)"

ENGINE_REGISTER_ANCHOR = '("sdxl", lambda: SdCppDriver(all_cfg, ws_path)),'
ENGINE_REGISTER_MARKER = '"vision"'
ENGINE_REGISTER_LINE = '("vision", lambda: MtmdDriver()),  # Driver de visao (setup_vision.py)'

ENGINE_MANUAL_PATCH_TEXT = f"""\
PATCH MANUAL NECESSARIO: phoenix_kernel/runtime/engine.py
===========================================================
Gerado por setup_vision.py em @GENERATED_AT@

O script nao conseguiu localizar automaticamente os pontos de insercao
neste arquivo (ele pode nao existir ainda, ou o codigo mudou desde a
ultima vez). Faca as duas edicoes abaixo manualmente:

1) No topo do arquivo, junto aos outros imports de driver, adicione:

   {ENGINE_IMPORT_LINE}

2) Na lista `optional_drivers` (dentro de initialize()), procure a linha
   ("sdxl", lambda: SdCppDriver(...)), e adicione logo depois, como um
   novo item da lista (não como statement solto):

   {ENGINE_REGISTER_LINE}
"""


# =====================================================================
# CONTEUDO: PATCH DO api_server.py
# =====================================================================
API_IMPORT_MARKER = "from fastapi import UploadFile, File"
API_IMPORT_ANCHOR_CANDIDATES = [
    "from fastapi import FastAPI",
    "import fastapi",
]

API_ROUTE_MARKER = "/api/describe-image"
API_ROUTE_ANCHOR_CANDIDATES = [
    '@app.post("/api/command")',
    '@app.get("/health")',
]

API_ROUTE_CODE = '''

@app.post("/api/describe-image")
async def describe_image(file: UploadFile = File(...), prompt: str = Form("Descreva esta imagem")):
    """Recebe uma imagem, salva temporariamente e usa o llama-mtmd-cli (MiniCPM-V) para descreve-la.
    Gerado automaticamente por setup_vision.py."""
    import uuid
    import shutil as _shutil
    from pathlib import Path as _Path

    # PHX-FIX: path traversal — sanitiza filename do cliente antes de usar
    # como parte do caminho de disco (ver api_server.py para comentario completo).
    _ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
    _raw_name = (file.filename or "upload").strip()
    _safe_ext = _Path(_raw_name).suffix.lower()
    if _safe_ext not in _ALLOWED_IMAGE_EXTS:
        _safe_ext = ".bin"
    _safe_filename = f"{uuid.uuid4()}{_safe_ext}"

    temp_dir = _Path("temp/vision")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / _safe_filename

    try:
        with temp_file.open("wb") as buffer:
            _shutil.copyfileobj(file.file, buffer)

        from core.domain.execution import ExecutionPlan

        plan = ExecutionPlan(
            runtime="vision",
            model="minicpmv",
            parameters={"image_path": str(temp_file), "prompt": prompt},
            reasoning="Analise de imagem via MiniCPM-V (setup_vision.py)",
        )

        result = await kernel.runtime.execute(plan)

        if result.status == ExecutionStatus.SUCCESS:
            return {"text": result.output}
        return {"error": result.errors[0] if result.errors else "Erro desconhecido na analise"}

    except Exception as e:
        return {"error": str(e)}
    finally:
        if temp_file.exists():
            temp_file.unlink()
'''

API_MANUAL_PATCH_TEXT = f"""\
PATCH MANUAL NECESSARIO: api_server.py
========================================
Gerado por setup_vision.py em @GENERATED_AT@

O script nao conseguiu localizar automaticamente os pontos de insercao
neste arquivo. Faca as duas edicoes abaixo manualmente:

1) Junto aos imports do FastAPI no topo do arquivo, adicione:

   {API_IMPORT_MARKER}

   (garanta tambem que "import uuid", "import shutil" e
   "from pathlib import Path" existem em algum lugar do arquivo - a
   rota abaixo ja importa esses tres localmente, entao isso e so
   redundancia de seguranca, nao bloqueante.)

2) Em qualquer lugar depois de "app = FastAPI(...)" e depois da
   variavel "kernel" existir, cole o bloco de rota abaixo:

{API_ROUTE_CODE}
"""


# =====================================================================
# CATALOGO COMPLETO (usado como fallback se catalog/models.json nao existir)
# =====================================================================
FULL_CATALOG = {
    "qwen3:8b": {
        "name": "Qwen3 8B Instruct (GGUF Q4_K_M)",
        "url": "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf",
        "type": "llm", "architecture": "Qwen3", "parameters": "8B", "quantization": "Q4_K_M",
        "size_gb": 5.03, "min_vram_gb": 6, "context_length": 32768,
        "tags": ["chat", "reasoning", "coding", "portuguese"], "license": "Apache 2.0",
        "backend": ["vulkan", "cpu"], "tok_s_rx580": 9.0,
        "description": "Modelo principal da Phoenix. Excelente raciocinio e suporte a portugues. Roda fluido na RX 580 via Vulkan.",
        "destination_folder": "Chat/GGUF", "filename": "qwen3-8b-q4_k_m.gguf",
    },
    "mistral7b": {
        "name": "Mistral 7B Instruct v0.3 (GGUF Q4_K_M)",
        "url": "https://huggingface.co/QuantFactory/Mistral-7B-Instruct-v0.3-GGUF/resolve/main/Mistral-7B-Instruct-v0.3.Q4_K_M.gguf",
        "type": "llm", "architecture": "Mistral", "parameters": "7B", "quantization": "Q4_K_M",
        "size_gb": 4.37, "min_vram_gb": 6, "context_length": 32768,
        "tags": ["chat", "reasoning", "fast"], "license": "Apache 2.0",
        "backend": ["vulkan", "cpu"], "tok_s_rx580": 17.77,
        "description": "O modelo mais rapido testado na RX 580. 100% GPU Vulkan. Ideal para tarefas gerais.",
        "destination_folder": "Chat/GGUF", "filename": "mistral-7b-instruct-v0.3.Q4_K_M.gguf",
    },
    "llama3.2:3b": {
        "name": "Llama 3.2 3B Instruct (GGUF Q4_K_M)",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "type": "llm", "architecture": "Llama3.2", "parameters": "3B", "quantization": "Q4_K_M",
        "size_gb": 2.02, "min_vram_gb": 3, "context_length": 131072,
        "tags": ["chat", "fast", "small", "portuguese"], "license": "Llama 3.2 Community License",
        "backend": ["vulkan", "cpu"], "tok_s_rx580": None,
        "description": "Modelo pequeno e rapido, bom para respostas curtas/tarefas leves quando o Qwen3/Mistral seriam overkill.",
        "destination_folder": "Chat/GGUF", "filename": "llama-3.2-3b-instruct-q4_k_m.gguf",
    },
    "minicpmv": {
        "name": "MiniCPM-V 4.6 (Vision)",
        # PHX-UPDATE (2026-09-06, pedido do usuário — leu o model card oficial
        # e pediu pra atualizar): trocado de MiniCPM-V 2.6 (LLM base ~8B) para
        # 4.6 (SigLIP2-400M + Qwen3.5-0.8B) — mesma família, arquitetura NOVA e
        # muito mais leve. Suporte no llama.cpp confirmado via mtmd (PR #22529,
        # "mtmd: support MiniCPM-V 4.6", já na release b9049) - o commit já
        # compilado neste projeto (0b5be7e4a, PR #26284 "hip: tune rdna 3 mmq
        # config") é cronologicamente POSTERIOR a essa PR, então o binário já
        # deve suportar sem precisar recompilar - mas ainda não testei rodando
        # de verdade nesta máquina (sem acesso a hardware físico daqui).
        # Fonte: repositório oficial OpenBMB (mesmo padrão já usado pro Flux -
        # preferir sempre o autor original do modelo, não um requant de
        # terceiros de procedência incerta), nomes de arquivo confirmados no
        # guia oficial do MiniCPM-V-CookBook (OpenSQZ/MiniCPM-V-CookBook,
        # deployment/llama.cpp/minicpm-v4_6_llamacpp.md).
        "url": "https://huggingface.co/openbmb/MiniCPM-V-4.6-gguf/resolve/main/MiniCPM-V-4.6-Q4_K_M.gguf",
        "type": "vision", "architecture": "MiniCPM-V (SigLIP2-400M + Qwen3.5-0.8B)", "parameters": "0.8B",
        "quantization": "Q4_K_M",
        # PHX-UPDATE (2026-09-06, confirmado): tamanho do Q4_K_M confirmado
        # DIRETO na página oficial (huggingface.co/openbmb/MiniCPM-V-4.6-gguf,
        # tabela "Hardware compatibility" - 529 MB). Só o mmproj continua
        # estimado (não aparece nessa tabela, que só lista o modelo principal).
        "size_gb": 0.529, "min_vram_gb": 2, "context_length": 8192,
        "tags": ["vision", "image-chat", "multimodal", "on-device"], "license": "Apache 2.0",
        "backend": ["vulkan", "cpu"], "tok_s_rx580": None,
        "description": (
            "Modelo multimodal nativo para leitura e compreensao de imagens via "
            "llama-mtmd-cli. LLM base muito menor que a versao 2.6 (0.8B vs 8B) - "
            "mais rapido e mais leve em VRAM nesta GPU, mantendo compreensao "
            "visual forte (OCRBench, RefCOCO). Requer o componente mmproj - sem "
            "ele o modelo carrega mas nao enxerga."
        ),
        "destination_folder": "Chat/GGUF", "filename": "MiniCPM-V-4.6-Q4_K_M.gguf",
        "components": {
            "mmproj": {
                "url": "https://huggingface.co/openbmb/MiniCPM-V-4.6-gguf/resolve/main/mmproj-MiniCPM-V-4.6-F16.gguf",
                "filename": "mmproj-MiniCPM-V-4.6-F16.gguf", "size_gb": 0.85,  # estimado, ver nota acima
                "note": "OBRIGATORIO. Projetor de imagem (SigLIP2-400M). Sem este arquivo o modelo carrega mas nao enxerga.",
            }
        },
    },
    "flux": {
        "name": "FLUX.1-schnell (GGUF Q4_0) - leejet",
        "url": "https://huggingface.co/leejet/FLUX.1-schnell-gguf/resolve/main/flux1-schnell-q4_0.gguf",
        "type": "image", "architecture": "FLUX", "parameters": "12B", "quantization": "Q4_0",
        "size_gb": 6.88, "min_vram_gb": 6,
        "tags": ["image-gen", "high-quality", "schnell", "sd.cpp"], "license": "Apache 2.0 (Schnell)",
        "backend": ["vulkan"], "tok_s_rx580": None,
        "destination_folder": "Image/Flux", "filename": "flux1-schnell-q4_0.gguf",
        "components": {
            "clip_l": {
                "url": "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors",
                "filename": "clip_l.safetensors", "note": "Repo oficial ComfyOrg. Sem login. 246 MB.",
            },
            "t5xxl": {
                "url": "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors",
                "filename": "t5xxl_fp16.safetensors",
                "note": "Repo oficial ComfyOrg. Sem login. 9.79 GB. Existe tambem a versao fp8 (4.89 GB) mais leve pra RX 580.",
            },
            "vae": {
                "url": "https://huggingface.co/ffxvs/vae-flux/resolve/main/ae.safetensors",
                "filename": "ae.safetensors",
                "note": "Mirror publico sem login (o oficial da black-forest-labs e gated e exige token HF).",
            },
        },
        "description": "Modelo de geracao de imagem de altissima qualidade. Repo leejet homologado para stable-diffusion.cpp.",
    },
    "sd15": {
        "name": "DreamShaper 8 LCM (SD 1.5 GGUF)",
        "url": "https://huggingface.co/stduhpf/dreamshaper-8LCM-im-GGUF-sdcpp/resolve/main/dreamshaper-8-lcm-IQ4_NL.gguf",
        "type": "image", "architecture": "SD1.5", "parameters": "1B", "quantization": "IQ4_NL",
        "size_gb": 1.57, "min_vram_gb": 2,
        "tags": ["image-gen", "fast", "legacy", "sd.cpp"], "license": "CreativeML OpenRAIL-M",
        "backend": ["vulkan"], "tok_s_rx580": None,
        "destination_folder": "Image/StableDiffusion", "filename": "dreamshaper-8-lcm-IQ4_NL.gguf",
        "description": "O classico SD 1.5 pre-convertido para sd.cpp. Ultra rapido na RX 580.",
    },
}


# =====================================================================
# FUNCOES DE SETUP
# =====================================================================
def ensure_dirs(root: Path, workspace: Path) -> dict[str, Path]:
    section("1. CRIANDO ESTRUTURA DE PASTAS")
    dirs = {
        "drivers": root / "phoenix_kernel" / "runtime" / "drivers",
        "catalog": root / "catalog",
        "temp_vision": root / "temp" / "vision",
        "patches": root / "patches",
        "models_gguf": workspace / "Models" / "Chat" / "GGUF",
    }
    for label, d in dirs.items():
        d.mkdir(parents=True, exist_ok=True)
        p("OK", f"{label}: {d}")
    return dirs


def write_driver(drivers_dir: Path, generated_at: str) -> Path:
    section("2. ESCREVENDO O DRIVER DE VISAO (mtmd_driver.py)")
    driver_path = drivers_dir / "mtmd_driver.py"
    code = MTMD_DRIVER_CODE.format(generated_at=generated_at)
    driver_path.write_text(code, encoding="utf-8")
    p("OK", f"Driver escrito em: {driver_path}")
    return driver_path


def update_catalog(catalog_dir: Path) -> Path:
    section("3. ATUALIZANDO catalog/models.json")
    catalog_path = catalog_dir / "models.json"

    if catalog_path.exists():
        try:
            existing = json.loads(catalog_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            backup = catalog_path.with_suffix(".json.bak")
            shutil.copy2(catalog_path, backup)
            p("WARN", f"models.json existente esta com JSON invalido ({exc}). "
                      f"Backup salvo em {backup}. Escrevendo catalogo completo novo.")
            existing = {}
    else:
        existing = {}
        p("INFO", "catalog/models.json nao existia - sera criado do zero.")

    if "minicpmv" in existing:
        p("OK", "Entrada 'minicpmv' ja existia no catalogo - mantendo como estava (nao sobrescrevo edicoes suas).")
    else:
        # Preserva tudo que ja existe; so injeta a entrada que falta.
        # Se o catalogo estava vazio/novo, usa o catalogo de referencia completo.
        if existing:
            existing["minicpmv"] = FULL_CATALOG["minicpmv"]
        else:
            existing = dict(FULL_CATALOG)
        p("OK", "Entrada 'minicpmv' adicionada ao catalogo.")

    catalog_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    p("OK", f"Catalogo salvo em: {catalog_path}")
    return catalog_path


def _already_patched(text: str, marker: str) -> bool:
    return marker in text


def patch_engine(root: Path, patches_dir: Path, generated_at: str) -> None:
    section("4. APLICANDO PATCH em phoenix_kernel/runtime/engine.py")
    engine_path = root / "phoenix_kernel" / "runtime" / "engine.py"

    if not engine_path.exists():
        p("WARN", f"engine.py nao encontrado em {engine_path}. Gerando instrucoes manuais.")
        _write_manual(patches_dir, "ENGINE_PATCH_MANUAL.txt", ENGINE_MANUAL_PATCH_TEXT, generated_at)
        return

    text = engine_path.read_text(encoding="utf-8")
    original = text
    changed = False

    if _already_patched(text, "mtmd_driver"):
        p("OK", "Import do MtmdDriver ja presente em engine.py - pulando.")
    elif ENGINE_IMPORT_ANCHOR in text:
        # PHX-FIX: a versao anterior hardcodava 12 espacos de indentacao
        # assumindo que a ancora estava dentro de um bloco indentado. A
        # ancora (`from .drivers.sd_cpp import SdCppDriver`) fica no nivel
        # do modulo (coluna 0), entao 12 espacos extras quebravam o arquivo
        # com IndentationError. Agora calcula a indentacao real da linha,
        # igual a rotina de registro logo abaixo ja fazia.
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if ENGINE_IMPORT_ANCHOR in line:
                indent = line[: len(line) - len(line.lstrip())]
                lines.insert(i + 1, f"{indent}{ENGINE_IMPORT_LINE}\n")
                changed = True
                break
        text = "".join(lines)
        p("OK", "Import do MtmdDriver inserido.")
    else:
        p("WARN", f"Ancora de import ('{ENGINE_IMPORT_ANCHOR}') nao encontrada em engine.py.")

    if _already_patched(text, ENGINE_REGISTER_MARKER):
        p("OK", "Registro do driver 'vision' ja presente em engine.py - pulando.")
    elif ENGINE_REGISTER_ANCHOR in text:
        # Insere apos a linha inteira que contem a ancora (nao so o fragmento)
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if ENGINE_REGISTER_ANCHOR in line:
                indent = line[: len(line) - len(line.lstrip())]
                lines.insert(i + 1, f"{indent}{ENGINE_REGISTER_LINE}\n")
                changed = True
                break
        text = "".join(lines)
        p("OK", "Registro do driver 'vision' inserido.")
    else:
        p("WARN", f"Ancora de registro ('{ENGINE_REGISTER_ANCHOR}') nao encontrada em engine.py.")

    if changed:
        backup = engine_path.with_suffix(".py.bak")
        backup.write_text(original, encoding="utf-8")
        engine_path.write_text(text, encoding="utf-8")
        p("OK", f"engine.py atualizado (backup do original em {backup.name}).")
    elif original == text:
        p("INFO", "Nenhuma alteracao necessaria em engine.py.")

    if "Ancora" in "".join([]):  # noop, mantem estrutura clara
        pass

    missing_import = ENGINE_IMPORT_ANCHOR not in original and "mtmd_driver" not in original
    missing_register = ENGINE_REGISTER_ANCHOR not in original and ENGINE_REGISTER_MARKER not in original
    if missing_import or missing_register:
        _write_manual(patches_dir, "ENGINE_PATCH_MANUAL.txt", ENGINE_MANUAL_PATCH_TEXT, generated_at)
        p("WARN", "Instrucoes manuais geradas em patches/ENGINE_PATCH_MANUAL.txt para o que nao pode ser automatizado.")


def patch_api_server(root: Path, patches_dir: Path, generated_at: str) -> None:
    section("5. APLICANDO PATCH em api_server.py")
    api_path = root / "api_server.py"

    if not api_path.exists():
        p("WARN", f"api_server.py nao encontrado em {api_path}. Gerando instrucoes manuais.")
        _write_manual(patches_dir, "API_SERVER_PATCH_MANUAL.txt", API_ROUTE_CODE, generated_at, prefix=API_MANUAL_PATCH_TEXT)
        return

    text = api_path.read_text(encoding="utf-8")
    original = text
    changed = False

    if API_IMPORT_MARKER in text:
        p("OK", "Import 'UploadFile, File' ja presente em api_server.py - pulando.")
    else:
        anchor_found = None
        for anchor in API_IMPORT_ANCHOR_CANDIDATES:
            if anchor in text:
                anchor_found = anchor
                break
        if anchor_found:
            text = text.replace(anchor_found, f"{anchor_found}\n{API_IMPORT_MARKER}", 1)
            changed = True
            p("OK", "Import 'UploadFile, File' inserido.")
        else:
            p("WARN", "Nenhuma ancora de import do FastAPI encontrada em api_server.py.")

    if API_ROUTE_MARKER in text:
        p("OK", "Rota /api/describe-image ja presente em api_server.py - pulando.")
    else:
        anchor_found = None
        for anchor in API_ROUTE_ANCHOR_CANDIDATES:
            if anchor in text:
                anchor_found = anchor
                break
        if anchor_found:
            text = text.replace(anchor_found, f"{API_ROUTE_CODE}\n\n{anchor_found}", 1)
            changed = True
            p("OK", "Rota /api/describe-image inserida.")
        else:
            p("WARN", "Nenhuma ancora de rota encontrada em api_server.py - a rota nao foi inserida automaticamente.")

    if changed:
        backup = api_path.with_suffix(".py.bak")
        backup.write_text(original, encoding="utf-8")
        api_path.write_text(text, encoding="utf-8")
        p("OK", f"api_server.py atualizado (backup do original em {backup.name}).")
    elif original == text:
        p("INFO", "Nenhuma alteracao necessaria em api_server.py.")

    missing_import = API_IMPORT_MARKER not in original and not any(a in original for a in API_IMPORT_ANCHOR_CANDIDATES)
    missing_route = API_ROUTE_MARKER not in original and not any(a in original for a in API_ROUTE_ANCHOR_CANDIDATES)
    if missing_import or missing_route:
        _write_manual(patches_dir, "API_SERVER_PATCH_MANUAL.txt", API_ROUTE_CODE, generated_at, prefix=API_MANUAL_PATCH_TEXT)
        p("WARN", "Instrucoes manuais geradas em patches/API_SERVER_PATCH_MANUAL.txt para o que nao pode ser automatizado.")


def _write_manual(patches_dir: Path, filename: str, body: str, generated_at: str, prefix: str | None = None) -> None:
    patches_dir.mkdir(parents=True, exist_ok=True)
    raw = prefix if prefix is not None else body
    # Usamos .replace() (nao .format()) de proposito: 'body'/'prefix' podem
    # conter codigo Python com chaves literais (ex: {uuid.uuid4()}), que
    # .format() interpretaria erroneamente como placeholders.
    content = raw.replace("@GENERATED_AT@", generated_at)
    (patches_dir / filename).write_text(content, encoding="utf-8")


def maybe_download_models(models_dir: Path, do_download: bool) -> None:
    section("6. MODELOS .GGUF DE VISAO")
    targets = [
        # PHX-UPDATE (2026-09-06): ver a mesma atualização no MODEL_CATALOG
        # acima (achado real: esta lista era um SEGUNDO lugar duplicado com
        # os mesmos nomes de arquivo hardcoded — mesmo padrão de duplicação
        # já visto e corrigido no catálogo do Flux).
        ("MiniCPM-V-4.6-Q4_K_M.gguf",
         "https://huggingface.co/openbmb/MiniCPM-V-4.6-gguf/resolve/main/MiniCPM-V-4.6-Q4_K_M.gguf",
         0.529),  # confirmado na página oficial (tabela Hardware compatibility)
        ("mmproj-MiniCPM-V-4.6-F16.gguf",
         "https://huggingface.co/openbmb/MiniCPM-V-4.6-gguf/resolve/main/mmproj-MiniCPM-V-4.6-F16.gguf",
         0.85),  # estimado, ver nota no MODEL_CATALOG
    ]

    if not do_download:
        p("INFO", f"Download automatico desligado (padrao). Os arquivos abaixo devem existir em: {models_dir}")
        for name, url, size in targets:
            dest = models_dir / name
            status = "presente" if dest.exists() else "AUSENTE"
            p("OK" if dest.exists() else "WARN", f"{name} (~{size} GB) - {status}")
        p("INFO", "Rode com --download-models para baixar automaticamente, ou use a Secao 8 do common.ps1.")
        return

    for name, url, size_gb in targets:
        dest = models_dir / name
        if dest.exists():
            p("OK", f"{name} ja existe ({dest.stat().st_size / (1024**3):.2f} GB) - pulando.")
            continue
        p("INFO", f"Baixando {name} (~{size_gb} GB) de {url} ...")
        tmp_dest = dest.with_suffix(dest.suffix + ".part")
        try:
            def _report(block_num, block_size, total_size):
                if total_size <= 0:
                    return
                pct = min(100.0, block_num * block_size * 100 / total_size)
                print(f"\r    {pct:5.1f}%", end="", flush=True)

            urllib.request.urlretrieve(url, tmp_dest, reporthook=_report)
            print()
            tmp_dest.rename(dest)
            p("OK", f"{name} baixado com sucesso.")
        except Exception as exc:  # noqa: BLE001
            print()
            p("FAIL", f"Falha ao baixar {name}: {exc}")
            if tmp_dest.exists():
                tmp_dest.unlink()


# =====================================================================
# MAIN
# =====================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Monta o ambiente de visao nativa da Phoenix (MiniCPM-V).")
    parser.add_argument("--root", default=".", help="Raiz do projeto Phoenix (pasta do api_server.py). Default: diretorio atual.")
    parser.add_argument("--workspace", default=None, help="Pasta do workspace (onde ficam os Models). Default: <root>/Workstations")
    parser.add_argument("--download-models", action="store_true", help="Baixa os .gguf de visao automaticamente (~1.4 GB - modelo confirmado, mmproj estimado).")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    workspace = Path(args.workspace).resolve() if args.workspace else root / "Workstations"
    generated_at = datetime.now().isoformat(timespec="seconds")

    print(f"{C.INFO if _COLOR else ''}" + "=" * 70)
    print("   PHOENIX VISION SETUP (MiniCPM-V-4.6 + llama-mtmd-cli)")
    print("=" * 70 + (C.ENDC if _COLOR else ""))
    p("INFO", f"Raiz do projeto: {root}")
    p("INFO", f"Workspace (Models): {workspace}")

    if not (root / "api_server.py").exists():
        p("WARN", f"api_server.py nao encontrado em {root}. Confirme se --root aponta pra pasta certa do Phoenix.")

    dirs = ensure_dirs(root, workspace)
    write_driver(dirs["drivers"], generated_at)
    update_catalog(dirs["catalog"])
    patch_engine(root, dirs["patches"], generated_at)
    patch_api_server(root, dirs["patches"], generated_at)
    maybe_download_models(dirs["models_gguf"], args.download_models)

    section("CONCLUIDO")
    p("OK", "Ambiente de visao montado.")
    p("INFO", "Se algum patch nao pode ser aplicado automaticamente, confira a pasta 'patches/' na raiz do projeto.")
    p("WARN", "Sem o mmproj-model-f16.gguf no disco, o modelo carrega mas fica cego - confirme que ele existe antes de testar.")


if __name__ == "__main__":
    main()