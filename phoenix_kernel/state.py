import asyncio
import logging
from dataclasses import asdict

from phoenix_kernel.paths import PhoenixPaths

logger = logging.getLogger(__name__)

class StateEngine:
    def __init__(self, budget, telemetry, services, models):
        self.budget = budget
        self.telemetry = telemetry
        self.services = services
        self.models = models
        self.machine_context = None
        self.hardware_data = None
        # PHX-NEW (integração AHDE, Fase 2): setado via set_ahde() depois
        # que o kernel instancia o AHDE - não é passado no construtor pra
        # não precisar reordenar a Composition Root do kernel.py.
        self.ahde = None
        # PHX-NEW: logs do kernel, injetados via set_logs() para expor
        # o terminal de boot real no Mission Console (substituindo o
        # hardcoded no frontend).
        self.logs = None

    def set_context(self, machine_context, hardware_data):
        self.machine_context = machine_context
        self.hardware_data = hardware_data

    def set_ahde(self, ahde) -> None:
        self.ahde = ahde

    def set_logs(self, logs_engine) -> None:
        """Injeta o LogsEngine após boot — mesmo padrão do set_ahde()."""
        self.logs = logs_engine

    async def get_state(self) -> dict:
        if not self.machine_context:
            return {"error": "Hardware ainda não descoberto"}
        
        profile = self.machine_context.profile
        gpu = profile.gpus[0] if profile.gpus else {}
        
        budget_task = self.budget.evaluate_machine(self.hardware_data)
        telemetry_task = self.telemetry.get_live_metrics()
        env_task = self.services.get_environment_status()
        models_task = self.models.get_model_and_rag_status()
        
        budget_data, telemetry_data, env, models_data = await asyncio.gather(
            budget_task, telemetry_task, env_task, models_task
        )

        return {
            "hardware": {
                "cpu": profile.cpu.get('model', 'Unknown'),
                "ram_mb": profile.memory.get('total_mb', 0),
                "gpu": gpu.get('model', 'Unknown'),
                "vram_mb": gpu.get('vram_mb', 0),
                "backends": list(profile.available_backends)
            },
            "hardware_devices": self.hardware_data,
            "budget": budget_data,
            "telemetry": telemetry_data,
            "environment": env,
            "models": models_data.get("models", []),
            # PHX-NEW (varredura 2026-08-21, achado 2): distingue "Ollama
            # offline/não instalado" de "genuinamente zero modelos" -
            # antes as duas situações produziam a mesma "models": [] sem
            # nenhum sinal a mais.
            "ollama_available": models_data.get("ollama_available", False),
            "rag_docs": models_data.get("rag_docs", 0),
            "rag_documents": models_data.get("rag_documents", []),
            "score": budget_data.get("score", 0),
            # PHX-FIX (achado real do usuário 2026-08-28, ao comparar esta
            # base com uma linha de trabalho paralela: "TIRAR CAMINHO
            # R:\Phoenix\Workstations, PORQUE NAO FAZ SENTIDO NENHUM... JA
            # NAO É MAIS R:\ E SÓ FUNCIONA NA MINHA MAQUINA"): ProcessLauncherBar.tsx
            # e ManualModal.tsx (via AviaryApp.tsx) mostravam
            # "R:\Phoenix\Workstations\Models\..." como se fosse UM caminho
            # universal - era só o drive específico de uma máquina de
            # desenvolvimento antiga, hardcoded direto no componente, e já
            # nem reflete a instalação real de ninguém (nem a de quem
            # escreveu aquele texto). PhoenixPaths (phoenix_kernel/paths.py)
            # já existe exatamente pra resolver isso de forma dinâmica (via
            # storage.json/ProgramData, nunca um literal C:\D:\E:\ no
            # código - ver docstring do próprio módulo) - só nunca tinha
            # sido exposto pro frontend. Agora o caminho REAL desta
            # instalação (o que get_workspace() de fato resolveu, seja qual
            # for a letra de unidade) vai no /api/state, e os componentes
            # que mostravam o texto fixo passam a usar este valor.
            "workspace_path": str(PhoenixPaths.get_workspace()),
            "ahde": self._get_ahde_section(),
            # PHX-NEW: logs reais do kernel (substituem o terminal hardcoded no frontend)
            "boot_log": self.logs.get_recent_logs(50) if hasattr(self, 'logs') and self.logs else [],
        }

    def _get_ahde_section(self) -> dict:
        """
        PHX-NEW (integração AHDE, Fase 2): expõe só dado real, derivado
        de scan de verdade (CapabilitySnapshot vem de CapabilityEngine.
        extract() rodando em cima do hardware/services reais coletados
        no boot + a cada tick de telemetria).

        DELIBERADAMENTE NÃO expõe health_score: HealthEngine.evaluate()
        (phoenix_kernel/ahde/health/engine.py) ainda é stub fixo em 100 -
        a Fase 4 (Health real + testes de degradação) não começou. O
        próprio código da Fase 0 já documenta isso como "Regra absoluta
        #2": nenhum consumidor pode tomar decisão (nem mostrar na tela
        como se fosse calculado) com esse valor do jeito que está hoje.
        Quando a Fase 4 entregar o cálculo de verdade, aí sim isso entra
        aqui.
        """
        if self.ahde is None:
            return {"available": False}

        hw_snap = self.ahde.get_latest_hardware_snapshot()
        tel_snap = self.ahde.get_latest_telemetry_snapshot()

        return {
            "available": True,
            "capabilities": asdict(hw_snap.capabilities) if hw_snap else None,
            "hardware_snapshot_id": hw_snap.snapshot_id if hw_snap else None,
            "hardware_snapshot_at": hw_snap.timestamp if hw_snap else None,
            "last_telemetry_change_at": tel_snap.timestamp if tel_snap else None,
        }
