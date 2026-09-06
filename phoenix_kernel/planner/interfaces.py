from abc import ABC, abstractmethod
from core.domain.machine import MachineContext
from core.domain.execution import ExecutionPlan

class IPlannerService(ABC):
    @abstractmethod
    async def initialize(self):
        """Inicializa dependências (como o RAG)."""
        pass

    @abstractmethod
    async def plan_inference(self, context: MachineContext, user_prompt: str) -> ExecutionPlan:
        """Decide qual modelo e runtime usar com base no hardware e na pergunta."""
        pass