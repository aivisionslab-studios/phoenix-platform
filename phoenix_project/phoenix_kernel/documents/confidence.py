# confidence.py
"""Status de confiança e regras de auditoria (regra de ouro do projeto)."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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

def is_writeable(ev: FieldEvidence) -> bool:
    return ev.status in (ConfidenceStatus.CONFIRMED, ConfidenceStatus.PROBABLE)

def needs_audit(ev: FieldEvidence) -> bool:
    return ev.status in (ConfidenceStatus.CONFLICT, ConfidenceStatus.AMBIGUOUS, ConfidenceStatus.INVALID)
