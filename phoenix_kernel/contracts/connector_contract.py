from abc import ABC, abstractmethod

class IConnector(ABC):
    @abstractmethod
    def install(self, name: str, info: dict) -> str: pass
    
    @abstractmethod
    def check(self, name: str) -> bool: pass
    
    @abstractmethod
    def status(self, name: str) -> str: pass
