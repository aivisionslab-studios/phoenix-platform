from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path
from typing import Any


def which(name: str) -> str | None:
    return shutil.which(name)


def find_native_helper(explicit: str | None = None) -> str | None:
    exe = 'phoenix-forge-native.exe' if os.name == 'nt' else 'phoenix-forge-native'
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_path = os.environ.get('PHOENIX_FORGE_NATIVE_PATH')
    if env_path:
        candidates.append(Path(env_path))
    try:
        candidates.append(Path(sys.executable).resolve().parent / exe)
    except Exception:
        pass
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.extend([
            parent / '.venv' / 'Scripts' / exe,
            parent / 'native' / 'build' / 'Release' / exe,
            parent / 'native' / 'build' / exe,
        ])
    p = shutil.which(exe)
    if p:
        candidates.append(Path(p))
    seen=set()
    for c in candidates:
        try:
            r=c.resolve()
        except Exception:
            r=c
        k=str(r).lower()
        if k in seen:
            continue
        seen.add(k)
        if r.is_file():
            return str(r)
    return None


def adaptive_vram_timeout(size_mb: int, passes: int, full_scan: bool) -> int:
    size_mb=max(16,int(size_mb)); passes=max(1,int(passes))
    if full_scan:
        # User-validated Polaris baseline was ~0.17 s/MB/pass for 8 patterns.
        # Give >2x headroom for slower hardware / OS scheduling.
        return min(7200, max(180, int(120 + size_mb * 0.40 * passes)))
    return min(1800, max(120, 90 + passes * 120))


def run(cmd: list[str], timeout: int = 20, cwd: str | None = None) -> tuple[int,str,str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout, cwd=cwd)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        out=e.stdout.decode(errors='replace') if isinstance(e.stdout,bytes) else (e.stdout or '')
        err=e.stderr.decode(errors='replace') if isinstance(e.stderr,bytes) else (e.stderr or '')
        return 124, out, (err + f'\nTIMEOUT after {timeout} seconds').strip()
    except Exception as e:
        return 1, '', str(e)

def run_supervised(cmd:list[str],timeout:int=20,cwd:str|None=None,cancel_event:Any=None,
                   poll_interval:float=.1,terminate_grace:float=3.0)->tuple[int,str,str,dict[str,Any]]:
    """Run a child and terminate it when a safety monitor requests cancellation."""
    started=time.monotonic();reason=None
    try:
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,errors='replace',cwd=cwd)
        while p.poll() is None:
            if cancel_event is not None and cancel_event.is_set():reason='SAFETY_ABORT';break
            if time.monotonic()-started>=timeout:reason='TIMEOUT';break
            time.sleep(max(.02,poll_interval))
        terminated=killed=False
        if reason:
            terminated=True;p.terminate()
            try:p.wait(timeout=max(.1,terminate_grace))
            except subprocess.TimeoutExpired:p.kill();p.wait();killed=True
        out,err=p.communicate();code=125 if reason=='SAFETY_ABORT' else (124 if reason=='TIMEOUT' else p.returncode)
        meta={'supervised':True,'termination_reason':reason,'terminated':terminated,'killed':killed,
              'duration_s':round(time.monotonic()-started,3),'pid':p.pid}
        if reason:err=(err+f'\n{reason}: Phoenix Forge stopped the workload').strip()
        return code,out,err,meta
    except Exception as exc:
        return 1,'',str(exc),{'supervised':True,'termination_reason':'LAUNCH_ERROR','terminated':False,'killed':False,'duration_s':round(time.monotonic()-started,3)}


def powershell_json(script: str) -> Any:
    if os.name != 'nt': return None
    exe = shutil.which('powershell') or shutil.which('pwsh')
    if not exe: return None
    code,out,_ = run([exe,'-NoProfile','-ExecutionPolicy','Bypass','-Command',script], timeout=30)
    if code != 0 or not out.strip(): return None
    try: return json.loads(out)
    except Exception: return None


def parse_cim_date(value: Any) -> str | None:
    if value is None:
        return None
    s=str(value)
    import re
    m=re.fullmatch(r'/Date\((\d+)\)/',s)
    if m:
        from datetime import datetime, timezone
        try:
            return datetime.fromtimestamp(int(m.group(1))/1000, tz=timezone.utc).date().isoformat()
        except Exception:
            return s
    return s or None


def parse_pnp_ids(pnp: str | None) -> dict[str,str]:
    import re
    if not pnp: return {}
    up=pnp.upper(); out={}
    for key,pat in {
        'vendor_id':r'VEN_([0-9A-F]{4})',
        'device_id':r'DEV_([0-9A-F]{4})',
        'subsys':r'SUBSYS_([0-9A-F]{8})',
        'revision_id':r'REV_([0-9A-F]{2})',
    }.items():
        m=re.search(pat,up)
        if m: out[key]=m.group(1)
    if 'subsys' in out:
        out['subsystem_device_id']=out['subsys'][:4]
        out['subsystem_vendor_id']=out['subsys'][4:]
    return out
