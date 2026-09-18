# Phoenix Forge 0.7.0 — Native Core and Active Safety

This release replaces three comparative Python-only paths with native C++20 kernels while preserving the existing Python orchestration and result-integrity policy.

## Delivered

- `cpu-bench`: bounded multi-threaded integer workload with per-thread checksums.
- `memory-bench`: native memory-copy bandwidth with byte-for-byte correctness validation.
- `cache-bench`: dependent pointer chasing over 32 KiB through 128 MiB working sets.
- `vram-bandwidth`: Vulkan device-to-device copies followed by a full correctness readback.
- Active workload supervision: a thermal violation can terminate the Vulkan child process, escalate to kill after a grace period, invalidate the score, and report `SAFETY_ABORT`.
- CLI command `native-benchmark {cpu,memory,cache}` and API route `POST /api/benchmark/native`.

## Safety semantics

The sensor sampler sets a cancellation event when a configured CPU/GPU temperature limit is reached. Supervised native GPU compute receives that event, terminates the child process, and records the termination evidence. A clean video signal is never treated as proof that the GPU is suitable for AI inference.

## Limits

The cache benchmark is comparative, not a declaration of physical cache boundaries. Vulkan VRAM windows are logical allocations because consumer APIs do not expose physical GDDR-chip addresses. CPU fallback remains workload-scoped through the existing GPU safety matrix.
