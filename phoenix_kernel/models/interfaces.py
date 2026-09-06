from abc import ABC, abstractmethod
from typing import Any

class IModelsService(ABC):
    @abstractmethod
    async def get_model_and_rag_status(self) -> dict[str, Any]:
        """Retorna a lista de modelos de IA instalados e a contagem de documentos do RAG."""
        pass