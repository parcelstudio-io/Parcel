"""Internal validation and decoding helpers for the gateway V2 state DTO.

The public dataclass remains in :mod:`parcel_robot.bridge.protocol`; this
module only owns its large, pure validation/decoding implementation so the
wire API and class identity stay stable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GatewayStateV2Codec:
    version: Callable[[object], int]
    string: Callable[..., str]
    integer: Callable[..., int]
    number: Callable[[object, str], float]
    boolean: Callable[[object, str], bool]
    fixed_numbers: Callable[..., tuple[float, ...]]
    fixed_integers: Callable[..., tuple[int, ...]]
    optional_number: Callable[[object, str], float | None]
    optional_nonnegative_number: Callable[[object, str], float | None]
    optional_integer: Callable[..., int | None]
    optional_fixed_integers: Callable[..., tuple[int, ...] | None]
    mapping: Callable[[object, str], dict[str, object]]
    exact_fields: Callable[[dict[str, object], set[str], str], None]
    kind: Callable[[object, str], str]
    phase_type: Callable[[str], object]
    body_kind_type: Callable[[str], object]


STATE_V2_FIELDS = {
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
    "body_kind",
    "telemetry_valid",
    "vendor_position_m",
    "vendor_rpy_rad",
    "mode",
    "error_code",
    "source_time_s",
    "sport_foot_force_raw",
    "feedback_integrity_ok",
    "feedback_integrity_reason",
    "commissioned_soc_ok",
    "commissioned_soc_reason",
    "low_state_valid",
    "low_state_sequence",
    "low_state_age_ms",
    "low_state_tick",
    "battery_soc_percent",
    "power_v",
    "power_a",
    "max_motor_temperature_raw",
    "motor_lost_max_raw",
    "foot_force_est_raw",
    "imu_temperature_raw",
    "temperature_ntc_raw",
    "bms_status",
}


def _validate_base_and_sport(state: Any, codec: GatewayStateV2Codec) -> None:
    codec.version(state.schema_version)
    codec.string(state.boot_epoch, "boot_epoch", maximum=80)
    codec.integer(state.gateway_sequence, "gateway_sequence", minimum=1)
    if not isinstance(state.phase, codec.phase_type):
        raise TypeError("phase must be GatewayPhaseV1")
    codec.integer(state.state_sequence, "state_sequence", minimum=1)
    age = codec.number(state.state_age_ms, "state_age_ms")
    if age < 0.0:
        raise ValueError("state_age_ms must be non-negative")
    codec.boolean(state.lease_active, "lease_active")
    codec.string(state.writer_id, "writer_id", maximum=80, allow_empty=True)
    for name in ("vx_mps", "vy_mps", "vyaw_rad_s"):
        codec.number(getattr(state, name), name)
    codec.boolean(state.stationary, "stationary")
    codec.integer(state.last_stop_sequence, "last_stop_sequence", minimum=0)
    codec.string(state.last_stop_reason, "last_stop_reason", maximum=160, allow_empty=True)
    if not isinstance(state.body_kind, codec.body_kind_type):
        raise TypeError("body_kind must be a GatewayBodyKindV1")
    codec.boolean(state.telemetry_valid, "telemetry_valid")
    object.__setattr__(
        state,
        "vendor_position_m",
        codec.fixed_numbers(state.vendor_position_m, "vendor_position_m", length=3),
    )
    object.__setattr__(
        state,
        "vendor_rpy_rad",
        codec.fixed_numbers(state.vendor_rpy_rad, "vendor_rpy_rad", length=3),
    )
    codec.integer(state.mode, "mode", minimum=0, maximum=255)
    codec.integer(state.error_code, "error_code", minimum=0, maximum=2**32 - 1)
    object.__setattr__(
        state,
        "source_time_s",
        codec.optional_number(state.source_time_s, "source_time_s"),
    )
    object.__setattr__(
        state,
        "sport_foot_force_raw",
        codec.fixed_integers(
            state.sport_foot_force_raw,
            "sport_foot_force_raw",
            length=4,
            minimum=-(2**15),
            maximum=2**15 - 1,
        ),
    )


def _validate_integrity_and_soc(state: Any, codec: GatewayStateV2Codec) -> None:
    if state.feedback_integrity_ok is not None:
        codec.boolean(state.feedback_integrity_ok, "feedback_integrity_ok")
    codec.string(state.feedback_integrity_reason, "feedback_integrity_reason", maximum=160)
    if state.feedback_integrity_ok is None and (
        state.feedback_integrity_reason != "feedback_integrity_unavailable"
    ):
        raise ValueError("unavailable feedback integrity must carry its canonical reason")
    if (
        state.feedback_integrity_ok is not None
        and state.feedback_integrity_reason == "feedback_integrity_unavailable"
    ):
        raise ValueError("available feedback integrity cannot carry the unavailable reason")
    if state.feedback_integrity_ok is not None and state.feedback_integrity_ok is not (
        state.feedback_integrity_reason == "ok"
    ):
        raise ValueError("V2 feedback integrity verdict and reason disagree")
    if state.commissioned_soc_ok is not None:
        codec.boolean(state.commissioned_soc_ok, "commissioned_soc_ok")
    codec.string(state.commissioned_soc_reason, "commissioned_soc_reason", maximum=160)
    expected_soc_reason = {
        True: "soc_above_commissioned_minimum",
        False: "soc_at_or_below_commissioned_minimum",
        None: "commissioned_soc_unavailable",
    }[state.commissioned_soc_ok]
    if state.commissioned_soc_reason != expected_soc_reason:
        raise ValueError("V2 commissioned SOC verdict and reason disagree")


def _validate_low_state(state: Any, codec: GatewayStateV2Codec) -> tuple[object, ...]:
    codec.boolean(state.low_state_valid, "low_state_valid")
    codec.integer(state.low_state_sequence, "low_state_sequence", minimum=0)
    object.__setattr__(
        state,
        "low_state_age_ms",
        codec.optional_nonnegative_number(state.low_state_age_ms, "low_state_age_ms"),
    )
    codec.optional_integer(state.low_state_tick, "low_state_tick", minimum=0, maximum=2**32 - 1)
    codec.optional_integer(state.battery_soc_percent, "battery_soc_percent", minimum=0, maximum=100)
    object.__setattr__(state, "power_v", codec.optional_number(state.power_v, "power_v"))
    object.__setattr__(state, "power_a", codec.optional_number(state.power_a, "power_a"))
    codec.optional_integer(
        state.max_motor_temperature_raw,
        "max_motor_temperature_raw",
        minimum=0,
        maximum=255,
    )
    codec.optional_integer(
        state.motor_lost_max_raw,
        "motor_lost_max_raw",
        minimum=0,
        maximum=2**32 - 1,
    )
    object.__setattr__(
        state,
        "foot_force_est_raw",
        codec.optional_fixed_integers(
            state.foot_force_est_raw,
            "foot_force_est_raw",
            length=4,
            minimum=-(2**15),
            maximum=2**15 - 1,
        ),
    )
    codec.optional_integer(state.imu_temperature_raw, "imu_temperature_raw", minimum=0, maximum=255)
    object.__setattr__(
        state,
        "temperature_ntc_raw",
        codec.optional_fixed_integers(
            state.temperature_ntc_raw,
            "temperature_ntc_raw",
            length=2,
            minimum=0,
            maximum=255,
        ),
    )
    codec.optional_integer(state.bms_status, "bms_status", minimum=0, maximum=255)
    return (
        state.low_state_age_ms,
        state.low_state_tick,
        state.battery_soc_percent,
        state.power_v,
        state.power_a,
        state.max_motor_temperature_raw,
        state.motor_lost_max_raw,
        state.foot_force_est_raw,
        state.imu_temperature_raw,
        state.temperature_ntc_raw,
        state.bms_status,
    )


def _validate_consistency(state: Any, low_values: tuple[object, ...]) -> None:
    if state.low_state_valid:
        if state.low_state_sequence < 1 or any(value is None for value in low_values):
            raise ValueError("valid LowState requires a positive sequence and every raw field")
    elif state.low_state_sequence != 0 or any(value is not None for value in low_values):
        raise ValueError("invalid LowState must carry sequence zero and null raw fields")
    if state.low_state_valid and state.commissioned_soc_ok is None:
        raise ValueError("valid commissioned LowState requires an SOC verdict")
    if not state.low_state_valid and state.commissioned_soc_ok is not None:
        raise ValueError("commissioned SOC must be unavailable without LowState")
    if not state.telemetry_valid and (
        state.vendor_position_m != (0.0, 0.0, 0.0)
        or state.vendor_rpy_rad != (0.0, 0.0, 0.0)
        or state.mode != 0
        or state.error_code != 0
        or state.source_time_s is not None
        or state.sport_foot_force_raw != (0, 0, 0, 0)
    ):
        raise ValueError("invalid Sport telemetry must carry only neutral placeholders")
    if state.telemetry_valid and state.feedback_integrity_ok is None:
        raise ValueError("valid Sport telemetry requires a feedback integrity verdict")
    if not state.telemetry_valid and state.feedback_integrity_ok is not None:
        raise ValueError("invalid Sport telemetry requires unavailable feedback integrity")


def validate_gateway_state_v2(state: Any, codec: GatewayStateV2Codec) -> None:
    _validate_base_and_sport(state, codec)
    _validate_integrity_and_soc(state, codec)
    _validate_consistency(state, _validate_low_state(state, codec))


def _decode_base(data: dict[str, object], codec: GatewayStateV2Codec) -> dict[str, object]:
    return {
        "boot_epoch": codec.string(data["boot_epoch"], "boot_epoch", maximum=80),
        "gateway_sequence": codec.integer(data["gateway_sequence"], "gateway_sequence", minimum=1),
        "phase": codec.phase_type(codec.string(data["phase"], "phase", maximum=16)),
        "state_sequence": codec.integer(data["state_sequence"], "state_sequence", minimum=1),
        "state_age_ms": codec.number(data["state_age_ms"], "state_age_ms"),
        "lease_active": codec.boolean(data["lease_active"], "lease_active"),
        "writer_id": codec.string(data["writer_id"], "writer_id", maximum=80, allow_empty=True),
        "vx_mps": codec.number(data["vx_mps"], "vx_mps"),
        "vy_mps": codec.number(data["vy_mps"], "vy_mps"),
        "vyaw_rad_s": codec.number(data["vyaw_rad_s"], "vyaw_rad_s"),
        "stationary": codec.boolean(data["stationary"], "stationary"),
        "last_stop_sequence": codec.integer(
            data["last_stop_sequence"], "last_stop_sequence", minimum=0
        ),
        "last_stop_reason": codec.string(
            data["last_stop_reason"], "last_stop_reason", maximum=160, allow_empty=True
        ),
    }


def _decode_sport(data: dict[str, object], codec: GatewayStateV2Codec) -> dict[str, object]:
    return {
        "body_kind": codec.body_kind_type(codec.string(data["body_kind"], "body_kind", maximum=32)),
        "telemetry_valid": codec.boolean(data["telemetry_valid"], "telemetry_valid"),
        "vendor_position_m": codec.fixed_numbers(
            data["vendor_position_m"], "vendor_position_m", length=3
        ),
        "vendor_rpy_rad": codec.fixed_numbers(data["vendor_rpy_rad"], "vendor_rpy_rad", length=3),
        "mode": codec.integer(data["mode"], "mode", minimum=0, maximum=255),
        "error_code": codec.integer(data["error_code"], "error_code", minimum=0, maximum=2**32 - 1),
        "source_time_s": codec.optional_number(data["source_time_s"], "source_time_s"),
        "sport_foot_force_raw": codec.fixed_integers(
            data["sport_foot_force_raw"],
            "sport_foot_force_raw",
            length=4,
            minimum=-(2**15),
            maximum=2**15 - 1,
        ),
    }


def _decode_verdicts(data: dict[str, object], codec: GatewayStateV2Codec) -> dict[str, object]:
    return {
        "feedback_integrity_ok": (
            None
            if data["feedback_integrity_ok"] is None
            else codec.boolean(data["feedback_integrity_ok"], "feedback_integrity_ok")
        ),
        "feedback_integrity_reason": codec.string(
            data["feedback_integrity_reason"], "feedback_integrity_reason", maximum=160
        ),
        "commissioned_soc_ok": (
            None
            if data["commissioned_soc_ok"] is None
            else codec.boolean(data["commissioned_soc_ok"], "commissioned_soc_ok")
        ),
        "commissioned_soc_reason": codec.string(
            data["commissioned_soc_reason"], "commissioned_soc_reason", maximum=160
        ),
    }


def _decode_low_state(data: dict[str, object], codec: GatewayStateV2Codec) -> dict[str, object]:
    return {
        "low_state_valid": codec.boolean(data["low_state_valid"], "low_state_valid"),
        "low_state_sequence": codec.integer(
            data["low_state_sequence"], "low_state_sequence", minimum=0
        ),
        "low_state_age_ms": codec.optional_nonnegative_number(
            data["low_state_age_ms"], "low_state_age_ms"
        ),
        "low_state_tick": codec.optional_integer(
            data["low_state_tick"], "low_state_tick", minimum=0, maximum=2**32 - 1
        ),
        "battery_soc_percent": codec.optional_integer(
            data["battery_soc_percent"], "battery_soc_percent", minimum=0, maximum=100
        ),
        "power_v": codec.optional_number(data["power_v"], "power_v"),
        "power_a": codec.optional_number(data["power_a"], "power_a"),
        "max_motor_temperature_raw": codec.optional_integer(
            data["max_motor_temperature_raw"], "max_motor_temperature_raw", minimum=0, maximum=255
        ),
        "motor_lost_max_raw": codec.optional_integer(
            data["motor_lost_max_raw"], "motor_lost_max_raw", minimum=0, maximum=2**32 - 1
        ),
        "foot_force_est_raw": codec.optional_fixed_integers(
            data["foot_force_est_raw"],
            "foot_force_est_raw",
            length=4,
            minimum=-(2**15),
            maximum=2**15 - 1,
        ),
        "imu_temperature_raw": codec.optional_integer(
            data["imu_temperature_raw"], "imu_temperature_raw", minimum=0, maximum=255
        ),
        "temperature_ntc_raw": codec.optional_fixed_integers(
            data["temperature_ntc_raw"],
            "temperature_ntc_raw",
            length=2,
            minimum=0,
            maximum=255,
        ),
        "bms_status": codec.optional_integer(
            data["bms_status"], "bms_status", minimum=0, maximum=255
        ),
    }


def gateway_state_v2_from_mapping(
    state_type: Callable[..., Any],
    value: object,
    codec: GatewayStateV2Codec,
) -> Any:
    data = codec.mapping(value, "state_v2 message")
    codec.exact_fields(data, STATE_V2_FIELDS | {"schema_version", "kind"}, "state_v2 message")
    codec.version(data["schema_version"])
    codec.kind(data["kind"], "state_v2")
    fields = _decode_base(data, codec)
    fields.update(_decode_sport(data, codec))
    fields.update(_decode_verdicts(data, codec))
    fields.update(_decode_low_state(data, codec))
    fields["schema_version"] = codec.version(data["schema_version"])
    return state_type(**fields)
