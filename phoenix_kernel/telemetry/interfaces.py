from abc import ABC, abstractmethod
from typing import Any

class ITelemetryService(ABC):
    @abstractmethod
    async def get_live_metrics(self) -> dict[str, Any]:
        """Coleta métricas em tempo real (CPU, RAM, GPU)."""
        pass