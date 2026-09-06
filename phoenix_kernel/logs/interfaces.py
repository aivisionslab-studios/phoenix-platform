from abc import ABC, abstractmethod
from typing import Any

class ILogsService(ABC):
    @abstractmethod
    def add_event(self, level: str, source: str, message: str):
        pass
    
    @abstractmethod
    def get_recent_logs(self, count: int = 20) -> list[dict]:
        pass
