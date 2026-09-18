# Phoenix Llama Runtime Stable 1.0.0 — Validation report

## Snapshot

- Upstream commit: `e71b80510c848c00175924ecf3c40333ccae8eb5`
- Runtime channel: `stable`
- Core upstream modified: **no** (v1.0.0 keeps Phoenix changes isolated under `phoenix_runtime/`)

## Static/source checks

- Critical source SHA-256 manifest: PASS
- Phoenix profile tests: 13/13 PASS
- CPU policy uses `--device none`: PASS
- GPU policy uses native `-ngl all` (not legacy `999`): PASS
- Hybrid uses native `-ngl auto --fit on`: PASS
- Device auto-resolution is based on `--list-devices`: PASS
- Polaris conservative disables op-offload but keeps a real GPU layer: PASS
- MoE profile uses native `--cpu-moe`: PASS
- Correctness gate rejects `????????` corruption: PASS

## Build smoke

CMake configuration for a portable CPU build completed successfully with:

`-DGGML_VULKAN=OFF -DGGML_NATIVE=OFF -DCMAKE_BUILD_TYPE=Release`

A target build of `llama-server` was started and successfully built the base ggml/CPU libraries before the sandbox execution time limit interrupted compilation. This report therefore **does not claim a completed binary build** in the sandbox. The included Windows/Linux build scripts run the CLI contract check after a complete local build.

## Release rule

A Phoenix Stable release must not be upgraded by pulling llama.cpp `master`. A new upstream revision is first integrated into a `next` candidate and must pass the Phoenix CLI contract, correctness gates and hardware/profile tests before becoming stable.
