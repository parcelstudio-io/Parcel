"""Strict, bounded V1 DTOs for the gateway/fake-Sport process seam.

The wire carries *duration TTLs*.  It intentionally carries no client-side
absolute monotonic deadline: monotonic clocks from different processes are
not comparable.  A receiving gateway derives its own deadline at receipt.

``GatewayAckV1`` acknowledges protocol admission only.  It is never evidence
that Sport moved or that the robot stopped; those claims live in state and
stop-report DTOs backed by fake feedback in this N24 slice.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeAlias

GATEWAY_PROTOCOL_VERSION = 1
MAX_GATEWAY_PACKET_BYTES = 16 * 1024
# The existing 0.35 s simulator/control lease is frozen, not retuned, by N24.
MAX_LOCAL_TTL_MS = 350

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GatewayPhaseV1(str, Enum):
    DISARMED = "disarmed"
    ARMED = "armed"
    LATCHED = "latched"


class GatewayAckDispositionV1(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STOPPED = "stopped"


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} keys must be strings")
    return dict(value)


def _exact_fields(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{name} fields mismatch: missing={missing}, extra={extra}")


def _string(value: object, name: str, *, maximum: int = 128, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (not value and not allow_empty) or len(value) > maximum:
        qualifier = "0" if allow_empty else "1"
        raise ValueError(f"{name} must contain {qualifier}..{maximum} characters")
    return value


def _integer(value: object, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        upper = "unbounded" if maximum is None else str(maximum)
        raise ValueError(f"{name} must be in [{minimum}, {upper}]")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _version(value: object) -> int:
    version = _integer(value, "schema_version", minimum=1)
    if version != GATEWAY_PROTOCOL_VERSION:
        raise ValueError(f"unsupported gateway schema version {version}")
    return version


def _sha256(value: object, name: str) -> str:
    digest = _string(value, name, maximum=64)
    if _SHA256_RE.fullmatch(digest) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return digest


def _kind(value: object, expected: str) -> str:
    kind = _string(value, "kind", maximum=32)
    if kind != expected:
        raise ValueError(f"expected gateway message kind {expected!r}, got {kind!r}")
    return kind


@dataclass(frozen=True, slots=True)
class GatewayHashesV1:
    """Compatibility identities carried on every authority-bearing request.

    N24 pins propagation and equality only.  N29 remains responsible for
    generating and signing the canonical manifest/envelope identities.
    """

    config_sha256: str
    capability_sha256: str
    calibration_sha256: str
    firmware_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "config_sha256",
            "capability_sha256",
            "calibration_sha256",
            "firmware_sha256",
        ):
            _sha256(getattr(self, name), name)

    @classmethod
    def from_mapping(cls, value: object) -> GatewayHashesV1:
        data = _mapping(value, "GatewayHashesV1")
        expected = {
            "config_sha256",
            "capability_sha256",
            "calibration_sha256",
            "firmware_sha256",
        }
        _exact_fields(data, expected, "GatewayHashesV1")
        return cls(**{name: _sha256(data[name], name) for name in expected})

    def as_dict(self) -> dict[str, object]:
        return {
            "config_sha256": self.config_sha256,
            "capability_sha256": self.capability_sha256,
            "calibration_sha256": self.calibration_sha256,
            "firmware_sha256": self.firmware_sha256,
        }


@dataclass(frozen=True, slots=True)
class GatewayHelloV1:
    boot_epoch: str
    gateway_sequence: int
    phase: GatewayPhaseV1
    required_hashes: GatewayHashesV1
    schema_version: int = GATEWAY_PROTOCOL_VERSION
    kind: str = field(default="hello", init=False)

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _string(self.boot_epoch, "boot_epoch", maximum=80)
        _integer(self.gateway_sequence, "gateway_sequence", minimum=1)
        if not isinstance(self.phase, GatewayPhaseV1):
            raise TypeError("phase must be a GatewayPhaseV1")
        if not isinstance(self.required_hashes, GatewayHashesV1):
            raise TypeError("required_hashes must be GatewayHashesV1")

    @classmethod
    def from_mapping(cls, value: object) -> GatewayHelloV1:
        data = _message_mapping(
            value, "hello", {"boot_epoch", "gateway_sequence", "phase", "required_hashes"}
        )
        return cls(
            boot_epoch=_string(data["boot_epoch"], "boot_epoch", maximum=80),
            gateway_sequence=_integer(data["gateway_sequence"], "gateway_sequence", minimum=1),
            phase=GatewayPhaseV1(_string(data["phase"], "phase", maximum=16)),
            required_hashes=GatewayHashesV1.from_mapping(data["required_hashes"]),
            schema_version=_version(data["schema_version"]),
        )

    def as_dict(self) -> dict[str, object]:
        return _base(self) | {
            "boot_epoch": self.boot_epoch,
            "gateway_sequence": self.gateway_sequence,
            "phase": self.phase.value,
            "required_hashes": self.required_hashes.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class GatewayAcquireV1:
    writer_id: str
    boot_epoch: str
    sequence: int
    local_ttl_ms: int
    hashes: GatewayHashesV1
    schema_version: int = GATEWAY_PROTOCOL_VERSION
    kind: str = field(default="acquire", init=False)

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _string(self.writer_id, "writer_id", maximum=80)
        _string(self.boot_epoch, "boot_epoch", maximum=80)
        _integer(self.sequence, "sequence", minimum=1)
        _integer(self.local_ttl_ms, "local_ttl_ms", minimum=1, maximum=MAX_LOCAL_TTL_MS)
        if not isinstance(self.hashes, GatewayHashesV1):
            raise TypeError("hashes must be GatewayHashesV1")

    @classmethod
    def from_mapping(cls, value: object) -> GatewayAcquireV1:
        data = _message_mapping(
            value, "acquire", {"writer_id", "boot_epoch", "sequence", "local_ttl_ms", "hashes"}
        )
        return cls(
            writer_id=_string(data["writer_id"], "writer_id", maximum=80),
            boot_epoch=_string(data["boot_epoch"], "boot_epoch", maximum=80),
            sequence=_integer(data["sequence"], "sequence", minimum=1),
            local_ttl_ms=_integer(
                data["local_ttl_ms"], "local_ttl_ms", minimum=1, maximum=MAX_LOCAL_TTL_MS
            ),
            hashes=GatewayHashesV1.from_mapping(data["hashes"]),
            schema_version=_version(data["schema_version"]),
        )

    def as_dict(self) -> dict[str, object]:
        return _base(self) | {
            "writer_id": self.writer_id,
            "boot_epoch": self.boot_epoch,
            "sequence": self.sequence,
            "local_ttl_ms": self.local_ttl_ms,
            "hashes": self.hashes.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class GatewayCommandV1:
    writer_id: str
    boot_epoch: str
    sequence: int
    local_ttl_ms: int
    frame_id: str
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    task_id: str
    trace_id: str
    hashes: GatewayHashesV1
    schema_version: int = GATEWAY_PROTOCOL_VERSION
    kind: str = field(default="command", init=False)

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _string(self.writer_id, "writer_id", maximum=80)
        _string(self.boot_epoch, "boot_epoch", maximum=80)
        _integer(self.sequence, "sequence", minimum=1)
        _integer(self.local_ttl_ms, "local_ttl_ms", minimum=1, maximum=MAX_LOCAL_TTL_MS)
        if self.frame_id != "base_link":
            raise ValueError("GatewayCommandV1.frame_id must be 'base_link'")
        for name in ("vx_mps", "vy_mps", "vyaw_rad_s"):
            _number(getattr(self, name), name)
        _string(self.task_id, "task_id", maximum=128)
        _string(self.trace_id, "trace_id", maximum=128)
        if not isinstance(self.hashes, GatewayHashesV1):
            raise TypeError("hashes must be GatewayHashesV1")

    @classmethod
    def from_mapping(cls, value: object) -> GatewayCommandV1:
        fields = {
            "writer_id",
            "boot_epoch",
            "sequence",
            "local_ttl_ms",
            "frame_id",
            "vx_mps",
            "vy_mps",
            "vyaw_rad_s",
            "task_id",
            "trace_id",
            "hashes",
        }
        data = _message_mapping(value, "command", fields)
        return cls(
            writer_id=_string(data["writer_id"], "writer_id", maximum=80),
            boot_epoch=_string(data["boot_epoch"], "boot_epoch", maximum=80),
            sequence=_integer(data["sequence"], "sequence", minimum=1),
            local_ttl_ms=_integer(
                data["local_ttl_ms"], "local_ttl_ms", minimum=1, maximum=MAX_LOCAL_TTL_MS
            ),
            frame_id=_string(data["frame_id"], "frame_id", maximum=32),
            vx_mps=_number(data["vx_mps"], "vx_mps"),
            vy_mps=_number(data["vy_mps"], "vy_mps"),
            vyaw_rad_s=_number(data["vyaw_rad_s"], "vyaw_rad_s"),
            task_id=_string(data["task_id"], "task_id", maximum=128),
            trace_id=_string(data["trace_id"], "trace_id", maximum=128),
            hashes=GatewayHashesV1.from_mapping(data["hashes"]),
            schema_version=_version(data["schema_version"]),
        )

    def as_dict(self) -> dict[str, object]:
        return _base(self) | {
            "writer_id": self.writer_id,
            "boot_epoch": self.boot_epoch,
            "sequence": self.sequence,
            "local_ttl_ms": self.local_ttl_ms,
            "frame_id": self.frame_id,
            "vx_mps": self.vx_mps,
            "vy_mps": self.vy_mps,
            "vyaw_rad_s": self.vyaw_rad_s,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "hashes": self.hashes.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class GatewayStopV1:
    writer_id: str
    boot_epoch: str
    sequence: int
    reason: str
    emergency: bool
    schema_version: int = GATEWAY_PROTOCOL_VERSION
    kind: str = field(default="stop", init=False)

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _string(self.writer_id, "writer_id", maximum=80)
        _string(self.boot_epoch, "boot_epoch", maximum=80)
        _integer(self.sequence, "sequence", minimum=1)
        _string(self.reason, "reason", maximum=160)
        _boolean(self.emergency, "emergency")

    @classmethod
    def from_mapping(cls, value: object) -> GatewayStopV1:
        data = _message_mapping(
            value, "stop", {"writer_id", "boot_epoch", "sequence", "reason", "emergency"}
        )
        return cls(
            writer_id=_string(data["writer_id"], "writer_id", maximum=80),
            boot_epoch=_string(data["boot_epoch"], "boot_epoch", maximum=80),
            sequence=_integer(data["sequence"], "sequence", minimum=1),
            reason=_string(data["reason"], "reason", maximum=160),
            emergency=_boolean(data["emergency"], "emergency"),
            schema_version=_version(data["schema_version"]),
        )

    def as_dict(self) -> dict[str, object]:
        return _base(self) | {
            "writer_id": self.writer_id,
            "boot_epoch": self.boot_epoch,
            "sequence": self.sequence,
            "reason": self.reason,
            "emergency": self.emergency,
        }


@dataclass(frozen=True, slots=True)
class GatewayStateQueryV1:
    sequence: int
    schema_version: int = GATEWAY_PROTOCOL_VERSION
    kind: str = field(default="state_query", init=False)

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _integer(self.sequence, "sequence", minimum=1)

    @classmethod
    def from_mapping(cls, value: object) -> GatewayStateQueryV1:
        data = _message_mapping(value, "state_query", {"sequence"})
        return cls(
            sequence=_integer(data["sequence"], "sequence", minimum=1),
            schema_version=_version(data["schema_version"]),
        )

    def as_dict(self) -> dict[str, object]:
        return _base(self) | {"sequence": self.sequence}


@dataclass(frozen=True, slots=True)
class GatewayAckV1:
    boot_epoch: str
    gateway_sequence: int
    acknowledged_kind: str
    acknowledged_sequence: int
    disposition: GatewayAckDispositionV1
    reason: str
    ack_scope: str = "gateway_admission"
    schema_version: int = GATEWAY_PROTOCOL_VERSION
    kind: str = field(default="ack", init=False)

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _string(self.boot_epoch, "boot_epoch", maximum=80)
        _integer(self.gateway_sequence, "gateway_sequence", minimum=1)
        _string(self.acknowledged_kind, "acknowledged_kind", maximum=32)
        _integer(self.acknowledged_sequence, "acknowledged_sequence", minimum=1)
        if not isinstance(self.disposition, GatewayAckDispositionV1):
            raise TypeError("disposition must be GatewayAckDispositionV1")
        _string(self.reason, "reason", maximum=160, allow_empty=True)
        if self.ack_scope != "gateway_admission":
            raise ValueError("GatewayAckV1 never acknowledges physical motion or stillness")

    @classmethod
    def from_mapping(cls, value: object) -> GatewayAckV1:
        fields = {
            "boot_epoch",
            "gateway_sequence",
            "acknowledged_kind",
            "acknowledged_sequence",
            "disposition",
            "reason",
            "ack_scope",
        }
        data = _message_mapping(value, "ack", fields)
        return cls(
            boot_epoch=_string(data["boot_epoch"], "boot_epoch", maximum=80),
            gateway_sequence=_integer(data["gateway_sequence"], "gateway_sequence", minimum=1),
            acknowledged_kind=_string(data["acknowledged_kind"], "acknowledged_kind", maximum=32),
            acknowledged_sequence=_integer(
                data["acknowledged_sequence"], "acknowledged_sequence", minimum=1
            ),
            disposition=GatewayAckDispositionV1(
                _string(data["disposition"], "disposition", maximum=16)
            ),
            reason=_string(data["reason"], "reason", maximum=160, allow_empty=True),
            ack_scope=_string(data["ack_scope"], "ack_scope", maximum=32),
            schema_version=_version(data["schema_version"]),
        )

    def as_dict(self) -> dict[str, object]:
        return _base(self) | {
            "boot_epoch": self.boot_epoch,
            "gateway_sequence": self.gateway_sequence,
            "acknowledged_kind": self.acknowledged_kind,
            "acknowledged_sequence": self.acknowledged_sequence,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "ack_scope": self.ack_scope,
        }


@dataclass(frozen=True, slots=True)
class GatewayStateV1:
    boot_epoch: str
    gateway_sequence: int
    phase: GatewayPhaseV1
    state_sequence: int
    state_age_ms: float
    lease_active: bool
    writer_id: str
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    stationary: bool
    last_stop_sequence: int
    last_stop_reason: str
    schema_version: int = GATEWAY_PROTOCOL_VERSION
    kind: str = field(default="state", init=False)

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _string(self.boot_epoch, "boot_epoch", maximum=80)
        _integer(self.gateway_sequence, "gateway_sequence", minimum=1)
        if not isinstance(self.phase, GatewayPhaseV1):
            raise TypeError("phase must be GatewayPhaseV1")
        _integer(self.state_sequence, "state_sequence", minimum=1)
        age = _number(self.state_age_ms, "state_age_ms")
        if age < 0.0:
            raise ValueError("state_age_ms must be non-negative")
        _boolean(self.lease_active, "lease_active")
        _string(self.writer_id, "writer_id", maximum=80, allow_empty=True)
        for name in ("vx_mps", "vy_mps", "vyaw_rad_s"):
            _number(getattr(self, name), name)
        _boolean(self.stationary, "stationary")
        _integer(self.last_stop_sequence, "last_stop_sequence", minimum=0)
        _string(self.last_stop_reason, "last_stop_reason", maximum=160, allow_empty=True)

    @classmethod
    def from_mapping(cls, value: object) -> GatewayStateV1:
        fields = {
            "boot_epoch",
            "gateway_sequence",
            "phase",
            "state_sequence",
            "state_age_ms",
            "lease_active",
            "writer_id",
            "vx_mps",
            "vy_mps",
            "vyaw_rad_s",
            "stationary",
            "last_stop_sequence",
            "last_stop_reason",
        }
        data = _message_mapping(value, "state", fields)
        return cls(
            boot_epoch=_string(data["boot_epoch"], "boot_epoch", maximum=80),
            gateway_sequence=_integer(data["gateway_sequence"], "gateway_sequence", minimum=1),
            phase=GatewayPhaseV1(_string(data["phase"], "phase", maximum=16)),
            state_sequence=_integer(data["state_sequence"], "state_sequence", minimum=1),
            state_age_ms=_number(data["state_age_ms"], "state_age_ms"),
            lease_active=_boolean(data["lease_active"], "lease_active"),
            writer_id=_string(data["writer_id"], "writer_id", maximum=80, allow_empty=True),
            vx_mps=_number(data["vx_mps"], "vx_mps"),
            vy_mps=_number(data["vy_mps"], "vy_mps"),
            vyaw_rad_s=_number(data["vyaw_rad_s"], "vyaw_rad_s"),
            stationary=_boolean(data["stationary"], "stationary"),
            last_stop_sequence=_integer(
                data["last_stop_sequence"], "last_stop_sequence", minimum=0
            ),
            last_stop_reason=_string(
                data["last_stop_reason"], "last_stop_reason", maximum=160, allow_empty=True
            ),
            schema_version=_version(data["schema_version"]),
        )

    def as_dict(self) -> dict[str, object]:
        return _base(self) | {
            "boot_epoch": self.boot_epoch,
            "gateway_sequence": self.gateway_sequence,
            "phase": self.phase.value,
            "state_sequence": self.state_sequence,
            "state_age_ms": self.state_age_ms,
            "lease_active": self.lease_active,
            "writer_id": self.writer_id,
            "vx_mps": self.vx_mps,
            "vy_mps": self.vy_mps,
            "vyaw_rad_s": self.vyaw_rad_s,
            "stationary": self.stationary,
            "last_stop_sequence": self.last_stop_sequence,
            "last_stop_reason": self.last_stop_reason,
        }


@dataclass(frozen=True, slots=True)
class GatewayStopReportV1:
    boot_epoch: str
    gateway_sequence: int
    stop_sequence: int
    reason: str
    stop_rpc_completed: bool
    stationary_confirmed: bool
    state_sequence: int
    schema_version: int = GATEWAY_PROTOCOL_VERSION
    kind: str = field(default="stop_report", init=False)

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _string(self.boot_epoch, "boot_epoch", maximum=80)
        _integer(self.gateway_sequence, "gateway_sequence", minimum=1)
        _integer(self.stop_sequence, "stop_sequence", minimum=1)
        _string(self.reason, "reason", maximum=160)
        _boolean(self.stop_rpc_completed, "stop_rpc_completed")
        _boolean(self.stationary_confirmed, "stationary_confirmed")
        _integer(self.state_sequence, "state_sequence", minimum=0)
        if self.stationary_confirmed and not self.stop_rpc_completed:
            raise ValueError("a failed Stop RPC cannot confirm stationary state")
        if self.stationary_confirmed and self.state_sequence < 1:
            raise ValueError("stationary confirmation requires a feedback state sequence")

    @classmethod
    def from_mapping(cls, value: object) -> GatewayStopReportV1:
        fields = {
            "boot_epoch",
            "gateway_sequence",
            "stop_sequence",
            "reason",
            "stop_rpc_completed",
            "stationary_confirmed",
            "state_sequence",
        }
        data = _message_mapping(value, "stop_report", fields)
        return cls(
            boot_epoch=_string(data["boot_epoch"], "boot_epoch", maximum=80),
            gateway_sequence=_integer(data["gateway_sequence"], "gateway_sequence", minimum=1),
            stop_sequence=_integer(data["stop_sequence"], "stop_sequence", minimum=1),
            reason=_string(data["reason"], "reason", maximum=160),
            stop_rpc_completed=_boolean(data["stop_rpc_completed"], "stop_rpc_completed"),
            stationary_confirmed=_boolean(data["stationary_confirmed"], "stationary_confirmed"),
            state_sequence=_integer(data["state_sequence"], "state_sequence", minimum=0),
            schema_version=_version(data["schema_version"]),
        )

    def as_dict(self) -> dict[str, object]:
        return _base(self) | {
            "boot_epoch": self.boot_epoch,
            "gateway_sequence": self.gateway_sequence,
            "stop_sequence": self.stop_sequence,
            "reason": self.reason,
            "stop_rpc_completed": self.stop_rpc_completed,
            "stationary_confirmed": self.stationary_confirmed,
            "state_sequence": self.state_sequence,
        }


GatewayMessage: TypeAlias = (
    GatewayHelloV1
    | GatewayAcquireV1
    | GatewayCommandV1
    | GatewayStopV1
    | GatewayStateQueryV1
    | GatewayAckV1
    | GatewayStateV1
    | GatewayStopReportV1
)

_DECODERS: dict[str, type[GatewayMessage]] = {
    "hello": GatewayHelloV1,
    "acquire": GatewayAcquireV1,
    "command": GatewayCommandV1,
    "stop": GatewayStopV1,
    "state_query": GatewayStateQueryV1,
    "ack": GatewayAckV1,
    "state": GatewayStateV1,
    "stop_report": GatewayStopReportV1,
}


def _message_mapping(value: object, kind: str, fields: set[str]) -> dict[str, object]:
    data = _mapping(value, f"{kind} message")
    _exact_fields(data, fields | {"schema_version", "kind"}, f"{kind} message")
    _version(data["schema_version"])
    _kind(data["kind"], kind)
    return data


def _base(message: GatewayMessage) -> dict[str, object]:
    return {"schema_version": message.schema_version, "kind": message.kind}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def encode_gateway_message(message: GatewayMessage) -> bytes:
    if not isinstance(message, tuple(_DECODERS.values())):
        raise TypeError("message must be a gateway V1 DTO")
    packet = json.dumps(message.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(packet) > MAX_GATEWAY_PACKET_BYTES:
        raise ValueError("gateway packet exceeds the bounded wire size")
    return packet


def decode_gateway_message(packet: bytes) -> GatewayMessage:
    if not isinstance(packet, bytes):
        raise TypeError("gateway packet must be bytes")
    if not packet or len(packet) > MAX_GATEWAY_PACKET_BYTES:
        raise ValueError("gateway packet size is outside the bounded wire contract")
    try:
        value = json.loads(packet.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("gateway packet is not strict UTF-8 JSON") from exc
    data = _mapping(value, "gateway message")
    kind = _string(data.get("kind"), "kind", maximum=32)
    decoder = _DECODERS.get(kind)
    if decoder is None:
        raise ValueError(f"unsupported gateway message kind {kind!r}")
    return decoder.from_mapping(data)
