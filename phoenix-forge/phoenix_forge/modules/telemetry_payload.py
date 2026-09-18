from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import Any

import phoenix_forge
from phoenix_forge.modules import (
    telemetry_governance, telemetry_sanitizer, capability_registry,
    hardware_inspector, configuration_auditor, pcie_link_intelligence,
    nvme_deep_inspector, sensor_fusion, gpu_safety, workload_state,
)

SCHEMA = "phoenix.forge.telemetry-payload/v1"


def _safe_call(fn, default):
    try:
        return fn()
    except Exception as exc:
        return {"status":"UNAVAILABLE","error_class":type(exc).__name__} if isinstance(default, dict) else default


def build() -> dict[str, Any]:
    st = telemetry_governance.load()
    categories = st.get("categories") or telemetry_governance.DEFAULT_CATEGORIES
    raw: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "installation_id": st.get("installation_id"),
        "product": {
            "name": "Phoenix Forge",
            "version": phoenix_forge.__version__,
            "python": platform.python_version(),
            "platform": platform.system(),
            "platform_release": platform.release(),
        },
    }
    inspector = None
    if any(categories.get(x, False) for x in ("hardware_summary","topology","sensors","storage")):
        inspector = _safe_call(hardware_inspector.collect, {})
    if categories.get("hardware_summary"):
        raw["hardware_summary"] = inspector or {}
    if categories.get("topology"):
        raw["pcie"] = _safe_call(pcie_link_intelligence.collect, {})
    if categories.get("capabilities"):
        raw["capabilities"] = capability_registry.build()
    if categories.get("storage"):
        raw["storage"] = _safe_call(nvme_deep_inspector.collect, {})
    if categories.get("sensors"):
        raw["sensors"] = _safe_call(sensor_fusion.collect, {})
    if categories.get("diagnostics"):
        raw["configuration_audit"] = _safe_call(lambda: configuration_auditor.audit(inspector or hardware_inspector.collect()), {})
    if categories.get("reliability"):
        raw["gpu_safety"] = _safe_call(lambda: gpu_safety.status_for_detect(__import__('phoenix_forge.modules.detect', fromlist=['collect']).collect()), {})
        raw["workload_states"] = _safe_call(workload_state.status, {})
    # Benchmark details are intentionally not read from user prompts/outputs; only capability/state level here.
    if categories.get("benchmarks"):
        raw["benchmark_policy"] = {"collection":"summary_only","content_outputs":False}

    sanitized = telemetry_sanitizer.sanitize(raw, installation_id=str(st.get("installation_id") or "unknown"))
    violations = telemetry_sanitizer.assert_no_sensitive_keys(sanitized)
    return {
        "schema": SCHEMA,
        "consent_required": True,
        "sanitizer_schema": telemetry_sanitizer.SCHEMA,
        "policy_ok": not violations,
        "policy_violations": violations,
        "payload": sanitized,
    }
