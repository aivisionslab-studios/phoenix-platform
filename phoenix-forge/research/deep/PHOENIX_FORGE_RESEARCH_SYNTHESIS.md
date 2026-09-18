# Phoenix Forge — Synthesis from GPU-Z + OCCT Research

> Continuation (2026-09-11): the previously pending OCCT payload extraction is
> now complete at the container level. See `OCCT_PAYLOAD_EXTRACTION_2026-09-11.md`
> for the 16-archive map and the static OpenCL/pattern-family findings from
> `GpuMemtest.exe`.

## What each application actually contributes

### GPU-Z: acquisition and interpretation specialist
GPU-Z is built around a layered data-acquisition model:
- Windows SetupAPI / Configuration Manager for PCI/PnP identity
- DXGI/D3DKMT for WDDM adapter information/statistics
- AMD ADL, NVIDIA NVAPI/NVML, Intel ctl for vendor-specific telemetry/details
- Vulkan/OpenCL/CUDA probes for actual compute/API capability
- ATOMBIOS/PCIR/UEFI parsing plus VBIOS acquisition paths
- I2C/EEPROM support for selected board-level data
- internal mapping/normalization to user-facing names

### OCCT: validation/orchestration specialist
OCCT is built around:
- a launcher/bundle that starts a large NativeAOT/Avalonia core
- explicit hardware-information provider abstractions
- HWiNFO-backed and OCCT-owned monitoring/sysinfo providers
- ORing low-level access for privileged register/tuning paths
- independent workers for CPU, RAM, VRAM, GPU 3D, GPU compute, storage, combined/PSU-style load
- WHEA/sensor/watchdog event handling
- common configuration/result/scheduling infrastructure

## Correct Phoenix Forge architecture

```text
AHDE / Windows / Linux discovery
            |
            v
+------------------------------+
| Phoenix Forge Hardware Model |
+------------------------------+
    |        |        |        |
    v        v        v        v
  PCI      Vendor   VBIOS    Compute
 generic   plugins  parser    probes
    |        |        |        |
    +--------+--------+--------+
             |
             v
      Phoenix Detect/Inspect
             |
             v
+---------------------------------+
| Validation & Monitoring Bus      |
| Pulse + WHEA + thermals + errors |
+---------------------------------+
      |       |       |       |
      v       v       v       v
    CPU     RAM     VRAM     GPU
  worker   worker   worker   worker
      \       |       |       /
       \------Crucible--------/
              |
              v
         AI Bench workers
      llama.cpp / diffusion
              |
              v
          Certify
              |
              v
          Autopilot
   CPU / GPU / HYBRID policy
```

## Data-source precedence recommended for Forge

### PCI identity
1. Windows SetupAPI/CM (or Linux sysfs)
2. DXGI/D3DKMT cross-check
3. vendor API cross-check
4. VBIOS subsystem fields as evidence, not unquestioned truth

### VRAM capacity
1. Vulkan/DXGI/vendor API consistent result
2. vendor API memory info
3. OS/WDDM budget vs physical capacity kept separate
4. WMI AdapterRAM only fallback, low confidence

### AMD telemetry
1. ADL/ADL2
2. OS/WDDM counters
3. optional low-level/I2C only where safe and justified

### GPU capability
Probe the API itself: Vulkan/OpenCL/CUDA/DirectML/DirectX rather than infer from model name.

### VBIOS identity
Parse PCIR + AMD ATOMBIOS + UEFI image metadata. Report provenance and confidence. Never equate subsystem-vendor ID with proven physical board assembler.

## What Phoenix Forge should NOT do
- Do not copy GPU-Z's proprietary internal database or code.
- Do not copy OCCT stress kernels/patterns.
- Do not pretend Vulkan logical allocations map directly to physical GDDR chips.
- Do not report one API's number as ground truth when sources disagree.

## What makes Forge distinct
GPU-Z answers: “What GPU is this and what is it reporting?”
OCCT answers: “Does the system remain stable under controlled stress?”
Phoenix Forge should answer: “What hardware is actually available, what parts are validated, what workload can it safely run, and how should Phoenix schedule CPU/GPU/hybrid execution?”

## Priority implementation gaps discovered
1. AMD ADL2 telemetry plugin for Polaris/modern AMD.
2. DXGI/D3DKMT backend for physical VRAM, budget, residency and adapter correlation.
3. VBIOS acquisition + ATOMBIOS parser expansion.
4. Vendor-specific sensor provider interface.
5. WHEA/event-log watchdog.
6. CPU stress worker with selectable instruction sets and data sets.
7. VRAM worker with chunked residency, verification patterns, progress and reset detection.
8. GPU compute worker using Vulkan compute shaders, separate from transfer-only stress.
9. Combined-load orchestrator.
10. AI benchmark workers feeding a safe-runtime policy.
