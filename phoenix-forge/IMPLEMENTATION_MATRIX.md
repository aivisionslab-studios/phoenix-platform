# GPU-Z / OCCT research → Phoenix Forge 0.4 implementation matrix

| Observed architectural capability | Phoenix Forge 0.4 |
|---|---|
| Windows PCI/PnP identity | Implemented through CIM/PNP parsing with explicit provenance |
| Vulkan device/memory query | Implemented in native helper |
| DXGI adapter cross-check | Implemented in native helper (`dxgi-info`) |
| AMD ADL adapter/memory/activity/temp/fan | Implemented read-only provider; availability depends on driver/Overdrive generation |
| NVIDIA telemetry | Existing `nvidia-smi` provider; direct NVAPI/NVML binding remains future work |
| Intel graphics telemetry | Capability placeholder only; direct Intel Control Library provider remains future work |
| OpenCL/CUDA/DirectX/DirectML capability probes | Implemented direct library/API presence probes; OpenCL initializes platform enumeration |
| VBIOS PCIR/ATOM parsing | Existing parser retained and cross-source Forensics expanded |
| HWiNFO-style provider abstraction | Implemented conceptually through multiple provider adapters; no HWiNFO binary redistribution |
| WHEA watchdog | Implemented read-only Windows event-log reader |
| CPU stress worker | Existing bounded independent worker |
| RAM worker | Existing pattern validation |
| VRAM worker | Existing Vulkan readback + multi-allocation mapping |
| GPU transfer worker | Existing Vulkan transfer stress |
| GPU compute worker | New real Vulkan compute shader workload |
| Combined/PSU-style orchestration | New CPU + GPU combined worker + WHEA before/after comparison |
| Storage benchmark/validation | New bounded sequential write/read + SHA-256 validation |
| Common result schema | Implemented with Pydantic `StressResult` and reports |
| AI workload benchmark | Existing llama.cpp/OpenAI-compatible + Stable Diffusion API workers |
| Runtime policy / Autopilot | Existing CPU/GPU/HYBRID decision layer |

## Deliberately not copied
Phoenix Forge does not copy GPU-Z's proprietary lookup database or OCCT's private kernels/patterns/scheduling algorithms. Equivalent capabilities are implemented independently using public/documented interfaces and original workloads.
