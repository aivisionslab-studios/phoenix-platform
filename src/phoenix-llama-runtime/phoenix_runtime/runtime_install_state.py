from __future__ import annotations
import argparse, hashlib, json, os, platform
from datetime import datetime, timezone
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = RUNTIME_ROOT / 'build' / 'phoenix_runtime_build.json'
LOCK_FILE = RUNTIME_ROOT / 'phoenix_runtime' / 'upstream.lock.json'
INTEGRITY_FILE = RUNTIME_ROOT / 'phoenix_runtime' / 'source_integrity.json'


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def source_fingerprint() -> str:
    h = hashlib.sha256()
    for path in (LOCK_FILE, INTEGRITY_FILE):
        if not path.is_file():
            raise FileNotFoundError(path)
        h.update(path.name.encode('utf-8'))
        h.update(path.read_bytes())
    return h.hexdigest()


def write_state(server: Path) -> dict:
    server = server.resolve()
    if not server.is_file():
        raise FileNotFoundError(server)
    state = {
        'schema': 1,
        'runtime': 'Phoenix Llama Runtime Stable',
        'source_fingerprint': source_fingerprint(),
        'server_sha256': _sha256(server),
        'server_relative_path': server.relative_to(RUNTIME_ROOT).as_posix(),
        'platform': platform.platform(),
        'built_at_utc': datetime.now(timezone.utc).isoformat(),
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(tmp, STATE_FILE)
    return state


def verify_state(server: Path) -> tuple[bool, str]:
    server = server.resolve()
    if not server.is_file():
        return False, f'llama-server ausente: {server}'
    if not STATE_FILE.is_file():
        return False, 'build stamp ausente'
    try:
        state = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        expected_source = source_fingerprint()
    except Exception as exc:
        return False, f'estado de build inválido: {exc}'
    if state.get('source_fingerprint') != expected_source:
        return False, 'source do runtime mudou desde a compilação'
    if state.get('server_sha256') != _sha256(server):
        return False, 'hash do llama-server difere do build validado'
    return True, 'ok'


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('write', 'verify'):
        p = sub.add_parser(name)
        p.add_argument('--server', required=True)
    args = ap.parse_args()
    server = Path(args.server)
    if args.cmd == 'write':
        state = write_state(server)
        print(json.dumps(state, ensure_ascii=False))
        return 0
    ok, reason = verify_state(server)
    print('PHOENIX_RUNTIME_BUILD_OK' if ok else f'PHOENIX_RUNTIME_BUILD_INVALID: {reason}')
    return 0 if ok else 2

if __name__ == '__main__':
    raise SystemExit(main())
