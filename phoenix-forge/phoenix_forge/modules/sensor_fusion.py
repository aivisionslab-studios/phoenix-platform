from __future__ import annotations
import time
from typing import Any
from phoenix_forge.modules import pulse,ahde_evidence_bridge
SCHEMA='phoenix.forge.sensor-fusion/v2'

def _walk(obj:Any,prefix:str=''):
    if isinstance(obj,dict):
        for k,v in obj.items():
            p=f'{prefix}.{k}' if prefix else str(k)
            if isinstance(v,(dict,list)): yield from _walk(v,p)
            elif isinstance(v,(int,float)) and not isinstance(v,bool): yield p,float(v)
    elif isinstance(obj,list):
        for i,v in enumerate(obj): yield from _walk(v,f'{prefix}[{i}]')

def collect()->dict[str,Any]:
    raw=pulse.collect(); data=raw.model_dump() if hasattr(raw,'model_dump') else (raw if isinstance(raw,dict) else {})
    metrics=[{'path':p,'value':v,'provider':'Phoenix Pulse/vendor fallback','confidence':'MEDIUM','source':'FORGE_PULSE','available':True} for p,v in _walk(data)]
    ahde=ahde_evidence_bridge.latest()
    for m in ahde.get('metrics') or []:
        mm=dict(m); mm['source']='AHDE'; mm['path']=f"ahde.{m.get('category','unknown')}.{m.get('device','device')}.{m.get('name','metric')}"; metrics.append(mm)
    conflicts=[]
    # Conservative conflict detector: only compares identical semantic name + unit.
    by_key={}
    for i,m in enumerate(metrics):
        if not m.get('available'): continue
        key=(str(m.get('name') or m.get('path','').split('.')[-1]).lower(),str(m.get('unit') or '').lower())
        by_key.setdefault(key,[]).append((i,m))
    for key,items in by_key.items():
        vals=[]
        for _,m in items:
            v=m.get('value')
            if isinstance(v,(int,float)): vals.append(float(v))
        if len(vals)>=2 and max(vals)-min(vals)>max(1.0,0.20*max(abs(v) for v in vals)):
            conflicts.append({'metric':key[0],'unit':key[1],'status':'CONFLICT','sources':[m.get('source') for _,m in items],'values':[m.get('value') for _,m in items],'policy':'do_not_silently_merge'})
    status='COMPLETE' if metrics else 'PARTIAL'
    if ahde.get('status')=='STALE': status='DEGRADED'
    return {'schema':SCHEMA,'generated_at':time.time(),'status':status,'metrics':metrics,'conflicts':conflicts,'ahde':{'status':ahde.get('status'),'age_s':ahde.get('age_s'),'metrics':len(ahde.get('metrics') or [])},'summary':{'numeric_or_live_metrics':len(metrics),'conflicts':len(conflicts)},'policy':{'cross_provider_conflicts_visible':True,'missing_sensor_is_unknown':True,'zero_is_not_missing_by_default':True,'ambiguous_zero_is_not_authoritative':True,'semantic_equivalence_required_for_conflict':True},'raw':{'forge_pulse':data}}
