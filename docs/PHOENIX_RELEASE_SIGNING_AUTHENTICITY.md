# PHOENIX Release Signing & Authenticity Contract — PHASE7K

## Goal

PHASE7D proves payload integrity. PHASE7K adds publisher authenticity with Ed25519.
Private signing keys are never part of the Phoenix tree or release ZIP.

## Two signatures

1. `release_signature.json` is embedded in the ZIP and signs the exact bytes of
   `release_build_manifest.json`. Because that manifest commits to the full
   release payload fingerprint, this authenticates the release content.
2. `<release>.zip.sig.json` is detached and signs the SHA-256 of the exact ZIP
   bytes. It detects recompression, repackaging, appended bytes, or any other
   byte-level change to the archive.

`release_signature.json` is generated metadata and is excluded from the payload
fingerprint to avoid a signing/fingerprint cycle.

## Root of trust

The ZIP under verification is NEVER allowed to provide the trusted public key
used to authenticate itself. Verification uses either:

- the already-installed local `release_trust_store.json`, or
- an explicitly pinned `--trust-store <path>` obtained through a trusted
  channel.

The `release_trust_store.json` inside a candidate release is distributable
metadata/key-rotation material only; it is not the root of trust for that same
candidate.

For a first installation, the official public-key fingerprint must be obtained
out-of-band (for example from the official project site/repository/release
announcement). Until an official key exists, the repository trust store remains
empty and releases are not claimed as officially signed.

## Building a signed release

Set the private key path outside the Phoenix directory:

```text
PHOENIX_RELEASE_SIGNING_KEY=C:\secure\phoenix-release-ed25519.pem
```

Optional encrypted PEM password:

```text
PHOENIX_RELEASE_SIGNING_KEY_PASSWORD=...
```

Then build with `--require-signature` (or `-RequireSignature` in the Windows
production pipeline). The public key used by that private key must already be
present in the trusted local `release_trust_store.json`, otherwise a required
signed build fails closed.

## Key creation

`release_signing.py keygen --private-out <outside-phoenix-path>` creates an
Ed25519 private key and prints the corresponding public trust-store entry.
The command refuses to create the private key inside the Phoenix project tree.

## Verification

Content + exact archive verification:

```text
python verify_release_archive.py --zip <release.zip> --profile source \
  --require-signature --trust-store <pinned-trust-store.json>
```

When `--require-signature` is active, both the embedded signature and detached
ZIP signature are mandatory.

## Upgrade enforcement

`upgrade_phoenix.py` accepts `--require-signature`.
On Windows, set:

```text
PHOENIX_REQUIRE_SIGNED_RELEASE=1
```

before running `Atualizar_Phoenix.bat` to reject unsigned/untrusted upgrades.

## Key rotation

Key rotation must be authorized by a release signed by a key already trusted by
the current installation. A candidate ZIP cannot bootstrap trust in a new key
for its own signature.

## Current status

The shipped PHASE7K `release_trust_store.json` intentionally contains zero
production keys. No ephemeral/test key is declared official.
