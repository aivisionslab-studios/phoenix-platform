# Phoenix Forge 0.4 Architecture

```text
Windows PnP/CIM ─┐
DXGI/WDDM ───────┼──> Unified Hardware Evidence Model
Vulkan ──────────┤      + per-field provenance
AMD ADL ─────────┤
NV/Intel adapters┘
                     |
                     +--> Detect / Inspect / Forensics
                     |
Sensors/vendor APIs -> Pulse -> Watchdog (WHEA / thermals / errors)
                     |
                     +--> Independent workers
                          CPU / RAM / VRAM / GPU transfer / GPU compute / storage
                                   |
                              Combined Crucible
                                   |
                                AI Bench
                                   |
                                Certify
                                   |
                               Autopilot
```

## Design rule
No single API is ground truth. Conflicting sources are preserved and scored. Vendor-specific interfaces enrich generic OS identity; they do not replace it.

## Safety rule
Vendor integration in 0.4 is query/read-only. Forge does not modify clocks, voltage, fan curves, power limits, I2C state or firmware.
