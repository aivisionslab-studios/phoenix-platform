# Phoenix SMBus Windows Provider Foundation

Read-only user-mode provider for a future signed `PhoenixForgeSmbus` kernel device.

No kernel driver is bundled. Without a compatible driver the provider handshake reports
`driver_status=MISSING` and exposes no live SPD capabilities. Forge remains functional and
continues to support offline `.bin/.spd/.rom` parsing.
