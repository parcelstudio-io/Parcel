"""Aligned-stream session logging for the D1 corpus (local JSONL)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class DuplexSessionLog:
    """Append-only rotating JSONL writer for duplex frames + turn outcomes.

    Privacy: transcripts stay on the local machine. Files under ``logs/duplex/``
    are gitignored and must not be committed. Kill switch: ``duplex.logging``.
    """

    def __init__(
        self,
        path: Path,
        *,
        rotate_bytes: int = 2_000_000,
        enabled: bool = True,
    ) -> None:
        self._path = Path(path)
        self._rotate_bytes = int(rotate_bytes)
        self._enabled = bool(enabled)
        self._lock = threading.Lock()
        self._bytes_written = 0
        self._records = 0
        if self._enabled:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)
            if self._enabled:
                self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        if not self._enabled:
            return
        payload = dict(record)
        payload.setdefault("wall_s", time.time())
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        data = line.encode("utf-8")
        with self._lock:
            if not self._enabled:
                return
            if self._path.exists() and self._path.stat().st_size + len(data) > self._rotate_bytes:
                rotated = self._path.with_suffix(self._path.suffix + ".1")
                if rotated.exists():
                    rotated.unlink()
                self._path.replace(rotated)
                self._bytes_written = 0
            with self._path.open("ab") as handle:
                handle.write(data)
            self._bytes_written += len(data)
            self._records += 1

    def write_frame(
        self,
        *,
        t: int,
        epoch: int,
        text: str,
        act: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "type": "frame",
            "t": int(t),
            "epoch": int(epoch),
            "text": text,
            "act": act,
        }
        if context:
            record["context"] = context
        self.write(record)

    def write_turn_outcome(self, outcome: dict[str, Any]) -> None:
        record = {"type": "turn_outcome", **outcome}
        self.write(record)

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self._enabled,
            "path": str(self._path),
            "records": self._records,
            "bytes_written": self._bytes_written,
            "rotate_bytes": self._rotate_bytes,
        }


__all__ = ["DuplexSessionLog"]
