from __future__ import annotations
from typing import Protocol, runtime_checkable, Any

@runtime_checkable
class IConfigurationSDK(Protocol):
    def get(self, section: str, key: str = None, default: Any = None) -> Any: ...
