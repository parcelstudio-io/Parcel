from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

#: Columns added for the Realtime lane's both-sides turn ledger (card R1).
#: Every one is NULLABLE with no default, so the ALTER TABLE below is purely
#: additive: rows written before this card keep reading exactly as they did,
#: and ``recent()`` — the only pre-existing reader, consumed at agent.py:498 —
#: still selects just ``role, content``.
REALTIME_COLUMNS: tuple[tuple[str, str], ...] = (
    ("session_id", "TEXT"),
    ("speaker", "TEXT"),
    ("origin", "TEXT"),
    ("provider_item_id", "TEXT"),
)

#: Who said it → the role the existing schema already understands. The lane
#: needs the distinction (a hosted reply is not a local one), but inventing a
#: new ``role`` value would break ``add()``'s Python-side whitelist and every
#: consumer that switches on role.
_SPEAKER_ROLES = {"owner": "user", "robot": "assistant", "system": "tool"}


class ConversationMemory:
    """Small local audit/conversation store; no raw audio is retained."""

    def __init__(self, path: str | Path = ":memory:"):
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS messages "
                "(id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            self._migrate_realtime_columns()

    def _migrate_realtime_columns(self) -> None:
        """Add the annotation columns to an EXISTING database, once.

        Guarded by ``PRAGMA table_info`` rather than a version counter: the live
        ``parcel_memory.sqlite3`` predates any schema versioning and contains
        only the ``messages`` table, so the table's own shape is the only honest
        source of truth about what has already been applied.
        """

        existing = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        for column, sql_type in REALTIME_COLUMNS:
            if column in existing:
                continue
            self.connection.execute(f"ALTER TABLE messages ADD COLUMN {column} {sql_type}")
        self.connection.commit()

    def add(self, role: str, content: str) -> None:
        if role not in {"user", "assistant", "tool"}:
            raise ValueError(f"unsupported memory role: {role}")
        with self._lock:
            self.connection.execute(
                "INSERT INTO messages(role, content) VALUES (?, ?)", (role, content)
            )
            self.connection.commit()

    def recent(self, limit: int = 8) -> list[dict[str, str]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def write_realtime_turn(
        self,
        *,
        session_id: str | None,
        speaker: str,
        text: str,
        origin: str,
        provider_item_id: str | None = None,
    ) -> int:
        """Write ONE side of a hosted turn, annotated with its provenance.

        The Realtime lane's dedicated writer. FIX-A/F3's transcript fields cover
        only the owner side of a LOCAL voice turn and obey the duplex-logging
        kill switch; hosted replies never create those turns at all. This is the
        conversation ledger — the product's memory — and it is deliberately not
        behind the diagnostics switch.

        Returns the new row id so a caller can correlate without re-querying.
        """

        role = _SPEAKER_ROLES.get(speaker)
        if role is None:
            raise ValueError(f"unsupported realtime speaker: {speaker!r}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("realtime turn text must be non-empty")
        with self._lock:
            cursor = self.connection.execute(
                "INSERT INTO messages(role, content, session_id, speaker, origin, "
                "provider_item_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    role,
                    text,
                    None if session_id is None else str(session_id),
                    speaker,
                    str(origin),
                    None if provider_item_id is None else str(provider_item_id),
                ),
            )
            self.connection.commit()
            return int(cursor.lastrowid or 0)

    def realtime_turns(
        self,
        *,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Oldest-first tail of hosted turns, for memory injection at reconnect.

        Only rows this writer produced (``speaker IS NOT NULL``) are returned,
        so a local typed turn can never be replayed to the provider as if the
        hosted agent had said it.
        """

        query = (
            "SELECT id, role, content, session_id, speaker, origin, provider_item_id "
            "FROM messages WHERE speaker IS NOT NULL"
        )
        params: list[object] = []
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self.connection.execute(query, tuple(params)).fetchall()
        return [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "session_id": row[3],
                "speaker": row[4],
                "origin": row[5],
                "provider_item_id": row[6],
            }
            for row in reversed(rows)
        ]
