"""Leaf-level transactional source-bundle validation for wire transfer."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .bundle_validation import PersistedBundleShapeV1, verify_persisted_bundle
from .consent import TrustedConsentVerifierV1
from .consent_persistence import persisted_consent_rejection


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _direct_child(root: Path, relative: object) -> Path:
    path = root / str(relative)
    resolved = path.resolve()
    if resolved.parent != root:
        raise ValueError("bundle artifact escapes managed root")
    return resolved


def validate_persisted_bundle_for_transfer(
    connection: sqlite3.Connection,
    lock: threading.RLock,
    *,
    bundle_root: Path,
    destination: str,
    bundle_sha256: str,
    current: datetime,
    allow_synced: bool,
    consent_verifier: TrustedConsentVerifierV1 | None,
) -> tuple[int, str]:
    with lock:
        row = connection.execute(
            """SELECT path, manifest_path, priority, event_count, compressed_bytes,
                      uncompressed_bytes, manifest_file_sha256,
                      manifest_content_sha256, event_id_digest, first_event_id,
                      last_event_id, lineage_sha256, state, invalidated
               FROM bundles WHERE bundle_sha256 = ?""",
            (bundle_sha256,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown_source_bundle")
        allowed_states = {"local", "charged", "synced"} if allow_synced else {"local", "charged"}
        if row[12] not in allowed_states or row[13] != 0:
            raise ValueError("source_not_uploadable")
        events = connection.execute(
            """SELECT e.event_id, e.event_sha256, e.expires_at,
                      e.privacy_class, e.consent_id, e.stream,
                      e.robot_pseudonym, e.occurred_at
               FROM bundle_events be JOIN events e ON e.event_id = be.event_id
               WHERE be.bundle_sha256 = ?""",
            (bundle_sha256,),
        ).fetchall()
        if len(events) != row[3]:
            raise ValueError("source_bundle_membership_mismatch")
        for event in events:
            expired = _parse(str(event[2])) <= current
            consent_invalid = event[3] == "consent_required" and (
                persisted_consent_rejection(
                    connection,
                    consent_id=str(event[4]) if event[4] is not None else None,
                    stream=str(event[5]),
                    robot_pseudonym=str(event[6]),
                    occurred=_parse(str(event[7])),
                    now=current,
                    destination=destination,
                    verifier_provider=consent_verifier,
                )
                is not None
            )
            if expired or consent_invalid:
                raise ValueError("source_retention_or_consent_invalid")
        event_hashes = {str(event[0]): str(event[1]) for event in events}
        bundle_path = _direct_child(bundle_root, row[0])
        manifest_path = _direct_child(bundle_root, row[1])
    if not bundle_path.is_file() or not manifest_path.is_file():
        raise ValueError("source_bundle_artifact_missing")
    shape = PersistedBundleShapeV1(
        bundle_sha256,
        int(row[2]),
        int(row[3]),
        int(row[4]),
        int(row[5]),
        str(row[6]),
        str(row[7]),
        str(row[8]),
        str(row[9]),
        str(row[10]),
        str(row[11]),
    )
    verify_persisted_bundle(
        bundle_path,
        manifest_path,
        shape,
        expected_event_hashes=event_hashes,
    )
    return int(row[2]), str(row[12])
