"""Versioned Parcel bag schema (real-sensor-shaped, agent-safe).

Bags are hardware-shaped contracts so P5 real recordings drop into the same
harness. Agent-facing messages must not carry privileged oracle fields;
scorer-only truth stays outside this path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "parcel.bag.v1"
MANIFEST_FILENAME = "manifest.json"
MESSAGES_FILENAME = "messages.jsonl"

# Topics shaped like the real Go2 + D455 + UWB + GNSS stack. Payloads are
# metadata-first in the sim MVP; real bags later fill the same envelopes.
KNOWN_TOPICS = frozenset(
    {
        "camera/color/meta",
        "camera/depth/meta",
        "lidar/scan",
        "imu/data",
        "odom/se2",
        "uwb/state",
        "gnss/fix",
        "robot/sport_state",
        "audio/chunk_meta",
    }
)

# Keys (exact or prefix) that must never appear on the agent bag path.
_PRIVILEGED_EXACT = frozenset(
    {
        "oracle",
        "ground_truth",
        "groundtruth",
        "privileged",
        "shortest_path",
        "collision_truth",
        "true_pose",
        "true_semantic_id",
        "scorer_only",
        "world_truth",
        "oracle_pose",
        "oracle_collision",
        "oracle_identity",
        "privileged_pose",
        "privileged_semantics",
    }
)
_PRIVILEGED_PREFIXES = ("oracle_", "privileged_", "ground_truth_", "scorer_")

REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "bag_id",
        "created_at_utc",
        "source",
        "clocks",
        "frames",
        "topics",
        "does_not_prove",
        "message_count",
    }
)

REQUIRED_CLOCK_KEYS = frozenset(
    {
        "source_clock",
        "recording_monotonic_origin_ns",
        "note",
    }
)

REQUIRED_FRAME_KEYS = frozenset(
    {
        "map_frame",
        "odom_frame",
        "base_frame",
        "camera_frame",
        "lidar_frame",
        "ownership_note",
    }
)

REQUIRED_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "evidence_id",
        "source",
        "source_timestamp_ns",
        "received_monotonic_ns",
        "sequence",
        "frame_id",
        "calibration_id",
        "expires_monotonic_ns",
    }
)

DEFAULT_DOES_NOT_PROVE = (
    "Sim-recorded bags do not prove physical camera/LiDAR recognition.",
    "Sim motion messages do not prove Unitree Sport tracking under the 10 Hz stream.",
    "Synthetic UWB/GNSS models do not prove field multipath or outdoor GNSS quality.",
    "Desktop/CPU-proxy timing in bags does not prove Orin NX latency budgets.",
    "Agent bag path excludes scorer oracle fields; replay alone does not prove closed-loop safety.",
)


class BagSchemaError(ValueError):
    """Raised when a bag manifest, message, or payload violates the contract."""


def default_frames() -> dict[str, str]:
    return {
        "map_frame": "map",
        "odom_frame": "odom",
        "base_frame": "base_link",
        "camera_frame": "camera_color_optical_frame",
        "lidar_frame": "lidar_link",
        "ownership_note": (
            "TF ownership is declared here for replay consumers; "
            "P5 commissioning validates physical extrinsics."
        ),
    }


def default_clocks(*, source_clock: str = "sim") -> dict[str, Any]:
    if source_clock not in {"sim", "sensor", "ros"}:
        raise BagSchemaError(f"unsupported source_clock: {source_clock!r}")
    return {
        "source_clock": source_clock,
        "recording_monotonic_origin_ns": 0,
        "note": (
            "Adapters record both source timestamps and local monotonic receive "
            "times; do not mix ROS/system/sim clocks with Python monotonic directly."
        ),
    }


def make_envelope(
    *,
    evidence_id: str,
    source: str,
    source_timestamp_ns: int,
    received_monotonic_ns: int,
    sequence: int,
    frame_id: str,
    calibration_id: str = "uncalibrated",
    expires_monotonic_ns: int | None = None,
    scene_revision: int = 0,
    provenance: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build an EvidenceEnvelopeV1-shaped header for a bag message."""
    if not evidence_id.strip():
        raise BagSchemaError("evidence_id must be non-empty")
    if not frame_id.strip():
        raise BagSchemaError("frame_id must be non-empty")
    if source_timestamp_ns < 0 or received_monotonic_ns < 0:
        raise BagSchemaError("timestamps must be non-negative nanoseconds")
    if sequence < 0:
        raise BagSchemaError("sequence must be non-negative")
    expires = (
        received_monotonic_ns + 500_000_000
        if expires_monotonic_ns is None
        else int(expires_monotonic_ns)
    )
    envelope = {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "source": source,
        "source_timestamp_ns": int(source_timestamp_ns),
        "received_monotonic_ns": int(received_monotonic_ns),
        "sequence": int(sequence),
        "frame_id": frame_id,
        "scene_revision": int(scene_revision),
        "expires_monotonic_ns": expires,
        "calibration_id": calibration_id,
        "provenance": list(provenance or ()),
    }
    validate_envelope(envelope)
    return envelope


def validate_envelope(envelope: Mapping[str, Any]) -> None:
    missing = REQUIRED_ENVELOPE_KEYS - set(envelope)
    if missing:
        raise BagSchemaError(f"envelope missing keys: {sorted(missing)}")
    if int(envelope["schema_version"]) != 1:
        raise BagSchemaError("envelope schema_version must be 1")
    reject_privileged_fields(envelope, path="envelope")


def is_privileged_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _PRIVILEGED_EXACT:
        return True
    return any(lowered.startswith(prefix) for prefix in _PRIVILEGED_PREFIXES)


def reject_privileged_fields(payload: Any, *, path: str = "payload") -> None:
    """Fail closed if privileged oracle fields appear on the agent bag path."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_s = str(key)
            child = f"{path}.{key_s}"
            if is_privileged_key(key_s):
                raise BagSchemaError(
                    f"privileged oracle field forbidden on agent bag path: {child}"
                )
            reject_privileged_fields(value, path=child)
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            reject_privileged_fields(item, path=f"{path}[{index}]")


def validate_topic(topic: str) -> None:
    if not topic or topic.startswith("/") or " " in topic:
        raise BagSchemaError(
            f"topic must be non-empty, unprefixed, and space-free: {topic!r}"
        )
    # Allow known topics and future sensor-shaped extensions under the same rules.
    if "/" not in topic:
        raise BagSchemaError(f"topic must be hierarchical (a/b): {topic!r}")


def validate_message(message: Mapping[str, Any]) -> None:
    for key in ("topic", "envelope", "payload"):
        if key not in message:
            raise BagSchemaError(f"message missing key: {key}")
    validate_topic(str(message["topic"]))
    envelope = message["envelope"]
    if not isinstance(envelope, Mapping):
        raise BagSchemaError("message.envelope must be an object")
    validate_envelope(envelope)
    reject_privileged_fields(message["payload"], path="payload")
    # Topic itself must not smuggle oracle namespaces.
    if is_privileged_key(str(message["topic"]).replace("/", "_")):
        raise BagSchemaError(f"privileged topic forbidden: {message['topic']!r}")


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    missing = REQUIRED_MANIFEST_KEYS - set(manifest)
    if missing:
        raise BagSchemaError(f"manifest missing keys: {sorted(missing)}")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise BagSchemaError(
            f"unsupported schema_version: {manifest['schema_version']!r} "
            f"(expected {SCHEMA_VERSION!r})"
        )
    if not str(manifest["bag_id"]).strip():
        raise BagSchemaError("bag_id must be non-empty")
    if manifest["source"] not in {"sim", "hardware"}:
        raise BagSchemaError(f"unsupported bag source: {manifest['source']!r}")
    clocks = manifest["clocks"]
    if not isinstance(clocks, Mapping):
        raise BagSchemaError("clocks must be an object")
    clock_missing = REQUIRED_CLOCK_KEYS - set(clocks)
    if clock_missing:
        raise BagSchemaError(f"clocks missing keys: {sorted(clock_missing)}")
    frames = manifest["frames"]
    if not isinstance(frames, Mapping):
        raise BagSchemaError("frames must be an object")
    frame_missing = REQUIRED_FRAME_KEYS - set(frames)
    if frame_missing:
        raise BagSchemaError(f"frames missing keys: {sorted(frame_missing)}")
    topics = manifest["topics"]
    if not isinstance(topics, list) or not topics:
        raise BagSchemaError("topics must be a non-empty list")
    for topic in topics:
        validate_topic(str(topic))
    does_not_prove = manifest["does_not_prove"]
    if not isinstance(does_not_prove, list) or not does_not_prove:
        raise BagSchemaError("does_not_prove must be a non-empty list of strings")
    if any(not isinstance(item, str) or not item.strip() for item in does_not_prove):
        raise BagSchemaError("does_not_prove entries must be non-empty strings")
    if int(manifest["message_count"]) < 0:
        raise BagSchemaError("message_count must be non-negative")
    reject_privileged_fields(manifest, path="manifest")


def make_manifest(
    *,
    bag_id: str,
    created_at_utc: str,
    source: str = "sim",
    clocks: Mapping[str, Any] | None = None,
    frames: Mapping[str, Any] | None = None,
    topics: Sequence[str] | None = None,
    does_not_prove: Sequence[str] | None = None,
    message_count: int = 0,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    topic_list = list(topics) if topics is not None else sorted(KNOWN_TOPICS)
    for topic in topic_list:
        validate_topic(topic)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "bag_id": bag_id,
        "created_at_utc": created_at_utc,
        "source": source,
        "clocks": dict(clocks or default_clocks()),
        "frames": dict(frames or default_frames()),
        "topics": topic_list,
        "does_not_prove": list(does_not_prove or DEFAULT_DOES_NOT_PROVE),
        "message_count": int(message_count),
        "hardware_claims": False,
        "agent_path_excludes_oracle": True,
    }
    if extra:
        reject_privileged_fields(extra, path="extra")
        manifest.update(dict(extra))
    validate_manifest(manifest)
    return manifest
