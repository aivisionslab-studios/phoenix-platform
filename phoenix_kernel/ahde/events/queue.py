# phoenix_kernel/ahde/events/queue.py
from abc import ABC, abstractmethod
from phoenix_kernel.ahde.contracts import DiscoveryEvent

class EventQueue(ABC):
    """Interface para fila persistente (Fase 2). Garante que eventos não se percam se a rede cair."""
    @abstractmethod
    async def enqueue(self, event: DiscoveryEvent) -> None:
        pass

    @abstractmethod
    async def dequeue(self) -> DiscoveryEvent:
        pass

class MemoryEventQueue(EventQueue):
    """Implementação temporária em memória para a Fase 1."""
    def __init__(self):
        self._queue = []
        
    async def enqueue(self, event: DiscoveryEvent) -> None:
        self._queue.append(event)
        
    async def dequeue(self) -> DiscoveryEvent:
        if self._queue:
            return self._queue.pop(0)
        return None
