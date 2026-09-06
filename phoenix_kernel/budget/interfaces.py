from abc import ABC, abstractmethod
from typing import Any

class IBudgetService(ABC):
    @abstractmethod
    async def evaluate_machine(self, hardware_data: dict[str, Any]) -> dict[str, Any]:
        """Calcula o score e a classe da máquina baseado no hardware."""
        pass