from __future__ import annotations
from typing import Any

from phoenix_forge.modules import capability_finalization, gpu_safety, detect, stress_correctness, workload_profile, decision_shadow, shadow_outcome_tracking

SCHEMA = 'phoenix.forge.decision-preview/v4'
VALID_MODES = {'AUTO','CPU','GPU','HYBRID'}


def _norm_mode(value: str | None) -> str:
    mode = str(value or 'AUTO').upper()
    return mode if mode in VALID_MODES else 'AUTO'


def _add(scores: dict[str,float], breakdown: list[dict[str,Any]], mode: str, delta: float, reason: str, evidence: str) -> None:
    scores[mode] = round(float(scores.get(mode, 0.0)) + float(delta), 3)
    breakdown.append({'mode':mode,'delta':float(delta),'reason':reason,'evidence':evidence})


def capabilities() -> dict[str, Any]:
    gate = capability_finalization.audit().get('gate', {})
    return {
        'schema': SCHEMA,
        'status': 'READY',
        'preview_enabled': True,
        'evidence_scoring_enabled': True,
        'shadow_evidence_enabled': True,
        'shadow_outcome_tracking_enabled': True,
        'execution_enabled': False,
        'auto_orchestration_enabled': False,
        'decision_engine_gate_open': bool(gate.get('ready_for_decision_engine')),
        'gate_reasons': list(gate.get('decision_engine_block_reasons') or []),
        'inputs': ['user_intent','gpu_presence','gpu_safety','diagnostic_requirement','vram_capacity','stress_correctness_history','parallelism','workload_profile','model_fit','calibration_cohorts','confidence_aging'],
        'policy': {
            'preview_is_advisory_only': True,
            'no_dispatch': True,
            'no_provider_actions': True,
            'no_firmware_write': True,
            'user_requested_mode_is_preserved_as_intent': True,
            'unsafe_explicit_gpu_request_may_be_recommended_as_cpu': True,
            'unknown_is_not_failure': True,
            'capacity_is_not_corruption': True,
            'oom_is_not_physical_defect': True,
            'single_mismatch_is_not_physical_defect': True,
            'shadow_evidence_never_dispatches': True,
            'shadow_evidence_does_not_replace_base_recommendation': True,
            'shadow_outcomes_never_claim_unobserved_counterfactuals': True,
            'reproducible_corruption_has_high_negative_weight': True,
        },
    }


def _stress_evidence(device_key: str | None) -> dict[str,Any]:
    hist = stress_correctness.history(limit=100)
    entries = list(hist.get('entries') or [])
    if device_key:
        selected = [x for x in entries if x.get('device_key') in {None, device_key} and x.get('domain') in {'vram','gpu_compute'}]
    else:
        selected = [x for x in entries if x.get('domain') in {'vram','gpu_compute'}]
    analysis = stress_correctness.analyze_runs(selected) if selected else {
        'schema': stress_correctness.SCHEMA, 'status':'ANALYZED','verdict':'NO_RELEVANT_HISTORY','runs':0,
        'pass_runs':0,'capacity_events':0,'instability_events':0,'corruption_events':0,
        'reproducible_corruption':[],'physical_defect_suspected':False,'evidence':[]
    }
    analysis['selected_runs'] = len(selected)
    return analysis


def preview(*, workload: str='llm', requested_mode: str='AUTO', min_vram_mb: int=0,
            parallelizable: bool=False, task_count: int=1, model: str='*', model_size_mb: int=0, context_tokens: int=0, quantization: str|None=None, backend: str='vulkan', width: int=0, height: int=0, batch: int=1, runtime_version: str|None=None, model_fingerprint: str|None=None, execution_id: str|None=None) -> dict[str, Any]:
    requested = _norm_mode(requested_mode)
    finalization = capability_finalization.audit()
    report = detect.collect()
    safety = gpu_safety.status_for_detect(report, workload=workload, backend='vulkan', runtime='*', model='*')
    authorization = safety.get('authorization') or {}
    gpu = report.gpus[0] if report.gpus else None
    device_key = getattr(gpu, 'device_key', None) if gpu else None
    stress = _stress_evidence(device_key)
    wp = workload_profile.profile(workload=workload,model=model,model_size_mb=model_size_mb,context_tokens=context_tokens,quantization=quantization,backend=backend,width=width,height=height,batch=batch)

    scores: dict[str,float] = {'CPU':50.0,'GPU':50.0,'HYBRID':50.0}
    breakdown: list[dict[str,Any]] = []
    reasons: list[str] = []
    evidence_points = 0
    max_evidence_points = 6

    # User intent is strong preference but never stronger than a hard safety block.
    if requested in {'CPU','GPU','HYBRID'}:
        _add(scores, breakdown, requested, 35, 'Explicit user mode preference.', 'user_intent')
        evidence_points += 1
    else:
        reasons.append('AUTO mode requested; placement is ranked from available evidence.')

    gpu_present = bool(report.gpus)
    gpu_blocked = authorization.get('state') == 'BLOCKED' or bool(safety.get('global_ai_blocked'))
    diagnostic_required = bool(safety.get('diagnostic_required', False))
    if gpu_present:
        evidence_points += 1
        _add(scores, breakdown, 'GPU', 15, 'A GPU is detected.', 'gpu_presence')
        _add(scores, breakdown, 'HYBRID', 10, 'A GPU is detected and can contribute to hybrid capacity.', 'gpu_presence')
    else:
        _add(scores, breakdown, 'GPU', -100, 'No GPU is detected.', 'gpu_presence')
        _add(scores, breakdown, 'HYBRID', -80, 'Hybrid mode requires a usable GPU.', 'gpu_presence')
        _add(scores, breakdown, 'CPU', 20, 'CPU is the available execution resource.', 'gpu_presence')

    if gpu_present:
        evidence_points += 1
        if gpu_blocked:
            _add(scores, breakdown, 'GPU', -150, 'GPU safety authorization is BLOCKED.', 'gpu_safety')
            _add(scores, breakdown, 'HYBRID', -120, 'Blocked GPU must not participate in hybrid execution.', 'gpu_safety')
            _add(scores, breakdown, 'CPU', 35, 'CPU is preferred while GPU is blocked.', 'gpu_safety')
            reasons.append('GPU safety evidence currently blocks GPU participation.')
        elif diagnostic_required:
            _add(scores, breakdown, 'GPU', -25, 'GPU requires diagnostics; full GPU placement is penalized.', 'gpu_safety')
            _add(scores, breakdown, 'HYBRID', 8, 'Hybrid keeps GPU contribution limited while diagnostics are required.', 'gpu_safety')
            _add(scores, breakdown, 'CPU', 8, 'CPU gains weight while GPU diagnostics remain pending.', 'gpu_safety')
            reasons.append('GPU remains available but requires diagnostics.')
        else:
            _add(scores, breakdown, 'GPU', 18, 'GPU is not blocked and no diagnostic requirement is active.', 'gpu_safety')
            _add(scores, breakdown, 'HYBRID', 10, 'GPU is available for hybrid participation.', 'gpu_safety')

    min_vram_mb = max(0, int(min_vram_mb))
    vram_mb = 0
    if gpu is not None:
        try: vram_mb = int((getattr(gpu,'adapter_ram_bytes',0) or 0) / (1024*1024))
        except Exception: vram_mb = 0
    prof_req = int(((wp.get('requirements') or {}).get('estimated_min_vram_mb') or 0))
    if prof_req > min_vram_mb:
        min_vram_mb = prof_req
        reasons.append(f'Workload profile raised the advisory VRAM requirement to {prof_req} MB.')
    model_fit = workload_profile.fit(wp, available_vram_mb=vram_mb)
    if (model_fit.get('gpu') or {}).get('status') == 'NO_FIT':
        _add(scores, breakdown, 'GPU', -55, 'Workload profile does not fit detected VRAM.', 'model_fit')
        _add(scores, breakdown, 'HYBRID', 8, 'Hybrid gains weight when full GPU residency does not fit.', 'model_fit')
        _add(scores, breakdown, 'CPU', 14, 'CPU gains weight when model fit exceeds VRAM.', 'model_fit')
        evidence_points += 1

    if min_vram_mb > 0:
        evidence_points += 1
        if vram_mb >= min_vram_mb:
            _add(scores, breakdown, 'GPU', 20, f'Detected VRAM ({vram_mb} MB) meets requested minimum ({min_vram_mb} MB).', 'vram_capacity')
            _add(scores, breakdown, 'HYBRID', 10, 'VRAM minimum is satisfied.', 'vram_capacity')
        elif vram_mb > 0:
            _add(scores, breakdown, 'GPU', -60, f'Detected VRAM ({vram_mb} MB) is below requested minimum ({min_vram_mb} MB).', 'vram_capacity')
            _add(scores, breakdown, 'HYBRID', -15, 'VRAM is below requested minimum; hybrid may still use CPU capacity.', 'vram_capacity')
            _add(scores, breakdown, 'CPU', 20, 'CPU avoids the requested GPU VRAM capacity shortfall.', 'vram_capacity')
        else:
            reasons.append('VRAM requirement was supplied, but usable VRAM capacity could not be proven.')

    if int(stress.get('runs') or 0) > 0:
        evidence_points += 1
        verdict = str(stress.get('verdict') or 'INCONCLUSIVE')
        if stress.get('physical_defect_suspected') or verdict == 'REPRODUCIBLE_CORRUPTION':
            _add(scores, breakdown, 'GPU', -140, 'Reproducible corruption exists in GPU/VRAM correctness history.', 'stress_correctness')
            _add(scores, breakdown, 'HYBRID', -110, 'Reproducible corruption excludes GPU participation from hybrid mode.', 'stress_correctness')
            _add(scores, breakdown, 'CPU', 35, 'CPU is preferred while reproducible GPU corruption is unresolved.', 'stress_correctness')
            reasons.append('Stress & Correctness contains reproducible corruption evidence.')
        elif verdict == 'CORRUPTION_NEEDS_REPEAT':
            _add(scores, breakdown, 'GPU', -30, 'A corruption event exists but requires reproduction.', 'stress_correctness')
            _add(scores, breakdown, 'HYBRID', -10, 'Single corruption event lowers confidence but is not physical-defect proof.', 'stress_correctness')
            reasons.append('A single corruption event exists; repetition is required before hardware-defect conclusions.')
        elif verdict == 'INSTABILITY_NEEDS_CORRELATION':
            _add(scores, breakdown, 'GPU', -22, 'Instability evidence requires correlation.', 'stress_correctness')
            _add(scores, breakdown, 'HYBRID', 3, 'Hybrid is favored over full GPU while instability is being correlated.', 'stress_correctness')
        elif verdict == 'CAPACITY_LIMIT_ONLY':
            _add(scores, breakdown, 'GPU', -8, 'Capacity limit observed; this is not corruption evidence.', 'stress_correctness')
            _add(scores, breakdown, 'HYBRID', 6, 'Hybrid can compensate for GPU capacity limits.', 'stress_correctness')
            _add(scores, breakdown, 'CPU', 4, 'CPU gains modest weight from GPU capacity pressure.', 'stress_correctness')
        elif verdict == 'PASS_NO_CORRUPTION_OBSERVED':
            _add(scores, breakdown, 'GPU', 14, 'Recent GPU/VRAM correctness history passed without corruption.', 'stress_correctness')
            _add(scores, breakdown, 'HYBRID', 8, 'Passing GPU correctness supports hybrid participation.', 'stress_correctness')
    else:
        reasons.append('No relevant GPU/VRAM Stress & Correctness history is available; no positive or negative score is invented.')

    task_count = max(1, int(task_count))
    if bool(parallelizable) and task_count > 1:
        evidence_points += 1
        _add(scores, breakdown, 'HYBRID', 18, f'Workload is parallelizable across {task_count} tasks.', 'parallelism')
        _add(scores, breakdown, 'CPU', 4, 'CPU can participate in parallel work.', 'parallelism')
        _add(scores, breakdown, 'GPU', 4, 'GPU can participate in parallel work.', 'parallelism')

    # Hard safety constraints are applied after all soft scoring.
    if gpu_blocked or not gpu_present or bool(stress.get('physical_defect_suspected')):
        scores['GPU'] = min(scores['GPU'], -50.0)
        scores['HYBRID'] = min(scores['HYBRID'], -25.0)

    ranked = sorted(scores.items(), key=lambda kv: (kv[1], {'CPU':2,'HYBRID':1,'GPU':0}.get(kv[0],0)), reverse=True)
    recommendation = ranked[0][0]
    margin = float(ranked[0][1] - ranked[1][1]) if len(ranked)>1 else 0.0
    evidence_quality = round(min(1.0, evidence_points / max_evidence_points), 3)
    confidence = round(min(0.98, 0.35 + evidence_quality*0.4 + min(0.23, max(0.0, margin)/100.0)), 3)

    # Explicit CPU is always respected; explicit GPU/HYBRID is respected unless safety makes it unsafe.
    if requested == 'CPU':
        recommendation = 'CPU'; confidence = max(confidence, 0.95)
    elif requested in {'GPU','HYBRID'} and not gpu_blocked and gpu_present and not bool(stress.get('physical_defect_suspected')):
        recommendation = requested

    gate = finalization.get('gate', {})
    can_execute = bool(gate.get('ready_for_decision_engine'))
    if not can_execute:
        reasons.append('Decision Engine gate remains closed; this result is advisory only.')

    shadow = decision_shadow.assess(
        base_scores=scores, base_recommendation=recommendation, model_id=model, workload=workload, backend=backend,
        device_key=device_key, driver_version=getattr(gpu,'driver_version',None) if gpu else None, runtime_version=runtime_version,
        model_fingerprint=model_fingerprint, context_tokens=context_tokens, width=width, height=height,
        gpu_present=gpu_present, gpu_blocked=gpu_blocked, physical_defect_suspected=bool(stress.get('physical_defect_suspected')),
    )

    shadow_tracking = None
    if execution_id:
        try:
            shadow_tracking = shadow_outcome_tracking.record_prediction(
                execution_id=execution_id, model_id=model, workload=workload, backend=backend,
                base_recommended_mode=recommendation,
                shadow_recommended_mode=str(shadow.get('shadow_recommended_mode') or recommendation),
                base_scores=scores, shadow_scores=shadow.get('shadow_scores') or {},
                device_key=device_key, driver_version=getattr(gpu,'driver_version',None) if gpu else None,
                runtime_version=runtime_version, model_fingerprint=model_fingerprint,
                context_tokens=context_tokens, width=width, height=height,
                evidence_status=str(shadow.get('status') or 'UNKNOWN'),
            )
        except Exception as exc:
            shadow_tracking = {'schema': shadow_outcome_tracking.SCHEMA, 'status':'TRACKING_FAILED', 'error':type(exc).__name__}

    return {
        'schema': SCHEMA,
        'status': 'PREVIEW',
        'workload': workload,
        'requested_mode': requested,
        'recommended_mode': recommendation,
        'shadow_recommended_mode': shadow.get('shadow_recommended_mode'),
        'shadow_changed': bool(shadow.get('shadow_changed')),
        'shadow_evidence': shadow,
        'shadow_outcome_tracking': shadow_tracking,
        'confidence': confidence,
        'evidence_quality': evidence_quality,
        'scores': {k:round(v,3) for k,v in scores.items()},
        'score_margin': round(margin,3),
        'score_breakdown': breakdown,
        'reasons': reasons,
        'evidence': {
            'gpu_safety': safety,
            'gpu_count': len(report.gpus),
            'gpu_device_key': device_key,
            'gpu_vram_mb': vram_mb or None,
            'requested_min_vram_mb': min_vram_mb,
            'stress_correctness': stress,'workload_profile':wp,'model_fit':model_fit,
            'parallelizable': bool(parallelizable),
            'task_count': task_count,
            'capability_finalization_gate': gate,
        },
        'authority': {
            'preview_only': True,
            'execution_enabled': False,
            'auto_orchestration_enabled': False,
            'decision_engine_gate_open': can_execute,
            'would_require_explicit_future_enablement': True,
        },
        'policy': capabilities()['policy'],
    }
