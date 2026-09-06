from __future__ import annotations
from typing import Protocol, runtime_checkable
from core.domain.workflows import Workflow

@runtime_checkable
class IWorkflowSDK(Protocol):
    async def execute(self, workflow: Workflow) -> Workflow: ...
