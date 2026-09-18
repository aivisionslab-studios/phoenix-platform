from __future__ import annotations
from typing import Any
from phoenix_forge.modules import hardware_inspector,evidence_graph,capability_matrix,configuration_auditor,pcie_link_intelligence,capability_registry

SCHEMA="phoenix.forge.setup-intelligence/v2"

def analyze(detected=None)->dict[str,Any]:
    inspector=hardware_inspector.collect(detected)
    graph=evidence_graph.build(inspector)
    capability=capability_matrix.build(inspector)
    pcie=pcie_link_intelligence.collect(load_validated=False)
    audit=configuration_auditor.audit(inspector,graph,pcie)
    missing=inspector.get("missing_providers",[])
    conflicts=graph.get("conflicts",[])
    risks=[]
    if conflicts: risks.append({"severity":"MEDIUM","kind":"EVIDENCE_CONFLICT","count":len(conflicts),"action":"review_sources_before_automatic_decision"})
    if "raw_spd_smbus" in missing: risks.append({"severity":"INFO","kind":"SPD_LIVE_PROVIDER_MISSING","action":"keep_spd_fields_unknown"})
    if "native_cpu_runtime_clock" in missing: risks.append({"severity":"INFO","kind":"NATIVE_CLOCK_PROVIDER_PARTIAL","action":"do_not_claim_effective_clock_or_throttling"})
    items=capability.get("capabilities",[]) if isinstance(capability,dict) else []
    done=sum(1 for x in items if x.get("state")=="DONE"); partial=sum(1 for x in items if x.get("state")=="PARTIAL"); miss=sum(1 for x in items if x.get("state")=="MISSING")
    status = "BLOCKED_CONFIGURATION" if audit.get("status") == "BLOCKED" else ("READY_WITH_CONFLICTS" if conflicts else ("READY_WITH_ATTENTION" if audit.get("status") == "ATTENTION" else "READY"))
    return {"schema":SCHEMA,"status":status,"hardware_inspector":inspector,"evidence_graph":graph,"configuration_audit":audit,"pcie_link_intelligence":pcie,"capability_registry":capability_registry.build(),"capability_summary":{"done":done,"partial":partial,"missing":miss},"risks":risks,"decision_contract":{"never_invent_missing_data":True,"never_hide_source_conflicts":True,"prefer_high_confidence_native_evidence":True,"preserve_raw_provider_evidence":True}}
