#!/usr/bin/env python3
"""Independent binary inventory helper. Does not decompile or copy proprietary source."""
import argparse,hashlib,subprocess,re,os
from pathlib import Path

def sh(cmd):
    try:return subprocess.run(cmd,capture_output=True,text=True,errors='replace',timeout=120).stdout
    except Exception:return ''
def main():
    ap=argparse.ArgumentParser();ap.add_argument('binary');ap.add_argument('--out',default='binary_inventory.md');a=ap.parse_args();p=Path(a.binary)
    data=p.read_bytes();sha=hashlib.sha256(data).hexdigest();fileinfo=sh(['file',str(p)]);obj=sh(['objdump','-p',str(p)]);strings=sh(['strings','-a','-n','6',str(p)])
    dlls=sorted(set(re.findall(r'DLL Name:\s+(\S+)',obj,re.I)))
    keys=['SetupDi','CM_Get','DeviceIoControl','CreateFile','Vulkan','OpenCL','ADL','NVAPI','VBIOS','Subvendor','Samsung','Hynix','Micron','GpuMemtest','HWiNFO','ORing','diskspd']
    hits=[x for x in strings.splitlines() if any(k.lower() in x.lower() for k in keys)][:800]
    md=[f'# Binary inventory: {p.name}','',f'- Size: {len(data)} bytes',f'- SHA-256: `{sha}`',f'- Format: `{fileinfo.strip()}`','','## Imported DLLs']+[f'- {x}' for x in dlls]+['','## Hardware-related strings (sample)']+[f'- `{x[:240]}`' for x in hits]
    Path(a.out).write_text('\n'.join(md)+'\n',encoding='utf-8')
if __name__=='__main__':main()
