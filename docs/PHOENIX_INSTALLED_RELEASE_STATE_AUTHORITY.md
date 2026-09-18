# PHASE7P — Installed Release State / Version Authority

PHASE7P defines one canonical, read-only view for the installed Phoenix release. It does **not** create another persistent source of truth.

## Existing authorities preserved

- `release_build_manifest.json`: immutable build identity/provenance.
- `release_policy.json`: published version/channel/release sequence.
- `data/update_release_state.json`: accepted installed release and anti-rollback high-water.
- `release_trust_store.json`: installed public trust policy.
- `migration_contract.json` + `data/migration_state.json`: target/applied migration schemas.
- `data/startup_integrity_cache.json`: last local integrity evidence/cache; never release identity.

`installed_release_state.py` composes those sources and reports disagreement instead of choosing one silently.

## Status

- `untracked`: source/development tree without release provenance.
- `packaged`: valid packaged build exists but no accepted update state exists yet.
- `consistent`: published identity, build provenance and accepted installed state agree.
- `inconsistent`: two or more authorities disagree.

## Surfaces

- `Estado_Phoenix.bat`
- `python installed_release_state.py show --json`
- `GET /api/release/status`
- `release` field in `GET /api/observability`
- `/health` version/build ID derive from the same authority.

## Ownership rule

PHASE7P is a view, not a database and not an updater. It never writes release state, trust state, migration state or integrity state. Mutations remain owned by the updater/migration/signing/integrity subsystems introduced in PHASE7H–7O.
