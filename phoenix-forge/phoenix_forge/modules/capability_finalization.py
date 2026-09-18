from __future__ import annotations

from collections import Counter
from typing import Any
from phoenix_forge.modules import capability_registry, readiness_model

SCHEMA = "phoenix.forge.capability-finalization/v1"
VALID_STATES = {"COMPLETE","PARTIAL","RUNTIME_DEPENDENT","EXTERNAL_REQUIRED","IMPOSSIBLE_GENERICALLY","MISSING"}
VALID_ROADMAP = {"NONE","PLANNED","IN_PROGRESS","BLOCKED"}
REQUIRED_FIELDS = {"id","domain","status","roadmap","phase","dependency_class","verification_state","verification_status","source_contract","evidence_contract","test_contract","confidence_policy","limitation"}

def audit(machine_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    reg = capability_registry.build()
    caps = reg.get("capabilities") or []
    violations: list[dict[str, Any]] = []
    ids: set[str] = set()
    for c in caps:
        cid = str(c.get("id") or "")
        if not cid:
            violations.append({"id":None,"kind":"MISSING_ID"})
            continue
        if cid in ids:
            violations.append({"id":cid,"kind":"DUPLICATE_ID"})
        ids.add(cid)
        missing = sorted(REQUIRED_FIELDS - set(c))
        if missing:
            violations.append({"id":cid,"kind":"MISSING_FIELDS","fields":missing})
        if c.get("status") not in VALID_STATES:
            violations.append({"id":cid,"kind":"INVALID_STATUS","value":c.get("status")})
        if c.get("roadmap") not in VALID_ROADMAP:
            violations.append({"id":cid,"kind":"INVALID_ROADMAP","value":c.get("roadmap")})
        if c.get("status") == "MISSING" and c.get("roadmap") == "NONE":
            violations.append({"id":cid,"kind":"UNCLASSIFIED_MISSING","message":"MISSING must have an explicit roadmap or be reclassified."})
        if c.get("status") == "COMPLETE" and not c.get("provider"):
            violations.append({"id":cid,"kind":"COMPLETE_WITHOUT_PROVIDER"})

    capability_first = [c for c in caps if c.get("phase") != "FUTURE_EXECUTION"]
    future = [c for c in caps if c.get("phase") == "FUTURE_EXECUTION"]
    unresolved = [c for c in capability_first if c.get("status") == "MISSING"]
    external = [c for c in capability_first if c.get("status") == "EXTERNAL_REQUIRED"]
    impossible = [c for c in capability_first if c.get("status") == "IMPOSSIBLE_GENERICALLY"]
    runtime = [c for c in capability_first if c.get("status") == "RUNTIME_DEPENDENT"]
    readiness = readiness_model.build(machine_evidence)
    counts = Counter(c.get("status") for c in capability_first)

    return {
        "schema": SCHEMA,
        "status": "PASS" if not violations else "FAIL",
        "registry_schema": reg.get("schema"),
        "capability_first_total": len(capability_first),
        "state_counts": dict(counts),
        "classification_violations": violations,
        "unresolved_implementable": [c.get("id") for c in unresolved],
        "external_required": [c.get("id") for c in external],
        "impossible_generically": [c.get("id") for c in impossible],
        "runtime_dependent": [c.get("id") for c in runtime],
        "future_execution": [c.get("id") for c in future],
        "implementation_coverage_percent": readiness["hardware_capability_matrix"]["implementation_coverage_percent"],
        "verification_coverage_percent": readiness["hardware_capability_matrix"]["verification_coverage_percent"],
        "gate": {
            "classification_closed": not violations,
            "ready_for_public_ui_completion": not violations,
            "ready_for_decision_engine": (not violations and not unresolved and readiness["hardware_capability_matrix"]["verification_coverage_percent"] >= 95.0),
            "decision_engine_block_reasons": (["UNRESOLVED_IMPLEMENTABLE_CAPABILITIES"] if unresolved else []) + (["HARDWARE_VERIFICATION_BELOW_95_PERCENT"] if readiness["hardware_capability_matrix"]["verification_coverage_percent"] < 95.0 else []),
        },
        "policy": {
            "missing_is_never_silently_reclassified_complete": True,
            "runtime_dependent_is_not_missing": True,
            "external_required_is_resolved_classification_not_implementation": True,
            "impossible_generically_is_resolved_classification_not_implementation": True,
            "future_execution_is_excluded_from_capability_first_gate": True,
            "decision_engine_remains_frozen": True,
        },
    }
