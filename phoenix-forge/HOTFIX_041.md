# Phoenix Forge v0.4.1 — Native Windows Build Hotfix

This release repairs the MSVC failure observed on the target Windows machine in v0.4.0.

## Root cause
`Windows.h` may define `min` and `max` preprocessor macros. The v0.4.0 native CLI dispatcher used `std::max(...)` on a very long single source line. On MSVC the macro collision corrupted parsing, which produced C2589 and cascading C2660 errors for `doVram`, `doVramMap`, `doGpuStress`, and `doGpuComputeStress`.

## Fixes
- `NOMINMAX` is defined before Windows headers.
- CMake also defines `NOMINMAX` and `WIN32_LEAN_AND_MEAN` for the native target.
- Defensive `#undef min` and `#undef max` are present after Windows headers.
- The native CLI parser/dispatcher was rewritten into readable multi-line code.
- Dispatch uses macro-resistant `(std::max)(...)` forms at Windows-sensitive call sites.
- Missing/unknown native CLI options now return explicit JSON errors.
- MSVC build uses `/W4 /EHsc /permissive-`.
- `BUILD_WINDOWS.ps1` now validates `phoenix-forge-native.exe --help` and requires `stress.spv` after the native build.

## Target-machine verification
Run:

```powershell
cd "C:\PROJETO COMPLETO\PHOENIX FORGE\phoenix-forge-v0.4.1"
Set-ExecutionPolicy -Scope Process Bypass
.\BUILD_WINDOWS.ps1
.\.venv\Scripts\Activate.ps1
phoenix-forge-native --help
phoenix-forge-native dxgi-info
phoenix-forge-native cpu-info
phoenix-forge inspect
phoenix-forge gpu-compute-stress --seconds 10 --mb 128 --rounds 32
```

Only increase stress duration/memory after the short compute run succeeds and thermals are being monitored.
