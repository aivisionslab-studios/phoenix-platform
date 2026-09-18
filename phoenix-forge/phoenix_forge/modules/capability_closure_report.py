from __future__ import annotations

from typing import Any
from phoenix_forge.modules import capability_registry, windows_evidence_promotion

SCHEMA = "phoenix.forge.capability-closure-report/v3"
BASE_IMPLEMENTABLE_MISSING = 4
IMPLEMENTABLE_TARGETS = {
    "memory.xmp_expo",
    "gpu.intel.vendor_deep",
    "pcie.affinity.gpu_numa",
    "storage.nvme.pcie_mapping",
}


def build() -> dict[str, Any]:
    reg = capability_registry.build()
    caps = reg.get("capabilities") or []
    windows_overlay = windows_evidence_promotion.current_promotions()
    summary: dict[str, int] = {}
    false_claims = 0
    unknown_coerced = 0
    hw_verified = 0
    synthetic_verified = 0
    windows_verified = 0
    hw_unverified = 0
    still_missing = []
    for row in caps:
        status = str(row.get("status") or "UNKNOWN")
        summary[status] = summary.get(status, 0) + 1
        cid = str(row.get("id") or "")
        if cid in IMPLEMENTABLE_TARGETS and status == "MISSING":
            still_missing.append(cid)
        vs = str(windows_overlay.get(cid) or row.get("verification_status") or "").upper()
        # Verification axes are intentionally separate:
        # VERIFIED_SYNTHETIC is never counted as real hardware verification.
        if vs == "VERIFIED_SYNTHETIC":
            synthetic_verified += 1
        elif vs in {"WINDOWS_VERIFIED", "VERIFIED_ON_WINDOWS"}:
            windows_verified += 1
        elif vs in {
            "VERIFIED_ON_REAL_HARDWARE",
            "HARDWARE_VERIFIED",
            "VERIFIED_REAL_HARDWARE",
        }:
            hw_verified += 1
        elif status == "COMPLETE":
            hw_unverified += 1
        if status == "COMPLETE" and not row.get("source_contract"):
            false_claims += 1
    all_missing = sorted(str(row.get("id") or "") for row in caps if str(row.get("status") or "") == "MISSING")
    planned_missing = sorted(str(row.get("id") or "") for row in caps if str(row.get("status") or "") == "MISSING" and str(row.get("roadmap") or "") == "PLANNED")
    return {
        "schema": SCHEMA,
        "release_train": "0.25.0rc6.post15 Release Integrity + Shadow Hygiene Consolidation",
        "current_gate": "0.25-privileged-provider",
        "implementable_missing_before": BASE_IMPLEMENTABLE_MISSING,
        "implementable_missing_after": len(still_missing),
        "remaining_implementable_missing": still_missing,
        "legacy_gate_scope": sorted(IMPLEMENTABLE_TARGETS),
        "all_missing_count": len(all_missing),
        "all_missing_ids": all_missing,
        "planned_missing_count": len(planned_missing),
        "planned_missing_ids": planned_missing,
        "zero_missing_globally": len(all_missing) == 0,
        "summary": summary,
        "false_claims_detected": false_claims,
        "unknown_coerced": unknown_coerced,
        "hardware_verified": hw_verified,
        "synthetic_verified": synthetic_verified,
        "windows_verified": windows_verified,
        "hardware_unverified": hw_unverified,
        "decision_influence": "DISABLED",
        "policy": {
            "complete_does_not_imply_hardware_verified": True,
            "unknown_is_not_guessed": True,
            "decision_engine_enabled": False,
            "windows_evidence_overlay_count": len(windows_overlay),
        },
    }


def to_text(report: dict[str, Any] | None = None) -> str:
    r = report or build()
    s = r.get("summary") or {}
    return "\n".join([
        "============================================================",
        "PHOENIX FORGE — CAPABILITY CLOSURE REPORT",
        "============================================================",
        f"Legacy Gate 24A-24D MISSING before: {r['implementable_missing_before']}",
        f"Legacy Gate 24A-24D MISSING after:  {r['implementable_missing_after']}",
        f"All MISSING capabilities:            {r.get('all_missing_count', 0)}",
        f"Planned MISSING capabilities:        {r.get('planned_missing_count', 0)}",
        "",
        f"COMPLETE:                {s.get('COMPLETE', 0)}",
        f"PARTIAL:                 {s.get('PARTIAL', 0)}",
        f"RUNTIME_DEPENDENT:       {s.get('RUNTIME_DEPENDENT', 0)}",
        f"EXTERNAL_REQUIRED:       {s.get('EXTERNAL_REQUIRED', 0)}",
        f"IMPOSSIBLE_GENERICALLY:  {s.get('IMPOSSIBLE_GENERICALLY', 0)}",
        f"MISSING:                 {s.get('MISSING', 0)}",
        "",
        f"False claims detected:   {r['false_claims_detected']}",
        f"Unknown coerced:         {r['unknown_coerced']}",
        f"Hardware verified:       {r['hardware_verified']}",
        f"Synthetic verified:      {r['synthetic_verified']}",
        f"Windows verified:        {r['windows_verified']}",
        f"Hardware unverified:     {r['hardware_unverified']}",
        "",
        "Decision influence:",
        str(r['decision_influence']),
        "============================================================",
    ])
