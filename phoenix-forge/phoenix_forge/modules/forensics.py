from __future__ import annotations
from pathlib import Path
from phoenix_forge.models import DetectReport,ForensicsFinding,ForensicsReport
from phoenix_forge.modules.vbios import parse_vbios

GENERIC_SUBVENDORS={'1002':'AMD','10DE':'NVIDIA','8086':'Intel','0000':'Unknown/Generic'}


def analyze(detect:DetectReport, vbios_path: str | None = None)->ForensicsReport:
    findings=[]; notes=[]; flags=[]; conf=[]
    for i,g in enumerate(detect.gpus):
        if g.vendor_id and g.device_id:
            findings.append(ForensicsFinding(key=f'gpu[{i}].pci',value=f'{g.vendor_id}:{g.device_id}',confidence=.99,evidence=[g.pnp_device_id or 'Windows PnP']))
            conf.append(.99)
        if g.subsystem_vendor_id:
            label=GENERIC_SUBVENDORS.get(g.subsystem_vendor_id,'third-party/unknown')
            findings.append(ForensicsFinding(key=f'gpu[{i}].subsystem',value=f'subvendor={g.subsystem_vendor_id} ({label}) subdevice={g.subsystem_device_id or "?"}',confidence=.98,evidence=['Decoded from PCI SUBSYS']))
            conf.append(.98)
            if g.subsystem_vendor_id==g.vendor_id:
                flags.append(f'gpu[{i}]: subsystem vendor equals silicon vendor; physical board assembler remains unverified.')
        if '2048sp' in (g.name or '').lower() and (g.device_id or '').upper()=='6FDF':
            findings.append(ForensicsFinding(key=f'gpu[{i}].polaris_profile',value='Polaris-family 2048-SP identity detected',confidence=.90,evidence=[g.name,g.device_id or '']))
            conf.append(.90)

        # Cross-source consistency: Windows PnP, DXGI, Vulkan and vendor API.
        dx=g.dxgi or {}; vd=g.vendor_details or {}
        mismatches=[]
        if dx:
            try:
                if g.vendor_id and int(g.vendor_id,16)!=int(dx.get('vendor_id')): mismatches.append('DXGI vendor ID differs from PnP')
                if g.device_id and int(g.device_id,16)!=int(dx.get('device_id')): mismatches.append('DXGI device ID differs from PnP')
            except Exception: pass
            if dx.get('dedicated_video_memory_bytes'):
                findings.append(ForensicsFinding(key=f'gpu[{i}].dxgi_vram',value=f"{int(dx['dedicated_video_memory_bytes'])/1024**3:.2f} GiB dedicated VRAM",confidence=.98,evidence=['DXGI_ADAPTER_DESC1.DedicatedVideoMemory']))
        if g.vulkan_primary_device_local_bytes:
            findings.append(ForensicsFinding(key=f'gpu[{i}].vulkan_heap',value=f"{g.vulkan_primary_device_local_bytes/1024**3:.2f} GiB primary device-local heap",confidence=.96,evidence=['VkPhysicalDeviceMemoryProperties']))
        mem=vd.get('memory') if isinstance(vd,dict) else None
        if mem and mem.get('size_bytes'):
            findings.append(ForensicsFinding(key=f'gpu[{i}].adl_memory',value=f"{int(mem['size_bytes'])/1024**3:.2f} GiB {mem.get('type') or ''}".strip(),confidence=.97,evidence=['AMD ADL_Adapter_MemoryInfo_Get']))
        if mismatches:
            flags.extend(f'gpu[{i}]: {m}' for m in mismatches)
        elif dx:
            findings.append(ForensicsFinding(key=f'gpu[{i}].identity_consistency',value='PnP/DXGI identity consistent',confidence=.99,evidence=['Windows PnP','DXGI']))

    if vbios_path:
        try:
            v=parse_vbios(vbios_path)
            if v.get('pcir'):
                p=v['pcir']; findings.append(ForensicsFinding(key='vbios.pcir',value=f"{p.get('vendor_id')}:{p.get('device_id')}",confidence=.99,evidence=[str(vbios_path),'PCIR structure']))
                conf.append(.99)
            if v.get('atom'):
                a=v['atom']; findings.append(ForensicsFinding(key='vbios.atom',value=f"ATOM {a.get('format_revision')}.{a.get('content_revision')} SUBSYS {a.get('subsystem_id')}:{a.get('subsystem_vendor_id')}",confidence=.99,evidence=['ATOM ROM header']))
                conf.append(.99)
            if v.get('vbios_part_number'):
                findings.append(ForensicsFinding(key='vbios.part_number',value=str(v['vbios_part_number']),confidence=.95,evidence=['ATOMBIOS fixed metadata region']))
                conf.append(.95)
            mv=v.get('memory_vendor_string_candidates') or []
            if mv:
                findings.append(ForensicsFinding(key='vbios.memory_vendor_strings',value=', '.join(mv),confidence=.70,evidence=['Printable firmware strings; not physical chip proof']))
            if not v.get('checksum_ok'):
                flags.append('VBIOS byte checksum is non-zero; this may be valid for some images but deserves comparison with a known-good ROM.')
            findings.append(ForensicsFinding(key='vbios.sha256',value=v['sha256'],confidence=1.0,evidence=['SHA-256']))
            conf.append(1.0)
        except Exception as e:
            flags.append(f'VBIOS parse failed: {e}')

    notes += [
      'PCI and VBIOS identifiers describe silicon/firmware identity; they do not prove who physically assembled or remanufactured the board.',
      'A remanufacture assessment should combine firmware, PCB silkscreen, memory markings, VRM/controller identity and stability evidence.',
      'Phoenix Forensics reports uncertainty instead of assigning an unsupported board vendor.'
    ]
    score=round((sum(conf)/len(conf))*100) if conf else 0
    return ForensicsReport(findings=findings,notes=notes,risk_flags=flags,confidence_score=score)
