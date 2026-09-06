from dataclasses import dataclass, field, asdict
from typing import List, Any
from datetime import datetime, UTC
import uuid
from .enums import MissionStatus, MissionAction

JsonMap = dict[str, Any]

@dataclass
class MissionStep:
    step: int
    action: MissionAction
    target: str
    description: str
    parameters: JsonMap = field(default_factory=dict)

@dataclass
class Mission:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    intent: str = ""
    status: MissionStatus = MissionStatus.CREATED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    steps: List[MissionStep] = field(default_factory=list)
    metadata: JsonMap = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["created_at"] = self.created_at.isoformat()
        for step in data["steps"]:
            step["action"] = step["action"].value
        return data
