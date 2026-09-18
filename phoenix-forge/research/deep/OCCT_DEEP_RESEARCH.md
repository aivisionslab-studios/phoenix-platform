# OCCT — Deep Static Research

## Scope
Analyzed files:
- `OCCT-unpacked(1).exe`
- extracted inner `OCCTGUI.exe`

Outer executable:
- SHA-256: `f967bb1588e70510add653485fed06c68423bfbe5514a0e1fbf7fc0a9eab1ab4`
- Size: 199,485,096 bytes
- PE32+ x86-64
- Native launcher PE image is under 1 MB; most of the file is bundled payload.

Inner GUI/core executable:
- SHA-256: `e6e9cabb394e9fc66ed11fa174351827054d67356563f2c1823902586c3bcd1a`
- Size: 140,871,552 bytes
- PE32+ x86-64
- Strong .NET / CoreCLR / NativeAOT evidence
- Avalonia UI
- Silk.NET bindings present

## Outer launcher / packaging
A ZIP local-header signature begins near file offset `0x8E600` in the outer executable. Extraction reveals at least:
- `OCCTGUI.exe`
- `steam_api64.dll`
- `steam_appid.txt`

The launcher imports/contains strings for:
- `CreateProcessW`
- `CreateFileW`
- `WriteFile`
- `DeleteFileW`
- `GetTempPathW` / `GetTempPath2W`
- ZIP/zlib error strings

Conclusion: the outer EXE is primarily a launcher/bundler that extracts packaged components and starts the real GUI/core executable. Reverse engineering should therefore focus on `OCCTGUI.exe`, not the outer wrapper.

## Runtime/application architecture
`OCCTGUI.exe` contains strong evidence of:
- NativeAOT compilation
- CoreCLR runtime components
- `System.Private.CoreLib`
- Avalonia (`OcctGuiAvalonia`)
- Silk.NET low-level graphics/compute bindings

This explains why normal native imports reveal little: much platform access is dynamically resolved or emitted through .NET P/Invoke/native runtime machinery.

## System-information model
Namespaces/classes expose two distinct system-information providers:

### OCCT-owned sysinfo path
- `OcctCore.Models.SysInfo.Cpu.Occt`
- `OcctCore.Models.SysInfo.Gpu.Occt`
- `OcctCore.Models.SysInfo.Memory.Occt`
- `OcctCore.Models.SysInfo.Motherboard.Occt`
- `OcctCore.Models.SysInfo.Storage.Occt`

### HWiNFO-backed sysinfo path
- `OcctCore.Models.SysInfo.Cpu.HwInfo`
- `OcctCore.Models.SysInfo.Gpu.HwInfo`
- `OcctCore.Models.SysInfo.Memory.HwInfo`
- `OcctCore.Models.SysInfo.Motherboard.HwInfo`
- `OcctCore.Models.SysInfo.Storage.HwInfo`
- `HwInfoCpuInfos`, `HwInfoGpuInfos`, `HwInfoMemoryInfos`, `HwInfoMotherboardInfos`, `HwInfoStorageInfos`

Conclusion: OCCT intentionally separates its own hardware model from HWiNFO-derived inventory. HWiNFO is not merely decoration; the application has explicit factories/interfaces for translating HWiNFO data into OCCT's domain model.

## Monitoring architecture
Observed classes/interfaces:
- `OcctCore.Models.Monitoring.Engine.HwInfo`
- `OcctCore.Models.Monitoring.Engine.Occt`
- `HwInfoMonitoringEngine`
- `IOcctMonitoringEngine`
- `IHwInfoMonitoringEngine`
- `MonitoringEngineType`
- `HwInfoSensor`, `IHwInfoSensor`
- sensor IDs and component-property models

A localization string states that when embedded HWiNFO refresh is disabled, it is still loaded at startup to obtain system information required for OCCT to function fully.

Conclusion: OCCT has a provider abstraction for monitoring, with HWiNFO as a major provider and an OCCT-owned provider as another path.

## Low-level ORing layer
Large groups of classes are present under:
- `OcctCore.Services.ORingLib`
- `OcctCore.Models.ORingLib`
- `OcctCore.Models.ORingLib.Cpu.Intel.*`

Examples include MSR and Intel OC/tuning structures:
- IA32 temperature target
- HWP package
- turbo ratio limit registers
- power-limit functions
- voltage/frequency override structures
- TPMI/OC mailbox structures
- memory timing control

There is also a setting for GPU I2C monitoring.

Conclusion: OCCT has its own privileged/low-level hardware layer (ORing) for operations HWiNFO alone does not cover, especially CPU MSR/OC/tuning and related hardware-register access.

## CPU stress architecture
Observed test model:
- `OcctCore.Models.Tests.CpuOcct`
- `CpuOcctConfig`
- `CpuOcctCoreConfig`
- `CpuOcctWorker`
- advanced per-core/thread configuration
- instruction set selection
- SSE / AVX / AVX2 / AVX512 localization/model references
- data-set, load-type, mode and thread controls

Conclusion: CPU stress is worker-based and configurable by instruction set, data set, load mode and thread/core topology. This is more sophisticated than a generic busy loop.

## Memory stress architecture
Observed:
- `OcctCore.Models.Tests.Memory`
- `MemoryWorker`
- custom-test parameter models
- instruction-set selection
- asynchronous process/message handling

Conclusion: memory testing is a distinct worker/test engine rather than being implemented as part of CPU stress.

## VRAM test architecture
Observed:
- `OcctCore.Models.Tests.Vram`
- `VramConfig`
- `VramTestResult`
- `VramMemUnit`
- `_FindGpuMemorySize` lambdas
- adapter selection and GPU-view-model integration

This strongly supports a dedicated GPU-memory test component with explicit capacity discovery and result modeling.

Important limitation: static metadata alone does not expose the exact memory pattern algorithm, address-selection strategy, or shader/kernel used by the VRAM engine. Those require function-level decompilation/dynamic tracing of the relevant NativeAOT-generated code.

## GPU stress / compute architecture
Observed distinct GPU test families:
- `OcctCore.Models.Tests.Gpu3d`
- `Gpu3dStandard`
- `Gpu3dAdaptive`
- shader complexity/load/intensity models
- `OcctCore.Models.Tests.GpuCompute`
- `GpuComputeConfig`
- `GpuComputeTestResult`
- Vulkan adapter models
- OpenCL adapter models
- DirectX/DXGI types
- Silk.NET Vulkan/OpenCL/OpenGL/DirectX bindings

Conclusion: OCCT separates 3D rendering stress from compute stress and supports multiple graphics/compute API backends.

## Combined / PSU test
Observed:
- `OcctCore.Models.Tests.Combined`
- `OcctCore.Models.Tests.PowerSupply`
- PowerSupply configuration/result classes

Conclusion: the “Power”/PSU style test is orchestration of multiple load generators rather than a magical direct PSU test. Its value comes from combined subsystem load plus telemetry/error monitoring.

## Error detection / watchdog model
Observed:
- WHEA error event handling
- `StopOnWheaError`
- `WheaErrorsDetected`
- schedule-machine handlers that react to monitoring/WHEA events
- sensor-alert settings
- temperature threshold models
- test process lifecycle/start/stop/exit-code handling

Conclusion: OCCT's maturity comes as much from orchestration, monitoring and stop conditions as from raw load generation. Phoenix Forge should copy this architectural principle, not proprietary algorithms.

## Storage and benchmark families
Observed test/benchmark modules:
- Storage test
- Storage benchmark
- CPU benchmark
- Memory benchmark
- memory latency/bandwidth benchmark
- latency/bandwidth benchmark

This confirms the core architecture is a suite of independent workers behind a common scheduling/result/monitoring framework.

## Key implication for Phoenix Forge
Recreate these architectural ideas:
1. provider abstraction for system information and sensors;
2. privileged low-level helper for MSR/PCI/I2C only when needed;
3. independent test workers (CPU, RAM, VRAM, GPU compute, GPU 3D, storage);
4. shared watchdog/event bus for thermals, WHEA, driver reset and error counts;
5. common result schema;
6. combined-load orchestrator;
7. API/backend adapters selected by actual capability.

## Confidence / limits
High confidence: launcher/bundle architecture; NativeAOT/Avalonia/Silk.NET stack; HWiNFO + OCCT dual provider model; ORing low-level layer; named test families; WHEA/watchdog orchestration.
Medium confidence: exact relationships between individual providers/workers at runtime.
Not yet proven: proprietary VRAM patterns, exact GPU shader kernels, exact CPU stress math loops, and exact scheduling algorithms. Those require deeper function-level decompilation or runtime instrumentation.
