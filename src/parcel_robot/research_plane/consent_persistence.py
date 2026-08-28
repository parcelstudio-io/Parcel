"""Re-bind persisted consent rows to their authenticated canonical digest."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .consent import (
    AuthenticatedConsentV1,
    ConsentRecordV1,
    TrustedConsentVerifierV1,
)
from .contracts import canonical_json_bytes, sha256_hex


@dataclass(frozen=True, slots=True)
class VerifiedPersistedConsentV1:
    record: ConsentRecordV1
    revoked_at: str | None


def load_verified_consent(
    connection: sqlite3.Connection,
    consent_id: str | None,
    *,
    verifier_provider: TrustedConsentVerifierV1 | None,
) -> VerifiedPersistedConsentV1 | None:
    if consent_id is None:
        return None
    row = connection.execute(
        """SELECT consent_id, subject_pseudonym, streams_json, destination,
                  purpose, granted_at, expires_at, authority, authentication_channel,
                  authenticator_id, consent_proof, proof_sha256, consent_verifier_id,
                  record_sha256, revoked_at
           FROM consents WHERE consent_id = ?""",
        (consent_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        streams = json.loads(bytes(row[2]))
        if not isinstance(streams, list) or canonical_json_bytes(streams) != bytes(row[2]):
            raise ValueError("persisted consent streams are not canonical")
        record = ConsentRecordV1(
            consent_id=str(row[0]),
            subject_pseudonym=str(row[1]),
            streams=tuple(streams),
            destination=str(row[3]),
            purpose=str(row[4]),
            granted_at=str(row[5]),
            expires_at=str(row[6]),
            authority=str(row[7]),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("persisted consent authentication binding is invalid") from exc
    canonical = record.canonical_bytes()
    proof = str(row[10])
    if (
        sha256_hex(canonical) != row[13]
        or sha256_hex(proof.encode("utf-8")) != row[11]
        or row[8] != record.authority
        or not isinstance(verifier_provider, TrustedConsentVerifierV1)
        or verifier_provider.verifier_id != row[12]
        or not verifier_provider.verify(canonical, proof, str(row[9]), str(row[8]))
    ):
        raise ValueError("persisted consent authentication binding is invalid")
    return VerifiedPersistedConsentV1(
        record,
        str(row[14]) if row[14] is not None else None,
    )


def persist_authenticated_consent(
    connection: sqlite3.Connection,
    authenticated: AuthenticatedConsentV1,
    *,
    destination: str,
    verifier_provider: TrustedConsentVerifierV1 | None,
) -> bool:
    """Persist an exact proof that can be re-verified on every later read."""

    if not isinstance(authenticated, AuthenticatedConsentV1) or not authenticated.authenticated:
        raise TypeError("an authenticated consent wrapper is required")
    if not isinstance(verifier_provider, TrustedConsentVerifierV1):
        raise TypeError("trusted persisted consent verifier is required")
    if authenticated.verifier_id != verifier_provider.verifier_id:
        raise ValueError("authenticated consent verifier does not match the spool verifier")
    record = authenticated.verified_record()
    if record.destination != destination:
        raise ValueError("consent destination does not match this research spool")
    if not verifier_provider.verify(
        authenticated.canonical_record,
        authenticated.proof,
        authenticated.authenticator_id,
        authenticated.channel,
    ):
        raise ValueError("consent authentication failed")
    proof_sha256 = sha256_hex(authenticated.proof.encode("utf-8"))
    existing = connection.execute(
        """SELECT record_sha256, authentication_channel, authenticator_id,
                  consent_proof, proof_sha256, consent_verifier_id
           FROM consents WHERE consent_id = ?""",
        (record.consent_id,),
    ).fetchone()
    if existing is not None:
        load_verified_consent(
            connection,
            record.consent_id,
            verifier_provider=verifier_provider,
        )
        expected = (
            authenticated.record_sha256,
            authenticated.channel,
            authenticated.authenticator_id,
            authenticated.proof,
            proof_sha256,
            authenticated.verifier_id,
        )
        if tuple(existing) != expected:
            raise ValueError("consent_id already binds different authenticated data")
        return False
    connection.execute(
        """INSERT INTO consents(
               consent_id, subject_pseudonym, streams_json, destination, purpose,
               granted_at, expires_at, authority, authentication_channel,
               authenticator_id, consent_proof, proof_sha256, consent_verifier_id,
               record_sha256
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record.consent_id,
            record.subject_pseudonym,
            canonical_json_bytes(list(record.streams)),
            record.destination,
            record.purpose,
            record.granted_at,
            record.expires_at,
            record.authority,
            authenticated.channel,
            authenticated.authenticator_id,
            authenticated.proof,
            proof_sha256,
            authenticated.verifier_id,
            authenticated.record_sha256,
        ),
    )
    return True


def persisted_consent_rejection(
    connection: sqlite3.Connection,
    *,
    consent_id: str | None,
    stream: str,
    robot_pseudonym: str,
    occurred: datetime,
    now: datetime,
    destination: str,
    verifier_provider: TrustedConsentVerifierV1 | None,
) -> str | None:
    try:
        verified = load_verified_consent(
            connection,
            consent_id,
            verifier_provider=verifier_provider,
        )
    except ValueError:
        return "consent_record_binding_invalid"
    if verified is None:
        return "unknown_consent"
    record = verified.record
    granted = datetime.fromisoformat(record.granted_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(record.expires_at.replace("Z", "+00:00"))
    if stream not in record.streams:
        return "consent_scope_mismatch"
    if record.subject_pseudonym != robot_pseudonym:
        return "consent_subject_mismatch"
    if record.destination != destination:
        return "consent_destination_mismatch"
    if verified.revoked_at is not None:
        return "consent_revoked"
    if occurred < granted or occurred >= expires:
        return "consent_not_valid_at_event"
    if now >= expires:
        return "consent_expired"
    return None
