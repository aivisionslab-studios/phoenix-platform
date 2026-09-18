# Phoenix Forge 0.4.3 — Persistent GPU Safety

## Why this release exists

The RX 580 2048SP produced 1,191,355 OCCT VRAM errors in about one minute. A
Forge full scan later reproduced two data mismatches in the logical 3072–4096
MB range, both involving bit 27. Earlier shallow tests could pass because they
did not exercise the failing logical region.

## Safety contract

- `MEMORY_ERROR`, `DRIVER_ERROR`, `DEVICE_LOST`, and `COMPUTE_MISMATCH` latch
  the identified GPU as `UNSAFE`.
- The state is persisted atomically across commands and restarts.
- A later quick pass or even an isolated full pass never silently clears the
  latch.
- Autopilot forces `CPU`, disables Vulkan preference/GPU-only placement, and
  returns a critical user alert in the runtime policy.
- A compact `phoenix.hardware.event/v1` JSONL event is emitted for AHDE/EventBus
  ingestion. Resident can use `required_runtime_mode: CPU`; Orchestrator applies
  the placement.
- `gpu-safety` exposes current state. `gpu-fault-report` lets a runtime report a
  confirmed compute mismatch/device loss discovered outside Forge.

## Commands

```powershell
phoenix-forge gpu-safety
phoenix-forge gpu-fault-report --kind COMPUTE_MISMATCH --device-name "AMD Radeon RX 580 2048SP" --message "runtime correctness test returned corrupted tokens"
```

State defaults to `%LOCALAPPDATA%\Phoenix\Forge\state` on Windows. Integrators
may set `PHOENIX_FORGE_STATE_DIR` to the AHDE-owned state directory.
