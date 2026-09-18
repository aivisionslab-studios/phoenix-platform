# Phoenix Polling Consolidation Contract — PHX-PHASE6N

## Principle

Polling is allowed when the data is genuinely time-varying and the consumer has a reason to refresh it. Phoenix must not create one timer per sub-resource when a canonical aggregate already exists.

## Ownership

- `TelemetryEngine`: owns short-lived real sensor sample coalescing.
- `StateEngine`: owns short-lived `/api/state` composition coalescing.
- `ObservabilityService`: read-only canonical aggregation.
- `ProvisioningJobService`: authoritative provisioning/download job lifecycle.
- Aviary components: may associate UI elements with job ids, but must not create a second job registry.

## PHX-PHASE6N rules

### AHDE Hardware Drawer

Preferred UI endpoint:

`GET /api/ahde/overview?limit=50`

It combines the read-only views formerly polled separately:

- sensors/devices
- recent AHDE events
- latest AHDE hardware/telemetry snapshot

The specialized endpoints remain supported for compatibility and debugging.

### Model Hub provisioning

Preferred UI polling endpoint:

`GET /api/provisioning/jobs`

One timer observes all active downloads. Model Hub stores only the relation between a visible button/model and its backend `job_id`; status truth remains in `ProvisioningJobService`.

The legacy per-job status endpoints remain supported.

### Polling intentionally preserved

- Engine bridge latency/health while Mission Control is visible.
- `/api/state` live telemetry used by Mission Control.
- Arena collaboration progress while collaboration is active.
- Audiobook progress while synthesis is active.
- Kokoro install polling while its single installation workflow is active (candidate for later reuse of the registry, not required by this phase).

## Anti-patterns

Do not add:

- one `setInterval` per provisioning job;
- three parallel AHDE GETs for one drawer refresh;
- long-lived polling for installation/static paths;
- frontend-local job lifecycle truth that can disagree with the backend registry.

## Future direction

Prefer consolidation and bounded polling before introducing WebSocket/SSE. Event streaming should be added only for flows where it materially improves latency, resource use, or user feedback.
