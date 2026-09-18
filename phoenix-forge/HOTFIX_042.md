# Phoenix Forge v0.4.2 — Forensic VRAM Hotfix

This release responds to the RX 580 2048SP evidence gathered on 2026-09-11:

- sampled 6144 MB run: no mismatch;
- full 4096 MB run: 3 mismatches;
- full 6144 MB run: 1 mismatch;
- full 7168 MB / 2-pass run: 1 mismatch;
- OCCT: 1,191,355 reported errors.

The v0.4.2 result no longer equates a completed sample with healthy VRAM.
Mismatch reports now preserve enough evidence to compare recurring bit masks,
patterns, and logical allocation windows. Logical offsets are not physical GDDR
addresses because placement remains driver-managed.

## Short confirmation test

Do not repeat the multi-hour test first. Build v0.4.2, then run a bounded 4096 MB
full scan that continues across patterns while storing at most 64 details:

```powershell
.\BUILD_WINDOWS.ps1
.\.venv\Scripts\Activate.ps1
phoenix-forge vram-map --chunk-mb 512 --target-mb 4096 --passes 1 --full-scan --continue-on-error --max-errors 64
```

Stop if the driver resets, the display becomes unstable, or temperatures/power
delivery become unsafe.
