from __future__ import annotations
from typing import Protocol, runtime_checkable

@runtime_checkable
class IUpdaterSDK(Protocol):
    async def check_for_updates(self) -> dict: ...
    async def apply_update(self) -> bool: ...
