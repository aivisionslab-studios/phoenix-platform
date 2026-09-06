from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_UTC = timezone.utc

@dataclass(frozen=True, slots=True, kw_only=True)
class HardwareDescriptor:
    component: str
    model: str
    vendor: str = ''
    driver_version: str = ''
    details: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True, kw_only=True)
class HardwareEvent:
    event_type: str
    component: str
    old_value: Any = None
    new_value: Any = None
    delta: Any = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(_UTC))
