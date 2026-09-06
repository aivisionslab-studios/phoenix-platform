from abc import ABC, abstractmethod

class IService(ABC):
    @abstractmethod
    async def start(self): pass
    
    @abstractmethod
    async def stop(self): pass
    
    @abstractmethod
    async def health(self) -> dict: pass
