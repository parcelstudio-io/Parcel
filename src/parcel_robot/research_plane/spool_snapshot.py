"""Leaf-level bounded research spool diagnostics."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


def spool_snapshot(
    connection: sqlite3.Connection,
    lock: threading.RLock,
    *,
    schema_version: int,
    database_path: Path,
    max_payload_bytes: int,
    destination: str,
) -> dict[str, object]:
    with lock:
        states = dict(connection.execute("SELECT state, COUNT(*) FROM events GROUP BY state"))
        payload_bytes = int(
            connection.execute(
                "SELECT COALESCE(SUM(LENGTH(event_json)), 0) FROM events"
            ).fetchone()[0]
        )
        invalidated = int(
            connection.execute("SELECT COUNT(*) FROM bundles WHERE invalidated = 1").fetchone()[0]
        )
        obligations = int(
            connection.execute(
                "SELECT COUNT(*) FROM deletion_obligations WHERE state = 'pending'"
            ).fetchone()[0]
        )
        local_deletions = int(
            connection.execute("SELECT COUNT(*) FROM local_deletion_journal").fetchone()[0]
        )
    disk_bytes = sum(
        path.stat().st_size
        for path in (database_path, Path(f"{database_path}-wal"))
        if path.exists()
    )
    return {
        "schema_version": schema_version,
        "database_path": str(database_path),
        "event_states": states,
        "payload_bytes": payload_bytes,
        "max_payload_bytes": max_payload_bytes,
        "sqlite_disk_bytes": disk_bytes,
        "invalidated_bundles": invalidated,
        "pending_remote_deletion_obligations": obligations,
        "pending_local_deletions": local_deletions,
        "destination": destination,
    }
