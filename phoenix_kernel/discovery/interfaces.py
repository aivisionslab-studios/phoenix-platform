from abc import ABC, abstractmethod
from typing import Any

class IDiscoveryService(ABC):
    @abstractmethod
    async def discover_hardware(self) -> dict[str, Any]:
        """Descobre o hardware estático da máquina (Machine DNA)."""
        pass