"""Focused desktop contract tests for the optional SDK2 gateway SportPort.

No vendor package is installed or imported.  The SDK's four symbols are
injected with small fakes so these tests prove mapping, ownership and refusal
semantics without making a hardware claim.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

import pytest

from gateway import ports as ports_module
from gateway import process as process_module
from gateway.audit import BoundedAuditRingV1
from gateway.core import GatewayCoreV1
from gateway.limits import STATE_TIMEOUT_S, default_limits
from gateway.ports import (
    UnitreeAuthorityError,
    UnitreeSdk2SportPortV1,
    UnitreeSdkBindingsV1,
    UnitreeSdkUnavailableError,
    UnitreeSportConfigV1,
    UnitreeSportError,
    UnitreeStateError,
    _UnitreeProcessAuthorityV1,
    read_sport_sample,
)
from gateway.seam import cli as cli_module
from parcel_robot.bridge import unitree_writer_lock as writer_lock_module
from parcel_robot.bridge.protocol import GatewayPhaseV1


@dataclass
class _Imu:
    rpy: list[float]


@dataclass
class _Stamp:
    sec: int = 1_700_000_000
    nanosec: int = 250_000_000


@dataclass
class _State:
    velocity: list[float]
    imu_state: _Imu
    yaw_speed: float
    mode: int
    error_code: int = 0
    position: list[float] = field(default_factory=lambda: [1.0, 2.0, 0.32])
    foot_force: list[int] = field(default_factory=lambda: [10, 11, 12, 13])
    stamp: _Stamp = field(default_factory=_Stamp)


@dataclass
class _MotorState:
    temperature: int = 40
    lost: int = 0


@dataclass
class _BmsState:
    soc: int = 87
    status: int = 2


@dataclass
class _LowImu:
    temperature: int = 39


@dataclass
class _LowState:
    tick: int = 1234
    bms_state: _BmsState = field(default_factory=_BmsState)
    power_v: float = 30.5
    power_a: float = 1.25
    motor_state: list[_MotorState] = field(
        default_factory=lambda: [_MotorState(temperature=40 + index % 4) for index in range(20)]
    )
    foot_force_est: list[int] = field(default_factory=lambda: [9, 10, 11, 12])
    imu_state: _LowImu = field(default_factory=_LowImu)
    temperature_ntc1: int = 44
    temperature_ntc2: int = 45


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    tuple(
        (field_name, invalid_value)
        for field_name in (
            "received_at_monotonic_s",
            "vx_mps",
            "vy_mps",
            "vyaw_rad_s",
        )
        for invalid_value in (True, "1.0")
    ),
)
def test_read_sport_sample_does_not_coerce_invalid_physical_numbers(
    field_name: str,
    invalid_value: object,
) -> None:
    class RawState:
        sequence = 1
        received_at_monotonic_s: object = 1.0
        vx_mps: object = 0.0
        vy_mps: object = 0.0
        vyaw_rad_s: object = 0.0
        lease_active = False

    raw = RawState()
    setattr(raw, field_name, invalid_value)

    class Port:
        def state(self) -> RawState:
            return raw

    with pytest.raises(TypeError, match=field_name):
        read_sport_sample(Port())  # type: ignore[arg-type]


def test_unitree_writer_lock_is_fixed_path_persistent_and_exclusive(tmp_path) -> None:
    path = tmp_path / "unitree-writer.lock"
    first = ports_module.UnitreeWriterLockV1(required=True, path=path)
    second = ports_module.UnitreeWriterLockV1(required=True, path=path)
    try:
        first.acquire()
        assert first.held is True
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == ports_module.UNITREE_WRITER_LOCK_MODE
        with pytest.raises(FileExistsError, match="another process holds"):
            second.acquire()
    finally:
        first.close()
        second.close()

    # The inode persists so releasing a lock cannot create a split-lock race.
    identity = (path.stat().st_dev, path.stat().st_ino)
    second.acquire()
    try:
        assert (path.stat().st_dev, path.stat().st_ino) == identity
    finally:
        second.close()


def test_unitree_writer_lock_excludes_and_releases_across_processes(tmp_path) -> None:
    path = tmp_path / "unitree-writer.lock"
    holder = ports_module.UnitreeWriterLockV1(required=True, path=path)
    program = """
import sys
from parcel_robot.bridge.unitree_writer_lock import UnitreeWriterLockV1
lock = UnitreeWriterLockV1(required=True, path=sys.argv[1])
try:
    lock.acquire()
except FileExistsError:
    raise SystemExit(23)
lock.close()
"""
    holder.acquire()
    try:
        blocked = subprocess.run(
            [sys.executable, "-c", program, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert blocked.returncode == 23, blocked.stderr
    finally:
        holder.close()

    released = subprocess.run(
        [sys.executable, "-c", program, str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert released.returncode == 0, released.stderr


def test_losing_fixed_writer_lock_never_reaches_vendor_construction(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "unitree-writer.lock"
    monkeypatch.setattr(writer_lock_module, "UNITREE_WRITER_LOCK_PATH", path)
    holder = ports_module.UnitreeWriterLockV1(required=True)
    holder.acquire()
    reached_vendor = False

    class Settings:
        sport = "vendor"

    def forbidden_run(_settings, *, writer_lock) -> int:
        del writer_lock
        nonlocal reached_vendor
        reached_vendor = True
        raise AssertionError("vendor construction ran without writer authority")

    monkeypatch.setattr(cli_module, "settings_from", lambda _args, _env: Settings())
    monkeypatch.setattr(cli_module, "_run_with_writer_authority", forbidden_run)
    try:
        with pytest.raises(SystemExit, match="vendor writer authority unavailable"):
            cli_module.main([])
        assert reached_vendor is False
    finally:
        holder.close()


@pytest.mark.parametrize("entrypoint", ("systemd", "bench"))
def test_vendor_entrypoints_hold_writer_lock_around_all_construction(
    monkeypatch,
    entrypoint: str,
) -> None:
    events: list[str] = []

    class RecordingLock:
        def __init__(self, *, required: bool) -> None:
            assert required is True
            events.append("lock_created")

        def acquire(self) -> None:
            events.append("lock_acquired")

        def close(self) -> None:
            events.append("lock_released")

    class Settings:
        sport = "vendor"

    if entrypoint == "systemd":
        monkeypatch.setattr(cli_module, "UnitreeWriterLockV1", RecordingLock)
        monkeypatch.setattr(cli_module, "settings_from", lambda _args, _env: Settings())

        def run(_settings, *, writer_lock) -> int:
            assert isinstance(writer_lock, RecordingLock)
            events.append("vendor_construction_and_serve")
            return 17

        monkeypatch.setattr(cli_module, "_run_with_writer_authority", run)
        assert cli_module.main([]) == 17
    else:
        monkeypatch.setattr(process_module, "UnitreeWriterLockV1", RecordingLock)
        monkeypatch.setattr(process_module.signal, "signal", lambda *_args: None)

        def run(_args, _stop_event, *, writer_lock) -> int:
            assert isinstance(writer_lock, RecordingLock)
            events.append("vendor_construction_and_serve")
            return 19

        monkeypatch.setattr(process_module, "_run_with_writer_authority", run)
        assert (
            process_module.main(
                [
                    "--socket",
                    "/unused/gateway.sock",
                    "--audit-log",
                    "/unused/audit.jsonl",
                    "--sport",
                    "vendor",
                ]
            )
            == 19
        )

    assert events == [
        "lock_created",
        "lock_acquired",
        "vendor_construction_and_serve",
        "lock_released",
    ]


def test_core_close_reaches_sport_after_writer_cleanup_raises() -> None:
    events: list[str] = []

    class Closer:
        def __init__(self, name: str, error: BaseException | None = None) -> None:
            self.name = name
            self.error = error

        def close(self) -> None:
            events.append(self.name)
            if self.error is not None:
                raise self.error

    core = object.__new__(GatewayCoreV1)
    core._lock = threading.RLock()
    core._closed = False
    core.phase = GatewayPhaseV1.DISARMED
    core._watch_stop = threading.Event()
    core._watchdog = None
    core._writer = Closer("writer", RuntimeError("seeded writer close failure"))
    core._vendor_io = Closer("vendor_io")
    core._sport = Closer("sport")

    with pytest.raises(RuntimeError, match="seeded writer close failure"):
        core.close()
    assert events == ["writer", "vendor_io", "sport"]
    assert core._closed is True


class _GatedStateView:
    def __init__(
        self,
        state: _State,
        *,
        velocity_accessed: threading.Event,
        release_velocity: threading.Event,
    ) -> None:
        self._state = state
        self._velocity_accessed = velocity_accessed
        self._release_velocity = release_velocity

    @property
    def velocity(self) -> list[float]:
        self._velocity_accessed.set()
        if not self._release_velocity.wait(1.0):
            raise RuntimeError("timed out waiting to release gated SportModeState")
        return self._state.velocity

    def __getattr__(self, name: str):
        return getattr(self._state, name)


class _GatedLowStateView:
    def __init__(
        self,
        state: _LowState,
        *,
        tick_accessed: threading.Event,
        release_tick: threading.Event,
    ) -> None:
        self._state = state
        self._tick_accessed = tick_accessed
        self._release_tick = release_tick

    @property
    def tick(self) -> int:
        self._tick_accessed.set()
        if not self._release_tick.wait(1.0):
            raise RuntimeError("timed out waiting to release gated LowState")
        return self._state.tick

    def __getattr__(self, name: str):
        return getattr(self._state, name)


class _Subscriber:
    def __init__(
        self,
        message: object,
        *,
        event_name: str,
        events: list[str],
        emit_on_init: bool = True,
        close_hook=None,
    ) -> None:
        self.message = message
        self.event_name = event_name
        self.events = events
        self.emit_on_init = emit_on_init
        self.close_hook = close_hook
        self.callback = None
        self.queue_depth = 0
        self.closed = threading.Event()
        self.close_entered = threading.Event()
        self.close_calls = 0

    def Init(self, callback, queue_depth: int) -> None:
        self.events.append(f"subscriber_init:{self.event_name}")
        self.callback = callback
        self.queue_depth = queue_depth
        if self.emit_on_init:
            callback(self.message)

    def emit(self, message: object) -> None:
        assert self.callback is not None
        self.callback(message)

    def Close(self) -> None:
        self.close_calls += 1
        self.close_entered.set()
        if self.close_hook is not None:
            self.close_hook()
        self.closed.set()


class _Client:
    def __init__(
        self,
        *,
        events: list[str],
        init_error: BaseException | None = None,
        stop_hook=None,
    ) -> None:
        self.events = events
        self.init_error = init_error
        self.stop_hook = stop_hook
        self.timeout_s = 0.0
        self.lease_id = 71
        self.moves: list[tuple[float, float, float]] = []
        self.stop_calls = 0
        self.stop_entered = threading.Event()
        self.move_result = 0
        self.stop_result = 0
        self.close_calls = 0

    def SetTimeout(self, timeout_s: float) -> None:
        self.events.append("client_set_timeout")
        self.timeout_s = timeout_s

    def Init(self) -> None:
        self.events.append("client_init")
        if self.init_error is not None:
            raise self.init_error

    def GetLeaseId(self) -> int:
        return self.lease_id

    def Move(self, vx: float, vy: float, vyaw: float) -> int:
        self.moves.append((vx, vy, vyaw))
        return self.move_result

    def StopMove(self) -> int:
        self.events.append("stop_move")
        self.stop_calls += 1
        self.stop_entered.set()
        if self.stop_hook is not None:
            self.stop_hook()
        return self.stop_result

    def Close(self) -> None:
        """A tempting but unsupported API the production port must not guess at."""

        self.close_calls += 1


class _SdkHarness:
    def __init__(
        self,
        message: _State,
        *,
        low_message: _LowState | None = None,
        client_init_error: BaseException | None = None,
        client_stop_hook=None,
        subscriber_close_hook=None,
        emit_low_state: bool = True,
    ) -> None:
        self.events: list[str] = []
        self.message = message
        self.low_message = low_message or _LowState()
        self.client = _Client(
            events=self.events,
            init_error=client_init_error,
            stop_hook=client_stop_hook,
        )
        self.subscriber_close_hook = subscriber_close_hook
        self.emit_low_state = emit_low_state
        self.subscribers: list[_Subscriber] = []
        self.subscriber_requests: list[tuple[str, object]] = []
        self.channel_initializations: list[tuple[int, str]] = []
        self.lease_flags: list[bool] = []

    def initialize(self, domain_id: int, interface: str) -> None:
        self.events.append("channel_initialize")
        self.channel_initializations.append((domain_id, interface))

    def subscriber(self, topic: str, message_type: object) -> _Subscriber:
        assert topic.startswith("rt/")
        self.events.append(f"subscriber_factory:{topic}")
        self.subscriber_requests.append((topic, message_type))
        if message_type is _State:
            message = self.message
        else:
            assert message_type is _LowState
            message = self.low_message
        made = _Subscriber(
            message,
            event_name=topic,
            events=self.events,
            emit_on_init=message_type is not _LowState or self.emit_low_state,
            close_hook=self.subscriber_close_hook,
        )
        self.subscribers.append(made)
        return made

    def sport_client(self, *, enableLease: bool) -> _Client:
        self.events.append("client_factory")
        self.lease_flags.append(enableLease)
        return self.client

    def bindings(self) -> UnitreeSdkBindingsV1:
        return UnitreeSdkBindingsV1(
            channel_factory_initialize=self.initialize,
            subscriber_factory=self.subscriber,
            sport_client_factory=self.sport_client,
            sport_mode_state_type=_State,
            low_state_type=_LowState,
        )


def _config(**overrides: object) -> UnitreeSportConfigV1:
    values = {
        "interface": "robot0",
        "domain_id": 0,
        "allowed_modes": (3,),
        "allowed_error_codes": (0,),
        "state_velocity_frame": "odom",
        "lateral_sign": -1,
        "yaw_sign": -1,
        "axes_commissioned": True,
        "state_frame_commissioned": True,
        "sport_state_stamp_monotonic_commissioned": True,
        "battery_soc_percent_commissioned": True,
        "minimum_battery_soc_percent": 8,
        "low_state_tick_monotonic_commissioned": True,
    }
    values.update(overrides)
    return UnitreeSportConfigV1(**values)


def _port(
    harness: _SdkHarness,
    *,
    config: UnitreeSportConfigV1 | None = None,
    authority: _UnitreeProcessAuthorityV1 | None = None,
    clock=None,
    sleep=None,
) -> UnitreeSdk2SportPortV1:
    options = {}
    if clock is not None:
        options["_clock"] = clock
    if sleep is not None:
        options["_sleep"] = sleep
    return UnitreeSdk2SportPortV1(
        config or _config(),
        _bindings=harness.bindings(),
        _interface_exists=lambda interface: interface == "robot0",
        _authority=authority or _UnitreeProcessAuthorityV1(),
        **options,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"interface": ""}, "Linux NIC name"),
        ({"domain_id": 233}, "domain_id"),
        ({"allowed_modes": ()}, "at least one"),
        ({"allowed_error_codes": ()}, "commissioned values"),
        ({"state_velocity_frame": "guessed"}, "base_link"),
        ({"lateral_sign": 0}, "lateral_sign"),
        ({"axes_commissioned": False}, "explicitly true"),
        ({"state_frame_commissioned": False}, "explicitly true"),
        ({"sport_state_stamp_monotonic_commissioned": False}, "hardware validation"),
        ({"battery_soc_percent_commissioned": False}, "hardware validation"),
        ({"minimum_battery_soc_percent": 0}, "minimum_battery"),
        ({"minimum_battery_soc_percent": 100}, r"\[1, 99\]"),
        ({"low_state_tick_monotonic_commissioned": False}, "hardware validation"),
        ({"rpc_timeout_s": 0.21}, "stop retry budget"),
        ({"startup_timeout_s": 10.1}, "10 seconds"),
        ({"subscriber_queue_depth": 1}, "exactly 0"),
    ],
)
def test_physical_config_refuses_implicit_or_unbounded_values(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        _config(**overrides)


def test_sdk2_mapping_uses_one_lease_move_stopmove_and_local_state() -> None:
    harness = _SdkHarness(
        _State(
            velocity=[1.0, 2.0, 0.0],
            imu_state=_Imu([0.0, 0.0, math.pi / 2.0]),
            yaw_speed=0.4,
            mode=3,
        )
    )
    port = _port(harness)
    try:
        assert harness.channel_initializations == [(0, "robot0")]
        assert harness.lease_flags == [True]
        assert harness.subscriber_requests == [
            ("rt/sportmodestate", _State),
            ("rt/lowstate", _LowState),
        ]
        assert harness.client.timeout_s == pytest.approx(0.2)
        assert harness.subscribers[0].queue_depth == 0
        assert harness.subscribers[1].queue_depth == 0
        assert port.state().lease_active is False

        assert port.acquire_writer("parcel-runtime") is True
        assert port.acquire_writer("some-other-writer") is False
        state = port.state()
        assert state.vx_mps == pytest.approx(2.0)
        assert state.vy_mps == pytest.approx(1.0)
        assert state.vyaw_rad_s == pytest.approx(-0.4)
        assert state.lease_active is True
        assert state.telemetry_valid is True
        assert state.vendor_position_m == (1.0, 2.0, 0.32)
        assert state.vendor_rpy_rad == pytest.approx((0.0, 0.0, math.pi / 2.0))
        assert state.mode == 3
        assert state.error_code == 0
        assert state.source_time_s == pytest.approx(1_700_000_000.25)
        assert state.sport_foot_force_raw == (10, 11, 12, 13)
        assert state.commissioned_soc_ok is True
        assert state.commissioned_soc_reason == "soc_above_commissioned_minimum"
        assert state.low_state is not None
        assert state.low_state.tick == 1234
        assert state.low_state.battery_soc_percent == 87
        assert state.low_state.power_v == pytest.approx(30.5)
        assert state.low_state.power_a == pytest.approx(1.25)
        assert state.low_state.max_motor_temperature_raw == 43
        assert state.low_state.motor_lost_max_raw == 0
        assert state.low_state.foot_force_est_raw == (9, 10, 11, 12)
        assert state.low_state.imu_temperature_raw == 39
        assert state.low_state.temperature_ntc_raw == (44, 45)
        assert state.low_state.bms_status == 2

        port.move(
            writer_id="parcel-runtime",
            vx_mps=0.1,
            vy_mps=0.2,
            vyaw_rad_s=0.3,
        )
        assert harness.client.moves == [(0.1, -0.2, -0.3)]
        with pytest.raises(UnitreeAuthorityError, match="identity mismatch"):
            port.move(writer_id="wrong", vx_mps=0.0, vy_mps=0.0, vyaw_rad_s=0.0)
        assert port.stop_move(reason="test") is True
        assert harness.client.stop_calls == 2

        port.release_writer("parcel-runtime")
        assert port.state().lease_active is False
    finally:
        port.close()
    assert all(subscriber.closed.wait(0.2) for subscriber in harness.subscribers)


def test_writer_acquire_and_move_refuse_stale_or_future_feedback() -> None:
    now = [10.0]
    harness = _SdkHarness(
        _State(
            velocity=[0.0, 0.0, 0.0],
            imu_state=_Imu([0.0, 0.0, 0.0]),
            yaw_speed=0.0,
            mode=3,
        )
    )
    port = _port(harness, clock=lambda: now[0])
    try:
        now[0] = 10.0 + STATE_TIMEOUT_S
        assert port.acquire_writer("parcel-runtime") is False
        now[0] = 9.0
        assert port.acquire_writer("parcel-runtime") is False
        now[0] = 10.0
        assert port.acquire_writer("parcel-runtime") is True
        now[0] = 10.0 + STATE_TIMEOUT_S
        with pytest.raises(UnitreeStateError, match="not fresh"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
        assert harness.client.moves == []
    finally:
        port.close()


def test_duplicate_sport_stamp_cannot_renew_motion_freshness() -> None:
    now = [10.0]
    sport = _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3)
    harness = _SdkHarness(sport)
    port = _port(harness, clock=lambda: now[0])
    try:
        first = port.state()
        assert port.acquire_writer("parcel-runtime") is True
        now[0] += STATE_TIMEOUT_S
        harness.subscribers[1].emit(_LowState(tick=1235))
        harness.subscribers[0].emit(sport)
        observed = port.state()
        assert observed.sequence == first.sequence
        assert observed.received_at_monotonic_s == first.received_at_monotonic_s
        assert observed.low_state is not None
        with pytest.raises(UnitreeStateError, match="SportModeState is not fresh"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
        port.release_writer("parcel-runtime")
        assert port.acquire_writer("parcel-runtime") is False
    finally:
        port.close()


def test_sport_stamp_regression_latches_feedback_unreadable() -> None:
    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    port = _port(harness)
    try:
        assert port.acquire_writer("parcel-runtime") is True
        harness.subscribers[0].emit(
            _State(
                [0.0, 0.0, 0.0],
                _Imu([0.0, 0.0, 0.0]),
                0.0,
                mode=3,
                stamp=_Stamp(nanosec=249_999_999),
            )
        )
        with pytest.raises(UnitreeStateError, match="stamp moved backwards"):
            port.state()
        assert port.acquire_writer("parcel-runtime") is False
        with pytest.raises(UnitreeStateError, match="stamp moved backwards"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
    finally:
        port.close()


def test_overlapping_sport_callbacks_serialize_decode_and_keep_entry_time() -> None:
    now = [10.0]
    newer_entered = threading.Event()

    def clock() -> float:
        value = now[0]
        if threading.current_thread().name == "unitree-newer-sport-callback":
            newer_entered.set()
        return value

    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    port = _port(harness, clock=clock)
    older_accessed = threading.Event()
    release_older = threading.Event()
    older = _GatedStateView(
        _State(
            [0.1, 0.0, 0.0],
            _Imu([0.0, 0.0, 0.0]),
            0.0,
            mode=3,
            stamp=_Stamp(nanosec=250_000_001),
        ),
        velocity_accessed=older_accessed,
        release_velocity=release_older,
    )
    newer = _State(
        [0.2, 0.0, 0.0],
        _Imu([0.0, 0.0, 0.0]),
        0.0,
        mode=3,
        stamp=_Stamp(nanosec=250_000_002),
    )
    newer_done = threading.Event()
    older_thread = threading.Thread(
        target=harness.subscribers[0].emit,
        args=(older,),
        name="unitree-older-sport-callback",
    )

    def emit_newer() -> None:
        harness.subscribers[0].emit(newer)
        newer_done.set()

    newer_thread = threading.Thread(
        target=emit_newer,
        name="unitree-newer-sport-callback",
    )
    older_thread.start()
    try:
        assert older_accessed.wait(0.2)
        now[0] = 10.02
        newer_thread.start()
        assert newer_entered.wait(0.2)
        assert not newer_done.wait(0.02)

        # LowState has its own callback lock and can advance while Sport decode
        # is deliberately stalled.
        harness.subscribers[1].emit(_LowState(tick=1235))
        parallel_low = port.state().low_state
        assert parallel_low is not None
        assert parallel_low.tick == 1235

        now[0] = 10.03
        release_older.set()
        older_thread.join(0.2)
        newer_thread.join(0.2)
        assert not older_thread.is_alive()
        assert not newer_thread.is_alive()
        assert newer_done.is_set()
        observed = port.state()
        assert observed.sequence == 3
        assert observed.vx_mps == pytest.approx(0.2)
        assert observed.received_at_monotonic_s == pytest.approx(10.02)
    finally:
        release_older.set()
        older_thread.join(0.2)
        if newer_thread.ident is not None:
            newer_thread.join(0.2)
        port.close()


def test_close_during_overlapping_sport_callbacks_prevents_late_commits() -> None:
    now = [10.0]
    newer_entered = threading.Event()

    def clock() -> float:
        value = now[0]
        if threading.current_thread().name == "unitree-close-newer-sport":
            newer_entered.set()
        return value

    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    port = _port(harness, clock=clock)
    older_accessed = threading.Event()
    release_older = threading.Event()
    never_parse_newer = threading.Event()
    already_released = threading.Event()
    already_released.set()
    older = _GatedStateView(
        _State(
            [0.1, 0.0, 0.0],
            _Imu([0.0, 0.0, 0.0]),
            0.0,
            mode=3,
            stamp=_Stamp(nanosec=250_000_001),
        ),
        velocity_accessed=older_accessed,
        release_velocity=release_older,
    )
    newer = _GatedStateView(
        _State(
            [0.2, 0.0, 0.0],
            _Imu([0.0, 0.0, 0.0]),
            0.0,
            mode=3,
            stamp=_Stamp(nanosec=250_000_002),
        ),
        velocity_accessed=never_parse_newer,
        release_velocity=already_released,
    )
    older_thread = threading.Thread(
        target=harness.subscribers[0].emit,
        args=(older,),
        name="unitree-close-older-sport",
    )
    newer_thread = threading.Thread(
        target=harness.subscribers[0].emit,
        args=(newer,),
        name="unitree-close-newer-sport",
    )
    older_thread.start()
    try:
        assert older_accessed.wait(0.2)
        now[0] = 10.02
        newer_thread.start()
        assert newer_entered.wait(0.2)
        port.close()
        release_older.set()
        older_thread.join(0.2)
        newer_thread.join(0.2)
        assert not older_thread.is_alive()
        assert not newer_thread.is_alive()
        assert never_parse_newer.is_set() is False
        assert port._sequence == 1
        assert port._last_sport_stamp_ns == 1_700_000_000_250_000_000
    finally:
        release_older.set()
        older_thread.join(0.2)
        if newer_thread.ident is not None:
            newer_thread.join(0.2)
        port.close()


def test_low_state_freshness_is_required_even_when_sport_feedback_advances() -> None:
    now = [10.0]
    sport = _State(
        velocity=[0.0, 0.0, 0.0],
        imu_state=_Imu([0.0, 0.0, 0.0]),
        yaw_speed=0.0,
        mode=3,
    )
    harness = _SdkHarness(sport)
    port = _port(harness, clock=lambda: now[0])
    try:
        assert port.acquire_writer("parcel-runtime") is True
        now[0] += STATE_TIMEOUT_S
        sport.stamp.nanosec += 1
        harness.subscribers[0].emit(sport)
        observed = port.state()
        assert observed.low_state is None
        assert observed.commissioned_soc_ok is None
        assert observed.commissioned_soc_reason == "commissioned_soc_unavailable"
        with pytest.raises(UnitreeStateError, match="LowState is not fresh"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
        port.release_writer("parcel-runtime")
        assert port.acquire_writer("parcel-runtime") is False
    finally:
        port.close()


def test_malformed_low_state_marks_soc_gate_unavailable_and_motion_fails_closed() -> None:
    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    port = _port(harness)
    try:
        assert port.acquire_writer("parcel-runtime") is True
        malformed = _LowState(foot_force_est=[1, 2, 3])
        harness.subscribers[1].emit(malformed)
        observed = port.state()
        assert observed.low_state is None
        assert observed.commissioned_soc_ok is None
        assert observed.commissioned_soc_reason == "commissioned_soc_unavailable"
        assert port.acquire_writer("parcel-runtime") is False
        with pytest.raises(UnitreeStateError, match="invalid Unitree LowState"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
    finally:
        port.close()


def test_duplicate_low_state_tick_cannot_renew_freshness() -> None:
    now = [10.0]
    sport = _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3)
    harness = _SdkHarness(sport, low_message=_LowState(tick=77))
    port = _port(harness, clock=lambda: now[0])
    try:
        first = port.state().low_state
        assert first is not None
        assert port.acquire_writer("parcel-runtime") is True
        now[0] += STATE_TIMEOUT_S
        harness.subscribers[1].emit(_LowState(tick=77))
        sport.stamp.nanosec += 1
        harness.subscribers[0].emit(sport)
        observed = port.state()
        assert observed.low_state is None
        assert observed.commissioned_soc_ok is None
        with pytest.raises(UnitreeStateError, match="LowState is not fresh"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
        port.release_writer("parcel-runtime")
        assert port.acquire_writer("parcel-runtime") is False
        assert first.sequence == 1
    finally:
        port.close()


def test_low_state_tick_wraps_forward_but_regression_latches() -> None:
    harness = _SdkHarness(
        _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3),
        low_message=_LowState(tick=2**32 - 1),
    )
    port = _port(harness)
    try:
        harness.subscribers[1].emit(_LowState(tick=0))
        wrapped = port.state().low_state
        assert wrapped is not None
        assert wrapped.sequence == 2
        assert wrapped.tick == 0
        assert port.acquire_writer("parcel-runtime") is True
        harness.subscribers[1].emit(_LowState(tick=2**32 - 1))
        observed = port.state()
        assert observed.low_state is None
        assert observed.commissioned_soc_ok is None
        with pytest.raises(UnitreeStateError, match="tick moved backwards"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
        port.release_writer("parcel-runtime")
        assert port.acquire_writer("parcel-runtime") is False
    finally:
        port.close()


def test_overlapping_low_state_callbacks_serialize_decode_and_keep_entry_time() -> None:
    now = [10.0]
    newer_entered = threading.Event()

    def clock() -> float:
        value = now[0]
        if threading.current_thread().name == "unitree-newer-low-state-callback":
            newer_entered.set()
        return value

    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    port = _port(harness, clock=clock)
    older_accessed = threading.Event()
    release_older = threading.Event()
    older = _GatedLowStateView(
        _LowState(tick=1235),
        tick_accessed=older_accessed,
        release_tick=release_older,
    )
    newer = _LowState(tick=1236)
    newer_done = threading.Event()
    older_thread = threading.Thread(
        target=harness.subscribers[1].emit,
        args=(older,),
        name="unitree-older-low-state-callback",
    )

    def emit_newer() -> None:
        harness.subscribers[1].emit(newer)
        newer_done.set()

    newer_thread = threading.Thread(
        target=emit_newer,
        name="unitree-newer-low-state-callback",
    )
    older_thread.start()
    try:
        assert older_accessed.wait(0.2)
        now[0] = 10.02
        newer_thread.start()
        assert newer_entered.wait(0.2)
        assert not newer_done.wait(0.02)
        now[0] = 10.03
        release_older.set()
        older_thread.join(0.2)
        newer_thread.join(0.2)
        assert not older_thread.is_alive()
        assert not newer_thread.is_alive()
        assert newer_done.is_set()
        observed = port.state().low_state
        assert observed is not None
        assert observed.sequence == 3
        assert observed.tick == 1236
        assert observed.received_at_monotonic_s == pytest.approx(10.02)
    finally:
        release_older.set()
        older_thread.join(0.2)
        if newer_thread.ident is not None:
            newer_thread.join(0.2)
        port.close()


def test_commissioned_battery_floor_refuses_authority_and_move() -> None:
    harness = _SdkHarness(
        _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3),
        low_message=_LowState(tick=1, bms_state=_BmsState(soc=8)),
    )
    port = _port(harness)
    try:
        unhealthy = port.state()
        assert unhealthy.commissioned_soc_ok is False
        assert unhealthy.commissioned_soc_reason == "soc_at_or_below_commissioned_minimum"
        assert port.acquire_writer("parcel-runtime") is False

        harness.subscribers[1].emit(_LowState(tick=2, bms_state=_BmsState(soc=9)))
        assert port.acquire_writer("parcel-runtime") is True
        harness.subscribers[1].emit(_LowState(tick=3, bms_state=_BmsState(soc=8)))
        with pytest.raises(UnitreeStateError, match="soc_at_or_below"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
        assert harness.client.moves == []
    finally:
        port.close()


def test_mode_and_vendor_error_are_not_positive_motion_evidence() -> None:
    harness = _SdkHarness(
        _State(
            velocity=[0.0, 0.0, 0.0],
            imu_state=_Imu([0.0, 0.0, 0.0]),
            yaw_speed=0.0,
            mode=3,
        )
    )
    port = _port(harness)
    try:
        assert port.acquire_writer("parcel-runtime") is True
        harness.subscribers[0].emit(
            _State(
                [0.0, 0.0, 0.0],
                _Imu([0.0, 0.0, 0.0]),
                0.0,
                mode=9,
                stamp=_Stamp(nanosec=250_000_001),
            )
        )
        invalid_mode = port.state()
        assert invalid_mode.feedback_integrity_ok is False
        assert invalid_mode.feedback_integrity_reason == "sport_mode_not_commissioned_9"
        assert port.acquire_writer("parcel-runtime") is False
        with pytest.raises(UnitreeStateError, match="not commissioned"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
        harness.subscribers[0].emit(
            _State(
                [0.0, 0.0, 0.0],
                _Imu([0.0, 0.0, 0.0]),
                0.0,
                mode=3,
                error_code=8,
                stamp=_Stamp(nanosec=250_000_002),
            )
        )
        invalid_error = port.state()
        assert invalid_error.feedback_integrity_ok is False
        assert invalid_error.feedback_integrity_reason == "sport_error_code_not_commissioned_8"
        assert port.acquire_writer("parcel-runtime") is False
        with pytest.raises(UnitreeStateError, match="error_code 8 is not commissioned"):
            port.move(
                writer_id="parcel-runtime",
                vx_mps=0.1,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
            )
        assert harness.client.moves == []
    finally:
        port.close()


def test_commissioned_nonzero_vendor_error_can_be_positive_motion_evidence() -> None:
    harness = _SdkHarness(
        _State(
            [0.0, 0.0, 0.0],
            _Imu([0.0, 0.0, 0.0]),
            0.0,
            mode=3,
            error_code=8,
        )
    )
    port = _port(harness, config=_config(allowed_error_codes=(8,)))
    try:
        observed = port.state()
        assert observed.feedback_integrity_ok is True
        assert observed.feedback_integrity_reason == "ok"
        assert port.acquire_writer("parcel-runtime") is True
        port.move(
            writer_id="parcel-runtime",
            vx_mps=0.1,
            vy_mps=0.0,
            vyaw_rad_s=0.0,
        )
        assert harness.client.moves == [(0.1, -0.0, -0.0)]
    finally:
        port.close()


def test_client_init_failure_stops_and_closes_after_client_creation() -> None:
    harness = _SdkHarness(
        _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3),
        client_init_error=RuntimeError("client init failed"),
    )
    with pytest.raises(UnitreeSportError, match="initialization failed") as raised:
        _port(harness)
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert harness.subscribers == []
    assert harness.client.stop_calls == 1
    assert harness.client.close_calls == 0
    assert all(subscriber.closed.wait(0.2) for subscriber in harness.subscribers)


def test_defensive_stop_precedes_readers_when_low_state_never_arrives() -> None:
    harness = _SdkHarness(
        _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3),
        emit_low_state=False,
    )

    with pytest.raises(UnitreeSportError, match="fresh LowState"):
        _port(
            harness,
            config=_config(rpc_timeout_s=0.01, startup_timeout_s=0.02),
        )

    assert harness.events[:5] == [
        "channel_initialize",
        "client_factory",
        "client_set_timeout",
        "client_init",
        "stop_move",
    ]
    first_reader_event = min(
        index
        for index, event in enumerate(harness.events)
        if event.startswith(("subscriber_factory:", "subscriber_init:"))
    )
    assert harness.events.index("stop_move") < first_reader_event
    assert harness.client.stop_calls == 2
    assert len(harness.subscribers) == 2
    assert all(subscriber.closed.wait(0.2) for subscriber in harness.subscribers)


def test_defensive_startup_stop_result_failure_refuses_all_readers() -> None:
    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    harness.client.stop_result = 19

    with pytest.raises(UnitreeSportError, match="failed with SDK result 19"):
        _port(harness)

    assert harness.subscribers == []
    assert not any(event.startswith("subscriber_") for event in harness.events)
    # The required call failed, then initialization cleanup made one bounded
    # final attempt before discarding the client.
    assert harness.client.stop_calls == 2


def test_defensive_startup_stop_exception_refuses_all_readers() -> None:
    def raise_stop() -> None:
        raise RuntimeError("vendor stop failed")

    harness = _SdkHarness(
        _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3),
        client_stop_hook=raise_stop,
    )

    with pytest.raises(UnitreeSportError, match="startup StopMove raised") as raised:
        _port(harness)

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert harness.subscribers == []
    assert harness.client.stop_calls == 2


def test_defensive_startup_stop_timeout_is_bounded_and_not_reentered() -> None:
    release_stop = threading.Event()
    harness = _SdkHarness(
        _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3),
        client_stop_hook=release_stop.wait,
    )
    started = time.monotonic()
    try:
        with pytest.raises(UnitreeSportError, match="startup StopMove timed out"):
            _port(
                harness,
                config=_config(rpc_timeout_s=0.02, startup_timeout_s=0.1),
            )
        elapsed = time.monotonic() - started
        assert elapsed < 0.1
        assert harness.client.stop_entered.is_set()
        assert harness.client.stop_calls == 1
        assert harness.subscribers == []
    finally:
        release_stop.set()


def test_startup_decode_failure_stops_and_closes_after_client_initialization() -> None:
    harness = _SdkHarness(
        _State(
            [0.0, 0.0, 0.0],
            _Imu([0.0, 0.0, 0.0]),
            0.0,
            mode=3,
        ),
        low_message=_LowState(foot_force_est=[1, 2, 3]),
    )
    with pytest.raises(UnitreeStateError, match="invalid Unitree LowState"):
        _port(harness)
    assert harness.client.stop_calls == 2
    assert harness.client.close_calls == 0
    assert all(subscriber.closed.wait(0.2) for subscriber in harness.subscribers)


def test_normal_close_stops_and_closes_exactly_once() -> None:
    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    port = _port(harness)
    port.close()
    port.close()
    assert harness.client.stop_calls == 2
    assert harness.client.close_calls == 0
    assert all(subscriber.closed.wait(0.2) for subscriber in harness.subscribers)
    assert all(subscriber.close_calls == 1 for subscriber in harness.subscribers)


def test_hung_final_stop_cannot_block_close_past_the_rpc_budget() -> None:
    release_stop = threading.Event()
    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    port = _port(harness, config=_config(rpc_timeout_s=0.02, startup_timeout_s=0.1))
    harness.client.stop_hook = release_stop.wait
    harness.client.stop_entered.clear()
    started = time.monotonic()
    try:
        port.close()
        elapsed = time.monotonic() - started
        assert harness.client.stop_entered.is_set()
        assert elapsed < 0.1
        assert all(subscriber.closed.wait(0.1) for subscriber in harness.subscribers)
    finally:
        release_stop.set()


def test_hung_final_stop_and_both_reader_closes_have_an_aggregate_bound() -> None:
    release_cleanup = threading.Event()
    rpc_timeout_s = 0.02
    harness = _SdkHarness(
        _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3),
        subscriber_close_hook=release_cleanup.wait,
    )
    port = _port(
        harness,
        config=_config(rpc_timeout_s=rpc_timeout_s, startup_timeout_s=0.1),
    )
    harness.client.stop_hook = release_cleanup.wait
    harness.client.stop_entered.clear()
    started = time.monotonic()
    try:
        port.close()
        elapsed = time.monotonic() - started
        assert harness.client.stop_entered.is_set()
        assert all(subscriber.close_entered.is_set() for subscriber in harness.subscribers)
        assert elapsed < 3 * rpc_timeout_s + 0.08
    finally:
        release_cleanup.set()
    assert all(subscriber.closed.wait(0.2) for subscriber in harness.subscribers)


def test_raising_final_stop_and_subscriber_cleanup_are_best_effort() -> None:
    def raise_stop() -> None:
        raise RuntimeError("stop cleanup failed")

    def raise_subscriber_close() -> None:
        raise RuntimeError("subscriber cleanup failed")

    harness = _SdkHarness(
        _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3),
        subscriber_close_hook=raise_subscriber_close,
    )
    port = _port(harness)
    harness.client.stop_hook = raise_stop
    port.close()
    port.close()
    assert harness.client.stop_calls == 2
    assert harness.client.close_calls == 0
    assert all(subscriber.close_entered.wait(0.2) for subscriber in harness.subscribers)
    assert all(subscriber.close_calls == 1 for subscriber in harness.subscribers)


def test_cleanup_thread_start_failure_does_not_abort_remaining_cleanup(monkeypatch) -> None:
    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    port = _port(harness)
    original_start = threading.Thread.start
    attempts = 0

    def fail_first_start(thread: threading.Thread) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("thread resources exhausted")
        original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_first_start)
    port.close()
    assert harness.client.stop_calls == 1
    assert all(subscriber.closed.wait(0.2) for subscriber in harness.subscribers)


def test_init_error_survives_cleanup_thread_resource_exhaustion(monkeypatch) -> None:
    harness = _SdkHarness(
        _State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3),
        client_init_error=RuntimeError("original init failure"),
    )

    def refuse_start(_thread: threading.Thread) -> None:
        raise RuntimeError("thread resources exhausted")

    monkeypatch.setattr(threading.Thread, "start", refuse_start)
    with pytest.raises(UnitreeSportError, match="initialization failed") as raised:
        _port(harness)
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "original init failure"


def test_process_authority_is_not_released_by_close() -> None:
    authority = _UnitreeProcessAuthorityV1()
    first_harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    first = _port(first_harness, authority=authority)
    first.close()
    second_harness = _SdkHarness(first_harness.message)
    with pytest.raises(UnitreeAuthorityError, match="already claimed"):
        _port(second_harness, authority=authority)
    assert second_harness.channel_initializations == []


def test_missing_nic_and_missing_sdk_fail_before_any_writer_exists(monkeypatch) -> None:
    harness = _SdkHarness(_State([0.0, 0.0, 0.0], _Imu([0.0, 0.0, 0.0]), 0.0, mode=3))
    with pytest.raises(UnitreeSportError, match="does not exist"):
        UnitreeSdk2SportPortV1(
            _config(),
            _bindings=harness.bindings(),
            _interface_exists=lambda _interface: False,
            _authority=_UnitreeProcessAuthorityV1(),
        )
    assert harness.channel_initializations == []

    def absent(_name: str):
        raise ModuleNotFoundError("optional SDK absent")

    monkeypatch.setattr(ports_module.importlib, "import_module", absent)
    with pytest.raises(UnitreeSdkUnavailableError, match="unavailable or incompatible"):
        ports_module.load_unitree_sdk_bindings()


def test_production_cli_resolves_explicit_vendor_environment_and_dispatches(
    monkeypatch, tmp_path
) -> None:
    args = cli_module._parser().parse_args(
        [
            "--disarmed",
            "--sport",
            "vendor",
            "--socket",
            str(tmp_path / "gateway.sock"),
            "--audit-log",
            str(tmp_path / "audit.jsonl"),
        ]
    )
    environment = {
        "PARCEL_ARMED": "0",
        "PARCEL_GATEWAY_CONFIG_SHA256": "1" * 64,
        "PARCEL_GATEWAY_CAPABILITY_SHA256": "2" * 64,
        "PARCEL_GATEWAY_CALIBRATION_SHA256": "3" * 64,
        "PARCEL_GATEWAY_FIRMWARE_SHA256": "4" * 64,
        "PARCEL_GATEWAY_CLIENT_UID": str(os.geteuid()),
        "PARCEL_GATEWAY_CLIENT_GID": str(os.getegid()),
        "PARCEL_GATEWAY_STOP_CLIENT_UID": str(os.geteuid() + 1),
        "PARCEL_GATEWAY_SOCKET_MODE": "0660",
        "PARCEL_UNITREE_INTERFACE": "robot0",
        "PARCEL_UNITREE_DOMAIN_ID": "0",
        "PARCEL_UNITREE_ALLOWED_MODES": "3,5",
        "PARCEL_UNITREE_ALLOWED_ERROR_CODES": "0",
        "PARCEL_UNITREE_STATE_VELOCITY_FRAME": "base_link",
        "PARCEL_UNITREE_LATERAL_SIGN": "1",
        "PARCEL_UNITREE_YAW_SIGN": "-1",
        "PARCEL_UNITREE_AXES_COMMISSIONED": "true",
        "PARCEL_UNITREE_STATE_FRAME_COMMISSIONED": "1",
        "PARCEL_UNITREE_SPORT_STATE_STAMP_MONOTONIC_COMMISSIONED": "1",
        "PARCEL_UNITREE_BATTERY_SOC_PERCENT_COMMISSIONED": "1",
        "PARCEL_UNITREE_MINIMUM_BATTERY_SOC_PERCENT": "8",
        "PARCEL_UNITREE_LOW_STATE_TICK_MONOTONIC_COMMISSIONED": "1",
    }
    settings = cli_module.settings_from(args, environment)
    assert settings.unitree_config == _config(
        allowed_modes=(3, 5),
        state_velocity_frame="base_link",
        lateral_sign=1,
    )
    assert settings.required_hashes.config_sha256 == "1" * 64
    assert settings.required_hashes != process_module.BENCH_HASHES
    assert cli_module._policy_from_settings(settings).required_hashes == settings.required_hashes
    made = object()
    seen = []
    monkeypatch.setattr(
        cli_module,
        "UnitreeSdk2SportPortV1",
        lambda config, **_kwargs: seen.append(config) or made,
    )
    assert cli_module._build_sport(settings) is made
    assert seen == [settings.unitree_config]

    non_direct_callback = dict(environment)
    non_direct_callback["PARCEL_UNITREE_SUBSCRIBER_QUEUE_DEPTH"] = "1"
    with pytest.raises(cli_module.GatewayLaunchError, match="must be exactly 0"):
        cli_module.settings_from(args, non_direct_callback)


def test_bench_cli_vendor_dispatch_is_explicit_and_fake_stays_sdk_free(monkeypatch) -> None:
    vendor_arguments = [
        "--socket",
        "/tmp/parcel-unitree-test.sock",
        "--audit-log",
        "/tmp/parcel-unitree-test.jsonl",
        "--sport",
        "vendor",
        "--unitree-interface",
        "robot0",
        "--unitree-domain-id",
        "0",
        "--unitree-allowed-mode",
        "3",
        "--unitree-allowed-error-code",
        "0",
        "--unitree-state-velocity-frame",
        "base_link",
        "--unitree-lateral-sign",
        "1",
        "--unitree-yaw-sign",
        "1",
        "--unitree-axes-commissioned",
        "--unitree-state-frame-commissioned",
        "--unitree-sport-state-stamp-monotonic-commissioned",
        "--unitree-battery-soc-percent-commissioned",
        "--unitree-minimum-battery-soc-percent",
        "8",
        "--unitree-low-state-tick-monotonic-commissioned",
    ]
    vendor_args = process_module._parser().parse_args(vendor_arguments)
    made = object()
    constructed = []
    monkeypatch.setattr(
        process_module,
        "UnitreeSdk2SportPortV1",
        lambda config, **_kwargs: constructed.append(config) or made,
    )
    with pytest.raises(SystemExit, match="launch compatibility hashes"):
        process_module._build_sport(vendor_args)
    assert constructed == []
    vendor_args = process_module._parser().parse_args(
        vendor_arguments
        + [
            "--config-sha256",
            "1" * 64,
            "--capability-sha256",
            "2" * 64,
            "--calibration-sha256",
            "3" * 64,
            "--firmware-sha256",
            "4" * 64,
        ]
    )
    assert process_module._build_sport(vendor_args) is made
    assert constructed == [_config(state_velocity_frame="base_link", lateral_sign=1, yaw_sign=1)]
    assert process_module._required_hashes_from_args(vendor_args).config_sha256 == "1" * 64

    def sdk_must_not_run(_config):
        raise AssertionError("fake path loaded SDK2")

    monkeypatch.setattr(process_module, "UnitreeSdk2SportPortV1", sdk_must_not_run)
    fake_args = process_module._parser().parse_args(
        ["--socket", "/tmp/fake.sock", "--audit-log", "/tmp/fake.jsonl"]
    )
    fake = process_module._build_sport(fake_args)
    try:
        assert fake.state().lease_active is False
    finally:
        fake.close()


@pytest.mark.parametrize(
    ("option", "takes_value"),
    [
        ("--unitree-allowed-error-code", True),
        ("--unitree-sport-state-stamp-monotonic-commissioned", False),
        ("--unitree-battery-soc-percent-commissioned", False),
        ("--unitree-minimum-battery-soc-percent", True),
        ("--unitree-low-state-tick-monotonic-commissioned", False),
    ],
)
def test_bench_vendor_soc_commissioning_is_never_implicit(
    option: str,
    takes_value: bool,
) -> None:
    arguments = [
        "--socket",
        "/tmp/parcel-unitree-test.sock",
        "--audit-log",
        "/tmp/parcel-unitree-test.jsonl",
        "--sport",
        "vendor",
        "--config-sha256",
        "1" * 64,
        "--capability-sha256",
        "2" * 64,
        "--calibration-sha256",
        "3" * 64,
        "--firmware-sha256",
        "4" * 64,
        "--unitree-interface",
        "robot0",
        "--unitree-domain-id",
        "0",
        "--unitree-allowed-mode",
        "3",
        "--unitree-allowed-error-code",
        "0",
        "--unitree-state-velocity-frame",
        "base_link",
        "--unitree-lateral-sign",
        "1",
        "--unitree-yaw-sign",
        "1",
        "--unitree-axes-commissioned",
        "--unitree-state-frame-commissioned",
        "--unitree-sport-state-stamp-monotonic-commissioned",
        "--unitree-battery-soc-percent-commissioned",
        "--unitree-minimum-battery-soc-percent",
        "8",
        "--unitree-low-state-tick-monotonic-commissioned",
    ]
    index = arguments.index(option)
    del arguments[index : index + (2 if takes_value else 1)]
    args = process_module._parser().parse_args(arguments)
    with pytest.raises(SystemExit, match=option):
        process_module._build_sport(args)


def test_both_entrypoints_reject_an_sdk_callback_queue() -> None:
    with pytest.raises(SystemExit):
        process_module._parser().parse_args(
            [
                "--socket",
                "/tmp/bench.sock",
                "--audit-log",
                "/tmp/bench.jsonl",
                "--unitree-subscriber-queue-depth",
                "1",
            ]
        )
    with pytest.raises(SystemExit):
        cli_module._parser().parse_args(["--unitree-subscriber-queue-depth", "1"])


def test_production_vendor_hashes_are_required_and_sha256_valid(tmp_path) -> None:
    args = cli_module._parser().parse_args(
        [
            "--disarmed",
            "--sport",
            "vendor",
            "--socket",
            str(tmp_path / "gateway.sock"),
            "--audit-log",
            str(tmp_path / "audit.jsonl"),
        ]
    )
    physical = {
        "PARCEL_ARMED": "0",
        "PARCEL_GATEWAY_CLIENT_UID": str(os.geteuid()),
        "PARCEL_GATEWAY_CLIENT_GID": str(os.getegid()),
        "PARCEL_GATEWAY_STOP_CLIENT_UID": str(os.geteuid() + 1),
        "PARCEL_GATEWAY_SOCKET_MODE": "0660",
        "PARCEL_UNITREE_INTERFACE": "robot0",
        "PARCEL_UNITREE_DOMAIN_ID": "0",
        "PARCEL_UNITREE_ALLOWED_MODES": "3",
        "PARCEL_UNITREE_ALLOWED_ERROR_CODES": "0",
        "PARCEL_UNITREE_STATE_VELOCITY_FRAME": "base_link",
        "PARCEL_UNITREE_LATERAL_SIGN": "1",
        "PARCEL_UNITREE_YAW_SIGN": "1",
        "PARCEL_UNITREE_AXES_COMMISSIONED": "1",
        "PARCEL_UNITREE_STATE_FRAME_COMMISSIONED": "1",
        "PARCEL_UNITREE_SPORT_STATE_STAMP_MONOTONIC_COMMISSIONED": "1",
        "PARCEL_UNITREE_BATTERY_SOC_PERCENT_COMMISSIONED": "1",
        "PARCEL_UNITREE_MINIMUM_BATTERY_SOC_PERCENT": "8",
        "PARCEL_UNITREE_LOW_STATE_TICK_MONOTONIC_COMMISSIONED": "1",
    }
    with pytest.raises(cli_module.GatewayLaunchError, match="launch compatibility hashes"):
        cli_module.settings_from(args, physical)
    physical.update(
        {
            "PARCEL_GATEWAY_CONFIG_SHA256": "not-a-sha256",
            "PARCEL_GATEWAY_CAPABILITY_SHA256": "2" * 64,
            "PARCEL_GATEWAY_CALIBRATION_SHA256": "3" * 64,
            "PARCEL_GATEWAY_FIRMWARE_SHA256": "4" * 64,
        }
    )
    with pytest.raises(cli_module.GatewayLaunchError, match="invalid launch compatibility hash"):
        cli_module.settings_from(args, physical)
    physical.update(
        {
            "PARCEL_GATEWAY_CONFIG_SHA256": process_module.BENCH_HASHES.config_sha256,
            "PARCEL_GATEWAY_CAPABILITY_SHA256": (process_module.BENCH_HASHES.capability_sha256),
            "PARCEL_GATEWAY_CALIBRATION_SHA256": (process_module.BENCH_HASHES.calibration_sha256),
            "PARCEL_GATEWAY_FIRMWARE_SHA256": process_module.BENCH_HASHES.firmware_sha256,
        }
    )
    with pytest.raises(cli_module.GatewayLaunchError, match="BENCH_HASHES"):
        cli_module.settings_from(args, physical)


def test_failed_gateway_boot_construction_closes_the_sport(monkeypatch) -> None:
    class Sport:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    sport = Sport()

    def fail_core(*_args: object, **_kwargs: object):
        raise RuntimeError("boot StopMove failed")

    monkeypatch.setattr(process_module, "GatewayCoreV1", fail_core)
    with pytest.raises(RuntimeError, match="boot StopMove failed"):
        process_module.construct_core_or_close_sport(
            sport,
            policy=object(),
            limits=default_limits(),
            audit=BoundedAuditRingV1(),
        )
    assert sport.closed is True


def test_gateway_shutdown_closes_core_first_and_isolates_ancillary_failures() -> None:
    events: list[str] = []

    class Core:
        def close(self) -> None:
            events.append("core")

    def broken_notifier() -> None:
        events.append("notifier")
        raise RuntimeError("notifier cleanup failed")

    def exporter() -> None:
        events.append("exporter")

    process_module._close_core_then_cleanup(Core(), (broken_notifier, exporter))
    assert events == ["core", "notifier", "exporter"]
