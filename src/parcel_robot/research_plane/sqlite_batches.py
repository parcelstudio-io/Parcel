"""Bounded temporary-table helpers for SQLite set operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

_TABLES = frozenset({"purge_requested_ids", "purge_delete_ids", "purge_survivor_ids"})


def replace_temp_ids(
    connection: sqlite3.Connection,
    table: str,
    values: Iterable[str],
) -> None:
    if table not in _TABLES:
        raise ValueError("temporary ID table is not allowed")
    connection.execute(f"CREATE TEMP TABLE IF NOT EXISTS {table}(event_id TEXT PRIMARY KEY)")
    connection.execute(f"DELETE FROM {table}")
    batch: list[tuple[str]] = []
    for value in values:
        batch.append((value,))
        if len(batch) == 500:
            connection.executemany(f"INSERT INTO {table}(event_id) VALUES (?)", batch)
            batch.clear()
    if batch:
        connection.executemany(f"INSERT INTO {table}(event_id) VALUES (?)", batch)
