#\phoenix_kernel\runtime\engine.py

from __future__ import annotations
import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any

from core.contracts.engine import IEngine
from core.contracts.runtime import IRuntimeSDK
from core.domain.engine import EngineDescriptor, HealthStatus, Capability
from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeDescriptor, RuntimeStatus, RuntimeState
from core.events.bus import EventBus
from core.events.base import Event
from core.kernel.kernel import PlatformKernel
from phoenix_kernel.paths import PhoenixPaths

# Importando os drivers da pasta local 'drivers'
from .drivers.llama_cpp import LlamaCppDriver
from .drivers.phoenix_diffusion import PhoenixDiffusionDriver
from .drivers.mtmd_driver import MtmdDriver  # Visao nativa (setup_vision.py)
from .drivers.whisper import WhisperDriver
from .drivers.comfyui import ComfyUIDriver
# PHX-REVERT (destravar Ollama como 2ª opção de engine de texto, a pedido
# explícito): o comentário aqui dizia "OllamaDriver removido
# definitivamente", mas o arquivo `drivers/ollama.py` nunca foi apagado -
# só parou de ser importado e registrado. Religado agora como driver
# OPCIONAL (nunca é o default de nenhuma role no catalog/models.json,
# resolve() só devolve o alias 'ollama' quando o usuário troca a
# preferência de engine de texto explicitamente - ver
# ResidentManager.set_text_engine_preference()). O llama.cpp continua
# sendo o motor de texto padrão da Phoenix; Ollama é só uma segunda
# opção mais lenta (roda via Docker, porta 11434) pra quando a
# compilação Vulkan do llama.cpp falhar na máquina do usuário, ou por
# preferência pessoal.
from .drivers.ollama import OllamaDriver

logger = logging.getLogger(__name__)

# Type hint genérico para evitar dependência de arquivos que possam ter ficado para trás
RuntimeDriver = Any

# PHX-NEW: mapa runtime -> categoria de tarefa, usado só pra rotular o
# evento "runtime.execution_completed" (telemetria de desempenho, ver
# cloud_sync.push_model_run). Não afeta em nada a execução em si.
_RUNTIME_TASK_CATEGORY = {
    "llama.cpp": "chat",
    "ollama": "chat",
    "sdxl": "image",
    "vision": "vision",
    "whisper": "transcription",
}


async def _call_driver_start(driver: RuntimeDriver, plan: ExecutionPlan | None) -> bool:
    """PHX-FIX: chama driver.start() passando `plan` SOMENTE se a assinatura aceitar."""
    sig = inspect.signature(driver.start)
    if len(sig.parameters) >= 1:
        return await driver.start(plan)
    return await driver.start()


class RuntimeEngine(IEngine, IRuntimeSDK):
    def __init__(self, event_bus: EventBus, kernel: PlatformKernel) -> None:
        self._event_bus = event_bus
        self._kernel = kernel
        self._drivers: dict[str, RuntimeDriver] = {}
        self._active_runtimes: set[str] = set()
        self._watchdog_task: asyncio.Task | None = None
        self._exclusive_execution_lock = asyncio.Lock()
        # PHX-FIX (auditoria 2026-08-21, reconciliação com transcrições
        # paralelas): _watchdog_loop() reiniciava um driver derrubado
        # chamando _call_driver_start(driver, None) - ou seja, sem plano.
        # Pra drivers com processo persistente e modelo carregado em
        # memória (llama.cpp é o caso real: LlamaCppDriver.start() usa
        # `plan.model if plan and plan.model else "qwen3:8b"`), isso troca
        # SILENCIOSAMENTE o modelo ativo pro default do catalog/models.json
        # sempre que o llama-server cai e o watchdog o reergue - mesmo que
        # o usuário tivesse carregado outro modelo (ex: qwen2.5-coder:32b)
        # de propósito minutos antes. Nada loga isso como troca de modelo;
        # a próxima resposta do chat simplesmente vem de um modelo
        # diferente do que o usuário escolheu, sem aviso. Corrigido
        # guardando o último ExecutionPlan usado com sucesso por runtime e
        # reaproveitando-o no restart do watchdog.
        self._last_plan: dict[str, ExecutionPlan] = {}
        
        self._descriptor = EngineDescriptor(
            id="runtime", name="Phoenix Runtime Engine", version="4.5.0", sdk_version="1.0.0",
            capabilities=(Capability(name="execution", version="1.0"),)
        )

    @property
    def descriptor(self) -> EngineDescriptor: return self._descriptor

    async def initialize(self) -> None:
        # PHX-FIX (auditoria 2026-08-04): kernel.resolve("storage") e
        # kernel.resolve("config") SEMPRE retornavam None - register_engine()
        # (o unico jeito de popular o que resolve() devolve) nunca e chamado
        # em lugar nenhum de phoenix_kernel/kernel.py. Isso significa que
        # ws_path sempre virava Path(".") (o diretorio de trabalho atual do
        # processo no momento em que api_server.py foi iniciado), ignorando
        # por completo o disco NVMe/SSD/HDD com >=40GB livres que o
        # install/storage_scanner.ps1 detecta e grava em storage.json. Se o
        # processo for iniciado de dentro de um caminho tipo "Z:\...", TODOS
        # os drivers (sdxl/whisper/piper) acabavam gravando/procurando
        # arquivos ali, mesmo que o disco certo (mais rapido, com espaço)
        # fosse outro. PhoenixPaths.get_workspace() lê o mesmo storage.json
        # de verdade - é a mesma fonte que get_category_path() já usa nos
        # endpoints de visão/TTS - e nunca hardcoda letra de unidade.
        config_eng = self._kernel.resolve("config") if hasattr(self._kernel, 'resolve') else None
        ws_path = PhoenixPaths.get_workspace()
        all_cfg = config_eng.get_all() if config_eng else {}
        
        # Backend Oficial LLM (CPU)
        self._drivers["llama.cpp"] = LlamaCppDriver()

        # CORREÇÃO: antes os drivers opcionais estavam num único try -
        # se qualquer um falhasse ao instanciar, os que viriam depois dele
        # na mesma lista nunca chegavam a ser registrados (mesmo que
        # funcionassem perfeitamente sozinhos). Agora cada um é isolado -
        # uma falha em "sdxl" não impede "whisper"/"comfyui".
        #
        # PHX-FIX (achado real do usuário 2026-08-24, "se piper nao
        # funciona e kokoro é melhor, jogar fora o piper de vez"): o
        # PiperDriver (drivers/piper.py) já estava morto de verdade desde
        # 2026-08-23 (generate_speech_direct() e generate_audiobook_direct()
        # em resident_manager.py chamam o motor Kokoro DIRETO, nunca
        # `self.runtime.execute(runtime="piper")`) - continuava só
        # registrado aqui "pra quem quiser reativar no futuro". Removido de
        # vez a pedido do usuário: arquivo apagado, import e registro
        # tirados daqui, entrada órfã tirada de catalog/models.json (nada
        # no código chama registry.resolve("speech_synthesis") - conferido
        # antes de remover) e o download do binário/vozes tirado de
        # install/common.ps1.
        optional_drivers = [
            # O alias público "sdxl" é preservado por compatibilidade com
            # planos antigos; a implementação agora é Phoenix Diffusion.
            ("sdxl", lambda: PhoenixDiffusionDriver(all_cfg, ws_path)),
            ("whisper", lambda: WhisperDriver(all_cfg, ws_path)),
            ("comfyui", lambda: ComfyUIDriver(all_cfg)),
            # PHX-FIX: MtmdDriver era importado (setup_vision.py) mas nunca
            # registrado em self._drivers — o import sozinho não expõe a
            # capacidade de visão pro RuntimeEngine.execute(plan.runtime="vision").
            ("vision", lambda: MtmdDriver()),
            # PHX-REVERT (destravar Ollama como 2ª opção): registrado como
            # opcional igual os outros - se o Docker/Ollama não estiver
            # instalado nesta máquina, a instanciação aqui não falha (o
            # driver só faz chamada de rede dentro de execute()/status(),
            # nunca no construtor), então isso nunca derruba o boot da
            # Phoenix.
            ("ollama", lambda: OllamaDriver()),
        ]
        for driver_name, factory in optional_drivers:
            try:
                self._drivers[driver_name] = factory()
            except Exception as e:
                logger.error(f"RuntimeEngine: Falha ao carregar driver opcional '{driver_name}': {e}", exc_info=True)
        
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def shutdown(self) -> None:
        if self._watchdog_task: self._watchdog_task.cancel()
        for runtime in list(self._active_runtimes): await self.stop(runtime)

    async def health(self) -> HealthStatus: return HealthStatus.HEALTHY

    async def list_runtimes(self) -> tuple[RuntimeDescriptor, ...]:
        descs = []
        for name in self._active_runtimes: descs.append(RuntimeDescriptor(name=name))
        return tuple(descs)

    def get_last_plan(self, runtime: str) -> ExecutionPlan | None:
        """PHX-NEW (colaboração de dois modelos com modelos DIFERENTES por
        lado): expõe publicamente o último ExecutionPlan que realmente ligou
        um runtime com sucesso (o mesmo estado interno que o watchdog já usa
        pra restaurar o modelo certo depois de uma queda - ver
        _watchdog_loop). resident_manager.py usa isso pra lembrar qual
        modelo o motor de texto compartilhado (porta 8081) tinha ANTES de
        emprestá-lo pro lado CPU da colaboração, e restaurar esse mesmo
        modelo no final - sem isso, o chat normal ficaria "preso" no modelo
        da colaboração depois dela terminar."""
        return self._last_plan.get(runtime)

    async def stop_all(self, except_runtime: str | None = None) -> None:
        """Encerra todos os runtimes gerenciados antes de trocar a carga da GPU."""
        for active in list(self._active_runtimes):
            if except_runtime and active == except_runtime:
                continue
            try:
                logger.info("RuntimeEngine lifecycle: encerrando '%s' antes da próxima carga.", active)
                await self.stop(active)
            except Exception as exc:
                logger.warning("RuntimeEngine lifecycle: falha ao encerrar '%s': %s", active, exc)

    async def prepare_exclusive(self, target_runtime: str, settle_seconds: float = 1.0) -> None:
        """Encerra TODOS os runtimes antes de uma carga pesada exclusiva."""
        await self.stop_all()
        if settle_seconds > 0:
            await asyncio.sleep(settle_seconds)

    async def start(self, runtime: str, plan: ExecutionPlan | None = None) -> bool:
        driver = self._drivers.get(runtime)
        if not driver: return False
        await self.stop_all(except_runtime=runtime)
        success = await _call_driver_start(driver, plan)
        if success:
            self._active_runtimes.add(runtime)
            # PHX-FIX: guarda o plano que efetivamente ligou este runtime,
            # pro watchdog conseguir restaurá-lo em vez de cair no default.
            if plan is not None:
                self._last_plan[runtime] = plan
            if self._event_bus:
                await self._event_bus.publish(Event(event_type="runtime.started", source="runtime", payload={"runtime": runtime}))
        return success

    async def stop(self, runtime: str) -> bool:
        driver = self._drivers.get(runtime)
        if not driver: return False
        success = await driver.stop()
        if success:
            self._active_runtimes.discard(runtime)
            if self._event_bus:
                await self._event_bus.publish(Event(event_type="runtime.stopped", source="runtime", payload={"runtime": runtime}))
        return success

    async def status(self, runtime: str) -> RuntimeStatus:
        driver = self._drivers.get(runtime)
        if not driver: return RuntimeStatus(name=runtime, state=RuntimeState.ERROR)
        return await driver.status()

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        async with self._exclusive_execution_lock:
            return await self._execute_exclusive(plan)

    async def _execute_exclusive(self, plan: ExecutionPlan) -> ExecutionResult:
        driver = self._drivers.get(plan.runtime)
        if not driver:
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=[f"Runtime '{plan.runtime}' not found"])

        await self.stop_all(except_runtime=plan.runtime)

        if plan.runtime not in self._active_runtimes:
            # PHX-FIX: passa o plan adiante para o driver saber qual modelo carregar
            started = await self.start(plan.runtime, plan)
            if not started:
                detail = str(getattr(driver, "startup_error", "") or "").strip()
                error = detail or f"Failed to start runtime '{plan.runtime}'"
                logger.warning("RuntimeEngine: Failed to start '%s': %s", plan.runtime, error)
                # PHX-FIX: Retorna falha imediata. Não fazer fallback silencioso para Ollama.
                return ExecutionResult(
                    plan_id=plan.id, 
                    status=ExecutionStatus.FAILED, 
                    errors=[error]
                )
        
        result = await driver.execute(plan)
        if result.status != ExecutionStatus.SUCCESS:
            logger.warning(f"RuntimeEngine: Execution failed on '{plan.runtime}'. Errors: {result.errors}")

        # PHX-NEW: publica o resultado da execução como evento - quem
        # quiser consumir isso (ex: PhoenixKernel enviando telemetria de
        # desempenho pro Firestore via cloud_sync.push_model_run) escuta
        # "runtime.execution_completed" sem o RuntimeEngine precisar
        # conhecer cloud_sync/Firestore/etc. Mesmo padrão já usado em
        # "runtime.started"/"runtime.stopped" - só mais um tipo de evento,
        # não uma dependência nova. O payload só carrega metadado
        # estrutural (result.metrics, que hoje só tem tokens/duração) -
        # NUNCA plan.parameters (que é onde o prompt do usuário mora).
        if self._event_bus:
            await self._event_bus.publish(Event(
                event_type="runtime.execution_completed",
                source="runtime",
                payload={
                    "runtime": plan.runtime,
                    "model": plan.model,
                    "task_category": _RUNTIME_TASK_CATEGORY.get(plan.runtime, "other"),
                    "success": result.status == ExecutionStatus.SUCCESS,
                    "metrics": dict(result.metrics or {}),
                },
            ))

        # PHX-FIX: Removido o bloco de FALLBACK LOGIC para Ollama.
        # Se o motor nativo falhar, a falha deve ser explícita.
        return result

    async def pull_model(self, runtime: str, model_name: str) -> bool:
        driver = self._drivers.get(runtime)
        if not driver or not hasattr(driver, "pull_model"): return False
        if runtime not in self._active_runtimes: await self.start(runtime)
        return await driver.pull_model(model_name)

    async def embed(self, runtime: str, model: str, text: str) -> list[float]:
        driver = self._drivers.get(runtime)
        if not driver or not hasattr(driver, "embed"): return []
        if runtime not in self._active_runtimes: await self.start(runtime)
        return await driver.embed(model, text)

    async def describe_image(self, runtime: str, model: str, prompt: str, image_path: str) -> str:
        driver = self._drivers.get(runtime)
        if not driver or not hasattr(driver, "describe_image"): return "Error: Runtime does not support image description."
        if runtime not in self._active_runtimes: await self.start(runtime)
        return await driver.describe_image(model, prompt, image_path)

    async def _watchdog_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(30)
                for runtime_name in list(self._active_runtimes):
                    driver = self._drivers.get(runtime_name)
                    if not driver: continue
                    status = await driver.status()
                    if status.state != RuntimeState.RUNNING:
                        await driver.stop()
                        # PHX-FIX: restaura o último plano (modelo/config)
                        # que realmente ligou este runtime, em vez de
                        # reiniciar "no escuro" com plan=None - o que fazia
                        # o llama.cpp recarregar o default do catálogo e
                        # trocar de modelo sem avisar ninguém.
                        last_plan = self._last_plan.get(runtime_name)
                        success = await _call_driver_start(driver, last_plan)
                        if success:
                            logger.info(
                                "RuntimeEngine.watchdog: '%s' caiu e foi "
                                "reerguido%s.",
                                runtime_name,
                                f" com o modelo '{last_plan.model}'" if last_plan and last_plan.model else "",
                            )
                        if not success: self._active_runtimes.discard(runtime_name)
            except asyncio.CancelledError:
                break
