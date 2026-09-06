from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

class RuntimeState(StrEnum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'
    ERROR = 'error'

@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeDescriptor:
    name: str
    version: str = ''
    endpoint: str = ''
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    supported_backends: tuple[str, ...] = field(default_factory=tuple)
    priority: int = 1

@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeStatus:
    name: str
    state: RuntimeState
    health: str = 'unknown'
    loaded_model: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
