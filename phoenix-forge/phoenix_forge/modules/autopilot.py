from __future__ import annotations
from phoenix_forge.models import DetectReport,StressResult,AIBenchResult,AutopilotDecision


def _reported_vram_gb(d:DetectReport)->float:
    if not d.gpus:return 0.0
    g=d.gpus[0]
    b=g.vulkan_primary_device_local_bytes or 0
    if not b:
        heaps=[h.get('size_bytes',0) for h in g.vulkan_memory_heaps if h.get('device_local')]
        b=max(heaps or [g.adapter_ram_bytes or 0])
    return b/1024**3


def _is_real_failure(t:StressResult)->bool:
    if t.passed:return False
    status=str(t.metrics.get('status') or '').upper()
    if status in {'TIMEOUT','ALLOCATION_FAILED','BUDGET_EXHAUSTED','NATIVE_HELPER_MISSING'}:
        return False
    return True


def decide(d:DetectReport,tests:list[StressResult]|None=None,ai:list[AIBenchResult]|None=None,*,workload:str='llm',backend:str='vulkan',runtime:str='*',model:str='*')->AutopilotDecision:
    tests=tests or []; ai=ai or []; gpu=d.gpus[0] if d.gpus else None; vram=_reported_vram_gb(d); reasons=[]
    from phoenix_forge.modules.gpu_safety import status_for_detect
    from phoenix_forge.modules.gpu_ledger import route as ledger_route
    safety=status_for_detect(d,workload=workload,backend=backend,runtime=runtime,model=model)
    ledger=ledger_route(workload,device_name=gpu.name if gpu else None,user_mode='AUTO')
    vram_tests=[t for t in tests if 'VRAM' in t.module]
    scope_blocked=safety.get('authorization',{}).get('state')=='BLOCKED'
    ledger_forces_cpu=ledger.get('effective_mode')=='CPU'
    gpu_fail=scope_blocked or ledger_forces_cpu or any(('GPU' in t.module or 'VRAM' in t.module) and _is_real_failure(t) for t in tests)
    inconclusive=[t for t in vram_tests if (not t.passed and str(t.metrics.get('status') or '').upper() in {'TIMEOUT','ALLOCATION_FAILED','BUDGET_EXHAUSTED'})]
    ai_pass=sum(1 for a in ai if a.passed); ai_fail=sum(1 for a in ai if not a.passed)
    max_stable_mb=0
    strong_full_scan=False
    quick_only=False
    for t in vram_tests:
        status=str(t.metrics.get('status') or '').upper()
        if t.passed:
            max_stable_mb=max(max_stable_mb,int(t.metrics.get('max_stable_mb',0) or 0),int(t.metrics.get('requested_mb',0) or 0),int(t.metrics.get('target_mb',0) or 0),int(t.metrics.get('validated_mb',0) or 0))
            coverage=float(t.metrics.get('address_coverage_percent') or (100.0 if t.metrics.get('full_scan') else 0.0))
            passes=int(t.metrics.get('passes') or 0)
            tested=int(t.metrics.get('target_mb') or t.metrics.get('requested_mb') or 0)
            required=int(vram*1024*.75) if vram else 0
            if status in {'FULL_SCAN_PASS','PASS'} and bool(t.metrics.get('full_scan')) and coverage>=99.9 and passes>=2 and tested>=required:
                strong_full_scan=True
            elif status in {'QUICK_PASS','PASS'}:
                quick_only=True
        elif status=='BUDGET_EXHAUSTED':
            # A partial resident map can still validate the portion that completed without data mismatches.
            max_stable_mb=max(max_stable_mb,int(t.metrics.get('validated_mb',0) or 0))

    if gpu and d.vulkan_available and not gpu_fail:
        if vram>=7.0 and not inconclusive and strong_full_scan:
            mode='GPU'; frac=.82; conf=.92; reasons.append(f'Vulkan GPU detected with approximately {vram:.1f} GiB primary device-local heap and no confirmed GPU memory error.')
        else:
            mode='HYBRID'; frac=.50; conf=.82; reasons.append('Vulkan is usable, but no repeated high-coverage validation authorizes unrestricted GPU placement.')
    elif gpu and d.vulkan_available:
        mode='CPU'; frac=0.0; conf=.96; reasons.append('GPU/VRAM validation reported a confirmed instability; automatic Vulkan placement is blocked until an explicit user override or repaired hardware is revalidated.')
    else:
        mode='CPU'; frac=0.0; conf=.88; reasons.append('No validated Vulkan GPU path is available.')

    if inconclusive:reasons.append(f'{len(inconclusive)} VRAM validation result(s) were inconclusive due to timeout/allocation-budget limits, not memory corruption.')
    if quick_only:reasons.append('A quick/sample pass is triage evidence only and cannot certify healthy VRAM.')
    if ai_pass: reasons.append(f'{ai_pass} AI benchmark(s) completed successfully.')
    if ai_fail: reasons.append(f'{ai_fail} AI benchmark(s) failed; policy remains conservative.')
    if max_stable_mb: reasons.append(f'Highest explicitly validated VRAM allocation/map target: {max_stable_mb} MB.')
    if scope_blocked:reasons.append(f"Persistent safety policy blocks {workload}/{backend} on this GPU; the workload is forced to CPU while unrelated GPU workloads remain independent.")
    elif ledger_forces_cpu:reasons.append(f"GPU Health Ledger restricts {workload} after historical hardware evidence; a later PASS did not erase the failure latch.")
    elif safety.get('diagnostic_required'):reasons.append('GPU hardware is degraded and requires diagnosis; this workload remains independently monitored.')

    headroom=512 if mode=='GPU' else (1024 if mode=='HYBRID' else 0)
    hard_cap_mb = max_stable_mb if strong_full_scan else int(vram*1024*frac) if vram and mode!='CPU' else 0
    vram_health='SUSPECTED_UNSTABLE' if gpu_fail else ('VALIDATED' if strong_full_scan else 'INCONCLUSIVE')
    policy={
        'schema':'phoenix.forge.runtime-policy/v1',
        'mode':mode,
        'prefer_vulkan':bool(d.vulkan_available and mode!='CPU'),
        'allow_cpu_fallback':True,
        'gpu_only_allowed':bool(mode=='GPU' and strong_full_scan and not gpu_fail),
        'vram_health':vram_health,
        'validation_level':'deep' if strong_full_scan else ('failed' if gpu_fail else 'unverified'),
        'max_vram_fraction':frac,
        'validated_vram_mb':max_stable_mb or None,
        'vram_hard_cap_mb':hard_cap_mb or None,
        'vram_headroom_mb':headroom,
        'llm':{'backend':'vulkan' if mode!='CPU' else 'cpu','gpu_offload':'max_safe' if mode=='GPU' else ('partial' if mode=='HYBRID' else 'none')},
        'image':{'backend':'vulkan' if mode!='CPU' else 'cpu','placement':'gpu' if mode=='GPU' else ('split' if mode=='HYBRID' else 'cpu')},
        'fallback_order':['GPU','HYBRID','CPU'] if mode=='GPU' else (['HYBRID','CPU'] if mode=='HYBRID' else ['CPU'])
    }
    policy['gpu_safety']=safety
    policy['gpu_ledger_route']=ledger
    policy['workload']=workload;policy['backend']=backend;policy['runtime']=runtime;policy['model']=model
    policy['notification_required']=bool(scope_blocked or safety.get('diagnostic_required'))
    policy['effective_mode_reason']='workload_gpu_blocked' if scope_blocked else ('gpu_degraded_monitored' if safety.get('diagnostic_required') else 'current_validation_policy')
    return AutopilotDecision(mode=mode,confidence=conf,reasons=reasons,policy=policy)
