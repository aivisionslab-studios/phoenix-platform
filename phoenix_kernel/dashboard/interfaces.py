from abc import ABC, abstractmethod

class IEngine(ABC):
    @abstractmethod
    async def initialize(self):
        pass
