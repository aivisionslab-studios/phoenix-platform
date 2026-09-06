from abc import ABC, abstractmethod
from phoenix_kernel.shared.models import HardwareSnapshot

class IDiscoveryProvider(ABC):
    @abstractmethod
    def discover(self) -> HardwareSnapshot:
        pass
