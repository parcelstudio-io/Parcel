"""Bounded startup rollback and orphan reconciliation for bundle publication."""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
from datetime import datetime, timedelta, timezone
from itertools import islice
from pathlib import Path

PUBLICATION_LEASE = timedelta(minutes=15)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("publication clock must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def record_publication_intent(
    connection: sqlite3.Connection,
    lock: threading.RLock,
    bundle_root: Path,
    *,
    claim_token: str,
    owner_token: str,
    bundle_sha256: str,
    paths: tuple[Path, Path, Path, Path],
    now: datetime | None = None,
) -> None:
    root = bundle_root.resolve()
    names: list[str] = []
    for path in paths:
        resolved = path.resolve()
        if resolved.parent != root or len(resolved.name) > 255:
            raise ValueError("publication artifacts must be direct bundle-root children")
        names.append(resolved.name)
    created_input = now or datetime.now(timezone.utc)
    _utc_text(created_input)
    created = created_input.astimezone(timezone.utc)
    with lock:
        connection.execute("BEGIN IMMEDIATE")
        try:
            count = connection.execute(
                """SELECT COUNT(*) FROM events
                   WHERE state = 'claimed' AND claim_token = ?""",
                (claim_token,),
            ).fetchone()[0]
            if count <= 0:
                raise ValueError("publication intent requires a live event claim")
            connection.execute(
                """INSERT INTO bundle_publication_intents(
                       claim_token, owner_token, bundle_sha256, bundle_path,
                       manifest_path, bundle_stage_path, manifest_stage_path,
                       created_at, lease_expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    claim_token,
                    owner_token,
                    bundle_sha256,
                    *names,
                    _utc_text(created),
                    _utc_text(created + PUBLICATION_LEASE),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def abandon_publication_intent(
    connection: sqlite3.Connection,
    lock: threading.RLock,
    *,
    claim_token: str,
    owner_token: str,
) -> bool:
    """Rollback only the caller's own failed publication claim."""

    with lock:
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT owner_token FROM bundle_publication_intents WHERE claim_token = ?",
                (claim_token,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            if row[0] != owner_token:
                raise ValueError("publication intent is owned by another process")
            connection.execute(
                """UPDATE events SET state = 'queued', claim_token = NULL, claimed_at = NULL
                   WHERE state = 'claimed' AND claim_token = ?""",
                (claim_token,),
            )
            connection.execute(
                "DELETE FROM bundle_publication_intents WHERE claim_token = ?",
                (claim_token,),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise


def _unlink_direct(directory_fd: int, name: str) -> bool:
    if not name or len(name) > 255 or "/" in name or name in {".", ".."}:
        return False
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    if not stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        return False
    os.unlink(name, dir_fd=directory_fd)
    os.fsync(directory_fd)
    return True


def reconcile_bundle_artifacts(
    connection: sqlite3.Connection,
    lock: threading.RLock,
    bundle_root: Path,
    *,
    max_entries: int = 4096,
    now: datetime | None = None,
) -> int:
    """Expire abandoned leases and remove orphans under the same DB write lock."""

    if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries <= 0:
        raise ValueError("max_entries must be a positive integer")
    current = now or datetime.now(timezone.utc)
    removed = 0
    with lock:
        connection.execute("BEGIN IMMEDIATE")
        try:
            intents = connection.execute(
                """SELECT claim_token FROM bundle_publication_intents
                   WHERE lease_expires_at <= ?
                   ORDER BY lease_expires_at, claim_token LIMIT ?""",
                (_utc_text(current), max_entries),
            ).fetchall()
            for (claim_token,) in intents:
                connection.execute(
                    """UPDATE events SET state = 'queued', claim_token = NULL,
                              claimed_at = NULL
                       WHERE state = 'claimed' AND claim_token = ?""",
                    (claim_token,),
                )
                connection.execute(
                    "DELETE FROM bundle_publication_intents WHERE claim_token = ?",
                    (claim_token,),
                )
            tracked = {
                str(value)
                for row in connection.execute("SELECT path, manifest_path FROM bundles")
                for value in row
            }
            tracked.update(
                str(value)
                for row in connection.execute(
                    """SELECT bundle_path, manifest_path, bundle_stage_path,
                              manifest_stage_path FROM bundle_publication_intents"""
                )
                for value in row
            )
            directory_fd = os.open(bundle_root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for child in islice(bundle_root.iterdir(), max_entries):
                    if child.name not in tracked and _unlink_direct(directory_fd, child.name):
                        removed += 1
            finally:
                os.close(directory_fd)
            connection.commit()
            return removed
        except Exception:
            connection.rollback()
            raise
