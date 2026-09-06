from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

_UTC = timezone.utc

@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ''
    source: str = ''
    timestamp: datetime = field(default_factory=lambda: datetime.now(_UTC))
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True, kw_only=True)
class Command:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    command_type: str = ''
    target: str = ''
    reply_to: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(_UTC))
    payload: dict[str, Any] = field(default_factory=dict)
