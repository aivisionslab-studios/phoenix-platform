from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import uuid

_UTC = timezone.utc

class HealthStatus(StrEnum):
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    UNHEALTHY = 'unhealthy'
    UNKNOWN = 'unknown'

@dataclass(frozen=True, slots=True, kw_only=True)
class Capability:
    name: str
    version: str = '1.0.0'
    description: str = ''

@dataclass(frozen=True, slots=True, kw_only=True)
class EngineDescriptor:
    id: str
    name: str
    version: str = '3.0.0'
    sdk_version: str = '1.0.0'
    capabilities: tuple[Capability, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    health_endpoint: str = 'health'
    configuration_schema: dict[str, object] = field(default_factory=dict)
    registered_at: datetime = field(default_factory=lambda: datetime.now(_UTC))
