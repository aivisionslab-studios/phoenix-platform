from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = 'phoenix.forge.model-discovery/v1'
CALIBRATION_SCHEMA = 'phoenix.forge.model-fit-calibration/v1'
SUPPORTED_EXTENSIONS = {'.gguf', '.safetensors', '.ckpt', '.pt', '.pth', '.bin'}
_QUANT_RE = re.compile(r'(?<![A-Z0-9])(Q\d(?:_[A-Z0-9]+)*|IQ\d(?:_[A-Z0-9]+)*|FP(?:8|16|32)|BF16)(?![A-Z0-9])', re.I)


def _phoenix_root() -> Path:
    env = os.getenv('PHOENIX_ROOT') or os.getenv('PHOENIX_HOME')
    if env:
        return Path(env).expanduser()
    # .../phoenix-forge/phoenix_forge/modules/model_discovery.py -> Phoenix root is parent of phoenix-forge
    p = Path(__file__).resolve()
    for parent in p.parents:
        if parent.name.lower() == 'phoenix-forge':
            return parent.parent
    return p.parents[3]


def _candidate_roots(extra_roots: Iterable[str] | None = None) -> list[tuple[str, Path]]:
    root = _phoenix_root()
    items: list[tuple[str, Path]] = [
        ('phoenix_models', root / 'models'),
        ('phoenix_llm_models', root / 'models' / 'llm'),
        ('phoenix_diffusion_models', root / 'models' / 'diffusion'),
        ('phoenix_data_models', root / 'data' / 'models'),
    ]
    env = os.getenv('PHOENIX_MODEL_ROOTS', '')
    for i, raw in enumerate([x for x in env.split(os.pathsep) if x.strip()]):
        items.append((f'env_{i}', Path(raw).expanduser()))
    for i, raw in enumerate(extra_roots or []):
        if raw:
            items.append((f'explicit_{i}', Path(raw).expanduser()))
    seen: set[str] = set(); out: list[tuple[str, Path]] = []
    for label, path in items:
        key = str(path.resolve()) if path.exists() else str(path.absolute())
        if key.lower() in seen:
            continue
        seen.add(key.lower()); out.append((label, path))
    return out


def _gguf_header(path: Path) -> dict[str, Any]:
    try:
        with path.open('rb') as f:
            head = f.read(8)
        if len(head) >= 8 and head[:4] == b'GGUF':
            return {'format_verified': True, 'format': 'GGUF', 'gguf_version': int.from_bytes(head[4:8], 'little')}
    except OSError:
        pass
    return {'format_verified': False, 'format': path.suffix.lower().lstrip('.').upper() or 'UNKNOWN', 'gguf_version': None}


def _artifact(path: Path, root_label: str, include_paths: bool) -> dict[str, Any]:
    st = path.stat(); hdr = _gguf_header(path)
    q = _QUANT_RE.search(path.name.upper())
    fmt = hdr['format']
    workload = 'llm' if path.suffix.lower() == '.gguf' else ('image' if path.suffix.lower() in {'.safetensors', '.ckpt'} else 'unknown')
    item = {
        'id': f'{root_label}:{path.name}',
        'name': path.name,
        'extension': path.suffix.lower(),
        'size_bytes': int(st.st_size),
        'size_mb': round(st.st_size / (1024 * 1024), 2),
        'workload_hint': workload,
        'format': fmt,
        'format_verified': bool(hdr['format_verified']),
        'gguf_version': hdr['gguf_version'],
        'quantization': q.group(1).upper() if q else None,
        'quantization_evidence': 'FILENAME_ONLY' if q else 'UNKNOWN',
        'root_source': root_label,
        'mtime': st.st_mtime,
    }
    if include_paths:
        item['path'] = str(path.resolve())
    return item


def discover(*, extra_roots: Iterable[str] | None = None, include_paths: bool = False, max_files: int = 500) -> dict[str, Any]:
    max_files = max(1, min(int(max_files or 500), 5000))
    roots = _candidate_roots(extra_roots)
    artifacts: list[dict[str, Any]] = []; root_status = []
    for label, root in roots:
        exists = root.exists() and root.is_dir()
        root_status.append({'source': label, 'exists': exists, **({'path': str(root.resolve())} if include_paths else {})})
        if not exists:
            continue
        try:
            for p in root.rglob('*'):
                if len(artifacts) >= max_files:
                    break
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                    try: artifacts.append(_artifact(p, label, include_paths))
                    except OSError: continue
        except OSError:
            continue
        if len(artifacts) >= max_files:
            break
    artifacts.sort(key=lambda x: (x['workload_hint'], x['name'].lower()))
    return {
        'schema': SCHEMA,
        'status': 'DISCOVERED' if artifacts else 'NO_MODELS_FOUND',
        'generated_at': time.time(),
        'count': len(artifacts),
        'truncated': len(artifacts) >= max_files,
        'roots': root_status,
        'models': artifacts,
        'policy': {
            'read_only': True,
            'no_model_download': True,
            'no_model_delete': True,
            'no_dispatch': True,
            'absolute_paths_hidden_by_default': True,
            'filename_quantization_is_not_binary_metadata_proof': True,
            'model_name_alone_never_proves_fit': True,
        },
    }


def _calibration_path() -> Path:
    custom = os.getenv('PHOENIX_FORGE_MODEL_CALIBRATION_PATH')
    return Path(custom).expanduser() if custom else Path.home() / '.phoenix-forge' / 'model-fit-calibration.jsonl'


def record_calibration(*, model_id: str, workload: str, observed_peak_vram_mb: int = 0,
                       observed_peak_ram_mb: int = 0, context_tokens: int = 0,
                       width: int = 0, height: int = 0, backend: str = 'vulkan',
                       outcome: str = 'SUCCESS') -> dict[str, Any]:
    entry = {
        'schema': CALIBRATION_SCHEMA,
        'timestamp': time.time(),
        'model_id': str(model_id), 'workload': str(workload).lower(), 'backend': str(backend),
        'observed_peak_vram_mb': max(0, int(observed_peak_vram_mb or 0)) or None,
        'observed_peak_ram_mb': max(0, int(observed_peak_ram_mb or 0)) or None,
        'context_tokens': max(0, int(context_tokens or 0)) or None,
        'width': max(0, int(width or 0)) or None, 'height': max(0, int(height or 0)) or None,
        'outcome': str(outcome).upper(),
    }
    path = _calibration_path(); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False, separators=(',', ':')) + '\n')
    return {'schema': CALIBRATION_SCHEMA, 'status': 'RECORDED', 'entry': entry, 'policy': {'advisory_only': True, 'no_dispatch': True}}


def calibration_history(*, model_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    path = _calibration_path(); rows: list[dict[str, Any]] = []
    if path.exists():
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                try: row = json.loads(line)
                except Exception: continue
                if model_id and row.get('model_id') != model_id: continue
                rows.append(row)
        except OSError: pass
    rows = rows[-max(1, min(int(limit or 100), 1000)):]
    return {'schema': CALIBRATION_SCHEMA, 'status': 'HISTORY', 'count': len(rows), 'entries': rows, 'policy': {'observations_do_not_prove_future_fit': True}}


def calibrated_requirement(*, model_id: str, baseline_vram_mb: int | None = None, safety_margin: float = 1.08) -> dict[str, Any]:
    hist = calibration_history(model_id=model_id, limit=200)['entries']
    good = [int(x['observed_peak_vram_mb']) for x in hist if x.get('observed_peak_vram_mb') and x.get('outcome') == 'SUCCESS']
    observed = max(good) if good else None
    baseline = int(baseline_vram_mb or 0) or None
    candidates = [x for x in [observed, baseline] if x]
    required = int(max(candidates) * max(1.0, float(safety_margin))) if candidates else None
    return {
        'schema': 'phoenix.forge.model-fit-calibrated-requirement/v1',
        'model_id': model_id,
        'baseline_vram_mb': baseline,
        'observed_success_peak_vram_mb': observed,
        'sample_count': len(good),
        'calibrated_min_vram_mb': required,
        'status': 'CALIBRATED' if observed else ('BASELINE_ONLY' if baseline else 'UNKNOWN'),
        'policy': {'historical_success_is_evidence_not_guarantee': True, 'safety_margin': max(1.0, float(safety_margin)), 'advisory_only': True},
    }
