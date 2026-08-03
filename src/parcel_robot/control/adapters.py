from __future__ import annotations

import threading
import time
from typing import Any

from parcel_robot.models import VelocityCommand

from .models import ControllerCapabilities, RobotMotionState, TimedVelocitySetpoint


class BackendVelocityController:
    """Simulator-only compatibility controller for an existing velocity backend."""

    capabilities = ControllerCapabilities(requires_stop_confirmation=False)

    def __init__(self, backend: Any, *, refresh_s: float = 0.2) -> None:
        if refresh_s <= 0.0:
            raise ValueError("controller refresh_s must be positive")
        self.backend = backend
        self.name = f"{getattr(backend, 'name', 'backend')}_velocity"
        self.refresh_s = float(refresh_s)
        self._active = False
        self._closed = False
        self._last_command = VelocityCommand()
        self._last_send_at = 0.0
        self._stopped = True
        self._startup_stop_pending = False
        self._io_lock = threading.Lock()

    def activate(self) -> None:
        with self._io_lock:
            if self._closed:
                raise RuntimeError("controller is closed")
            self._active = True
            # Avoid aborting dashboard startup when its optional simulator
            # socket is offline. The first later actuator interaction sends a
            # stop before any move, covering a reconnected persistent backend.
            self._stopped = True
            self._startup_stop_pending = True

    def update(
        self,
        target: TimedVelocitySetpoint,
        state: RobotMotionState,
        *,
        now: float,
    ) -> None:
        del state
        with self._io_lock:
            if not self._active or self._closed:
                raise RuntimeError("controller is not active")
            command = target.command
            if self._startup_stop_pending:
                self.backend.stop()
                self._startup_stop_pending = False
                self._last_command = VelocityCommand()
                self._stopped = True
            if command == self._last_command and now - self._last_send_at < self.refresh_s:
                self._stopped = False
                return
            # Once delivery is attempted, a fail-safe stop is required even if
            # the transport raises before acknowledging the command.
            self._stopped = False
            self.backend.move(command)
            self._last_command = command
            self._last_send_at = now

    def stop(self, reason: str) -> None:
        with self._io_lock:
            if self._closed or (self._startup_stop_pending and reason == "manager_start"):
                return
            self.backend.stop()
            self._startup_stop_pending = False
            self._last_command = VelocityCommand()
            self._last_send_at = time.monotonic()
            self._stopped = True

    def emergency_stop(self) -> None:
        with self._io_lock:
            if self._closed:
                return
            emergency = getattr(self.backend, "emergency_stop", None)
            if callable(emergency):
                emergency()
            else:
                self.backend.stop()
            self._startup_stop_pending = False
            self._last_command = VelocityCommand()
            self._stopped = True

    def clear_emergency_stop(self) -> None:
        with self._io_lock:
            clear = getattr(self.backend, "clear_emergency_stop", None)
            if callable(clear):
                clear()
            self._last_command = VelocityCommand()
            self._stopped = True

    def close(self) -> None:
        with self._io_lock:
            if self._closed:
                return
            try:
                if not self._stopped:
                    self.backend.stop()
            finally:
                self._closed = True
                self._active = False
                self._stopped = True
                self._startup_stop_pending = False
