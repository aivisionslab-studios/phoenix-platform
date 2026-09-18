# Phoenix Forge 0.5 — Benchmark & Machine Health foundation

## Measurement contract

A benchmark score is valid only when the workload completes and its correctness
check passes. Peak throughput, sustained telemetry and output correctness are
separate facts.

Every measured workload returns:

- exact parameters and Phoenix version;
- throughput samples and aggregate values;
- correctness status;
- sensor timeline and min/average/max summaries;
- explicit score validity;
- warnings that affect comparison.

## Golden Baseline

The baseline is bound to a stable hardware fingerprint containing CPU, memory
capacity, motherboard and PCI GPU identity. It can be created only when every
required subsystem is verified healthy and every benchmark score is valid.
Creation is exclusive: a later run cannot overwrite it. Comparisons flag
regressions of 10 percent or more.

## Machine Health

Health is reported independently for CPU, RAM, GPU, storage and benchmark
integrity. GPU display status is separate from AI-compute authorization.
Confirmed output failures continue to use the v0.4.4 workload matrix.

## Commands

    phoenix-forge benchmark --seconds 5 --memory-mb 256 --storage-mb 256 --include-gpu
    phoenix-forge machine-health --benchmark --include-gpu
    phoenix-forge baseline-create --seconds 5 --include-gpu
    phoenix-forge baseline-compare --seconds 5 --include-gpu

Short profiles are triage. Deep certification still requires full VRAM scans,
longer CPU/GPU loads, WHEA monitoring and repeated correctness checks.
