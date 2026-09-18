from __future__ import annotations

import time
from typing import Any
from phoenix_forge.modules import provider_runtime, sensor_fusion, ahde_evidence_bridge

SCHEMA = "phoenix.forge.sensor-provider-inventory/v1"

def collect() -> dict[str, Any]:
    runtime = provider_runtime.health(max_age_s=30.0)
    fused = sensor_fusion.collect()
    ahde = ahde_evidence_bridge.status()
    rows=[]
    for p in runtime.get("providers") or []:
        probe=p.get("probe") or {}
        rows.append({
            "name": p.get("name"),
            "kind": p.get("kind"),
            "status": p.get("runtime_status") or probe.get("status") or p.get("status"),
            "capabilities": probe.get("capabilities") or p.get("capabilities") or [],
            "privilege": probe.get("privilege"),
        })
    return {
        "schema": SCHEMA,
        "generated_at": time.time(),
        "status": "OK",
        "ahde": {
            "status": ahde.get("status"),
            "available": ahde.get("available"),
            "stale": ahde.get("stale"),
            "metrics": ahde.get("metrics"),
        },
        "sensor_fusion_status": fused.get("status"),
        "providers": rows,
        "coverage": {
            "ahde_live": bool(ahde.get("available")),
            "vendor_deep_provider": any("sensor.vendor_deep" in set(map(str,r.get("capabilities") or [])) for r in rows),
            "electrical_provider": any("electrical.telemetry" in set(map(str,r.get("capabilities") or [])) for r in rows),
        },
        "invariants": {
            "missing_sensor_is_unknown_not_zero": True,
            "provider_absence_is_not_hardware_failure": True,
            "semantic_equivalence_required_for_conflict": True,
        },
    }
