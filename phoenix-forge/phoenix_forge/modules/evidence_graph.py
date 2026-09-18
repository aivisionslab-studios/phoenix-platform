from __future__ import annotations

import hashlib
import json
import time
from typing import Any

SCHEMA = "phoenix.forge.hardware-evidence-graph/v1"

_CONF = {"NONE":0.0,"LOW":0.35,"MEDIUM":0.65,"HIGH":0.9,"PROVEN":1.0}

def _stable_id(kind:str, path:str)->str:
    return f"{kind}-" + hashlib.sha256(path.encode("utf-8","replace")).hexdigest()[:16]

def _is_evidence(v:Any)->bool:
    return isinstance(v,dict) and {"value","available","provider","confidence"}.issubset(v.keys())

def build(inspector:dict[str,Any])->dict[str,Any]:
    nodes=[]; edges=[]; conflicts=[]; providers={}
    seen_values:dict[str,list[tuple[str,Any,float]]]={}

    def walk(obj:Any,path:str="root"):
        if _is_evidence(obj):
            provider=str(obj.get("provider") or "UNKNOWN")
            conf=str(obj.get("confidence") or "NONE").upper()
            score=_CONF.get(conf,0.0)
            nid=_stable_id("evidence",path)
            value=obj.get("value")
            node={"id":nid,"kind":"EVIDENCE","path":path,"available":bool(obj.get("available")),"provider":provider,"confidence":conf,"confidence_score":score,"value":value,"note":obj.get("note")}
            nodes.append(node); providers[provider]=providers.get(provider,0)+1
            canonical=path.split(".")[-1]
            if node["available"] and isinstance(value,(str,int,float,bool)):
                seen_values.setdefault(canonical,[]).append((nid,value,score))
            if isinstance(value,(dict,list)): walk(value,path+".value")
            return
        if isinstance(obj,dict):
            for k,v in obj.items(): walk(v,f"{path}.{k}")
        elif isinstance(obj,list):
            for i,v in enumerate(obj): walk(v,f"{path}[{i}]")
    walk(inspector)

    for field,vals in seen_values.items():
        distinct={json.dumps(v,sort_keys=True,default=str) for _,v,_ in vals}
        if len(distinct)>1 and len(vals)>1:
            conflicts.append({"field":field,"status":"CONFLICT","evidence_ids":[x[0] for x in vals],"values":[x[1] for x in vals],"policy":"do_not_silently_merge"})
            for a in vals:
                for b in vals:
                    if a[0] < b[0]: edges.append({"from":a[0],"to":b[0],"relation":"CONFLICTS_WITH"})

    available=sum(1 for n in nodes if n["available"])
    high=sum(1 for n in nodes if n["available"] and n["confidence_score"]>=0.9)
    return {"schema":SCHEMA,"generated_at":time.time(),"status":"COMPLETE" if nodes else "EMPTY","summary":{"evidence_nodes":len(nodes),"available_nodes":available,"high_confidence_nodes":high,"conflicts":len(conflicts),"providers":providers},"nodes":nodes,"edges":edges,"conflicts":conflicts,"invariants":{"conflicts_are_visible":True,"missing_is_unknown_not_failure":True,"provider_and_confidence_are_preserved":True,"no_silent_source_overwrite":True}}
