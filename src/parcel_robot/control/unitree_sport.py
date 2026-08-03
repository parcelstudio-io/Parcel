from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from parcel_robot.models import VelocityCommand

from .models import ControllerCapabilities, RobotMotionState, TimedVelocitySetpoint

_CHANNEL_FACTORY_LOCK = threading.Lock()
_CHANNEL_FACTORY_CONFIG: tuple[int, str] | None = None
_PROCESS_LEASE_LOCK = threading.Lock()
_PROCESS_LEASE_CLAIMED = False


class UnitreeChannelContext:
    """Initialize the process-global Unitree DDS channel exactly once."""

    def __init__(
        self,
        domain_id: int,
        interface: str,
        initializer: Callable[[int, str], Any] | None = None,
    ) -> None:
        if domain_id < 0:
            raise ValueError("Unitree DDS domain_id cannot be negative")
        if not interface.strip():
            raise ValueError("Unitree network interface cannot be empty")
        self.domain_id = int(domain_id)
        self.interface = interface.strip()
        self._initializer = initializer
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> None:
        global _CHANNEL_FACTORY_CONFIG

        with self._lock:
            if self._initialized:
                return
            initializer = self._initializer
            if initializer is not None:
                initializer(self.domain_id, self.interface)
                self._initialized = True
                return
            if not (Path("/sys/class/net") / self.interface).is_dir():
                raise RuntimeError(
                    f"Unitree network interface {self.interface!r} does not exist on this host"
                )
            try:
                from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            except ImportError as error:
                raise RuntimeError(
                    "unitree_sdk2py is required for the Unitree Sport controller"
                ) from error
            requested = (self.domain_id, self.interface)
            with _CHANNEL_FACTORY_LOCK:
                if _CHANNEL_FACTORY_CONFIG is None:
                    ChannelFactoryInitialize(*requested)
                    _CHANNEL_FACTORY_CONFIG = requested
                elif _CHANNEL_FACTORY_CONFIG != requested:
                    raise RuntimeError(
                        "Unitree DDS is already initialized for "
                        f"domain/interface {_CHANNEL_FACTORY_CONFIG!r}; refusing "
                        f"conflicting configuration {requested!r}"
                    )
            self._initialized = True


class UnitreeSportStateSource:
    """Subscribe to SportModeState and expose body-frame feedback."""

    name = "unitree_sport_state"

    def __init__(
        self,
        channel: UnitreeChannelContext,
        *,
        topic: str = "rt/sportmodestate",
        subscriber_factory: Callable[[str, Any], Any] | None = None,
        message_type: Any = None,
        velocity_frame: str = "odom",
        lateral_sign: int = 1,
        yaw_sign: int = 1,
        clock=time.monotonic,
    ) -> None:
        if not topic.strip():
            raise ValueError("Unitree Sport state topic cannot be empty")
        self.channel = channel
        self.topic = topic.strip()
        self._subscriber_factory = subscriber_factory
        self._message_type = message_type
        if velocity_frame not in {"odom", "base_link"}:
            raise ValueError("Unitree velocity_frame must be odom or base_link")
        self.velocity_frame = velocity_frame
        self.lateral_sign = _axis_sign(lateral_sign, "lateral_sign")
        self.yaw_sign = _axis_sign(yaw_sign, "yaw_sign")
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: RobotMotionState | None = None
        self._subscriber: Any = None
        self._sequence = 0
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Unitree state source is closed")
            if self._subscriber is not None:
                return
        self.channel.initialize()
        factory = self._subscriber_factory
        message_type = self._message_type
        if factory is None or message_type is None:
            try:
                from unitree_sdk2py.core.channel import ChannelSubscriber
                from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
            except ImportError as error:
                raise RuntimeError(
                    "unitree_sdk2py SportModeState support is unavailable"
                ) from error
            factory = factory or ChannelSubscriber
            message_type = message_type or SportModeState_
        subscriber = factory(self.topic, message_type)
        subscriber.Init(self._on_message, 1)
        with self._lock:
            if self._closed:
                return
            self._subscriber = subscriber

    def latest(self) -> RobotMotionState | None:
        with self._lock:
            return self._latest

    def close(self) -> None:
        with self._lock:
            self._closed = True
            subscriber = self._subscriber
            self._subscriber = None
            self._latest = None
        close = getattr(subscriber, "Close", None) or getattr(subscriber, "CloseChannel", None)
        if callable(close):
            close()

    def _on_message(self, message: Any) -> None:
        received_at = float(self._clock())
        position = _float_tuple(message.position, 3, "position")
        odom_velocity = _float_tuple(message.velocity, 3, "velocity")
        imu = message.imu_state
        rpy = _float_tuple(imu.rpy, 3, "imu_state.rpy")
        yaw = rpy[2]
        if self.velocity_frame == "odom":
            cosine = math.cos(yaw)
            sine = math.sin(yaw)
            body_vx = cosine * odom_velocity[0] + sine * odom_velocity[1]
            body_vy = -sine * odom_velocity[0] + cosine * odom_velocity[1]
        else:
            body_vx = odom_velocity[0]
            body_vy = odom_velocity[1]
        body_velocity = VelocityCommand(
            vx=body_vx,
            vy=self.lateral_sign * body_vy,
            vyaw=self.yaw_sign * float(message.yaw_speed),
        )
        foot_forces = tuple(float(value) for value in message.foot_force)
        with self._lock:
            if self._closed:
                return
            self._sequence += 1
            state = RobotMotionState(
                received_at=received_at,
                sequence=self._sequence,
                position=position,
                roll=rpy[0],
                pitch=rpy[1],
                yaw=yaw,
                velocity=body_velocity,
                mode=int(message.mode),
                error_code=int(message.error_code),
                source="unitree_sport",
                foot_forces=foot_forces,
            )
            self._latest = state


class UnitreeSportController:
    """High-level Unitree controller with feedback supervised by ControlManager.

    ``Move`` supplies a body-velocity setpoint to Unitree's onboard closed-loop
    balance and gait controller. Its return value is only a transport result;
    actual movement is observed through ``SportModeState``.

    The official Python lease client cannot release or stop its renewal thread.
    Real SDK activation is therefore one-shot per OS process; replacing this
    driver requires terminating its dedicated process.
    """

    name = "unitree_sport"
    capabilities = ControllerCapabilities(
        body_velocity=True,
        lateral_velocity=True,
        high_level_balance=True,
        low_level_joint_control=False,
    )

    def __init__(
        self,
        channel: UnitreeChannelContext,
        *,
        rpc_timeout_s: float = 0.2,
        refresh_s: float = 0.1,
        enable_lease: bool = True,
        lease_acquire_timeout_s: float = 2.0,
        lateral_sign: int = 1,
        yaw_sign: int = 1,
        allowed_modes: tuple[int, ...],
        client_factory: Callable[..., Any] | None = None,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        if not math.isfinite(rpc_timeout_s) or rpc_timeout_s <= 0.0:
            raise ValueError("Unitree RPC timeout must be positive and finite")
        if not math.isfinite(refresh_s) or refresh_s <= 0.0:
            raise ValueError("Unitree command refresh must be positive and finite")
        if not math.isfinite(lease_acquire_timeout_s) or lease_acquire_timeout_s <= 0.0:
            raise ValueError("Unitree lease timeout must be positive and finite")
        self.channel = channel
        self.rpc_timeout_s = float(rpc_timeout_s)
        self.refresh_s = float(refresh_s)
        self.enable_lease = bool(enable_lease)
        self.lease_acquire_timeout_s = float(lease_acquire_timeout_s)
        self.lateral_sign = _axis_sign(lateral_sign, "lateral_sign")
        self.yaw_sign = _axis_sign(yaw_sign, "yaw_sign")
        if any(isinstance(mode, bool) or not isinstance(mode, int) for mode in allowed_modes):
            raise TypeError("Unitree allowed_modes must contain integers")
        self.allowed_modes = frozenset(allowed_modes)
        if not self.allowed_modes:
            raise ValueError("Unitree allowed_modes must be explicitly commissioned")
        if any(mode < 0 or mode > 255 for mode in self.allowed_modes):
            raise ValueError("Unitree allowed_modes must contain byte-sized integers")
        self._client_factory = client_factory
        self._clock = clock
        self._sleeper = sleeper
        self._io_lock = threading.Lock()
        self._client: Any = None
        self._lease_id_getter: Callable[[], Any] | None = None
        self._active = False
        self._closed = False
        self._emergency_stopped = False
        self._last_command = VelocityCommand()
        self._last_send_at = 0.0
        self._stop_required = False

    def activate(self) -> None:
        global _PROCESS_LEASE_CLAIMED

        if self._closed:
            raise RuntimeError("Unitree Sport controller is closed")
        if self._active:
            return
        self.channel.initialize()
        factory = self._client_factory
        if factory is None:
            try:
                from unitree_sdk2py.go2.sport.sport_client import SportClient
            except ImportError as error:
                raise RuntimeError("unitree_sdk2py SportClient is unavailable") from error
            factory = SportClient
        if self.enable_lease and self._client_factory is None:
            with _PROCESS_LEASE_LOCK:
                if _PROCESS_LEASE_CLAIMED:
                    raise RuntimeError(
                        "Unitree Sport lease is process-lifetime; restart the dedicated "
                        "control process before activating another controller"
                    )
                _PROCESS_LEASE_CLAIMED = True
        client = factory(enableLease=self.enable_lease)
        client.SetTimeout(self.rpc_timeout_s)
        client.Init()
        if self.enable_lease:
            get_lease_id = getattr(client, "GetLeaseId", None)
            if not callable(get_lease_id):
                raise RuntimeError("Unitree Sport client does not expose lease state")
            self._lease_id_getter = get_lease_id
            deadline = self._clock() + self.lease_acquire_timeout_s
            while not get_lease_id():
                remaining = deadline - self._clock()
                if remaining <= 0.0:
                    raise RuntimeError("Unitree Sport lease was not acquired before timeout")
                self._sleeper(min(0.05, remaining))
        self._client = client
        self._active = True

    def update(
        self,
        target: TimedVelocitySetpoint,
        state: RobotMotionState,
        *,
        now: float,
    ) -> None:
        if not self._active or self._closed or self._client is None:
            raise RuntimeError("Unitree Sport controller is not active")
        if self._emergency_stopped:
            raise RuntimeError("Unitree Sport controller emergency stop is latched")
        self._require_active_lease()
        if state.mode not in self.allowed_modes:
            raise RuntimeError(f"Unitree Sport mode {state.mode} is not allowed for movement")
        command = target.command
        if command == self._last_command and now - self._last_send_at < self.refresh_s:
            return
        # Move is a no-reply SDK operation. Treat every delivery attempt as
        # potentially applied, so an error path still forces StopMove.
        with self._io_lock:
            if self._emergency_stopped:
                raise RuntimeError("Unitree Sport controller emergency stop is latched")
            self._require_active_lease()
            self._stop_required = True
            code = self._client.Move(
                float(command.vx),
                float(self.lateral_sign * command.vy),
                float(self.yaw_sign * command.vyaw),
            )
            if code not in (None, 0):
                raise RuntimeError(f"Unitree Move transport failed with code {code}")
            self._last_command = command
            self._last_send_at = now

    def stop(self, reason: str) -> None:
        del reason
        if not self._active or self._client is None or self._closed:
            return
        with self._io_lock:
            code = self._client.StopMove()
            if code not in (None, 0):
                raise RuntimeError(f"Unitree StopMove failed with code {code}")
            self._last_command = VelocityCommand()
            self._stop_required = False

    def emergency_stop(self) -> None:
        if self._closed or self._emergency_stopped:
            return
        self._emergency_stopped = True
        self.stop("emergency_stop")

    def clear_emergency_stop(self) -> None:
        if self._closed:
            raise RuntimeError("Unitree Sport controller is closed")
        with self._io_lock:
            self._emergency_stopped = False
            self._last_command = VelocityCommand()

    def close(self) -> None:
        if self._closed:
            return
        try:
            # ControlManager normally delivered and confirmed the final stop.
            # Avoid emitting another unobservable StopMove after its feedback
            # loop has ended. Direct users still get a fail-safe stop if this
            # instance may have sent motion.
            if self._stop_required:
                self.stop("controller_closed")
        finally:
            self._closed = True
            self._active = False
            self._client = None

    def _require_active_lease(self) -> None:
        if not self.enable_lease:
            return
        get_lease_id = self._lease_id_getter
        if get_lease_id is None or not get_lease_id():
            raise RuntimeError("Unitree Sport lease was lost; movement is suppressed")


def _float_tuple(value: Any, length: int, field: str) -> tuple[float, ...]:
    result = tuple(float(item) for item in value)
    if len(result) != length or any(not math.isfinite(item) for item in result):
        raise ValueError(f"Unitree {field} must contain {length} finite values")
    return result


def _axis_sign(value: int, field: str) -> int:
    if isinstance(value, bool) or int(value) not in {-1, 1}:
        raise ValueError(f"Unitree {field} must be -1 or 1")
    return int(value)
