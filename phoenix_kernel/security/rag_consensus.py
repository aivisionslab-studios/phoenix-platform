from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from phoenix_kernel.security.rag_integrity import RagIntegrityRegistry
from phoenix_kernel.security.rag_usage_ledger import RagUsageLedger
from phoenix_kernel.security.rag_integrity_manifest import RagIntegrityManifest


@dataclass(frozen=True)
class ConsensusState:
    valid: bool
    reason: str
    authorized_ids: set[str]
    checks: dict[str, bool]
    details: dict[str, Any]


class RagConsensus:
    """4/4 obrigatório: autorização comercial + registry + ledger + manifest."""

    def __init__(
        self,
        registry: RagIntegrityRegistry | None = None,
        ledger: RagUsageLedger | None = None,
        manifest: RagIntegrityManifest | None = None,
    ) -> None:
        self.registry = registry or RagIntegrityRegistry()
        self.ledger = ledger or RagUsageLedger()
        self.manifest = manifest or RagIntegrityManifest()

    @staticmethod
    def _entitlement_state() -> dict[str, Any]:
        # Nome preservado por compatibilidade interna. A autoridade real V4
        # é commercial_guard/capability, não entitlement.json.
        from phoenix_kernel.licensing.commercial_guard import authorization_state
        return authorization_state()

    def validate(self) -> ConsensusState:
        reg = self.registry.load()
        led = self.ledger.load()
        ent = self._entitlement_state()

        # FREE é sempre um estado comercial válido. PRO só é retornado por
        # authorization_state() após capability válida + feature rag.pro.
        entitlement_ok = bool(ent.get("valid"))
        registry_ok = reg.valid and reg.initialized
        ledger_ok = led.valid

        manifest_ok, manifest_reason, manifest_data = self.manifest.verify(
            self.registry.registry_path,
            self.ledger.ledger_path,
            ent,
        )

        checks = {
            "authorization": entitlement_ok,
            "registry": registry_ok,
            "ledger": ledger_ok,
            "manifest": manifest_ok,
        }

        if not all(checks.values()):
            failed = [name for name, ok in checks.items() if not ok]
            return ConsensusState(
                False,
                "consensus_failed:" + ",".join(failed),
                set(),
                checks,
                {
                    "registry_reason": reg.reason,
                    "ledger_reason": led.reason,
                    "manifest_reason": manifest_reason,
                    "authorization_reason": ent["reason"],
                },
            )

        registry_ids = set(reg.documents.keys())
        ledger_ids = set(led.active_documents.keys())

        if registry_ids != ledger_ids:
            return ConsensusState(
                False,
                "registry_ledger_membership_mismatch",
                set(),
                checks,
                {
                    "registry_count": len(registry_ids),
                    "ledger_count": len(ledger_ids),
                },
            )

        return ConsensusState(
            True,
            "ok",
            registry_ids,
            checks,
            {
                "registry_count": len(registry_ids),
                "ledger_count": len(ledger_ids),
                "manifest_generation": int(manifest_data.get("generation") or 0),
                "ledger_generation": led.generation,
                "plan": ent["plan"],
            },
        )

    def checkpoint(self) -> None:
        ent = self._entitlement_state()
        self.manifest.write(
            self.registry.registry_path,
            self.ledger.ledger_path,
            ent,
        )
