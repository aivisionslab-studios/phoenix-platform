from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

SCHEMA = "phoenix.forge.cooperative-executor/v1"
_LOCK = threading.RLock()


@dataclass(frozen=True)
class BackendAdapter:
    name: str
    execute: Callable[[dict[str, Any]], dict[str, Any]]
    workloads: tuple[str, ...]


_ADAPTERS: dict[str, BackendAdapter] = {}


def register_backend(name: str, execute: Callable[[dict[str, Any]], dict[str, Any]], *, workloads: tuple[str, ...] = ("*",)) -> dict[str, Any]:
    key=str(name or "").strip().lower()
    if not key or not callable(execute):
        raise ValueError("backend name and callable execute function are required")
    adapter=BackendAdapter(key,execute,tuple(str(x).lower() for x in workloads) or ("*",))
    with _LOCK:
        _ADAPTERS[key]=adapter
    return {"status":"REGISTERED","backend":key,"workloads":list(adapter.workloads)}


def unregister_backend(name: str) -> bool:
    with _LOCK:
        return _ADAPTERS.pop(str(name or "").strip().lower(),None) is not None


def registered_backends() -> list[dict[str, Any]]:
    with _LOCK:
        return [{"backend":a.name,"workloads":list(a.workloads)} for a in sorted(_ADAPTERS.values(),key=lambda x:x.name)]


def backend_available(name: str, workload: str = "*") -> bool:
    key=str(name or "").strip().lower(); work=str(workload or "*").lower()
    with _LOCK:
        a=_ADAPTERS.get(key)
    return bool(a and ("*" in a.workloads or work in a.workloads))


def execute(dispatch: dict[str, Any], *, backend: str, workload: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if str(dispatch.get("effective_mode") or "").upper() != "COOPERATIVE":
        raise ValueError("cooperative executor accepts COOPERATIVE dispatch only")
    if not bool(dispatch.get("execution_ready")):
        raise RuntimeError("dispatch is not execution_ready")
    assignments=list(dispatch.get("assignments") or [])
    if len(assignments) < 2:
        raise RuntimeError("cooperative execution requires at least two assignments")
    device_keys=[str(x.get("device_key") or "") for x in assignments]
    if not all(device_keys) or len(set(device_keys)) != len(device_keys):
        raise RuntimeError("cooperative assignments require distinct persistent device_key values")
    key=str(backend or "").strip().lower()
    with _LOCK:
        adapter=_ADAPTERS.get(key)
    if adapter is None:
        raise RuntimeError(f"cooperative backend adapter not registered: {key}")
    work=str(workload or "*").lower()
    if "*" not in adapter.workloads and work not in adapter.workloads:
        raise RuntimeError(f"backend {key} does not declare workload {work}")
    context={
        "schema":"phoenix.forge.cooperative-execution-context/v1",
        "execution_id":dispatch.get("execution_id"),
        "backend":key,
        "workload":work,
        "assignments":assignments,
        "device_keys":device_keys,
        "payload":dict(payload or {}),
        "policy":{
            "no_shell_execution_from_api":True,
            "adapter_must_be_registered_in_process":True,
            "device_identity_uses_persistent_device_key":True,
            "leases_are_owned_by_scheduler_execution_policy":True,
        },
    }
    result=adapter.execute(context)
    if not isinstance(result,dict):
        raise TypeError("cooperative backend adapter must return dict")
    return {
        "schema":"phoenix.forge.cooperative-execution-result/v1",
        "status":str(result.get("status") or "UNKNOWN").upper(),
        "execution_id":dispatch.get("execution_id"),
        "backend":key,
        "workload":work,
        "device_keys":device_keys,
        "backend_result":result,
    }


def capabilities() -> dict[str, Any]:
    adapters=registered_backends()
    return {
        "schema":SCHEMA,
        "status":"READY" if adapters else "RUNTIME_DEPENDENT",
        "registered_backends":adapters,
        "backend_count":len(adapters),
        "policy":{
            "no_arbitrary_executable_path":True,
            "no_shell_execution_from_api":True,
            "in_process_adapter_registration_only":True,
            "persistent_device_identity_required":True,
            "multiple_assignments_required":True,
            "runtime_backend_adapter_required":True,
        },
    }
