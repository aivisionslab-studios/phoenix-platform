from abc import ABC, abstractmethod
from typing import Any

class IServicesService(ABC):
    @abstractmethod
    async def get_environment_status(self) -> dict[str, Any]:
        """Verifica o status dos serviços do sistema (Docker, Ollama, etc)."""
        pass