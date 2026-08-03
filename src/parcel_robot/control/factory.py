from __future__ import annotations

from typing import Any

from parcel_robot.safety import SafetyLimits

from .adapters import BackendVelocityController
from .manager import ControlManager
from .models import ControlLimits, ControlTiming
from .state import BufferedRobotStateSource
from .unitree_sport import (
    UnitreeChannelContext,
    UnitreeSportController,
    UnitreeSportStateSource,
)


def build_backend_control_manager(
    backend: Any,
    config: dict[str, Any],
    safety_limits: SafetyLimits,
) -> tuple[ControlManager, BufferedRobotStateSource]:
    timing = _timing(config)
    source = BufferedRobotStateSource()
    controller = BackendVelocityController(
        backend,
        refresh_s=float(config.get("command_refresh_s", 0.2)),
    )
    manager = ControlManager(
        controller,
        source,
        limits=_limits(config, safety_limits),
        timing=timing,
    )
    return manager, source


def build_unitree_sport_control_manager(
    config: dict[str, Any],
    safety_limits: SafetyLimits,
) -> ControlManager:
    """Build a hardware manager without importing Unitree SDK until start()."""

    timing = _timing(config)
    sport = config.get("unitree_sport") or {}
    if not isinstance(sport, dict):
        raise TypeError("control.unitree_sport must be a mapping")
    domain_id = int(sport.get("domain_id", 0))
    interface = str(sport.get("interface", "enp3s0"))
    channel = UnitreeChannelContext(domain_id, interface)
    lateral_sign = int(sport.get("lateral_sign", 1))
    yaw_sign = int(sport.get("yaw_sign", 1))
    if sport.get("enable_lease") is not True:
        raise ValueError("control.unitree_sport.enable_lease must be true for physical control")
    if sport.get("axes_commissioned") is not True:
        raise ValueError(
            "control.unitree_sport.axes_commissioned must be true after sign verification"
        )
    if sport.get("state_frame_commissioned") is not True:
        raise ValueError(
            "control.unitree_sport.state_frame_commissioned must be true after frame verification"
        )
    state_source = UnitreeSportStateSource(
        channel,
        topic=str(sport.get("state_topic", "rt/sportmodestate")),
        velocity_frame=str(sport.get("state_velocity_frame", "odom")),
        lateral_sign=lateral_sign,
        yaw_sign=yaw_sign,
    )
    raw_allowed_modes = sport.get("allowed_modes", [])
    if not isinstance(raw_allowed_modes, list):
        raise TypeError("control.unitree_sport.allowed_modes must be a list")
    if not raw_allowed_modes:
        raise ValueError("control.unitree_sport.allowed_modes must be explicitly commissioned")
    if any(isinstance(mode, bool) or not isinstance(mode, int) for mode in raw_allowed_modes):
        raise TypeError("control.unitree_sport.allowed_modes must contain integers")
    rpc_timeout_s = float(sport.get("rpc_timeout_s", 0.2))
    if rpc_timeout_s > min(timing.stop_retry_s, timing.stop_timeout_s):
        raise ValueError("Unitree rpc_timeout_s cannot exceed the stop retry/confirmation deadline")
    lease_acquire_timeout_s = float(sport.get("lease_acquire_timeout_s", 2.0))
    if lease_acquire_timeout_s > timing.io_quiesce_timeout_s:
        raise ValueError(
            "Unitree lease_acquire_timeout_s cannot exceed control.io_quiesce_timeout_s"
        )
    controller = UnitreeSportController(
        channel,
        rpc_timeout_s=rpc_timeout_s,
        refresh_s=float(sport.get("command_refresh_s", 0.1)),
        enable_lease=True,
        lease_acquire_timeout_s=lease_acquire_timeout_s,
        lateral_sign=lateral_sign,
        yaw_sign=yaw_sign,
        allowed_modes=tuple(raw_allowed_modes),
    )
    return ControlManager(
        controller,
        state_source,
        limits=_limits(config, safety_limits),
        timing=timing,
    )


def _timing(config: dict[str, Any]) -> ControlTiming:
    stop_settled_samples = config.get("stop_settled_samples", 2)
    if isinstance(stop_settled_samples, bool) or not isinstance(stop_settled_samples, int):
        raise TypeError("control.stop_settled_samples must be an integer")
    return ControlTiming(
        control_hz=float(config.get("control_hz", 50.0)),
        command_timeout_s=float(config.get("command_timeout_s", 0.35)),
        state_timeout_s=float(config.get("state_timeout_s", 0.25)),
        startup_timeout_s=float(config.get("startup_timeout_s", 2.0)),
        stop_timeout_s=float(config.get("stop_timeout_s", 1.0)),
        stop_retry_s=float(config.get("stop_retry_s", 0.2)),
        io_quiesce_timeout_s=float(config.get("io_quiesce_timeout_s", 2.5)),
        stop_settled_samples=stop_settled_samples,
        settled_linear_speed_mps=float(config.get("settled_linear_speed_mps", 0.08)),
        settled_yaw_speed_rad_s=float(config.get("settled_yaw_speed_rad_s", 0.12)),
    )


def _limits(config: dict[str, Any], fallback: SafetyLimits) -> ControlLimits:
    return ControlLimits(
        max_vx=float(config.get("max_vx", fallback.max_vx)),
        max_vy=float(config.get("max_vy", fallback.max_vy)),
        max_vyaw=float(config.get("max_vyaw", fallback.max_vyaw)),
        max_tilt_rad=float(config.get("max_tilt_rad", 0.75)),
    )
