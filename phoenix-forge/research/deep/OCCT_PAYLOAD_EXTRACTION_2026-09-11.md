# OCCT payload extraction — 2026-09-11

## Scope and boundary

This is a static interoperability and architecture study. No extracted binary
was executed. Phoenix Forge does not redistribute these files and does not copy
OCCT source code, private kernels, scheduling logic, lookup databases, or
licensing mechanisms.

## Reproducibility

- Input: `OCCT-unpacked(2).exe`
- Size: 199,485,096 bytes
- SHA-256: `f967bb1588e70510add653485fed06c68423bfbe5514a0e1fbf7fc0a9eab1ab4`
- Format: PE32+ x86-64 Windows GUI, 7 mapped PE sections plus a large overlay
- PE image base: `0x140000000`
- Entry point RVA: `0x375B8`

The overlay is not one monolithic archive. Sixteen independently valid classic
ZIP archives were recovered by locating each EOCD, deriving its archive start
from the central-directory offset, and validating every member.

## Priority payloads

| Archive | Start offset | Extracted component | Size | SHA-256 |
|---:|---:|---|---:|---|
| 0 | 583168 | HWiNFO64.dll | 2,508,784 | `48d0c99a03e95661151176b8e8c0fb2efab1711193797470131c0ee0b6e385be` |
| 2 | 3340184 | ORingDrv.sys | 76,976 | `221d879a2b4c7bbd80dfba8f95a2ca388bffd152af7bc208025404b33c17ef41` |
| 3 | 3373811 | ORingLib.dll | 296,960 | `fbd82e30bc522e7a648bc27d7627b85fd1c3400373b6e5c911e69cb584053fcb` |
| 5 | 7922172 | CpuOcct64.exe | 24,419,928 | `bdc759c55203a8a222004130d16f8ffe199ad041c0626f894fce816ea7269e78` |
| 6 | 12740650 | GpuMemtest.exe | 402,520 | `5d7a0cac28de12fe73243efdd88a0458c9f5bc47d9e6f09956d41eef75ae2596` |
| 7 | 12918291 | OcctMemtest.exe | 347,736 | `ef17565a1bace49ecc2cb0d5ea61e47d5ac6f832f221221b0de69c1a32097f9a` |
| 8 | 13082895 | diskspd.exe | 755,200 | `2f804069c6ea17d4a163cb889d26769f233f668ddd2da59201dc8ef4396640e1` |

Archives 9 and 10 contain the D3D12/Unreal `gpu3d` workload and its runtime
dependencies. Archives 11–14 contain several Linpack variants. Archive 15 is
an outer distribution bundle containing `OCCTGUI.exe`, `steam_api64.dll`, and
`steam_appid.txt`.

## GpuMemtest architectural findings

`GpuMemtest.exe` is a PE32+ console program with image base `0x140000000`, entry
point RVA `0x29270`, and a September 3, 2026 linker timestamp. Its static import
table contains only `KERNEL32.dll` and `botan-3.dll`, but its strings show that
it loads `OpenCL.dll` dynamically and resolves a complete OpenCL execution path:

- platform/device discovery: `clGetPlatformIDs`, `clGetDeviceIDs`, `clGetDeviceInfo`
- context/queue: `clCreateContext`, `clCreateCommandQueue`
- allocation: `clCreateBuffer`
- program/kernel: `clCreateProgramWithSource`, `clBuildProgram`, `clCreateKernel`
- execution/readback: `clSetKernelArg`, `clEnqueueNDRangeKernel`, `clEnqueueReadBuffer`, `clFlush`
- teardown: release functions for queue, context, event, kernel, memory, and program

Named internal operations reveal several test families:

- `WriteConstant` / `CheckConstant`
- `WriteConstantPair` / `CheckConstantPair`
- `WriteModuloPair` / `CheckModuloPair`
- `WriteWalking32B` / `CheckWalking32B`
- `WriteRandomBlocks` / `CheckRandomBlocks`

The program also contains `\\.\pipe\`, indicating a named-pipe control/result
channel with the OCCT orchestration layer. Cryptographic Botan calls appear in
both memory workers; their existence is recorded, but licensing/authentication
behavior is deliberately outside Phoenix Forge's implementation scope.

## Comparison with Phoenix Forge 0.4.1

The recovered design confirms that a mature VRAM validator separates backend
discovery/allocation, GPU-side pattern generation, readback and mismatch
counting, orchestration/status, and cleanup/failure classification.

Phoenix Forge already implements these layers independently with Vulkan
device-local allocations, transfer fills, readback validation, JSON results,
adaptive multi-allocation maps, timeout/budget/error classification, and an
Autopilot consumer. It currently has eight constant 32-bit patterns, whereas
the OCCT binary visibly exposes more pattern *families*. The correct next step
is an original Vulkan pattern suite with documented algorithms and deterministic
seeds, not a transcription of OCCT's private kernels.

## Reproduction command

```powershell
python tools\extract_embedded_zips.py OCCT-unpacked.exe --out OCCT_EXTRACTED
python tools\extract_embedded_zips.py OCCT-unpacked.exe --out OCCT_EXTRACTED --extract --archive 6
```

The first command inventories all archives. The second extracts only the
GpuMemtest archive. The helper rejects absolute/traversal paths and writes a
JSON inventory containing offsets and hashes.
