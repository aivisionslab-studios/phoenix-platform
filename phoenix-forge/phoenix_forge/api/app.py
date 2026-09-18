from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field
from pathlib import Path
import logging
import threading
import time
from phoenix_forge.modules import detect,pulse,forensics,crucible,memory,inspect,combined,watchdog,storage,gpu_safety,result_integrity,benchmark,benchmark_jobs,health,baseline,diagnostics,native_benchmark,system_inventory,archive_integrity,production_benchmark,gpu_ledger,delivery_guard,runtime_guard,execution_journal,quality_gate,fault_correlator,workload_state,hardware_inspector,capability_matrix,gpu_qualification,post_flash_qualification,compute_fabric,hardware_deep_inventory,cpu_runtime_telemetry,memory_spd,evidence_graph,setup_intelligence,configuration_auditor,pcie_link_intelligence,capability_registry,nvme_deep_inspector,sensor_fusion,privileged_provider_contracts,audit_gap_tracker,hardware_recommendation_engine,telemetry_governance,firestore_telemetry,snapshot_cache,provider_bridge,gpu_identity_registry,provider_runtime,provider_actions,msr_clock_intelligence,ahde_evidence_bridge,windows_msr_provider,cpu_vendor_deep,privileged_provider_contract,privileged_driver_source,privileged_runtime_handshake,privileged_build_evidence,privileged_driver_trust,privileged_wdk_diagnostics,project_hygiene,cooperative_executor,phoenix_lava_foundation_adapter,phoenix_lava_runtime_manager,phoenix_lava_model_registry,phoenix_lava_benchmark,phoenix_lava_artifact_qualification,phoenix_lava_engine_bridge,windows_evidence_promotion,multi_device_scheduler,scheduler_execution_policy,phoenix_diffusion_scheduler_adapter,runtime_feedback,windows_smbus_provider,sensor_provider_inventory,capability_completion,gpu_deep_telemetry,pcie_deep_inspection,readiness_model,sensor_intelligence_deep,cpu_deep_inspector,stress_correctness,capability_finalization,public_surface,vbios_dossier,release_candidate,decision_preview,workload_profile,model_discovery,runtime_observation_bridge,observation_correlation,calibration_cohorts,decision_shadow,shadow_outcome_tracking,shadow_reliability_scorecard,telemetry_retry_worker
from phoenix_forge.service import build_report

app=FastAPI(title='Phoenix Forge',version='0.25.0rc6.post15')
_guard_log=logging.getLogger('phoenix.forge.guard')
_detect_lock=threading.Lock()
_detect_cache:dict={"at":0.0,"value":None}
def _record_execution(result:dict,*,workload:str,runtime:str,model:str):
    """Persist observability without turning a successful inference into a failure."""
    try:
        execution_journal.record(result,workload=workload,runtime=runtime,model=model)
        recorded=True
    except Exception as exc:
        recorded=False
        _guard_log.exception('execution journal unavailable: %s',exc)
    failures=sorted({failure for item in result.get('trace',[]) for failure in (item.get('validation') or {}).get('failures',[])})
    _guard_log.info('decision id=%s workload=%s status=%s mode=%s deliver=%s failures=%s',
      result.get('execution_id'),workload,result.get('status'),result.get('effective_mode'),result.get('deliver'),','.join(failures) or '-')
    result['journal']={'recorded':recorded}
    result['quality_gate']=quality_gate.delivery_gate(result)
    try:result['workload_state']=workload_state.observe_execution(result,workload)
    except Exception as exc:_guard_log.exception('workload state unavailable: %s',exc)
    try:result['runtime_observation']=runtime_observation_bridge.observe_guard_result(result,runtime=runtime,workload=workload,model_id=model)
    except Exception as exc:_guard_log.exception('runtime observation unavailable: %s',exc)
def _detected(ttl_s:float=30.0):
    now=time.monotonic()
    cached=_detect_cache["value"]
    if cached is not None and now-float(_detect_cache["at"])<ttl_s:return cached
    with _detect_lock:
        now=time.monotonic();cached=_detect_cache["value"]
        if cached is None or now-float(_detect_cache["at"])>=ttl_s:
            cached=detect.collect();_detect_cache.update({"at":now,"value":cached})
        return cached
class TextValidationRequest(BaseModel):
    text:str|None=None;finish_reason:str|None=None;stream_completed:bool=True;process_exit_code:int|None=0
    expected_text:str|None=None;workload:str='llm';backend:str='vulkan';runtime:str='phoenix-llama-runtime';model:str='*'
    attempt:int=1;cpu_control_passed:bool=False
class ImageValidationRequest(BaseModel):
    path:str;prompt:str|None=None;expected_text:str|None=None;ocr_text:str|None=None;ocr_confidence:float|None=None
    vision_score:float|None=None;vision_verdict:str|None=None;blur_score:float|None=None;artifact_score:float|None=None
    workload:str='image';backend:str='vulkan';runtime:str='phoenix-diffusion';model:str='*';attempt:int=1;cpu_control_passed:bool=False
class BaselineRequest(BaseModel):
    benchmark:dict
class ArchiveRequest(BaseModel):
    path:str;max_member_gb:float=20;max_ratio:float=1000
class GpuQualificationRequest(BaseModel):
    device_label:str;phase:str;device_index:int=0;vbios_path:str|None=None;memory_clock_mhz:int|None=None;notes:str|None=None

class PostFlashQualificationRequest(BaseModel):
    device_label:str;device_index:int=0;profile:str='standard'
class DeliveryGuardRequest(BaseModel):
    kind:str;workload:str;gpu_outputs:list[dict]=Field(default_factory=list);cpu_output:dict|None=None
    backend:str='vulkan';runtime:str='*';model:str='*';device_name:str|None=None;execution_id:str|None=None
class GuardedChatRequest(BaseModel):
    gpu_url:str='http://127.0.0.1:8082/v1';cpu_url:str='http://127.0.0.1:8081/v1';model:str='local'
    messages:list[dict];device_name:str|None=None;max_tokens:int=512;temperature:float=.2;timeout_s:float=300
    validator_url:str|None=None;requested_mode:str='AUTO'
class GuardedImageRequest(BaseModel):
    gpu_url:str='http://127.0.0.1:7860';cpu_url:str='http://127.0.0.1:7861';prompt:str
    negative_prompt:str='';width:int=512;height:int=512;steps:int=20;timeout_s:float=1800
    device_name:str|None=None;ocr_url:str|None=None;vision_url:str|None=None;expected_text:str|None=None
    model:str='stable-diffusion';requested_mode:str='AUTO'
class TelemetryConsentRequest(BaseModel):
    accepted_notice_version:str
    categories:dict[str,bool]|None=None

class TelemetryDestinationRequest(BaseModel):
    project_id:str='setup-ia-local-rx580-vulkan'
    collection:str='forge_telemetry'
    auth_mode:str='AUTO'
    service_account_file:str|None=None
    enabled:bool=True

class DecisionPreviewRequest(BaseModel):
    workload:str='llm'; requested_mode:str='AUTO'; min_vram_mb:int=0; parallelizable:bool=False; task_count:int=1
    model:str='*'; model_size_mb:int=0; context_tokens:int=0; quantization:str|None=None; backend:str='vulkan'; width:int=0; height:int=0; batch:int=1; runtime_version:str|None=None; model_fingerprint:str|None=None; execution_id:str|None=None
class WorkloadProfileRequest(BaseModel):
    workload:str='llm'; model:str='*'; model_size_mb:int=0; context_tokens:int=0; quantization:str|None=None; backend:str='vulkan'; width:int=0; height:int=0; batch:int=1
class ModelCalibrationRequest(BaseModel):
    model_id:str; workload:str='llm'; observed_peak_vram_mb:int=0; observed_peak_ram_mb:int=0; context_tokens:int=0; width:int=0; height:int=0; backend:str='vulkan'; outcome:str='SUCCESS'
class RuntimeObservationRequest(BaseModel):
    runtime:str; workload:str='llm'; model_id:str='*'; backend:str='vulkan'; effective_mode:str='UNKNOWN'; outcome:str='SUCCESS'
    execution_id:str|None=None; assignment_id:str|None=None; device_key:str|None=None; driver_version:str|None=None; runtime_version:str|None=None; model_fingerprint:str|None=None; failure_class:str|None=None; fallback_reason:str|None=None
    duration_s:float|None=None; peak_vram_mb:int=0; peak_ram_mb:int=0; context_tokens:int=0; width:int=0; height:int=0; evidence_source:str='PHOENIX_RUNTIME'

class ProviderCallRequest(BaseModel):
    provider:str
    capability:str
    params:dict=Field(default_factory=dict)
    timeout_s:float=5.0

class SchedulerDispatchRequest(BaseModel):
    workload:str='llm'
    mode:str='AUTO'
    parallelizable:bool=False
    task_count:int=1
    min_vram_mb:int=0
    backend:str='generic'
    cooperative_executor_available:bool=False
    lease_ttl_s:float=300.0

class SchedulerResultRequest(BaseModel):
    execution_id:str
    assignment_id:str
    status:str
    failure_class:str|None=None
    detail:str|None=None
    release_leases:bool=True
    training_eligible:bool=True


class StressCorrectnessRequest(BaseModel):
    domain:str
    seconds:int=10
    mb:int=256
    passes:int=2
    device:int=0
    rounds:int=64
    directory:str|None=None
    full_scan:bool=False

class StressCorrectnessAnalyzeRequest(BaseModel):
    runs:list[dict]=Field(default_factory=list)

class SchedulerCancelRequest(BaseModel):
    execution_id:str
    reason:str='user_or_engine_cancel'


def _build_capability_matrix_snapshot():
    inspector=hardware_inspector.collect(_detected(300.0))
    return capability_matrix.build(inspector)

def _build_capability_completion_snapshot():
    return capability_completion.build()

def _build_memory_spd_snapshot():
    return memory_spd.collect()

@app.on_event('startup')
def _prewarm_nonblocking_snapshots():
    snapshot_cache.refresh_async('detect',lambda:_detected(300.0))
    snapshot_cache.refresh_async('gpu-safety',_build_gpu_safety_snapshot)
    snapshot_cache.refresh_async('system-report',_build_forge_report_snapshot)
    snapshot_cache.refresh_async('capability-matrix',_build_capability_matrix_snapshot)
    snapshot_cache.refresh_async('capability-completion',_build_capability_completion_snapshot)
    snapshot_cache.refresh_async('memory-spd',_build_memory_spd_snapshot)
    provider_runtime.refresh_async()
    try:
        telemetry_retry_worker.ensure_started()
    except Exception:
        _guard_log.exception('telemetry retry worker startup failed')

@app.get('/api/providers/status')
def api_provider_status():return provider_bridge.discover()

@app.get('/api/providers/probe/{name}')
def api_provider_probe(name:str):return provider_bridge.probe(name)

@app.get('/api/providers/health')
def api_provider_health():return provider_runtime.health()

@app.post('/api/providers/call')
def api_provider_call(req:ProviderCallRequest):
    return provider_actions.call(req.provider,req.capability,req.params,req.timeout_s)

@app.get('/api/providers/circuit-breakers')
def api_provider_circuit_breakers():
    return provider_actions.breaker_status()

@app.get('/api/hardware/msr-clock')
def api_hardware_msr_clock():
    return msr_clock_intelligence.collect()

@app.get('/api/providers/msr-windows/status')
def api_msr_windows_status():
    return windows_msr_provider.status()

@app.get('/api/scheduler/capabilities')
def api_scheduler_capabilities():
    return multi_device_scheduler.capabilities()

@app.get('/api/scheduler/plan')
def api_scheduler_plan(workload:str='llm',mode:str='AUTO',backend:str='generic',parallelizable:bool=False,min_vram_mb:int=0):
    return multi_device_scheduler.plan(_detected(),workload=workload,mode=mode,backend=backend,parallelizable=parallelizable,min_vram_bytes=max(0,int(min_vram_mb))*1024*1024)

@app.get('/api/scheduler/history')
def api_scheduler_history(limit:int=50):
    return multi_device_scheduler.history(limit)


@app.get('/api/scheduler/adapters/phoenix-diffusion')
def api_scheduler_phoenix_diffusion_adapter():
    return phoenix_diffusion_scheduler_adapter.capabilities()

@app.get('/api/scheduler/adapters/phoenix-lava')
def api_scheduler_phoenix_lava_adapter():
    return phoenix_lava_foundation_adapter.capabilities()

@app.get('/api/phoenix-lava/foundation')
def api_phoenix_lava_foundation():
    return {'capabilities':phoenix_lava_foundation_adapter.capabilities(),'discovery':phoenix_lava_foundation_adapter.discover()}

@app.get('/api/phoenix-lava/runtime-policy')
def api_phoenix_lava_runtime_policy(mode:str='AUTO',quantization:str='Q5_K_M',context_tokens:int=8192,threads:int=12,device:str='Vulkan0',port:int=8082):
    return phoenix_lava_foundation_adapter.runtime_policy(mode=mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,port=port)

@app.get('/api/phoenix-lava/runtime/discover')
def api_phoenix_lava_runtime_discover():
    return phoenix_lava_runtime_manager.discover_runtime()

@app.get('/api/phoenix-lava/runtime/launch-plan')
def api_phoenix_lava_launch_plan(mode:str='AUTO',quantization:str='Q5_K_M',context_tokens:int=8192,threads:int=12,device:str='Vulkan0',parallel:int=1,port:int=8082):
    return phoenix_lava_runtime_manager.launch_plan(mode=mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,parallel=parallel,port=port)

@app.get('/api/phoenix-lava/runtime/status')
def api_phoenix_lava_runtime_status(port:int=8082):
    return phoenix_lava_runtime_manager.endpoint_status(port=port)

@app.get('/api/phoenix-lava/models')
def api_phoenix_lava_models(compute_sha256:bool=False):
    return phoenix_lava_model_registry.local_status(compute_sha256=compute_sha256)

@app.get('/api/phoenix-lava/models/download-plan')
def api_phoenix_lava_download_plan(quantization:str='Q5_K_M'):
    return phoenix_lava_model_registry.download_plan(quantization)

@app.get('/api/phoenix-lava/runtime/managed-status')
def api_phoenix_lava_managed_status(port:int=8082):
    return phoenix_lava_runtime_manager.managed_status(port=port)

@app.get('/api/phoenix-lava/runtime/hardware-fit')
def api_phoenix_lava_hardware_fit(quantization:str='Q5_K_M',reserve_ram_gb:float=6.0):
    return phoenix_lava_runtime_manager.hardware_fit(quantization,reserve_ram_gb=reserve_ram_gb)

@app.get('/api/phoenix-lava/benchmark-plan')
def api_phoenix_lava_benchmark_plan(mode:str='AUTO',context_tokens:int=8192,threads:int=12,device:str='Vulkan0',port:int=8082):
    return phoenix_lava_runtime_manager.benchmark_plan(mode=mode,context_tokens=context_tokens,threads=threads,device=device,port=port)

@app.get('/api/phoenix-lava/benchmark/history')
def api_phoenix_lava_benchmark_history(limit:int=50):
    return phoenix_lava_benchmark.history(limit=limit)

@app.get('/api/phoenix-lava/benchmark/compare')
def api_phoenix_lava_benchmark_compare():
    return phoenix_lava_benchmark.compare_latest()

@app.post('/api/phoenix-lava/runtime/start')
def api_phoenix_lava_runtime_start(confirm:bool=False,mode:str='AUTO',quantization:str='Q5_K_M',context_tokens:int=8192,threads:int=12,device:str='Vulkan0',parallel:int=1,port:int=8082,wait_ready_seconds:float=0.0):
    return phoenix_lava_runtime_manager.start_runtime(confirm=confirm,mode=mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,parallel=parallel,port=port,wait_ready_seconds=wait_ready_seconds)

@app.post('/api/phoenix-lava/runtime/stop')
def api_phoenix_lava_runtime_stop(confirm:bool=False):
    return phoenix_lava_runtime_manager.stop_runtime(confirm=confirm)


@app.post('/api/phoenix-lava/models/download')
def api_phoenix_lava_download(quantization:str='Q5_K_M',confirm:bool=False,resume:bool=True):
    return phoenix_lava_model_registry.download(quantization,confirm=confirm,resume=resume)

@app.get('/api/phoenix-lava/models/source-probe')
def api_phoenix_lava_source_probe(quantization:str='Q5_K_M',timeout_s:float=10.0):
    return phoenix_lava_model_registry.source_probe(quantization,timeout_s=timeout_s)

@app.get('/api/phoenix-lava/models/verify')
def api_phoenix_lava_verify_model(quantization:str='Q5_K_M',compute_sha256:bool=True):
    return phoenix_lava_model_registry.verify_model(quantization,compute_sha256=compute_sha256)

@app.get('/api/phoenix-lava/models/partial-status')
def api_phoenix_lava_partial_status(quantization:str='Q5_K_M'):
    return phoenix_lava_model_registry.partial_status(quantization)

@app.post('/api/phoenix-lava/models/discard-partial')
def api_phoenix_lava_discard_partial(quantization:str='Q5_K_M',confirm:bool=False):
    return phoenix_lava_model_registry.discard_partial(quantization,confirm=confirm)

@app.get('/api/phoenix-lava/runtime/admission')
def api_phoenix_lava_admission(mode:str='AUTO',quantization:str='Q5_K_M',context_tokens:int=8192,threads:int=12,device:str='Vulkan0',port:int=8082):
    return phoenix_lava_runtime_manager.admission_plan(mode=mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,port=port)

@app.get('/api/phoenix-lava/runtime/log-tail')
def api_phoenix_lava_log_tail(lines:int=80):
    return phoenix_lava_runtime_manager.log_tail(lines=lines)

@app.post('/api/phoenix-lava/runtime/reconcile-state')
def api_phoenix_lava_reconcile_state(confirm:bool=False,port:int=8082):
    return phoenix_lava_runtime_manager.reconcile_state(confirm=confirm,port=port)

@app.post('/api/phoenix-lava/runtime/restart')
def api_phoenix_lava_runtime_restart(confirm:bool=False,mode:str='AUTO',quantization:str='Q5_K_M',context_tokens:int=8192,threads:int=12,device:str='Vulkan0',port:int=8082,wait_ready_seconds:float=180.0):
    return phoenix_lava_runtime_manager.restart_runtime(confirm=confirm,mode=mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,port=port,wait_ready_seconds=wait_ready_seconds)

@app.post('/api/phoenix-lava/benchmark/suite')
def api_phoenix_lava_benchmark_suite(quantization:str,confirm:bool=False,port:int=8082,max_tokens:int=96):
    return phoenix_lava_benchmark.benchmark_suite_current(quantization=quantization,confirm=confirm,port=port,max_tokens=max_tokens)


@app.get('/api/phoenix-lava/artifacts/qualification')
def api_phoenix_lava_artifact_qualification(quantization:str='Q5_K_M',compute_sha256:bool=True):
    return phoenix_lava_artifact_qualification.qualify(quantization,compute_sha256=compute_sha256)

@app.get('/api/phoenix-lava/artifacts/qualification-matrix')
def api_phoenix_lava_artifact_qualification_matrix(compute_sha256:bool=False):
    return phoenix_lava_artifact_qualification.matrix(compute_sha256=compute_sha256)

@app.get('/api/phoenix-lava/engine-state')
def api_phoenix_lava_engine_state(quantization:str='Q5_K_M',mode:str='AUTO',port:int=8082):
    return phoenix_lava_engine_bridge.state(quantization=quantization,mode=mode,port=port)

@app.get('/api/scheduler/feedback/status')
def api_scheduler_feedback_status():
    return runtime_feedback.status()

@app.get('/api/scheduler/feedback/profile')
def api_scheduler_feedback_profile(workload:str|None=None,backend:str|None=None,device_key:str|None=None,target:str|None=None,limit:int=500):
    return runtime_feedback.profile(workload=workload,backend=backend,device_key=device_key,target=target,limit=limit)

@app.get('/api/scheduler/execution/capabilities')
def api_scheduler_execution_capabilities():
    return scheduler_execution_policy.capabilities()

@app.get('/api/scheduler/execution/leases')
def api_scheduler_execution_leases():
    return scheduler_execution_policy.leases()

@app.get('/api/scheduler/execution/history')
def api_scheduler_execution_history(limit:int=100):
    return scheduler_execution_policy.history(limit)

@app.post('/api/scheduler/execution/dispatch')
def api_scheduler_execution_dispatch(req:SchedulerDispatchRequest):
    return scheduler_execution_policy.prepare_dispatch(
        _detected(),workload=req.workload,mode=req.mode,parallelizable=req.parallelizable,
        task_count=req.task_count,min_vram_bytes=max(0,int(req.min_vram_mb))*1024*1024,
        backend=req.backend,cooperative_executor_available=req.cooperative_executor_available,
        lease_ttl_s=req.lease_ttl_s,acquire_leases=True)

@app.post('/api/scheduler/execution/result')
def api_scheduler_execution_result(req:SchedulerResultRequest):
    return scheduler_execution_policy.record_result(req.execution_id,req.assignment_id,status=req.status,
        failure_class=req.failure_class,detail=req.detail,release_leases=req.release_leases,training_eligible=req.training_eligible)

@app.post('/api/scheduler/execution/cancel')
def api_scheduler_execution_cancel(req:SchedulerCancelRequest):
    return scheduler_execution_policy.cancel(req.execution_id,req.reason)

@app.get('/api/gpu-identities')
def api_gpu_identities():return gpu_identity_registry.status()

@app.get('/api/telemetry/privacy-notice')
def api_telemetry_privacy_notice():return telemetry_governance.privacy_notice()
@app.get('/api/telemetry/status')
def api_telemetry_status():return firestore_telemetry.status()
@app.get('/api/telemetry/destination')
def api_telemetry_destination():return firestore_telemetry.configuration(False)
@app.post('/api/telemetry/destination/configure')
def api_telemetry_destination_configure(req:TelemetryDestinationRequest):
    return firestore_telemetry.configure_destination(project_id=req.project_id,collection=req.collection,auth_mode=req.auth_mode,service_account_file=req.service_account_file,enabled=req.enabled)
@app.post('/api/telemetry/destination/test')
def api_telemetry_destination_test():return firestore_telemetry.test_destination()
@app.post('/api/telemetry/destination/test-write')
def api_telemetry_destination_test_write():return firestore_telemetry.test_write_destination()
@app.post("/api/telemetry/destination/test-write-visible")
def api_telemetry_destination_test_write_visible():return firestore_telemetry.test_write_visible()
@app.post('/api/telemetry/queue/clear')
def api_telemetry_queue_clear():return firestore_telemetry.clear_queue()
@app.post('/api/telemetry/queue/retry')
def api_telemetry_queue_retry():return firestore_telemetry.retry_queue()
@app.get('/api/telemetry/preview')
def api_telemetry_preview():return firestore_telemetry.preview_cached()
@app.post('/api/telemetry/consent')
def api_telemetry_consent(req:TelemetryConsentRequest):return telemetry_governance.consent(req.accepted_notice_version,req.categories)
@app.post('/api/telemetry/revoke')
def api_telemetry_revoke():return telemetry_governance.revoke()
@app.post('/api/telemetry/send')
def api_telemetry_send():return firestore_telemetry.send_now()

@app.get('/health')
def health_check():return {'ok':True,'product':'Phoenix Forge','version':'0.25.0rc6.post15','service':'alive'}
@app.get('/health/live')
def health_live():return health_check()
@app.get('/health/ready')
def health_ready():
    started=time.monotonic();d=_detected()
    return {'ok':True,'product':'Phoenix Forge','version':'0.25.0rc6.post15','service':'ready',
      'probe_duration_s':round(time.monotonic()-started,3),'gpu_safety':gpu_safety.status_for_detect(d)}
@app.post('/api/output/delivery-guard')
def api_delivery_guard(req:DeliveryGuardRequest):
    started=time.monotonic();lookup_started=started;d=_detected(300.0);lookup_s=time.monotonic()-lookup_started;gpu=d.gpus[0] if d.gpus else None
    result=delivery_guard.evaluate_sequence(kind=req.kind,workload=req.workload,gpu_outputs=req.gpu_outputs,
      cpu_output=req.cpu_output,backend=req.backend,runtime=req.runtime,model=req.model,
      device_name=req.device_name or (gpu.name if gpu else None),gpu=gpu,execution_id=req.execution_id)
    result['forge_timing']={'hardware_lookup_s':round(lookup_s,3),'total_s':round(time.monotonic()-started,3)}
    _record_execution(result,workload=req.workload,runtime=req.runtime,model=req.model)
    return result
@app.post('/api/runtime/guarded-chat')
def api_guarded_chat(req:GuardedChatRequest):
    started=time.monotonic();lookup_started=started;d=_detected(300.0);lookup_s=time.monotonic()-lookup_started;gpu=d.gpus[0] if d.gpus else None
    result=runtime_guard.guarded_chat(gpu_url=req.gpu_url,cpu_url=req.cpu_url,model=req.model,
      messages=req.messages,device_name=req.device_name or (gpu.name if gpu else None),gpu=gpu,
      max_tokens=req.max_tokens,temperature=req.temperature,timeout_s=req.timeout_s,
      validator_url=req.validator_url,user_mode=req.requested_mode)
    result['forge_timing']={'hardware_lookup_s':round(lookup_s,3),'total_s':round(time.monotonic()-started,3)}
    _record_execution(result,workload='llm',runtime='llama.cpp-openai',model=req.model)
    return result
@app.post('/api/runtime/guarded-image')
def api_guarded_image(req:GuardedImageRequest):
    started=time.monotonic();lookup_started=started;d=_detected(300.0);lookup_s=time.monotonic()-lookup_started;gpu=d.gpus[0] if d.gpus else None
    result=runtime_guard.guarded_image(gpu_url=req.gpu_url,cpu_url=req.cpu_url,prompt=req.prompt,
      device_name=req.device_name or (gpu.name if gpu else None),gpu=gpu,negative_prompt=req.negative_prompt,
      width=req.width,height=req.height,steps=req.steps,timeout_s=req.timeout_s,ocr_url=req.ocr_url,
      vision_url=req.vision_url,expected_text=req.expected_text,model=req.model,user_mode=req.requested_mode)
    result['forge_timing']={'hardware_lookup_s':round(lookup_s,3),'total_s':round(time.monotonic()-started,3)}
    _record_execution(result,workload='image',runtime='stable-diffusion-api',model=req.model)
    return result
@app.get('/api/executions/recent')
def api_recent_executions(limit:int=20):return execution_journal.recent(limit)
def _build_gpu_safety_snapshot():
    d=_detected(300.0)
    return gpu_safety.status_for_detect(d)

@app.get('/api/gpu-safety')
def api_gpu_safety(workload:str|None=None,backend:str='vulkan',runtime:str='*',model:str='*'):
    if workload or backend!='vulkan' or runtime!='*' or model!='*':
        # scoped decisions are still cheap once detection cache is warm; fail-safe if it is not.
        snap=snapshot_cache.get('detect',lambda:_detected(300.0),max_age_s=300.0,wait_first_s=0.15)
        d=snap.get('value')
        if d is None:
            return {'schema':'phoenix.forge.gpu-safety/v2','status':'WARMING','snapshot':snap['snapshot'],'authorization':{'state':'UNKNOWN','effective_mode':'CPU','reason':'hardware_snapshot_warming'}}
        out=gpu_safety.status_for_detect(d,workload=workload,backend=backend,runtime=runtime,model=model);out['snapshot']=snap['snapshot'];return out
    snap=snapshot_cache.get('gpu-safety',_build_gpu_safety_snapshot,max_age_s=30.0,wait_first_s=0.15)
    if snap.get('value') is None:
        return {'schema':'phoenix.forge.gpu-safety/v2','status':'WARMING','snapshot':snap['snapshot'],'authorization':{'state':'UNKNOWN','effective_mode':'CPU','reason':'gpu_safety_snapshot_warming'}}
    out=snap['value'];out['snapshot']=snap['snapshot'];return out
@app.get('/api/autopilot')
def api_autopilot(workload:str='llm',backend:str='vulkan',runtime:str='*',model:str='*'):return build_report(workload=workload,backend=backend,runtime=runtime,model=model).autopilot
@app.post('/api/gpu-faults/report')
def api_gpu_fault_report(kind:str,message:str,workload:str='llm',backend:str='vulkan',runtime:str='*',model:str='*',cpu_control_passed:bool=True,reproduced:bool=True):
    d=detect.collect();gpu=d.gpus[0] if d.gpus else None
    return gpu_safety.record_external_fault(kind,message,gpu=gpu,workload=workload,backend=backend,runtime=runtime,model=model,cpu_control_passed=cpu_control_passed,reproduced=reproduced)
@app.post('/api/output/validate-text')
def api_validate_text(req:TextValidationRequest):
    validation=result_integrity.validate_text(req.text,finish_reason=req.finish_reason,stream_completed=req.stream_completed,process_exit_code=req.process_exit_code,expected_text=req.expected_text)
    d=detect.collect();gpu=d.gpus[0] if d.gpus else None
    return result_integrity.evaluate_and_record(validation,workload=req.workload,backend=req.backend,runtime=req.runtime,model=req.model,attempt=req.attempt,cpu_control_passed=req.cpu_control_passed,gpu=gpu)
@app.post('/api/output/validate-image')
def api_validate_image(req:ImageValidationRequest):
    validation=result_integrity.validate_image(req.path,prompt=req.prompt,expected_text=req.expected_text,ocr_text=req.ocr_text,ocr_confidence=req.ocr_confidence,vision_score=req.vision_score,vision_verdict=req.vision_verdict,blur_score=req.blur_score,artifact_score=req.artifact_score)
    d=detect.collect();gpu=d.gpus[0] if d.gpus else None
    return result_integrity.evaluate_and_record(validation,workload=req.workload,backend=req.backend,runtime=req.runtime,model=req.model,attempt=req.attempt,cpu_control_passed=req.cpu_control_passed,gpu=gpu)
@app.post('/api/benchmark/run')
def api_benchmark_run(profile:str='quick',include_gpu:bool=False,cpu_temp_limit:float=90,gpu_temp_limit:float=90):
    return benchmark.suite(profile,include_gpu,{'cpu_temperature':cpu_temp_limit,'gpu_temperature':gpu_temp_limit})
@app.post('/api/benchmark/jobs')
def api_benchmark_job_start(profile:str='quick',include_gpu:bool=False,confirm_gpu_risk:bool=False,cpu_temp_limit:float=90,gpu_temp_limit:float=90):return benchmark_jobs.start(profile=profile,include_gpu=include_gpu,confirm_gpu_risk=confirm_gpu_risk,cpu_temp_limit=cpu_temp_limit,gpu_temp_limit=gpu_temp_limit)
@app.get('/api/benchmark/jobs/{job_id}')
def api_benchmark_job_status(job_id:str):return benchmark_jobs.status(job_id)
@app.post('/api/benchmark/jobs/{job_id}/cancel')
def api_benchmark_job_cancel(job_id:str):return benchmark_jobs.cancel(job_id)
@app.get('/api/benchmark/history')
def api_benchmark_history(limit:int=20):return benchmark_jobs.recent(limit)
@app.get('/api/quality-gate/benchmark/{job_id}')
def api_benchmark_quality_gate(job_id:str):
    job=benchmark_jobs.status(job_id)
    if not job.get('result'):return {'schema':'phoenix.forge.quality-gate/v1','status':'PENDING','passed':False,'reasons':['BENCHMARK_NOT_FINISHED']}
    return quality_gate.benchmark_gate(job['result'],job.get('health'))
@app.get('/api/gpu-faults/correlation')
def api_gpu_fault_correlation(device_name:str|None=None,limit:int=100):return fault_correlator.analyze(device_name,limit)
@app.get('/api/workloads/states')
def api_workload_states():return workload_state.status()
@app.get('/api/compute-fabric')
def api_compute_fabric():
    d=_detected()
    return compute_fabric.build(d)
@app.get('/api/compute-fabric/placement')
def api_compute_fabric_placement(workload:str='llm'):
    d=_detected()
    return compute_fabric.placement_candidates(d,workload=workload)
def _build_forge_report_snapshot():
    d=_detected(300.0);safety=gpu_safety.status_for_detect(d);base=baseline.read(d);history=benchmark_jobs.recent(20)
    last=history.get('entries',[])[-1] if history.get('entries') else None
    inspector=hardware_inspector.collect(d)
    matrix=capability_matrix.build(inspector)
    return {'schema':'phoenix.forge.system-report/v65','generated_at':time.time(),'status':'reported','forge':{'product':'Phoenix Forge','version':'0.25.0rc6.post15','service':'alive'},'hardware':d.model_dump(),'compute_fabric':compute_fabric.build(d),'hardware_inspector':inspector,'capability_matrix':matrix,'parity_matrix':matrix,'configuration_audit':configuration_auditor.audit(inspector,evidence_graph.build(inspector)),'pcie_link_intelligence':pcie_link_intelligence.collect(),'nvme_deep':nvme_deep_inspector.collect(),'storage_deep':nvme_deep_inspector.collect(),'readiness_model':readiness_model.build(),'sensor_fusion':sensor_fusion.collect(),'sensor_intelligence_deep':sensor_intelligence_deep.capability_summary(),'cpu_deep':cpu_deep_inspector.collect(samples=3,interval_ms=100),'cpu_vendor_deep':cpu_vendor_deep.collect(),'privileged_provider_contract':privileged_provider_contract.provider_requirements(),'privileged_driver_source':privileged_driver_source.source_status(),'privileged_wdk_diagnostics':privileged_wdk_diagnostics.collect(),'msr_clock_intelligence':msr_clock_intelligence.collect(),'msr_provider_windows':windows_msr_provider.status(),'smbus_provider_windows':windows_smbus_provider.status(),'sensor_provider_inventory':sensor_provider_inventory.collect(),'gpu_deep_telemetry':gpu_deep_telemetry.collect(),'pcie_deep_inspection':pcie_deep_inspection.collect(),'capability_completion':capability_completion.build(),'capability_finalization':capability_finalization.audit(),'audit_gaps':audit_gap_tracker.build(),'gpu_qualification':gpu_qualification.history(limit=20),'gpu_identities':gpu_identity_registry.status(),'gpu_safety':safety,'benchmark_history':history,'executions':execution_journal.recent(20),'quality_gate':last.get('quality_gate') if last else None,'fault_correlation':fault_correlator.analyze(limit=100),'workload_states':workload_state.status(),'scheduler':multi_device_scheduler.capabilities(),'scheduler_execution':scheduler_execution_policy.capabilities(),'scheduler_runtime_feedback':runtime_feedback.status(),'phoenix_diffusion_scheduler_adapter':phoenix_diffusion_scheduler_adapter.capabilities(),'phoenix_lava_foundation_adapter':phoenix_lava_foundation_adapter.capabilities(),'phoenix_lava_runtime_manager':phoenix_lava_runtime_manager.capabilities(),'phoenix_lava_model_registry':phoenix_lava_model_registry.capabilities(),'phoenix_lava_benchmark':phoenix_lava_benchmark.capabilities(),'phoenix_lava_artifact_qualification':phoenix_lava_artifact_qualification.capabilities(),'phoenix_lava_engine_bridge':phoenix_lava_engine_bridge.capabilities(),'stress_correctness':stress_correctness.capabilities(),'public_surface':public_surface.build(),'vbios_dossier':vbios_dossier.capabilities(),'release_candidate':release_candidate.audit(route_paths={getattr(r,'path',None) for r in app.routes}),'project_hygiene':project_hygiene.capabilities(),'decision_preview':decision_preview.capabilities(),'decision_shadow':decision_shadow.capabilities(),'shadow_outcomes':shadow_outcome_tracking.capabilities(),'shadow_reliability':shadow_reliability_scorecard.capabilities(),'workload_profile':workload_profile.profile(),'model_discovery':model_discovery.discover(max_files=200),'runtime_observations':runtime_observation_bridge.status(),'observation_correlation':observation_correlation.correlate(limit=500),'calibration_cohorts':calibration_cohorts.cohorts(limit=500),'baseline':{'available':base is not None,'created_at':base.get('created_at') if base else None,'fingerprint':base.get('fingerprint') if base else None,'immutable':bool(base and base.get('immutable'))}}

@app.get('/api/report')
def api_forge_report():
    snap=snapshot_cache.get('system-report',_build_forge_report_snapshot,max_age_s=45.0,wait_first_s=0.25)
    if snap.get('value') is None:
        return {'schema':'phoenix.forge.system-report/v65','generated_at':time.time(),'status':'WARMING','partial':True,'forge':{'product':'Phoenix Forge','version':'0.25.0rc6.post15','service':'alive'},'snapshot':snap['snapshot'],'message':'Coleta profunda em segundo plano; o Forge permanece online.'}
    report=snap['value'];report['snapshot']=snap['snapshot'];report['partial']=False;return report

@app.get('/api/snapshots/status')
def api_snapshot_status():return snapshot_cache.status()

@app.post('/api/snapshots/refresh')
def api_snapshot_refresh():
    snapshot_cache.refresh_async('gpu-safety',_build_gpu_safety_snapshot)
    snapshot_cache.refresh_async('system-report',_build_forge_report_snapshot)
    snapshot_cache.refresh_async('capability-matrix',_build_capability_matrix_snapshot)
    snapshot_cache.refresh_async('capability-completion',_build_capability_completion_snapshot)
    provider_runtime.refresh_async()
    try:
        telemetry_retry_worker.ensure_started()
    except Exception:
        _guard_log.exception('telemetry retry worker startup failed')
    return {'ok':True,'status':'REFRESH_STARTED','snapshots':snapshot_cache.status()}

@app.get('/api/hardware/inspect')
def api_hardware_inspect():return hardware_inspector.collect(_detected())
@app.get('/api/hardware/cpu-native')
def api_cpu_native():
    return hardware_deep_inventory.collect(_detected()).get('cpu',{}).get('cpuid_deep',{})

@app.get('/api/hardware/cpu-runtime')
def api_cpu_runtime(samples:int=5,interval_ms:int=200):
    return cpu_runtime_telemetry.collect(samples=samples,interval_ms=interval_ms)

@app.get('/api/hardware/cpu-deep')
def api_cpu_deep(samples:int=5,interval_ms:int=200):
    return cpu_deep_inspector.collect(samples=samples,interval_ms=interval_ms)

@app.get('/api/hardware/cpu-vendor-deep')
def api_cpu_vendor_deep():
    return cpu_vendor_deep.collect()

@app.get('/api/hardware/cpu-vendor-deep/capabilities')
def api_cpu_vendor_deep_capabilities():
    return cpu_vendor_deep.capabilities()

@app.get('/api/providers/privileged-contract')
def api_privileged_provider_contract():
    return privileged_provider_contract.capability_catalog()

@app.get('/api/providers/privileged-contract/requirements')
def api_privileged_provider_requirements():
    return privileged_provider_contract.provider_requirements()

@app.get('/api/providers/privileged-driver-source')
def api_privileged_driver_source():
    return privileged_driver_source.source_status()

@app.get('/api/providers/privileged-runtime-handshake')
def api_privileged_runtime_handshake():
    return privileged_runtime_handshake.probe()

@app.get('/api/providers/privileged-build-evidence')
def api_privileged_build_evidence():
    return privileged_build_evidence.read()

@app.get('/api/providers/privileged-driver-trust')
def api_privileged_driver_trust():
    return privileged_driver_trust.probe()


@app.get('/api/evidence/windows-ledger')
def api_windows_evidence_ledger():
    return windows_evidence_promotion.status()

@app.get('/api/evidence/capability-map')
def api_capability_evidence_map():
    return windows_evidence_promotion.evidence_map()
@app.get('/api/providers/privileged-wdk-diagnostics')
def api_privileged_wdk_diagnostics():
    return privileged_wdk_diagnostics.collect()

@app.get('/api/project-hygiene')
def api_project_hygiene():
    return project_hygiene.capabilities()

@app.get('/api/project-hygiene/audit')
def api_project_hygiene_audit(max_files:int=25000):
    return project_hygiene.audit_release_tree(max_files=max_files)

@app.get('/api/scheduler/cooperative-executor/capabilities')
def api_cooperative_executor_capabilities():
    return cooperative_executor.capabilities()

@app.get('/api/hardware/memory-spd')
def api_memory_spd():
    snap=snapshot_cache.get('memory-spd',_build_memory_spd_snapshot,max_age_s=120.0,wait_first_s=0.25)
    if snap.get('value') is None:
        return {
            'schema':'phoenix.forge.memory-spd/v4',
            'status':'WARMING',
            'partial':True,
            'snapshot':snap['snapshot'],
            'message':'SPD/SMBus collection continues in background; no memory failure is inferred.'
        }
    return snap['value']


@app.get('/api/hardware/memory-spd/provider')
def api_memory_spd_provider():
    return windows_smbus_provider.status()

@app.get('/api/hardware/sensor-intelligence/capabilities')
def api_sensor_intelligence_capabilities():return sensor_intelligence_deep.capability_summary()

@app.post('/api/hardware/sensor-intelligence/analyze')
def api_sensor_intelligence_analyze(payload:dict):return sensor_intelligence_deep.analyze(
    payload.get("readings") or [],
    now=payload.get("now"),
    stale_after_s=float(payload.get("stale_after_s",15.0)),
    previous_keys=payload.get("previous_keys") or []
)

@app.get('/api/hardware/sensor-providers')
def api_sensor_providers():
    return sensor_provider_inventory.collect()

@app.get('/api/hardware/pcie-deep-inspection')
def api_pcie_deep_inspection():return pcie_deep_inspection.collect()

@app.get('/api/hardware/gpu-deep-telemetry')
def api_gpu_deep_telemetry():return gpu_deep_telemetry.collect()

@app.get('/api/readiness')
def api_readiness():return readiness_model.build()

@app.get('/api/capability-completion')
def api_capability_completion():
    snap=snapshot_cache.get('capability-completion',_build_capability_completion_snapshot,max_age_s=60.0,wait_first_s=0.25)
    if snap.get('value') is None:
        return {
            'schema':'phoenix.forge.capability-completion/v6',
            'status':'WARMING',
            'partial':True,
            'snapshot':snap['snapshot'],
            'message':'Capability Completion deep collection is running in background.'
        }
    out=snap['value']
    out['snapshot']=snap['snapshot']
    out['partial']=False
    return out


@app.get('/api/hardware/evidence-graph')
def api_hardware_evidence_graph():
    return evidence_graph.build(hardware_inspector.collect(_detected()))

@app.get('/api/hardware/setup-intelligence')
def api_hardware_setup_intelligence():
    return setup_intelligence.analyze(_detected())

@app.get('/api/hardware/configuration-audit')
def api_hardware_configuration_audit():
    inspector=hardware_inspector.collect(_detected())
    graph=evidence_graph.build(inspector)
    return configuration_auditor.audit(inspector,graph)

@app.get('/api/hardware/pcie-link')
def api_hardware_pcie_link(load_validated:bool=False):
    return pcie_link_intelligence.collect(load_validated=load_validated)

@app.get('/api/hardware/deep-inspect')
def api_hardware_deep_inspect():
    d=_detected()
    return hardware_deep_inventory.collect(d,d.compute_fabric)
@app.get('/api/capability-matrix')
def api_capability_matrix():
    snap=snapshot_cache.get('capability-matrix',_build_capability_matrix_snapshot,max_age_s=60.0,wait_first_s=0.25)
    if snap.get('value') is None:
        return {
            'schema':'phoenix.forge.capability-matrix/v34',
            'status':'WARMING',
            'partial':True,
            'snapshot':snap['snapshot'],
            'message':'Capability Matrix deep collection is running in background.'
        }
    out=snap['value']
    out['snapshot']=snap['snapshot']
    out['partial']=False
    return out

@app.get('/api/parity-matrix', include_in_schema=False)
def api_legacy_parity_matrix():
    # Legacy compatibility alias; public API uses /api/capability-matrix.
    return api_capability_matrix()

@app.get('/api/capabilities')
def api_capabilities():return capability_registry.build()

@app.get('/api/public-surface')
def api_public_surface():return public_surface.build()
@app.get('/api/release-candidate')
def release_candidate_status():
    paths={getattr(r,'path',None) for r in app.routes}
    return release_candidate.audit(route_paths=paths)

@app.get('/api/decision-preview/capabilities')
def api_decision_preview_capabilities():return decision_preview.capabilities()
@app.get('/api/decision-preview/shadow-capabilities')
def api_decision_shadow_capabilities():return decision_shadow.capabilities()
@app.get('/api/decision-preview/shadow-outcomes/capabilities')
def api_shadow_outcome_capabilities():return shadow_outcome_tracking.capabilities()
@app.get('/api/decision-preview/shadow-outcomes')
def api_shadow_outcome_history(execution_id:str|None=None,model_id:str|None=None,limit:int=500):return shadow_outcome_tracking.history(execution_id=execution_id,model_id=model_id,limit=limit)
@app.get('/api/decision-preview/shadow-validation')
def api_shadow_validation(execution_id:str|None=None,model_id:str|None=None,limit:int=1000):return shadow_outcome_tracking.validate(execution_id=execution_id,model_id=model_id,limit=limit)

@app.get('/api/decision-preview/shadow-reliability/capabilities')
def api_shadow_reliability_capabilities():return shadow_reliability_scorecard.capabilities()
@app.get('/api/decision-preview/shadow-reliability')
def api_shadow_reliability(model_id:str|None=None,limit:int=5000):return shadow_reliability_scorecard.build(model_id=model_id,limit=limit)

@app.post('/api/decision-preview')
def api_decision_preview(req:DecisionPreviewRequest):
    return decision_preview.preview(workload=req.workload,requested_mode=req.requested_mode,min_vram_mb=req.min_vram_mb,parallelizable=req.parallelizable,task_count=req.task_count,model=req.model,model_size_mb=req.model_size_mb,context_tokens=req.context_tokens,quantization=req.quantization,backend=req.backend,width=req.width,height=req.height,batch=req.batch,runtime_version=req.runtime_version,model_fingerprint=req.model_fingerprint,execution_id=req.execution_id)


@app.post('/api/workload-profile')
def api_workload_profile(req:WorkloadProfileRequest):
    return workload_profile.profile(workload=req.workload,model=req.model,model_size_mb=req.model_size_mb,context_tokens=req.context_tokens,quantization=req.quantization,backend=req.backend,width=req.width,height=req.height,batch=req.batch)

@app.get('/api/models/discover')
def api_models_discover(include_paths:bool=False,max_files:int=500):
    return model_discovery.discover(include_paths=include_paths,max_files=max_files)

@app.get('/api/models/calibration')
def api_models_calibration(model_id:str|None=None,limit:int=100):
    return model_discovery.calibration_history(model_id=model_id,limit=limit)

@app.post('/api/models/calibration')
def api_models_calibration_record(req:ModelCalibrationRequest):
    return model_discovery.record_calibration(model_id=req.model_id,workload=req.workload,observed_peak_vram_mb=req.observed_peak_vram_mb,observed_peak_ram_mb=req.observed_peak_ram_mb,context_tokens=req.context_tokens,width=req.width,height=req.height,backend=req.backend,outcome=req.outcome)

@app.get('/api/runtime-observations/capabilities')
def api_runtime_observation_capabilities():return runtime_observation_bridge.capabilities()
@app.get('/api/runtime-observations/status')
def api_runtime_observation_status():return runtime_observation_bridge.status()
@app.get('/api/runtime-observations')
def api_runtime_observation_history(runtime:str|None=None,model_id:str|None=None,limit:int=100):return runtime_observation_bridge.history(runtime=runtime,model_id=model_id,limit=limit)
@app.get('/api/runtime-observations/correlation')
def api_runtime_observation_correlation(model_id:str|None=None,runtime:str|None=None,limit:int=2000):
    return observation_correlation.correlate(model_id=model_id,runtime=runtime,limit=limit)
@app.get('/api/calibration-confidence')
def api_calibration_confidence(model_id:str,workload:str|None=None,backend:str|None=None,effective_mode:str|None=None,device_key:str|None=None,driver_version:str|None=None,runtime_version:str|None=None,model_fingerprint:str|None=None,context_tokens:int=0,width:int=0,height:int=0):
    return observation_correlation.confidence(model_id=model_id,workload=workload,backend=backend,effective_mode=effective_mode,device_key=device_key,driver_version=driver_version,runtime_version=runtime_version,model_fingerprint=model_fingerprint,context_tokens=context_tokens,width=width,height=height)
@app.get('/api/calibration-cohorts')
def api_calibration_cohorts(model_id:str|None=None,runtime:str|None=None,limit:int=3000):
    return calibration_cohorts.cohorts(model_id=model_id,runtime=runtime,limit=limit)
@app.get('/api/calibration-aging')
def api_calibration_aging(model_id:str,workload:str|None=None,backend:str|None=None,effective_mode:str|None=None,device_key:str|None=None,driver_version:str|None=None,runtime_version:str|None=None,model_fingerprint:str|None=None,context_tokens:int=0,width:int=0,height:int=0):
    return calibration_cohorts.evaluate(model_id=model_id,workload=workload,backend=backend,effective_mode=effective_mode,device_key=device_key,driver_version=driver_version,runtime_version=runtime_version,model_fingerprint=model_fingerprint,context_tokens=context_tokens,width=width,height=height)
@app.post('/api/runtime-observations')
def api_runtime_observation_record(req:RuntimeObservationRequest):
    return runtime_observation_bridge.record(runtime=req.runtime,workload=req.workload,model_id=req.model_id,backend=req.backend,effective_mode=req.effective_mode,outcome=req.outcome,execution_id=req.execution_id,assignment_id=req.assignment_id,device_key=req.device_key,driver_version=req.driver_version,runtime_version=req.runtime_version,model_fingerprint=req.model_fingerprint,failure_class=req.failure_class,fallback_reason=req.fallback_reason,duration_s=req.duration_s,peak_vram_mb=req.peak_vram_mb,peak_ram_mb=req.peak_ram_mb,context_tokens=req.context_tokens,width=req.width,height=req.height,evidence_source=req.evidence_source)

@app.get('/api/vbios-dossier/capabilities')
def api_vbios_dossier_capabilities():return vbios_dossier.capabilities()
@app.get('/api/vbios-dossier/inventory')
def api_vbios_dossier_inventory():return vbios_dossier.inventory()
@app.get('/api/vbios-dossier/analyze')
def api_vbios_dossier_analyze(path:str):return vbios_dossier.analyze(path)
@app.post('/api/vbios-dossier/capture')
def api_vbios_dossier_capture(req:GpuQualificationRequest):return vbios_dossier.capture(device_label=req.device_label,phase=req.phase,device_index=req.device_index,vbios_path=req.vbios_path,memory_clock_mhz=req.memory_clock_mhz,notes=req.notes)
@app.get('/api/vbios-dossier/history')
def api_vbios_dossier_history(device_key:str|None=None,limit:int=50):return vbios_dossier.history(device_key,limit)
@app.get('/api/vbios-dossier/compare/{device_key}')
def api_vbios_dossier_compare(device_key:str):return vbios_dossier.compare(device_key)
@app.get('/api/vbios-dossier/qualification/plan')
def api_vbios_dossier_plan(device_label:str,device_index:int=0,profile:str='standard'):return vbios_dossier.qualification_plan(device_label,device_index,profile)
@app.post('/api/vbios-dossier/qualification/run')
def api_vbios_dossier_run(req:PostFlashQualificationRequest):return vbios_dossier.qualification_run(req.device_label,req.device_index,req.profile)
@app.post('/api/vbios-dossier/dump-amd')
def api_vbios_dossier_dump_amd(adapter:int=0,out_path:str='reports/vbios_adapter0.rom'):return vbios_dossier.dump_amd_read_only(adapter,out_path)

@app.get('/api/capability-finalization')
def api_capability_finalization():return capability_finalization.audit()
@app.get('/api/hardware/storage-deep')
def api_storage_deep():return nvme_deep_inspector.collect()

@app.get('/api/hardware/nvme-deep')
def api_nvme_deep():return nvme_deep_inspector.collect()
@app.get('/api/hardware/sensor-fusion')
def api_sensor_fusion():return sensor_fusion.collect()

@app.post('/api/evidence/ahde')
def api_evidence_ahde(payload:dict):return ahde_evidence_bridge.ingest(payload)
@app.get('/api/evidence/ahde/status')
def api_evidence_ahde_status():return ahde_evidence_bridge.status()
@app.get('/api/hardware/provider-contracts')
def api_provider_contracts():return privileged_provider_contracts.collect()
@app.get('/api/audit/gaps')
def api_audit_gaps():return audit_gap_tracker.build()
@app.get('/api/hardware/recommendations')
def api_hardware_recommendations():return hardware_recommendation_engine.build(_detected())
@app.post('/api/gpu-qualification/capture')
def api_gpu_qualification_capture(req:GpuQualificationRequest):
    d=_detected(0);gpu=d.gpus[req.device_index] if 0<=req.device_index<len(d.gpus) else None
    if gpu is None:raise ValueError('GPU index not found')
    return gpu_qualification.capture(gpu=gpu,device_label=req.device_label,phase=req.phase,vbios_path=req.vbios_path,memory_clock_mhz=req.memory_clock_mhz,notes=req.notes)
@app.get('/api/gpu-qualification/history')
def api_gpu_qualification_history(device_key:str|None=None,limit:int=50):return gpu_qualification.history(device_key,limit)
@app.get('/api/gpu-qualification/compare/{device_key}')
def api_gpu_qualification_compare(device_key:str):return gpu_qualification.compare(device_key)
@app.get('/api/gpu-qualification/post-flash/plan')
def api_post_flash_plan(device_label:str,device_index:int=0,profile:str='standard'):return post_flash_qualification.plan(device_label,device_index,profile)
@app.post('/api/gpu-qualification/post-flash/run')
def api_post_flash_run(req:PostFlashQualificationRequest):return post_flash_qualification.run(req.device_label,req.device_index,req.profile)
@app.get('/api/gpu-qualification/post-flash/history')
def api_post_flash_history(device_key:str|None=None,limit:int=50):return post_flash_qualification.history(device_key,limit)
@app.post('/api/benchmark/native')
def api_native_benchmark(kind:str='cpu',seconds:int=3,threads:int=0,mb:int=256,passes:int=5,accesses:int=2_000_000,device:int=0):
    return native_benchmark.execute(kind,seconds,threads,mb,passes,accesses,device=device)
@app.post('/api/benchmark/production')
def api_production_benchmark(profile:str='standard'):return production_benchmark.run(profile)
@app.get('/api/system-inventory')
def api_system_inventory():return system_inventory.collect()
@app.get('/api/pcie-health')
def api_pcie_health(minutes:int=1440,max_events:int=200):return system_inventory.pcie_health(minutes,max_events)
@app.post('/api/archive/check')
def api_archive_check(req:ArchiveRequest):return archive_integrity.inspect_zip(req.path,int(req.max_member_gb*1024**3),req.max_ratio)
@app.get('/api/gpu-ledger')
def api_gpu_ledger(device_name:str|None=None):return gpu_ledger.summarize(device_name)
@app.post('/api/gpu-ledger/ingest')
def api_gpu_ledger_ingest(path:str,device_name:str|None=None):return gpu_ledger.ingest_report(path,device_name)
@app.get('/api/route')
def api_route(workload:str,device_name:str|None=None,mode:str='AUTO',backend:str='vulkan',runtime:str='*',model:str='*'):return gpu_ledger.route(workload,device_name=device_name,user_mode=mode,backend=backend,runtime=runtime,model=model)
@app.get('/api/storage-health')
def api_storage_health():return storage.health_inventory()
@app.post('/api/machine-health')
def api_machine_health(req:BaselineRequest):
    return health.assess(detect.collect(),benchmark=req.benchmark)
@app.post('/api/diagnostics/plan')
def api_diagnostics_plan(req:BaselineRequest):
    h=health.assess(detect.collect(),benchmark=req.benchmark)
    return diagnostics.plan(h,req.benchmark,storage.health_inventory())
@app.post('/api/baseline/create')
def api_baseline_create(req:BaselineRequest):
    d=detect.collect();h=health.assess(d,benchmark=req.benchmark)
    return baseline.create(d,req.benchmark,h)
@app.post('/api/baseline/compare')
def api_baseline_compare(req:BaselineRequest):
    return baseline.compare(detect.collect(),req.benchmark)
@app.get('/api/detect')
def api_detect():return detect.collect()
@app.get('/api/inspect')
def api_inspect():return inspect.collect()
@app.get('/api/whea')
def api_whea(minutes:int=60,max_events:int=50):return watchdog.whea_events(minutes,max_events)
@app.get('/api/pulse')
def api_pulse():return pulse.collect()
@app.get('/api/forensics')
def api_forensics(vbios_path:str|None=None):return forensics.analyze(detect.collect(),vbios_path)

@app.get('/api/stress-correctness/capabilities')
def api_stress_correctness_capabilities():return stress_correctness.capabilities()

@app.get('/api/stress-correctness/history')
def api_stress_correctness_history(limit:int=100):return stress_correctness.history(limit)

@app.post('/api/stress-correctness/analyze')
def api_stress_correctness_analyze(req:StressCorrectnessAnalyzeRequest):return stress_correctness.analyze_runs(req.runs)

@app.post('/api/stress-correctness/run')
def api_stress_correctness_run(req:StressCorrectnessRequest):
    return stress_correctness.run(req.domain,seconds=req.seconds,mb=req.mb,passes=req.passes,device=req.device,rounds=req.rounds,directory=req.directory,full_scan=req.full_scan)

@app.post('/api/combined-stress')
def api_combined_stress(seconds:int=30,workers:int|None=None,gpu_mb:int=256):return combined.combined_stress(seconds,workers,gpu_mb)
@app.post('/api/storage-bench')
def api_storage_bench(mb:int=256,block_mb:int=4,directory:str|None=None):return storage.sequential_bench(mb,block_mb,directory)
@app.post('/api/cpu-stress')
def api_cpu_stress(seconds:int=10,workers:int|None=None):return crucible.cpu_stress(seconds,workers)
@app.post('/api/gpu-compute-stress')
def api_gpu_compute_stress(seconds:int=20,mb:int=256,rounds:int=64,device:int=0):return crucible.gpu_compute_stress(seconds,mb,rounds,device=device)
@app.post('/api/gpu-stress')
def api_gpu_stress(seconds:int=20,mb:int=256,device:int=0):return crucible.gpu_stress(seconds,mb,device=device)
@app.post('/api/ram-test')
def api_ram_test(mb:int=256,passes:int=2):return memory.ram_test(mb,passes)
@app.post('/api/vram-test')
def api_vram_test(mb:int=512,passes:int=2,full_scan:bool=False,device:int=0):return memory.native_vram_test(mb,passes,full_scan=full_scan,device=device)
@app.post('/api/vram-sweep')
def api_vram_sweep(start_mb:int=256,stop_mb:int=4096,step_mb:int=256,passes:int=1,full_scan:bool=False,device:int=0):return memory.vram_sweep(start_mb,stop_mb,step_mb,passes,full_scan=full_scan,device=device)
@app.post('/api/vram-map')
def api_vram_map(chunk_mb:int=256,target_mb:int=0,passes:int=1,full_scan:bool=False,device:int=0,adaptive:bool=False,min_chunk_mb:int=128,reserve_mb:int=512):return memory.vram_map(chunk_mb,target_mb,passes,full_scan=full_scan,device=device,adaptive=adaptive,min_chunk_mb=min_chunk_mb,reserve_mb=reserve_mb)
@app.post('/api/certify')
def api_certify(with_tests:bool=False,with_vram:bool=False,vbios_path:str|None=None):
    tests=[crucible.cpu_stress(5),memory.ram_test(128,1)] if with_tests else []
    if with_vram:tests.append(memory.native_vram_test(512,1))
    return build_report(tests=tests,vbios_path=vbios_path)
@app.get('/',response_class=HTMLResponse)
def root():
    p=Path(__file__).resolve().parents[2]/'web'/'index.html'
    if p.exists():return p.read_text(encoding='utf-8')
    t=telemetry_governance.status()
    notice='<p><strong>Telemetria opcional:</strong> desligada ate o usuario aceitar o aviso. <a href="/api/telemetry/privacy-notice">Ver dados e politica</a>.</p>' if not t.get('consent') else '<p>Telemetria opcional: consentimento ativo. <a href="/api/telemetry/status">Status</a> | <a href="/api/telemetry/preview">Preview</a></p>'
    return '<h1>Phoenix Forge 0.25.0rc6.post15</h1>'+notice

