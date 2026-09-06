from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
import uuid

_UTC = timezone.utc

class ExecutionStatus(StrEnum):
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    SKIPPED = 'skipped'

@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPlan:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    runtime: str = ''
    backend: str = ''
    model: str = ''
    strategy: str = ''
    parameters: dict[str, Any] = field(default_factory=dict)
    steps: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    confidence: float = 0.0
    reasoning: str = ''
    created_at: datetime = field(default_factory=lambda: datetime.now(_UTC))

@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionResult:
    plan_id: str
    status: ExecutionStatus
    output: Any = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    metrics: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
