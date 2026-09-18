from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True, slots=True, kw_only=True)
class UserPreferences:
    preferred_runtime: str = ''
    preferred_backend: str = ''
    auto_install: bool = False
    language: str = 'pt-BR'
    theme: str = 'dark'
    extra: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True, kw_only=True)
class Policies:
    allow_cpu_fallback: bool = True
    max_vram_usage_percent: float = 90.0
    max_ram_usage_percent: float = 85.0
    thermal_throttle_limit_celsius: float = 85.0
    auto_repair: bool = True
    extra: dict[str, Any] = field(default_factory=dict)
