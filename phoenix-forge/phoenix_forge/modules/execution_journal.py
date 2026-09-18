from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from phoenix_forge.modules import gpu_safety

SCHEMA = "phoenix.forge.execution-journal/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path() -> Path:
    return gpu_safety.state_dir() / "execution-journal.jsonl"


def record(result: dict[str, Any], *, workload: str, runtime: str, model: str) -> dict[str, Any]:
    trace = result.get("trace") or []
    entry = {
        "schema": SCHEMA,
        "recorded_at": _now(),
        "execution_id": result.get("execution_id"),
        "workload": workload,
        "runtime": runtime,
        "model": model,
        "status": result.get("status"),
        "deliver": result.get("deliver") is True,
        "effective_mode": result.get("effective_mode"),
        "route": result.get("route"),
        "notice": result.get("notice"),
        "timing": result.get("forge_timing"),
        "runtime_latency_s": (result.get("output") or {}).get("latency_s"),
        "usage": (result.get("output") or {}).get("usage") or {},
        "attempts": [
            {
                "attempt": item.get("attempt"),
                "mode": item.get("mode"),
                "status": (item.get("validation") or {}).get("status"),
                "failures": (item.get("validation") or {}).get("failures", []),
                "warnings": (item.get("validation") or {}).get("warnings", []),
                "evidence": (item.get("validation") or {}).get("evidence", {}),
            }
            for item in trace
        ],
    }
    path = _path(); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush(); os.fsync(handle.fileno())
    return entry


def recent(limit: int = 20) -> dict[str, Any]:
    path = _path(); entries: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines[-max(1, min(int(limit), 200)):]:
        try:
            value = json.loads(line)
            if isinstance(value, dict): entries.append(value)
        except json.JSONDecodeError:
            continue
    return {"schema": SCHEMA, "count": len(entries), "entries": entries}
