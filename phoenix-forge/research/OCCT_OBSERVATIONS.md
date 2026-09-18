# OCCT research observations

Source studied locally: user-supplied executable. This document records observable packaging/components and API patterns only; no proprietary source is redistributed.

## Packaging
The supplied ~191 MB executable is a valid PE64/Windows package with a ZIP overlay. The overlay exposes:
- `OCCTGUI.exe`
- `steam_api64.dll`
- `steam_appid.txt`

The embedded GUI binary is PE32+ / x86-64 and contains references/resources related to independent workload components.

## Component names observed in the binary resources/strings
- `HWiNFO64.dll`
- `ORingDrv.sys`
- `ORingLib.dll`
- `CpuOcct64.exe`
- `GpuMemtest.exe`
- `OcctMemtest.exe`
- `diskspd.exe`
- `gpu3d/...` including a Win64 shipping executable and D3D12 runtime components

## Architectural lesson for Phoenix Forge
OCCT's observable packaging strongly supports a modular test-runner architecture: controller/UI plus specialized workload engines. Phoenix Forge therefore keeps identification, telemetry, CPU stress, RAM/VRAM validation and AI workloads as separate modules with a shared result schema.

Phoenix Forge does not ship, invoke or copy these proprietary components.
