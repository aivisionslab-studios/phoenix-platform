from __future__ import annotations
from phoenix_forge import __version__

import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from phoenix_forge.modules import phoenix_lava_foundation_adapter as lava

SCHEMA = "phoenix.forge.phoenix-lava-model-registry/v2"
DOWNLOAD_SCHEMA = "phoenix.forge.phoenix-lava-download/v2"


def _phoenix_root() -> Path:
    for key in ("PHOENIX_ROOT", "PHOENIX_HOME"):
        v=os.getenv(key)
        if v: return Path(v).expanduser().resolve()
    p=Path(__file__).resolve()
    for parent in p.parents:
        if parent.name.lower()=="phoenix-forge": return parent.parent.resolve()
    return p.parents[3].resolve()


def model_root() -> Path:
    explicit=os.getenv("PHOENIX_LAVA_MODEL_DIR") or os.getenv("PHOENIX_MODELS")
    return Path(explicit).expanduser().resolve() if explicit else (_phoenix_root()/"models"/"lava").resolve()


def registry_path() -> Path: return model_root()/"registry.json"
def _metadata_path(q: str) -> Path: return model_root()/(lava.variant(q)["filename"]+".phoenix.json")


def _sha256(path: Path, chunk_size: int=8*1024*1024) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        while True:
            b=f.read(chunk_size)
            if not b: break
            h.update(b)
    return h.hexdigest().upper()


def _safe_destination(q: str) -> Path:
    meta=lava.variant(q); base=model_root(); dest=(base/meta['filename']).resolve()
    if base!=dest.parent: raise RuntimeError('Phoenix LaVa destination escaped canonical model root')
    return dest


def _probe_free_space(base: Path) -> int:
    probe=base
    while not probe.exists() and probe.parent!=probe: probe=probe.parent
    return shutil.disk_usage(probe).free


def source_probe(quantization: str='Q5_K_M', *, timeout_s: float=10.0) -> dict[str,Any]:
    q=lava.variant(quantization); url=q['source_url']
    headers={'User-Agent':f'Phoenix-Forge/{__version__}','Accept-Encoding':'identity'}
    try:
        req=urllib.request.Request(url,headers=headers,method='HEAD')
        with urllib.request.urlopen(req,timeout=max(2.0,float(timeout_s))) as r:
            hdr=dict(r.headers.items()); code=int(getattr(r,'status',200)); final=getattr(r,'url',url)
    except Exception as first:
        try:
            headers['Range']='bytes=0-0'; req=urllib.request.Request(url,headers=headers,method='GET')
            with urllib.request.urlopen(req,timeout=max(2.0,float(timeout_s))) as r:
                hdr=dict(r.headers.items()); code=int(getattr(r,'status',200)); final=getattr(r,'url',url); r.read(1)
        except Exception as exc:
            return {'schema':'phoenix.forge.phoenix-lava-source-probe/v1','status':'UNREACHABLE','quantization':q['quantization'],'source_url':url,'error':type(exc).__name__,'first_error':type(first).__name__}
    cl=hdr.get('Content-Length'); cr=hdr.get('Content-Range'); total=None
    if cr and '/' in cr:
        try: total=int(cr.rsplit('/',1)[1])
        except Exception: pass
    if total is None and cl:
        try: total=int(cl)
        except Exception: pass
    return {'schema':'phoenix.forge.phoenix-lava-source-probe/v1','status':'READY','quantization':q['quantization'],'source_url':url,'resolved_url':str(final),'http_status':code,'content_length':total,'etag':hdr.get('ETag'),'last_modified':hdr.get('Last-Modified'),'accept_ranges':hdr.get('Accept-Ranges'),'content_type':hdr.get('Content-Type')}


def download_plan(quantization: str='Q5_K_M', *, probe_remote: bool=False) -> dict[str,Any]:
    q=lava.variant(quantization); dest=_safe_destination(quantization); base=model_root()
    approx=int(float(q['approx_size_gb'])*1024**3); remote=source_probe(quantization) if probe_remote else None
    expected=int(remote.get('content_length') or approx) if remote and remote.get('status')=='READY' else approx
    need=int(expected*1.08); free=_probe_free_space(base)
    return {'schema':'phoenix.forge.phoenix-lava-download-plan/v2','status':'READY' if free>=need else 'INSUFFICIENT_DISK_SPACE','quantization':q['quantization'],'tier':q['tier'],'source_url':q['source_url'],'destination':str(dest),'partial_path':str(dest)+'.part','approx_size_gb':q['approx_size_gb'],'expected_bytes':expected,'required_free_bytes':need,'free_bytes':free,'remote_probe':remote,'explicit_confirmation_required':True,'automatic_download':False,'resume_supported':True}


def verify_model(quantization: str='Q5_K_M', *, compute_sha256: bool=True) -> dict[str,Any]:
    q=lava.variant(quantization); p=_safe_destination(quantization); mp=_metadata_path(quantization)
    if not p.is_file(): return {'schema':'phoenix.forge.phoenix-lava-model-verification/v1','status':'MODEL_REQUIRED','quantization':q['quantization'],'path':str(p)}
    size=p.stat().st_size; minimum=int(float(q['approx_size_gb'])*1024**3*.80); digest=_sha256(p) if compute_sha256 else None
    meta=None; meta_error=None
    if mp.is_file():
        try: meta=json.loads(mp.read_text(encoding='utf-8'))
        except Exception as exc: meta_error=type(exc).__name__
    sha_match=None
    if meta and digest and meta.get('sha256'): sha_match=str(meta['sha256']).upper()==digest.upper()
    status='VERIFIED' if size>=minimum and sha_match is not False else ('HASH_MISMATCH' if sha_match is False else 'SIZE_SUSPICIOUS')
    return {'schema':'phoenix.forge.phoenix-lava-model-verification/v1','status':status,'quantization':q['quantization'],'path':str(p),'size_bytes':size,'minimum_reasonable_bytes':minimum,'sha256':digest,'metadata_path':str(mp),'metadata':meta,'metadata_error':meta_error,'sha256_matches_sidecar':sha_match,'foundation_model_not_phoenix_trained':True}


def local_status(*, compute_sha256: bool=False) -> dict[str,Any]:
    rows=[]
    for quant in lava.VARIANTS:
        q=lava.variant(quant); p=_safe_destination(quant); row={'quantization':quant,'tier':q['tier'],'path':str(p),'exists':p.is_file()}
        if p.is_file():
            row.update({'size_bytes':p.stat().st_size,'size_gb':round(p.stat().st_size/1024**3,3)})
            if compute_sha256: row['verification']=verify_model(quant,compute_sha256=True)
        rows.append(row)
    return {'schema':SCHEMA,'status':'READY','model_root':str(model_root()),'variants':rows,'installed_count':sum(1 for x in rows if x['exists']),'policy':{'downloads_are_explicit':True,'partial_files_are_never_registered':True,'sha256_is_computed_after_download':True,'source_url_is_recorded':True,'external_import_requires_confirmation':True,'symlink_import_forbidden':True}}


def _write_sidecar(quantization: str, path: Path, digest: str, *, source_url: str|None, origin: str, extra: dict[str,Any]|None=None) -> dict[str,Any]:
    q=lava.variant(quantization)
    meta={'schema':'phoenix.forge.phoenix-lava-model-artifact/v2','model_id':lava.MODEL_ID,'family':lava.FAMILY,'quantization':q['quantization'],'tier':q['tier'],'source_url':source_url,'origin':origin,'path':str(path),'size_bytes':path.stat().st_size,'sha256':digest,'registered_at':time.time(),'training_status':'FOUNDATION_MODEL_NOT_PHOENIX_TRAINED'}
    if extra: meta.update(extra)
    _metadata_path(quantization).write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')
    registry_path().write_text(json.dumps(local_status(compute_sha256=False),indent=2,ensure_ascii=False),encoding='utf-8')
    return meta


def download(quantization: str='Q5_K_M', *, confirm: bool=False, resume: bool=True, timeout_s: float=60.0) -> dict[str,Any]:
    if not confirm: return {'schema':DOWNLOAD_SCHEMA,'status':'CONFIRMATION_REQUIRED','plan':download_plan(quantization)}
    plan=download_plan(quantization,probe_remote=True)
    if plan['status']!='READY': return {'schema':DOWNLOAD_SCHEMA,'status':plan['status'],'plan':plan}
    dest=Path(plan['destination']); part=Path(plan['partial_path']); dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.is_file(): return {'schema':DOWNLOAD_SCHEMA,'status':'ALREADY_PRESENT','verification':verify_model(quantization)}
    offset=part.stat().st_size if (resume and part.is_file()) else 0
    headers={'User-Agent':f'Phoenix-Forge/{__version__}','Accept-Encoding':'identity'}
    if offset>0: headers['Range']=f'bytes={offset}-'
    req=urllib.request.Request(plan['source_url'],headers=headers)
    mode='ab' if offset>0 else 'wb'; expected_total=plan.get('expected_bytes')
    with urllib.request.urlopen(req,timeout=max(5.0,float(timeout_s))) as r, part.open(mode) as f:
        code=int(getattr(r,'status',200)); content_range=r.headers.get('Content-Range')
        if offset>0 and code!=206:
            f.close(); part.unlink(missing_ok=True); return download(quantization,confirm=True,resume=False,timeout_s=timeout_s)
        if content_range and '/' in content_range:
            try: expected_total=int(content_range.rsplit('/',1)[1])
            except Exception: pass
        while True:
            b=r.read(8*1024*1024)
            if not b: break
            f.write(b)
    size=part.stat().st_size; q=lava.variant(quantization); minimum=int(float(q['approx_size_gb'])*1024**3*.80)
    if expected_total and size!=int(expected_total): return {'schema':DOWNLOAD_SCHEMA,'status':'INCOMPLETE','partial_path':str(part),'size_bytes':size,'expected_bytes':int(expected_total),'resume_available':True}
    if size<minimum: return {'schema':DOWNLOAD_SCHEMA,'status':'INCOMPLETE','partial_path':str(part),'size_bytes':size,'minimum_reasonable_bytes':minimum,'resume_available':True}
    digest=_sha256(part); os.replace(part,dest)
    meta=_write_sidecar(quantization,dest,digest,source_url=q['source_url'],origin='DOWNLOADED',extra={'remote_probe':plan.get('remote_probe')})
    return {'schema':DOWNLOAD_SCHEMA,'status':'DOWNLOADED_AND_REGISTERED','artifact':meta,'verification':verify_model(quantization)}


def import_local(source_path: str, quantization: str='Q5_K_M', *, confirm: bool=False, copy_file: bool=True) -> dict[str,Any]:
    raw=Path(source_path).expanduser(); q=lava.variant(quantization); dest=_safe_destination(quantization)
    if raw.is_symlink(): return {'schema':'phoenix.forge.phoenix-lava-model-import/v1','status':'SYMLINK_SOURCE_FORBIDDEN','source':str(raw)}
    src=raw.resolve()
    if not confirm: return {'schema':'phoenix.forge.phoenix-lava-model-import/v1','status':'CONFIRMATION_REQUIRED','source':str(src),'destination':str(dest),'quantization':q['quantization'],'copy_file':bool(copy_file)}
    if not src.is_file() or src.is_symlink(): return {'schema':'phoenix.forge.phoenix-lava-model-import/v1','status':'INVALID_SOURCE','source':str(src)}
    minimum=int(float(q['approx_size_gb'])*1024**3*.80)
    if src.stat().st_size<minimum: return {'schema':'phoenix.forge.phoenix-lava-model-import/v1','status':'SIZE_SUSPICIOUS','source':str(src),'size_bytes':src.stat().st_size,'minimum_reasonable_bytes':minimum}
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists() and src!=dest: return {'schema':'phoenix.forge.phoenix-lava-model-import/v1','status':'DESTINATION_EXISTS','destination':str(dest)}
    if src!=dest:
        if not copy_file: return {'schema':'phoenix.forge.phoenix-lava-model-import/v1','status':'COPY_REQUIRED','source':str(src),'destination':str(dest)}
        tmp=Path(str(dest)+'.importing'); shutil.copy2(src,tmp); os.replace(tmp,dest)
    digest=_sha256(dest); meta=_write_sidecar(quantization,dest,digest,source_url=None,origin='LOCAL_IMPORT',extra={'source_path':str(src)})
    return {'schema':'phoenix.forge.phoenix-lava-model-import/v1','status':'IMPORTED_AND_REGISTERED','artifact':meta,'verification':verify_model(quantization)}


def partial_status(quantization: str='Q5_K_M') -> dict[str,Any]:
    dest=_safe_destination(quantization); part=Path(str(dest)+'.part')
    return {'schema':'phoenix.forge.phoenix-lava-partial/v1','status':'PARTIAL_PRESENT' if part.is_file() else 'NO_PARTIAL','quantization':lava.variant(quantization)['quantization'],'partial_path':str(part),'size_bytes':part.stat().st_size if part.is_file() else 0}


def discard_partial(quantization: str='Q5_K_M', *, confirm: bool=False) -> dict[str,Any]:
    st=partial_status(quantization)
    if not confirm: return {'schema':'phoenix.forge.phoenix-lava-partial-discard/v1','status':'CONFIRMATION_REQUIRED','partial':st}
    p=Path(st['partial_path'])
    if not p.is_file(): return {'schema':'phoenix.forge.phoenix-lava-partial-discard/v1','status':'NOTHING_TO_DISCARD'}
    size=p.stat().st_size; p.unlink()
    return {'schema':'phoenix.forge.phoenix-lava-partial-discard/v1','status':'DISCARDED','bytes_removed':size}


def capabilities() -> dict[str,Any]:
    return {'schema':SCHEMA,'status':'READY','model_root':str(model_root()),'variants':list(lava.VARIANTS),'features':['CANONICAL_MODEL_ROOT','Q5_Q6_REGISTRY','EXPLICIT_DOWNLOAD_PLAN','REMOTE_SOURCE_PROBE','RESUMABLE_DOWNLOAD','CONTENT_LENGTH_VALIDATION','POST_DOWNLOAD_SHA256','SIDECAR_PROVENANCE','LOCAL_IMPORT','PARTIAL_LIFECYCLE','MODEL_VERIFICATION'],'policy':{'no_install_time_download':True,'explicit_confirmation_required':True,'no_shell':True,'foundation_model_not_claimed_as_phoenix_trained':True,'symlink_import_forbidden':True,'no_silent_partial_delete':True}}
