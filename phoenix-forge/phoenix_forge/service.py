from __future__ import annotations
from phoenix_forge.modules import detect,pulse,forensics,autopilot,certify
from phoenix_forge.models import CertificationReport

def build_report(tests=None,ai=None,vbios_path:str|None=None,*,workload:str='llm',backend:str='vulkan',runtime:str='*',model:str='*')->CertificationReport:
    tests=tests or []; ai=ai or []
    d=detect.collect();p=pulse.collect();f=forensics.analyze(d,vbios_path=vbios_path);dec=autopilot.decide(d,tests,ai,workload=workload,backend=backend,runtime=runtime,model=model)
    r=CertificationReport(detect=d,forensics=f,pulse=p,tests=tests,ai=ai,autopilot=dec,score=0);r.score=certify.score(r);return r
