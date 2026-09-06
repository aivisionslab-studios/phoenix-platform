"""Driver oficial Phoenix Diffusion: bridge C ABI, sem sd-cli/HTTP/clone."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

import psutil

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeState, RuntimeStatus
from phoenix_kernel.paths import PhoenixPaths
from phoenix_kernel.runtime.native.phoenix_sd_native import GenerationConfig, ModelConfig

from .phoenix_diffusion_worker import run_worker
from .sd_cpp import _check_known_failure, _select_profile

logger = logging.getLogger(__name__)
_UTC = timezone.utc
_MIN_VALID_IMAGE_BYTES = 100


class NativeWorkerExitedError(RuntimeError):
    """O processo C/Vulkan encerrou sem conseguir devolver uma resposta RPC."""


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _native_placement_defaults(profile: dict[str, Any]) -> dict[str, Any]:
    """Traduz os aliases CLI validados para os campos da API C atual.

    O sd-cli ainda aceita ``--clip-on-cpu``/``--vae-on-cpu`` e
    ``--offload-to-cpu``, mas essa tradução acontece apenas no parser do
    executável. A Phoenix chama a biblioteca diretamente, portanto precisa
    preencher ``backend``/``params_backend`` e desativar ``auto_fit`` (que,
    quando ligado, ignora justamente esses dois campos).
    """
    flags = set(profile.get("extra_flags", ()))
    runtime_assignments: list[str] = []
    if "--clip-on-cpu" in flags:
        runtime_assignments.append("te=cpu")
    if "--vae-on-cpu" in flags:
        runtime_assignments.append("vae=cpu")
    if "--control-net-cpu" in flags:
        runtime_assignments.append("controlnet=cpu")

    params_backend = "*=cpu" if "--offload-to-cpu" in flags else None
    has_explicit_placement = bool(runtime_assignments or params_backend)
    backend = ",".join(("all=gpu", *runtime_assignments)) if runtime_assignments else None
    return {
        "backend": backend,
        "params_backend": params_backend,
        "auto_fit": not has_explicit_placement,
        "max_vram": None if has_explicit_placement else "-0.75",
        "stream_layers": False if has_explicit_placement else True,
    }


def _native_placement_candidates(
    profile: dict[str, Any], parameters: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    """Monta tentativas realmente distintas para a API C do sd.cpp.

    O patch anterior usava ``None`` como "use o default" e, com isso, os
    quatro degraus continuavam recebendo ``max_vram=-0.75``. Portanto todos
    ainda ativavam graph-cut e não reproduziam o comando Flux historicamente
    funcional. Aqui ``None`` significa de fato ponteiro nulo na API C.
    """
    defaults = _native_placement_defaults(profile)
    overrides = profile.get("native_overrides", {})
    placement_keys = {
        "backend", "params_backend", "auto_fit", "max_vram",
        "stream_layers", "split_mode", "mmap",
    }
    has_user_placement = any(key in parameters for key in placement_keys)

    base = {
        "backend": _optional_text(parameters.get("backend", defaults["backend"])),
        "params_backend": _optional_text(
            parameters.get("params_backend", defaults["params_backend"])
        ),
        "auto_fit": bool(parameters.get("auto_fit", defaults["auto_fit"])),
        "max_vram": _optional_text(
            parameters.get("max_vram", defaults["max_vram"])
        ),
        "split_mode": str(parameters.get("split_mode", "layer")),
        "stream_layers": bool(
            parameters.get(
                "stream_layers",
                overrides.get("stream_layers", defaults["stream_layers"]),
            )
        ),
        "enable_mmap": bool(parameters.get("mmap", overrides.get("mmap", True))),
    }
    profile_name = str(profile.get("name", "")).lower()
    supports_hybrid_fallback = profile_name.startswith("flux") or profile_name.startswith("z-image")
    if has_user_placement or not supports_hybrid_fallback:
        return [("configurado", base)]

    # PHX-FIX (auditoria Claude, 2026-09-05): os 4 candidatos abaixo usavam
    # max_vram=None em 3 dos 4 placements. None desativa por completo o
    # mecanismo de "graph cut" do stable-diffusion.cpp (ver
    # sd::ggml_graph_cut::MaxVramAssignment em core/ggml_graph_cut.cpp/.h,
    # consumido em stable-diffusion.cpp via sd_ctx_params->max_vram) - sem
    # um valor, o processo nunca reserva margem pros buffers de
    # conditioning (T5XXL/CLIP) e tenta alocar até estourar a VRAM real da
    # placa. Foi exatamente esse buraco que causou o
    # "ggml_vulkan: ErrorOutOfDeviceMemory" seguido do
    # "GGML_ASSERT(!chunk_hidden_states.empty())" no placement 'auto-fit'
    # (log real do usuário, RX 580 8GB) - o T5 tentou computar sem margem
    # nenhuma reservada.
    #
    # Valor usado: "-1.7" (reserva 1.7 GiB de VRAM livre; negativo = "detecta
    # o que está livre agora e reserva essa margem", ver
    # build_and_runtime_flags_reference.json). 1.7 GiB não é arbitrário -
    # é a MESMA matemática da "Regra 6.3GB VRAM" que já existe na UI da
    # Aviary e em phoenix_kernel/models/hardware_fit.py (1.2GB de buffer de
    # compute + 0.5GB de folga de segurança), só que aquele módulo nunca
    # era chamado pra geração de imagem - só pra colaboração de dois
    # modelos de texto. Isso aplica a mesma regra aqui, no lugar que
    # faltava.
    _VRAM_RESERVE = "-1.7"

    return [
        # Híbrido oficialmente suportado: pesos na RAM/CPU, diffusion na
        # Vulkan, encoder e VAE executados na CPU. Com graph-cut ativo
        # (max_vram reservando margem) em vez de desligado.
        (
            "hybrid-cpu-gpu",
            {
                **base,
                "auto_fit": False,
                "max_vram": _VRAM_RESERVE,
                "stream_layers": False,
                "enable_mmap": True,
            },
        ),
        # Auto-fit pode mover um componente inteiro para CPU ou usar
        # time-share quando ele não cabe em uma GPU. Antes sem orçamento
        # forçado nenhum - agora reserva a mesma margem que os outros.
        (
            "auto-fit",
            {
                "backend": None,
                "params_backend": None,
                "auto_fit": True,
                "max_vram": _VRAM_RESERVE,
                "split_mode": "layer",
                "stream_layers": False,
                "enable_mmap": False,
            },
        ),
        # O split CPU/GPU válido para uma única GPU no sd.cpp é streaming:
        # pesos ficam em CPU e cada bloco é enviado à Vulkan sob demanda.
        # `gpu&cpu` não é usado porque o próprio backend rejeita CPU em
        # listas de layer split e recua silenciosamente para a GPU.
        # Já reservava -2.0 (mais conservador ainda que os outros três) -
        # mantido como estava.
        (
            "hybrid-streaming",
            {
                "backend": "all=gpu,te=cpu,vae=cpu",
                "params_backend": "*=cpu",
                "auto_fit": False,
                "max_vram": "-2.0",
                "split_mode": "layer",
                "stream_layers": True,
                "enable_mmap": False,
            },
        ),
        # Último recurso: parâmetros em RAM, mas o enorme TE relido do disco.
        (
            "text-encoder-disk",
            {
                "backend": base["backend"],
                "params_backend": "*=cpu,te=disk",
                "auto_fit": False,
                "max_vram": _VRAM_RESERVE,
                "split_mode": "layer",
                "stream_layers": False,
                "enable_mmap": True,
            },
        ),
    ]


def _project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "src" / "phoenix-diffusion.cpp" / "CMakeLists.txt").is_file():
            return parent
    return Path(__file__).resolve().parents[3]


class PhoenixDiffusionDriver:
    """Mantém o modelo residente em processo isolado usando a bridge nativa."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self._project_root = _project_root()
        self._process: multiprocessing.Process | None = None
        self._connection: Connection | None = None
        self._loaded_signature: tuple[tuple[str, Any], ...] | None = None
        self._bridge_info: dict[str, Any] = {}
        self._start_error = ""

    @property
    def name(self) -> str:
        return "phoenix-diffusion"

    @property
    def startup_error(self) -> str:
        """Diagnóstico preservado quando start() retorna False."""
        return self._start_error

    def _bridge_candidates(self) -> list[Path]:
        source = self._project_root / "src" / "phoenix-diffusion.cpp"
        env_path = os.environ.get("PHOENIX_SD_BRIDGE", "").strip()
        names = ["phoenix_sd_bridge.dll"] if platform.system() == "Windows" else [
            "libphoenix_sd_bridge.so", "libphoenix_sd_bridge.dylib"
        ]
        candidates = [Path(env_path)] if env_path else []
        # A cópia promovida pelo instalador/reparador é a fonte estável.
        # Builds dentro de src/ ficam como fallback para desenvolvimento.
        for base in (
            self._project_root / "bin",
            source / "build" / "windows-rx580-vulkan" / "bin" / "Release",
            source / "build" / "windows-rx580-vulkan" / "bin",
            source / "build" / "bin" / "Release",
            source / "build" / "bin",
        ):
            candidates.extend(base / name for name in names)
        return candidates

    def _find_bridge(self) -> Path | None:
        return next((path for path in self._bridge_candidates() if path.is_file()), None)

    def _find_model_file(self, model_name: str) -> Path | None:
        clean = model_name.split(":")[0].replace("/", "-").lower()
        image_dir = PhoenixPaths.get_category_path("Image")
        candidates: list[Path] = []
        if image_dir.exists():
            candidates.extend(image_dir.rglob(f"*{clean}*.gguf"))
            candidates.extend(image_dir.rglob(f"*{clean}*.safetensors"))
        if candidates:
            return self._pick_best_component_match(candidates, clean)
        for partition in psutil.disk_partitions(all=False):
            for hint in ("models", "image-models"):
                try:
                    root = Path(partition.mountpoint) / hint
                    if root.exists():
                        found = list(root.rglob(f"*{clean}*.gguf")) + list(root.rglob(f"*{clean}*.safetensors"))
                        if found:
                            return self._pick_best_component_match(found, clean)
                except (OSError, PermissionError):
                    continue
        return None

    def _pick_best_component_match(self, matches: list[Path], hint: str) -> Path:
        """PHX-FIX (auditoria Claude, achado ao investigar risco de colisão
        de nomes entre modelos que compartilham a mesma pasta Models/Image):
        antes desta função, _find_component() sempre devolvia matches[0] -
        o primeiro arquivo que o rglob encontrasse, em qualquer ordem que o
        sistema de arquivos decidisse devolver (não é alfabética nem
        garantida). Com um único arquivo por hint isso nunca deu problema
        (confirmado - nenhuma colisão real nos arquivos atuais), mas é uma
        armadilha silenciosa: se dois modelos diferentes um dia tiverem
        arquivos cujo nome contenha o mesmo hint (ex: dois "ae*.safetensors"
        de VAEs diferentes), o driver carregaria QUALQUER um dos dois sem
        erro nem aviso - o gerador rodaria normalmente, só que com o
        componente errado.

        Critério: prefere match EXATO de nome (stem ou nome completo igual
        ao hint, sem diferenciar maiúsculas/minúsculas) sobre match por
        substring solto. Se ainda houver ambiguidade, ordena
        deterministicamente (em vez de depender da ordem do SO) e avisa no
        log quais candidatos existiam e qual foi escolhido, pra quem estiver
        depurando um resultado de imagem estranho saber onde olhar."""
        if len(matches) == 1:
            return matches[0]

        exact = [
            p for p in matches
            if p.stem.lower() == hint.lower() or p.name.lower() == hint.lower()
        ]
        candidates = exact if len(exact) == 1 else (exact or matches)
        candidates_sorted = sorted(candidates, key=lambda p: str(p).lower())

        if len(candidates_sorted) > 1:
            logger.warning(
                "PhoenixDiffusion: %d arquivos batem no hint '%s' - escolhendo "
                "'%s'. Candidatos: %s. Renomeie ou mova os arquivos duplicados "
                "pra pastas separadas por modelo se isso não for o esperado.",
                len(candidates_sorted), hint, candidates_sorted[0],
                [str(p) for p in candidates_sorted],
            )
        return candidates_sorted[0]

    def _find_component(self, hints: list[str]) -> Path | None:
        roots: list[Path] = []
        image_dir = PhoenixPaths.get_category_path("Image")
        if image_dir.exists():
            roots.append(image_dir)
        for partition in psutil.disk_partitions(all=False):
            for hint in ("models", "image-models"):
                root = Path(partition.mountpoint) / hint
                if root.exists():
                    roots.append(root)
        for root in roots:
            for hint in hints:
                try:
                    matches = [p for p in root.rglob(f"*{hint}*") if p.suffix.lower() in (".safetensors", ".gguf", ".bin")]
                except (OSError, PermissionError):
                    continue
                if matches:
                    return self._pick_best_component_match(matches, hint)
        return None

    def _rpc_sync(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        if self._connection is None or self._process is None or not self._process.is_alive():
            raise RuntimeError("processo Phoenix Diffusion não está ativo")
        command = str(payload.get("command", "operação"))
        try:
            self._connection.send(payload)
            if not self._connection.poll(timeout):
                if not self._process.is_alive():
                    raise NativeWorkerExitedError(self._native_exit_message(command))
                raise TimeoutError(f"Phoenix Diffusion excedeu o limite de {timeout:.0f}s")
            response = self._connection.recv()
        except NativeWorkerExitedError:
            raise
        except (EOFError, BrokenPipeError, OSError) as exc:
            raise NativeWorkerExitedError(self._native_exit_message(command)) from exc
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "erro nativo desconhecido"))
        return response

    def _native_exit_message(self, command: str) -> str:
        process = self._process
        if process is None:
            return f"processo nativo encerrou durante '{command}'"
        try:
            # No Windows o pipe pode fechar alguns instantes antes de o SO
            # publicar o exitcode do subprocesso. Esperar um pouco evita o
            # diagnóstico inútil "código de saída indisponível" visto nos
            # testes físicos do Flux.
            process.join(timeout=2.0)
        except (AssertionError, OSError):
            pass
        code = process.exitcode
        if code is None:
            return f"processo nativo fechou o pipe durante '{command}' (código de saída indisponível)"
        unsigned = code & 0xFFFFFFFF
        known = {
            0xC0000005: "violação de acesso nativa",
            0xC0000017: "memória insuficiente",
            0xC0000409: "falha de segurança de pilha",
        }.get(unsigned, "falha nativa")
        return f"processo nativo encerrou durante '{command}': {known}, código {code} (0x{unsigned:08X})"

    async def _rpc(self, payload: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        return await asyncio.to_thread(self._rpc_sync, payload, timeout)

    async def start(self, _plan: ExecutionPlan | None = None) -> bool:
        self._start_error = ""
        if self._process is not None and self._process.is_alive():
            return True
        bridge = self._find_bridge()
        if bridge is None:
            self._start_error = (
                "Bridge Phoenix Diffusion ausente. Feche a Phoenix e execute "
                "Reparar_Phoenix_Diffusion.bat como administrador."
            )
            logger.error(self._start_error)
            return False
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(
            target=run_worker,
            args=(child, str(bridge)),
            name="phoenix-diffusion-native",
            daemon=True,
        )
        process.start()
        child.close()
        self._process = process
        self._connection = parent
        try:
            ready = await asyncio.to_thread(self._receive_ready, 30.0)
            self._bridge_info = ready
            return True
        except Exception as exc:
            self._start_error = f"Phoenix Diffusion não iniciou: {type(exc).__name__}: {exc}"
            await self.stop()
            logger.exception(self._start_error)
            return False

    def _receive_ready(self, timeout: float) -> dict[str, Any]:
        if self._connection is None or self._process is None:
            raise RuntimeError("processo não criado")
        if not self._connection.poll(timeout):
            raise TimeoutError("timeout carregando bridge Phoenix Diffusion")
        response = self._connection.recv()
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "bridge falhou ao iniciar"))
        return response

    async def stop(self) -> bool:
        process, connection = self._process, self._connection
        self._process = None
        self._connection = None
        self._loaded_signature = None
        if process is None:
            return True
        if process.is_alive() and connection is not None:
            try:
                await asyncio.to_thread(connection.send, {"command": "close"})
                await asyncio.to_thread(process.join, 5.0)
            except (BrokenPipeError, EOFError, OSError):
                pass
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, 5.0)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 2.0)
        if connection is not None:
            connection.close()
        return True

    async def status(self) -> RuntimeStatus:
        running = self._process is not None and self._process.is_alive()
        return RuntimeStatus(
            name=self.name,
            state=RuntimeState.RUNNING if running else RuntimeState.STOPPED,
            health="healthy" if running else "unavailable",
            metrics=self._bridge_info if running else {},
        )

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        started = datetime.now(_UTC)
        if not await self.start(plan):
            tried = ", ".join(str(path) for path in self._bridge_candidates())
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=(
                    self.startup_error
                    or (
                        "Bridge Phoenix Diffusion não encontrada. Feche esta janela e execute "
                        "Reparar_Phoenix_Diffusion.bat como administrador. "
                        f"Caminhos verificados: {tried}"
                    ),
                ),
            )

        model_path = self._find_model_file(plan.model or "flux")
        if model_path is None:
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=(f"Modelo de imagem '{plan.model or 'flux'}' não encontrado.",))
        profile = _select_profile(model_path.name)
        width = int(plan.parameters.get("width", profile["default_resolution"][0]))
        height = int(plan.parameters.get("height", profile["default_resolution"][1]))
        hazard = _check_known_failure(profile, model_path, width, height)
        if hazard:
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=(f"Combinação bloqueada por segurança: {hazard}",))

        component_map = {
            "--vae": "vae_path",
            "--clip_l": "clip_l_path",
            "--clip_g": "clip_g_path",
            "--t5xxl": "t5xxl_path",
            "--llm": "llm_path",
        }
        components: dict[str, str] = {}
        missing: list[str] = []
        for flag, hints in profile["components"]:
            path = self._find_component(hints)
            if path is None:
                missing.append(f"{flag} ({'/'.join(hints)})")
            else:
                components[component_map[flag]] = str(path)
        if missing:
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=(f"Componentes ausentes para {profile['name']}: {', '.join(missing)}",))

        candidates = _native_placement_candidates(profile, plan.parameters)
        generation = GenerationConfig(
            prompt=str(plan.parameters.get("prompt", "a majestic phoenix bird, cinematic lighting, 8k")),
            negative_prompt=str(plan.parameters.get("negative_prompt", "")),
            sampler=str(plan.parameters.get("sampler", "")),
            scheduler=str(plan.parameters.get("scheduler", "")),
            width=width,
            height=height,
            steps=int(plan.parameters.get("steps", profile.get("default_steps", 20))),
            cfg_scale=float(plan.parameters.get("cfg_scale", profile.get("cfg_scale") or 7.0)),
            seed=int(plan.parameters.get("seed", 42)),
            vae_tiling="--vae-tiling" in profile.get("extra_flags", []) or bool(plan.parameters.get("vae_tiling", False)),
        )
        native_crashes: list[str] = []
        try:
            for attempt, (placement_name, placement) in enumerate(candidates, start=1):
                if self._process is None or not self._process.is_alive():
                    if not await self.start(plan):
                        raise RuntimeError(
                            self.startup_error or "não foi possível iniciar um worker limpo"
                        )

                load = ModelConfig(
                    model_path=None if profile["diffusion_flag"] else str(model_path),
                    diffusion_model_path=str(model_path) if profile["diffusion_flag"] else None,
                    backend=placement["backend"],
                    params_backend=placement["params_backend"],
                    max_vram=placement["max_vram"],
                    split_mode=placement["split_mode"],
                    auto_fit=placement["auto_fit"],
                    stream_layers=placement["stream_layers"],
                    enable_mmap=placement["enable_mmap"],
                    diffusion_flash_attn=bool(
                        plan.parameters.get(
                            "diffusion_flash_attn",
                            profile.get("diffusion_flash_attn", False),
                        )
                    ),
                    vae_format=int(profile.get("vae_format", -1)),
                    **components,
                )
                signature = tuple(sorted(asdict(load).items()))
                try:
                    if signature != self._loaded_signature:
                        if self._loaded_signature is not None:
                            logger.info(
                                "Phoenix Diffusion: modelo/configuração mudou; encerrando o worker anterior "
                                "para liberar integralmente contexto, DLL e estado Vulkan."
                            )
                            await self.stop()
                            if not await self.start(plan):
                                raise RuntimeError(
                                    self.startup_error or "não foi possível iniciar um worker limpo"
                                )
                        logger.info(
                            "Phoenix Diffusion: tentativa %d/%d [%s], perfil=%s, backend=%s, "
                            "params_backend=%s, auto_fit=%s, max_vram=%s, "
                            "stream_layers=%s, mmap=%s",
                            attempt, len(candidates), placement_name, profile["name"],
                            load.backend, load.params_backend, load.auto_fit,
                            load.max_vram, load.stream_layers, load.enable_mmap,
                        )
                        await self._rpc(
                            {"command": "load", "config": asdict(load)}, timeout=900.0
                        )
                        self._loaded_signature = signature

                    output_dir = self._project_root / "output" / "images"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_file = output_dir / (
                        f"phoenix_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
                    )
                    response = await self._rpc(
                        {
                            "command": "generate",
                            "config": asdict(generation),
                            "output_file": str(output_file),
                        },
                        timeout=float(plan.parameters.get("timeout", 2700)),
                    )
                    if (
                        not output_file.is_file()
                        or output_file.stat().st_size < _MIN_VALID_IMAGE_BYTES
                    ):
                        raise RuntimeError(
                            "bridge retornou sucesso, mas o PNG está ausente ou truncado"
                        )
                    return ExecutionResult(
                        plan_id=plan.id,
                        status=ExecutionStatus.SUCCESS,
                        output=(
                            f"Imagem salva em: {output_file} "
                            f"(Phoenix Diffusion/{profile['name']}, placement={placement_name})"
                        ),
                        metrics={
                            "output_file": str(output_file),
                            "profile": profile["name"],
                            "placement": placement_name,
                            "placement_attempt": attempt,
                            **response,
                        },
                        started_at=started,
                        finished_at=datetime.now(_UTC),
                    )
                except NativeWorkerExitedError as exc:
                    detail = str(exc).strip() or "processo nativo encerrou sem diagnóstico"
                    native_crashes.append(f"{placement_name}: {detail}")
                    await self.stop()
                    if attempt < len(candidates):
                        logger.warning(
                            "Phoenix Diffusion: crash nativo no placement '%s'; "
                            "tentando fallback %d/%d.",
                            placement_name, attempt + 1, len(candidates),
                        )
                        continue
                    raise RuntimeError(
                        f"todos os placements de {profile['name']} falharam por crash nativo: "
                        + " | ".join(native_crashes)
                    ) from exc

            raise RuntimeError("nenhum placement Phoenix Diffusion disponível")
        except Exception as exc:
            logger.exception("Phoenix Diffusion falhou")
            if isinstance(exc, (NativeWorkerExitedError, EOFError, BrokenPipeError, TimeoutError)):
                await self.stop()
            detail = str(exc).strip() or f"{type(exc).__name__} sem mensagem"
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=(f"Phoenix Diffusion: {detail}",), started_at=started, finished_at=datetime.now(_UTC))
