# Phoenix Forge 0.4.4 — Result Integrity Gateway

This release separates display capability from trustworthy AI compute.

## Runtime contract

1. Runtime submits text/image output before user delivery.
2. Forge validates structure and quality signals.
3. First rejection requests a clean same-GPU retry.
4. Reproduction requests a CPU control.
5. GPU failure plus successful CPU control blocks only the exact
   workload/backend/runtime/model scope.
6. Two independently blocked AI domains escalate the device to
   AI_COMPUTE_UNSAFE; all Phoenix AI inference falls back to CPU while display
   use remains outside the block.

## Validators

- Text: truncated streams, crashes, 0xC0000005, invalid encoding,
  question/slash/zero repetition, low character diversity, finish reason and
  expected-text comparison.
- Image: file/header/decode integrity, dimensions, low-information frames,
  externally measured blur/artifacts, OCR expected/observed comparison and
  MiniCPM-V quality verdict/score.

OCR and MiniCPM-V remain independent providers. Forge consumes their evidence;
it never treats a single subjective low-quality judgment as proof of defective
hardware. A scope block requires reproduction plus a successful CPU control.

## API

- POST /api/output/validate-text
- POST /api/output/validate-image
- GET /api/gpu-safety with workload/backend/runtime/model scope
- GET /api/autopilot with workload/backend/runtime/model scope

Events are appended as phoenix.hardware.event/v1 for the AHDE bridge.
