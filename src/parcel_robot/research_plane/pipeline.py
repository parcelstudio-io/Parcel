"""Explicit, default-off composition for the local research plane."""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .admission import AdmissionDecision, AdmissionStatus, admit_candidate
from .bundle import BundleArtifactV1, build_bundle
from .consent import TrustedConsentVerifierV1
from .governor import (
    ByteGovernor,
    EncryptedObjectV1,
    RemoteReceiptV1,
    TransferDecision,
    TrustedReceiptVerifierV1,
    mark_remote_receipt,
)
from .spool import AuthenticatedConsentV1, ResearchSpool, SpoolDecision

if TYPE_CHECKING:  # pragma: no cover - Python 3.10 runtime compatibility
    from typing import Self


@dataclass(frozen=True, slots=True)
class ResearchPlaneConfig:
    enabled: bool = False
    root: Path | None = None
    max_spool_payload_bytes: int = 512 * 1024 * 1024
    target_bundle_bytes: int = 512 * 1024
    daily_summary_bytes: int = 50 * 1024 * 1024
    monthly_summary_bytes: int = 5_000_000_000
    daily_control_bytes: int = 1 * 1024 * 1024
    monthly_control_bytes: int = 30 * 1024 * 1024
    destination: str = "research-local"

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be an exact boolean")
        values = (
            self.max_spool_payload_bytes,
            self.target_bundle_bytes,
            self.daily_summary_bytes,
            self.monthly_summary_bytes,
            self.daily_control_bytes,
            self.monthly_control_bytes,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in values
        ):
            raise ValueError("research-plane byte limits must be positive integers")
        if self.enabled and self.root is None:
            raise ValueError("an enabled research plane requires an explicit root")


class DisabledResearchPlane:
    """No-I/O implementation returned by the canonical default config."""

    enabled = False

    def emit(self, _candidate: Mapping[str, object]) -> tuple[SpoolDecision, str]:
        return SpoolDecision.REJECTED, "research_plane_disabled"

    def bundle_next(self) -> None:
        return None

    def snapshot(self) -> dict[str, object]:
        return {"enabled": False, "reason": "research_plane_disabled"}

    def maintenance(self, *, now: datetime | None = None) -> dict[str, int]:
        """No-I/O boundary: disabled maintenance never opens storage."""

        _ = now
        return {"purged_events": 0, "recovered_claims": 0, "local_deletions": 0, "orphans": 0}

    def close(self) -> None:
        return None


class ResearchPlane:
    """Local admission/spool/bundle coordinator with no network client."""

    enabled = True

    @classmethod
    def from_config(
        cls,
        config: ResearchPlaneConfig,
        *,
        owner_memory_paths: Iterable[str | Path] = (),
        consent_verifier: TrustedConsentVerifierV1 | None = None,
    ) -> ResearchPlane | DisabledResearchPlane:
        if not config.enabled:
            return DisabledResearchPlane()
        return cls(
            config,
            owner_memory_paths=owner_memory_paths,
            consent_verifier=consent_verifier,
        )

    def __init__(
        self,
        config: ResearchPlaneConfig,
        *,
        owner_memory_paths: Iterable[str | Path] = (),
        consent_verifier: TrustedConsentVerifierV1 | None = None,
    ) -> None:
        if not config.enabled or config.root is None:
            raise ValueError("use DisabledResearchPlane for a disabled configuration")
        self.config = config
        self.spool = ResearchSpool(
            root=config.root,
            max_payload_bytes=config.max_spool_payload_bytes,
            owner_memory_paths=owner_memory_paths,
            destination=config.destination,
            consent_verifier=consent_verifier,
        )
        # Recover only claims older than the bounded crash window. A second
        # accidentally configured process must not steal a live bundle claim.
        self.spool.recover_claims()
        self.spool.purge_expired()
        self.spool.reconcile_bundle_artifacts()
        self.governor = ByteGovernor(
            self.spool,
            daily_ordinary_bytes=config.daily_summary_bytes,
            monthly_ordinary_bytes=config.monthly_summary_bytes,
            daily_control_bytes=config.daily_control_bytes,
            monthly_control_bytes=config.monthly_control_bytes,
        )
        self._counters: Counter[str] = Counter()
        self._counter_lock = threading.Lock()

    def record_consent(self, authenticated: AuthenticatedConsentV1) -> bool:
        return self.spool.record_consent(authenticated)

    def emit(self, candidate: Mapping[str, object]) -> tuple[SpoolDecision, str]:
        admission: AdmissionDecision = admit_candidate(candidate)
        if admission.status is AdmissionStatus.REJECTED:
            self._count(f"admission_rejected:{admission.reason}")
            return SpoolDecision.REJECTED, admission.reason
        decision, reason = self.spool.admit(admission)
        self._count(f"spool_{decision.value}:{reason}")
        if admission.redactions:
            for name in admission.redactions:
                self._count(f"redacted:{name}")
        return decision, reason

    def bundle_next(self) -> BundleArtifactV1 | None:
        artifact = build_bundle(
            self.spool,
            target_uncompressed_bytes=self.config.target_bundle_bytes,
        )
        if artifact is not None:
            self._count("bundles_built")
        return artifact

    def authorize_encrypted_transfer(
        self,
        encrypted: EncryptedObjectV1,
        *,
        transfer_attempt_id: str,
    ) -> TransferDecision:
        """Durably charge ciphertext; transport remains an external concern."""

        decision = self.governor.charge(
            encrypted,
            transfer_attempt_id=transfer_attempt_id,
        )
        self._count(f"transfer_{'allowed' if decision.allowed else 'denied'}:{decision.reason}")
        return decision

    def mark_synced(
        self,
        receipt: RemoteReceiptV1,
        *,
        verifier_provider: TrustedReceiptVerifierV1 | None = None,
    ) -> bool:
        stored = mark_remote_receipt(
            self.spool,
            receipt,
            verifier_provider=verifier_provider,
        )
        self._count("bundles_synced" if stored else "duplicate_remote_receipts")
        return stored

    def revoke_consent(self, consent_id: str, *, reason_code: str) -> dict[str, int]:
        result = self.spool.revoke_consent(consent_id, reason_code=reason_code)
        self._count("consents_revoked")
        return result

    def snapshot(self) -> dict[str, object]:
        with self._counter_lock:
            counters = dict(sorted(self._counters.items()))
        return {"enabled": True, "spool": self.spool.snapshot(), "counters": counters}

    def maintenance(self, *, now: datetime | None = None) -> dict[str, int]:
        """Run bounded retention, claim, orphan, and deletion maintenance."""

        result = {
            "purged_events": self.spool.purge_expired(now=now),
            "recovered_claims": self.spool.recover_claims(now=now),
            "local_deletions": self.spool.drain_local_deletions(),
            "orphans": self.spool.reconcile_bundle_artifacts(now=now),
        }
        self._count("maintenance_runs")
        return result

    def close(self) -> None:
        self.spool.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _count(self, key: str) -> None:
        with self._counter_lock:
            self._counters[key] += 1
