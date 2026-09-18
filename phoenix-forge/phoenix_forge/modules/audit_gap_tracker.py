from __future__ import annotations
import time
from typing import Any
from phoenix_forge.modules import capability_registry, privileged_provider_contracts

SCHEMA='phoenix.forge.audit-gap-tracker/v1'

def build()->dict[str,Any]:
    caps=capability_registry.build()['capabilities']
    contracts=privileged_provider_contracts.collect()['providers']
    gaps=[]
    for c in caps:
        if c['status'] not in {'COMPLETE','RUNTIME_DEPENDENT'}:
            gaps.append({'id':c['id'],'domain':c['domain'],'status':c['status'],'provider':c.get('provider'),'release':c.get('release')})
    return {'schema':SCHEMA,'generated_at':time.time(),'status':'OPEN_GAPS' if gaps else 'CLOSED','summary':{'open':len(gaps),'tracked':len(caps)},'gaps':gaps,
      'privileged_provider_state':contracts,'policy':{'partial_is_not_complete':True,'planned_is_not_implemented':True,'hardware_dependency_is_explicit':True}}
