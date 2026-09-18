#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACT = json.loads((HERE/'compatibility_contract.json').read_text(encoding='utf-8'))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--server', required=True)
    ns=ap.parse_args()
    cp=subprocess.run([ns.server,'--help'], text=True, capture_output=True, check=False)
    text=(cp.stdout or '')+'\n'+(cp.stderr or '')
    if cp.returncode not in (0,1):
        print(text[-5000:], file=sys.stderr); return 2
    missing=[x for x in CONTRACT['required_server_flags'] if x not in text]
    for value in CONTRACT['required_ngl_values']:
        if value not in text: missing.append(f'ngl-value:{value}')
    for value in CONTRACT['required_load_modes']:
        if value not in text: missing.append(f'load-mode:{value}')
    if missing:
        print('PHOENIX CLI CONTRACT FAILED')
        for x in missing: print(' -',x)
        return 3
    print('PHOENIX CLI CONTRACT OK')
    return 0

if __name__=='__main__': raise SystemExit(main())
