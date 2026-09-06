"""
phoenix_kernel/runtime/drivers/comfyui.py

ComfyUI Driver com detecção automática de backend GPU:
  - CUDA disponível (RTX/GTX/etc): tenta ComfyUI com --cuda-device 0
  - ROCm disponível (RX 6000+ nativo): tenta --cuda-device 0 via ROCm
  - Vulkan (fallback universal, SEMPRE disponível via sd.cpp): delega ao SdCppDriver
  - Sem GPU detectada: CPU mode

A lógica de "placa nova = tenta CUDA/ROCm, placa legada = Vulkan via sd.cpp"
é implementada aqui, não no planner. O planner decide QUANDO gerar imagem;
o driver decide COMO, com base na capacidade real da máquina.

Detecção:
  - capabilities.cuda = True  →  tenta ComfyUI via CUDA (RTX/GTX)
  - capabilities.rocm = True  →  tenta ComfyUI via ROCm (RX 6000+)
  - capabilities.vulkan = True + sem cuda/rocm  →  Vulkan via sd.cpp (RX 500/580 etc)
  - nenhum  →  CPU mode via sd.cpp

Por que delegar ao SdCppDriver e não subir o ComfyUI diretamente pra Vulkan?
Porque o ComfyUI não tem suporte oficial a Vulkan - ele usa CUDA/ROCm. Pra
Vulkan (o caso da RX 580 desta máquina), o caminho correto é o sd.cpp com
--offload-to-cpu, que já está validado e funcionando. Não faz sentido subir
um servidor ComfyUI pra uma placa que não consegue rodar via CUDA/ROCm.
"""
from __future__ import annotations
import asyncio
import logging
import platform
import subprocess
import shutil
from pathlib import Path

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeStatus, RuntimeState
from phoenix_kernel.paths import PhoenixPaths

logger = logging.getLogger(__name__)


def _discover_project_root(start_file: Path) -> Path:
    current = start_file.resolve()
    for _ in range(8):
        current = current.parent
        if (current / "repos").exists() or (current / "phoenix_kernel").exists():
            return current
    return start_file.resolve().parent.parent.parent.parent


def _detect_gpu_backend() -> str:
    """Detecta o backend GPU disponível.
    Retorna: 'cuda' | 'rocm' | 'vulkan' | 'cpu'
    """
    try:
        from phoenix_kernel.ahde.facade import AHDE
        # Tenta ler do AHDE se já estiver disponível como singleton
        # (só funciona se o kernel já inicializou)
        pass
    except Exception:
        pass

    # Detecção direta — não depende do AHDE estar inicializado
    # CUDA: nvidia-smi ou torch.cuda
    if _has_nvidia_cuda():
        return 'cuda'

    # ROCm: rocm-smi ou platform AMD (RX 6000+)
    if _has_amd_rocm():
        return 'rocm'

    # Vulkan: qualquer GPU moderna que não tem CUDA/ROCm (RX 500/580, Intel Arc, etc)
    if _has_vulkan():
        return 'vulkan'

    return 'cpu'


def _has_nvidia_cuda() -> bool:
    """Verifica CUDA via nvidia-smi (mais confiável que torch)."""
    if shutil.which('nvidia-smi'):
        try:
            r = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                             capture_output=True, text=True, timeout=5)
            return r.returncode == 0 and r.stdout.strip()
        except Exception:
            pass
    # Fallback: verifica se torch.cuda está disponível
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        pass
    return False


def _has_amd_rocm() -> bool:
    """Verifica ROCm via rocm-smi."""
    if shutil.which('rocm-smi'):
        try:
            r = subprocess.run(['rocm-smi', '--showid'], capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except Exception:
            pass
    # Fallback: hipconfig
    if shutil.which('hipconfig'):
        return True
    return False


def _has_vulkan() -> bool:
    """Verifica Vulkan via vulkaninfo (SDK) ou VK_ICD_FILENAMES."""
    import os
    if shutil.which('vulkaninfo'):
        try:
            r = subprocess.run(['vulkaninfo', '--summary'], capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except Exception:
            pass
    # Se tem RADV ou mesa-vulkan-drivers no Linux, provavelmente ok
    if platform.system() == 'Linux':
        for p in ['/usr/lib/x86_64-linux-gnu/libvulkan.so.1', '/usr/lib/libvulkan.so.1']:
            if Path(p).exists():
                return True
    # No Windows, assume Vulkan se tem GPU AMD (driver RADV/AMDVLK)
    return platform.system() == 'Windows'


def _find_comfyui_executable(project_root: Path) -> Path | None:
    """Procura ComfyUI instalado localmente (venv ou sistema)."""
    candidates = [
        project_root / "repos" / "ComfyUI" / "main.py",
        project_root / "repos" / "comfyui" / "main.py",
        Path.home() / "ComfyUI" / "main.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _find_python_executable(project_root: Path) -> str:
    """Encontra o Python do venv do projeto, ou o sistema."""
    venv_python = project_root / "venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    venv_python_linux = project_root / "venv" / "bin" / "python"
    if venv_python_linux.exists():
        return str(venv_python_linux)
    return shutil.which('python3') or shutil.which('python') or 'python'


class ComfyUIDriver:
    """
    Driver para ComfyUI com fallback automático para Vulkan (sd.cpp).

    Hierarquia de backends:
      1. CUDA  →  ComfyUI nativo (RTX/GTX — melhor qualidade e velocidade)
      2. ROCm  →  ComfyUI nativo via ROCm (RX 6000+)
      3. Vulkan →  Delega ao SdCppDriver (RX 580/500 e qualquer placa sem CUDA/ROCm)
      4. CPU   →  SdCppDriver em modo CPU (lento mas funciona)
    """

    def __init__(self, config: dict = None) -> None:
        self._config = config or {}
        self._project_root = _discover_project_root(Path(__file__))
        self._process = None
        self._backend = None  # detectado lazily no primeiro execute()
        self._comfyui_port = self._config.get('comfyui_port', 8188)

    @property
    def name(self) -> str:
        return "comfyui"

    def _get_backend(self) -> str:
        """Detecta e cacheia o backend GPU."""
        if self._backend is None:
            self._backend = _detect_gpu_backend()
            logger.info(f"ComfyUIDriver: backend detectado = '{self._backend}'")
        return self._backend

    async def start(self, plan: ExecutionPlan | None = None) -> bool:
        backend = self._get_backend()
        if backend == 'cpu':
            logger.error("ComfyUIDriver: GPU-only ativo e nenhuma GPU compatível foi detectada.")
            return False
        if backend == 'vulkan':
            logger.info("ComfyUIDriver: Vulkan detectado — usando SdCppDriver GPU-only.")
            return True

        # CUDA/ROCm: tenta subir ComfyUI como servidor local
        comfyui_main = _find_comfyui_executable(self._project_root)
        if comfyui_main is None:
            logger.warning("ComfyUIDriver: ComfyUI não instalado em repos/ComfyUI/. Usando fallback sd.cpp.")
            self._backend = 'vulkan'
            return True

        python_exe = _find_python_executable(self._project_root)
        args = [
            python_exe, str(comfyui_main),
            '--port', str(self._comfyui_port),
        ]
        if backend == 'cuda':
            args.extend(['--cuda-device', '0'])
        elif backend == 'rocm':
            args.extend(['--cuda-device', '0'])  # ROCm usa o mesmo flag via HIP

        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(comfyui_main.parent)
            )
            await asyncio.sleep(5)  # aguarda subir
            if self._process.returncode is not None:
                logger.warning("ComfyUIDriver: servidor ComfyUI encerrou imediatamente. Fallback para sd.cpp.")
                self._backend = 'vulkan'
            else:
                logger.info(f"ComfyUIDriver: servidor ComfyUI subiu na porta {self._comfyui_port} (backend: {backend}).")
            return True
        except Exception as e:
            logger.warning(f"ComfyUIDriver: falha ao iniciar ComfyUI ({e}). Fallback para sd.cpp.")
            self._backend = 'vulkan'
            return True

    async def stop(self) -> bool:
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except Exception:
                self._process.kill()
        self._process = None
        return True

    async def status(self) -> RuntimeStatus:
        if self._process and self._process.returncode is None:
            return RuntimeStatus(name=self.name, state=RuntimeState.RUNNING)
        return RuntimeStatus(name=self.name, state=RuntimeState.STOPPED)

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        backend = self._get_backend()

        # Placa legada (Vulkan/CPU) ou ComfyUI não disponível → delega ao SdCppDriver
        if backend == 'cpu':
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=["GPU-only ativo: nenhuma GPU compatível."])
        if backend == 'vulkan':
            logger.info("ComfyUIDriver: Vulkan → SdCppDriver GPU-only.")
            try:
                from phoenix_kernel.runtime.drivers.phoenix_diffusion import PhoenixDiffusionDriver
                sd = PhoenixDiffusionDriver()
                return await sd.execute(plan)
            except Exception as e:
                return ExecutionResult(
                    plan_id=plan.id, status=ExecutionStatus.FAILED,
                    errors=[f"ComfyUIDriver: falha ao delegar ao SdCppDriver: {e}"]
                )

        # CUDA/ROCm com ComfyUI rodando: envia workflow via API
        if self._process is None or self._process.returncode is not None:
            # Servidor caiu ou nunca subiu — inicia agora
            await self.start(plan)
            if self._backend in ('vulkan', 'cpu'):
                return await self.execute(plan)  # recurse após fallback

        try:
            import json
            import urllib.request

            prompt = plan.parameters.get('prompt', 'a majestic phoenix bird, cinematic lighting')
            width = int(plan.parameters.get('width', 512))
            height = int(plan.parameters.get('height', 512))
            steps = int(plan.parameters.get('steps', 20))
            seed = int(plan.parameters.get('seed', 42))

            # Workflow mínimo ComfyUI (KSampler básico)
            workflow = {
                "3": {"class_type": "KSampler", "inputs": {
                    "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                    "latent_image": ["5", 0], "seed": seed, "steps": steps,
                    "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0
                }},
                "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": plan.model or "v1-5-pruned-emaonly.ckpt"}},
                "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
                "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
                "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
                "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "phoenix_comfyui"}}
            }

            payload = json.dumps({"prompt": workflow}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{self._comfyui_port}/prompt",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"}
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                result_data = json.loads(resp.read())
                prompt_id = result_data.get("prompt_id", "")

            # Aguarda conclusão polling simples (máx 20 min)
            for _ in range(1200):
                await asyncio.sleep(1)
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{self._comfyui_port}/history/{prompt_id}", timeout=5) as h:
                        history = json.loads(h.read())
                        if prompt_id in history:
                            outputs = history[prompt_id].get("outputs", {})
                            for node_output in outputs.values():
                                images = node_output.get("images", [])
                                if images:
                                    img_info = images[0]
                                    return ExecutionResult(
                                        plan_id=plan.id, status=ExecutionStatus.SUCCESS,
                                        output=f"ComfyUI ({backend}): {img_info.get('filename', 'imagem gerada')}"
                                    )
                except Exception:
                    pass

            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED,
                                   errors=["ComfyUI: timeout aguardando geração (20 min)."])

        except Exception as e:
            logger.warning(f"ComfyUIDriver: falha na execução via ComfyUI ({e}). Tentando fallback sd.cpp.")
            try:
                from phoenix_kernel.runtime.drivers.phoenix_diffusion import PhoenixDiffusionDriver
                sd = PhoenixDiffusionDriver()
                return await sd.execute(plan)
            except Exception as e2:
                return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED,
                                       errors=[f"Falha no ComfyUI ({e}) e no fallback sd.cpp ({e2})."])
