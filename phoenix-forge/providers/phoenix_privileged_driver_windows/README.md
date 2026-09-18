# Phoenix Forge Privileged Driver — Pre-Install Hardening (0.25.0rc6.post12)

No driver is installed or signed by this package.

Hardening:
- METHOD_BUFFERED request preserved before output overwrite;
- IoCreateDeviceSecure with LocalSystem/Administrators SDDL;
- Wdmsec.lib link;
- fixed E7/E8 allowlist remains read-only;
- parallel bounded APERF/MPERF sampling;
- fail-closed signature/thumbprint trust gate;
- no signer approved by default;
- raw APERF/MPERF preserved when reference MHz is unknown;
- WDK preflight verifies Visual Studio kernel toolset integration.

The rc6.post1 Windows build log showed MSB8020 because WindowsKernelModeDriver10.0
was not installed/integrated. v2 preflight reports WDK_VS_INTEGRATION_MISSING
instead of the old false-positive WDK_ENVIRONMENT_READY.

Do not install the driver yet.
