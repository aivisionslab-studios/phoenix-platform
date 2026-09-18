from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from phoenix_forge.modules import gpu_safety

SCHEMA = "phoenix.forge.gpu-identity-registry/v1"

def _path() -> Path:
    return gpu_safety.state_dir() / "gpu-identities.json"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def load() -> dict[str, Any]:
    p=_path()
    try:
        data=json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data,dict) and data.get("schema")==SCHEMA and isinstance(data.get("devices"),dict): return data
    except Exception: pass
    return {"schema":SCHEMA,"devices":{}}

def bind(device_key:str, label:str, *, evidence:dict[str,Any]|None=None, allow_rename:bool=False) -> dict[str, Any]:
    key=str(device_key or "").strip(); alias=str(label or "").strip()
    if not key: raise ValueError("device_key persistente é obrigatório")
    if not alias: raise ValueError("alias físico é obrigatório")
    data=load(); current=data["devices"].get(key,{})
    previous=str(current.get("physical_alias") or "").strip()
    if previous and previous != alias and not allow_rename:
        raise ValueError(f"Alias físico já confirmado para este device_key: {previous}")
    row={"device_key":key,"physical_alias":alias,"confirmed_by_user":True,"updated_at":_now(),"previous_alias":previous if previous and previous != alias else None,"evidence":evidence or current.get("evidence") or {}}
    data["devices"][key]=row
    p=_path(); p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(tmp,p)
    return row

def resolve(device_key:str) -> dict[str,Any]|None:
    return load().get("devices",{}).get(str(device_key or ""))

def status() -> dict[str,Any]:
    data=load(); return {"schema":SCHEMA,"count":len(data.get("devices",{})),"devices":list(data.get("devices",{}).values())}
