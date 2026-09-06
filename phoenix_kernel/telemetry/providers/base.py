
from abc import ABC, abstractmethod
from phoenix_kernel.shared.models import TelemetrySnapshot

class ITelemetryProvider(ABC):
    @abstractmethod
    def get_metrics(self) -> TelemetrySnapshot: pass
