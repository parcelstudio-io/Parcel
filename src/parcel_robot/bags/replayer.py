"""Deterministic bag replayer for sim (and later hardware) recordings."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from parcel_robot.bags.schema import (
    MANIFEST_FILENAME,
    MESSAGES_FILENAME,
    BagSchemaError,
    validate_manifest,
    validate_message,
)


class BagReplayer:
    """Read and iterate a versioned bag directory in record order."""

    def __init__(self, bag_dir: Path | str, *, validate: bool = True) -> None:
        self._bag_dir = Path(bag_dir)
        manifest_path = self._bag_dir / MANIFEST_FILENAME
        messages_path = self._bag_dir / MESSAGES_FILENAME
        if not manifest_path.is_file():
            raise BagSchemaError(f"missing manifest: {manifest_path}")
        if not messages_path.is_file():
            raise BagSchemaError(f"missing messages: {messages_path}")
        self._manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if validate:
            validate_manifest(self._manifest)
        self._messages_path = messages_path
        self._validate = validate
        self._messages: list[dict[str, Any]] | None = None

    @property
    def bag_dir(self) -> Path:
        return self._bag_dir

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    @property
    def does_not_prove(self) -> list[str]:
        return list(self._manifest["does_not_prove"])

    def messages(self) -> list[dict[str, Any]]:
        if self._messages is None:
            self._messages = list(self.iter_messages())
        return list(self._messages)

    def iter_messages(self) -> Iterator[dict[str, Any]]:
        count = 0
        with self._messages_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise BagSchemaError(
                        f"invalid JSONL at {self._messages_path}:{line_no}: {exc}"
                    ) from exc
                if not isinstance(message, dict):
                    raise BagSchemaError(
                        f"message at line {line_no} must be an object"
                    )
                if self._validate:
                    validate_message(message)
                count += 1
                yield message
        expected = int(self._manifest["message_count"])
        if count != expected:
            raise BagSchemaError(
                f"message_count mismatch: manifest={expected} jsonl={count}"
            )

    def messages_for_topic(self, topic: str) -> list[dict[str, Any]]:
        return [message for message in self.messages() if message["topic"] == topic]

    def digest(self) -> str:
        """Stable content digest for CI determinism checks."""
        import hashlib

        hasher = hashlib.sha256()
        hasher.update(
            json.dumps(self._manifest, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        for message in self.messages():
            hasher.update(
                json.dumps(message, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
        return hasher.hexdigest()
