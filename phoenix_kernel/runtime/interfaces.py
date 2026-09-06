from abc import ABC, abstractmethod
from core.domain.execution import ExecutionPlan, ExecutionResult

class IRuntimeService(ABC):
    @abstractmethod
    async def initialize(self):
        """Inicializa os drivers (Ollama, llama.cpp, etc)."""
        pass

    @abstractmethod
    async def shutdown(self):
        """Desliga os runtimes limpinhos."""
        pass

    @abstractmethod
    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        """Executa o plano de inferência gerado pelo Planner."""
        pass