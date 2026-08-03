from __future__ import annotations

from typing import Protocol

from .models import ControllerCapabilities, RobotMotionState, TimedVelocitySetpoint


class RobotStateSource(Protocol):
    """Source of locally timestamped physical feedback.

    ``latest`` must be nonblocking and state sequence numbers must increase for
    every received sample; post-stop confirmation depends on that ordering.
    """

    name: str

    def start(self) -> None: ...

    def latest(self) -> RobotMotionState | None: ...

    def close(self) -> None: ...


class LocomotionController(Protocol):
    """Exclusive body-velocity controller owned by ``ControlManager``.

    Unitree Sport closes its fast gait/balance loop onboard. A future custom
    implementation can close a faster IMU/joint loop internally while keeping
    the same leased body-velocity input contract. Implementations must make
    ``stop`` and ``emergency_stop`` safe when an ``update`` is in flight; the
    manager invalidates that update and follows it with a compensating stop.

    ``activate`` must be passive (it must never initiate locomotion), bounded,
    and safe to follow immediately with ``stop`` or ``emergency_stop``. Every
    controller I/O method must be bounded and internally serialize access to
    its vendor transport. Those invariants let the manager latch an E-stop
    while slow activation is still returning and safely quiesce replacement
    controllers during shutdown.
    """

    name: str
    capabilities: ControllerCapabilities

    def activate(self) -> None: ...

    def update(
        self,
        target: TimedVelocitySetpoint,
        state: RobotMotionState,
        *,
        now: float,
    ) -> None: ...

    def stop(self, reason: str) -> None: ...

    def emergency_stop(self) -> None: ...

    def clear_emergency_stop(self) -> None: ...

    def close(self) -> None: ...
