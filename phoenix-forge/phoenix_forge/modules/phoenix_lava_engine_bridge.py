from __future__ import annotations
from typing import Any
from phoenix_forge.modules import phoenix_lava_model_registry as registry
from phoenix_forge.modules import phoenix_lava_artifact_qualification as aq
from phoenix_forge.modules import phoenix_lava_runtime_manager as runtime

SCHEMA="phoenix.forge.phoenix-lava-engine-bridge/v1"

def state(*,quantization='Q5_K_M',mode='AUTO',port=8082)->dict[str,Any]:
    models=registry.local_status(compute_sha256=False)
    artifact=aq.qualify(quantization,compute_sha256=False)
    rt=runtime.managed_status(port=port)
    admission=runtime.admission_plan(mode=mode,quantization=quantization,port=port)
    if artifact.get('status')=='MODEL_REQUIRED':
        overall='MODEL_REQUIRED'; next_action='DOWNLOAD_OR_IMPORT_MODEL'
    elif artifact.get('status')!='QUALIFIED':
        overall='ARTIFACT_NOT_QUALIFIED'; next_action='QUALIFY_MODEL_ARTIFACT'
    elif rt.get('status') in {'RUNNING','EXTERNAL_ONLINE'} and (rt.get('endpoint') or {}).get('status')=='ONLINE':
        overall='ONLINE'; next_action='BENCHMARK_OR_USE'
    elif admission.get('status')=='READY_FOR_RUNTIME_FIT':
        overall='READY_TO_START'; next_action='START_RUNTIME_EXPLICITLY'
    else:
        overall='BLOCKED'; next_action='REVIEW_BLOCKED_REASONS'
    return {"schema":SCHEMA,"status":overall,"quantization":quantization,"mode":mode,"model_registry":models,"artifact":artifact,"runtime":rt,"admission":admission,"next_action":next_action,"policy":{"read_only":True,"engine_may_observe_but_not_auto_download":True,"engine_may_observe_but_not_auto_start":True,"placement_owner":"Phoenix Llama Runtime"}}

def capabilities()->dict[str,Any]:
    return {"schema":SCHEMA,"status":"RUNTIME_DEPENDENT","features":["CONSOLIDATED_STATE","NEXT_ACTION","ARTIFACT_GATE","RUNTIME_STATUS","ADMISSION_STATUS"],"policy":{"read_only":True,"no_automatic_download":True,"no_automatic_start":True}}
