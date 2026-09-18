# Phoenix Update Channel & Anti-Rollback Contract — PHASE7M

## Goal

PHASE7M adds a release-order contract on top of PHASE7K/7L authenticity. A release may be cryptographically authentic and still be too old to install over a newer Phoenix. The updater therefore tracks a monotonic sequence per update channel.

## Release identity

Every release contains `release_policy.json`:

```json
{
  "schema_version": 1,
  "product": "PHOENIX 4.5",
  "phoenix_version": "4.5.0",
  "channel": "stable",
  "release_sequence": 1
}
```

`release_sequence` is not the product version and is not a PHASE number. It is a monotonic publication counter within one channel.

Examples:

```text
stable/1
stable/2
stable/3
beta/1
beta/2
```

Each channel has an independent high-water mark.

## Provenance binding

`release_build_manifest.json` records:

```json
"release": {
  "channel": "stable",
  "sequence": 1,
  "version": "4.5.0"
}
```

and hashes `release_policy.json` under `components.release_policy`.

The archive verifier rejects a ZIP if release policy, provenance, package version, or component hash disagree.

## Local anti-rollback state

After the first PHASE7M-aware upgrade, Phoenix creates:

```text
data/update_release_state.json
```

Example:

```json
{
  "schema_version": 1,
  "current": {
    "channel": "stable",
    "sequence": 3,
    "version": "4.5.0",
    "build_id": "..."
  },
  "highest_sequence_by_channel": {
    "stable": 3
  },
  "policy": "monotonic-per-channel-v1"
}
```

This file is local protected state. It is forbidden in public release ZIPs and is never overwritten by a release payload.

## Normal update rules

For the current channel:

```text
candidate sequence > high-water
→ allowed

candidate sequence < high-water
→ rejected

candidate sequence == current sequence
+ same build_id
→ exact reinstall may be accepted

candidate sequence == current sequence
+ different build_id
→ rejected as sequence collision
```

A sequence number must therefore identify one publication unambiguously.

## Explicit downgrade

Downgrade requires both:

1. local policy permits explicit downgrade; and
2. the user/admin supplies `--allow-downgrade`.

Example:

```powershell
python upgrade_phoenix.py apply `
  --release PHOENIX_4.5.zip `
  --profile windows-ready `
  --allow-downgrade
```

Or with the Windows wrapper:

```bat
set PHOENIX_ALLOW_DOWNGRADE=1
Atualizar_Phoenix.bat PHOENIX_4.5.zip windows-ready
```

Downgrade changes `current`, but never lowers the high-water mark.

Example:

```text
highest stable = 8
explicit downgrade → stable/6

current = 6
highest stable = 8
```

A later ordinary attempt to install 7 is still rejected because 7 < 8.

## Channel switching

The destination channel must first be listed in local protected policy:

```text
data/update_security_policy.json
```

Example:

```json
"allowed_channels": ["stable", "beta"]
```

Then the switch must also be explicit:

```powershell
python upgrade_phoenix.py apply ... --allow-channel-switch
```

or:

```bat
set PHOENIX_ALLOW_CHANNEL_SWITCH=1
Atualizar_Phoenix.bat ...
```

A release cannot add `beta` to the local allowlist because the policy file is protected user/admin state.

## Rollback behavior

Application rollback restores the previous application identity as `current`, but it never lowers `highest_sequence_by_channel`.

Example:

```text
stable/2
→ stable/3
→ application rollback

current = stable/2
high-water stable = 3
```

This means rollback restores operability without making an older release automatically acceptable again.

## Builder usage

The source tree contains a baseline `release_policy.json`, but official builders can override channel/sequence only in staging:

```powershell
python build_release_zip.py `
  --profile source `
  --out phoenix.zip `
  --channel stable `
  --release-sequence 12
```

Environment equivalents:

```text
PHOENIX_RELEASE_CHANNEL=stable
PHOENIX_RELEASE_SEQUENCE=12
```

`build_windows_ready_release.ps1` also accepts `-Channel` and `-ReleaseSequence`.

The source-tree policy is not modified by these overrides.

## Anti-rollback is not authenticity

Sequence enforcement and cryptographic authenticity solve different problems.

Anti-rollback protects against installing an older known release. By itself it cannot prove who created a ZIP. An attacker who can supply arbitrary unsigned releases could fabricate a very high sequence and poison the local high-water mark.

For security-sensitive/official distribution, PHASE7M should therefore be combined with PHASE7L:

```json
{
  "signature_mode": "required"
}
```

Then the effective rule is:

```text
trusted signature
AND trusted key policy
AND allowed channel
AND acceptable release sequence
→ update may proceed
```

## Fail-closed guarantees

PHASE7M rejects:

- unknown channels;
- sequence < 1;
- provenance/policy disagreement;
- release version disagreement;
- downgrade without explicit authorization;
- channel switch without explicit authorization;
- channel not listed in local policy;
- same sequence reused by a different build ID;
- public releases that contain `data/update_release_state.json`.
