# Phoenix Forge Windows MSR Provider Foundation — ABI v1

This provider is intentionally **read-only**. Version 0.20.9 does not bundle a kernel driver.
The executable opens `\\.\PhoenixForgeMsr`; if a compatible signed driver is absent, the
handshake reports no MSR clock capabilities and Forge keeps APERF/MPERF as unavailable.

The future driver must implement `phoenix_msr_abi.h`. Do not substitute WinRing0 or other
legacy/vulnerable third-party drivers. `clock.aperf_mperf` returns raw APERF/MPERF deltas plus
a measured reference MHz; Forge derives effective MHz itself and rejects invalid samples.
