# Phoenix Release Key Rotation, Revocation & Signed Update Policy — PHASE7L

## Objective

PHASE7L extends PHASE7K from signature verification into trust lifecycle management. The installed or explicitly pinned trust store is always the root of trust. A release ZIP is never allowed to establish its own trust merely by containing a public key.

## Trust-store schema

`release_trust_store.json` uses schema 2 and a monotonic `policy_version`. Each Ed25519 key has:

- `key_id` — SHA-256-derived identifier of the public key;
- `status` — `active`, `retiring`, or `revoked`;
- `not_before` / `not_after` — optional UTC validity window;
- `revoked_at` and `revocation_reason`;
- `revocation_mode` — `all_signatures` or `signed_at_or_after`.

`retiring` is the normal planned-rotation state. `revoked` is for administrative revocation or compromise.

### Revocation modes

`all_signatures` is the safe default for a compromised key. The key is rejected even when an attacker backdates `signed_at_utc`.

`signed_at_or_after` preserves verification of signatures whose authenticated `signed_at_utc` predates `revoked_at`. Use it only when historical auditability is intentionally preferred over full compromise invalidation.

## Monotonic policy

A Phoenix update never accepts:

- a lower `policy_version`;
- a different trust store with the same `policy_version`;
- removal or reactivation of a key already recorded as revoked.

Application rollback does not roll the trust policy backwards. If policy v5 is installed and the application is rolled back, policy v5 remains. A security-policy correction must therefore be published as policy v6, not by restoring v4/v5 files.

## Planned rotation OLD → NEW

1. Keep the currently trusted policy as `trust-v1.json`.
2. Generate NEW outside the Phoenix tree:

```powershell
python release_signing.py keygen --private-out D:\PhoenixKeys\release-new.pem > D:\PhoenixKeys\new-public.json
```

3. Create a candidate policy with NEW. The helper always writes a new file and increments `policy_version`:

```powershell
python release_signing.py add-key `
  --trust-store D:\PhoenixKeys\trust-v1.json `
  --public-entry D:\PhoenixKeys\new-public.json `
  --out D:\PhoenixKeys\trust-v2.json
```

4. Optionally create another candidate marking OLD as retiring with a fixed `not_after`. Each operation creates another monotonic policy version:

```powershell
python release_signing.py retire-key `
  --trust-store D:\PhoenixKeys\trust-v2.json `
  --key-id ed25519-OLD `
  --not-after 2027-01-01T00:00:00Z `
  --out D:\PhoenixKeys\trust-v3.json
```

5. Place the final candidate public trust store in the release source as `release_trust_store.json`. Never place either private key in the Phoenix tree.

6. Build the release signed by NEW while OLD authorizes the trust transition:

```powershell
$env:PHOENIX_RELEASE_SIGNING_KEY = 'D:\PhoenixKeys\release-new.pem'
$env:PHOENIX_PREVIOUS_TRUST_STORE = 'D:\PhoenixKeys\trust-v1.json'
$env:PHOENIX_TRUST_TRANSITION_KEY = 'D:\PhoenixKeys\release-old.pem'

powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_ready_release.ps1 -RequireSignature
```

The builder generates `release_trust_transition.json` before provenance. Its bytes are therefore included in the payload fingerprint. The transition contains the old and new policy versions, SHA-256 of the candidate trust store, authorization time, signer key ID, and an Ed25519 signature by OLD.

A machine that trusts only OLD can validate the transition, promote the candidate policy for this verification, and then verify the release/ZIP signatures made by NEW.

## Emergency revocation

Create a new policy instead of editing the installed one:

```powershell
python release_signing.py revoke-key `
  --trust-store D:\PhoenixKeys\trust-v3.json `
  --key-id ed25519-COMPROMISED `
  --reason 'suspected private-key compromise' `
  --mode all_signatures `
  --out D:\PhoenixKeys\trust-v4.json
```

The new policy still requires an authorized transition from a different key that remains trusted. If every trusted private key is lost or compromised, automated rotation cannot safely bootstrap a replacement; an out-of-band pinned trust store is required.

## First official-key bootstrap

The repository intentionally ships with no production public key. The first key cannot be made trustworthy by the same untrusted ZIP that contains it.

For the first official bootstrap, pin the public trust store out-of-band and use:

```bat
set PHOENIX_RELEASE_TRUST_STORE=D:\PhoenixKeys\phoenix-official-trust.json
set PHOENIX_REQUIRE_SIGNED_RELEASE=1
Atualizar_Phoenix.bat PHOENIX_4.5_WINDOWS_READY.zip windows-ready
```

Explicit bootstrap is only accepted while the installed trust policy has no keys. It can be disabled locally through `data/update_security_policy.json`.

## Persistent signed-update policy

Copy:

`update_security_policy.template.json`

into:

`data/update_security_policy.json`

and set:

```json
{
  "schema_version": 1,
  "signature_mode": "required",
  "allow_explicit_pinned_bootstrap": false
}
```

The local file is protected user/security state. Releases cannot ship it, overwrite it, or roll it back. CLI `--require-signature` and `PHOENIX_REQUIRE_SIGNED_RELEASE=1` can still force strict mode even when the local policy is `optional`.

## Trust transition invariants

A transition is rejected when:

- the signer was not already in the installed trust policy;
- the signer is outside its validity window;
- the signer is revoked according to its lifecycle policy;
- `from_policy_version` differs from the installed policy;
- `to_policy_version` differs from the candidate policy;
- candidate version is not higher;
- candidate trust-store SHA-256 differs;
- a revoked key is removed, redefined, or reactivated;
- the Ed25519 signature is invalid.

## What PHASE7L does not solve

No signature system can cryptographically solve the very first trust decision if both software and public key arrive solely through the same untrusted channel. The first Phoenix production public key must be pinned through a separately trusted channel or installation process.
