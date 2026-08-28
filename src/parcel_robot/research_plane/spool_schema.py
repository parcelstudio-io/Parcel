"""Leaf-level SQLite schema creation for the research spool."""

from __future__ import annotations

import sqlite3

_CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consents (
    consent_id TEXT PRIMARY KEY,
    subject_pseudonym TEXT NOT NULL,
    streams_json BLOB NOT NULL,
    destination TEXT NOT NULL,
    purpose TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    authority TEXT NOT NULL,
    authentication_channel TEXT NOT NULL,
    authenticator_id TEXT NOT NULL,
    consent_proof TEXT NOT NULL,
    proof_sha256 TEXT NOT NULL,
    consent_verifier_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    revoked_at TEXT,
    revocation_reason TEXT
);
CREATE TABLE IF NOT EXISTS tombstones (
    consent_id TEXT PRIMARY KEY,
    subject_pseudonym TEXT NOT NULL,
    purpose TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reason_code TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stream TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    robot_pseudonym TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    priority INTEGER NOT NULL,
    privacy_class TEXT NOT NULL,
    consent_id TEXT,
    retention_class TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    event_json BLOB NOT NULL,
    event_sha256 TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued'
        CHECK(state IN ('queued', 'claimed', 'bundled', 'synced')),
    claim_token TEXT,
    claimed_at TEXT,
    UNIQUE(run_id, stream, sequence)
);
CREATE INDEX IF NOT EXISTS events_queue_idx
    ON events(state, priority, occurred_at, stream, sequence, event_id);
CREATE TABLE IF NOT EXISTS bundles (
    bundle_sha256 TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    priority INTEGER NOT NULL,
    event_count INTEGER NOT NULL,
    compressed_bytes INTEGER NOT NULL,
    uncompressed_bytes INTEGER NOT NULL,
    manifest_file_sha256 TEXT NOT NULL,
    manifest_content_sha256 TEXT NOT NULL,
    event_id_digest TEXT NOT NULL,
    first_event_id TEXT NOT NULL,
    last_event_id TEXT NOT NULL,
    lineage_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'local'
        CHECK(state IN ('local', 'charged', 'synced')),
    invalidated INTEGER NOT NULL DEFAULT 0 CHECK(invalidated IN (0, 1))
);
CREATE TABLE IF NOT EXISTS bundle_events (
    bundle_sha256 TEXT NOT NULL REFERENCES bundles(bundle_sha256) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    PRIMARY KEY(bundle_sha256, event_id)
);
CREATE TABLE IF NOT EXISTS bundle_publication_intents (
    claim_token TEXT PRIMARY KEY,
    owner_token TEXT NOT NULL,
    bundle_sha256 TEXT NOT NULL,
    bundle_path TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    bundle_stage_path TEXT NOT NULL,
    manifest_stage_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL
);
"""

_TRANSFER_SCHEMA = """
CREATE TABLE IF NOT EXISTS encrypted_objects (
    source_bundle_sha256 TEXT PRIMARY KEY
        REFERENCES bundles(bundle_sha256) ON DELETE CASCADE,
    ciphertext_sha256 TEXT NOT NULL UNIQUE,
    ciphertext_path TEXT NOT NULL,
    byte_count INTEGER NOT NULL,
    priority INTEGER NOT NULL,
    destination TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    nonce_hex TEXT NOT NULL,
    wrapped_key_id TEXT NOT NULL,
    aad_sha256 TEXT NOT NULL,
    registered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transfer_attempts (
    transfer_attempt_id TEXT PRIMARY KEY,
    source_bundle_sha256 TEXT NOT NULL,
    ciphertext_sha256 TEXT NOT NULL,
    destination TEXT NOT NULL,
    byte_count INTEGER NOT NULL,
    priority INTEGER NOT NULL,
    attempted_at TEXT NOT NULL,
    day_key TEXT NOT NULL,
    month_key TEXT NOT NULL,
    bucket TEXT NOT NULL CHECK(bucket IN ('ordinary', 'control'))
);
CREATE INDEX IF NOT EXISTS transfer_attempt_usage_idx
    ON transfer_attempts(bucket, day_key, month_key);
CREATE TABLE IF NOT EXISTS remote_receipts (
    receipt_id TEXT PRIMARY KEY,
    transfer_attempt_id TEXT NOT NULL,
    source_bundle_sha256 TEXT NOT NULL,
    ciphertext_sha256 TEXT NOT NULL,
    destination TEXT NOT NULL,
    remote_checksum_sha256 TEXT NOT NULL,
    received_at TEXT NOT NULL,
    provider_receipt_id TEXT NOT NULL,
    signature TEXT NOT NULL,
    receipt_verifier_id TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deletion_obligations (
    obligation_id TEXT PRIMARY KEY,
    source_bundle_sha256 TEXT NOT NULL,
    ciphertext_sha256 TEXT NOT NULL,
    destination TEXT NOT NULL,
    remote_provider_receipt_id TEXT,
    receipt_verifier_id TEXT,
    receipt_proof_sha256 TEXT,
    receipt_record_sha256 TEXT,
    created_at TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state = 'pending')
);
CREATE TABLE IF NOT EXISTS local_deletion_journal (
    entry_id TEXT PRIMARY KEY,
    managed_kind TEXT NOT NULL CHECK(managed_kind IN ('bundle', 'encrypted')),
    relative_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    generation_id TEXT NOT NULL,
    device_id INTEGER,
    inode INTEGER,
    created_at TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    UNIQUE(managed_kind, relative_path)
);
CREATE TABLE IF NOT EXISTS purge_tombstones (
    tombstone_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    bundle_count INTEGER NOT NULL
);
"""

_EXPECTED_COLUMNS = {
    "metadata": ("key", "value"),
    "consents": (
        "consent_id", "subject_pseudonym", "streams_json", "destination", "purpose",
        "granted_at", "expires_at", "authority", "authentication_channel",
        "authenticator_id", "consent_proof", "proof_sha256", "consent_verifier_id",
        "record_sha256", "revoked_at", "revocation_reason",
    ),
    "tombstones": (
        "consent_id", "subject_pseudonym", "purpose", "created_at", "reason_code",
    ),
    "events": (
        "event_id", "run_id", "stream", "sequence", "robot_pseudonym", "occurred_at",
        "priority", "privacy_class", "consent_id", "retention_class", "expires_at",
        "event_json", "event_sha256", "state", "claim_token", "claimed_at",
    ),
    "bundles": (
        "bundle_sha256", "path", "manifest_path", "priority", "event_count",
        "compressed_bytes", "uncompressed_bytes", "manifest_file_sha256",
        "manifest_content_sha256", "event_id_digest", "first_event_id", "last_event_id",
        "lineage_sha256", "created_at", "state", "invalidated",
    ),
    "bundle_events": ("bundle_sha256", "event_id"),
    "bundle_publication_intents": (
        "claim_token", "owner_token", "bundle_sha256", "bundle_path", "manifest_path",
        "bundle_stage_path", "manifest_stage_path", "created_at", "lease_expires_at",
    ),
    "encrypted_objects": (
        "source_bundle_sha256", "ciphertext_sha256", "ciphertext_path", "byte_count",
        "priority", "destination", "algorithm", "nonce_hex", "wrapped_key_id",
        "aad_sha256", "registered_at",
    ),
    "transfer_attempts": (
        "transfer_attempt_id", "source_bundle_sha256", "ciphertext_sha256", "destination",
        "byte_count", "priority", "attempted_at", "day_key", "month_key", "bucket",
    ),
    "remote_receipts": (
        "receipt_id", "transfer_attempt_id", "source_bundle_sha256", "ciphertext_sha256",
        "destination", "remote_checksum_sha256", "received_at", "provider_receipt_id",
        "signature", "receipt_verifier_id", "receipt_sha256",
    ),
    "deletion_obligations": (
        "obligation_id", "source_bundle_sha256", "ciphertext_sha256", "destination",
        "remote_provider_receipt_id", "receipt_verifier_id", "receipt_proof_sha256",
        "receipt_record_sha256", "created_at", "reason_code", "state",
    ),
    "local_deletion_journal": (
        "entry_id", "managed_kind", "relative_path", "content_sha256", "generation_id",
        "device_id", "inode", "created_at", "reason_code", "attempt_count",
        "last_attempt_at",
    ),
    "purge_tombstones": (
        "tombstone_id", "created_at", "reason_code", "event_count", "bundle_count",
    ),
}


def _validate_schema_shape(connection: sqlite3.Connection) -> None:
    for table, expected in _EXPECTED_COLUMNS.items():
        actual = tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})"))
        if actual != expected:
            raise RuntimeError(f"research spool table shape mismatch: {table}")
    if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise RuntimeError("research spool foreign-key enforcement is disabled")
    expected_foreign_keys = {
        "bundle_events": {
            ("bundles", "bundle_sha256", "bundle_sha256"),
            ("events", "event_id", "event_id"),
        },
        "encrypted_objects": {
            ("bundles", "source_bundle_sha256", "bundle_sha256"),
        },
    }
    for table, expected in expected_foreign_keys.items():
        actual = {
            (str(row[2]), str(row[3]), str(row[4]))
            for row in connection.execute(f"PRAGMA foreign_key_list({table})")
        }
        if actual != expected:
            raise RuntimeError(f"research spool foreign-key shape mismatch: {table}")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError("research spool foreign-key check failed")


def create_spool_schema(
    connection: sqlite3.Connection,
    *,
    schema_version: int,
    destination: str,
) -> None:
    connection.executescript(_CORE_SCHEMA)
    connection.executescript(_TRANSFER_SCHEMA)
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
            (str(schema_version),),
        )
    elif row[0] != str(schema_version):
        raise RuntimeError(f"unsupported research spool schema: {row[0]}")
    stored_destination = connection.execute(
        "SELECT value FROM metadata WHERE key = 'destination'"
    ).fetchone()
    if stored_destination is None:
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES('destination', ?)",
            (destination,),
        )
    elif stored_destination[0] != destination:
        raise RuntimeError("research spool destination is immutable")
    _validate_schema_shape(connection)
    connection.commit()
