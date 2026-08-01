from __future__ import annotations

import sqlite3
from pathlib import Path


class ConversationMemory:
    """Small local audit/conversation store; no raw audio is retained."""

    def __init__(self, path: str | Path = ":memory:"):
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS messages "
            "(id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )

    def add(self, role: str, content: str) -> None:
        if role not in {"user", "assistant", "tool"}:
            raise ValueError(f"unsupported memory role: {role}")
        self.connection.execute(
            "INSERT INTO messages(role, content) VALUES (?, ?)", (role, content)
        )
        self.connection.commit()

    def recent(self, limit: int = 8) -> list[dict[str, str]]:
        rows = self.connection.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

