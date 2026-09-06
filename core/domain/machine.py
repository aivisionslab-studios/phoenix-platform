from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import hashlib

_UTC = timezone.utc

@dataclass(frozen=True, slots=True, kw_only=True)
class MachineDNA:
    hash: str
    components_hashed: tuple[str, ...] = field(default_factory=tuple)
    generated_at: datetime = field(default_factory=lambda: datetime.now(_UTC))

@dataclass(frozen=True, slots=True, kw_only=True)
class MachineProfile:
    dna: MachineDNA
    cpu: dict[str, Any] = field(default_factory=dict)
    gpus: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    memory: dict[str, Any] = field(default_factory=dict)
    disks: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    motherboard: dict[str, Any] = field(default_factory=dict)
    network: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    os: dict[str, Any] = field(default_factory=dict)
    drivers: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    ai_environment: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    ai_readiness: dict[str, Any] = field(default_factory=dict)
    available_backends: tuple[str, ...] = field(default_factory=tuple)
    generated_at: datetime = field(default_factory=lambda: datetime.now(_UTC))

@dataclass(frozen=True, slots=True, kw_only=True)
class MachineContext:
    profile: MachineProfile | None = None
    telemetry: Any | None = None
    installed_models: tuple[Any, ...] = field(default_factory=tuple)
    installed_runtimes: tuple[Any, ...] = field(default_factory=tuple)
    configuration: dict[str, Any] = field(default_factory=dict)
    preferences: Any | None = None
    policies: Any | None = None
    capabilities: tuple[Any, ...] = field(default_factory=tuple)
