from abc import ABC, abstractmethod
from typing import Any

class ISecurityService(ABC):
    @abstractmethod
    async def check_integrity(self) -> dict[str, Any]:
        """Checks basic security and integrity of the platform."""
        pass
