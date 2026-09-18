# Build validation — Phoenix Forge v0.12.0

Validated in the build container:
- Python source compilation: PASS
- Python unit tests: **19 passed**
- Regression functions: **24 passed** with the local direct test harness, including forensic fields, conservative policy, ADL deduplication, embedded-ZIP discovery, and traversal rejection.
- CLI parser/help including new 0.4 commands: PASS
- Source package structure: PASS

Native Windows compilation cannot be executed inside this Linux build container because the Windows SDK/MSVC and Vulkan development SDK are not installed here. A local Linux CMake configure was also attempted and correctly stopped at missing Vulkan development headers/libraries; Python/regression validation remains green. The supplied `BUILD_WINDOWS.ps1` is configured for the same Visual Studio + Vulkan SDK toolchain that successfully built v0.3.1/v0.3.2 on the target Windows machine. v0.4 adds `dxgi` linkage and compiles `stress.comp` with Vulkan SDK `glslc`.

Required target-machine validation:
1. `BUILD_WINDOWS.ps1`
2. `phoenix-forge-native dxgi-info`
3. `phoenix-forge-native cpu-info`
4. `phoenix-forge inspect`
5. `phoenix-forge pulse`
6. `phoenix-forge gpu-compute-stress --seconds 10 --mb 128 --rounds 32`
7. `phoenix-forge whea --minutes 60`
8. only then increase stress duration/memory.
