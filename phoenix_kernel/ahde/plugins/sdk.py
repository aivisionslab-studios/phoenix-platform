# phoenix_kernel/ahde/plugins/sdk.py
from abc import ABC, abstractmethod
from phoenix_kernel.ahde.contracts import DiscoveryEvent

class AHDEPlugin(ABC):
    """SDK para produtos AIVisions (iDoctor, etc.) se plugarem no AHDE sem alterar o núcleo."""
    @abstractmethod
    async def initialize(self) -> None:
        pass

    @abstractmethod
    async def on_event(self, event: DiscoveryEvent) -> None:
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        pass
