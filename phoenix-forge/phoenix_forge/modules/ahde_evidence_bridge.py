from __future__ import annotations
import json,time
from pathlib import Path
from typing import Any
SCHEMA='phoenix.forge.ahde-evidence/v1'
STATE=Path.home()/'.phoenix_forge'/'ahde_evidence.json'
STALE_AFTER_S=15.0

def _write(obj:dict[str,Any])->None:
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(STATE)

def ingest(payload:dict[str,Any])->dict[str,Any]:
    now=time.time(); devices=payload.get('devices') if isinstance(payload,dict) else None
    if not isinstance(devices,list): raise ValueError('AHDE payload requires devices[]')
    cleaned=[]; metrics=[]
    for di,d in enumerate(devices):
        if not isinstance(d,dict): continue
        dev={'name':str(d.get('name') or f'Device {di}'),'type':str(d.get('type') or 'Unknown'),'category':str(d.get('category') or 'unknown'),'sensors':[]}
        for si,s in enumerate(d.get('sensors') or []):
            if not isinstance(s,dict): continue
            value=s.get('value'); unit=str(s.get('unit') or ''); typ=str(s.get('type') or 'Status'); name=str(s.get('name') or f'Sensor {si}')
            available=value not in (None,'','indisponível','N/D','UNKNOWN')
            ambiguous_zero=bool(available and isinstance(value,(int,float)) and float(value)==0.0 and 'power' in typ.lower() and not s.get('provider'))
            sensor={'id':str(s.get('id') or f'{di}:{si}:{name}'),'name':name,'type':typ,'value':value,'unit':unit,'updatedAt':s.get('updatedAt'),'available':available,'quality':'AMBIGUOUS_ZERO' if ambiguous_zero else ('AVAILABLE' if available else 'UNKNOWN'),'provider':str(s.get('provider') or 'Phoenix AHDE/provider chain')}
            dev['sensors'].append(sensor)
            metrics.append({'device':dev['name'],'category':dev['category'],'name':name,'semantic_type':typ,'value':value,'unit':unit,'available':available,'quality':sensor['quality'],'provider':'Phoenix AHDE/provider chain','confidence':'LOW' if ambiguous_zero else ('MEDIUM' if available else 'NONE'),'timestamp':s.get('updatedAt') or now})
        cleaned.append(dev)
    state={'schema':SCHEMA,'received_at':now,'source':'Phoenix Engine AHDE','devices':cleaned,'metrics':metrics,'policy':{'zero_is_not_missing_by_default':True,'zero_power_without_provider_is_ambiguous':True,'missing_is_unknown_not_zero':True}}
    _write(state)
    return {'ok':True,'schema':SCHEMA,'received_at':now,'devices':len(cleaned),'metrics':len(metrics)}

def latest()->dict[str,Any]:
    try: data=json.loads(STATE.read_text(encoding='utf-8'))
    except Exception: return {'schema':SCHEMA,'status':'EMPTY','available':False,'stale':True,'metrics':[]}
    age=max(0.0,time.time()-float(data.get('received_at') or 0))
    data['age_s']=age; data['stale']=age>STALE_AFTER_S; data['available']=True; data['status']='STALE' if data['stale'] else 'LIVE'
    return data

def status()->dict[str,Any]:
    d=latest(); return {'schema':SCHEMA,'status':d.get('status'),'available':d.get('available',False),'stale':d.get('stale',True),'age_s':d.get('age_s'),'metrics':len(d.get('metrics') or [])}
