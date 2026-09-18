from __future__ import annotations
from typing import Protocol, runtime_checkable, Any
from core.domain.workflows import Workflow

@runtime_checkable
class IPipelineSDK(Protocol):
    async def execute_pipeline(self, pipeline: Workflow) -> dict[str, Any]: ...
