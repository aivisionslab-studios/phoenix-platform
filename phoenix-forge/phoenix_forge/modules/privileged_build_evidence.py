from __future__ import annotations
import json
from pathlib import Path
from typing import Any

SCHEMA = "phoenix.forge.unsigned-driver-qualification-evidence/v1"

def _path() -> Path:
    return Path(__file__).resolve().parents[2] / "providers" / "phoenix_privileged_driver_windows" / "build_evidence" / "unsigned_build_qualification.json"

def read() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {
            "schema": SCHEMA,
            "status": "NOT_RUN",
            "evidence_present": False,
            "qualified": False,
            "runtime_promoted": False,
            "policy": {
                "unsigned_build_is_not_trusted_runtime": True,
                "driver_install_automatic": False,
                "service_start_automatic": False,
                "signing_bypass_allowed": False,
                "hardware_verified": False,
            },
        }
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {
            "schema": SCHEMA,
            "status": "EVIDENCE_INVALID",
            "evidence_present": True,
            "qualified": False,
            "runtime_promoted": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    status = str(data.get("status") or "UNKNOWN")
    return {
        "schema": SCHEMA,
        "status": status,
        "evidence_present": True,
        "qualified": status == "UNSIGNED_BUILD_QUALIFIED",
        "runtime_promoted": False,
        "build": data,
        "policy": {
            "unsigned_build_is_not_trusted_runtime": True,
            "driver_install_automatic": False,
            "service_start_automatic": False,
            "signing_bypass_allowed": False,
            "hardware_verified": False,
        },
    }
