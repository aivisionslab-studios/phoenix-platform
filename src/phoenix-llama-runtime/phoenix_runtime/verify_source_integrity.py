#!/usr/bin/env python3
import hashlib, json, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
manifest=json.loads((HERE/'source_integrity.json').read_text(encoding='utf-8'))
failed=[]
for rel, expected in manifest['critical_source_sha256'].items():
    p=ROOT/rel
    if not p.is_file():
        failed.append((rel,'missing',expected)); continue
    got=hashlib.sha256(p.read_bytes()).hexdigest()
    if got != expected: failed.append((rel,got,expected))
if failed:
    print('PHOENIX SOURCE INTEGRITY FAILED')
    for rel, got, exp in failed: print(f' - {rel}: got={got} expected={exp}')
    raise SystemExit(4)
print('PHOENIX SOURCE INTEGRITY OK')
print('Pinned upstream commit:', manifest['upstream_commit'])
