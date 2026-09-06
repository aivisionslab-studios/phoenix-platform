import asyncio
import logging
import psutil
from typing import Any
from .interfaces import ITelemetryService
from .providers.factory import get_telemetry_provider

logger = logging.getLogger(__name__)

class TelemetryEngine(ITelemetryService):
    def __init__(self):
        # A fábrica decide se vai usar WindowsProvider ou LinuxProvider
        self.provider = get_telemetry_provider()

    async def get_live_metrics(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        
        # Roda a coleta de métricas (que é bloqueante) numa thread separada
        def collect():
            snapshot = self.provider.get_metrics()
            return {
                "cpu_usage": snapshot.cpu_usage_percent,
                "ram_used_mb": snapshot.ram_used_mb,
                "ram_total_mb": int(psutil.virtual_memory().total / (1024 * 1024)),
                "gpu_temp": snapshot.gpu_temp_celsius,
                "gpu_load": snapshot.gpu_load_percent,
                "gpu_vram_used": snapshot.gpu_vram_used_mb
            }
            
        metrics = await loop.run_in_executor(None, collect)
        return metrics
