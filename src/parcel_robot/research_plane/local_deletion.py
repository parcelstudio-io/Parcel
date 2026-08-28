"""Crash-recoverable, identity-bound draining for local deletion intents."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

DeletionUnlinker = Callable[[Path], None]


def _direct_name(relative_path: str) -> str:
    if not relative_path or len(relative_path) > 255 or "/" in relative_path:
        raise ValueError("journaled deletion must name one bounded direct child")
    if relative_path in {".", ".."}:
        raise ValueError("journaled deletion path is invalid")
    return relative_path


def _open_verified(
    directory_fd: int,
    name: str,
    expected_sha256: str,
    expected_device: int | None,
    expected_inode: int | None,
) -> int | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("managed deletion target is not a regular no-follow file")
    if expected_device is not None and (metadata.st_dev, metadata.st_ino) != (
        expected_device,
        expected_inode,
    ):
        raise ValueError("managed deletion target generation changed")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    digest = hashlib.sha256()
    with os.fdopen(os.dup(descriptor), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        os.close(descriptor)
        raise ValueError("managed deletion target content identity changed")
    return descriptor


def capture_local_identity(root: Path, relative_path: str, expected_sha256: str) -> tuple[int, int]:
    name = _direct_name(relative_path)
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        descriptor = _open_verified(directory_fd, name, expected_sha256, None, None)
        if descriptor is None:
            return (0, 0)
        try:
            metadata = os.fstat(descriptor)
            return int(metadata.st_dev), int(metadata.st_ino)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_fd)


def _attempt_delete(
    root: Path,
    row: tuple[object, ...],
    unlinker: DeletionUnlinker | None,
) -> bool:
    _entry, _kind, relative, digest, _generation, device, inode = row
    name = _direct_name(str(relative))
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        if not device or not inode:
            try:
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                return True
            return False
        descriptor = _open_verified(
            directory_fd,
            name,
            str(digest),
            int(device) if device else None,
            int(inode) if inode else None,
        )
        if descriptor is not None:
            verified = os.fstat(descriptor)
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            os.close(descriptor)
            if (current.st_dev, current.st_ino) != (verified.st_dev, verified.st_ino):
                return False
            if unlinker is None:
                os.unlink(name, dir_fd=directory_fd)
            else:
                unlinker(root / name)
            os.fsync(directory_fd)
        return True
    except (OSError, ValueError):
        return False
    finally:
        os.close(directory_fd)


def drain_local_deletions(
    connection: sqlite3.Connection,
    lock: threading.RLock,
    *,
    roots: Mapping[str, Path],
    unlinker: DeletionUnlinker | None,
    max_entries: int = 256,
) -> int:
    """Scan beyond failed head rows under bounded work and drain idempotently."""

    if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries <= 0:
        raise ValueError("max_entries must be a positive integer")
    completed = 0
    scan_limit = max_entries * 4
    with lock:
        rows = connection.execute(
            """SELECT entry_id, managed_kind, relative_path, content_sha256,
                      generation_id, device_id, inode
               FROM local_deletion_journal
               ORDER BY COALESCE(last_attempt_at, ''), created_at, entry_id LIMIT ?""",
            (scan_limit,),
        ).fetchall()
        for row in rows:
            if completed >= max_entries:
                break
            root = roots.get(str(row[1]))
            if root is not None and _attempt_delete(root, tuple(row), unlinker):
                connection.execute(
                    "DELETE FROM local_deletion_journal WHERE entry_id = ?", (row[0],)
                )
                completed += 1
            else:
                connection.execute(
                    """UPDATE local_deletion_journal
                       SET attempt_count = attempt_count + 1, last_attempt_at = ?
                       WHERE entry_id = ?""",
                    (datetime.now(timezone.utc).isoformat(), row[0]),
                )
            connection.commit()
    return completed
