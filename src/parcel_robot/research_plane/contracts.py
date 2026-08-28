"""Strict v1 contracts for pseudonymous research summary events.

The event shape is CloudEvents-inspired, but intentionally narrower.  It
accepts only bounded summary fields; raw media, transcripts, exact locations,
biometric embeddings, and credentials have no representation here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SCHEMA_ID = "parcel://schemas/research_event_v1"
SPEC_VERSION = "1.0"
PURPOSE = "research_evaluation"
MAX_EVENT_BYTES = 32 * 1024

EVENT_TYPES: dict[str, str] = {
    "navigation": "ai.parcel.research.navigation.summary.v1",
    "conversation": "ai.parcel.research.conversation.outcome.v1",
    "audio": "ai.parcel.research.audio.summary.v1",
    "perception": "ai.parcel.research.perception.summary.v1",
    "feedback": "ai.parcel.research.learning.feedback.v1",
}

# Priority zero is reserved for a future authenticated control plane. Research
# producers cannot self-promote summaries into that byte bucket, and every
# admitted stream has one canonical scheduling priority.
PRIORITY_BY_STREAM: dict[str, int] = {
    "feedback": 1,
    "conversation": 1,
    "navigation": 2,
    "audio": 2,
    "perception": 2,
}

ALLOWED_DATA_KEYS: dict[str, frozenset[str]] = {
    "navigation": frozenset(
        {
            "distance_delta_m",
            "speed_mps",
            "localization_confidence",
            "planner_state",
            "recovery_count",
            "path_segment_hash",
            "terminal_code",
        }
    ),
    "conversation": frozenset(
        {
            "outcome_code",
            "latency_ms",
            "turn_count",
            "repair_count",
            "safety_route_used",
            "redacted_note",
        }
    ),
    "audio": frozenset(
        {
            "speech_probability",
            "snr_db",
            "vad_segments",
            "acoustic_class",
            "source_chunk_hash",
        }
    ),
    "perception": frozenset(
        {
            "class_counts",
            "obstacle_min_m",
            "detector_confidence",
            "frame_summary_hash",
        }
    ),
    "feedback": frozenset({"label", "task", "reward", "evaluator", "redacted_note"}),
}

PRIVACY_CLASSES = frozenset(
    {"research_nonpersonal", "research_pseudonymous", "consent_required"}
)
RETENTION_CLASSES = frozenset({"summary_90d", "feedback_1y", "consented_text_30d"})
DEVICE_CLOCKS = frozenset({"sim", "sensor", "ros", "system"})

_ROBOT_PSEUDONYM = re.compile(r"^robot_[0-9a-f]{16}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")

_PLANNER_STATES = frozenset(
    {"tracking", "paused", "recovery", "blocked", "arrived", "uncertain", "failed"}
)
_TERMINAL_CODES = frozenset(
    {
        "arrived",
        "no_path",
        "goal_blocked",
        "completion_unverified",
        "localization_lost",
        "cancelled",
        "none",
    }
)
_CONVERSATION_OUTCOMES = frozenset(
    {"completed", "clarified", "declined", "timed_out", "failed", "interrupted"}
)
_ACOUSTIC_CLASSES = frozenset(
    {"quiet", "speech", "television", "appliance", "outdoor", "unknown"}
)
_FEEDBACK_LABELS = frozenset({"success", "partial", "failure"})
_FEEDBACK_TASKS = frozenset(
    {"navigate", "answer", "follow", "recover", "conversation", "perception", "embodiment"}
)
_CLASS_NAME = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")


def canonical_json_bytes(value: object) -> bytes:
    """Return the one byte representation used for hashes and persistence."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _bounded_string(value: object, name: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (not empty and not value) or len(value) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters")
    return value


def _identifier(value: object, name: str) -> str:
    result = _bounded_string(value, name, 128)
    if not _IDENTIFIER.fullmatch(result):
        raise ValueError(f"{name} must be a bounded identifier")
    return result


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _string_tuple(value: object, name: str, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise ValueError(f"{name} must contain at most {maximum} strings")
    result = tuple(_bounded_string(item, name, 256) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _validate_json(value: object, name: str, *, depth: int = 0) -> None:
    if depth > 5:
        raise ValueError(f"{name} exceeds maximum nesting depth")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} contains a non-finite number")
        return
    if isinstance(value, list):
        if len(value) > 128:
            raise ValueError(f"{name} contains too many array items")
        for item in value:
            _validate_json(item, name, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError(f"{name} contains too many object fields")
        for key, item in value.items():
            _bounded_string(key, f"{name} key", 128)
            _validate_json(item, name, depth=depth + 1)
        return
    raise TypeError(f"{name} contains a non-JSON value")


def _parse_datetime(value: object, name: str) -> str:
    text = _bounded_string(value, name, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return text


def _bounded_number(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be finite and between {minimum} and {maximum}")
    return number


def _bounded_integer(value: object, name: str, maximum: int) -> int:
    result = _nonnegative_int(value, name)
    if result > maximum:
        raise ValueError(f"{name} must not exceed {maximum}")
    return result


def _enum_string(value: object, name: str, allowed: frozenset[str]) -> str:
    result = _bounded_string(value, name, 64)
    if result not in allowed:
        raise ValueError(f"{name} is not an allowed value")
    return result


def _optional_sha(data: Mapping[str, Any], key: str) -> None:
    if key in data and (not isinstance(data[key], str) or not _SHA256.fullmatch(data[key])):
        raise ValueError(f"{key} must be lowercase SHA-256")


def _validate_navigation_data(data: Mapping[str, Any]) -> None:
    numeric = {
        "distance_delta_m": (0.0, 1_000.0),
        "speed_mps": (0.0, 10.0),
        "localization_confidence": (0.0, 1.0),
    }
    for key, bounds in numeric.items():
        if key in data:
            _bounded_number(data[key], key, minimum=bounds[0], maximum=bounds[1])
    if "planner_state" in data:
        _enum_string(data["planner_state"], "planner_state", _PLANNER_STATES)
    if "terminal_code" in data:
        _enum_string(data["terminal_code"], "terminal_code", _TERMINAL_CODES)
    if "recovery_count" in data:
        _bounded_integer(data["recovery_count"], "recovery_count", 10_000)
    _optional_sha(data, "path_segment_hash")


def _validate_conversation_data(data: Mapping[str, Any]) -> None:
    if "outcome_code" in data:
        _enum_string(data["outcome_code"], "outcome_code", _CONVERSATION_OUTCOMES)
    for key, maximum in (("latency_ms", 600_000), ("turn_count", 1_000), ("repair_count", 1_000)):
        if key in data:
            _bounded_integer(data[key], key, maximum)
    if "safety_route_used" in data and not isinstance(data["safety_route_used"], bool):
        raise TypeError("safety_route_used must be a boolean")


def _validate_audio_data(data: Mapping[str, Any]) -> None:
    if "speech_probability" in data:
        _bounded_number(
            data["speech_probability"], "speech_probability", minimum=0.0, maximum=1.0
        )
    if "snr_db" in data:
        _bounded_number(data["snr_db"], "snr_db", minimum=-100.0, maximum=200.0)
    if "vad_segments" in data:
        _bounded_integer(data["vad_segments"], "vad_segments", 100_000)
    if "acoustic_class" in data:
        _enum_string(data["acoustic_class"], "acoustic_class", _ACOUSTIC_CLASSES)
    _optional_sha(data, "source_chunk_hash")


def _validate_perception_data(data: Mapping[str, Any]) -> None:
    if "class_counts" in data:
        counts = data["class_counts"]
        if not isinstance(counts, Mapping) or len(counts) > 64:
            raise ValueError("class_counts must be an object with at most 64 classes")
        for name, count in counts.items():
            if not isinstance(name, str) or not _CLASS_NAME.fullmatch(name):
                raise ValueError("class_counts keys must be bounded class identifiers")
            _bounded_integer(count, f"class_counts.{name}", 1_000_000)
    if "obstacle_min_m" in data:
        _bounded_number(data["obstacle_min_m"], "obstacle_min_m", minimum=0.0, maximum=1_000.0)
    if "detector_confidence" in data:
        _bounded_number(
            data["detector_confidence"], "detector_confidence", minimum=0.0, maximum=1.0
        )
    _optional_sha(data, "frame_summary_hash")


def _validate_feedback_data(data: Mapping[str, Any]) -> None:
    if "label" in data:
        _enum_string(data["label"], "label", _FEEDBACK_LABELS)
    if "task" in data:
        _enum_string(data["task"], "task", _FEEDBACK_TASKS)
    if "reward" in data:
        _bounded_number(data["reward"], "reward", minimum=-1.0, maximum=1.0)
    if "evaluator" in data:
        _identifier(data["evaluator"], "evaluator")


def _validate_stream_data(stream: str, data: Mapping[str, Any]) -> None:
    validators = {
        "navigation": _validate_navigation_data,
        "conversation": _validate_conversation_data,
        "audio": _validate_audio_data,
        "perception": _validate_perception_data,
        "feedback": _validate_feedback_data,
    }
    validators[stream](data)
    if "redacted_note" in data:
        _bounded_string(data["redacted_note"], "redacted_note", 512, empty=True)


@dataclass(frozen=True, slots=True)
class ResearchOriginV1:
    device_clock: str
    source_time_ns: int
    receive_monotonic_ns: int

    def __post_init__(self) -> None:
        if self.device_clock not in DEVICE_CLOCKS:
            raise ValueError("device_clock is not supported")
        _nonnegative_int(self.source_time_ns, "source_time_ns")
        _nonnegative_int(self.receive_monotonic_ns, "receive_monotonic_ns")

    @classmethod
    def from_mapping(cls, value: object) -> ResearchOriginV1:
        if not isinstance(value, Mapping) or set(value) != {
            "device_clock",
            "source_time_ns",
            "receive_monotonic_ns",
        }:
            raise ValueError("origin has unknown or missing fields")
        return cls(
            device_clock=str(value["device_clock"]),
            source_time_ns=_nonnegative_int(value["source_time_ns"], "source_time_ns"),
            receive_monotonic_ns=_nonnegative_int(
                value["receive_monotonic_ns"], "receive_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "device_clock": self.device_clock,
            "source_time_ns": self.source_time_ns,
            "receive_monotonic_ns": self.receive_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class ResearchProvenanceV1:
    source_event_ids: tuple[str, ...]
    code_sha256: str
    config_sha256: str
    model_ids: tuple[str, ...] = ()
    calibration_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        source_ids = _string_tuple(self.source_event_ids, "source_event_ids", 32)
        for source_id in source_ids:
            _identifier(source_id, "source_event_id")
        if not _SHA256.fullmatch(self.code_sha256):
            raise ValueError("code_sha256 must be lowercase SHA-256")
        if not _SHA256.fullmatch(self.config_sha256):
            raise ValueError("config_sha256 must be lowercase SHA-256")
        for model_id in _string_tuple(self.model_ids, "model_ids", 16):
            _identifier(model_id, "model_id")
        for calibration_id in _string_tuple(self.calibration_ids, "calibration_ids", 16):
            _identifier(calibration_id, "calibration_id")

    @classmethod
    def from_mapping(cls, value: object) -> ResearchProvenanceV1:
        fields = {
            "source_event_ids",
            "code_sha256",
            "config_sha256",
            "model_ids",
            "calibration_ids",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("provenance has unknown or missing fields")
        return cls(
            source_event_ids=_string_tuple(value["source_event_ids"], "source_event_ids", 32),
            code_sha256=str(value["code_sha256"]),
            config_sha256=str(value["config_sha256"]),
            model_ids=_string_tuple(value["model_ids"], "model_ids", 16),
            calibration_ids=_string_tuple(value["calibration_ids"], "calibration_ids", 16),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "source_event_ids": list(self.source_event_ids),
            "code_sha256": self.code_sha256,
            "config_sha256": self.config_sha256,
            "model_ids": list(self.model_ids),
            "calibration_ids": list(self.calibration_ids),
        }


@dataclass(frozen=True, slots=True)
class ResearchEventV1:
    event_id: str
    source: str
    event_type: str
    occurred_at: str
    run_id: str
    stream: str
    sequence: int
    robot_pseudonym: str
    origin: ResearchOriginV1
    privacy_class: str
    consent_id: str | None
    retention_class: str
    priority: int
    provenance: ResearchProvenanceV1
    data: Mapping[str, Any]
    _canonical_payload: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.event_id)
        except (ValueError, TypeError) as exc:
            raise ValueError("event_id must be a UUID") from exc
        if self.stream not in EVENT_TYPES:
            raise ValueError("stream is not supported")
        if self.event_type != EVENT_TYPES[self.stream]:
            raise ValueError("event_type does not match stream")
        _parse_datetime(self.occurred_at, "occurred_at")
        _identifier(self.run_id, "run_id")
        _nonnegative_int(self.sequence, "sequence")
        if not _ROBOT_PSEUDONYM.fullmatch(self.robot_pseudonym):
            raise ValueError("robot_pseudonym must be robot_ plus 16 lowercase hex digits")
        if self.source != f"parcel://robot/{self.robot_pseudonym}":
            raise ValueError("source must match robot_pseudonym")
        if self.privacy_class not in PRIVACY_CLASSES:
            raise ValueError("privacy_class is not supported")
        if self.privacy_class == "consent_required" and not self.consent_id:
            raise ValueError("consent_required event lacks consent_id")
        if self.consent_id is not None:
            _identifier(self.consent_id, "consent_id")
        if self.retention_class not in RETENTION_CLASSES:
            raise ValueError("retention_class is not supported")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not 0 <= self.priority <= 3:
            raise ValueError("priority must be between zero and three")
        if self.priority != PRIORITY_BY_STREAM[self.stream]:
            raise ValueError("priority does not match stream")
        if not isinstance(self.data, Mapping):
            raise TypeError("data must be an object")
        unknown = set(self.data) - ALLOWED_DATA_KEYS[self.stream]
        if unknown:
            raise ValueError(f"data contains unknown fields: {sorted(unknown)}")
        _validate_json(self.data, "data")
        _validate_stream_data(self.stream, self.data)
        if "redacted_note" in self.data and (
            self.privacy_class != "consent_required"
            or self.retention_class != "consented_text_30d"
        ):
            raise ValueError(
                "redacted_note requires consent_required privacy and consented_text_30d retention"
            )
        encoded = canonical_json_bytes(self._live_dict())
        if len(encoded) > MAX_EVENT_BYTES:
            raise ValueError(f"event exceeds {MAX_EVENT_BYTES} bytes")
        # Freeze the authority-bearing representation at construction. A
        # caller retaining a reference to its input dict cannot mutate what is
        # later hashed or persisted through this event object.
        object.__setattr__(self, "_canonical_payload", encoded)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ResearchEventV1:
        fields = {
            "specversion",
            "id",
            "source",
            "type",
            "time",
            "dataschema",
            "run_id",
            "stream",
            "sequence",
            "robot_pseudonym",
            "origin",
            "privacy_class",
            "purpose",
            "consent_id",
            "retention_class",
            "priority",
            "provenance",
            "data",
        }
        if set(value) != fields:
            raise ValueError("research event has unknown or missing fields")
        if value["specversion"] != SPEC_VERSION or value["dataschema"] != SCHEMA_ID:
            raise ValueError("unsupported research event version")
        if value["purpose"] != PURPOSE:
            raise ValueError("purpose must be research_evaluation")
        sequence = _nonnegative_int(value["sequence"], "sequence")
        priority = _nonnegative_int(value["priority"], "priority")
        data = value["data"]
        if not isinstance(data, Mapping):
            raise TypeError("data must be an object")
        return cls(
            event_id=str(value["id"]),
            source=str(value["source"]),
            event_type=str(value["type"]),
            occurred_at=str(value["time"]),
            run_id=str(value["run_id"]),
            stream=str(value["stream"]),
            sequence=sequence,
            robot_pseudonym=str(value["robot_pseudonym"]),
            origin=ResearchOriginV1.from_mapping(value["origin"]),
            privacy_class=str(value["privacy_class"]),
            consent_id=None if value["consent_id"] is None else str(value["consent_id"]),
            retention_class=str(value["retention_class"]),
            priority=priority,
            provenance=ResearchProvenanceV1.from_mapping(value["provenance"]),
            data=dict(data),
        )

    def _live_dict(self) -> dict[str, object]:
        return {
            "specversion": SPEC_VERSION,
            "id": self.event_id,
            "source": self.source,
            "type": self.event_type,
            "time": self.occurred_at,
            "dataschema": SCHEMA_ID,
            "run_id": self.run_id,
            "stream": self.stream,
            "sequence": self.sequence,
            "robot_pseudonym": self.robot_pseudonym,
            "origin": self.origin.as_dict(),
            "privacy_class": self.privacy_class,
            "purpose": PURPOSE,
            "consent_id": self.consent_id,
            "retention_class": self.retention_class,
            "priority": self.priority,
            "provenance": self.provenance.as_dict(),
            "data": dict(self.data),
        }

    def as_dict(self) -> dict[str, object]:
        # JSON decode supplies a fresh deep copy and avoids leaking mutable
        # references from this frozen contract.
        return json.loads(self._canonical_payload)

    def canonical_bytes(self) -> bytes:
        return self._canonical_payload

    @property
    def sha256(self) -> str:
        return sha256_hex(self.canonical_bytes())


def event_id_digest(events: Sequence[ResearchEventV1]) -> str:
    return sha256_hex("\n".join(event.event_id for event in events).encode("utf-8"))
