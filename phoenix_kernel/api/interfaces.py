from abc import ABC, abstractmethod

class IApiService(ABC):
    @abstractmethod
    async def process_command(self, command: str) -> dict:
        """Processa um comando enviado pelo usuário e retorna a resposta."""
        pass