from __future__ import annotations

from pathlib import Path
from typing import Any

SCHEMA = "phoenix.forge.privileged-driver-source/v2"

def source_status() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / "providers" / "phoenix_privileged_driver_windows"
    required = [
        "driver.c",
        "phoenix_privileged_abi.h",
        "PhoenixForgePrivileged.inf",
        "WDK_PREFLIGHT.ps1",
        "BUILD_WDK.ps1",
        "DIAGNOSE_WDK.ps1",
        "QUALIFY_UNSIGNED_DRIVER.ps1",
        "PhoenixForgePrivileged.vcxproj",
        "phoenix_driver_trust_policy.json",
        "README.md",
    ]
    present = {name: (root / name).exists() for name in required}
    return {
        "schema": SCHEMA,
        "status": "SOURCE_FOUNDATION_READY" if all(present.values()) else "SOURCE_FOUNDATION_INCOMPLETE",
        "files": present,
        "driver_binary_bundled": any(root.glob("*.sys")),
        "catalog_bundled": any(root.glob("*.cat")),
        "signing_material_bundled": any(root.glob("*.pfx")) or any(root.glob("*.pvk")),
        "runtime_status": "EXTERNAL_REQUIRED",
        "policy": {
            "read_only": True,
            "capability_bits_advertised": 1,
            "privileged_reads_implemented": True,
            "aperf_mperf_source_implemented": True,
            "reference_mhz_source_implemented": False,
            "arbitrary_msr_forbidden": True,
            "arbitrary_port_io_forbidden": True,
            "memory_mapping_forbidden": True,
            "writes_forbidden": True,
            "signed_driver_required_for_runtime": True,
            "secure_device_acl_required": True,
            "trusted_runtime_gate_required": True,
            "parallel_sampling_required_for_scalability": True,
            "vulnerable_third_party_drivers_forbidden": True,
            "missing_driver_is_not_hardware_failure": True,
            "decision_influence_enabled": False,
        },
    }
