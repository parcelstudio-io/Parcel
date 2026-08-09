"""Sim-bag recorder/replayer — real-sensor-shaped bags for Parcel (K2′).

Hardware claims are out of scope until P5. Agent-facing bags reject privileged
oracle fields; scorer truth stays outside this path.
"""

from __future__ import annotations

from parcel_robot.bags.recorder import BagRecorder
from parcel_robot.bags.replayer import BagReplayer
from parcel_robot.bags.schema import (
    DEFAULT_DOES_NOT_PROVE,
    KNOWN_TOPICS,
    SCHEMA_VERSION,
    BagSchemaError,
    default_clocks,
    default_frames,
    is_privileged_key,
    make_envelope,
    make_manifest,
    reject_privileged_fields,
    validate_manifest,
    validate_message,
)

__all__ = [
    "BagRecorder",
    "BagReplayer",
    "BagSchemaError",
    "DEFAULT_DOES_NOT_PROVE",
    "KNOWN_TOPICS",
    "SCHEMA_VERSION",
    "default_clocks",
    "default_frames",
    "is_privileged_key",
    "make_envelope",
    "make_manifest",
    "reject_privileged_fields",
    "validate_manifest",
    "validate_message",
]
