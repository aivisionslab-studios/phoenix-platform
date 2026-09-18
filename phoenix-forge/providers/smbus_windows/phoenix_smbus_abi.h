#pragma once
#include <windows.h>
#include <winioctl.h>
#include <cstdint>

#define PHOENIX_SMBUS_ABI_VERSION 1u
#define PHOENIX_SMBUS_DEVICE L"\\\\.\\PhoenixForgeSmbus"
#define PFSMBUS_CAP_ENUMERATE 0x00000001u
#define PFSMBUS_CAP_READ_SPD  0x00000002u

#define PFSMBUS_IOCTL_GET_INFO  static_cast<DWORD>(CTL_CODE(static_cast<DWORD>(FILE_DEVICE_UNKNOWN), 0x930u, METHOD_BUFFERED, FILE_READ_ACCESS))
#define PFSMBUS_IOCTL_ENUMERATE static_cast<DWORD>(CTL_CODE(static_cast<DWORD>(FILE_DEVICE_UNKNOWN), 0x931u, METHOD_BUFFERED, FILE_READ_ACCESS))
#define PFSMBUS_IOCTL_READ_SPD  static_cast<DWORD>(CTL_CODE(static_cast<DWORD>(FILE_DEVICE_UNKNOWN), 0x932u, METHOD_BUFFERED, FILE_READ_ACCESS))

#pragma pack(push,1)
struct PfSmbusInfoV1 {
    std::uint32_t abi_version;
    std::uint32_t capability_bits;
    std::uint32_t max_slots;
    std::uint32_t max_spd_bytes;
};
struct PfSmbusReadRequestV1 {
    std::uint32_t abi_version;
    std::uint32_t slot_id;
};
#pragma pack(pop)
