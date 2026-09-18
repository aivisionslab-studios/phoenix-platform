from __future__ import annotations
from typing import Protocol, runtime_checkable

@runtime_checkable
class IGatewaySDK(Protocol):
    async def start_server(self) -> None: ...
    async def stop_server(self) -> None: ...
