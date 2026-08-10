from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from parcel_robot.models import VelocityCommand
from parcel_robot.safety import SafetyLimits

from .commands import MotionIntent


@dataclass(frozen=True)
class SubmitResult:
    accepted: bool
    reason: str


def waypoints_trigger_lethal_veto(
    lethal: Callable[[float, float], bool],
    waypoints: Sequence[tuple[float, float]] | None,
) -> bool:
    """Fail-closed lethal veto for a waypoint list (P0 mixed-lethal harden).

    Empty / missing waypoints do not veto on their own (pose is checked
    separately). **Any** lethal waypoint vetoes — a mixed safe/lethal list
    must not pass (the old ``all()`` rule let mixed goals through).
    """

    if not waypoints:
        return False
    return any(lethal(float(x), float(y)) for x, y in waypoints)


class CommandArbiter:
    """The only gate through which runtime velocity commands may pass.

    Higher-priority commands temporarily own motion. Every request has a TTL so
    a dead UI, planner, or network connection naturally becomes a stop.
    """

    def __init__(self, limits: SafetyLimits | None = None):
        self.limits = limits or SafetyLimits()
        self._active: MotionIntent | None = None
        self._emergency_stopped = False
        self._lock = threading.RLock()

    @property
    def emergency_stopped(self) -> bool:
        with self._lock:
            return self._emergency_stopped

    def submit(self, intent: MotionIntent, now: float | None = None) -> SubmitResult:
        current_time = time.monotonic() if now is None else now
        violation = self._limit_violation(intent.command)
        if violation:
            return SubmitResult(False, violation)
        with self._lock:
            if self._emergency_stopped:
                return SubmitResult(False, "motion is disabled by emergency stop")
            active = self._active
            if active is not None and active.expired(current_time):
                active = None
                self._active = None
            if active is not None and intent.effective_priority < active.effective_priority:
                return SubmitResult(
                    False,
                    f"{active.source} currently owns motion at higher priority",
                )
            self._active = intent
            return SubmitResult(True, f"accepted {intent.source} motion")

    def current(self, now: float | None = None) -> MotionIntent | None:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            if self._emergency_stopped:
                return None
            if self._active is not None and self._active.expired(current_time):
                self._active = None
            return self._active

    def stop(self) -> None:
        """Cancel the current lease without engaging the persistent E-stop."""
        with self._lock:
            self._active = None

    def cancel(self, source: str) -> None:
        """Cancel one producer without disturbing a higher-priority owner."""
        with self._lock:
            if self._active is not None and self._active.source == source:
                self._active = None

    def engage_emergency_stop(self) -> None:
        with self._lock:
            self._emergency_stopped = True
            self._active = None

    def clear_emergency_stop(self) -> None:
        with self._lock:
            self._active = None
            self._emergency_stopped = False

    def snapshot(self, now: float | None = None) -> dict[str, object]:
        intent = self.current(now)
        with self._lock:
            return {
                "emergency_stopped": self._emergency_stopped,
                "active_source": intent.source if intent else None,
                "command": {
                    "vx": intent.command.vx if intent else 0.0,
                    "vy": intent.command.vy if intent else 0.0,
                    "vyaw": intent.command.vyaw if intent else 0.0,
                },
            }

    def _limit_violation(self, command: VelocityCommand) -> str | None:
        if abs(command.vx) > self.limits.max_vx:
            return "vx exceeds the configured safe limit"
        if abs(command.vy) > self.limits.max_vy:
            return "vy exceeds the configured safe limit"
        if abs(command.vyaw) > self.limits.max_vyaw:
            return "vyaw exceeds the configured safe limit"
        return None
