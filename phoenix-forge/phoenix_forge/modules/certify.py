from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime,timezone
from phoenix_forge.models import CertificationReport

def score(r:CertificationReport)->int:
    s=25
    if r.detect.gpus:s+=10
    if r.detect.vulkan_available:s+=15
    if r.forensics.confidence_score:s+=round(r.forensics.confidence_score*.10)
    gpu_tests=[t for t in r.tests if ('GPU' in t.module or 'VRAM' in t.module)]
    other_tests=[t for t in r.tests if t not in gpu_tests]
    if gpu_tests:s+=round(20*sum(t.passed for t in gpu_tests)/len(gpu_tests))
    if other_tests:s+=round(10*sum(t.passed for t in other_tests)/len(other_tests))
    if r.ai:s+=round(10*sum(a.passed for a in r.ai)/len(r.ai))
    if any((not t.passed) and str(t.metrics.get('status') or '').upper() not in {'TIMEOUT','ALLOCATION_FAILED','BUDGET_EXHAUSTED','NATIVE_HELPER_MISSING'} for t in gpu_tests):s-=15
    return max(0,min(100,s))

def to_markdown(r:CertificationReport)->str:
    d=r.detect; lines=['# Phoenix Forge Certificate','',f'Generated: {datetime.now(timezone.utc).isoformat()}',f'Score: **{r.score}/100**',f'Autopilot: **{r.autopilot.mode}** ({r.autopilot.confidence:.0%})','','## Phoenix Detect',f'- Host: {d.hostname}',f'- OS: {d.os} {d.os_version}',f'- CPU: {d.cpu}',f'- RAM: {d.ram_total_bytes/1024**3:.1f} GB',f"- Vulkan: {'PASS' if d.vulkan_available else 'NOT DETECTED'}"]
    for i,g in enumerate(d.gpus):
        heaps=', '.join(f"{h.get('size_bytes',0)/1024**3:.2f} GiB{' device-local' if h.get('device_local') else ''}" for h in g.vulkan_memory_heaps) or 'n/a'
        lines += [f'- GPU {i}: {g.name}',f"  - PCI: {g.vendor_id or '?'}:{g.device_id or '?'} / SUBSYS {g.subsystem_device_id or '?'}:{g.subsystem_vendor_id or '?'}",f'  - Driver: {g.driver_version or "?"}',f'  - WMI AdapterRAM (fallback/low confidence): {(g.adapter_ram_bytes or 0)/1024**3:.1f} GiB',f'  - Vulkan primary device-local heap: {(g.vulkan_primary_device_local_bytes or 0)/1024**3:.2f} GiB',f'  - Vulkan heaps: {heaps}']
    lines += ['','## Phoenix Forensics',f'Confidence: **{r.forensics.confidence_score}/100**']
    for x in r.forensics.findings:lines.append(f'- {x.key}: {x.value} ({x.confidence:.0%})')
    for x in r.forensics.risk_flags:lines.append(f'- ⚠ {x}')
    lines += ['','## Phoenix Pulse',f'- CPU: {r.pulse.cpu_percent}%',f'- RAM: {r.pulse.ram_percent}%',f'- CPU frequency: {r.pulse.cpu_freq_mhz or "n/a"} MHz']
    if r.pulse.gpu: lines.append(f'- GPU telemetry records: {len(r.pulse.gpu)}')
    lines += ['','## Phoenix Crucible / Memory']
    for t in r.tests:lines.append(f"- {t.module}: **{'PASS' if t.passed else 'FAIL'}** — {t.duration_s:.2f}s — `{json.dumps(t.metrics,ensure_ascii=False)}`")
    lines += ['','## Phoenix AI Bench']
    for a in r.ai:lines.append(f"- {a.backend}: **{'PASS' if a.passed else 'FAIL'}** — {a.latency_s:.2f}s — TPS={a.tokens_per_second}")
    lines += ['','## Phoenix Autopilot']+[f'- {x}' for x in r.autopilot.reasons]+[f"- Policy: `{json.dumps(r.autopilot.policy,ensure_ascii=False)}`"]
    return '\n'.join(lines)+'\n'

def write(r:CertificationReport,out_dir:str|Path):
    p=Path(out_dir);p.mkdir(parents=True,exist_ok=True)
    j=p/'phoenix_forge_certificate.json';m=p/'phoenix_forge_certificate.md';policy=p/'phoenix_forge_runtime_policy.json'
    j.write_text(r.model_dump_json(indent=2),encoding='utf-8');m.write_text(to_markdown(r),encoding='utf-8');policy.write_text(json.dumps(r.autopilot.policy,ensure_ascii=False,indent=2),encoding='utf-8')
    return j,m,policy
