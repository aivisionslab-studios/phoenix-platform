from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

class ConfidenceStatus(Enum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    INVALID = "invalid"

@dataclass
class FieldEvidence:
    value: Any
    status: ConfidenceStatus
    source: str = ""
    reason: str = ""
    candidates: list = field(default_factory=list)

def is_writeable(ev):
    return ev.status in (ConfidenceStatus.CONFIRMED, ConfidenceStatus.PROBABLE)

def needs_audit(ev):
    return ev.status in (ConfidenceStatus.CONFLICT, ConfidenceStatus.AMBIGUOUS, ConfidenceStatus.INVALID)
