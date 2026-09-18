from __future__ import annotations

import json
import struct
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from phoenix_forge.modules import phoenix_lava_foundation_adapter as lava
from phoenix_forge.modules import phoenix_lava_model_registry as registry

SCHEMA = "phoenix.forge.phoenix-lava-artifact-qualification/v1"
ALLOWED_SOURCE_HOSTS = {"huggingface.co"}
ALLOWED_REPO_PREFIX = "/mradermacher/Mistral-Small-3.2-24B-Instruct-2506-ultra-uncensored-heretic-GGUF/"


def _source_policy(url: str | None) -> dict[str, Any]:
    if not url:
        return {"status":"SOURCE_UNRECORDED","allowed":False,"reason":"NO_SOURCE_URL"}
    u=urlparse(str(url))
    host=(u.hostname or "").lower()
    https=u.scheme.lower()=="https"
    repo_ok=u.path.startswith(ALLOWED_REPO_PREFIX)
    host_ok=host in ALLOWED_SOURCE_HOSTS
    allowed=https and host_ok and repo_ok
    return {"status":"ALLOWED" if allowed else "REJECTED","allowed":allowed,"https":https,"host":host,"host_allowed":host_ok,"repo_path_allowed":repo_ok,"path":u.path}


def _gguf_header(path: Path) -> dict[str, Any]:
    try:
        with path.open('rb') as f:
            head=f.read(24)
    except Exception as exc:
        return {"status":"READ_FAILED","error":f"{type(exc).__name__}: {exc}"}
    if len(head)<24:
        return {"status":"HEADER_TRUNCATED","bytes_read":len(head)}
    if head[:4] != b'GGUF':
        return {"status":"MAGIC_INVALID","magic_hex":head[:4].hex().upper()}
    version=struct.unpack('<I',head[4:8])[0]
    tensor_count=struct.unpack('<Q',head[8:16])[0]
    metadata_kv_count=struct.unpack('<Q',head[16:24])[0]
    plausible=(1 <= version <= 4 and tensor_count > 0 and metadata_kv_count > 0)
    return {"status":"VALID" if plausible else "STRUCTURE_SUSPICIOUS","magic":"GGUF","version":version,"tensor_count":tensor_count,"metadata_kv_count":metadata_kv_count,"plausible":plausible}


def qualify(quantization: str='Q5_K_M', *, compute_sha256: bool=True) -> dict[str, Any]:
    q=lava.variant(quantization)
    status=registry.local_status(compute_sha256=False)
    row=next((x for x in status.get('variants',[]) if x.get('quantization')==q['quantization']),None) or {}
    path=Path(row.get('path') or registry.model_root()/q['filename'])
    if not path.is_file():
        return {"schema":SCHEMA,"status":"MODEL_REQUIRED","quantization":q['quantization'],"path":str(path),"qualified":False}
    symlink=path.is_symlink()
    reg=registry.verify_model(quantization,compute_sha256=compute_sha256)
    header=_gguf_header(path)
    meta=reg.get('metadata') or {}
    source=meta.get('source_url') or q.get('source_url')
    source_policy=_source_policy(source)
    filename_ok=path.name==q['filename']
    size_ok=reg.get('status') not in {'SIZE_SUSPICIOUS','MODEL_REQUIRED'}
    hash_ok=reg.get('sha256_matches_sidecar') is not False
    header_ok=header.get('status')=='VALID'
    qualified=bool((not symlink) and filename_ok and size_ok and hash_ok and header_ok and source_policy['allowed'])
    reasons=[]
    if symlink:reasons.append('SYMLINK_FORBIDDEN')
    if not filename_ok:reasons.append('CANONICAL_FILENAME_MISMATCH')
    if not size_ok:reasons.append('SIZE_NOT_QUALIFIED')
    if not hash_ok:reasons.append('HASH_MISMATCH')
    if not header_ok:reasons.append('GGUF_HEADER_NOT_QUALIFIED')
    if not source_policy['allowed']:reasons.append('SOURCE_POLICY_REJECTED')
    return {"schema":SCHEMA,"status":"QUALIFIED" if qualified else "REJECTED","qualified":qualified,"quantization":q['quantization'],"tier":q['tier'],"path":str(path),"filename_ok":filename_ok,"symlink":symlink,"registry_verification":reg,"gguf_header":header,"source_policy":source_policy,"blocked_reasons":reasons,"policy":{"gguf_magic_required":True,"canonical_filename_required":True,"symlink_forbidden":True,"source_https_required":True,"source_allowlist_required":True,"hash_mismatch_blocks":True,"foundation_model_not_claimed_as_phoenix_trained":True}}


def matrix(*,compute_sha256: bool=False) -> dict[str, Any]:
    rows=[qualify(q,compute_sha256=compute_sha256) for q in lava.VARIANTS]
    return {"schema":"phoenix.forge.phoenix-lava-artifact-qualification-matrix/v1","status":"READY","variants":rows,"qualified_count":sum(1 for r in rows if r.get('qualified')),"policy":{"runtime_launch_should_require_qualified_artifact":True}}


def capabilities() -> dict[str, Any]:
    return {"schema":SCHEMA,"status":"COMPLETE","features":["GGUF_HEADER","CANONICAL_FILENAME","SIDE_CAR_HASH","HTTPS_SOURCE_ALLOWLIST","SYMLINK_REJECTION","Q5_Q6_MATRIX"],"policy":{"read_only_qualification":True,"does_not_download":True,"does_not_start_runtime":True}}
