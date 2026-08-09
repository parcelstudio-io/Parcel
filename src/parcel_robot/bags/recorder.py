"""Sim-bag recorder: append agent-safe sensor-shaped messages to a bag directory."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from parcel_robot.bags.schema import (
    MANIFEST_FILENAME,
    MESSAGES_FILENAME,
    BagSchemaError,
    make_envelope,
    make_manifest,
    reject_privileged_fields,
    validate_message,
    validate_manifest,
)


class BagRecorder:
    """Write a versioned bag directory (manifest.json + messages.jsonl)."""

    def __init__(
        self,
        bag_dir: Path | str,
        *,
        bag_id: str,
        source: str = "sim",
        topics: list[str] | None = None,
        clocks: Mapping[str, Any] | None = None,
        frames: Mapping[str, Any] | None = None,
        does_not_prove: list[str] | None = None,
    ) -> None:
        self._bag_dir = Path(bag_dir)
        self._bag_dir.mkdir(parents=True, exist_ok=True)
        messages_path = self._bag_dir / MESSAGES_FILENAME
        if messages_path.exists() and messages_path.stat().st_size > 0:
            raise BagSchemaError(f"refusing to append to existing bag: {self._bag_dir}")
        self._manifest = make_manifest(
            bag_id=bag_id,
            created_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            source=source,
            clocks=clocks,
            frames=frames,
            topics=topics,
            does_not_prove=does_not_prove,
            message_count=0,
        )
        self._sequence = 0
        self._closed = False
        self._messages_path = messages_path
        self._messages_path.write_text("", encoding="utf-8")
        self._write_manifest()

    @property
    def bag_dir(self) -> Path:
        return self._bag_dir

    @property
    def message_count(self) -> int:
        return int(self._manifest["message_count"])

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    def record(
        self,
        topic: str,
        payload: Mapping[str, Any],
        *,
        source: str,
        source_timestamp_ns: int,
        received_monotonic_ns: int,
        frame_id: str,
        evidence_id: str | None = None,
        calibration_id: str = "sim-uncalibrated",
        expires_monotonic_ns: int | None = None,
        scene_revision: int = 0,
        provenance: list[str] | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise BagSchemaError("recorder is closed")
        if topic not in self._manifest["topics"]:
            raise BagSchemaError(
                f"topic {topic!r} not declared in manifest topics "
                f"{self._manifest['topics']}"
            )
        reject_privileged_fields(payload, path="payload")
        envelope = make_envelope(
            evidence_id=evidence_id or f"{self._manifest['bag_id']}-{self._sequence}",
            source=source,
            source_timestamp_ns=source_timestamp_ns,
            received_monotonic_ns=received_monotonic_ns,
            sequence=self._sequence,
            frame_id=frame_id,
            calibration_id=calibration_id,
            expires_monotonic_ns=expires_monotonic_ns,
            scene_revision=scene_revision,
            provenance=provenance,
        )
        message = {
            "topic": topic,
            "envelope": envelope,
            "payload": dict(payload),
        }
        validate_message(message)
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._messages_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        self._sequence += 1
        self._manifest["message_count"] = self._sequence
        self._write_manifest()
        return message

    def close(self) -> dict[str, Any]:
        if self._closed:
            return self.manifest
        validate_manifest(self._manifest)
        self._write_manifest()
        self._closed = True
        return self.manifest

    def _write_manifest(self) -> None:
        path = self._bag_dir / MANIFEST_FILENAME
        path.write_text(
            json.dumps(self._manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
