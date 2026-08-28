"""Dedicated crash-safe SQLite spool for admitted research summaries.

The spool owns no adapter back into conversation memory or robot control.  Its
database must live under an explicit research root and may not contain a known
owner-memory path.  Consent checks, duplicate checks, and insertion occur in
one ``BEGIN IMMEDIATE`` transaction.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from .admission import AdmissionDecision
from .bundle_reconcile import (
    abandon_publication_intent,
    reconcile_bundle_artifacts,
    record_publication_intent,
)
from .consent import (
    AuthenticatedConsentV1,
    ConsentRecordV1,
    TrustedConsentVerifierV1,
)
from .consent_persistence import (
    load_verified_consent,
    persist_authenticated_consent,
    persisted_consent_rejection,
)
from .contracts import ResearchEventV1, sha256_hex
from .local_deletion import DeletionUnlinker, capture_local_identity, drain_local_deletions
from .spool_schema import create_spool_schema
from .spool_snapshot import spool_snapshot
from .spool_transfer_validation import validate_persisted_bundle_for_transfer
from .sqlite_batches import replace_temp_ids

__all__ = [
    "AuthenticatedConsentV1",
    "ClaimedEventsV1",
    "ConsentRecordV1",
    "ResearchSpool",
    "SpoolDecision",
    "TrustedConsentVerifierV1",
    "ValidatedBundleV1",
]

if TYPE_CHECKING:  # pragma: no cover - Python 3.10 runtime compatibility
    from typing import Self

SPOOL_SCHEMA_VERSION = 7
SPOOL_APPLICATION_ID = 0x50525331  # ASCII-ish "PRS1", distinct from owner memory.
RETENTION_DAYS = {"summary_90d": 90, "feedback_1y": 365, "consented_text_30d": 30}
_PSEUDONYM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _resolve_child(root: Path, child: Path) -> Path:
    root_resolved = root.expanduser().resolve()
    candidate = child.expanduser()
    if not candidate.is_absolute():
        candidate = root_resolved / candidate
    candidate = candidate.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"research path escapes configured root: {candidate}")
    return candidate


class SpoolDecision(str, Enum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ClaimedEventsV1:
    claim_token: str
    event_bytes: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class ValidatedBundleV1:
    bundle_sha256: str
    priority: int
    state: str


class ResearchSpool:
    """A bounded research-only event spool.

    ``max_payload_bytes`` caps canonical event payloads, not SQLite page
    overhead.  The distinction is surfaced by :meth:`snapshot`; operators must
    reserve disk for SQLite overhead separately.
    """

    def __init__(
        self,
        *,
        root: str | Path,
        database_name: str = "research_spool.sqlite3",
        max_payload_bytes: int = 512 * 1024 * 1024,
        owner_memory_paths: Iterable[str | Path] = (),
        destination: str = "research-local",
        deletion_unlinker: DeletionUnlinker | None = None,
        consent_verifier: TrustedConsentVerifierV1 | None = None,
    ) -> None:
        if (
            isinstance(max_payload_bytes, bool)
            or not isinstance(max_payload_bytes, int)
            or max_payload_bytes <= 0
        ):
            raise ValueError("max_payload_bytes must be a positive integer")
        if deletion_unlinker is not None and not callable(deletion_unlinker):
            raise TypeError("deletion_unlinker must be callable")
        if consent_verifier is not None and not isinstance(
            consent_verifier, TrustedConsentVerifierV1
        ):
            raise TypeError("consent_verifier must be TrustedConsentVerifierV1")
        if not _PSEUDONYM.fullmatch(destination):
            raise ValueError("destination must be a bounded identifier")
        self.destination = destination
        self.root = Path(root).expanduser().resolve()
        self.database_path = _resolve_child(self.root, Path(database_name))
        for owner_path in owner_memory_paths:
            owner = Path(owner_path).expanduser().resolve()
            if owner == self.database_path or self.root == owner or self.root in owner.parents:
                raise ValueError("research root may not contain owner memory")
        self.root.mkdir(parents=True, exist_ok=True)
        self.bundle_root = _resolve_child(self.root, Path("bundles"))
        self.bundle_root.mkdir(parents=True, exist_ok=True)
        self.encrypted_root = _resolve_child(self.root, Path("encrypted"))
        self.encrypted_root.mkdir(parents=True, exist_ok=True)
        self.max_payload_bytes = int(max_payload_bytes)
        self._deletion_unlinker = deletion_unlinker
        self._consent_verifier = consent_verifier
        self._publication_owner_token = str(uuid.uuid4())
        self._lock = threading.RLock()
        self._closed = False
        existing_database = self.database_path.exists() and self.database_path.stat().st_size > 0
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        application_id = int(self._connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if existing_database and (
            application_id != SPOOL_APPLICATION_ID or user_version != SPOOL_SCHEMA_VERSION
        ):
            self._connection.close()
            raise RuntimeError("existing database is not a Parcel research spool")
        if not existing_database:
            self._connection.execute(f"PRAGMA application_id={SPOOL_APPLICATION_ID}")
            self._connection.execute(f"PRAGMA user_version={SPOOL_SCHEMA_VERSION}")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        try:
            create_spool_schema(
                self._connection,
                schema_version=SPOOL_SCHEMA_VERSION,
                destination=self.destination,
            )
        except Exception:
            self._connection.close()
            raise
        check = self._connection.execute("PRAGMA quick_check").fetchone()
        if check != ("ok",):
            self._connection.close()
            raise RuntimeError(f"research spool integrity check failed: {check!r}")
        self.drain_local_deletions()
        self.reconcile_bundle_artifacts()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def record_consent(self, authenticated: AuthenticatedConsentV1) -> bool:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                stored = persist_authenticated_consent(
                    self._connection,
                    authenticated,
                    destination=self.destination,
                    verifier_provider=self._consent_verifier,
                )
                self._connection.commit()
                return stored
            except Exception:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise

    def revoke_consent(
        self,
        consent_id: str,
        *,
        reason_code: str,
        revoked_at: datetime | None = None,
    ) -> dict[str, int]:
        now = revoked_at or _utc_now()
        now_text = _iso(now)
        if not _PSEUDONYM.fullmatch(reason_code):
            raise ValueError("reason_code must be a bounded identifier")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                corrupt_record = False
                try:
                    verified = load_verified_consent(
                        self._connection,
                        consent_id,
                        verifier_provider=self._consent_verifier,
                    )
                except ValueError:
                    verified = None
                    corrupt_record = True
                if verified is None and not corrupt_record:
                    raise KeyError(f"unknown consent_id: {consent_id}")
                if verified is not None:
                    subject = verified.record.subject_pseudonym
                    purpose = verified.record.purpose
                else:
                    event_subject = self._connection.execute(
                        """SELECT robot_pseudonym FROM events
                           WHERE consent_id = ? ORDER BY occurred_at LIMIT 1""",
                        (consent_id,),
                    ).fetchone()
                    subject = str(event_subject[0]) if event_subject else "invalid_consent_record"
                    purpose = "research_evaluation"
                self._connection.execute(
                    """
                    UPDATE consents SET revoked_at = COALESCE(revoked_at, ?),
                        revocation_reason = COALESCE(revocation_reason, ?)
                    WHERE consent_id = ?
                    """,
                    (now_text, reason_code, consent_id),
                )
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO tombstones(
                        consent_id, subject_pseudonym, purpose, created_at, reason_code
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (consent_id, subject, purpose, now_text, reason_code),
                )
                event_ids = [
                    str(item[0])
                    for item in self._connection.execute(
                        "SELECT event_id FROM events WHERE consent_id = ?", (consent_id,)
                    )
                ]
                result = self._cascade_remove_events_locked(
                    event_ids,
                    reason_code=reason_code,
                    now=now,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        self.drain_local_deletions()
        return {
            "affected_events": len(event_ids),
            "deleted_events": result["deleted_events"],
            "invalidated_bundles": result["deleted_bundles"],
            "requeued_events": result["requeued_events"],
        }

    def _event_retained_locked(self, event_id: str, now: datetime) -> bool:
        row = self._connection.execute(
            """
            SELECT expires_at, privacy_class, consent_id, stream,
                   robot_pseudonym, occurred_at
            FROM events WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None or _parse(str(row[0])) <= now:
            return False
        if row[1] != "consent_required":
            return True
        return (
            persisted_consent_rejection(
                self._connection,
                consent_id=str(row[2]) if row[2] is not None else None,
                stream=str(row[3]),
                robot_pseudonym=str(row[4]),
                occurred=_parse(str(row[5])),
                now=now,
                destination=self.destination,
                verifier_provider=self._consent_verifier,
            )
            is None
        )

    def _cascade_remove_events_locked(
        self,
        requested_event_ids: Sequence[str],
        *,
        reason_code: str,
        now: datetime,
    ) -> dict[str, int]:
        requested = set(requested_event_ids)
        if not requested:
            return {"deleted_events": 0, "deleted_bundles": 0, "requeued_events": 0}
        replace_temp_ids(self._connection, "purge_requested_ids", requested)
        bundle_ids, all_bundle_events, bundle_rows, encrypted_rows = (
            self._collect_bundle_artifacts_locked()
        )

        delete_ids = set(requested)
        survivors: set[str] = set()
        for event_id in all_bundle_events - requested:
            if self._event_retained_locked(event_id, now):
                survivors.add(event_id)
            else:
                delete_ids.add(event_id)

        now_text = _iso(now)
        self._journal_deletions_and_obligations(
            encrypted_rows,
            bundle_rows,
            reason_code=reason_code,
            now_text=now_text,
        )

        for bundle_id in bundle_ids:
            self._connection.execute(
                "DELETE FROM remote_receipts WHERE source_bundle_sha256 = ?", (bundle_id,)
            )
            self._connection.execute("DELETE FROM bundles WHERE bundle_sha256 = ?", (bundle_id,))
        if survivors:
            replace_temp_ids(self._connection, "purge_survivor_ids", survivors)
            self._connection.execute(
                """
                UPDATE events SET state = 'queued', claim_token = NULL, claimed_at = NULL
                WHERE event_id IN (SELECT event_id FROM purge_survivor_ids)
                """
            )
        if delete_ids:
            replace_temp_ids(self._connection, "purge_delete_ids", delete_ids)
            self._connection.execute(
                "DELETE FROM events WHERE event_id IN (SELECT event_id FROM purge_delete_ids)"
            )
        tombstone_id = str(uuid.uuid4())
        self._connection.execute(
            """
            INSERT INTO purge_tombstones(
                tombstone_id, created_at, reason_code, event_count, bundle_count
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (tombstone_id, now_text, reason_code, len(delete_ids), len(bundle_ids)),
        )
        return {
            "deleted_events": len(delete_ids),
            "deleted_bundles": len(bundle_ids),
            "requeued_events": len(survivors),
        }

    def _collect_bundle_artifacts_locked(
        self,
    ) -> tuple[
        list[str], set[str], list[tuple[str, str, str, str]], list[tuple[str, str, str, str]]
    ]:
        bundle_ids = [
            str(row[0])
            for row in self._connection.execute(
                """SELECT DISTINCT be.bundle_sha256 FROM bundle_events be
                   JOIN purge_requested_ids p ON p.event_id = be.event_id"""
            )
        ]
        all_events: set[str] = set()
        bundle_rows: list[tuple[str, str, str, str]] = []
        encrypted_rows: list[tuple[str, str, str, str]] = []
        for bundle_id in bundle_ids:
            all_events.update(
                str(row[0])
                for row in self._connection.execute(
                    "SELECT event_id FROM bundle_events WHERE bundle_sha256 = ?",
                    (bundle_id,),
                )
            )
            bundle = self._connection.execute(
                """SELECT bundle_sha256, path, manifest_path, manifest_file_sha256
                   FROM bundles WHERE bundle_sha256 = ?""",
                (bundle_id,),
            ).fetchone()
            if bundle is not None:
                bundle_rows.append(tuple(str(value) for value in bundle))
            encrypted = self._connection.execute(
                """SELECT source_bundle_sha256, ciphertext_sha256,
                          ciphertext_path, destination
                   FROM encrypted_objects WHERE source_bundle_sha256 = ?""",
                (bundle_id,),
            ).fetchone()
            if encrypted is not None:
                encrypted_rows.append(tuple(str(value) for value in encrypted))
        return bundle_ids, all_events, bundle_rows, encrypted_rows

    def _journal_deletions_and_obligations(
        self,
        encrypted_rows: Sequence[tuple[str, str, str, str]],
        bundle_rows: Sequence[tuple[str, str, str, str]],
        *,
        reason_code: str,
        now_text: str,
    ) -> None:
        for source_sha, cipher_sha, encrypted_path, destination in encrypted_rows:
            obligation_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"parcel-delete:{source_sha}:{cipher_sha}:{destination}:{reason_code}",
                )
            )
            receipt = self._connection.execute(
                """SELECT provider_receipt_id, receipt_verifier_id,
                          receipt_sha256, signature
                   FROM remote_receipts WHERE source_bundle_sha256 = ?""",
                (source_sha,),
            ).fetchone()
            audit = tuple(receipt) if receipt is not None else (None, None, None, None)
            proof_sha = sha256_hex(str(audit[3]).encode("utf-8")) if audit[3] else None
            self._connection.execute(
                """INSERT OR IGNORE INTO deletion_obligations(
                       obligation_id, source_bundle_sha256, ciphertext_sha256,
                       destination, remote_provider_receipt_id, receipt_verifier_id,
                       receipt_proof_sha256, receipt_record_sha256,
                       created_at, reason_code
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    obligation_id,
                    source_sha,
                    cipher_sha,
                    destination,
                    audit[0],
                    audit[1],
                    proof_sha,
                    audit[2],
                    now_text,
                    reason_code,
                ),
            )
            self._journal_local_path(
                "encrypted", encrypted_path, cipher_sha, source_sha, now_text, reason_code
            )
        for source_sha, bundle_path, manifest_path, manifest_sha in bundle_rows:
            self._journal_local_path(
                "bundle", bundle_path, source_sha, source_sha, now_text, reason_code
            )
            self._journal_local_path(
                "bundle", manifest_path, manifest_sha, source_sha, now_text, reason_code
            )

    def _journal_local_path(
        self,
        managed_kind: str,
        relative_path: str,
        content_sha256: str,
        generation_id: str,
        now_text: str,
        reason_code: str,
    ) -> None:
        if (
            managed_kind not in {"bundle", "encrypted"}
            or not relative_path
            or len(relative_path) > 512
            or Path(relative_path).is_absolute()
        ):
            raise ValueError("invalid managed deletion intent")
        entry_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"parcel-local-delete:{managed_kind}:{relative_path}:{generation_id}",
            )
        )
        root = self.bundle_root if managed_kind == "bundle" else self.encrypted_root
        try:
            device_id, inode = capture_local_identity(root, relative_path, content_sha256)
        except (OSError, ValueError):
            # Commit a quarantine intent even when the target was replaced or
            # tampered. Null identity is deliberately non-deletable while the
            # name exists, so retention/revocation can proceed without ever
            # unlinking an unverified replacement.
            device_id = inode = 0
        existing = self._connection.execute(
            """SELECT content_sha256, generation_id FROM local_deletion_journal
               WHERE managed_kind = ? AND relative_path = ?""",
            (managed_kind, relative_path),
        ).fetchone()
        if existing is not None and tuple(existing) != (content_sha256, generation_id):
            raise ValueError("managed deletion path reuse is not allowed")
        self._connection.execute(
            """INSERT OR IGNORE INTO local_deletion_journal(
                   entry_id, managed_kind, relative_path, content_sha256,
                   generation_id, device_id, inode, created_at, reason_code
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                managed_kind,
                relative_path,
                content_sha256,
                generation_id,
                device_id or None,
                inode or None,
                now_text,
                reason_code,
            ),
        )

    def admit(
        self,
        decision: AdmissionDecision,
        *,
        now: datetime | None = None,
    ) -> tuple[SpoolDecision, str]:
        if not decision.accepted or decision.event is None:
            return SpoolDecision.REJECTED, decision.reason
        event = decision.event
        now_utc = (now or _utc_now()).astimezone(timezone.utc)
        occurred = _parse(event.occurred_at)
        if occurred > now_utc + timedelta(minutes=5):
            return SpoolDecision.REJECTED, "event_from_future"
        expiry = occurred + timedelta(days=RETENTION_DAYS[event.retention_class])
        if expiry <= now_utc:
            return SpoolDecision.REJECTED, "already_expired"
        encoded = event.canonical_bytes()
        digest = sha256_hex(encoded)

        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                rejection = self._consent_rejection(event, occurred, now_utc)
                if rejection is not None:
                    self._connection.rollback()
                    return SpoolDecision.REJECTED, rejection

                existing = self._connection.execute(
                    "SELECT event_sha256 FROM events WHERE event_id = ?", (event.event_id,)
                ).fetchone()
                if existing is not None:
                    self._connection.rollback()
                    if existing[0] != digest:
                        raise ValueError("event_id collision with different content")
                    return SpoolDecision.DUPLICATE, "duplicate_event_id"
                sequence = self._connection.execute(
                    "SELECT event_id FROM events WHERE run_id = ? AND stream = ? AND sequence = ?",
                    (event.run_id, event.stream, event.sequence),
                ).fetchone()
                if sequence is not None:
                    self._connection.rollback()
                    raise ValueError("run/stream/sequence collision with a different event")
                used = int(
                    self._connection.execute(
                        "SELECT COALESCE(SUM(LENGTH(event_json)), 0) FROM events"
                    ).fetchone()[0]
                )
                if used + len(encoded) > self.max_payload_bytes:
                    self._connection.rollback()
                    return SpoolDecision.REJECTED, "spool_payload_cap"
                self._connection.execute(
                    """
                    INSERT INTO events(
                        event_id, run_id, stream, sequence, robot_pseudonym, occurred_at, priority,
                        privacy_class, consent_id, retention_class, expires_at,
                        event_json, event_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.run_id,
                        event.stream,
                        event.sequence,
                        event.robot_pseudonym,
                        event.occurred_at,
                        event.priority,
                        event.privacy_class,
                        event.consent_id,
                        event.retention_class,
                        _iso(expiry),
                        encoded,
                        digest,
                    ),
                )
                self._connection.commit()
            except Exception:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise
        return SpoolDecision.STORED, "stored"

    def _consent_rejection(
        self,
        event: ResearchEventV1,
        occurred: datetime,
        now: datetime,
    ) -> str | None:
        if event.privacy_class != "consent_required":
            return None
        return persisted_consent_rejection(
            self._connection,
            consent_id=event.consent_id,
            stream=event.stream,
            robot_pseudonym=event.robot_pseudonym,
            occurred=occurred,
            now=now,
            destination=self.destination,
            verifier_provider=self._consent_verifier,
        )

    def purge_expired(self, *, now: datetime | None = None) -> int:
        current = (now or _utc_now()).astimezone(timezone.utc)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                event_ids: list[str] = []
                rows = self._connection.execute(
                    """SELECT event_id, expires_at, privacy_class, consent_id,
                              stream, robot_pseudonym, occurred_at
                       FROM events
                       WHERE expires_at <= ? OR privacy_class = 'consent_required'""",
                    (_iso(current),),
                ).fetchall()
                for row in rows:
                    expired = _parse(str(row[1])) <= current
                    consent_invalid = row[2] == "consent_required" and (
                        persisted_consent_rejection(
                            self._connection,
                            consent_id=str(row[3]) if row[3] is not None else None,
                            stream=str(row[4]),
                            robot_pseudonym=str(row[5]),
                            occurred=_parse(str(row[6])),
                            now=current,
                            destination=self.destination,
                            verifier_provider=self._consent_verifier,
                        )
                        is not None
                    )
                    if expired or consent_invalid:
                        event_ids.append(str(row[0]))
                result = self._cascade_remove_events_locked(
                    event_ids,
                    reason_code="retention_or_consent_expired",
                    now=current,
                )
                self._connection.commit()
                deleted = result["deleted_events"]
            except Exception:
                self._connection.rollback()
                raise
        self.drain_local_deletions()
        return deleted

    def recover_claims(
        self,
        *,
        older_than: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> int:
        threshold = (now or _utc_now()) - older_than
        with self._lock:
            count = self._connection.execute(
                """
                UPDATE events SET state = 'queued', claim_token = NULL, claimed_at = NULL
                WHERE state = 'claimed' AND claimed_at < ?
                """,
                (_iso(threshold),),
            ).rowcount
            self._connection.commit()
            return count

    def claim_queued(
        self,
        *,
        target_uncompressed_bytes: int = 512 * 1024,
        max_events: int = 4096,
        now: datetime | None = None,
    ) -> ClaimedEventsV1 | None:
        if target_uncompressed_bytes <= 0 or max_events <= 0:
            raise ValueError("claim limits must be positive")
        timestamp = now or _utc_now()
        self.purge_expired(now=timestamp)
        token = str(uuid.uuid4())
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                first_priority = self._connection.execute(
                    "SELECT MIN(priority) FROM events WHERE state = 'queued'"
                ).fetchone()[0]
                if first_priority is None:
                    self._connection.rollback()
                    return None
                rows = self._connection.execute(
                    """
                    SELECT event_id, event_json FROM events
                    WHERE state = 'queued' AND priority = ?
                    ORDER BY priority, occurred_at, stream, sequence, event_id
                    LIMIT ?
                    """,
                    (first_priority, max_events),
                ).fetchall()
                selected: list[tuple[str, bytes]] = []
                total = 0
                for event_id, encoded_raw in rows:
                    encoded = bytes(encoded_raw)
                    size = len(encoded) + 1
                    if selected and total + size > target_uncompressed_bytes:
                        break
                    selected.append((str(event_id), encoded))
                    total += size
                if not selected:
                    self._connection.rollback()
                    return None
                placeholders = ",".join("?" for _ in selected)
                ids = [event_id for event_id, _ in selected]
                self._connection.execute(
                    f"""
                    UPDATE events SET state = 'claimed', claim_token = ?, claimed_at = ?
                    WHERE state = 'queued' AND event_id IN ({placeholders})
                    """,
                    (token, _iso(timestamp), *ids),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return ClaimedEventsV1(token, tuple(encoded for _, encoded in selected))

    def release_claim(self, claim_token: str) -> int:
        with self._lock:
            count = self._connection.execute(
                """
                UPDATE events SET state = 'queued', claim_token = NULL, claimed_at = NULL
                WHERE state = 'claimed' AND claim_token = ?
                """,
                (claim_token,),
            ).rowcount
            self._connection.commit()
            return count

    def register_bundle(
        self,
        *,
        claim_token: str,
        bundle_sha256: str,
        bundle_path: Path,
        manifest_path: Path,
        priority: int,
        event_ids: Sequence[str],
        compressed_bytes: int,
        uncompressed_bytes: int,
        manifest_file_sha256: str,
        manifest_content_sha256: str,
        event_id_digest: str,
        first_event_id: str,
        last_event_id: str,
        lineage_sha256: str,
        created_at: datetime | None = None,
    ) -> None:
        bundle = _resolve_child(self.bundle_root, bundle_path)
        manifest = _resolve_child(self.bundle_root, manifest_path)
        if not bundle.is_file() or not manifest.is_file():
            raise ValueError("bundle and manifest must exist below the bundle root")
        if compressed_bytes != bundle.stat().st_size:
            raise ValueError("compressed byte count does not match bundle")
        registered_at = created_at or _utc_now()
        registered_text = _iso(registered_at)
        registered_utc = _parse(registered_text)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                intent = self._connection.execute(
                    """SELECT owner_token, lease_expires_at
                       FROM bundle_publication_intents WHERE claim_token = ?""",
                    (claim_token,),
                ).fetchone()
                if intent is None or intent[0] != self._publication_owner_token:
                    raise ValueError("bundle publication intent ownership mismatch")
                if _parse(str(intent[1])) <= registered_utc:
                    raise ValueError("bundle publication lease expired")
                claimed = self._connection.execute(
                    "SELECT event_id FROM events WHERE state = 'claimed' AND claim_token = ?",
                    (claim_token,),
                ).fetchall()
                claimed_ids = {str(row[0]) for row in claimed}
                if claimed_ids != set(event_ids) or len(claimed_ids) != len(event_ids):
                    raise ValueError("bundle event IDs do not exactly match claim")
                self._connection.execute(
                    """
                    INSERT INTO bundles(
                        bundle_sha256, path, manifest_path, priority, event_count,
                        compressed_bytes, uncompressed_bytes, manifest_file_sha256,
                        manifest_content_sha256, event_id_digest, first_event_id,
                        last_event_id, lineage_sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bundle_sha256,
                        str(bundle.relative_to(self.bundle_root)),
                        str(manifest.relative_to(self.bundle_root)),
                        priority,
                        len(event_ids),
                        compressed_bytes,
                        uncompressed_bytes,
                        manifest_file_sha256,
                        manifest_content_sha256,
                        event_id_digest,
                        first_event_id,
                        last_event_id,
                        lineage_sha256,
                        registered_text,
                    ),
                )
                self._connection.executemany(
                    "INSERT INTO bundle_events(bundle_sha256, event_id) VALUES (?, ?)",
                    ((bundle_sha256, event_id) for event_id in event_ids),
                )
                self._connection.execute(
                    """
                    UPDATE events SET state = 'bundled', claim_token = NULL, claimed_at = NULL
                    WHERE claim_token = ?
                    """,
                    (claim_token,),
                )
                self._connection.execute(
                    """DELETE FROM bundle_publication_intents
                       WHERE claim_token = ? AND owner_token = ?""",
                    (claim_token, self._publication_owner_token),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def record_bundle_publication_intent(
        self,
        *,
        claim_token: str,
        bundle_sha256: str,
        bundle_path: Path,
        manifest_path: Path,
        bundle_stage_path: Path,
        manifest_stage_path: Path,
        now: datetime | None = None,
    ) -> None:
        record_publication_intent(
            self._connection,
            self._lock,
            self.bundle_root,
            claim_token=claim_token,
            owner_token=self._publication_owner_token,
            bundle_sha256=bundle_sha256,
            paths=(bundle_path, manifest_path, bundle_stage_path, manifest_stage_path),
            now=now,
        )

    def abandon_bundle_publication(self, claim_token: str) -> bool:
        return abandon_publication_intent(
            self._connection,
            self._lock,
            claim_token=claim_token,
            owner_token=self._publication_owner_token,
        )

    def reconcile_bundle_artifacts(
        self,
        *,
        max_entries: int = 4096,
        now: datetime | None = None,
    ) -> int:
        return reconcile_bundle_artifacts(
            self._connection,
            self._lock,
            self.bundle_root,
            max_entries=max_entries,
            now=now,
        )

    def bundle_uploadable(self, bundle_sha256: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT state, invalidated FROM bundles WHERE bundle_sha256 = ?",
                (bundle_sha256,),
            ).fetchone()
        return row is not None and row[0] in {"local", "charged"} and row[1] == 0

    def validate_bundle_for_transfer(
        self,
        bundle_sha256: str,
        *,
        now: datetime | None = None,
        allow_synced: bool = False,
    ) -> ValidatedBundleV1:
        """Re-verify DB state, retention, consent, manifest, and payload bytes."""

        current = (now or _utc_now()).astimezone(timezone.utc)
        priority, state = validate_persisted_bundle_for_transfer(
            self._connection,
            self._lock,
            bundle_root=self.bundle_root,
            destination=self.destination,
            bundle_sha256=bundle_sha256,
            current=current,
            allow_synced=allow_synced,
            consent_verifier=self._consent_verifier,
        )
        return ValidatedBundleV1(bundle_sha256, priority, state)

    def managed_encrypted_path(self, path: str | Path) -> Path:
        """Resolve an encrypted object strictly below the configured managed root."""

        resolved = _resolve_child(self.encrypted_root, Path(path))
        if resolved.parent != self.encrypted_root:
            raise ValueError("encrypted objects must be direct managed-root children")
        return resolved

    def snapshot(self) -> dict[str, object]:
        return spool_snapshot(
            self._connection,
            self._lock,
            schema_version=SPOOL_SCHEMA_VERSION,
            database_path=self.database_path,
            max_payload_bytes=self.max_payload_bytes,
            destination=self.destination,
        )

    def drain_local_deletions(self, *, max_entries: int = 256) -> int:
        """Idempotently drain committed local deletion intents."""

        return drain_local_deletions(
            self._connection,
            self._lock,
            roots={"bundle": self.bundle_root, "encrypted": self.encrypted_root},
            unlinker=self._deletion_unlinker,
            max_entries=max_entries,
        )

    @property
    def connection_for_governor(self) -> sqlite3.Connection:
        """Package-private persistence seam used only by :class:`ByteGovernor`."""

        return self._connection

    @property
    def lock_for_governor(self) -> threading.RLock:
        return self._lock
