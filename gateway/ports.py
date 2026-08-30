"""The sole vendor-facing port, including the optional Unitree SDK2 binding.

The core reaches a robot only through the small structural :class:`SportPort`
below.  The desktop fake satisfies it by shape.  The physical binding in this
module loads SDK2 lazily, only after a ``vendor`` launch has supplied an
explicit NIC, DDS domain and commissioned frame/axis mapping.  Importing the
gateway, or selecting the fake, therefore never imports a vendor package.

SDK2's channel factory is a process singleton and its lease client identifies
itself by host/process.  :class:`UnitreeSdk2SportPortV1` mirrors that fact with
a process-lifetime authority claim: a second physical port is refused even
after ``close()``.  The gateway core remains the only owner of local writer
identity, TTL, stop epoch and stop dominance; this adapter exposes only
``Move``, ``StopMove`` and read-only SportModeState mapping.
"""

from __future__ import annotations

import importlib
import math
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import parcel_robot.bridge.unitree_writer_lock as _unitree_writer_lock

from .limits import STATE_TIMEOUT_S, STOP_RETRY_S

UNITREE_WRITER_LOCK_MODE = _unitree_writer_lock.UNITREE_WRITER_LOCK_MODE
UNITREE_WRITER_LOCK_PATH = _unitree_writer_lock.UNITREE_WRITER_LOCK_PATH
UnitreeWriterLockV1 = _unitree_writer_lock.UnitreeWriterLockV1


class SportStateLike(Protocol):
    """One high-level feedback sample as the vendor reports it."""

    sequence: int
    received_at_monotonic_s: float
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    lease_active: bool


class SportPort(Protocol):
    """The whole vendor surface the gateway is allowed to touch."""

    def acquire_writer(self, writer_id: str) -> bool: ...

    def release_writer(self, writer_id: str | None) -> None: ...

    def move(self, *, writer_id: str, vx_mps: float, vy_mps: float, vyaw_rad_s: float) -> None: ...

    def stop_move(self, *, reason: str) -> bool: ...

    def state(self) -> SportStateLike: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class UnitreeLowStateSampleV1:
    """Raw, timestamped Go2 LowState health evidence.

    Unitree's public IDL defines the containers but does not document physical
    units for the temperature/NTC bytes, ``lost`` counters, or foot-force
    counts.  Their names therefore retain ``raw`` and no threshold verdict is
    derived here.  Host receipt time is the only freshness clock.
    """

    sequence: int
    received_at_monotonic_s: float
    tick: int
    battery_soc_percent: int
    power_v: float
    power_a: float
    max_motor_temperature_raw: int
    motor_lost_max_raw: int
    foot_force_est_raw: tuple[int, int, int, int]
    imu_temperature_raw: int
    temperature_ntc_raw: tuple[int, int]
    bms_status: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise ValueError("low-state sequence must be a positive integer")
        if (
            isinstance(self.received_at_monotonic_s, bool)
            or not isinstance(self.received_at_monotonic_s, (int, float))
            or not math.isfinite(float(self.received_at_monotonic_s))
        ):
            raise ValueError("low-state receipt time must be finite")
        if (
            isinstance(self.tick, bool)
            or not isinstance(self.tick, int)
            or not 0 <= self.tick < 1 << 32
        ):
            raise ValueError("low-state tick must be an unsigned 32-bit integer")
        if (
            isinstance(self.battery_soc_percent, bool)
            or not isinstance(self.battery_soc_percent, int)
            or not 0 <= self.battery_soc_percent <= 100
        ):
            raise ValueError("low-state battery SOC must be an integer in [0, 100]")
        for name in ("power_v", "power_a"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"low-state {name} must be finite")
        for name in (
            "max_motor_temperature_raw",
            "imu_temperature_raw",
            "bms_status",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
                raise ValueError(f"low-state {name} must be an unsigned byte")
        if (
            isinstance(self.motor_lost_max_raw, bool)
            or not isinstance(self.motor_lost_max_raw, int)
            or not 0 <= self.motor_lost_max_raw < 1 << 32
        ):
            raise ValueError("low-state motor_lost_max_raw must be an unsigned 32-bit integer")
        if not isinstance(self.foot_force_est_raw, tuple) or len(self.foot_force_est_raw) != 4:
            raise ValueError("low-state foot_force_est_raw must be a 4-tuple")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not -(1 << 15) <= value < (1 << 15)
            for value in self.foot_force_est_raw
        ):
            raise ValueError("low-state foot_force_est_raw must contain signed int16 values")
        if not isinstance(self.temperature_ntc_raw, tuple) or len(self.temperature_ntc_raw) != 2:
            raise ValueError("low-state temperature_ntc_raw must be a 2-tuple")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255
            for value in self.temperature_ntc_raw
        ):
            raise ValueError("low-state temperature_ntc_raw must contain unsigned bytes")


@dataclass(frozen=True)
class SportSampleV1:
    """A validated copy of one vendor sample.

    The gateway never holds a live vendor object across a lock boundary: it
    copies the fields it is allowed to reason about and validates them at
    the copy.  A vendor that returns a bool where a float belongs, a NaN
    velocity, or a non-monotonic receipt stamp fails *here*, closed, instead of
    silently becoming positive authority.
    """

    sequence: int
    received_at_monotonic_s: float
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    lease_active: bool
    telemetry_valid: bool = False
    vendor_position_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    vendor_rpy_rad: tuple[float, float, float] = (0.0, 0.0, 0.0)
    mode: int = 0
    error_code: int = 0
    source_time_s: float | None = None
    sport_foot_force_raw: tuple[int, int, int, int] = (0, 0, 0, 0)
    low_state: UnitreeLowStateSampleV1 | None = None
    feedback_integrity_ok: bool = True
    feedback_integrity_reason: str = "ok"
    commissioned_soc_ok: bool | None = None
    commissioned_soc_reason: str = "commissioned_soc_unavailable"

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sport sample sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("sport sample sequence must be non-negative")
        for name in ("received_at_monotonic_s", "vx_mps", "vy_mps", "vyaw_rad_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"sport sample {name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"sport sample {name} must be finite")
        if not isinstance(self.lease_active, bool):
            raise TypeError("sport sample lease_active must be a boolean")
        if not isinstance(self.telemetry_valid, bool):
            raise TypeError("sport sample telemetry_valid must be a boolean")
        for name in ("vendor_position_m", "vendor_rpy_rad"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) != 3:
                raise ValueError(f"sport sample {name} must be a 3-tuple")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in values
            ):
                raise ValueError(f"sport sample {name} must contain finite numbers")
        if (
            isinstance(self.mode, bool)
            or not isinstance(self.mode, int)
            or not 0 <= self.mode <= 255
        ):
            raise ValueError("sport sample mode must be an integer in [0, 255]")
        if (
            isinstance(self.error_code, bool)
            or not isinstance(self.error_code, int)
            or not 0 <= self.error_code < 1 << 32
        ):
            raise ValueError("sport sample error_code must be an unsigned 32-bit integer")
        if self.source_time_s is not None and (
            isinstance(self.source_time_s, bool)
            or not isinstance(self.source_time_s, (int, float))
            or not math.isfinite(float(self.source_time_s))
        ):
            raise ValueError("sport sample source_time_s must be finite when present")
        if not isinstance(self.sport_foot_force_raw, tuple) or len(self.sport_foot_force_raw) != 4:
            raise ValueError("sport sample sport_foot_force_raw must be a 4-tuple")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not -(1 << 15) <= value < (1 << 15)
            for value in self.sport_foot_force_raw
        ):
            raise ValueError("sport sample sport_foot_force_raw must contain signed int16 values")
        if self.low_state is not None and not isinstance(
            self.low_state,
            UnitreeLowStateSampleV1,
        ):
            raise TypeError("sport sample low_state must be UnitreeLowStateSampleV1 or None")
        if not isinstance(self.feedback_integrity_ok, bool):
            raise TypeError("sport sample feedback_integrity_ok must be a boolean")
        if (
            not isinstance(self.feedback_integrity_reason, str)
            or not self.feedback_integrity_reason
            or len(self.feedback_integrity_reason) > 160
        ):
            raise ValueError("sport sample feedback_integrity_reason must be a short string")
        if self.feedback_integrity_ok is not (self.feedback_integrity_reason == "ok"):
            raise ValueError("sport sample feedback integrity verdict and reason disagree")
        if self.commissioned_soc_ok is not None and not isinstance(
            self.commissioned_soc_ok,
            bool,
        ):
            raise TypeError("sport sample commissioned_soc_ok must be boolean or None")
        if (
            not isinstance(self.commissioned_soc_reason, str)
            or not self.commissioned_soc_reason
            or len(self.commissioned_soc_reason) > 160
        ):
            raise ValueError("sport sample commissioned_soc_reason must be a short string")
        expected_soc_reason = {
            True: "soc_above_commissioned_minimum",
            False: "soc_at_or_below_commissioned_minimum",
            None: "commissioned_soc_unavailable",
        }[self.commissioned_soc_ok]
        if self.commissioned_soc_reason != expected_soc_reason:
            raise ValueError("sport sample commissioned SOC verdict and reason disagree")
        if self.low_state is None:
            if (
                self.commissioned_soc_ok is not None
                or self.commissioned_soc_reason != "commissioned_soc_unavailable"
            ):
                raise ValueError("sport sample SOC gate must be unavailable without fresh LowState")
        elif self.commissioned_soc_ok is None:
            raise ValueError("fresh LowState requires a commissioned SOC verdict")

    @property
    def max_abs_velocity(self) -> float:
        return max(abs(self.vx_mps), abs(self.vy_mps), abs(self.vyaw_rad_s))


def read_sport_sample(port: SportPort) -> SportSampleV1:
    """Copy and validate one vendor sample. Never returns a partial view."""

    raw = port.state()
    missing = [
        name
        for name in (
            "sequence",
            "received_at_monotonic_s",
            "vx_mps",
            "vy_mps",
            "vyaw_rad_s",
            "lease_active",
        )
        if not hasattr(raw, name)
    ]
    if missing:
        raise TypeError(f"sport state is missing required fields: {sorted(missing)}")
    return SportSampleV1(
        sequence=raw.sequence,
        # Preserve the vendor object's runtime types for SportSampleV1's
        # strict validator. Coercing here would turn bools and numeric strings
        # into apparently valid physical evidence.
        received_at_monotonic_s=raw.received_at_monotonic_s,
        vx_mps=raw.vx_mps,
        vy_mps=raw.vy_mps,
        vyaw_rad_s=raw.vyaw_rad_s,
        lease_active=raw.lease_active,
        telemetry_valid=getattr(raw, "telemetry_valid", False),
        vendor_position_m=getattr(raw, "vendor_position_m", (0.0, 0.0, 0.0)),
        vendor_rpy_rad=getattr(raw, "vendor_rpy_rad", (0.0, 0.0, 0.0)),
        mode=getattr(raw, "mode", 0),
        error_code=getattr(raw, "error_code", 0),
        source_time_s=getattr(raw, "source_time_s", None),
        sport_foot_force_raw=getattr(raw, "sport_foot_force_raw", (0, 0, 0, 0)),
        low_state=getattr(raw, "low_state", None),
        feedback_integrity_ok=getattr(raw, "feedback_integrity_ok", True),
        feedback_integrity_reason=getattr(raw, "feedback_integrity_reason", "ok"),
        commissioned_soc_ok=getattr(raw, "commissioned_soc_ok", None),
        commissioned_soc_reason=getattr(
            raw,
            "commissioned_soc_reason",
            "commissioned_soc_unavailable",
        ),
    )


class UnitreeSportError(RuntimeError):
    """Base class for fail-closed physical-port failures."""


class UnitreeSdkUnavailableError(UnitreeSportError):
    """The optional SDK2 package or one of its expected symbols is absent."""


class UnitreeAuthorityError(UnitreeSportError):
    """A second SDK2 writer was requested in the same process."""


class UnitreeStateError(UnitreeSportError):
    """SportModeState cannot provide valid motion evidence."""


@dataclass(frozen=True)
class UnitreeSportConfigV1:
    """Explicit physical configuration; no frame or sign is inferred.

    ``state_velocity_frame`` is either ``"base_link"`` (the first two velocity
    fields are already robot-relative) or ``"odom"`` (they are rotated into
    the robot body frame using IMU yaw).  ``lateral_sign`` and ``yaw_sign``
    map the gateway's canonical left-positive/CCW-positive convention to the
    commissioned SDK convention in both directions.
    """

    interface: str
    domain_id: int
    allowed_modes: tuple[int, ...]
    allowed_error_codes: tuple[int, ...]
    state_velocity_frame: str
    lateral_sign: int
    yaw_sign: int
    axes_commissioned: bool
    state_frame_commissioned: bool
    sport_state_stamp_monotonic_commissioned: bool = False
    battery_soc_percent_commissioned: bool = False
    minimum_battery_soc_percent: int = 8
    low_state_tick_monotonic_commissioned: bool = False
    state_topic: str = "rt/sportmodestate"
    low_state_topic: str = "rt/lowstate"
    rpc_timeout_s: float = 0.2
    startup_timeout_s: float = 2.0
    subscriber_queue_depth: int = 0

    def __post_init__(self) -> None:
        interface = self.interface.strip() if isinstance(self.interface, str) else ""
        if (
            not interface
            or interface != self.interface
            or len(interface) > 15
            or any(character.isspace() or character in "/\x00" for character in interface)
        ):
            raise ValueError("Unitree interface must be an explicit Linux NIC name")
        if (
            isinstance(self.domain_id, bool)
            or not isinstance(self.domain_id, int)
            or not 0 <= self.domain_id <= 232
        ):
            raise ValueError("Unitree DDS domain_id must be an integer in [0, 232]")
        try:
            modes = tuple(self.allowed_modes)
        except TypeError as exc:
            raise TypeError("Unitree allowed_modes must be an iterable of integers") from exc
        if not modes:
            raise ValueError("Unitree allowed_modes must name at least one commissioned mode")
        if any(
            isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 255
            for mode in modes
        ):
            raise ValueError("Unitree allowed_modes entries must be integers in [0, 255]")
        if len(set(modes)) != len(modes):
            raise ValueError("Unitree allowed_modes must not contain duplicates")
        object.__setattr__(self, "allowed_modes", modes)
        try:
            error_codes = tuple(self.allowed_error_codes)
        except TypeError as exc:
            raise TypeError("Unitree allowed_error_codes must be an iterable of integers") from exc
        if not error_codes:
            raise ValueError("Unitree allowed_error_codes must name commissioned values")
        if any(
            isinstance(code, bool) or not isinstance(code, int) or not 0 <= code < 1 << 32
            for code in error_codes
        ):
            raise ValueError("Unitree allowed_error_codes entries must be unsigned 32-bit integers")
        if len(set(error_codes)) != len(error_codes):
            raise ValueError("Unitree allowed_error_codes must not contain duplicates")
        object.__setattr__(self, "allowed_error_codes", error_codes)
        if self.state_velocity_frame not in {"base_link", "odom"}:
            raise ValueError("Unitree state_velocity_frame must be 'base_link' or 'odom'")
        for name in ("lateral_sign", "yaw_sign"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value not in {-1, 1}:
                raise ValueError(f"Unitree {name} must be exactly -1 or 1")
        if self.axes_commissioned is not True:
            raise ValueError("Unitree axes_commissioned must be explicitly true")
        if self.state_frame_commissioned is not True:
            raise ValueError("Unitree state_frame_commissioned must be explicitly true")
        if self.sport_state_stamp_monotonic_commissioned is not True:
            raise ValueError(
                "Unitree sport_state_stamp_monotonic_commissioned must be explicitly true "
                "after hardware validation"
            )
        if self.battery_soc_percent_commissioned is not True:
            raise ValueError(
                "Unitree battery_soc_percent_commissioned must be explicitly true after "
                "hardware validation"
            )
        if (
            isinstance(self.minimum_battery_soc_percent, bool)
            or not isinstance(self.minimum_battery_soc_percent, int)
            or not 1 <= self.minimum_battery_soc_percent <= 99
        ):
            raise ValueError("Unitree minimum_battery_soc_percent must be in [1, 99]")
        if self.low_state_tick_monotonic_commissioned is not True:
            raise ValueError(
                "Unitree low_state_tick_monotonic_commissioned must be explicitly true "
                "after hardware validation"
            )
        for name in ("state_topic", "low_state_topic"):
            topic = getattr(self, name)
            if (
                not isinstance(topic, str)
                or not topic.startswith("rt/")
                or topic.strip() != topic
                or any(character.isspace() or character == "\x00" for character in topic)
            ):
                raise ValueError(f"Unitree {name} must be an explicit rt/... DDS topic")
        if self.low_state_topic == self.state_topic:
            raise ValueError("Unitree state_topic and low_state_topic must be distinct")
        for name in ("rpc_timeout_s", "startup_timeout_s"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value <= 0.0
            ):
                raise ValueError(f"Unitree {name} must be finite and positive")
        if self.rpc_timeout_s > self.startup_timeout_s:
            raise ValueError("Unitree rpc_timeout_s must not exceed startup_timeout_s")
        if self.rpc_timeout_s > STOP_RETRY_S:
            raise ValueError(
                f"Unitree rpc_timeout_s must not exceed the {STOP_RETRY_S:g}s stop retry budget"
            )
        if self.startup_timeout_s > 10.0:
            raise ValueError("Unitree startup_timeout_s must not exceed 10 seconds")
        if (
            isinstance(self.subscriber_queue_depth, bool)
            or not isinstance(self.subscriber_queue_depth, int)
            or self.subscriber_queue_depth != 0
        ):
            raise ValueError(
                "Unitree subscriber_queue_depth must be exactly 0 so SDK FIFO backlog "
                "cannot masquerade as fresh feedback"
            )


@dataclass(frozen=True)
class UnitreeSdkBindingsV1:
    """The five SDK symbols used by the port, injectable for desktop tests."""

    channel_factory_initialize: Callable[[int, str], object]
    subscriber_factory: Callable[[str, object], object]
    sport_client_factory: Callable[..., object]
    sport_mode_state_type: object
    low_state_type: object


def load_unitree_sdk_bindings() -> UnitreeSdkBindingsV1:
    """Load official SDK2 symbols only for an explicitly selected vendor body."""

    try:
        channel_module = importlib.import_module("unitree_sdk2py.core.channel")
        sport_module = importlib.import_module("unitree_sdk2py.go2.sport.sport_client")
        state_module = importlib.import_module("unitree_sdk2py.idl.unitree_go.msg.dds_")
        return UnitreeSdkBindingsV1(
            channel_factory_initialize=channel_module.ChannelFactoryInitialize,
            subscriber_factory=channel_module.ChannelSubscriber,
            sport_client_factory=sport_module.SportClient,
            sport_mode_state_type=state_module.SportModeState_,
            low_state_type=state_module.LowState_,
        )
    except Exception as exc:
        raise UnitreeSdkUnavailableError(
            "Unitree SDK2 Python is unavailable or incompatible; install the official "
            "unitree_sdk2_python package in the gateway venv"
        ) from exc


class _UnitreeProcessAuthorityV1:
    """One irreversible physical-port claim for SDK2's process singleton."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claimed = False

    def claim(self) -> None:
        with self._lock:
            if self._claimed:
                raise UnitreeAuthorityError(
                    "Unitree SDK2 physical authority is already claimed in this process"
                )
            self._claimed = True


_UNITREE_PROCESS_AUTHORITY = _UnitreeProcessAuthorityV1()


@dataclass(frozen=True)
class _DecodedUnitreeStateV1:
    sequence: int
    received_at_monotonic_s: float
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    vendor_position_m: tuple[float, float, float]
    vendor_rpy_rad: tuple[float, float, float]
    mode: int
    error_code: int
    source_time_s: float | None
    sport_foot_force_raw: tuple[int, int, int, int]


class UnitreeSdk2SportPortV1:
    """SDK2 Go2 SportPort used only inside the native sole-writer gateway.

    The adapter intentionally does not expose SDK special actions, low-level
    motor writers, or a second TTL/stop policy.  SDK ``Move`` remains on the
    gateway writer lane and SDK ``StopMove`` remains on the independent stop
    lane built by :mod:`gateway.seam.vendor_io`.
    """

    def __init__(
        self,
        config: UnitreeSportConfigV1,
        *,
        _writer_authority: UnitreeWriterLockV1 | None = None,
        _bindings: UnitreeSdkBindingsV1 | None = None,
        _interface_exists: Callable[[str], bool] | None = None,
        _authority: _UnitreeProcessAuthorityV1 | None = None,
        _clock: Callable[[], float] = time.monotonic,
        _sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(config, UnitreeSportConfigV1):
            raise TypeError("config must be UnitreeSportConfigV1")
        if _authority is not None and _bindings is None:
            raise ValueError("a private authority may only be used with injected test bindings")
        if _bindings is None and (
            not isinstance(_writer_authority, UnitreeWriterLockV1)
            or not _writer_authority.held
        ):
            raise UnitreeAuthorityError(
                "real Unitree SDK2 construction requires the held device-wide writer lock"
            )
        interface_exists = _interface_exists or self._system_interface_exists
        try:
            nic_exists = interface_exists(config.interface)
        except Exception as exc:
            raise UnitreeSportError(
                f"could not validate Unitree interface {config.interface!r}: {exc}"
            ) from exc
        if nic_exists is not True:
            raise UnitreeSportError(
                f"configured Unitree interface {config.interface!r} does not exist"
            )
        bindings = _bindings or load_unitree_sdk_bindings()
        authority = _authority or _UNITREE_PROCESS_AUTHORITY
        if _bindings is None:
            assert _writer_authority is not None
            # The public SDK exposes no lease/thread teardown. From this point
            # onward the lock therefore belongs to the OS process, even if a
            # later constructor step raises after partially starting SDK code.
            _writer_authority.retain_until_process_exit()
        authority.claim()

        self._config = config
        self._clock = _clock
        self._sleep = _sleep
        self._lock = threading.Lock()
        self._sport_callback_lock = threading.Lock()
        self._low_state_callback_lock = threading.Lock()
        self._writer_id: str | None = None
        self._sample: _DecodedUnitreeStateV1 | None = None
        self._decode_error: UnitreeStateError | None = None
        self._sequence = 0
        self._last_sport_stamp_ns: int | None = None
        self._low_sample: UnitreeLowStateSampleV1 | None = None
        self._low_decode_error: UnitreeStateError | None = None
        self._low_sequence = 0
        self._last_low_tick: int | None = None
        self._closed = False
        self._subscribers: list[object] = []
        self._client: object | None = None
        self._startup_stop_thread: threading.Thread | None = None

        try:
            bindings.channel_factory_initialize(config.domain_id, config.interface)
            client = bindings.sport_client_factory(enableLease=True)
            self._client = client
            client.SetTimeout(float(config.rpc_timeout_s))
            client.Init()
            # Establish a defensive zero-motion boundary as soon as the SDK
            # client has authority.  Readers and their evidence wait come
            # later, so absent or malformed telemetry cannot postpone this
            # first stop attempt.
            self._require_defensive_startup_stop()
            sport_subscriber = bindings.subscriber_factory(
                config.state_topic, bindings.sport_mode_state_type
            )
            # Own each subscriber before Init: any later subscriber/evidence
            # failure must still reach the bounded cleanup path.
            self._subscribers.append(sport_subscriber)
            sport_subscriber.Init(self._on_state, config.subscriber_queue_depth)
            low_state_subscriber = bindings.subscriber_factory(
                config.low_state_topic,
                bindings.low_state_type,
            )
            self._subscribers.append(low_state_subscriber)
            low_state_subscriber.Init(self._on_low_state, config.subscriber_queue_depth)
            self._await_startup_evidence()
        except BaseException as exc:
            with self._lock:
                self._closed = True
                self._writer_id = None
            self._shutdown_sdk_best_effort()
            if not isinstance(exc, Exception) or isinstance(exc, UnitreeSportError):
                raise
            raise UnitreeSportError(f"Unitree SDK2 initialization failed: {exc}") from exc

    @property
    def config(self) -> UnitreeSportConfigV1:
        return self._config

    @staticmethod
    def _system_interface_exists(interface: str) -> bool:
        try:
            return socket.if_nametoindex(interface) > 0
        except OSError:
            return False

    def _await_startup_evidence(self) -> None:
        deadline = self._clock() + self._config.startup_timeout_s
        while True:
            with self._lock:
                sample = self._sample
                decode_error = self._decode_error
                low_sample = self._low_sample
                low_decode_error = self._low_decode_error
            if decode_error is not None:
                raise decode_error
            if low_decode_error is not None:
                raise low_decode_error
            now = self._clock()
            sample_fresh = (
                sample is not None and 0.0 <= now - sample.received_at_monotonic_s < STATE_TIMEOUT_S
            )
            low_sample_fresh = (
                low_sample is not None
                and 0.0 <= now - low_sample.received_at_monotonic_s < STATE_TIMEOUT_S
            )
            lease_active = self._vendor_lease_active()
            if sample_fresh and low_sample_fresh and lease_active:
                return
            if now >= deadline:
                missing = []
                if not sample_fresh:
                    missing.append("fresh SportModeState")
                if not low_sample_fresh:
                    missing.append("fresh LowState")
                if not lease_active:
                    missing.append("SDK lease")
                raise UnitreeSportError(
                    "Unitree startup timed out waiting for " + " and ".join(missing)
                )
            self._sleep(min(0.01, max(0.0, deadline - now)))

    def _require_defensive_startup_stop(self) -> None:
        """Require one bounded StopMove before opening feedback readers.

        ``SportClient.SetTimeout`` is retained, but this host-side deadline is
        the startup safety boundary if an SDK call ignores its configured RPC
        timeout.  A timed-out daemon may still be inside vendor code, so the
        shutdown path must not start a concurrent second StopMove call.
        """

        client = self._client
        if client is None:
            raise UnitreeSportError("Unitree Sport client was not initialized")
        outcome: list[tuple[bool, object]] = []

        def call_stop_move() -> None:
            try:
                outcome.append((True, client.StopMove()))
            except BaseException as exc:  # noqa: BLE001 - report vendor failure on owner thread
                outcome.append((False, exc))

        try:
            thread = threading.Thread(
                target=call_stop_move,
                name="parcel-gateway-unitree-startup-stop",
                daemon=True,
            )
            # Publish the thread before start so an asynchronous interruption
            # can never make cleanup issue a concurrent StopMove.  A start
            # failure clears it because no vendor call can then be running.
            self._startup_stop_thread = thread
            try:
                thread.start()
            except Exception:
                self._startup_stop_thread = None
                raise
            thread.join(timeout=float(self._config.rpc_timeout_s))
        except Exception as exc:
            raise UnitreeSportError(
                "Unitree defensive startup StopMove could not be bounded"
            ) from exc
        if thread.is_alive():
            raise UnitreeSportError("Unitree defensive startup StopMove timed out")
        self._startup_stop_thread = None
        if not outcome:
            raise UnitreeSportError("Unitree defensive startup StopMove completed without a result")
        completed, result = outcome[0]
        if not completed:
            assert isinstance(result, BaseException)
            raise UnitreeSportError("Unitree defensive startup StopMove raised") from result
        if not self._sdk_call_succeeded(result):
            raise UnitreeSportError(
                f"Unitree defensive startup StopMove failed with SDK result {result!r}"
            )

    def acquire_writer(self, writer_id: str) -> bool:
        if not isinstance(writer_id, str) or not writer_id:
            return False
        lease_active = self._vendor_lease_active()
        with self._lock:
            if (
                self._closed
                or self._decode_error is not None
                or self._low_decode_error is not None
                or not lease_active
            ):
                return False
            sample = self._sample
            low_sample = self._low_sample
            if sample is None or low_sample is None:
                return False
            if sample.error_code not in self._config.allowed_error_codes:
                return False
            if sample.mode not in self._config.allowed_modes:
                return False
            age = self._clock() - sample.received_at_monotonic_s
            if age < 0.0 or age >= STATE_TIMEOUT_S:
                return False
            low_age = self._clock() - low_sample.received_at_monotonic_s
            if low_age < 0.0 or low_age >= STATE_TIMEOUT_S:
                return False
            if not self._commissioned_soc(low_sample)[0]:
                return False
            if self._writer_id is not None and self._writer_id != writer_id:
                return False
            self._writer_id = writer_id
            return True

    def release_writer(self, writer_id: str | None) -> None:
        with self._lock:
            if writer_id is None or writer_id == self._writer_id:
                self._writer_id = None

    def move(
        self,
        *,
        writer_id: str,
        vx_mps: float,
        vy_mps: float,
        vyaw_rad_s: float,
    ) -> None:
        values = (vx_mps, vy_mps, vyaw_rad_s)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("Unitree Move velocities must be finite numbers")
        lease_active = self._vendor_lease_active()
        with self._lock:
            sample = self._sample
            if self._closed:
                raise UnitreeSportError("Unitree SportPort is closed")
            if writer_id != self._writer_id:
                raise UnitreeAuthorityError("Unitree Move refused: local writer identity mismatch")
            if not lease_active:
                raise UnitreeAuthorityError("Unitree Move refused: SDK lease is not active")
            if self._decode_error is not None:
                raise self._decode_error
            if self._low_decode_error is not None:
                raise self._low_decode_error
            if sample is None:
                raise UnitreeStateError("Unitree Move refused: no SportModeState sample")
            low_sample = self._low_sample
            if low_sample is None:
                raise UnitreeStateError("Unitree Move refused: no LowState sample")
            self._raise_for_state_fault(sample)
            age = self._clock() - sample.received_at_monotonic_s
            if age < 0.0 or age >= STATE_TIMEOUT_S:
                raise UnitreeStateError("Unitree Move refused: SportModeState is not fresh")
            low_age = self._clock() - low_sample.received_at_monotonic_s
            if low_age < 0.0 or low_age >= STATE_TIMEOUT_S:
                raise UnitreeStateError("Unitree Move refused: LowState is not fresh")
            soc_ok, soc_reason = self._commissioned_soc(low_sample)
            if not soc_ok:
                raise UnitreeStateError(f"Unitree Move refused: {soc_reason}")
            client = self._client
        if client is None:
            raise UnitreeSportError("Unitree Sport client was not initialized")
        result = client.Move(
            float(vx_mps),
            float(vy_mps) * self._config.lateral_sign,
            float(vyaw_rad_s) * self._config.yaw_sign,
        )
        if not self._sdk_call_succeeded(result):
            raise UnitreeSportError(f"Unitree Move failed with SDK result {result!r}")

    def stop_move(self, *, reason: str) -> bool:
        del reason
        with self._lock:
            if self._closed:
                return False
            client = self._client
        if client is None:
            return False
        return self._sdk_call_succeeded(client.StopMove())

    def state(self) -> SportSampleV1:
        lease_active = self._vendor_lease_active()
        with self._lock:
            if self._closed:
                raise UnitreeStateError("Unitree SportPort is closed")
            if self._decode_error is not None:
                raise self._decode_error
            sample = self._sample
            if sample is None:
                raise UnitreeStateError("no Unitree SportModeState sample has arrived")
            low_sample = self._low_sample
            if low_sample is not None:
                low_age = self._clock() - low_sample.received_at_monotonic_s
                if (
                    self._low_decode_error is not None
                    or low_age < 0.0
                    or low_age >= STATE_TIMEOUT_S
                ):
                    low_sample = None
            integrity_ok, integrity_reason = self._feedback_integrity(sample)
            if low_sample is None:
                soc_ok: bool | None = None
                soc_reason = "commissioned_soc_unavailable"
            else:
                soc_ok, soc_reason = self._commissioned_soc(low_sample)
            return SportSampleV1(
                sequence=sample.sequence,
                received_at_monotonic_s=sample.received_at_monotonic_s,
                vx_mps=sample.vx_mps,
                vy_mps=sample.vy_mps,
                vyaw_rad_s=sample.vyaw_rad_s,
                lease_active=self._writer_id is not None and lease_active,
                telemetry_valid=True,
                vendor_position_m=sample.vendor_position_m,
                vendor_rpy_rad=sample.vendor_rpy_rad,
                mode=sample.mode,
                error_code=sample.error_code,
                source_time_s=sample.source_time_s,
                sport_foot_force_raw=sample.sport_foot_force_raw,
                low_state=low_sample,
                feedback_integrity_ok=integrity_ok,
                feedback_integrity_reason=integrity_reason,
                commissioned_soc_ok=soc_ok,
                commissioned_soc_reason=soc_reason,
            )

    def _commissioned_soc(
        self,
        low_state: UnitreeLowStateSampleV1,
    ) -> tuple[bool, str]:
        if low_state.battery_soc_percent <= self._config.minimum_battery_soc_percent:
            return (
                False,
                "soc_at_or_below_commissioned_minimum",
            )
        return True, "soc_above_commissioned_minimum"

    def _feedback_integrity(
        self,
        sport_state: _DecodedUnitreeStateV1,
    ) -> tuple[bool, str]:
        if sport_state.error_code not in self._config.allowed_error_codes:
            return False, f"sport_error_code_not_commissioned_{sport_state.error_code}"[:160]
        if sport_state.mode not in self._config.allowed_modes:
            return False, f"sport_mode_not_commissioned_{sport_state.mode}"
        return True, "ok"

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._writer_id = None
        self._shutdown_sdk_best_effort()

    @staticmethod
    def _sdk_call_succeeded(result: object) -> bool:
        return isinstance(result, int) and not isinstance(result, bool) and result == 0

    def _vendor_lease_active(self) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            lease_id = client.GetLeaseId()
        except Exception:  # noqa: BLE001 - SDK lease evidence fails closed
            return False
        return isinstance(lease_id, int) and not isinstance(lease_id, bool) and lease_id != 0

    def _raise_for_state_fault(
        self,
        sample: _DecodedUnitreeStateV1,
        *,
        require_allowed_mode: bool = True,
    ) -> None:
        if sample.error_code not in self._config.allowed_error_codes:
            raise UnitreeStateError(
                f"Unitree SportModeState error_code {sample.error_code} is not commissioned"
            )
        if require_allowed_mode and sample.mode not in self._config.allowed_modes:
            raise UnitreeStateError(
                f"Unitree SportModeState mode {sample.mode} is not commissioned"
            )

    def _on_state(self, message: object) -> None:
        try:
            observed_at = self._finite_number(
                self._clock(),
                "SportModeState callback monotonic time",
            )
        except Exception as exc:  # noqa: BLE001 - malformed callback time latches state
            with self._sport_callback_lock:
                error = UnitreeStateError(f"invalid Unitree SportModeState: {exc}")
                with self._lock:
                    if not self._closed:
                        self._decode_error = error
            return
        # Timestamp at callback entry, then serialize decode and commit for this
        # stream.  Sport and LowState have distinct locks, so health ingestion
        # remains independent of motion-state parsing.
        with self._sport_callback_lock:
            with self._lock:
                if self._closed:
                    return
            self._on_state_serialized(message, observed_at)

    def _on_state_serialized(self, message: object, observed_at: float) -> None:
        try:
            velocity = message.velocity  # type: ignore[attr-defined]
            position = self._finite_vector(message.position, 3, "position")  # type: ignore[attr-defined]
            imu_state = message.imu_state  # type: ignore[attr-defined]
            rpy = imu_state.rpy
            vendor_vx = self._finite_vector_entry(velocity, 0, "velocity[0]")
            vendor_vy = self._finite_vector_entry(velocity, 1, "velocity[1]")
            roll_pitch_yaw = self._finite_vector(rpy, 3, "imu_state.rpy")
            yaw = roll_pitch_yaw[2]
            yaw_speed = self._finite_number(message.yaw_speed, "yaw_speed")
            mode = self._bounded_uint8(message.mode, "mode")
            error_code = self._bounded_uint32(message.error_code, "error_code")
            source_time_s, source_stamp_ns = self._source_time(  # type: ignore[attr-defined]
                message.stamp
            )
            foot_force = self._signed_int16_vector(  # type: ignore[attr-defined]
                message.foot_force,
                4,
                "foot_force",
            )
            if self._config.state_velocity_frame == "odom":
                cosine = math.cos(yaw)
                sine = math.sin(yaw)
                body_vx = cosine * vendor_vx + sine * vendor_vy
                body_vy = -sine * vendor_vx + cosine * vendor_vy
            else:
                body_vx = vendor_vx
                body_vy = vendor_vy
        except Exception as exc:  # noqa: BLE001 - malformed vendor objects latch state
            error = UnitreeStateError(f"invalid Unitree SportModeState: {exc}")
            with self._lock:
                if not self._closed:
                    self._decode_error = error
            return
        with self._lock:
            if self._closed:
                return
            previous_stamp_ns = self._last_sport_stamp_ns
            if previous_stamp_ns is not None:
                if source_stamp_ns == previous_stamp_ns:
                    # A duplicate DDS sample is not new body-motion evidence.
                    # Preserve the earlier host receipt time so a frozen stream
                    # ages out and cannot manufacture distinct stop witnesses.
                    return
                if source_stamp_ns < previous_stamp_ns:
                    self._decode_error = UnitreeStateError(
                        "invalid Unitree SportModeState: stamp moved backwards"
                    )
                    return
            self._last_sport_stamp_ns = source_stamp_ns
            self._sequence += 1
            self._sample = _DecodedUnitreeStateV1(
                sequence=self._sequence,
                received_at_monotonic_s=observed_at,
                vx_mps=body_vx,
                vy_mps=body_vy * self._config.lateral_sign,
                vyaw_rad_s=yaw_speed * self._config.yaw_sign,
                vendor_position_m=position,
                vendor_rpy_rad=roll_pitch_yaw,
                mode=mode,
                error_code=error_code,
                source_time_s=source_time_s,
                sport_foot_force_raw=foot_force,
            )

    def _on_low_state(self, message: object) -> None:
        """Copy raw LowState health fields without assigning undocumented units."""

        try:
            observed_at = self._finite_number(
                self._clock(),
                "LowState callback monotonic time",
            )
        except Exception as exc:  # noqa: BLE001 - malformed callback time latches health
            with self._low_state_callback_lock:
                error = UnitreeStateError(f"invalid Unitree LowState: {exc}")
                with self._lock:
                    if not self._closed:
                        self._low_decode_error = error
            return
        with self._low_state_callback_lock:
            with self._lock:
                if self._closed:
                    return
            self._on_low_state_serialized(message, observed_at)

    def _on_low_state_serialized(self, message: object, observed_at: float) -> None:
        try:
            tick = self._bounded_uint32(message.tick, "tick")  # type: ignore[attr-defined]
            bms_state = message.bms_state  # type: ignore[attr-defined]
            battery_soc = self._bounded_uint8(bms_state.soc, "bms_state.soc")
            if battery_soc > 100:
                raise ValueError("bms_state.soc must be in [0, 100]")
            bms_status = self._bounded_uint8(bms_state.status, "bms_state.status")
            power_v = self._finite_number(message.power_v, "power_v")  # type: ignore[attr-defined]
            power_a = self._finite_number(message.power_a, "power_a")  # type: ignore[attr-defined]
            try:
                motors = tuple(message.motor_state)  # type: ignore[attr-defined]
            except TypeError as exc:
                raise ValueError("motor_state must contain 20 entries") from exc
            if len(motors) != 20:
                raise ValueError("motor_state must contain 20 entries")
            temperatures = tuple(
                self._bounded_uint8(motor.temperature, f"motor_state[{index}].temperature")
                for index, motor in enumerate(motors[:12])
            )
            lost = tuple(
                self._bounded_uint32(motor.lost, f"motor_state[{index}].lost")
                for index, motor in enumerate(motors[:12])
            )
            foot_force_est = self._signed_int16_vector(  # type: ignore[attr-defined]
                message.foot_force_est,
                4,
                "foot_force_est",
            )
            imu_temperature = self._bounded_uint8(
                message.imu_state.temperature,  # type: ignore[attr-defined]
                "imu_state.temperature",
            )
            ntc = (
                self._bounded_uint8(  # type: ignore[attr-defined]
                    message.temperature_ntc1,
                    "temperature_ntc1",
                ),
                self._bounded_uint8(  # type: ignore[attr-defined]
                    message.temperature_ntc2,
                    "temperature_ntc2",
                ),
            )
        except Exception as exc:  # noqa: BLE001 - malformed vendor objects latch health
            error = UnitreeStateError(f"invalid Unitree LowState: {exc}")
            with self._lock:
                if not self._closed:
                    self._low_decode_error = error
            return
        with self._lock:
            if self._closed:
                return
            previous_tick = self._last_low_tick
            if previous_tick is not None:
                tick_delta = (tick - previous_tick) & 0xFFFF_FFFF
                if tick_delta == 0:
                    # A duplicate packet is not new health evidence. Keeping
                    # the prior host timestamp makes a frozen stream age out.
                    return
                if tick_delta >= 1 << 31:
                    self._low_decode_error = UnitreeStateError(
                        "invalid Unitree LowState: tick moved backwards"
                    )
                    return
            self._last_low_tick = tick
            self._low_sequence += 1
            self._low_sample = UnitreeLowStateSampleV1(
                sequence=self._low_sequence,
                received_at_monotonic_s=observed_at,
                tick=tick,
                battery_soc_percent=battery_soc,
                power_v=power_v,
                power_a=power_a,
                max_motor_temperature_raw=max(temperatures),
                motor_lost_max_raw=max(lost),
                foot_force_est_raw=foot_force_est,
                imu_temperature_raw=imu_temperature,
                temperature_ntc_raw=ntc,
                bms_status=bms_status,
            )

    @classmethod
    def _finite_vector(
        cls,
        value: object,
        length: int,
        name: str,
    ) -> tuple[float, ...]:
        try:
            result = tuple(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError(f"{name} must contain {length} finite values") from exc
        if len(result) != length:
            raise ValueError(f"{name} must contain {length} finite values")
        return tuple(
            cls._finite_number(item, f"{name}[{index}]") for index, item in enumerate(result)
        )

    @classmethod
    def _signed_int16_vector(
        cls,
        value: object,
        length: int,
        name: str,
    ) -> tuple[int, ...]:
        try:
            result = tuple(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError(f"{name} must contain {length} signed int16 values") from exc
        if len(result) != length:
            raise ValueError(f"{name} must contain {length} signed int16 values")
        for item in result:
            if (
                isinstance(item, bool)
                or not isinstance(item, int)
                or not -(1 << 15) <= item < (1 << 15)
            ):
                raise ValueError(f"{name} must contain {length} signed int16 values")
        return result

    @staticmethod
    def _source_time(stamp: object) -> tuple[float, int]:
        if stamp is None:
            raise ValueError("stamp must contain sec and nanosec")
        missing = object()
        seconds = getattr(stamp, "sec", missing)
        nanoseconds = getattr(stamp, "nanosec", missing)
        if nanoseconds is missing:
            nanoseconds = getattr(stamp, "nsec", missing)
        if seconds is missing or nanoseconds is missing:
            raise ValueError("stamp must contain sec and nanosec")
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, int)
            or not -(1 << 31) <= seconds < 1 << 31
            or isinstance(nanoseconds, bool)
            or not isinstance(nanoseconds, int)
        ):
            raise ValueError("stamp fields must match the Unitree TimeSpec integer ranges")
        if not 0 <= nanoseconds < 1_000_000_000:
            raise ValueError("stamp nanosec must be in [0, 1000000000)")
        result = float(seconds) + float(nanoseconds) / 1_000_000_000.0
        if not math.isfinite(result):
            raise ValueError("stamp must be finite")
        return result, seconds * 1_000_000_000 + nanoseconds

    @classmethod
    def _finite_vector_entry(cls, value: object, index: int, name: str) -> float:
        try:
            entry = value[index]  # type: ignore[index]
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError(f"{name} is missing") from exc
        return cls._finite_number(entry, name)

    @staticmethod
    def _finite_number(value: object, name: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError(f"{name} must be a finite number")
        return float(value)

    @staticmethod
    def _bounded_uint8(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError(f"{name} must be an integer in [0, 255]")
        return value

    @staticmethod
    def _bounded_uint32(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 1 << 32:
            raise ValueError(f"{name} must be an integer in [0, 4294967295]")
        return value

    def _shutdown_sdk_best_effort(self) -> None:
        """Bound the final supported SDK calls without inventing lease APIs.

        The official Python SDK exposes ``StopMove`` on ``SportClient`` and
        ``Close`` on ``ChannelSubscriber``.  Its public ``SportClient``, base
        client, client stub, and lease client expose no release/close method,
        so this port deliberately does not probe private attributes or guess
        at a client/lease cleanup call.  Process exit is therefore the only
        supported end to the SDK lease-renewal thread, matching this port's
        irreversible process authority claim.
        """

        with self._lock:
            client = self._client
            self._client = None
            startup_stop_thread = self._startup_stop_thread
            self._startup_stop_thread = None
        stop_move = getattr(client, "StopMove", None) if client is not None else None
        startup_stop_in_flight = False
        if startup_stop_thread is not None:
            try:
                startup_stop_in_flight = startup_stop_thread.is_alive()
            except Exception:  # noqa: BLE001 - uncertain means do not issue a concurrent stop
                startup_stop_in_flight = True
        if callable(stop_move) and not startup_stop_in_flight:
            self._run_cleanup_bounded(
                stop_move,
                thread_name="parcel-gateway-unitree-final-stop",
            )
        self._close_subscribers_bounded()

    def _close_subscribers_bounded(self) -> None:
        subscribers = tuple(self._subscribers)
        self._subscribers.clear()
        for index, subscriber in enumerate(subscribers):
            close = getattr(subscriber, "Close", None)
            if callable(close):
                self._run_cleanup_bounded(
                    close,
                    thread_name=f"parcel-gateway-unitree-subscriber-{index}-close",
                )

    def _run_cleanup_bounded(
        self,
        cleanup: Callable[[], object],
        *,
        thread_name: str,
    ) -> None:
        try:
            thread = threading.Thread(
                target=self._ignore_cleanup_error,
                args=(cleanup,),
                name=thread_name,
                daemon=True,
            )
            thread.start()
            thread.join(timeout=float(self._config.rpc_timeout_s))
        except Exception:  # noqa: BLE001 - resource exhaustion stays best-effort
            return

    @staticmethod
    def _ignore_cleanup_error(cleanup: Callable[[], object]) -> None:
        try:
            cleanup()
        except Exception:  # noqa: BLE001 - shutdown must stay bounded and best-effort
            return
