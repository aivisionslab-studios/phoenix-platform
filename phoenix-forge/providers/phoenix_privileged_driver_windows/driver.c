#include "phoenix_privileged_abi.h"
#include <intrin.h>
#include <wdmsec.h>

/*
 * Phoenix Forge privileged driver — allowlisted APERF/MPERF source.
 *
 * SECURITY MODEL
 * --------------
 * - read-only device;
 * - capability-based IOCTLs only;
 * - fixed MSR allowlist: IA32_MPERF (0xE7) and IA32_APERF (0xE8);
 * - user mode NEVER supplies an MSR address;
 * - no arbitrary port I/O;
 * - no physical/kernel memory mapping;
 * - no write IOCTLs;
 * - no MSR writes;
 * - request sampling window is bounded (10..2000 ms);
 * - target logical CPU is validated against active processor groups.
 *
 * This release ships SOURCE ONLY. A runtime capability is not considered
 * available until a separately built, trusted/signed Phoenix driver is
 * installed and the user-mode provider completes the ABI handshake.
 */

#define PFP_MSR_MPERF 0x000000E7u
#define PFP_MSR_APERF 0x000000E8u
#define PFP_MIN_SAMPLE_MS 10u
#define PFP_MAX_SAMPLE_MS 2000u

static const GUID PFP_DEVICE_CLASS_GUID = {
    0x9f1e5c62, 0x8c47, 0x4d94, {0x9e, 0xa7, 0x53, 0x27, 0x19, 0x43, 0xb4, 0x61}
};
#define PFP_DEVICE_SDDL L"D:P(A;;GA;;;SY)(A;;GA;;;BA)"

static NTSTATUS PfCompleteIrp(PIRP Irp, NTSTATUS Status, ULONG_PTR Information)
{
    Irp->IoStatus.Status = Status;
    Irp->IoStatus.Information = Information;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return Status;
}

static NTSTATUS PfCreateClose(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    return PfCompleteIrp(Irp, STATUS_SUCCESS, 0);
}

static NTSTATUS PfUnsupported(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    return PfCompleteIrp(Irp, STATUS_INVALID_DEVICE_REQUEST, 0);
}

static BOOLEAN PfAperfMperfSupported(void)
{
    int regs[4] = {0, 0, 0, 0};

    __cpuid(regs, 0);
    if (regs[0] < 6) {
        return FALSE;
    }

    __cpuidex(regs, 6, 0);

    /*
     * CPUID leaf 06h ECX[0] indicates the effective-frequency interface
     * (APERF/MPERF) on AMD; Intel implementations that expose the same
     * architectural MSRs are handled by the same fixed allowlist.
     *
     * The actual RDMSR operations are additionally protected by SEH and
     * fail closed if the platform/hypervisor does not permit the read.
     */
    return (regs[2] & 0x1) != 0;
}

static NTSTATUS PfReadFixedAperfMperf(
    ULONGLONG *Mperf,
    ULONGLONG *Aperf
)
{
    if (Mperf == NULL || Aperf == NULL) {
        return STATUS_INVALID_PARAMETER;
    }

    if (!PfAperfMperfSupported()) {
        return STATUS_NOT_SUPPORTED;
    }

    __try {
        *Mperf = __readmsr(PFP_MSR_MPERF);
        *Aperf = __readmsr(PFP_MSR_APERF);
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return GetExceptionCode();
    }

    return STATUS_SUCCESS;
}

static NTSTATUS PfValidateTarget(
    const PFP_COUNTER_REQUEST_V1 *Request,
    GROUP_AFFINITY *Affinity
)
{
    USHORT groupCount;
    ULONG activeCount;

    if (Request == NULL || Affinity == NULL) {
        return STATUS_INVALID_PARAMETER;
    }

    if (Request->abi_version != PHOENIX_PRIVILEGED_ABI_VERSION) {
        return STATUS_REVISION_MISMATCH;
    }

    if (Request->sampling_ms < PFP_MIN_SAMPLE_MS ||
        Request->sampling_ms > PFP_MAX_SAMPLE_MS) {
        return STATUS_INVALID_PARAMETER;
    }

    groupCount = KeQueryActiveGroupCount();
    if (Request->processor_group >= groupCount) {
        return STATUS_INVALID_PARAMETER;
    }

    activeCount = KeQueryActiveProcessorCountEx(Request->processor_group);
    if (Request->processor_number >= activeCount ||
        Request->processor_number >= (sizeof(KAFFINITY) * 8u)) {
        return STATUS_INVALID_PARAMETER;
    }

    RtlZeroMemory(Affinity, sizeof(*Affinity));
    Affinity->Group = Request->processor_group;
    Affinity->Mask = ((KAFFINITY)1) << Request->processor_number;

    return STATUS_SUCCESS;
}

static NTSTATUS PfSampleCounterPair(
    const PFP_COUNTER_REQUEST_V1 *Request,
    PFP_COUNTER_RESULT_V1 *Result
)
{
    GROUP_AFFINITY target;
    GROUP_AFFINITY previous;
    PROCESSOR_NUMBER actual;
    LARGE_INTEGER delay;
    ULONGLONG mperf0 = 0;
    ULONGLONG aperf0 = 0;
    ULONGLONG mperf1 = 0;
    ULONGLONG aperf1 = 0;
    NTSTATUS status;

    status = PfValidateTarget(Request, &target);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    RtlZeroMemory(&previous, sizeof(previous));
    KeSetSystemGroupAffinityThread(&target, &previous);

    KeGetCurrentProcessorNumberEx(&actual);
    if (actual.Group != Request->processor_group ||
        actual.Number != Request->processor_number) {
        KeRevertToUserGroupAffinityThread(&previous);
        return STATUS_PROCESSOR_MISMATCH;
    }

    status = PfReadFixedAperfMperf(&mperf0, &aperf0);
    if (!NT_SUCCESS(status)) {
        KeRevertToUserGroupAffinityThread(&previous);
        return status;
    }

    /*
     * Relative interval in 100-ns units. Negative = relative delay.
     * DeviceIoControl dispatch is expected at PASSIVE_LEVEL; fail closed
     * rather than attempting sampling at elevated IRQL.
     */
    if (KeGetCurrentIrql() != PASSIVE_LEVEL) {
        KeRevertToUserGroupAffinityThread(&previous);
        return STATUS_INVALID_DEVICE_STATE;
    }

    delay.QuadPart = -((LONGLONG)Request->sampling_ms * 10000LL);
    status = KeDelayExecutionThread(KernelMode, FALSE, &delay);
    if (!NT_SUCCESS(status)) {
        KeRevertToUserGroupAffinityThread(&previous);
        return status;
    }

    status = PfReadFixedAperfMperf(&mperf1, &aperf1);
    KeRevertToUserGroupAffinityThread(&previous);

    if (!NT_SUCCESS(status)) {
        return status;
    }

    RtlZeroMemory(Result, sizeof(*Result));
    Result->abi_version = PHOENIX_PRIVILEGED_ABI_VERSION;
    Result->processor_group = Request->processor_group;
    Result->processor_number = Request->processor_number;
    Result->aperf_delta = aperf1 - aperf0;
    Result->mperf_delta = mperf1 - mperf0;

    /*
     * Reference MHz is intentionally UNKNOWN in rc4.
     * Forge must not relabel OS CurrentMhz/boost clocks as reference frequency.
     * The raw APERF/MPERF evidence is still valuable and truthful; effective
     * MHz remains unavailable until an authoritative reference is implemented.
     */
    Result->reference_mhz = 0.0;

    if (Result->mperf_delta == 0) {
        return STATUS_NO_DATA_DETECTED;
    }

    return STATUS_SUCCESS;
}

static NTSTATUS PfDeviceControl(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PIO_STACK_LOCATION stack;
    ULONG code;

    UNREFERENCED_PARAMETER(DeviceObject);

    stack = IoGetCurrentIrpStackLocation(Irp);
    code = stack->Parameters.DeviceIoControl.IoControlCode;

    if (code == PFP_IOCTL_GET_INFO) {
        PFP_INFO_V1 *out;

        if (stack->Parameters.DeviceIoControl.OutputBufferLength < sizeof(PFP_INFO_V1)) {
            return PfCompleteIrp(Irp, STATUS_BUFFER_TOO_SMALL, 0);
        }

        out = (PFP_INFO_V1 *)Irp->AssociatedIrp.SystemBuffer;
        RtlZeroMemory(out, sizeof(*out));
        out->abi_version = PHOENIX_PRIVILEGED_ABI_VERSION;
        out->struct_size = sizeof(*out);

        /*
         * Source now implements the fixed allowlisted APERF/MPERF path.
         * Runtime exposure still depends on a separately built/signed driver.
         */
        out->capability_bits = PFP_CAP_APERF_MPERF;

        return PfCompleteIrp(Irp, STATUS_SUCCESS, sizeof(*out));
    }

    if (code == PFP_IOCTL_READ_COUNTER_PAIR) {
        PFP_COUNTER_REQUEST_V1 *in;
        PFP_COUNTER_RESULT_V1 *out;
        NTSTATUS status;

        if (stack->Parameters.DeviceIoControl.InputBufferLength < sizeof(PFP_COUNTER_REQUEST_V1) ||
            stack->Parameters.DeviceIoControl.OutputBufferLength < sizeof(PFP_COUNTER_RESULT_V1)) {
            return PfCompleteIrp(Irp, STATUS_BUFFER_TOO_SMALL, 0);
        }

        in = (PFP_COUNTER_REQUEST_V1 *)Irp->AssociatedIrp.SystemBuffer;
        out = (PFP_COUNTER_RESULT_V1 *)Irp->AssociatedIrp.SystemBuffer;

        /* METHOD_BUFFERED aliases input/output. Preserve input first. */
        {
            PFP_COUNTER_REQUEST_V1 request_copy = *in;
            status = PfSampleCounterPair(&request_copy, out);
        }
        return PfCompleteIrp(
            Irp,
            status,
            NT_SUCCESS(status) ? sizeof(PFP_COUNTER_RESULT_V1) : 0
        );
    }

    return PfCompleteIrp(Irp, STATUS_INVALID_DEVICE_REQUEST, 0);
}

static VOID PfUnload(PDRIVER_OBJECT DriverObject)
{
    UNICODE_STRING dosName;

    RtlInitUnicodeString(&dosName, PHOENIX_PRIVILEGED_DOS_DEVICE_NAME);
    IoDeleteSymbolicLink(&dosName);

    if (DriverObject->DeviceObject != NULL) {
        IoDeleteDevice(DriverObject->DeviceObject);
    }
}

NTSTATUS DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    UNICODE_STRING deviceName;
    UNICODE_STRING dosName;
    PDEVICE_OBJECT deviceObject = NULL;
    NTSTATUS status;
    ULONG i;

    UNREFERENCED_PARAMETER(RegistryPath);

    for (i = 0; i <= IRP_MJ_MAXIMUM_FUNCTION; ++i) {
        DriverObject->MajorFunction[i] = PfUnsupported;
    }

    DriverObject->MajorFunction[IRP_MJ_CREATE] = PfCreateClose;
    DriverObject->MajorFunction[IRP_MJ_CLOSE] = PfCreateClose;
    DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = PfDeviceControl;
    DriverObject->MajorFunction[IRP_MJ_WRITE] = PfUnsupported;
    DriverObject->DriverUnload = PfUnload;

    RtlInitUnicodeString(&deviceName, PHOENIX_PRIVILEGED_DEVICE_NAME);

    {
        UNICODE_STRING sddl;
        RtlInitUnicodeString(&sddl, PFP_DEVICE_SDDL);
        status = IoCreateDeviceSecure(
            DriverObject,
            0,
            &deviceName,
            PFP_DEVICE_TYPE,
            FILE_DEVICE_SECURE_OPEN,
            FALSE,
            &sddl,
            &PFP_DEVICE_CLASS_GUID,
            &deviceObject
        );
    }

    if (!NT_SUCCESS(status)) {
        return status;
    }

    deviceObject->Flags |= DO_BUFFERED_IO;

    RtlInitUnicodeString(&dosName, PHOENIX_PRIVILEGED_DOS_DEVICE_NAME);
    status = IoCreateSymbolicLink(&dosName, &deviceName);

    if (!NT_SUCCESS(status)) {
        IoDeleteDevice(deviceObject);
        return status;
    }

    deviceObject->Flags &= ~DO_DEVICE_INITIALIZING;
    return STATUS_SUCCESS;
}
