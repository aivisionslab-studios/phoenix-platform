# Phoenix upstream policy

Phoenix uses a frozen, tested base instead of tracking upstream `master`.

## Release gates

An upstream change is accepted only after all applicable gates pass:

1. source/API compatibility with `stable-diffusion.h` and `phoenix_sd_bridge`;
2. Windows x64 MSVC build;
3. Vulkan device enumeration;
4. SD 1.5 generation;
5. SDXL generation;
6. FLUX Schnell generation where supported by the target hardware/profile;
7. repeated generation with a resident context;
8. unload/reload without leaked process state;
9. CPU-only fallback;
10. split placement / max-VRAM behavior;
11. no regression in Phoenix Engine ABI.

Failures block promotion. Experimental upstream work lives in a candidate branch,
never directly in the production branch.
