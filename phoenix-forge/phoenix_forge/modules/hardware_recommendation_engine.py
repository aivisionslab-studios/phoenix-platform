from __future__ import annotations
import time
from typing import Any
from phoenix_forge.modules import hardware_inspector,evidence_graph,configuration_auditor,nvme_deep_inspector,pcie_link_intelligence

SCHEMA='phoenix.forge.hardware-recommendations/v1'

def build(detected=None)->dict[str,Any]:
    ins=hardware_inspector.collect(detected)
    graph=evidence_graph.build(ins)
    pcie=pcie_link_intelligence.collect(load_validated=False)
    audit=configuration_auditor.audit(ins,graph,pcie)
    nvme=nvme_deep_inspector.collect()
    rec=[]
    for f in audit.get('findings',[]):
        if f.get('severity') in {'CRITICAL','HIGH','MEDIUM'}:
            rec.append({'priority':f.get('severity'),'scope':f.get('scope'),'reason':f.get('kind'),'recommendation':f.get('recommendation'),'evidence':f.get('evidence',[])})
    if nvme.get('summary',{}).get('nvme_devices',0)==0 and nvme.get('status')!='UNAVAILABLE':
        rec.append({'priority':'INFO','scope':'STORAGE','reason':'NO_NVME_DETECTED','recommendation':'For large model/cache workloads, benchmark the fastest available storage path before changing placement.','evidence':[{'provider':'NVMe Deep Inspector'}]})
    order={'CRITICAL':4,'HIGH':3,'MEDIUM':2,'LOW':1,'INFO':0}
    rec.sort(key=lambda x:-order.get(x['priority'],0))
    return {'schema':SCHEMA,'generated_at':time.time(),'status':'ATTENTION' if any(r['priority'] in {'CRITICAL','HIGH','MEDIUM'} for r in rec) else 'OK',
      'recommendations':rec,'policy':{'recommendations_require_evidence':True,'no_purchase_recommendation_without_measured_need':True,'unknown_is_not_failure':True}}
