from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from phoenix_forge.models import DetectReport
from phoenix_forge.modules import gpu_safety, multi_device_scheduler, runtime_feedback

SCHEMA = "phoenix.forge.scheduler-execution-policy/v1"
DISPATCH_SCHEMA = "phoenix.forge.scheduler-dispatch/v1"
STATE_SCHEMA = "phoenix.forge.scheduler-execution-state/v1"
LEASE_SCHEMA = "phoenix.forge.scheduler-device-leases/v1"

_LOCK = threading.RLock()
_DEFAULT_LEASE_TTL_S = 300.0
_MAX_LEASE_TTL_S = 3600.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_dir() -> Path:
    p = gpu_safety.state_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _leases_path() -> Path:
    return _state_dir() / "scheduler-device-leases.json"


def _executions_path() -> Path:
    return _state_dir() / "scheduler-executions.jsonl"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_event(event: dict[str, Any]) -> None:
    path = _executions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as h:
        h.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def _load_leases() -> dict[str, Any]:
    state = _read_json(_leases_path(), {"schema": LEASE_SCHEMA, "leases": {}})
    if not isinstance(state, dict):
        state = {"schema": LEASE_SCHEMA, "leases": {}}
    state.setdefault("schema", LEASE_SCHEMA)
    state.setdefault("leases", {})
    return state


def _cleanup_expired(state: dict[str, Any], now: float | None = None) -> bool:
    now = float(time.time() if now is None else now)
    leases = state.setdefault("leases", {})
    dead = [key for key, row in leases.items() if float((row or {}).get("expires_epoch", 0.0) or 0.0) <= now]
    for key in dead:
        leases.pop(key, None)
    return bool(dead)


def leases() -> dict[str, Any]:
    with _LOCK:
        state = _load_leases()
        changed = _cleanup_expired(state)
        if changed:
            _atomic_write(_leases_path(), state)
        rows = list(state.get("leases", {}).values())
        rows.sort(key=lambda x: (str(x.get("device_key")), str(x.get("execution_id"))))
        return {"schema": LEASE_SCHEMA, "count": len(rows), "leases": rows}


def _acquire_lease(device_key: str, execution_id: str, assignment_id: str, ttl_s: float) -> dict[str, Any]:
    if not device_key:
        raise ValueError("device_key is required for GPU lease")
    ttl_s = max(5.0, min(float(ttl_s), _MAX_LEASE_TTL_S))
    now = time.time()
    with _LOCK:
        state = _load_leases()
        _cleanup_expired(state, now)
        current = state["leases"].get(device_key)
        if current and current.get("execution_id") != execution_id:
            return {
                "ok": False,
                "status": "DEVICE_BUSY",
                "device_key": device_key,
                "holder_execution_id": current.get("execution_id"),
                "expires_at": current.get("expires_at"),
            }
        token = uuid.uuid4().hex
        row = {
            "device_key": device_key,
            "execution_id": execution_id,
            "assignment_id": assignment_id,
            "lease_token": token,
            "acquired_at": _now_iso(),
            "expires_epoch": now + ttl_s,
            "expires_at": datetime.fromtimestamp(now + ttl_s, timezone.utc).isoformat(),
            "ttl_s": ttl_s,
        }
        state["leases"][device_key] = row
        _atomic_write(_leases_path(), state)
        return {"ok": True, "status": "LEASED", **row}


def _release_execution_leases(execution_id: str) -> int:
    with _LOCK:
        state = _load_leases()
        leases_map = state.setdefault("leases", {})
        keys = [key for key, row in leases_map.items() if (row or {}).get("execution_id") == execution_id]
        for key in keys:
            leases_map.pop(key, None)
        if keys:
            _atomic_write(_leases_path(), state)
        return len(keys)


def _safety_snapshot(report: DetectReport, workload: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for gpu in report.gpus:
        key = getattr(gpu, "device_key", None)
        if key:
            out[key] = gpu_safety.status_for_gpu(gpu, workload=workload)
    return out


def _is_blocked(status: dict[str, Any]) -> bool:
    return str((status.get("authorization") or {}).get("state", "")).upper() == "BLOCKED"


def _assignment(device: dict[str, Any] | None, ordinal: int, task_indexes: list[int], execution_id: str) -> dict[str, Any]:
    assignment_id = f"{execution_id}-a{ordinal}"
    if device is None:
        return {
            "assignment_id": assignment_id,
            "target": "CPU",
            "device_key": None,
            "device_index": None,
            "task_indexes": task_indexes,
            "lease": None,
            "status": "READY",
        }
    return {
        "assignment_id": assignment_id,
        "target": "GPU",
        "device_key": device.get("device_key"),
        "device_index": device.get("device_index"),
        "name": device.get("name"),
        "task_indexes": task_indexes,
        "lease": None,
        "status": "PENDING_LEASE",
    }


def prepare_dispatch(
    report: DetectReport,
    *,
    workload: str = "llm",
    mode: str = "AUTO",
    parallelizable: bool = False,
    task_count: int = 1,
    min_vram_bytes: int = 0,
    backend: str = "generic",
    cooperative_executor_available: bool = False,
    lease_ttl_s: float = _DEFAULT_LEASE_TTL_S,
    acquire_leases: bool = True,
    plan_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_count = max(1, min(int(task_count), 10000))
    execution_id = uuid.uuid4().hex
    plan = plan_override or multi_device_scheduler.plan(
        report,
        workload=workload,
        mode=mode,
        backend=backend,
        parallelizable=parallelizable,
        min_vram_bytes=min_vram_bytes,
        record=True,
    )

    effective = str(plan.get("effective_mode", "CPU")).upper()
    selected = list(plan.get("selected") or [])
    notes = list(plan.get("notes") or [])
    safety_now = _safety_snapshot(report, workload)

    safe_selected = []
    for device in selected:
        key = device.get("device_key")
        current = safety_now.get(key, {})
        if current and _is_blocked(current):
            notes.append(f"safety_changed_before_dispatch:{key}")
        else:
            safe_selected.append(device)

    if len(safe_selected) != len(selected):
        selected = safe_selected
        if not selected:
            effective = "CPU"
            notes.append("cpu_fallback_after_safety_revalidation")
        elif effective == "PARALLEL" and len(selected) == 1:
            effective = "SINGLE"
            notes.append("parallel_degraded_after_safety_revalidation")

    execution_ready = True
    if effective == "COOPERATIVE":
        if not cooperative_executor_available:
            execution_ready = False
            notes.append("cooperative_backend_executor_unavailable")
        elif len(selected) < 2:
            execution_ready = False
            notes.append("cooperative_requires_multiple_devices")

    assignments: list[dict[str, Any]] = []
    if effective == "CPU" or not selected:
        assignments = [_assignment(None, 0, list(range(task_count)), execution_id)]
    elif effective == "PARALLEL":
        buckets = [[] for _ in selected]
        for idx in range(task_count):
            buckets[idx % len(selected)].append(idx)
        for i, (device, indexes) in enumerate(zip(selected, buckets)):
            if indexes:
                assignments.append(_assignment(device, i, indexes, execution_id))
    elif effective == "COOPERATIVE":
        for i, device in enumerate(selected):
            assignments.append(_assignment(device, i, list(range(task_count)), execution_id))
    else:
        assignments = [_assignment(selected[0], 0, list(range(task_count)), execution_id)]

    lease_failures = []
    if acquire_leases and execution_ready:
        acquired: list[str] = []
        for assignment in assignments:
            if assignment["target"] != "GPU":
                continue
            lease = _acquire_lease(assignment["device_key"], execution_id, assignment["assignment_id"], lease_ttl_s)
            assignment["lease"] = lease
            if lease.get("ok"):
                assignment["status"] = "LEASED"
                acquired.append(assignment["device_key"])
            else:
                assignment["status"] = "DEVICE_BUSY"
                lease_failures.append(lease)
        if lease_failures:
            _release_execution_leases(execution_id)
            for assignment in assignments:
                if assignment["target"] == "GPU":
                    assignment["lease"] = None
                    assignment["status"] = "NOT_DISPATCHABLE"
            execution_ready = False
            notes.append("device_lease_conflict")

    out = {
        "schema": DISPATCH_SCHEMA,
        "execution_id": execution_id,
        "created_at": _now_iso(),
        "workload": workload,
        "backend": backend,
        "requested_mode": str(mode).upper(),
        "effective_mode": effective,
        "task_count": task_count,
        "execution_ready": execution_ready,
        "assignments": assignments,
        "lease_failures": lease_failures,
        "scheduler_plan": plan,
        "notes": notes,
        "policy": {
            "safety_revalidated_at_dispatch": True,
            "device_key_lease_prevents_concurrent_claims": True,
            "cpu_fallback_preserved": True,
            "parallel_tasks_are_independent": True,
            "cooperative_requires_backend_executor": True,
            "dispatch_does_not_spawn_arbitrary_processes": True,
        },
    }
    _append_event({"event": "DISPATCH_PREPARED", **out})
    return out


def record_result(execution_id: str, assignment_id: str, *, status: str, failure_class: str | None = None,
                  detail: str | None = None, release_leases: bool = True, training_eligible: bool = True) -> dict[str, Any]:
    normalized = str(status or "UNKNOWN").upper()
    event = {
        "schema": STATE_SCHEMA, "event": "ASSIGNMENT_RESULT", "recorded_at": _now_iso(),
        "execution_id": execution_id, "assignment_id": assignment_id, "status": normalized,
        "failure_class": failure_class, "detail": detail,
    }
    _append_event(event)
    feedback = None
    feedback_error = None
    released = 0
    try:
        try:
            feedback = runtime_feedback.record_result(
                execution_id, assignment_id, status=normalized, failure_class=failure_class, detail=detail,
                training_eligible=training_eligible)
        except Exception as exc:
            feedback_error = f"{type(exc).__name__}: {exc}"[:240]
    finally:
        if release_leases:
            released = _release_execution_leases(execution_id)
    return {**event, "runtime_feedback": feedback, "runtime_feedback_error": feedback_error, "released_leases": released}


def cancel(execution_id: str, reason: str = "user_or_engine_cancel") -> dict[str, Any]:
    released = _release_execution_leases(execution_id)
    event = {
        "schema": STATE_SCHEMA,
        "event": "EXECUTION_CANCELLED",
        "recorded_at": _now_iso(),
        "execution_id": execution_id,
        "reason": reason,
        "released_leases": released,
    }
    _append_event(event)
    return event


def history(limit: int = 100) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    try:
        lines = _executions_path().read_text(encoding="utf-8").splitlines()
        for line in lines[-max(1, min(int(limit), 1000)):]:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return {"schema": "phoenix.forge.scheduler-execution-history/v1", "count": len(rows), "events": rows}


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "READY",
        "dispatch_modes": {
            "CPU": "READY",
            "SINGLE": "READY",
            "PARALLEL": "READY_FOR_INDEPENDENT_TASKS",
            "COOPERATIVE": "READY_WHEN_COOPERATIVE_BACKEND_REGISTERED",
        },
        "leases": {"persistent": True, "ttl_default_s": _DEFAULT_LEASE_TTL_S, "cross_request": True},
        "result_correlation": True,
        "cancellation": True,
        "policy": {
            "safety_revalidation_before_dispatch": True,
            "no_arbitrary_process_spawn": True,
            "backend_executor_is_separate": True,
            "cpu_fallback_available": True,
            "runtime_feedback_recorded": True,
        },
    }
