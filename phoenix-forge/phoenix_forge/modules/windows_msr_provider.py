from __future__ import annotations

from pathlib import Path
from typing import Any

from phoenix_forge.modules import provider_bridge, provider_runtime, privileged_driver_trust

SCHEMA = "phoenix.forge.windows-msr-provider/v1"
PROVIDER_NAME = "phoenix-msr-windows"
DRIVER_DEVICE = r"\\.\PhoenixForgeMsr"
ABI_VERSION = 1


def status() -> dict[str, Any]:
    discovered = provider_bridge.discover()
    row = next((x for x in discovered.get("providers", []) if x.get("name") == PROVIDER_NAME), None)
    probe = provider_bridge.probe(PROVIDER_NAME, timeout_s=2.0) if row and row.get("status") == "VERIFIED" else {"status": "NOT_INSTALLED"}
    health = provider_runtime.health(max_age_s=20.0)
    hrow = next((x for x in health.get("providers", []) if x.get("name") == PROVIDER_NAME), None)
    caps = set(map(str, (probe or {}).get("capabilities") or []))
    trust = privileged_driver_trust.probe()
    driver_status = ((probe or {}).get("metadata") or {}).get("driver_status") or ("READY" if "clock.aperf_mperf" in caps else "UNKNOWN")
    return {
        "schema": SCHEMA,
        "provider": PROVIDER_NAME,
        "abi_version": ABI_VERSION,
        "driver_device": DRIVER_DEVICE,
        "manifest_status": row.get("status") if row else "NOT_INSTALLED",
        "probe_status": probe.get("status"),
        "runtime_status": hrow.get("runtime_status") if isinstance(hrow, dict) else None,
        "driver_status": ("TRUSTED_READY" if trust.get("trusted_runtime_ready") else ("PRESENT_UNTRUSTED" if driver_status=="READY" else driver_status)),
        "trust": trust,
        "capabilities": sorted(caps),
        "effective_clock_ready": "clock.aperf_mperf" in caps and probe.get("status") == "READY" and bool(trust.get("trusted_runtime_ready")),
        "bclk_ready": "clock.bclk_multiplier" in caps and probe.get("status") == "READY" and bool(trust.get("trusted_runtime_ready")),
        "policy": {
            "kernel_driver_not_bundled": True,
            "vulnerable_third_party_drivers_not_used": True,
            "read_only_capabilities_only": True,
            "missing_driver_is_not_failure": True,
            "trusted_runtime_required_for_data_path": True,
        },
    }
