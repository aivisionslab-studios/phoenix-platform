from __future__ import annotations
from typing import Protocol, runtime_checkable, Any

@runtime_checkable
class IAgentSDK(Protocol):
    async def execute_task(self, agent_name: str, task: str, context: dict | None = None) -> Any: ...
