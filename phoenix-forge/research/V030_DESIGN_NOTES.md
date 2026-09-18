# Phoenix Forge v0.3 design notes

## What the GPU-Z study contributed

The GPU-Z analysis reinforced the separation between PCI silicon identity, subsystem identity, firmware/VBIOS identity and the physical board assembler. The Phoenix implementation therefore keeps these as separate evidence channels. It also treats VBIOS strings as clues rather than proof.

## What the OCCT study contributed

The OCCT package exposed a modular design: separate memory, CPU, GPU/3D and monitoring components. Phoenix Forge follows the same *architectural lesson* without reusing proprietary implementation: stress, memory, sensors and orchestration are independent modules that return a common `StressResult` schema.

## Original implementation choices

- Vulkan is the native GPU validation backend because Phoenix targets vendor-neutral local AI hardware.
- Device-local VRAM is validated through GPU-side fill + transfer readback.
- Sensor collection uses public/vendor interfaces when present and degrades gracefully.
- Autopilot consumes measured evidence and emits a versioned policy document instead of relying on product names alone.
