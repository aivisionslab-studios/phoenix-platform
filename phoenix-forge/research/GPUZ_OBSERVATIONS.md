# GPU-Z 2.70.0 research observations

Source studied locally: user-supplied unpacked executable. This document records observable binary behavior only; no proprietary source is redistributed.

## PE
- PE32 / x86 Windows GUI.
- Visual Studio-family linker metadata.
- Large resource section.

## Hardware-facing imports observed
- `SETUPAPI.dll`: device enumeration routines including `SetupDiGetClassDevsW`, `SetupDiEnumDeviceInfo`, `SetupDiGetDeviceRegistryPropertyW`, `SetupDiGetDeviceInstanceIdW`, device interfaces and registry keys.
- Configuration Manager routines such as `CM_Get_Parent` and `CM_Get_Device_IDW`.
- `CreateFileW`, `DeviceIoControl`, `QueryDosDeviceW`, memory mapping and registry APIs.
- Dynamic loading via `LoadLibrary*` and `GetProcAddress`.
- Display enumeration via `EnumDisplayDevicesW` and `EnumDisplaySettingsW`.

## Hardware strings observed
- `GPU Subvendor ID` exists in the unpacked image.
- VBIOS-related strings are present.
- AMD ADL Overdrive function names are present, including temperature/performance/fan/clock APIs.

## Phoenix Forge design lessons
1. Treat Windows PnP/SetupAPI as a first-class identity source.
2. Separate silicon vendor, PCI subsystem identity, firmware identity and physical board assembler.
3. Use vendor telemetry APIs through isolated adapters rather than coupling the core to one GPU family.
4. Do not treat a PCI subvendor field as proof of the remanufacturer.
