from __future__ import annotations
from collections import Counter
from typing import Any
from phoenix_forge.modules import capability_registry

SCHEMA="phoenix.forge.readiness-model/v1"
CAPABILITY_STATES={"COMPLETE","PARTIAL","RUNTIME_DEPENDENT","EXTERNAL_REQUIRED","IMPOSSIBLE_GENERICALLY","MISSING"}
ROADMAP_STATES={"NONE","PLANNED","IN_PROGRESS","BLOCKED"}
VERIFICATION_STATES={"BUILT","TESTED_SYNTHETIC","INSTALLED","RUNTIME_VERIFIED","HARDWARE_VERIFIED"}

RESOLVED_IMPLEMENTATION_STATES={"COMPLETE","PARTIAL","RUNTIME_DEPENDENT","EXTERNAL_REQUIRED","IMPOSSIBLE_GENERICALLY"}

def _implementation_resolved(cap:dict[str,Any])->bool:
    return cap.get("status") in RESOLVED_IMPLEMENTATION_STATES

def build(machine_evidence:dict[str,Any]|None=None)->dict[str,Any]:
    caps=capability_registry.build()["capabilities"]
    hardware=[c for c in caps if c.get("phase")!="FUTURE_EXECUTION"]
    future=[c for c in caps if c.get("phase")=="FUTURE_EXECUTION"]

    state_counts=Counter(c.get("status") for c in hardware)
    roadmap_counts=Counter(c.get("roadmap") for c in hardware)
    dependency_counts=Counter(c.get("dependency_class") for c in hardware)

    resolved=sum(1 for c in hardware if _implementation_resolved(c))
    impl_pct=round(100.0*resolved/len(hardware),1) if hardware else 100.0

    evidence=machine_evidence or {}
    verified_ids=set(evidence.get("hardware_verified_capability_ids") or [])
    runtime_ids=set(evidence.get("runtime_verified_capability_ids") or [])
    ver_count=sum(1 for c in hardware if c.get("id") in verified_ids or c.get("id") in runtime_ids)
    verification_pct=round(100.0*ver_count/len(hardware),1) if hardware else 100.0

    unresolved=[
      c for c in hardware
      if c.get("status")=="MISSING"
    ]
    return {
      "schema":SCHEMA,
      "definition_of_100_percent":"Every capability has a true, evidence-backed, technically defensible state; 100% does not require every capability to be COMPLETE.",
      "hardware_capability_matrix":{
        "total":len(hardware),
        "state_counts":dict(state_counts),
        "roadmap_counts":dict(roadmap_counts),
        "dependency_counts":dict(dependency_counts),
        "implementation_coverage_percent":impl_pct,
        "verification_coverage_percent":verification_pct,
        "unresolved_missing":len(unresolved),
      },
      "future_execution_roadmap":{
        "total":len(future),
        "items":[{"id":c.get("id"),"status":c.get("status"),"roadmap":c.get("roadmap")} for c in future],
        "excluded_from_capability_first_percentage":True,
      },
      "verification_model":{
        "states":["BUILT","TESTED_SYNTHETIC","INSTALLED","RUNTIME_VERIFIED","HARDWARE_VERIFIED"],
        "note":"Package self-tests prove TESTED_SYNTHETIC, not HARDWARE_VERIFIED. Hardware verification must come from runtime evidence."
      },
      "policy":{
        "capability_first":True,
        "future_execution_does_not_reduce_hardware_completion":True,
        "external_required_is_resolved_classification":True,
        "impossible_generically_is_resolved_classification":True,
        "runtime_dependent_can_be_fully_implemented":True,
      }
    }
