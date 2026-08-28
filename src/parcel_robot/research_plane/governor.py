"""Fail-closed cryptographic admission, transfer accounting, and receipts.

This module provides no encryption, key, upload, or receipt provider. Product
composition must inject providers that independently verify AES-GCM
authentication and remote receipt authenticity.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .contracts import canonical_json_bytes, sha256_hex
from .spool import ResearchSpool

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[0-9a-f]{24}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,191}$")
_SIGNATURE = re.compile(r"^[A-Za-z0-9_+=./:-]{16,1024}$")
AAD_SCHEMA = "parcel.research.transfer_aad.v1"
RECEIPT_SCHEMA = "parcel.research.remote_receipt.v1"
MAX_CIPHERTEXT_BYTES = 64 * 1024 * 1024

AeadVerifier = Callable[[Path, str, str, bytes, str], bool]
ReceiptVerifier = Callable[[bytes, str], bool]


def _ciphertext_fingerprint(path: Path) -> tuple[int, str]:
    if not path.is_file():
        raise ValueError("ciphertext_path must be a file")
    size = path.stat().st_size
    if size < 17 or size > MAX_CIPHERTEXT_BYTES:
        raise ValueError("ciphertext size is outside the bounded prototype envelope")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return size, digest.hexdigest()


def transfer_aad_bytes(source_bundle_sha256: str, priority: int, destination: str) -> bytes:
    """Return the sole canonical AAD representation accepted by v1."""

    if not _SHA256.fullmatch(source_bundle_sha256):
        raise ValueError("source_bundle_sha256 is invalid")
    if isinstance(priority, bool) or not 0 <= priority <= 3:
        raise ValueError("priority must be between zero and three")
    if not _IDENTIFIER.fullmatch(destination):
        raise ValueError("destination is invalid")
    return canonical_json_bytes(
        {
            "destination": destination,
            "priority": priority,
            "schema": AAD_SCHEMA,
            "source_bundle_sha256": source_bundle_sha256,
        }
    )


@dataclass(frozen=True, slots=True)
class EncryptedObjectV1:
    """Ciphertext metadata authenticated by an injected trusted provider."""

    source_bundle_sha256: str
    ciphertext_sha256: str
    ciphertext_path: Path
    byte_count: int
    priority: int
    destination: str
    algorithm: str
    nonce_hex: str
    wrapped_key_id: str
    aad_sha256: str
    _aead_verified: bool = field(init=False, repr=False, compare=False, default=False)

    @classmethod
    def from_file(
        cls,
        *,
        source_bundle_sha256: str,
        ciphertext_path: str | Path,
        priority: int,
        destination: str,
        nonce_hex: str,
        wrapped_key_id: str,
        aad_sha256: str,
        aead_verifier: AeadVerifier | None = None,
        algorithm: str = "AES-256-GCM",
    ) -> EncryptedObjectV1:
        path = Path(ciphertext_path).expanduser().resolve()
        byte_count, ciphertext_sha = _ciphertext_fingerprint(path)
        aad = transfer_aad_bytes(source_bundle_sha256, priority, destination)
        if sha256_hex(aad) != aad_sha256:
            raise ValueError("AAD digest does not bind source, priority, and destination")
        result = cls(
            source_bundle_sha256=source_bundle_sha256,
            ciphertext_sha256=ciphertext_sha,
            ciphertext_path=path,
            byte_count=byte_count,
            priority=priority,
            destination=destination,
            algorithm=algorithm,
            nonce_hex=nonce_hex,
            wrapped_key_id=wrapped_key_id,
            aad_sha256=aad_sha256,
        )
        if aead_verifier is None:
            raise ValueError("trusted AEAD verifier is required")
        if aead_verifier(path, nonce_hex, wrapped_key_id, aad, algorithm) is not True:
            raise ValueError("AES-GCM provider did not verify tag and canonical AAD")
        object.__setattr__(result, "_aead_verified", True)
        return result

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.source_bundle_sha256):
            raise ValueError("source_bundle_sha256 is invalid")
        if not _SHA256.fullmatch(self.ciphertext_sha256):
            raise ValueError("ciphertext_sha256 is invalid")
        if self.ciphertext_sha256 == self.source_bundle_sha256:
            raise ValueError("ciphertext must not be byte-identical to the plaintext bundle")
        if self.algorithm != "AES-256-GCM":
            raise ValueError("only AES-256-GCM envelopes are accepted")
        if not _NONCE.fullmatch(self.nonce_hex):
            raise ValueError("AES-GCM nonce must be 12 bytes encoded as lowercase hex")
        if not _IDENTIFIER.fullmatch(self.wrapped_key_id):
            raise ValueError("wrapped_key_id is invalid")
        transfer_aad_bytes(self.source_bundle_sha256, self.priority, self.destination)
        if not _SHA256.fullmatch(self.aad_sha256):
            raise ValueError("aad_sha256 is invalid")
        path = self.ciphertext_path.resolve()
        byte_count, digest = _ciphertext_fingerprint(path)
        if byte_count != self.byte_count or digest != self.ciphertext_sha256:
            raise ValueError("ciphertext metadata does not match file bytes")

    @property
    def aead_verified(self) -> bool:
        return self._aead_verified


@dataclass(frozen=True, slots=True)
class RemoteReceiptV1:
    receipt_id: str
    transfer_attempt_id: str
    source_bundle_sha256: str
    ciphertext_sha256: str
    destination: str
    remote_checksum_sha256: str
    received_at: str
    provider_receipt_id: str
    signature: str

    def __post_init__(self) -> None:
        for name in ("receipt_id", "transfer_attempt_id", "destination", "provider_receipt_id"):
            if not _IDENTIFIER.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} is invalid")
        for name in (
            "source_bundle_sha256",
            "ciphertext_sha256",
            "remote_checksum_sha256",
        ):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} is invalid")
        if self.remote_checksum_sha256 != self.ciphertext_sha256:
            raise ValueError("remote checksum must equal the authenticated ciphertext checksum")
        parsed = datetime.fromisoformat(self.received_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("received_at must include a timezone")
        if not _SIGNATURE.fullmatch(self.signature):
            raise ValueError("signature is invalid")

    def signed_payload(self) -> bytes:
        return canonical_json_bytes(
            {
                "ciphertext_sha256": self.ciphertext_sha256,
                "destination": self.destination,
                "provider_receipt_id": self.provider_receipt_id,
                "receipt_id": self.receipt_id,
                "received_at": self.received_at,
                "remote_checksum_sha256": self.remote_checksum_sha256,
                "schema": RECEIPT_SCHEMA,
                "source_bundle_sha256": self.source_bundle_sha256,
                "transfer_attempt_id": self.transfer_attempt_id,
            }
        )


@dataclass(frozen=True, slots=True)
class TrustedReceiptVerifierV1:
    """Frozen trusted verifier whose identity cannot be supplied separately."""

    verifier_id: str
    verifier: ReceiptVerifier = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.verifier_id):
            raise ValueError("verifier_id is invalid")
        if not callable(self.verifier):
            raise TypeError("verifier must be callable")

    def verify(self, payload: bytes, signature: str) -> bool:
        return self.verifier(payload, signature) is True


@dataclass(frozen=True, slots=True)
class TransferDecision:
    allowed: bool
    reason: str
    bucket: str
    charged_bytes: int
    day_used_bytes: int
    month_used_bytes: int
    already_accounted: bool = False


class ByteGovernor:
    """Persist and charge every distinct authorized wire attempt."""

    def __init__(
        self,
        spool: ResearchSpool,
        *,
        daily_ordinary_bytes: int = 50 * 1024 * 1024,
        monthly_ordinary_bytes: int = 5_000_000_000,
        daily_control_bytes: int = 1 * 1024 * 1024,
        monthly_control_bytes: int = 30 * 1024 * 1024,
    ) -> None:
        caps = (daily_ordinary_bytes, monthly_ordinary_bytes, daily_control_bytes, monthly_control_bytes)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in caps
        ):
            raise ValueError("byte caps must be positive integers")
        self.spool = spool
        self.daily_ordinary_bytes = int(daily_ordinary_bytes)
        self.monthly_ordinary_bytes = int(monthly_ordinary_bytes)
        self.daily_control_bytes = int(daily_control_bytes)
        self.monthly_control_bytes = int(monthly_control_bytes)

    def charge(
        self,
        encrypted: EncryptedObjectV1,
        *,
        transfer_attempt_id: str,
        now: datetime | None = None,
    ) -> TransferDecision:
        if not _IDENTIFIER.fullmatch(transfer_attempt_id):
            raise ValueError("transfer_attempt_id is invalid")
        if not encrypted.aead_verified:
            return TransferDecision(False, "aead_not_verified", "none", 0, 0, 0)
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            self.spool.purge_expired(now=current)
            artifact = self.spool.validate_bundle_for_transfer(
                encrypted.source_bundle_sha256, now=current
            )
        except (TypeError, ValueError) as exc:
            return TransferDecision(False, str(exc), "none", 0, 0, 0)
        if artifact.priority != encrypted.priority:
            return TransferDecision(False, "priority_mismatch", "none", 0, 0, 0)
        if encrypted.destination != self.spool.destination:
            return TransferDecision(False, "destination_mismatch", "none", 0, 0, 0)
        expected_aad = sha256_hex(
            transfer_aad_bytes(artifact.bundle_sha256, artifact.priority, self.spool.destination)
        )
        if encrypted.aad_sha256 != expected_aad:
            return TransferDecision(False, "aad_binding_mismatch", "none", 0, 0, 0)
        try:
            managed = self.spool.managed_encrypted_path(encrypted.ciphertext_path)
        except ValueError:
            return TransferDecision(False, "ciphertext_outside_managed_root", "none", 0, 0, 0)
        if managed != encrypted.ciphertext_path.resolve():
            return TransferDecision(False, "ciphertext_path_mismatch", "none", 0, 0, 0)
        try:
            encrypted.__post_init__()
        except ValueError:
            return TransferDecision(False, "ciphertext_changed", "none", 0, 0, 0)
        bucket = "control" if encrypted.priority == 0 else "ordinary"
        day_key, month_key = current.date().isoformat(), current.strftime("%Y-%m")
        connection, lock = self.spool.connection_for_governor, self.spool.lock_for_governor
        with lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                decision = self._charge_locked(
                    connection, encrypted, transfer_attempt_id, bucket, day_key, month_key, current
                )
                if decision.allowed:
                    connection.commit()
                else:
                    connection.rollback()
                return decision
            except sqlite3.Error:
                if connection.in_transaction:
                    connection.rollback()
                return TransferDecision(False, "accounting_unavailable", bucket, 0, 0, 0)

    def _charge_locked(
        self,
        connection: sqlite3.Connection,
        encrypted: EncryptedObjectV1,
        attempt_id: str,
        bucket: str,
        day_key: str,
        month_key: str,
        current: datetime,
    ) -> TransferDecision:
        source_rejection = self._source_rejection(connection, encrypted)
        if source_rejection is not None:
            return TransferDecision(False, source_rejection, bucket, 0, 0, 0)
        mapping = (
            encrypted.source_bundle_sha256,
            encrypted.ciphertext_sha256,
            str(encrypted.ciphertext_path.relative_to(self.spool.encrypted_root)),
            encrypted.byte_count,
            encrypted.priority,
            encrypted.destination,
            encrypted.algorithm,
            encrypted.nonce_hex,
            encrypted.wrapped_key_id,
            encrypted.aad_sha256,
        )
        existing_source = connection.execute(
            """SELECT source_bundle_sha256, ciphertext_sha256, ciphertext_path, byte_count,
                      priority, destination, algorithm, nonce_hex, wrapped_key_id, aad_sha256
               FROM encrypted_objects WHERE source_bundle_sha256 = ?""",
            (encrypted.source_bundle_sha256,),
        ).fetchone()
        if existing_source is not None and tuple(existing_source) != mapping:
            return TransferDecision(False, "source_ciphertext_metadata_collision", bucket, 0, 0, 0)
        other_source = connection.execute(
            "SELECT source_bundle_sha256 FROM encrypted_objects WHERE ciphertext_sha256 = ?",
            (encrypted.ciphertext_sha256,),
        ).fetchone()
        if other_source is None:
            other_source = connection.execute(
                """SELECT source_bundle_sha256 FROM deletion_obligations
                   WHERE ciphertext_sha256 = ? LIMIT 1""",
                (encrypted.ciphertext_sha256,),
            ).fetchone()
        if other_source is not None and other_source[0] != encrypted.source_bundle_sha256:
            return TransferDecision(False, "cross_source_ciphertext_reuse", bucket, 0, 0, 0)
        existing_attempt = connection.execute(
            """SELECT source_bundle_sha256, ciphertext_sha256, destination, byte_count, priority
               FROM transfer_attempts WHERE transfer_attempt_id = ?""",
            (attempt_id,),
        ).fetchone()
        attempt_metadata = (
            encrypted.source_bundle_sha256,
            encrypted.ciphertext_sha256,
            encrypted.destination,
            encrypted.byte_count,
            encrypted.priority,
        )
        day_used, month_used = self._usage(connection, bucket, day_key, month_key)
        if existing_attempt is not None:
            if tuple(existing_attempt) != attempt_metadata:
                return TransferDecision(
                    False, "transfer_attempt_id_collision", bucket, 0, day_used, month_used
                )
            return TransferDecision(True, "already_accounted", bucket, 0, day_used, month_used, True)
        daily_cap = self.daily_control_bytes if bucket == "control" else self.daily_ordinary_bytes
        monthly_cap = self.monthly_control_bytes if bucket == "control" else self.monthly_ordinary_bytes
        if day_used + encrypted.byte_count > daily_cap:
            return TransferDecision(False, "daily_cap", bucket, 0, day_used, month_used)
        if month_used + encrypted.byte_count > monthly_cap:
            return TransferDecision(False, "monthly_cap", bucket, 0, day_used, month_used)
        if existing_source is None:
            connection.execute(
                """INSERT INTO encrypted_objects(
                       source_bundle_sha256, ciphertext_sha256, ciphertext_path, byte_count,
                       priority, destination, algorithm, nonce_hex, wrapped_key_id,
                       aad_sha256, registered_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*mapping, current.isoformat()),
            )
        connection.execute(
            """INSERT INTO transfer_attempts(
                   transfer_attempt_id, source_bundle_sha256, ciphertext_sha256,
                   destination, byte_count, priority, attempted_at, day_key, month_key, bucket
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (attempt_id, *attempt_metadata, current.isoformat(), day_key, month_key, bucket),
        )
        connection.execute(
            "UPDATE bundles SET state = 'charged' WHERE bundle_sha256 = ?",
            (encrypted.source_bundle_sha256,),
        )
        return TransferDecision(
            True,
            "charged",
            bucket,
            encrypted.byte_count,
            day_used + encrypted.byte_count,
            month_used + encrypted.byte_count,
        )

    @staticmethod
    def _source_rejection(
        connection: sqlite3.Connection,
        encrypted: EncryptedObjectV1,
    ) -> str | None:
        source = connection.execute(
            "SELECT priority, state, invalidated FROM bundles WHERE bundle_sha256 = ?",
            (encrypted.source_bundle_sha256,),
        ).fetchone()
        if source is None:
            return "unknown_source_bundle"
        if source[0] != encrypted.priority:
            return "priority_mismatch"
        if source[1] not in {"local", "charged"} or source[2] != 0:
            return "source_not_uploadable"
        return None

    @staticmethod
    def _usage(
        connection: sqlite3.Connection, bucket: str, day_key: str, month_key: str
    ) -> tuple[int, int]:
        day = connection.execute(
            "SELECT COALESCE(SUM(byte_count), 0) FROM transfer_attempts WHERE bucket = ? AND day_key = ?",
            (bucket, day_key),
        ).fetchone()[0]
        month = connection.execute(
            "SELECT COALESCE(SUM(byte_count), 0) FROM transfer_attempts WHERE bucket = ? AND month_key = ?",
            (bucket, month_key),
        ).fetchone()[0]
        return int(day), int(month)


def mark_remote_receipt(
    spool: ResearchSpool,
    receipt: RemoteReceiptV1,
    *,
    verifier_provider: TrustedReceiptVerifierV1 | None = None,
    now: datetime | None = None,
) -> bool:
    """Verify and persist a receipt before transitioning a bundle to synced."""

    if not isinstance(verifier_provider, TrustedReceiptVerifierV1):
        raise TypeError("trusted remote receipt verifier provider is required")
    if not verifier_provider.verify(receipt.signed_payload(), receipt.signature):
        raise ValueError("remote receipt authenticity verification failed")
    current_input = now or datetime.now(timezone.utc)
    if current_input.tzinfo is None:
        raise ValueError("receipt verification clock must include a timezone")
    current = current_input.astimezone(timezone.utc)
    digest = sha256_hex(
        canonical_json_bytes(
            {
                "payload_sha256": sha256_hex(receipt.signed_payload()),
                "receipt_verifier_id": verifier_provider.verifier_id,
                "signature": receipt.signature,
            }
        )
    )
    return _persist_remote_receipt(
        spool,
        receipt,
        receipt_verifier_id=verifier_provider.verifier_id,
        digest=digest,
        now=current,
    )


def _persist_remote_receipt(
    spool: ResearchSpool,
    receipt: RemoteReceiptV1,
    *,
    receipt_verifier_id: str,
    digest: str,
    now: datetime,
) -> bool:
    connection, lock = spool.connection_for_governor, spool.lock_for_governor
    with lock:
        connection.execute("BEGIN IMMEDIATE")
        try:
            # Provider verification occurs without a DB lock; all mutable
            # retention and source state is then revalidated in this exact
            # transaction before either idempotence or a synced transition.
            spool.validate_bundle_for_transfer(
                receipt.source_bundle_sha256,
                now=now,
                allow_synced=True,
            )
            mapping = connection.execute(
                """SELECT ciphertext_sha256, destination FROM encrypted_objects
                   WHERE source_bundle_sha256 = ?""",
                (receipt.source_bundle_sha256,),
            ).fetchone()
            if mapping != (receipt.ciphertext_sha256, receipt.destination):
                raise ValueError("receipt does not bind the registered encrypted object")
            attempt = connection.execute(
                """SELECT source_bundle_sha256, ciphertext_sha256, destination,
                          attempted_at
                   FROM transfer_attempts WHERE transfer_attempt_id = ?""",
                (receipt.transfer_attempt_id,),
            ).fetchone()
            if attempt is None or tuple(attempt[:3]) != (
                receipt.source_bundle_sha256,
                receipt.ciphertext_sha256,
                receipt.destination,
            ):
                raise ValueError("receipt does not bind an accounted transfer attempt")
            received = datetime.fromisoformat(receipt.received_at.replace("Z", "+00:00"))
            attempted = datetime.fromisoformat(str(attempt[3]).replace("Z", "+00:00"))
            if received < attempted:
                raise ValueError("receipt predates its accounted transfer attempt")
            if received > now + timedelta(minutes=5):
                raise ValueError("receipt exceeds bounded future clock skew")
            prior = connection.execute(
                "SELECT receipt_sha256 FROM remote_receipts WHERE receipt_id = ?",
                (receipt.receipt_id,),
            ).fetchone()
            if prior is not None:
                if prior[0] != digest:
                    raise ValueError("receipt_id collision")
                connection.rollback()
                return False
            connection.execute(
                """INSERT INTO remote_receipts(
                       receipt_id, transfer_attempt_id, source_bundle_sha256,
                       ciphertext_sha256, destination, remote_checksum_sha256,
                       received_at, provider_receipt_id, signature,
                       receipt_verifier_id, receipt_sha256
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    receipt.receipt_id,
                    receipt.transfer_attempt_id,
                    receipt.source_bundle_sha256,
                    receipt.ciphertext_sha256,
                    receipt.destination,
                    receipt.remote_checksum_sha256,
                    receipt.received_at,
                    receipt.provider_receipt_id,
                    receipt.signature,
                    receipt_verifier_id,
                    digest,
                ),
            )
            updated = connection.execute(
                """UPDATE bundles SET state = 'synced'
                   WHERE bundle_sha256 = ? AND state = 'charged' AND invalidated = 0""",
                (receipt.source_bundle_sha256,),
            ).rowcount
            if updated != 1:
                raise ValueError("bundle is not charged or is invalidated")
            connection.execute(
                """UPDATE events SET state = 'synced' WHERE event_id IN (
                       SELECT event_id FROM bundle_events WHERE bundle_sha256 = ?
                   )""",
                (receipt.source_bundle_sha256,),
            )
            connection.commit()
            return True
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
