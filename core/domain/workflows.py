from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
import uuid

_UTC = timezone.utc

class TaskStatus(StrEnum):
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'
    SKIPPED = 'skipped'

@dataclass(frozen=True, slots=True, kw_only=True)
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ''
    action: str = ''
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None

@dataclass(frozen=True, slots=True, kw_only=True)
class Workflow:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ''
    tasks: tuple[Task, ...] = field(default_factory=tuple)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(_UTC))

@dataclass(frozen=True, slots=True, kw_only=True)
class Mission:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ''
    objective: str = ''
    workflow: Workflow | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    created_at: datetime = field(default_factory=lambda: datetime.now(_UTC))
