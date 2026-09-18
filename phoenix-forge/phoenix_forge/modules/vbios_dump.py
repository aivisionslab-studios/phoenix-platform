from __future__ import annotations
import os
from pathlib import Path
from phoenix_forge.util import which, run


def dump_amd(adapter: int = 0, out_path: str | Path = 'reports/vbios_adapter0.rom') -> tuple[bool, str]:
    """Use an installed AMDVBFlash to save VBIOS. Never flashes or unlocks ROM."""
    exe = which('amdvbflash') or which('amdvbflash.exe')
    if not exe:
        return False, 'amdvbflash not found in PATH'
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    c, o, e = run([exe, '-s', str(int(adapter)), str(p.resolve())], timeout=60)
    return c == 0 and p.exists(), (o + '\n' + e).strip()
