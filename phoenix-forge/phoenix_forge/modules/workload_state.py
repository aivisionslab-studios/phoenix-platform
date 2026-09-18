from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from phoenix_forge.modules import gpu_safety

SCHEMA = "phoenix.forge.workload-state/v1"
_lock = RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path() -> Path:
    return gpu_safety.state_dir() / "workload-states.json"


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if data.get("schema") == SCHEMA:
            return data
    except (OSError, ValueError):
        pass
    return {"schema": SCHEMA, "updated_at": _now(), "workloads": {}}


def _save(data: dict[str, Any]) -> None:
    path = _path(); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass


def transition(workload: str, state: str, *, reason: str, effective_mode: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    workload = str(workload or "unknown").lower(); state = state.upper(); effective_mode = effective_mode.upper()
    allowed = {"GPU_ALLOWED", "GPU_MONITORED", "HYBRID_FALLBACK", "CPU_FALLBACK", "BLOCKED", "RECOVERING"}
    if state not in allowed:
        raise ValueError(f"Unknown workload state: {state}")
    with _lock:
        data = _load(); previous = data["workloads"].get(workload, {}).get("state")
        entry = {"workload": workload, "state": state, "previous_state": previous, "effective_mode": effective_mode,
                 "reason": reason, "updated_at": _now(), "fallback_order": ["GPU", "HYBRID", "CPU"], "evidence": evidence or {}}
        data["workloads"][workload] = entry; data["updated_at"] = _now(); _save(data); return entry


def observe_route(route: dict[str, Any]) -> dict[str, Any]:
    workload = str(route.get("workload") or "unknown")
    mode = str(route.get("effective_mode") or "CPU").upper()
    rule_state = str((route.get("rule") or {}).get("state") or "UNKNOWN").upper()
    if mode == "CPU": state = "CPU_FALLBACK"
    elif mode == "HYBRID": state = "HYBRID_FALLBACK"
    elif "MONITORED" in mode or rule_state == "CONDITIONAL": state = "GPU_MONITORED"
    else: state = "GPU_ALLOWED"
    # IMPORTANT: never persist the live route object itself. gpu_ledger.route()
    # attaches this workload_state back onto that same dict; keeping the
    # original object here creates route -> workload_state -> evidence ->
    # route circular references and FastAPI then returns HTTP 500 while
    # serializing /api/runtime/guarded-chat. Persist a JSON-safe snapshot.
    route_snapshot = {k: v for k, v in route.items() if k != "workload_state"}
    return transition(
        workload, state,
        reason=str((route.get("rule") or {}).get("reason") or "routing_policy"),
        effective_mode=mode, evidence={"route": route_snapshot},
    )


def observe_execution(result: dict[str, Any], workload: str) -> dict[str, Any]:
    status = str(result.get("status") or "UNKNOWN").upper(); mode = str(result.get("effective_mode") or "CPU").upper()
    if result.get("deliver") is not True:
        state = "BLOCKED"
    elif mode == "CPU" and ("GPU" in status or (result.get("route") or {}).get("safety_override")):
        state = "CPU_FALLBACK"
    elif mode == "HYBRID": state = "HYBRID_FALLBACK"
    elif mode == "GPU": state = "GPU_MONITORED" if (result.get("route") or {}).get("notify_user") else "GPU_ALLOWED"
    else: state = "CPU_FALLBACK"
    interception=result.get("failure_interception") or {}
    notice=result.get("notice") or {}
    return transition(workload, state, reason=status.lower(), effective_mode=mode, evidence={
        "execution_id": result.get("execution_id"), "deliver": result.get("deliver"),
        "status": status, "failure_classes": interception.get("classes") or [],
        "architecture_changed": bool(interception.get("architecture_changed")),
        "notice_code": notice.get("code") if isinstance(notice,dict) else None,
    })


def status() -> dict[str, Any]:
    with _lock: return _load()
