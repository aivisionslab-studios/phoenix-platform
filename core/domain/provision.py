from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True, slots=True, kw_only=True)
class ProvisionItem:
    id: str
    name: str
    category: str  # infrastructure, runtime, model, interface
    action: str    # install, compile, download
    required: bool = True
    reason: str = ""

@dataclass(frozen=True, slots=True, kw_only=True)
class ProvisionPlan:
    machine_id: str
    items: list[ProvisionItem] = field(default_factory=list)
    summary: str = ""
