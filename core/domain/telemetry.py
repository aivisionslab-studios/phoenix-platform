from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_UTC = timezone.utc

@dataclass(frozen=True, slots=True, kw_only=True)
class TelemetrySample:
    timestamp: datetime
    cpu_usage_percent: float | None = None
    cpu_temperature_celsius: float | None = None
    ram_used_mb: float | None = None
    ram_available_mb: float | None = None
    gpu_usage_percent: float | None = None
    gpu_temperature_celsius: float | None = None
    vram_used_mb: float | None = None
    vram_total_mb: float | None = None
    uptime_seconds: float = 0.0

@dataclass(frozen=True, slots=True, kw_only=True)
class TelemetrySnapshot:
    current: TelemetrySample
    history: tuple[TelemetrySample, ...] = field(default_factory=tuple)
    collected_at: datetime = field(default_factory=lambda: datetime.now(_UTC))
