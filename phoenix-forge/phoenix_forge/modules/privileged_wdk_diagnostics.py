from __future__ import annotations
import os, shutil
from pathlib import Path
from typing import Any
SCHEMA="phoenix.forge.privileged-wdk-diagnostics/v1"
def _exists(p:Path)->bool:
    try:return p.exists()
    except Exception:return False
def collect()->dict[str,Any]:
    is_win=os.name=='nt'
    pf86=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))
    vswhere=pf86/'Microsoft Visual Studio/Installer/vswhere.exe'
    kits=pf86/'Windows Kits/10'
    inc=kits/'Include'; lib=kits/'Lib'; binroot=kits/'bin'
    versions=[]
    if _exists(inc):
        try: versions=sorted([p.name for p in inc.iterdir() if p.is_dir()])
        except Exception: pass
    project=Path(__file__).resolve().parents[2]/'providers'/'phoenix_privileged_driver_windows'/'PhoenixForgePrivileged.vcxproj'
    source=project.parent
    checks={
      'windows':is_win,'vswhere':_exists(vswhere),'wdk_include':_exists(inc),'wdk_lib':_exists(lib),'wdk_bin':_exists(binroot),
      'driver_project':_exists(project),'driver_source':_exists(source/'driver.c'),'abi_header':_exists(source/'phoenix_privileged_abi.h'),
      'inf':_exists(source/'PhoenixForgePrivileged.inf'),'build_script':_exists(source/'BUILD_WDK.ps1'),'preflight_script':_exists(source/'WDK_PREFLIGHT.ps1'),
      'diagnose_script':_exists(source/'DIAGNOSE_WDK.ps1'),'cmake':bool(shutil.which('cmake')) if is_win else False,
    }
    source_ready=all(checks[k] for k in ('driver_project','driver_source','abi_header','inf','build_script','preflight_script','diagnose_script'))
    wdk_present=checks['wdk_include'] and checks['wdk_lib'] and checks['wdk_bin']
    if not is_win: status='WINDOWS_CONTEXT_REQUIRED'
    elif not source_ready: status='SOURCE_INCOMPLETE'
    elif not wdk_present: status='WDK_NOT_FOUND'
    elif not checks['vswhere']: status='VSWHERE_NOT_FOUND'
    else: status='WDK_FILES_PRESENT_INTEGRATION_UNPROVEN'
    return {'schema':SCHEMA,'status':status,'source_ready':source_ready,'wdk_files_present':wdk_present,'sdk_versions':versions[-5:], 'checks':checks,
      'next_action':'Run DIAGNOSE_WDK.ps1 on Windows and require WindowsKernelModeDriver10.0 toolset resolution before unsigned build qualification.',
      'policy':{'presence_does_not_prove_vs_integration':True,'no_driver_install':True,'no_service_start':True,'no_signing_bypass':True,'unsigned_build_not_trusted_runtime':True}}
def capabilities():
    return {'schema':'phoenix.forge.privileged-wdk-diagnostics-capabilities/v1','read_only':True,'windows_context_required_for_integration_proof':True}
