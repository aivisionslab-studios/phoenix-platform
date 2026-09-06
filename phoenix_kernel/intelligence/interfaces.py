from abc import ABC, abstractmethod

class IResidentManager(ABC):
    @abstractmethod
    async def analyze_machine(self) -> str: pass
