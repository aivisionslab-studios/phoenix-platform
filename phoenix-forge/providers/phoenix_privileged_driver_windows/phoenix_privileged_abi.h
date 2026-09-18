#pragma once

#include <ntddk.h>

#define PHOENIX_PRIVILEGED_ABI_VERSION 1u
#define PHOENIX_PRIVILEGED_DEVICE_NAME      L"\\Device\\PhoenixForgeMsr"
#define PHOENIX_PRIVILEGED_DOS_DEVICE_NAME  L"\\DosDevices\\PhoenixForgeMsr"

#define PFP_DEVICE_TYPE 0x8337u

#define PFP_IOCTL_GET_INFO \
    CTL_CODE(PFP_DEVICE_TYPE, 0x800u, METHOD_BUFFERED, FILE_READ_ACCESS)

#define PFP_IOCTL_READ_COUNTER_PAIR \
    CTL_CODE(PFP_DEVICE_TYPE, 0x801u, METHOD_BUFFERED, FILE_READ_ACCESS)

#define PFP_CAP_APERF_MPERF      (1ull << 0) /* fixed MSR E7/E8 only */
#define PFP_CAP_BCLK_MULTIPLIER  (1ull << 1)

#pragma pack(push, 1)
typedef struct _PFP_INFO_V1 {
    ULONG abi_version;
    ULONG struct_size;
    ULONGLONG capability_bits;
} PFP_INFO_V1;

typedef struct _PFP_COUNTER_REQUEST_V1 {
    ULONG abi_version;
    USHORT processor_group;
    USHORT processor_number;
    ULONG sampling_ms;
} PFP_COUNTER_REQUEST_V1;

typedef struct _PFP_COUNTER_RESULT_V1 {
    ULONG abi_version;
    USHORT processor_group;
    USHORT processor_number;
    ULONGLONG aperf_delta;
    ULONGLONG mperf_delta;
    double reference_mhz;
} PFP_COUNTER_RESULT_V1;
#pragma pack(pop)
