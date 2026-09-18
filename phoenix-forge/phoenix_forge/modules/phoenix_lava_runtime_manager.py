from __future__ import annotations
import json, os, subprocess, time, urllib.request
from pathlib import Path
from typing import Any
import psutil
from phoenix_forge.modules import phoenix_lava_foundation_adapter as lava
from phoenix_forge.modules import phoenix_lava_model_registry as model_registry

SCHEMA='phoenix.forge.phoenix-lava-runtime-manager/v3'; RUNTIME_NAME='Phoenix Llama Runtime'; DEFAULT_ALIAS='phoenix-lava-24b'

def _phoenix_roots()->list[Path]:
    roots=[]
    for key in ('PHOENIX_ROOT','PHOENIX_HOME'):
        v=os.getenv(key)
        if v: roots.append(Path(v).expanduser())
    p=Path(__file__).resolve()
    for parent in p.parents:
        if parent.name.lower()=='phoenix-forge': roots.append(parent.parent); break
    out=[];seen=set()
    for r in roots:
        k=str(r).lower()
        if k not in seen: seen.add(k);out.append(r)
    return out

def _root()->Path:
    r=_phoenix_roots(); return r[0].resolve() if r else Path.cwd().resolve()
def _state_dir()->Path:
    p=_root()/'runtime_state'/'phoenix-lava';p.mkdir(parents=True,exist_ok=True);return p
def _state_path()->Path:return _state_dir()/'runtime.json'
def _log_path()->Path:return _state_dir()/'phoenix-lava-runtime.log'

def runtime_candidates()->list[Path]:
    out=[];env=os.getenv('PHOENIX_LLAMA_SERVER')
    if env: out.append(Path(env).expanduser())
    rels=(Path('bin/phoenix-llama-runtime/windows-x64/llama-server.exe'),Path('bin/phoenix-llama-runtime/llama-server.exe'),Path('bin/llama-server.exe'),Path('llama-server.exe'))
    for root in _phoenix_roots():out.extend(root/r for r in rels)
    ded=[];seen=set()
    for p in out:
        k=str(p).lower()
        if k not in seen:seen.add(k);ded.append(p)
    return ded

def discover_runtime()->dict[str,Any]:
    c=runtime_candidates();f=next((p for p in c if p.is_file()),None)
    return {'schema':'phoenix.forge.phoenix-lava-runtime-discovery/v1','status':'READY' if f else 'RUNTIME_REQUIRED','runtime':RUNTIME_NAME,'path':str(f) if f else None,'searched':[str(x) for x in c]}

def _found_models()->dict[str,dict[str,Any]]:
    d=lava.discover();return {str(x.get('quantization')):dict(x) for x in d.get('found',[]) if x.get('quantization')}
def choose_model(preferred='Q5_K_M',*,allow_fallback=True)->dict[str,Any]:
    preferred=str(preferred or 'Q5_K_M').upper();lava.variant(preferred);found=_found_models()
    if preferred in found:return {'status':'READY','selected':found[preferred],'fallback':False,'requested':preferred}
    if allow_fallback:
        for q in ('Q5_K_M','Q6_K'):
            if q in found:return {'status':'READY','selected':found[q],'fallback':q!=preferred,'requested':preferred}
    return {'status':'MODEL_REQUIRED','selected':None,'fallback':False,'requested':preferred,'available':sorted(found)}

def launch_plan(*,mode='AUTO',quantization='Q5_K_M',context_tokens=8192,threads=12,device='Vulkan0',parallel=1,port=8082,alias=DEFAULT_ALIAS,allow_quant_fallback=True)->dict[str,Any]:
    from phoenix_forge.modules import phoenix_lava_artifact_qualification as _aq
    runtime=discover_runtime();model=choose_model(quantization,allow_fallback=allow_quant_fallback);sel=model.get('selected');chosen=(sel or {}).get('quantization') or quantization
    policy=lava.runtime_policy(mode=mode,quantization=chosen,context_tokens=context_tokens,threads=threads,device=device,parallel=parallel,port=port)
    artifact=_aq.qualify(chosen,compute_sha256=False)
    blocked=[x for x,ok in (('RUNTIME_REQUIRED',runtime.get('status')=='READY'),('MODEL_REQUIRED',model.get('status')=='READY')) if not ok]
    if model.get('status')=='READY' and artifact.get('status')!='QUALIFIED':blocked.append('ARTIFACT_NOT_QUALIFIED')
    ready=not blocked;argv=[]
    if ready:argv=[runtime['path'],'-m',sel['path'],'--alias',str(alias)]+list(policy['arguments'])
    return {'schema':'phoenix.forge.phoenix-lava-launch-plan/v4','status':'READY' if ready else 'BLOCKED','runtime':runtime,'model':model,'artifact':artifact,'policy':policy,'argv':argv,'shell':False,'automatic_start':False,'blocked_reasons':blocked}

def endpoint_status(port=8082,timeout_s=1.0)->dict[str,Any]:
    url=f'http://127.0.0.1:{int(port)}/health'
    try:
        with urllib.request.urlopen(url,timeout=max(.1,float(timeout_s))) as r:code=int(getattr(r,'status',200));body=r.read(4096).decode('utf-8','replace')
        return {'schema':'phoenix.forge.phoenix-lava-endpoint-status/v1','status':'ONLINE' if 200<=code<300 else 'DEGRADED','url':url,'http_status':code,'body_preview':body[:500]}
    except Exception as exc:return {'schema':'phoenix.forge.phoenix-lava-endpoint-status/v1','status':'OFFLINE','url':url,'error':type(exc).__name__}

def _load_state()->dict[str,Any]:
    try:return json.loads(_state_path().read_text(encoding='utf-8'))
    except Exception:return {}
def _identity(pid:int,state:dict[str,Any])->tuple[bool,bool,str]:
    try:
        p=psutil.Process(pid);alive=p.is_running() and p.status()!=psutil.STATUS_ZOMBIE;cmd=' '.join(p.cmdline()).lower();exe=''
        try:exe=(p.exe() or '').lower()
        except Exception:pass
        expected=str(state.get('runtime_path') or '').lower();ok=alive and (DEFAULT_ALIAS.lower() in cmd or (expected and expected==exe))
        return alive,ok,cmd
    except Exception:return False,False,''

def managed_status(port=8082)->dict[str,Any]:
    state=_load_state();pid=int(state.get('pid') or 0);alive=identity=False
    if pid:alive,identity,_=_identity(pid,state)
    ep=endpoint_status(port=port);st='RUNNING' if alive and identity else ('STALE_STATE' if state and not alive else ('EXTERNAL_ONLINE' if ep.get('status')=='ONLINE' else 'STOPPED'))
    return {'schema':'phoenix.forge.phoenix-lava-managed-status/v2','status':st,'pid':pid or None,'process_alive':alive,'identity_ok':identity,'endpoint':ep,'state':state or None,'stale_state_recoverable':st=='STALE_STATE'}

def reconcile_state(*,confirm=False,port=8082)->dict[str,Any]:
    cur=managed_status(port=port)
    if cur['status']!='STALE_STATE':return {'schema':'phoenix.forge.phoenix-lava-state-reconcile/v1','status':'NO_ACTION_REQUIRED','current':cur}
    if not confirm:return {'schema':'phoenix.forge.phoenix-lava-state-reconcile/v1','status':'CONFIRMATION_REQUIRED','current':cur}
    _state_path().unlink(missing_ok=True);return {'schema':'phoenix.forge.phoenix-lava-state-reconcile/v1','status':'STALE_STATE_REMOVED'}

def wait_ready(*,port=8082,timeout_s=180.0,poll_s=.5,pid:int|None=None)->dict[str,Any]:
    started=time.perf_counter();attempts=0
    while time.perf_counter()-started<max(0.1,float(timeout_s)):
        attempts+=1;ep=endpoint_status(port=port,timeout_s=min(2.0,max(.2,poll_s)))
        if ep.get('status')=='ONLINE':return {'schema':'phoenix.forge.phoenix-lava-readiness/v1','status':'READY','elapsed_seconds':round(time.perf_counter()-started,3),'attempts':attempts,'endpoint':ep}
        if pid:
            alive,identity,_=_identity(int(pid),_load_state())
            if not alive:return {'schema':'phoenix.forge.phoenix-lava-readiness/v1','status':'PROCESS_EXITED','elapsed_seconds':round(time.perf_counter()-started,3),'attempts':attempts,'pid':pid}
            if not identity:return {'schema':'phoenix.forge.phoenix-lava-readiness/v1','status':'IDENTITY_MISMATCH','pid':pid}
        time.sleep(max(.05,float(poll_s)))
    return {'schema':'phoenix.forge.phoenix-lava-readiness/v1','status':'TIMEOUT','elapsed_seconds':round(time.perf_counter()-started,3),'attempts':attempts,'endpoint':endpoint_status(port=port)}

def start_runtime(*,confirm=False,mode='AUTO',quantization='Q5_K_M',context_tokens=8192,threads=12,device='Vulkan0',parallel=1,port=8082,wait_ready_seconds=0.0)->dict[str,Any]:
    if not confirm:return {'schema':'phoenix.forge.phoenix-lava-runtime-start/v2','status':'CONFIRMATION_REQUIRED','plan':launch_plan(mode=mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,parallel=parallel,port=port)}
    cur=managed_status(port=port)
    if cur['status'] in {'RUNNING','EXTERNAL_ONLINE'}:return {'schema':'phoenix.forge.phoenix-lava-runtime-start/v2','status':'ALREADY_RUNNING','current':cur}
    if cur['status']=='STALE_STATE':return {'schema':'phoenix.forge.phoenix-lava-runtime-start/v2','status':'STALE_STATE_REQUIRES_RECONCILE','current':cur}
    plan=launch_plan(mode=mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,parallel=parallel,port=port)
    if plan['status']!='READY':return {'schema':'phoenix.forge.phoenix-lava-runtime-start/v2','status':'BLOCKED','plan':plan}
    log=_log_path();flags=0
    if os.name=='nt':flags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)|getattr(subprocess,'CREATE_NO_WINDOW',0)
    with log.open('ab',buffering=0) as fh:proc=subprocess.Popen(plan['argv'],stdin=subprocess.DEVNULL,stdout=fh,stderr=subprocess.STDOUT,shell=False,cwd=str(Path(plan['runtime']['path']).parent),creationflags=flags,start_new_session=(os.name!='nt'))
    state={'schema':'phoenix.forge.phoenix-lava-runtime-state/v2','pid':proc.pid,'started_at':time.time(),'port':int(port),'quantization':plan['model']['selected']['quantization'],'model_path':plan['model']['selected']['path'],'runtime_path':plan['runtime']['path'],'mode':mode,'context_tokens':int(context_tokens),'threads':int(threads),'device':device,'parallel':int(parallel),'log_path':str(log),'alias':DEFAULT_ALIAS,'argv':plan['argv']}
    _state_path().write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf-8')
    out={'schema':'phoenix.forge.phoenix-lava-runtime-start/v2','status':'STARTED','state':state,'automatic':False}
    if float(wait_ready_seconds)>0:out['readiness']=wait_ready(port=port,timeout_s=wait_ready_seconds,pid=proc.pid);out['status']='READY' if out['readiness']['status']=='READY' else 'STARTED_NOT_READY'
    return out

def stop_runtime(*,confirm=False,timeout_s=10.0)->dict[str,Any]:
    if not confirm:return {'schema':'phoenix.forge.phoenix-lava-runtime-stop/v1','status':'CONFIRMATION_REQUIRED','current':managed_status()}
    state=_load_state();pid=int(state.get('pid') or 0)
    if not pid:return {'schema':'phoenix.forge.phoenix-lava-runtime-stop/v1','status':'NOT_MANAGED'}
    alive,identity,_=_identity(pid,state)
    if not alive:_state_path().unlink(missing_ok=True);return {'schema':'phoenix.forge.phoenix-lava-runtime-stop/v1','status':'ALREADY_STOPPED'}
    if not identity:return {'schema':'phoenix.forge.phoenix-lava-runtime-stop/v1','status':'IDENTITY_MISMATCH','pid':pid,'action':'REFUSED'}
    p=psutil.Process(pid);p.terminate()
    try:p.wait(timeout=max(1.0,float(timeout_s)))
    except psutil.TimeoutExpired:p.kill();p.wait(timeout=5)
    _state_path().unlink(missing_ok=True);return {'schema':'phoenix.forge.phoenix-lava-runtime-stop/v1','status':'STOPPED','pid':pid}

def restart_runtime(*,confirm=False,mode='AUTO',quantization='Q5_K_M',context_tokens=8192,threads=12,device='Vulkan0',parallel=1,port=8082,wait_ready_seconds=180.0)->dict[str,Any]:
    if not confirm:return {'schema':'phoenix.forge.phoenix-lava-runtime-restart/v1','status':'CONFIRMATION_REQUIRED'}
    before=managed_status(port=port);stop=None
    if before['status']=='RUNNING':stop=stop_runtime(confirm=True)
    elif before['status']=='STALE_STATE':reconcile_state(confirm=True,port=port)
    elif before['status']=='EXTERNAL_ONLINE':return {'schema':'phoenix.forge.phoenix-lava-runtime-restart/v1','status':'EXTERNAL_PROCESS_REFUSED','current':before}
    start=start_runtime(confirm=True,mode=mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,parallel=parallel,port=port,wait_ready_seconds=wait_ready_seconds)
    return {'schema':'phoenix.forge.phoenix-lava-runtime-restart/v1','status':start.get('status'),'stop':stop,'start':start}

def log_tail(lines=80)->dict[str,Any]:
    p=_log_path();n=max(1,min(int(lines),1000))
    if not p.is_file():return {'schema':'phoenix.forge.phoenix-lava-log-tail/v1','status':'LOG_MISSING','path':str(p),'lines':[]}
    data=p.read_text(encoding='utf-8',errors='replace').splitlines()[-n:]
    return {'schema':'phoenix.forge.phoenix-lava-log-tail/v1','status':'READY','path':str(p),'count':len(data),'lines':data}

def hardware_fit(quantization='Q5_K_M',*,reserve_ram_gb=6.0)->dict[str,Any]:
    q=lava.variant(quantization);vm=psutil.virtual_memory();model=int(float(q['approx_size_gb'])*1024**3);reserve=int(max(2.0,float(reserve_ram_gb))*1024**3);available=int(vm.available);headroom=available-model-reserve
    cpu_fit=headroom>=0
    return {'schema':'phoenix.forge.phoenix-lava-hardware-fit/v2','status':'CPU_ONLY_FIT' if cpu_fit else 'RAM_PRESSURE_FOR_CPU_ONLY','quantization':q['quantization'],'model_approx_bytes':model,'available_ram_bytes':available,'reserve_ram_bytes':reserve,'cpu_only_headroom_bytes':headroom,'cpu_only_fit':cpu_fit,'hybrid_candidate':True,'recommended_mode':'AUTO' if cpu_fit else 'AUTO_OR_HYBRID_RUNTIME_FIT','blocking':False,'gpu_fit':'DELEGATED_TO_PHOENIX_LLAMA_RUNTIME','policy':{'no_vram_guess':True,'runtime_fit_owns_layer_placement':True,'ram_pressure_does_not_block_auto_hybrid':True,'cpu_only_admission_uses_ram_headroom':True}}

def admission_plan(*,mode='AUTO',quantization='Q5_K_M',context_tokens=8192,threads=12,device='Vulkan0',port=8082)->dict[str,Any]:
    fit=hardware_fit(quantization);launch=launch_plan(mode=mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,port=port,allow_quant_fallback=False);m=str(mode).upper()
    reasons=list(launch.get('blocked_reasons') or [])
    if m=='CPU' and not fit['cpu_only_fit']:reasons.append('CPU_ONLY_RAM_PRESSURE')
    status='READY_FOR_RUNTIME_FIT' if not reasons else 'BLOCKED'
    if m in {'AUTO','HYBRID'} and reasons==['CPU_ONLY_RAM_PRESSURE']:status='READY_FOR_RUNTIME_FIT';reasons=[]
    return {'schema':'phoenix.forge.phoenix-lava-admission-plan/v1','status':status,'mode':m,'quantization':quantization,'hardware_fit':fit,'launch':launch,'blocked_reasons':reasons,'cooperative_executor_required':False,'placement_owner':'Phoenix Llama Runtime','policy':{'auto_hybrid_not_blocked_by_cpu_only_ram_pressure':True,'forge_does_not_guess_gpu_layers':True,'single_runtime_owns_cpu_gpu_split':True}}

def benchmark_plan(*,mode='AUTO',context_tokens=8192,threads=12,device='Vulkan0',port=8082)->dict[str,Any]:
    rows=[]
    for i,q in enumerate(('Q5_K_M','Q6_K')):
        rows.append({'quantization':q,'fit':hardware_fit(q),'admission':admission_plan(mode=mode,quantization=q,context_tokens=context_tokens,threads=threads,device=device,port=port+i),'benchmark_port':port+i})
    return {'schema':'phoenix.forge.phoenix-lava-benchmark-plan/v2','status':'READY' if any(x['admission']['status']=='READY_FOR_RUNTIME_FIT' and x['admission']['launch']['status']=='READY' for x in rows) else 'MODELS_REQUIRED','variants':rows,'metrics':['startup_seconds','prompt_eval_tokens_per_second','eval_tokens_per_second','total_seconds'],'automatic_execution':False,'quality_ranking_not_claimed':True}

def capabilities()->dict[str,Any]:
    return {'schema':SCHEMA,'status':'RUNTIME_DEPENDENT','runtime':RUNTIME_NAME,'foundation':lava.MODEL_ID,'features':['RUNTIME_DISCOVERY','MODEL_SELECTION','SAFE_ARGV_PLAN','LOCAL_HEALTH_PROBE','EXPLICIT_START_STOP_RESTART','READINESS_WAIT','STALE_STATE_RECONCILIATION','MANAGED_PID_IDENTITY','LOG_TAIL','RAM_FIT_ADVISORY','HYBRID_ADMISSION','Q5_Q6_BENCHMARK_PLAN'],'policy':{'no_shell':True,'no_automatic_process_start':True,'explicit_mutation_confirmation':True,'explicit_start_stop_confirmation':True,'runtime_placement_owned_by_phoenix_llama_runtime':True,'missing_model_or_runtime_blocks_launch':True,'localhost_probe_only':True,'no_vram_guess':True,'ram_pressure_does_not_block_auto_hybrid':True}}
