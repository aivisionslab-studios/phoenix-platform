import asyncio
import importlib
import json
import logging
from pathlib import Path
from core.events.base import Event
from core.events.bus import EventBus
from core.kernel.kernel import PlatformKernel
from core.domain.machine import MachineContext
from phoenix_kernel.state import StateEngine
from phoenix_kernel.cloud_sync import has_consent, FirestoreSync, get_or_create_machine_id
from phoenix_kernel.paths import KNOWLEDGE_BASE_JSON
from phoenix_kernel.services.ocr_engine import OCREngine
from phoenix_kernel.orchestration.execution_arbiter import default_execution_arbiter
from phoenix_kernel.ahde.facade import AHDE
import setup_platform

logger = logging.getLogger(__name__)

CLOUD_SYNC_INTERVAL_SEC = 60
# PHX-NEW (integração AHDE, Fase 2): intervalo do polling de telemetria
# que alimenta o AHDE.ingest_telemetry(). Não precisa ser fino (a
# ChangeDetectionEngine embutida no TelemetryBridge já filtra ruído por
# threshold - só publica evento quando algo mudou de verdade), então 5s
# é suficiente sem gerar carga desnecessária.
AHDE_TELEMETRY_INTERVAL_SEC = 5


def _pool_entry_to_knowledge_card(entry: dict) -> dict:
    """
    PHX-NEW: traduz um documento do shared_knowledge_pool (schema:
    content/category/hardware_fingerprint/phoenix_version/capivara) pro
    formato que data/knowledge_base.json já usa hoje (id/content/layer/
    title/tags, mesmo shape que ChromaRagBackend.upsert() espera via
    MemoryCard). Os dois schemas são propositalmente diferentes - o do
    pool é sobre PROVENIÊNCIA (de onde veio, quantas máquinas confirmaram),
    o local é sobre COMO o RAG indexa - então precisa de tradução, não é
    o mesmo dict reaproveitado.
    """
    return {
        "id": f"pool_{entry.get('id', '')}",
        "content": entry.get("content", ""),
        "layer": "rag",
        "title": f"[{entry.get('category', 'unknown')}] achado compartilhado",
        "tags": [entry.get("category", "unknown"), "shared_pool"],
    }


class PhoenixKernel:
    """
    PHOENIX KERNEL 3.0
    Orquestrador central e Composition Root.
    Responsável por instanciar e injetar todas as dependências seguindo a arquitetura oficial.
    """
    def __init__(self):
        self.event_bus = EventBus()
        self.platform_kernel = PlatformKernel()
        
        # --- 1. INFRAESTRUTURA E DESCOBERTA ---
        discovery_module = importlib.import_module("phoenix_kernel.discovery.engine")
        self.discovery = discovery_module.DiscoveryEngine()

        budget_module = importlib.import_module("phoenix_kernel.budget.engine")
        self.budget = budget_module.BudgetEngine()

        telemetry_module = importlib.import_module("phoenix_kernel.telemetry.engine")
        self.telemetry = telemetry_module.TelemetryEngine()

        # --- 2. SERVIÇOS E MODELOS ---
        services_module = importlib.import_module("phoenix_kernel.services.engine")
        self.services = services_module.ServicesEngine()

        # Legado/Compatibilidade (NÃO É O BACKEND PRINCIPAL)
        self.platform_process = importlib.import_module("phoenix_kernel.services.platform_process")
        self.lmstudio_service = importlib.import_module("phoenix_kernel.services.lmstudio_service")

        # PHX-FIX: Motor de OCR nativo para ler imagens coladas no chat ou anexadas
        self.ocr_engine = OCREngine()

        # PHX-FIX: ModelsEngine injetado ANTES do StateEngine e PlannerEngine 
        # para resolver o AttributeError e permitir o set_knowledge_engine.
        models_module = importlib.import_module("phoenix_kernel.models.engine")
        self.models = models_module.ModelsEngine()

        # --- 3. ESTADO E PLANEJAMENTO ---
        # Agora self.models existe e pode ser passado com segurança para o StateEngine
        self.state = StateEngine(self.budget, self.telemetry, self.services, self.models)
        
        planner_module = importlib.import_module("phoenix_kernel.planner.engine")
        self.planner = planner_module.PlannerEngine(self.event_bus, self.platform_kernel)
        self.models.set_knowledge_engine(self.planner.knowledge)

        # --- 4. RUNTIME ENGINE (ÚNICO RESPONSÁVEL POR EXECUÇÃO) ---
        runtime_module = importlib.import_module("phoenix_kernel.runtime.engine")
        self.runtime = runtime_module.RuntimeEngine(self.event_bus, self.platform_kernel)

        # --- 5. SEGURANÇA, LOGS E VALIDAÇÃO ---
        validation_module = importlib.import_module("phoenix_kernel.validation.engine")
        self.validation = validation_module.ValidationEngine()

        logs_module = importlib.import_module("phoenix_kernel.logs.engine")
        self.logs = logs_module.LogsEngine()
        # PHX-FIX: injeta logs no state DEPOIS de self.logs ser criado
        # (estava na linha 88, antes do self.logs existir — causava AttributeError)
        self.state.set_logs(self.logs)

        security_module = importlib.import_module("phoenix_kernel.security.engine")
        self.security = security_module.SecurityEngine()

        # --- 6. EXECUTION ARBITER + RESIDENT MANAGER ---
        # Autoridade ÚNICA para claim de intenção, executor, grounding e CPU/GPU.
        # Os componentes antigos só executam o plano ou recebem NOT_CLAIMED.
        self.execution_arbiter = default_execution_arbiter
        resident_module = importlib.import_module("phoenix_kernel.resident.resident_manager")
        self.resident = resident_module.ResidentManager(
            state_engine=self.state, 
            planner_engine=self.planner, 
            services_engine=self.services, 
            logs_engine=self.logs, 
            runtime_engine=self.runtime
            # PHX-FIX: Removida a injeção do model_manager pois o ResidentManager já o instancia internamente.
        )
        self.resident.execution_arbiter = self.execution_arbiter

        # --- 7. API ENGINE ---
        api_module = importlib.import_module("phoenix_kernel.api.engine")
        self.api = api_module.ApiEngine(
            self.state, self.models, self.planner, self.runtime, 
            self.services, self.logs, self.validation, self.security, self.resident,
            self.ocr_engine
        )
        
        self.machine_context = None
        self._cloud_sync_task = None

        # --- 8. CLOUD SYNC ---
        self.cloud_sync = None
        try:
            self.cloud_sync = FirestoreSync()
        except Exception:
            logger.warning("Biblioteca google-cloud-firestore não instalada ou credenciais ausentes. Sincronização na nuvem desativada.")

        # --- 9. AHDE (Adaptive Hardware Discovery Engine) ---
        # PHX-NEW (integração AHDE, Fase 2): o facade (phoenix_kernel/ahde/
        # facade.py) já existia pronto desde a Fase 0, mas nenhum arquivo
        # fora da pasta ahde/ o importava - ficou construído e nunca
        # ligado. Esta é a primeira vez que o kernel real instancia o
        # AHDE. Reusa o mesmo machine_id do FirestoreSync (get_or_create_
        # machine_id já grava/lê o mesmo arquivo local), então os dois
        # sistemas identificam a mesma máquina com o mesmo ID.
        # repository=None de propósito nesta fase: persistência entre
        # reinícios é trabalho futuro (Fase 2 do facade não exige isso,
        # só ingestão + eventos em memória); o facade já mantém os
        # snapshots mais recentes em memória via get_latest_*_snapshot().
        self.ahde = AHDE(machine_id=get_or_create_machine_id())
        self._ahde_telemetry_task = None
        self.state.set_ahde(self.ahde)
        # PHX-NEW (Fase 3 - Hot-Swap): mesmo padrão do state.set_ahde()
        # acima - o ResidentManager também precisa consultar VRAM livre
        # antes de subir um modelo pesado (ver _vram_guard() em
        # resident_manager.py). Não dá pra injetar no construtor porque o
        # AHDE só existe a partir daqui, depois do ResidentManager já ter
        # sido criado.
        self.resident.set_ahde(self.ahde)

        # PHX-NEW: escuta "runtime.execution_completed" (publicado pelo
        # RuntimeEngine.execute() - mesmo EventBus, self.event_bus passado
        # no construtor dele lá em cima) e repassa como telemetria de
        # desempenho pro Firestore. RuntimeEngine nunca precisa saber que
        # cloud_sync existe - só publica o evento, quem consome é aqui.
        self.event_bus.subscribe("runtime.execution_completed", self._on_runtime_execution_completed)

    async def boot(self):
        print("[Kernel] Inicializando Discovery (Serviço 01)...")
        hw_data = await self.discovery.discover_hardware()
        
        class Profile: pass
        profile = Profile()
        profile.cpu = hw_data['cpu']
        profile.memory = hw_data['memory']
        profile.gpus = hw_data['gpus']
        profile.available_backends = hw_data['available_backends']
        
        self.machine_context = MachineContext(profile=profile)
        
        self.state.set_context(self.machine_context, hw_data)
        self.api.set_context(self.machine_context)
        
        self.logs.add_event("INFO", "Kernel", "Boot sequence initiated.")

        # PHX-NEW (integração AHDE, Fase 2): primeira ingestão de hardware
        # - roda uma vez no boot, com os mesmos dados que acabaram de
        # alimentar state.set_context() (mesma fonte, sem nova varredura).
        # Falha aqui NUNCA pode derrubar o boot - AHDE é observador, não
        # dependência crítica do sistema, então qualquer erro só vira log.
        try:
            ahde_hw_payload = await self._build_ahde_hardware_payload(hw_data)
            await self.ahde.ingest_hardware(ahde_hw_payload)
            self.logs.add_event("INFO", "AHDE", "Snapshot de hardware inicial capturado.")
        except Exception as e:
            logger.error(f"Kernel: AHDE.ingest_hardware() falhou no boot - {e}")
            self.logs.add_event("WARNING", "AHDE", f"Falha ao capturar snapshot inicial de hardware: {e}")
        
        print("[Kernel] Inicializando Planner e RAG (Serviço 03)...")
        await self.planner.initialize()
        self.planner.set_context(self.machine_context)
        
        print("[Kernel] Inicializando Runtime (Serviço 04)...")
        await self.runtime.initialize()
        self.logs.add_event("INFO", "Kernel", "Phoenix Kernel Pronto.")

        # PHX-FIX (corrigido): antes disparava o download do .gguf em
        # background e IMEDIATAMENTE tentava subir o llama.cpp na sequência
        # - o servidor sempre falhava na primeira instalação, porque o
        # arquivo ainda não existia (Path.exists() só confirma que o
        # download terminou, não que ele foi disparado). Agora:
        # - se o modelo já está pronto e íntegro -> sobe o motor na hora.
        # - se não está -> sobe em background só DEPOIS que o download
        #   validar como completo, sem travar o boot da API nesse meio tempo.
        from core.domain.execution import ExecutionPlan as BootPlan
        boot_plan = BootPlan(runtime="llama.cpp", model="qwen3:8b", parameters={}, reasoning="Bootstrap")

        model_ready = await self._ensure_default_model()

        if model_ready:
            print("[Kernel] Subindo Servidor LLM Nativo (llama.cpp) na porta 8081 [CPU Policy]...")
            await self._start_llm_engine(boot_plan)
        else:
            print("[Kernel] Modelo padrão ainda baixando - Servidor LLM (llama.cpp) vai subir sozinho quando o download terminar.")
            self.logs.add_event("INFO", "Kernel", "Aguardando download do modelo padrão para subir o Servidor LLM.")
            asyncio.create_task(self._start_llm_engine_when_ready(boot_plan))

        # PHX-NEW (auditoria 2026-08-20, "Whisper model provisioning"):
        # achado real em máquina de produção - whisper.cpp compilava
        # corretamente (common.ps1 clona e builda) e /api/transcribe
        # existia, mas NENHUM lugar do provisionamento baixava o modelo STT
        # (ggml-base.bin). Resultado: toda transcrição falhava com "Nenhum
        # modelo Whisper encontrado em <workspace>/Models/Audio/" até o
        # usuário baixar manualmente na mão. Mesmo padrão não-bloqueante de
        # _ensure_default_model() acima (LLM padrão) - dispara em background,
        # nunca trava o boot da API esperando ~150MB baixarem.
        await self._ensure_default_stt_model()

        # PHX-NEW (2026-08-22, pedido do usuário: "verifica se faltam
        # [modelos] pra rodar e se faltar baixa novamente pra evitar
        # erros e assim sempre garantimos sucessos"): mesmo padrão não-
        # bloqueante de _ensure_default_model()/_ensure_default_stt_model()
        # acima, agora também pro modelo de imagem PADRÃO (Flux). Antes
        # desta chamada, NENHUM lugar verificava isso no boot - só se
        # descobria que faltava na hora de gerar a primeira imagem pelo
        # chat, que documentadamente nunca baixa modelo sozinho (só uma
        # missão aprovada faz isso - ver ResidentManager.
        # generate_image_direct()). Numa instalação nova, isso significava
        # a primeira geração de imagem sempre falhando com "nenhum modelo
        # de imagem instalado", sem aviso nenhum antes disso.
        await self._ensure_default_image_model()

        print("[Kernel] Preparando Phoenix Aviary Platform (porta 3000)...")
        ok, msg = setup_platform.build_platform()
        self.logs.add_event("INFO" if ok else "ERROR", "PlatformProcess", msg)
        if ok:
            self.platform_process.start_supervised(self.logs)
        else:
            self.logs.add_event("WARNING", "PlatformProcess", "Platform não disponível na porta 3000 até o problema acima ser resolvido.")

        print("[Kernel] Verificando LM Studio (porta 1234) - Legado...")
        lm_ok, lm_msg = await self.lmstudio_service.try_start_server(self.logs)
        self.logs.add_event("INFO" if lm_ok else "WARNING", "LMStudioService", lm_msg)

        if self.cloud_sync is not None:
            print(f"[Kernel] Iniciando loop de sincronização com o Firestore (a cada {CLOUD_SYNC_INTERVAL_SEC}s, só se consentido)...")
            self._cloud_sync_task = asyncio.create_task(self._cloud_sync_loop())

        # PHX-NEW (integração AHDE, Fase 2): loop de telemetria - só
        # começa depois que o snapshot inicial de hardware acima já foi
        # capturado (senão o primeiro TelemetryBridge.detect_changes()
        # não teria baseline pra comparar). Independente do cloud_sync
        # estar configurado ou não - AHDE é local, não depende de nuvem.
        print(f"[Kernel] Iniciando loop de telemetria do AHDE (a cada {AHDE_TELEMETRY_INTERVAL_SEC}s)...")
        self._ahde_telemetry_task = asyncio.create_task(self._ahde_telemetry_loop())

    async def _build_ahde_hardware_payload(self, hw_data: dict) -> dict:
        """
        PHX-NEW (integração AHDE, Fase 2): traduz o shape que
        discovery.discover_hardware() já produz (flat: os/cpu/memory/gpus/
        storage/motherboard/available_backends) pro shape que
        AHDE.ingest_hardware() espera (contracts.HardwareSnapshot):
        {"hardware": {...}, "drivers": {...}, "services": {...},
        "models": [...], "available_backends": [...]}. Isso é adaptação
        de formato, não nova coleta - não faz nenhuma varredura extra de
        hardware.

        NOTA sobre CapabilityEngine.extract() (phoenix_kernel/ahde/
        analytics.py): ele lê "wsl" e "virtualization" de services, mas
        get_environment_status() (services/engine.py) não rastreia esses
        dois hoje - fica False, documentado aqui em vez de inventado.
        Também traduz a chave "llama_cpp" (com underscore, como
        get_environment_status() devolve) pra "llamacpp" (sem underscore,
        como CapabilityEngine.extract() já esperava desde a Fase 0) -
        sem essa tradução, o campo nunca batia e llamacpp sempre dava
        falso mesmo com o binário presente.
        """
        env = await self.services.get_environment_status()
        models_status = await self.models.get_model_and_rag_status()

        services_for_capabilities = {
            **env,
            "llamacpp": env.get("llama_cpp", False),
            "wsl": False,  # PHX-NOTE: não rastreado por get_environment_status() hoje
            "virtualization": False,  # PHX-NOTE: idem
        }

        return {
            "hardware": hw_data,
            "drivers": {},  # PHX-NOTE: nenhum produtor rastreia drivers separadamente hoje
            "services": services_for_capabilities,
            "models": models_status.get("models", []),
            "available_backends": hw_data.get("available_backends", []),
        }

    async def _ahde_telemetry_loop(self):
        """
        PHX-NEW (integração AHDE, Fase 2): a cada tick, pega a telemetria
        já coletada por TelemetryEngine.get_live_metrics() (mesma fonte
        que /api/state usa, sem sensor extra) e entrega pro
        AHDE.ingest_telemetry(). O próprio facade filtra ruído via
        TelemetryBridge antes de tocar no SnapshotEngine - se nada mudou
        além do limiar, ingest_telemetry() retorna None e não publica
        evento nenhum, então não tem problema chamar isso com frequência.
        """
        while True:
            try:
                await asyncio.sleep(AHDE_TELEMETRY_INTERVAL_SEC)
                live_metrics = await self.telemetry.get_live_metrics()
                await self.ahde.ingest_telemetry(self._map_telemetry_for_ahde(live_metrics))
            except asyncio.CancelledError:
                break
            except Exception as e:
                # PHX-NOTE: nunca deixa uma falha de telemetria (sensor
                # indisponível, etc.) derrubar o loop inteiro - só pula
                # esse tick e loga.
                logger.debug(f"Kernel: AHDE.ingest_telemetry() falhou nesse tick - {e}")

    @staticmethod
    def _map_telemetry_for_ahde(live_metrics: dict) -> dict:
        """
        PHX-FIX (integração AHDE, Fase 2 - achado durante teste manual):
        TelemetryEngine.get_live_metrics() (phoenix_kernel/telemetry/
        engine.py) devolve {cpu_usage, gpu_temp, gpu_load, gpu_vram_used,
        ram_used_mb, ram_total_mb}. Mas hardware_engine.telemetry.
        change_detection.ChangeDetectionEngine.detect() - que o
        TelemetryBridge usa por baixo pra decidir se algo mudou de
        verdade - procura chaves diferentes: gpu_temperature_celsius,
        vram_used_mb, cpu_temperature_celsius, etc. (ver
        _EVENT_NAME_MAP em change_detection.py).

        Sem esse mapeamento, AHDE.ingest_telemetry() roda sem erro
        nenhum, mas NUNCA detecta mudança - confirmado com teste manual
        forçando gpu_temp de 41 pra 55 (delta de 14 graus, bem acima do
        threshold de 1.0) e mesmo assim zero evento publicado, porque
        `self._previous.get('gpu_temperature_celsius')` e
        `sample.get('gpu_temperature_celsius')` davam None nos dois
        lados (a chave usada era 'gpu_temp', não a que o detector
        procura). Silencioso, sem exceção - o tipo de bug que passa
        despercebido pra sempre se não for testado ponta a ponta.

        Faz merge (não substitui) - preserva os campos originais no
        snapshot que o SnapshotEngine grava (cpu_usage, gpu_load etc.
        continuam lá pra quem consumir o snapshot depois), e ADICIONA os
        aliases com o nome que o ChangeDetectionEngine espera, só pra
        ele conseguir comparar. cpu_temperature_celsius fica None de
        propósito - o TelemetryEngine da Phoenix não mede temperatura de
        CPU hoje (só GPU), e é melhor documentar essa ausência real do
        que inventar um valor. disk_health_status / driver_change_
        detected / throttling_detected também ficam ausentes pelo mesmo
        motivo - nenhum produtor hoje coleta isso.
        """
        merged = dict(live_metrics)
        merged["gpu_temperature_celsius"] = live_metrics.get("gpu_temp")
        merged["vram_used_mb"] = live_metrics.get("gpu_vram_used")
        # ram_used_mb já bate por coincidência entre os dois vocabulários,
        # mas fica explícito aqui mesmo assim, documentando a dependência.
        merged["ram_used_mb"] = live_metrics.get("ram_used_mb")
        merged["cpu_temperature_celsius"] = None
        return merged

    async def _start_llm_engine(self, boot_plan) -> bool:
        """Sobe o llama.cpp e loga o resultado. Isolado em método próprio
        porque agora é chamado de dois lugares: na hora (modelo já pronto)
        ou depois, quando o download em background termina."""
        llm_ok = await self.runtime.start("llama.cpp", boot_plan)
        if llm_ok:
            self.logs.add_event("INFO", "Kernel", "Servidor LLM ativo na porta 8081.")
            print("[Kernel] ✅ Servidor LLM ativo na porta 8081.")
        else:
            self.logs.add_event("ERROR", "Kernel", "Falha ao subir Servidor LLM na porta 8081.")
            print("[Kernel] ❌ Falha ao subir Servidor LLM (Verifique se o download do .gguf concluiu).")
        return llm_ok

    async def _start_llm_engine_when_ready(self, boot_plan, timeout_seconds: int = 1800, poll_interval: int = 5):
        """Espera o download do modelo padrão terminar (com timeout) e só
        então sobe o llama.cpp. Roda em background (asyncio.create_task),
        não bloqueia o boot da API."""
        from phoenix_kernel.paths import PhoenixPaths
        model_path = PhoenixPaths.get_category_path("Chat", "GGUF") / "qwen3-8b-q4_k_m.gguf"
        min_valid_size_bytes = 1_000_000_000  # 1GB - abaixo disso, arquivo truncado/corrompido

        waited = 0
        while waited < timeout_seconds:
            if model_path.exists() and model_path.stat().st_size >= min_valid_size_bytes:
                print("[Kernel] Download do modelo padrão concluído - subindo Servidor LLM agora.")
                await self._start_llm_engine(boot_plan)
                return
            await asyncio.sleep(poll_interval)
            waited += poll_interval

        logger.error(f"Kernel: modelo padrão não ficou pronto após {timeout_seconds}s de espera - desistindo de subir o llama.cpp automaticamente.")
        self.logs.add_event("ERROR", "Kernel", f"Timeout ({timeout_seconds}s) esperando download do modelo padrão - Servidor LLM não foi iniciado.")

    async def _ensure_default_model(self) -> bool:
        """Verifica se o modelo padrão para raciocínio nativo existe E é
        válido (checagem de tamanho mínimo, não só Path.exists() - um
        download interrompido/disco cheio deixa o arquivo presente só que
        truncado, e Path.exists() sozinho nunca detectava isso). Se não
        estiver pronto, dispara o download em background e retorna False.
        Retorna True só quando o modelo está pronto pra uso imediato.

        PHX-FIX (2026-08-22): a checagem de tamanho/corrupção e o disparo
        do download em background agora vêm de phoenix_kernel.models.health
        (módulo novo, compartilhado com _ensure_default_stt_model() e
        _ensure_default_image_model() logo abaixo, e com o endpoint
        GET /api/models/status em api_server.py) - antes essa lógica estava
        copiada em cada um dos métodos _ensure_default_*, mesma classe de
        duplicação que já causou bugs reais em outro lugar desta auditoria
        (listas de match de arquitetura de imagem saindo de sincronia).
        Comportamento observável não muda."""
        from phoenix_kernel.paths import PhoenixPaths
        from phoenix_kernel.models import health
        model_path = PhoenixPaths.get_category_path("Chat", "GGUF") / "qwen3-8b-q4_k_m.gguf"

        async def _download():
            _models_module = importlib.import_module("phoenix_kernel.models.model_manager")
            mm = _models_module.ModelManager()
            await mm.download_model("qwen3:8b")

        return await health.ensure_model_ready(
            label="Modelo padrão (qwen3:8b)",
            path=model_path,
            min_valid_size_bytes=1_000_000_000,  # Q4_K_M do Qwen3-8B fica na faixa de 4.5-5GB
            trigger_download=_download,
            log_event=self.logs.add_event,
        )

    async def _ensure_default_stt_model(self) -> bool:
        """Mesmo padrão de _ensure_default_model() acima, mas para o
        modelo STT (Whisper) - achado real da auditoria de 2026-08-20
        ('Whisper model provisioning'): whisper.cpp compilava, /api/transcribe
        existia, mas nada baixava ggml-base.bin. WhisperDriver._find_model()
        (phoenix_kernel/runtime/drivers/whisper.py) procura em
        PhoenixPaths.get_category_path('Audio') - mesma pasta resolvida aqui.
        Nunca trava o boot da API esperando o download (~150MB) terminar.

        PHX-FIX (2026-08-22): ver comentário de _ensure_default_model()
        acima - agora usa phoenix_kernel.models.health em vez de lógica
        duplicada."""
        from phoenix_kernel.paths import PhoenixPaths
        from phoenix_kernel.models import health
        model_path = PhoenixPaths.get_category_path("Audio") / "ggml-base.bin"

        async def _download():
            _models_module = importlib.import_module("phoenix_kernel.models.model_manager")
            mm = _models_module.ModelManager()
            await mm.download_model("whisper-base")

        return await health.ensure_model_ready(
            label="Modelo STT padrão (whisper ggml-base)",
            path=model_path,
            min_valid_size_bytes=100_000_000,  # ggml-base.bin real fica em ~148MB
            trigger_download=_download,
            log_event=self.logs.add_event,
        )

    async def _ensure_default_image_model(self) -> bool:
        """PHX-NEW (2026-08-22, pedido do usuário: "verifica se faltam
        [modelos] pra rodar e se faltar baixa novamente pra evitar erros e
        assim sempre garantimos sucessos"): mesmo padrão de
        _ensure_default_model()/_ensure_default_stt_model() acima, agora
        pro modelo de imagem PADRÃO (Flux.1-schnell Q4_0, default_for_roles
        de "image_generation" em catalog/models.json).

        Antes desta função, nada verificava isso no boot - só se descobria
        que faltava na hora de gerar a primeira imagem pelo chat, e a
        ponte direta (ResidentManager.generate_image_direct()) NUNCA baixa
        modelo sozinha por design (só uma missão aprovada faz isso, ver
        comentário lá) - então numa instalação nova a primeira geração de
        imagem sempre falhava com "nenhum modelo de imagem instalado",
        sem nenhum aviso ou tentativa de correção automática antes disso.

        PHX-FIX (auditoria Claude): o nome hardcoded aqui era
        "flux1-schnell-Q4_K_M.gguf", mas catalog/assets/flux.json (o
        alias que _download() de fato baixa) apontava pra uma fonte
        incompatível com sd.cpp (unsloth/city96-tooling) que teria
        quebrado no generate mesmo se o download funcionasse. Corrigido
        junto: flux.json agora baixa flux1-schnell-q4_0.gguf de
        leejet/FLUX.1-schnell-gguf (compatível, validado manualmente) -
        o nome abaixo precisa bater com o "filename" real de flux.json,
        senão esta checagem nunca reconhece o arquivo como já presente
        e tenta baixar de novo a cada boot.

        PHX-FIX (auditoria Claude): o caminho de verificação aqui era
        hardcoded como PhoenixPaths.get_category_path("Image") /
        "<filename>" (sem subpasta), mas o AssetManager real resolve
        "target_dir": "downloads/images/" de flux.json como uma SUBPASTA
        "images/" dentro da categoria (ver
        Engine/provisioning/asset_manager.py._resolve_target_dir) - ou
        seja, o download real cai em Models/Image/images/<filename>, e
        essa checagem hardcoded olhava pra Models/Image/<filename> (sem a
        subpasta). Isso NUNCA batia: mesmo depois de um download bem
        sucedido, o boot seguinte achava "não pronto" e disparava
        download de novo, pra sempre. Mesma classe de bug já achada duas
        vezes nesta auditoria (duas fontes de verdade sobre "onde este
        arquivo mora", uma atualizada e outra esquecida - ver
        _IMAGE_ARCH_PATTERNS vs MODEL_PROFILES). Corrigido reutilizando a
        resolução real do AssetManager em vez de duplicar o caminho.

        Roda só em background, igual ao LLM/STT acima - nunca bloqueia o
        boot da API esperando os ~6.9GB do Flux baixarem."""
        from phoenix_kernel.models import health

        _asset_module = importlib.import_module("Engine.provisioning.asset_manager")
        am = _asset_module.AssetManager()
        flux_catalog = am._load_catalog("flux") or {}
        target_dir = am._resolve_target_dir(flux_catalog, "flux")
        filename = flux_catalog.get("filename", "flux1-schnell-q4_0.gguf")
        model_path = target_dir / filename

        async def _download():
            await asyncio.to_thread(am.get_asset, "flux")

        return await health.ensure_model_ready(
            label=f"Modelo de imagem padrão ({flux_catalog.get('name', 'Flux.1-schnell Q4_0')})",
            path=model_path,
            min_valid_size_bytes=4_000_000_000,  # real (HF, leejet Q4_0): 6.88 GB
            trigger_download=_download,
            log_event=self.logs.add_event,
        )

    def _merge_pool_entries_into_knowledge_base(self, pool_entries: list[dict]) -> int:
        """
        PHX-NEW: funde entradas baixadas do shared_knowledge_pool no
        data/knowledge_base.json local, sem duplicar. Não chama reingest
        no ChromaDB diretamente daqui de propósito - isso é
        responsabilidade do RagService/ChromaRagBackend na próxima vez que
        reingest_rag_sources() rodar, pra não acoplar o kernel na
        implementação interna do RAG.
        """
        if not pool_entries:
            return 0

        existing: list[dict] = []
        if KNOWLEDGE_BASE_JSON.exists():
            try:
                existing = json.loads(KNOWLEDGE_BASE_JSON.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    existing = [existing]
            except Exception as e:
                logger.error(f"Kernel: falha ao ler {KNOWLEDGE_BASE_JSON} para merge do pool - {e}")
                existing = []

        existing_ids = {doc.get("id") for doc in existing if doc.get("id")}
        new_cards = [
            _pool_entry_to_knowledge_card(entry) for entry in pool_entries
            if f"pool_{entry.get('id', '')}" not in existing_ids
        ]
        if not new_cards:
            return 0

        KNOWLEDGE_BASE_JSON.parent.mkdir(parents=True, exist_ok=True)
        KNOWLEDGE_BASE_JSON.write_text(
            json.dumps(existing + new_cards, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return len(new_cards)

    def _current_hardware_fingerprint(self) -> dict:
        """
        Monta um fingerprint mínimo (gpu/vram_gb) a partir do que o
        discovery já coletou no boot. Se chamado antes do boot terminar
        (não deveria acontecer - execute() só roda depois do runtime estar
        de pé), devolve vazio em vez de quebrar.
        """
        if not self.machine_context or not getattr(self.machine_context, "profile", None):
            return {}
        gpus = getattr(self.machine_context.profile, "gpus", None) or []
        if not gpus:
            return {}
        gpu = gpus[0]
        return {
            "gpu": getattr(gpu, "model", None) or (gpu.get("model") if isinstance(gpu, dict) else None),
            "vram_gb": getattr(gpu, "vram_gb", None) or (gpu.get("vram_gb") if isinstance(gpu, dict) else None),
        }

    async def _on_runtime_execution_completed(self, event: Event) -> None:
        """
        PHX-NEW: handler do evento que RuntimeEngine.execute() publica a
        cada execução (chat/imagem/visão/tts). Traduz pro schema fechado
        de cloud_sync.push_model_run() - allowlist já garante que nenhum
        campo de conteúdo passa por aqui, mesmo que o payload do evento um
        dia carregasse mais coisa por engano.
        """
        if self.cloud_sync is None:
            return
        payload = event.payload or {}
        metrics = payload.get("metrics") or {}
        try:
            await self.cloud_sync.push_model_run({
                "model_id": payload.get("model", "unknown"),
                "runtime": payload.get("runtime", "unknown"),
                "task_category": payload.get("task_category", "other"),
                "hardware_fingerprint": self._current_hardware_fingerprint(),
                "tokens_generated": metrics.get("tokens_generated", 0),
                "tokens_per_second": metrics.get("tokens_per_second", 0.0),
                "duration_ms": metrics.get("duration_ms", 0),
                "success": bool(payload.get("success", False)),
            })
        except Exception as e:
            # Nunca deixa telemetria quebrar a execução real - só loga.
            logger.debug(f"Kernel: falha ao registrar model_run - {e}")

    async def _cloud_sync_loop(self):
        # PHX-NEW: primeiro boot / clone novo - se ainda não existe
        # data/knowledge_base.json local (fica no .gitignore, então quem
        # clona o repo não recebe os documentos curados), baixa o pool
        # compartilhado inteiro antes de mais nada, pra não começar com
        # RAG completamente zerado.
        if self.cloud_sync is not None and not KNOWLEDGE_BASE_JSON.exists():
            pooled = await self.cloud_sync.pull_shared_knowledge_base(force_full=True)
            added = self._merge_pool_entries_into_knowledge_base(pooled)
            if added:
                self.logs.add_event(
                    "INFO", "FirestoreSync",
                    f"{added} documento(s) baixados do pool compartilhado no primeiro boot."
                )
                print(f"[Kernel] {added} documento(s) do conhecimento compartilhado baixados (primeiro boot).")

        await self.cloud_sync.sync_knowledge_base()
        # PHX-NEW: sincroniza os relatórios de instalação (logs/install/*.json)
        # que install_phoenix.ps1/common.ps1 já escrevem - falhas viram
        # achado compartilhável automaticamente (ver cloud_sync.py).
        await self.cloud_sync.sync_install_reports()

        while True:
            try:
                await asyncio.sleep(CLOUD_SYNC_INTERVAL_SEC)
                state_data = await self.state.get_state()
                await self.cloud_sync.sync_machine_state(state_data)

                # PHX-NEW: pull incremental do pool a cada ciclo - só traz
                # o que mudou desde o último pull (cursor em
                # SHARED_POOL_CURSOR_FILE), não o pool inteiro de novo.
                pooled = await self.cloud_sync.pull_shared_knowledge_base(force_full=False)
                added = self._merge_pool_entries_into_knowledge_base(pooled)
                if added:
                    self.logs.add_event("INFO", "FirestoreSync", f"{added} novo(s) achado(s) do pool compartilhado.")

                if has_consent():
                    self.logs.add_event("INFO", "FirestoreSync", "Telemetria sincronizada com a nuvem.")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"FirestoreSync: falha no loop de sync - {e}")
                self.logs.add_event("ERROR", "FirestoreSync", f"Falha ao sincronizar com o Firestore: {e}")

    async def shutdown(self):
        print("[Kernel] Desligando serviços...")
        self.logs.add_event("INFO", "Kernel", "Shutdown initiated.")

        await self.platform_process.stop()

        if self._cloud_sync_task:
            self._cloud_sync_task.cancel()

        # PHX-NEW (integração AHDE, Fase 2): cancela o loop de telemetria
        # e desliga o EventBus interno do AHDE (aguarda tasks pendentes
        # de subscribers antes de fechar - ver EventBus.shutdown()).
        if self._ahde_telemetry_task:
            self._ahde_telemetry_task.cancel()
        try:
            await self.ahde.shutdown()
        except Exception as e:
            logger.debug(f"Kernel: falha ao desligar AHDE - {e}")

        if self.cloud_sync is not None:
            self.cloud_sync.shutdown()
            
        # PHX-FIX (varredura 2026-08-21 rodada 2, achado #6): `except: pass`
        # engolia qualquer falha de shutdown do runtime sem log nenhum -
        # inconsistente com o padrão logo acima (AHDE, que já loga em
        # debug). Mesmo tratamento aqui.
        try:
            await self.runtime.shutdown()
        except Exception as e:
            logger.debug(f"Kernel: falha ao desligar runtime - {e}")
