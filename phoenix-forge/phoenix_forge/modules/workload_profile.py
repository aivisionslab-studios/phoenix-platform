from __future__ import annotations
from typing import Any

SCHEMA = "phoenix.forge.workload-profile/v1"

def _i(v: Any) -> int:
    try: return max(0, int(v or 0))
    except Exception: return 0

def profile(*, workload: str="llm", model: str="*", model_size_mb: int=0, context_tokens: int=0, quantization: str|None=None, backend: str="vulkan", width: int=0, height: int=0, batch: int=1) -> dict[str,Any]:
    w=str(workload or "unknown").lower(); size=_i(model_size_mb); ctx=_i(context_tokens); batch=max(1,_i(batch) or 1)
    reasons=[]; quality=0.15; required_vram=None; required_ram=None
    if size:
        quality += .45; reasons.append("Model size is supplied as explicit evidence.")
    else:
        reasons.append("Model size is unknown; no model-name-only VRAM fit claim is made.")
    if w in {"llm","chat","text"}:
        if ctx: quality += .2
        else: reasons.append("Context length is unknown; KV-cache allowance cannot be fully estimated.")
        if size:
            kv = int(ctx * 0.10) if ctx else 512
            overhead=max(384,int(size*.08))
            required_vram=int(size*1.05)+kv+overhead
            required_ram=int(size*1.30)+max(2048,kv)
    elif w in {"image","diffusion"}:
        pixels=_i(width)*_i(height)
        if pixels: quality += .15
        if size:
            activation=max(1024,int((pixels or 512*512)/(512*512)*768))*batch
            required_vram=int(size*1.03)+activation+512
            required_ram=int(size*1.20)+2048
    elif size:
        required_vram=int(size*1.10)+512; required_ram=int(size*1.25)+2048
    return {
      "schema":SCHEMA,"status":"PROFILED" if size else "PARTIAL","workload":w,"model":model,"backend":backend,
      "inputs":{"model_size_mb":size or None,"context_tokens":ctx or None,"quantization":quantization,"width":_i(width) or None,"height":_i(height) or None,"batch":batch},
      "requirements":{"estimated_min_vram_mb":required_vram,"estimated_min_system_ram_mb":required_ram},
      "evidence_quality":round(min(1.0,quality),3),"reasons":reasons,
      "policy":{"model_name_alone_never_proves_fit":True,"estimates_are_advisory":True,"no_dispatch":True,"execution_enabled":False}
    }

def fit(profile_data:dict[str,Any], *, available_vram_mb:int=0, available_ram_mb:int=0)->dict[str,Any]:
    rv=(profile_data.get("requirements") or {}).get("estimated_min_vram_mb"); rr=(profile_data.get("requirements") or {}).get("estimated_min_system_ram_mb")
    def one(req,avail):
        if not req or not avail:return {"status":"UNKNOWN","required_mb":req,"available_mb":avail or None,"margin_mb":None}
        m=int(avail)-int(req);return {"status":"FIT" if m>=0 else "NO_FIT","required_mb":int(req),"available_mb":int(avail),"margin_mb":m}
    return {"schema":"phoenix.forge.model-fit/v1","gpu":one(rv,_i(available_vram_mb)),"system_ram":one(rr,_i(available_ram_mb)),"advisory_only":True}
