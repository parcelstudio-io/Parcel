from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from parcel_robot.models import VelocityCommand


class ControlLifecycle(str, Enum):
    """Lifecycle of the single process allowed to command locomotion."""

    DISARMED = "disarmed"
    ARMING = "arming"
    IDLE = "idle"
    ACTIVE = "active"
    STOPPING = "stopping"
    FAULTED = "faulted"
    EMERGENCY_STOPPED = "emergency_stopped"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass(frozen=True)
class ControlLimits:
    """Last-line limits at the physical controller boundary."""

    max_vx: float = 0.6
    max_vy: float = 0.4
    max_vyaw: float = 1.0
    max_tilt_rad: float = 0.75

    def __post_init__(self) -> None:
        values = (self.max_vx, self.max_vy, self.max_vyaw, self.max_tilt_rad)
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("control limits must be positive and finite")

    def validate(self, command: VelocityCommand) -> None:
        values = (command.vx, command.vy, command.vyaw)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("controller velocity target must be finite")
        if abs(command.vx) > self.max_vx:
            raise ValueError("controller target vx exceeds the physical limit")
        if abs(command.vy) > self.max_vy:
            raise ValueError("controller target vy exceeds the physical limit")
        if abs(command.vyaw) > self.max_vyaw:
            raise ValueError("controller target vyaw exceeds the physical limit")


@dataclass(frozen=True)
class ControlTiming:
    """Timing contract shared by every locomotion controller implementation."""

    control_hz: float = 50.0
    command_timeout_s: float = 0.35
    state_timeout_s: float = 0.25
    startup_timeout_s: float = 2.0
    stop_timeout_s: float = 1.0
    stop_retry_s: float = 0.2
    io_quiesce_timeout_s: float = 2.5
    stop_settled_samples: int = 2
    settled_linear_speed_mps: float = 0.08
    settled_yaw_speed_rad_s: float = 0.12

    def __post_init__(self) -> None:
        values = (
            self.control_hz,
            self.command_timeout_s,
            self.state_timeout_s,
            self.startup_timeout_s,
            self.stop_timeout_s,
            self.stop_retry_s,
            self.io_quiesce_timeout_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("control timing values must be positive and finite")
        if (
            isinstance(self.stop_settled_samples, bool)
            or not isinstance(self.stop_settled_samples, int)
            or self.stop_settled_samples < 1
        ):
            raise ValueError("stop_settled_samples must be a positive integer")
        speeds = (self.settled_linear_speed_mps, self.settled_yaw_speed_rad_s)
        if any(not math.isfinite(value) or value < 0.0 for value in speeds):
            raise ValueError("settled speed thresholds must be finite and nonnegative")

    @property
    def period_s(self) -> float:
        return 1.0 / self.control_hz


@dataclass(frozen=True)
class TimedVelocitySetpoint:
    """A sequenced, leased velocity target in the robot body frame."""

    command: VelocityCommand
    source: str
    sequence: int
    issued_at: float
    valid_until: float
    frame: str = "base_link"

    def __post_init__(self) -> None:
        if not self.source or len(self.source) > 80:
            raise ValueError("control source must be a short non-empty string")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("control sequence must be a positive integer")
        if self.frame != "base_link":
            raise ValueError("body velocity setpoints must use the base_link frame")
        if not math.isfinite(self.issued_at) or not math.isfinite(self.valid_until):
            raise ValueError("control setpoint timestamps must be finite")
        if self.valid_until <= self.issued_at:
            raise ValueError("control setpoint deadline must follow its issue time")
        values = (self.command.vx, self.command.vy, self.command.vyaw)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("control setpoint velocity must be finite")

    def expired(self, now: float) -> bool:
        return now >= self.valid_until


@dataclass(frozen=True)
class RobotMotionState:
    """Vendor-neutral robot feedback sampled at a host monotonic timestamp.

    `velocity` is expressed in ``base_link`` even when the vendor reports
    odometry-frame velocity. A future custom controller may populate joints and
    foot forces from Unitree LowState without changing the high-level contract.
    """

    received_at: float
    sequence: int
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    velocity: VelocityCommand = field(default_factory=VelocityCommand)
    mode: int | None = None
    error_code: int = 0
    source: str = "unknown"
    joint_positions: tuple[float, ...] = ()
    joint_velocities: tuple[float, ...] = ()
    foot_forces: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.received_at):
            raise ValueError("robot state receipt timestamp must be finite")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("robot state sequence must be a positive integer")
        values = (
            *self.position,
            self.roll,
            self.pitch,
            self.yaw,
            self.velocity.vx,
            self.velocity.vy,
            self.velocity.vyaw,
            *self.joint_positions,
            *self.joint_velocities,
            *self.foot_forces,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("robot state must contain only finite values")
        if len(self.position) != 3:
            raise ValueError("robot state position must have three axes")
        if self.error_code < 0:
            raise ValueError("robot state error_code cannot be negative")
        if not self.source or len(self.source) > 80:
            raise ValueError("robot state source must be a short non-empty string")


@dataclass(frozen=True)
class ControllerCapabilities:
    """Controller features used for safe composition and future replacement."""

    body_velocity: bool = True
    lateral_velocity: bool = True
    high_level_balance: bool = True
    low_level_joint_control: bool = False
    requires_stop_confirmation: bool = True


@dataclass(frozen=True)
class ControllerStatus:
    lifecycle: ControlLifecycle
    controller: str
    target: VelocityCommand = field(default_factory=VelocityCommand)
    measured: VelocityCommand = field(default_factory=VelocityCommand)
    target_source: str | None = None
    target_sequence: int | None = None
    command_age_ms: float | None = None
    feedback_age_ms: float | None = None
    watchdog_stops: int = 0
    last_stop_reason: str = "not_started"
    fault: str | None = None
    emergency_stopped: bool = False
    stop_confirmed: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "lifecycle": self.lifecycle.value,
            "controller": self.controller,
            "target": _velocity_dict(self.target),
            "measured": _velocity_dict(self.measured),
            "tracking_error": {
                "vx": round(self.target.vx - self.measured.vx, 4),
                "vy": round(self.target.vy - self.measured.vy, 4),
                "vyaw": round(self.target.vyaw - self.measured.vyaw, 4),
            },
            "target_source": self.target_source,
            "target_sequence": self.target_sequence,
            "command_age_ms": self.command_age_ms,
            "feedback_age_ms": self.feedback_age_ms,
            "watchdog_stops": self.watchdog_stops,
            "last_stop_reason": self.last_stop_reason,
            "fault": self.fault,
            "emergency_stopped": self.emergency_stopped,
            "stop_confirmed": self.stop_confirmed,
        }


def _velocity_dict(command: VelocityCommand) -> dict[str, float]:
    return {
        "vx": round(command.vx, 4),
        "vy": round(command.vy, 4),
        "vyaw": round(command.vyaw, 4),
    }
