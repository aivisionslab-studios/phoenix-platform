# Phoenix Forge 0.6 — Expanded Real Benchmark

Version 0.6 consolidates a larger benchmark step instead of another narrow
micro-release.

## CPU and memory

- deterministic integer single/multi workloads;
- floating-point transcendental workload;
- SHA-256 throughput;
- zlib compression/decompression with byte-exact readback;
- memory copy bandwidth with five-sample distribution;
- comparative pointer-chase memory latency;
- sustained segmented CPU test with first/last degradation and variability.

## Storage

- sequential read/write with SHA-256 validation;
- deterministic random 4 KiB read/write;
- IOPS plus min, p50, p95, p99, maximum and average latency;
- read-only Windows Storage Reliability, smartctl or nvme-cli inventory.

## Statistical contract

Every repeated measurement reports distributions rather than a single peak.
The suite reports a quality/integrity score, but deliberately does not invent a
universal performance score. Performance remains in physical units and Golden
Baseline deltas.

## Profiles

- quick: approximately one-second CPU kernels, 64 MB memory and 32 MB storage;
- standard: longer kernels, 256 MB memory, 128 MB storage and sustained CPU;
- deep: 512 MB memory/storage, 10,000 random operations and longer sustained CPU.

GPU compute is opt-in because a degraded GPU must not be stressed implicitly.

## Safety and diagnosis

Sensor timelines compute percentiles and detect configured thermal limits. A
violation invalidates the score and raises an abort request for the supervising
runtime. The diagnostic planner prioritizes correctness errors, thermal limits,
GPU AI blocks, throttling evidence and storage health.

    phoenix-forge benchmark --profile standard --include-gpu
    phoenix-forge storage-health
    phoenix-forge diagnose --profile standard --include-gpu

The Phoenix Engine integration must honor abort_requested immediately by
terminating the supervised worker. Forge never claims that a Python signal by
itself has physically stopped an external process.
