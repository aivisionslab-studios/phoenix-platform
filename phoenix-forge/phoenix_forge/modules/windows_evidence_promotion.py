from __future__ import annotations
import hashlib,json,os,platform,time,uuid
from pathlib import Path
from typing import Any
from phoenix_forge import __version__
from phoenix_forge.modules import project_hygiene, privileged_wdk_diagnostics, capability_registry
SCHEMA="phoenix.forge.windows-verification-ledger/v1"
MAP_SCHEMA="phoenix.forge.capability-evidence-map/v1"
CTX_SCHEMA="phoenix.forge.windows-run-context/v1"
EVIDENCE_MAP=[
 {"capability_id":"release.hygiene.powershell_parser_gate","test_identity":"installer.powershell_parser_gate","verification_status":"WINDOWS_VERIFIED","requires":["windows","parser_gate_pass"]},
 {"capability_id":"release.hygiene.public_guard","test_identity":"project_hygiene.windows_inventory","verification_status":"WINDOWS_VERIFIED","requires":["windows","cumulative_selftests_pass","project_hygiene_ready"]},
 {"capability_id":"provider.privileged.wdk_diagnostics","test_identity":"privileged_wdk_diagnostics.windows_probe","verification_status":"WINDOWS_VERIFIED","requires":["windows","cumulative_selftests_pass","wdk_diagnostics_executed"]},
]
def phoenix_root()->Path:
    env=os.environ.get('PHOENIX_ROOT')
    if env:return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[3]
def audit_dir()->Path:
    p=phoenix_root()/'forge_audit';p.mkdir(parents=True,exist_ok=True);return p
def ledger_path()->Path:return audit_dir()/'PHOENIX_WINDOWS_VERIFICATION_LEDGER.json'
def map_path()->Path:return audit_dir()/'PHOENIX_CAPABILITY_EVIDENCE_MAP.json'
def _is_windows()->bool:return os.name=='nt'
def _sanitized_host_id()->str:
    raw='|'.join([platform.machine(),platform.processor(),os.environ.get('PROCESSOR_IDENTIFIER','')])
    return hashlib.sha256(raw.encode('utf-8',errors='ignore')).hexdigest()[:24]
def evidence_map()->dict[str,Any]:
    ids={str(x.get('id')) for x in capability_registry.build().get('capabilities',[])}
    rows=[]
    for row in EVIDENCE_MAP:
        r=dict(row);r['capability_exists']=r['capability_id'] in ids;rows.append(r)
    return {"schema":MAP_SCHEMA,"forge_version":__version__,"mappings":rows,
      "policy":{"capability_by_capability":True,"complete_does_not_imply_verified":True,"installer_pass_does_not_promote_all":True,"hardware_requires_hardware_evidence":True}}
def _load_json(path:str|Path)->dict[str,Any]:
    # Windows PowerShell 5.1 Set-Content -Encoding UTF8 emits a UTF-8 BOM.
    # utf-8-sig accepts both BOM and non-BOM UTF-8 while preserving strict JSON parsing.
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def _read_context(path:str|Path)->dict[str,Any]:
    p=Path(path);d=_load_json(p)
    if d.get('schema')!=CTX_SCHEMA:raise ValueError('invalid run-context schema')
    if d.get('forge_version')!=__version__:raise ValueError('run-context forge_version mismatch')
    if not d.get('windows'):raise ValueError('run-context is not Windows evidence')
    return d
def _existing()->dict[str,Any]:
    p=ledger_path()
    if not p.exists():return {"schema":SCHEMA,"entries":[]}
    try:
        d=_load_json(p)
        return d if d.get('schema')==SCHEMA else {"schema":SCHEMA,"entries":[]}
    except Exception:return {"schema":SCHEMA,"entries":[]}
def promote(run_context:str|Path)->dict[str,Any]:
    ctx=_read_context(run_context)
    if not _is_windows():raise RuntimeError('Windows evidence promotion requires Windows')
    ph=project_hygiene.capabilities(); wd=privileged_wdk_diagnostics.collect()
    facts={
      'windows':True,
      'parser_gate_pass':bool(ctx.get('parser_gate_pass')),
      'release_truth_pass':bool(ctx.get('release_truth_pass')),
      'cumulative_selftests_pass':bool(ctx.get('cumulative_selftests_pass')),
      'startup_integrity_pass':bool(ctx.get('startup_integrity_pass')),
      'project_hygiene_ready':ph.get('status')=='READY',
      'wdk_diagnostics_executed':bool(wd.get('checks',{}).get('windows')) and wd.get('status')!='WINDOWS_CONTEXT_REQUIRED',
    }
    run_id=str(ctx.get('run_id') or uuid.uuid4())
    now=time.time(); entries=[]; blocked=[]
    reg={str(x.get('id')):x for x in capability_registry.build().get('capabilities',[])}
    for m in EVIDENCE_MAP:
        cid=m['capability_id']; req=m['requires']; missing=[x for x in req if not facts.get(x)]
        if cid not in reg:missing.append('capability_missing_from_registry')
        if missing:
            blocked.append({'capability_id':cid,'missing_requirements':missing});continue
        entries.append({
          'capability_id':cid,'verification_status':'WINDOWS_VERIFIED','evidence_class':'WINDOWS_RUNTIME',
          'run_id':run_id,'forge_version':__version__,'test_identity':m['test_identity'],'recorded_at':now,
          'host_id_sanitized':_sanitized_host_id(),'os':{'system':platform.system(),'release':platform.release(),'version':platform.version()},
          'evidence':{'run_context':{k:ctx.get(k) for k in ('parser_gate_pass','release_truth_pass','cumulative_selftests_pass','startup_integrity_pass')},
                      'project_hygiene_status':ph.get('status'),'wdk_diagnostics_status':wd.get('status')},
          'provenance':{'source':'real_windows_install_run','context_path':str(Path(run_context).resolve())},'revoked':False})
    led=_existing(); old=[e for e in led.get('entries',[]) if not (e.get('forge_version')==__version__ and e.get('run_id')==run_id)]
    result={"schema":SCHEMA,"forge_version":__version__,"generated_at":now,"run_id":run_id,"entries":old+entries,"promoted_count":len(entries),"blocked":blocked,
      "policy":{"capability_by_capability":True,"no_hardware_promotion_without_hardware_evidence":True,"decision_influence":"DISABLED","revocation_supported":True}}
    ledger_path().write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    map_path().write_text(json.dumps(evidence_map(),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return result
def current_promotions()->dict[str,str]:
    led=_existing(); out={}
    if led.get('forge_version') not in (None,__version__):return out
    for e in led.get('entries',[]):
        if e.get('forge_version')==__version__ and not e.get('revoked') and e.get('verification_status')=='WINDOWS_VERIFIED':out[str(e.get('capability_id'))]='WINDOWS_VERIFIED'
    return out
def revoke(run_id:str,reason:str)->dict[str,Any]:
    led=_existing();n=0
    for e in led.get('entries',[]):
        if e.get('run_id')==run_id and not e.get('revoked'):
            e['revoked']=True;e['revoked_at']=time.time();e['revoke_reason']=reason;n+=1
    led['updated_at']=time.time();ledger_path().write_text(json.dumps(led,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return {'schema':'phoenix.forge.evidence-revoke/v1','run_id':run_id,'revoked_entries':n,'reason':reason}
def status()->dict[str,Any]:
    led=_existing(); return {'schema':SCHEMA,'forge_version':__version__,'ledger_path':str(ledger_path()),'promotions':current_promotions(),'entry_count':len(led.get('entries',[])),'policy':{'decision_influence':'DISABLED'}}
