"""A second, non-Unitree vendor adapter: the empirical portability proof.

One implementation is not proof of a portable boundary. This adapter models a
generic quadruped SDK — velocity commands tracked with a first-order lag,
periodic proprioceptive feedback, an explicit fault word, and no lease/DDS
concepts — and runs the full ``ControlManager`` contract (watchdog, TTL,
feedback-confirmed stop, latched E-stop) without a single manager edit.

It doubles as the reference for real second-vendor ports (Deep Robotics,
Spot): implement these two classes and one factory against the actual SDK,
register the factory, done.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from parcel_robot.models import VelocityCommand
from parcel_robot.safety import SafetyLimits

from .factory import _limits, _timing, register_controller_factory
from .manager import ControlManager
from .models import (
    ControllerCapabilities,
    FaultReason,
    RobotMotionState,
    TimedVelocitySetpoint,
)


class MockQuadrupedShared:
    """Thread-safe shared body state between controller and state source."""

    def __init__(self, *, tracking_lag_s: float = 0.15):
        if not math.isfinite(tracking_lag_s) or tracking_lag_s <= 0.0:
            raise ValueError("tracking lag must be positive and finite")
        self.tracking_lag_s = tracking_lag_s
        self.lock = threading.Lock()
        self.target = VelocityCommand()
        self.measured = VelocityCommand()
        self.fault = FaultReason.NONE
        self.roll = 0.0
        self.pitch = 0.0
        self.last_advanced = time.monotonic()

    def advance(self, now: float) -> None:
        """First-order velocity tracking toward the commanded target."""

        with self.lock:
            dt = max(0.0, now - self.last_advanced)
            self.last_advanced = now
            alpha = 1.0 - math.exp(-dt / self.tracking_lag_s)
            self.measured = VelocityCommand(
                vx=self.measured.vx + (self.target.vx - self.measured.vx) * alpha,
                vy=self.measured.vy + (self.target.vy - self.measured.vy) * alpha,
                vyaw=self.measured.vyaw + (self.target.vyaw - self.measured.vyaw) * alpha,
            )


class MockQuadrupedController:
    """LocomotionController for the mock vendor SDK."""

    name = "mock_quadruped"
    capabilities = ControllerCapabilities(
        body_velocity=True,
        lateral_velocity=True,
        high_level_balance=True,
        low_level_joint_control=False,
        requires_stop_confirmation=True,
    )

    def __init__(self, shared: MockQuadrupedShared):
        self._shared = shared
        self._emergency = False

    def activate(self) -> None:  # passive by contract
        return None

    def update(
        self,
        target: TimedVelocitySetpoint,
        state: RobotMotionState,
        *,
        now: float,
    ) -> None:
        del state, now
        with self._shared.lock:
            if self._emergency:
                raise RuntimeError("mock vendor rejects motion while emergency-stopped")
            self._shared.target = target.command

    def stop(self, reason: str) -> None:
        del reason
        with self._shared.lock:
            self._shared.target = VelocityCommand()

    def emergency_stop(self) -> None:
        with self._shared.lock:
            self._emergency = True
            self._shared.target = VelocityCommand()

    def clear_emergency_stop(self) -> None:
        with self._shared.lock:
            self._emergency = False

    def close(self) -> None:
        self.stop("close")


class MockQuadrupedStateSource:
    """RobotStateSource producing periodic tracked-velocity feedback."""

    name = "mock_quadruped_state"

    def __init__(self, shared: MockQuadrupedShared):
        self._shared = shared
        self._sequence = 0
        self._started = False

    def start(self) -> None:
        self._started = True

    def latest(self) -> RobotMotionState | None:
        if not self._started:
            return None
        now = time.monotonic()
        self._shared.advance(now)
        self._sequence += 1
        with self._shared.lock:
            return RobotMotionState(
                received_at=now,
                sequence=self._sequence,
                roll=self._shared.roll,
                pitch=self._shared.pitch,
                velocity=self._shared.measured,
                fault_reason=self._shared.fault,
                source=self.name,
            )

    def close(self) -> None:
        self._started = False


def build_mock_quadruped_control_manager(
    config: dict[str, Any],
    safety_limits: SafetyLimits,
) -> ControlManager:
    shared = MockQuadrupedShared(
        tracking_lag_s=float((config.get("mock_quadruped") or {}).get("tracking_lag_s", 0.15))
    )
    controller = MockQuadrupedController(shared)
    source = MockQuadrupedStateSource(shared)
    return ControlManager(
        controller,
        source,
        limits=_limits(config, safety_limits),
        timing=_timing(config),
    )


register_controller_factory("mock_quadruped", build_mock_quadruped_control_manager)
