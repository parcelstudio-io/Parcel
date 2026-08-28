"""Deterministic typed candidate factory for simulator/runtime producers."""

from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from .contracts import (
    DEVICE_CLOCKS,
    EVENT_TYPES,
    PRIORITY_BY_STREAM,
    ResearchProvenanceV1,
)

RETENTION_BY_STREAM = {
    "feedback": "feedback_1y",
    "conversation": "summary_90d",
    "navigation": "summary_90d",
    "audio": "summary_90d",
    "perception": "summary_90d",
}
_EVENT_NAMESPACE = uuid.UUID("e81b078e-4a0b-47fe-8d1f-2b66959b29e1")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_ROBOT_ID = re.compile(r"^robot_[0-9a-f]{16}$")


def pseudonymous_robot_id(project_secret: bytes, robot_local_id: str) -> str:
    """Derive a project-scoped pseudonym without persisting a serial number."""

    if len(project_secret) < 32:
        raise ValueError("project pseudonym secret must contain at least 32 bytes")
    if not robot_local_id or len(robot_local_id) > 256:
        raise ValueError("robot_local_id must be 1..256 characters")
    digest = hashlib.blake2b(
        robot_local_id.encode("utf-8"),
        key=project_secret,
        digest_size=8,
        person=b"parcel-rsch-v1",
    ).hexdigest()
    return f"robot_{digest}"


@dataclass(frozen=True, slots=True)
class ResearchProducerIdentityV1:
    run_id: str
    robot_pseudonym: str
    code_sha256: str
    config_sha256: str
    model_ids: tuple[str, ...] = ()
    calibration_ids: tuple[str, ...] = ()
    device_clock: str = "system"

    def __post_init__(self) -> None:
        if not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("run_id must be a bounded identifier")
        if not _ROBOT_ID.fullmatch(self.robot_pseudonym):
            raise ValueError("robot_pseudonym must be a scoped research pseudonym")
        if self.device_clock not in DEVICE_CLOCKS:
            raise ValueError("device_clock is unsupported")
        if not isinstance(self.model_ids, tuple) or not isinstance(self.calibration_ids, tuple):
            raise TypeError("model_ids and calibration_ids must be immutable tuples")
        # Reuse the event contract's digest and identifier validation now,
        # before a producer starts allocating sequence numbers.
        ResearchProvenanceV1(
            source_event_ids=(),
            code_sha256=self.code_sha256,
            config_sha256=self.config_sha256,
            model_ids=self.model_ids,
            calibration_ids=self.calibration_ids,
        )


class ResearchEventFactoryV1:
    """Mint unique ordered events from already summarized typed facts."""

    def __init__(
        self,
        identity: ResearchProducerIdentityV1,
        *,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.identity = identity
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_ns = monotonic_ns
        self._sequences = {stream: 0 for stream in EVENT_TYPES}
        self._lock = threading.Lock()

    def candidate(
        self,
        stream: str,
        data: Mapping[str, object],
        *,
        source_time_ns: int,
        source_event_ids: Sequence[str] = (),
        privacy_class: str = "research_pseudonymous",
        consent_id: str | None = None,
    ) -> dict[str, object]:
        if stream not in EVENT_TYPES:
            raise ValueError(f"unknown research stream: {stream}")
        if (
            isinstance(source_time_ns, bool)
            or not isinstance(source_time_ns, int)
            or source_time_ns < 0
        ):
            raise ValueError("source_time_ns must be a non-negative integer")
        retention_class = RETENTION_BY_STREAM[stream]
        if "redacted_note" in data:
            if privacy_class != "consent_required" or not consent_id:
                raise ValueError("redacted_note requires an explicit consent_id")
            retention_class = "consented_text_30d"
        with self._lock:
            sequence = self._sequences[stream]
            self._sequences[stream] += 1
        event_id = str(
            uuid.uuid5(
                _EVENT_NAMESPACE,
                f"{self.identity.robot_pseudonym}:{self.identity.run_id}:{stream}:{sequence}",
            )
        )
        occurred_at = self._wall_clock()
        if occurred_at.tzinfo is None:
            raise ValueError("producer wall clock must return a timezone-aware datetime")
        return {
            "specversion": "1.0",
            "id": event_id,
            "source": f"parcel://robot/{self.identity.robot_pseudonym}",
            "type": EVENT_TYPES[stream],
            "time": occurred_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "dataschema": "parcel://schemas/research_event_v1",
            "run_id": self.identity.run_id,
            "stream": stream,
            "sequence": sequence,
            "robot_pseudonym": self.identity.robot_pseudonym,
            "origin": {
                "device_clock": self.identity.device_clock,
                "source_time_ns": source_time_ns,
                "receive_monotonic_ns": self._monotonic_ns(),
            },
            "privacy_class": privacy_class,
            "purpose": "research_evaluation",
            "consent_id": consent_id,
            "retention_class": retention_class,
            "priority": PRIORITY_BY_STREAM[stream],
            "provenance": {
                "source_event_ids": list(source_event_ids),
                "code_sha256": self.identity.code_sha256,
                "config_sha256": self.identity.config_sha256,
                "model_ids": list(self.identity.model_ids),
                "calibration_ids": list(self.identity.calibration_ids),
            },
            "data": dict(data),
        }
