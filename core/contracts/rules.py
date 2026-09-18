from __future__ import annotations
from typing import Protocol, runtime_checkable
from core.domain.machine import MachineContext
from core.domain.execution import ExecutionPlan

@runtime_checkable
class IRulesSDK(Protocol):
    async def evaluate(self, context: MachineContext) -> ExecutionPlan: ...
    async def recommend_models(self, context: MachineContext) -> list[dict]: ...
