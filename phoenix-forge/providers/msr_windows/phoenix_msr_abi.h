#pragma once
#include <windows.h>
#include <cstdint>

// Phoenix Forge MSR read-only provider ABI v1.
// No kernel driver is bundled in 0.20.9. A future signed driver must implement
// this interface and expose \\.\PhoenixForgeMsr.
#define PHOENIX_MSR_ABI_VERSION 1u
#define PHOENIX_MSR_DEVICE L"\\\\.\\PhoenixForgeMsr"
#define PFMSR_DEVICE_TYPE 0x8337u
#define PFMSR_IOCTL_GET_INFO static_cast<DWORD>(CTL_CODE(PFMSR_DEVICE_TYPE, 0x800u, METHOD_BUFFERED, FILE_READ_ACCESS))
#define PFMSR_IOCTL_READ_COUNTER_PAIR static_cast<DWORD>(CTL_CODE(PFMSR_DEVICE_TYPE, 0x801u, METHOD_BUFFERED, FILE_READ_ACCESS))

static constexpr std::uint64_t PFMSR_CAP_APERF_MPERF = 1ull << 0;
static constexpr std::uint64_t PFMSR_CAP_BCLK_MULTIPLIER = 1ull << 1;

#pragma pack(push, 1)
struct PfMsrInfoV1 {
    std::uint32_t abi_version;
    std::uint32_t struct_size;
    std::uint64_t capability_bits;
};
struct PfMsrCounterRequestV1 {
    std::uint32_t abi_version;
    std::uint16_t processor_group;
    std::uint16_t processor_number;
    std::uint32_t sampling_ms;
};
struct PfMsrCounterResultV1 {
    std::uint32_t abi_version;
    std::uint16_t processor_group;
    std::uint16_t processor_number;
    std::uint64_t aperf_delta;
    std::uint64_t mperf_delta;
    double reference_mhz;
};
#pragma pack(pop)
