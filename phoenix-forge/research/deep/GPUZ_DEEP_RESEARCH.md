# GPU-Z 2.70.0 — Deep Static Research

## Scope
Analyzed file: `GPU-Z-unpacked(1).exe`

- SHA-256: `3200f813a6df6fe8103659b8922108e08970dcfc81f7388a864cad4d13461662`
- Size: 53,617,440 bytes
- Format: PE32, x86/i386, Windows GUI
- Image base: `0x00400000`
- Entry point: `0x005D61EA`
- Sections: `.text`, `.rdata`, `.data`, `.rsrc`, `.reloc`
- Resource section is very large (~49 MB), indicating substantial embedded data/resources.
- At least 11 additional valid PE images are embedded inside the file/resource space.

## Hardware discovery architecture
GPU-Z does not rely on one single hardware API. Static evidence shows a multi-source architecture:

### Windows PnP / PCI enumeration
Observed APIs/strings:
- `SetupDiCreateDeviceInfoList`
- `SetupDiGetDeviceInfoListDetailW`
- `SetupDiEnumDeviceInfo`
- `SetupDiGetClassDevsExW`
- `SetupDiGetDeviceRegistryPropertyW`
- `SetupDiOpenDevRegKey`
- `SetupDiOpenDeviceInfoW`
- `SetupDiGetDeviceInstanceIdW`
- `SetupDiEnumDeviceInterfaces`
- `SetupDiGetDeviceInterfaceDetailW`
- `CM_Get_Parent`
- `CM_Get_Device_IDW`
- `CM_Get_DevNode_Status`
- resource descriptor APIs such as `CM_Get_First_Log_Conf_Ex`, `CM_Get_Res_Des_Data_Ex`

Observed canonical PCI formats:
- `PCI\\VEN_%04X&DEV_%04X`
- `PCI\\VEN_%04X&DEV_%04X&SUBSYS_%04X%04X`

Conclusion: GPU-Z enumerates Windows devices and reconstructs PCI identity from PnP/config-manager data. This is the correct conceptual source for Vendor ID, Device ID, Subsystem Vendor ID, Subsystem Device ID, revision and topology.

### DXGI / WDDM / D3DKMT
Observed:
- `dxgi.dll`
- `CreateDXGIFactory`, `CreateDXGIFactory1`
- `D3DKMTOpenAdapterFromDeviceName`
- `D3DKMTQueryAdapterInfo`
- `D3DKMTQueryStatistics`
- `D3DKMTEnumAdapters2`
- `D3DKMTCreateDevice`, `D3DKMTDestroyDevice`

Conclusion: GPU-Z cross-checks Windows graphics-stack identity/statistics and adapter data through DXGI/WDDM, rather than depending only on registry strings.

## AMD backend
Observed AMD ADL APIs include:
- `ADL_Main_Control_Create`, `ADL2_Main_Control_Create`
- `ADL_Adapter_NumberOfAdapters_Get`
- `ADL_Adapter_AdapterInfo_Get`
- `ADL_Adapter_Active_Get`
- `ADL2_Adapter_Graphic_Core_Info_Get`
- `ADL_Adapter_MemoryInfo_Get`
- `ADL_Adapter_MemoryInfo3_Get`
- `ADL_Overdrive5_CurrentActivity_Get`
- `ADL_Overdrive5_FanSpeed_Get`
- `ADL_Overdrive5_Temperature_Get`
- `ADL2_OverdriveN_Temperature_Get`
- `ADL2_OverdriveN_SystemClocks_Get`
- `ADL2_OverdriveN_MemoryClocks_Get`
- `ADL2_OverdriveN_PerformanceStatus_Get`
- `ADL_Overdrive5_PowerControlInfo_Get`
- `ADL_Overdrive5_PowerControl_Get`
- `ADL_Adapter_ObservedGameClockInfo_Get`
- `ADL_Adapter_VideoBiosInfo_Get`
- `ADL_Display_WriteAndReadI2C`

DLL names include `atiadlxx.dll` / `atiadlxy.dll`.

Conclusion: for AMD cards, GPU-Z combines OS/PCI identity with ADL for clocks, memory information, thermals, fan, power/activity and VBIOS metadata. I2C support gives a route for board-level sensor/EEPROM access when supported.

## NVIDIA backend
Observed:
- `nvapi_QueryInterface`
- GPU enumeration/name/sensor/clock strings for NVAPI
- NVML API family: `nvmlInit`, `nvmlDeviceGetCount`, `nvmlDeviceGetHandleByIndex`, `nvmlDeviceGetPciInfo`, `nvmlDeviceGetMemoryInfo`
- CUDA backend strings and `nvcuda.dll`

Conclusion: GPU-Z uses vendor-native NVIDIA APIs in addition to Windows generic APIs.

## Intel backend
Observed Intel Graphics Control Library style APIs:
- `ctlInit`
- `ctlEnumerateDevices`
- `ctlPciGetProperties`
- `ctlGetDeviceProperties`
- `ctlOverclockGpuFrequencyOffsetGet`
- `ctlFrequencyGetProperties`
- `ctlEnumFrequencyDomains`
- `ctlFrequencyGetState`
- `ctlPowerTelemetryGet`

Conclusion: modern Intel data is sourced through Intel's Control Library path, not inferred only from generic PCI fields.

## Vulkan / OpenCL / CUDA capability probes
Vulkan strings show a dedicated probe layer:
- `vulkan:init:...`
- `vulkan:get_physical_device_properties`
- `vulkan:get_physical_device_features`
- `vulkan:get_queue_family_properties`
- `vulkan:get_physical_device_memory_properties`
- extension enumeration

OpenCL strings show:
- platform/device initialization
- `clGetDeviceInfo`
- Khronos OpenCL vendor registry path

CUDA strings show device name, capability and total-memory queries.

Conclusion: capability badges are based on actual API initialization/query paths, not merely GPU-name lookup.

## VBIOS / ROM parsing
Strong static evidence for dedicated ROM parsing:
- `ATOMBIOSBK-ATI VER`
- `ATOMBIOSBK-AMD VER`
- many `PCIR` references
- `VBIOS Version`
- PCI expansion ROM parsing messages
- UEFI image subsystem extraction
- `ADL_Adapter_VideoBiosInfo_Get`
- I2C/EEPROM access messages
- cached VBIOS registry references

Conclusion: GPU-Z has both metadata APIs and its own ROM-format knowledge. For AMD, ATOMBIOS/PCIR parsing is a major source for board/firmware properties. The presence of I2C/EEPROM logic means some ROM acquisition can occur below ordinary Windows display-driver metadata.

## Memory vendor/type identification
Observed canonical vendor/type strings:
- Samsung
- Hynix
- Micron
- Elpida
- GDDR2/GDDR3/GDDR4/GDDR5/GDDR5X/GDDR6/GDDR6X
- `Unknown memory type %d`
- `Memory Type`

Evidence supports a mapping/database/parser layer that converts low-level memory identifiers/firmware structures/vendor information into human-readable memory type/vendor.

## Subvendor path
Observed strings:
- `subvendorid`
- `SubvendorID`
- `GPU Subvendor ID`
- URL/query formatting containing vendor/device/subvendor/subsys/revision
- `Action: Override subvendor strap.`

Manual Ghidra work in this project located `GPU Subvendor ID` at `0x007D9EFC`, referenced from `FUN_00439070` around `0x0043989A`.

Conclusion: GPU-Z has an internal property system for hardware identity and a distinction between raw/overridden subsystem information. A displayed subvendor is not proof of physical PCB assembler; it is fundamentally based on subsystem identity and internal mapping, with possible strap/firmware overrides.

## Sensor acquisition model
The presence of ADL, NVAPI/NVML, Intel ctl, D3DKMT, I2C, and board-specific table names indicates a layered sensor model:
1. vendor API when available;
2. OS/WDDM statistics where appropriate;
3. board/I2C-specific paths for selected devices;
4. internal normalization into common fields such as clock, temperature, fan, voltage, power and bus load.

## Key implication for Phoenix Forge
Do not reproduce GPU-Z as a single scanner. Recreate the architecture:
- generic Windows PCI/PnP identity layer;
- DXGI/D3DKMT cross-check layer;
- AMD ADL plugin;
- NVIDIA NVAPI/NVML plugin;
- Intel ctl plugin;
- Vulkan/OpenCL/CUDA capability probes;
- independent VBIOS parser (ATOMBIOS/PCIR/UEFI);
- memory-vendor database/parser;
- confidence/provenance field for every reported datum.

## Confidence / limits
High confidence: API families, discovery paths, vendor backends, VBIOS-format support, capability probing.
Medium confidence: exact precedence rules between sources for every individual UI field.
Not yet proven: complete function-by-function decompilation and exact proprietary internal lookup database contents.
