from __future__ import annotations
from typing import Protocol, runtime_checkable

@runtime_checkable
class INotificationSDK(Protocol):
    async def send_notification(self, title: str, message: str, level: str = "info") -> None: ...
