"""Shared contracts for the commissioned motion-gateway adapters."""

from __future__ import annotations

from collections.abc import Callable

from parcel_robot.bridge.gateway_client import MotionGatewayClientV1, MotionStateV2
from parcel_robot.bridge.protocol import MAX_LOCAL_TTL_MS

ClientFactory = Callable[..., MotionGatewayClientV1]
StateObserver = Callable[[MotionStateV2, float], None]


class CommissionedGatewayError(RuntimeError):
    """The commissioned gateway composition lost a verified motion boundary."""


def local_ttl(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("motion gateway local_ttl_ms must be an integer")
    if not 1 <= value <= MAX_LOCAL_TTL_MS:
        raise ValueError(f"motion gateway local_ttl_ms must be between 1 and {MAX_LOCAL_TTL_MS}")
    return value


def bounded_identifier(value: str, *, fallback: str) -> str:
    clean = " ".join(str(value).split()) or fallback
    return clean[:128]


def bounded_reason(reason: str) -> str:
    clean = " ".join(str(reason).split()) or "runtime_stop"
    return clean[:160]


def sport_payload_without_age(state: MotionStateV2) -> tuple[object, ...]:
    return (
        state.boot_epoch,
        state.phase,
        state.state_sequence,
        state.lease_active,
        state.writer_id,
        state.vx_mps,
        state.vy_mps,
        state.vyaw_rad_s,
        state.stationary,
        state.last_stop_sequence,
        state.last_stop_reason,
        state.body_kind,
        state.telemetry_valid,
        state.vendor_position_m,
        state.vendor_rpy_rad,
        state.mode,
        state.error_code,
        state.source_time_s,
        state.sport_foot_force_raw,
        state.feedback_integrity_ok,
        state.feedback_integrity_reason,
    )


def low_state_payload_without_age(state: MotionStateV2) -> tuple[object, ...]:
    return (
        state.low_state_valid,
        state.low_state_sequence,
        state.commissioned_soc_ok,
        state.commissioned_soc_reason,
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
