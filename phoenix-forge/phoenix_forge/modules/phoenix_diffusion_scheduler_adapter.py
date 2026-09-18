from __future__ import annotations

from typing import Any

SCHEMA = "phoenix.forge.phoenix-diffusion-scheduler-adapter/v1"


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "READY",
        "backend": "phoenix-diffusion",
        "supported_dispatch_modes": ["CPU", "SINGLE"],
        "parallel_batch_planning": True,
        "parallel_batch_execution": False,
        "cooperative_execution": False,
        "device_selection": {
            "identity": "device_key",
            "runtime_selector": "device_index",
            "explicit_nonzero_device_index": "BACKEND_DEPENDENT",
        },
        "policies": {
            "forge_safety_precedes_diffusion": True,
            "cpu_dispatch_forces_cpu_backend": True,
            "gpu_dispatch_authorizes_phoenix_diffusion_internal_placement": True,
            "scheduler_does_not_replace_diffusion_memory_planner": True,
            "cooperative_not_claimed": True,
        },
    }


def scheduler_context(dispatch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(dispatch, dict) or not dispatch.get("execution_ready"):
        raise ValueError("dispatch Forge ausente ou não executável")
    mode = str(dispatch.get("effective_mode") or "CPU").upper()
    assignments = list(dispatch.get("assignments") or [])
    assignment = assignments[0] if assignments else {}
    if mode == "CPU":
        return {
            "target": "CPU",
            "execution_id": dispatch.get("execution_id"),
            "assignment_id": assignment.get("assignment_id"),
            "device_key": None,
            "device_index": None,
        }
    if mode == "SINGLE":
        if str(assignment.get("target") or "").upper() != "GPU":
            raise ValueError("dispatch SINGLE sem assignment GPU")
        return {
            "target": "GPU",
            "execution_id": dispatch.get("execution_id"),
            "assignment_id": assignment.get("assignment_id"),
            "device_key": assignment.get("device_key"),
            "device_index": assignment.get("device_index"),
        }
    raise ValueError(f"Phoenix Diffusion direct adapter não executa modo {mode}")
