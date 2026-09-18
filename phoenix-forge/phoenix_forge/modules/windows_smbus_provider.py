from __future__ import annotations

from typing import Any
from phoenix_forge.modules import provider_bridge

SCHEMA = "phoenix.forge.windows-smbus-provider/v1"
NAME = "phoenix-smbus-windows"

def status() -> dict[str, Any]:
    discovered = provider_bridge.discover()
    row = next((p for p in discovered.get("providers", []) if p.get("name") == NAME), None)
    probe = provider_bridge.probe(NAME, timeout_s=1.5) if row else {"status": "NOT_FOUND", "capabilities": []}
    caps = set(map(str, probe.get("capabilities") or []))
    meta = probe.get("metadata") or {}
    return {
        "schema": SCHEMA,
        "provider": NAME,
        "manifest_status": row.get("status") if row else "MISSING",
        "probe_status": probe.get("status"),
        "runtime_status": None,
        "driver_status": meta.get("driver_status", "MISSING"),
        "abi_version": meta.get("abi_version"),
        "capabilities": sorted(caps),
        "live_spd_ready": {"spd.enumerate", "spd.read"}.issubset(caps),
        "policy": {
            "kernel_driver_not_bundled": True,
            "read_only_capabilities_only": True,
            "missing_driver_is_not_failure": True,
            "no_direct_port_io_from_python": True,
        },
    }
