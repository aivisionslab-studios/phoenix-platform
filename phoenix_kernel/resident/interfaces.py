from abc import ABC, abstractmethod

class IResidentManager(ABC):
    @abstractmethod
    async def process_intent(self, intent: str) -> dict: pass

    @abstractmethod
    async def execute_plan(self, plan: list) -> str: pass

    @abstractmethod
    async def get_status(self) -> dict: pass
