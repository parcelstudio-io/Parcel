from __future__ import annotations

import math
import threading
import time
from types import SimpleNamespace

import pytest

from parcel_robot.control import (
    BackendVelocityController,
    ControllerCapabilities,
    ControlLifecycle,
    ControlLimits,
    ControlManager,
    ControlNotReadyError,
    ControlTiming,
    RobotMotionState,
    TimedVelocitySetpoint,
    UnitreeChannelContext,
    UnitreeSportController,
    UnitreeSportStateSource,
    build_unitree_sport_control_manager,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.safety import SafetyLimits


class FakeClock:
    def __init__(self, now: float = 10.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeStateSource:
    name = "fake_state"

    def __init__(self, state: RobotMotionState | None = None) -> None:
        self.state = state
        self.started = 0
        self.closed = 0

    def start(self) -> None:
        self.started += 1

    def latest(self) -> RobotMotionState | None:
        return self.state

    def close(self) -> None:
        self.closed += 1


class RecordingController:
    name = "recording"
    capabilities = ControllerCapabilities()

    def __init__(self) -> None:
        self.activated = 0
        self.updates: list[tuple[TimedVelocitySetpoint, RobotMotionState, float]] = []
        self.update_delivered = threading.Event()
        self.stops: list[str] = []
        self.emergency_stops = 0
        self.emergency_delivered = threading.Event()
        self.clears = 0
        self.closed = 0
        self.update_error: Exception | None = None
        self.stop_failures = 0

    def activate(self) -> None:
        self.activated += 1

    def update(
        self,
        target: TimedVelocitySetpoint,
        state: RobotMotionState,
        *,
        now: float,
    ) -> None:
        if self.update_error is not None:
            raise self.update_error
        self.updates.append((target, state, now))
        self.update_delivered.set()

    def stop(self, reason: str) -> None:
        self.stops.append(reason)
        if self.stop_failures:
            self.stop_failures -= 1
            raise RuntimeError("stop transport offline")

    def emergency_stop(self) -> None:
        self.emergency_stops += 1
        self.emergency_delivered.set()

    def clear_emergency_stop(self) -> None:
        self.clears += 1

    def close(self) -> None:
        self.closed += 1


def _state(now: float, sequence: int = 1, **overrides) -> RobotMotionState:
    values = {
        "received_at": now,
        "sequence": sequence,
        "velocity": VelocityCommand(),
        "mode": 1,
        "source": "test",
    }
    values.update(overrides)
    return RobotMotionState(**values)


def _capture_error(call, errors: list[Exception]) -> None:
    try:
        call()
    except Exception as error:  # noqa: BLE001 - race tests assert captured failures
        errors.append(error)


def _manager(clock: FakeClock):
    source = FakeStateSource(_state(clock()))
    controller = RecordingController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(
            control_hz=50.0,
            command_timeout_s=0.3,
            state_timeout_s=0.2,
            startup_timeout_s=0.5,
            stop_settled_samples=1,
        ),
        clock=clock,
    )
    manager.start(threaded=False)
    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    return manager, controller, source


@pytest.mark.parametrize(
    "kwargs",
    [
        {"control_hz": 0.0},
        {"command_timeout_s": math.inf},
        {"state_timeout_s": -1.0},
        {"startup_timeout_s": math.nan},
        {"io_quiesce_timeout_s": math.inf},
    ],
)
def test_control_timing_rejects_invalid_values(kwargs) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        ControlTiming(**kwargs)


@pytest.mark.parametrize("samples", [0, -1, 1.5, True])
def test_control_timing_rejects_invalid_stop_sample_count(samples) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        ControlTiming(stop_settled_samples=samples)


def test_start_requires_distinct_post_stop_feedback_samples() -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock(), sequence=1))
    controller = RecordingController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(stop_settled_samples=2),
        clock=clock,
    )

    manager.start(threaded=False)
    manager.tick(now=clock())
    assert not manager.snapshot(now=clock()).stop_confirmed

    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.STOPPING

    # Polling the same sample twice must not manufacture two confirmations.
    manager.tick(now=clock())
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.STOPPING

    clock.advance(0.001)
    source.state = _state(clock(), sequence=3)
    manager.tick(now=clock())
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.IDLE


def test_simulator_adapter_stops_before_first_move_without_feedback_handshake() -> None:
    class Backend:
        name = "sim"

        def __init__(self) -> None:
            self.actions: list[object] = []

        def stop(self) -> None:
            self.actions.append("stop")

        def move(self, command: VelocityCommand) -> None:
            self.actions.append(command)

    clock = FakeClock()
    backend = Backend()
    source = FakeStateSource(_state(clock()))
    controller = BackendVelocityController(backend)
    manager = ControlManager(controller, source, clock=clock)

    manager.start(threaded=False)
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.IDLE
    assert backend.actions == []

    manager.set_target(VelocityCommand(vx=0.1), source="manual")
    manager.tick(now=clock())

    assert backend.actions == ["stop", VelocityCommand(vx=0.1)]
    manager.close()
    assert backend.actions[-1] == "stop"


def test_emergency_stop_before_start_blocks_activation_until_cleared() -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))
    controller = RecordingController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(stop_settled_samples=1),
        clock=clock,
    )

    manager.emergency_stop()
    assert manager.snapshot(now=clock()).emergency_stopped
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.DISARMED
    assert controller.emergency_stops == 0

    with pytest.raises(ControlNotReadyError, match="pre-start emergency stop"):
        manager.start(threaded=False)
    assert controller.activated == 0
    manager.clear_emergency_stop()

    manager.start(threaded=False)
    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())

    assert controller.clears == 0
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.IDLE


def test_manager_applies_leased_target_and_stops_exactly_at_deadline() -> None:
    clock = FakeClock()
    manager, controller, source = _manager(clock)
    initial_stops = len(controller.stops)

    target = manager.set_target(VelocityCommand(vx=0.2), source="manual", ttl=0.3)
    manager.tick(now=clock())

    assert controller.updates[-1][0] == target
    assert manager.snapshot().lifecycle == ControlLifecycle.ACTIVE

    clock.advance(0.299)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    assert manager.snapshot().lifecycle == ControlLifecycle.ACTIVE

    clock.now = target.valid_until
    source.state = _state(clock(), sequence=3)
    manager.tick(now=clock())
    status = manager.snapshot(now=clock())
    assert status.lifecycle == ControlLifecycle.STOPPING
    assert not status.stop_confirmed
    assert status.watchdog_stops == 1
    assert len(controller.stops) == initial_stops + 1

    clock.advance(0.001)
    source.state = _state(clock(), sequence=4)
    manager.tick(now=clock())
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.IDLE


def test_target_that_expires_during_delivery_is_compensated_with_stop() -> None:
    clock = FakeClock()

    class SlowController(RecordingController):
        def update(self, target, state, *, now: float) -> None:
            super().update(target, state, now=now)
            clock.advance(0.31)

    source = FakeStateSource(_state(clock()))
    controller = SlowController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(stop_settled_samples=1),
        clock=clock,
    )
    manager.start(threaded=False)
    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    manager.set_target(VelocityCommand(vx=0.1), source="manual", ttl=0.3)

    manager.tick(now=clock())

    status = manager.snapshot(now=clock())
    assert status.target == VelocityCommand()
    assert status.watchdog_stops == 1
    assert controller.stops[-1] == "command_expired_during_delivery"


def test_manager_rejects_nonfinite_and_overlimit_targets() -> None:
    clock = FakeClock()
    manager, controller, _ = _manager(clock)

    with pytest.raises(ValueError, match="finite"):
        manager.set_target(VelocityCommand(vx=math.nan), source="manual")
    with pytest.raises(ValueError, match="physical limit"):
        manager.set_target(VelocityCommand(vx=0.61), source="manual")

    assert not controller.updates


def test_stale_robot_state_stops_and_latches_fault() -> None:
    clock = FakeClock()
    manager, controller, _ = _manager(clock)
    manager.set_target(VelocityCommand(vyaw=0.2), source="navigation")
    manager.tick(now=clock())

    clock.advance(0.201)
    manager.tick(now=clock())

    status = manager.snapshot(now=clock())
    assert status.lifecycle == ControlLifecycle.FAULTED
    assert status.fault == "robot_state_stale"
    assert controller.stops[-1] == "robot_state_stale"
    with pytest.raises(ControlNotReadyError, match="faulted"):
        manager.set_target(VelocityCommand(vx=0.1), source="manual")


def test_controller_exception_fails_closed() -> None:
    clock = FakeClock()
    manager, controller, source = _manager(clock)
    controller.update_error = RuntimeError("transport offline")
    manager.set_target(VelocityCommand(vx=0.1), source="follow")

    manager.tick(now=clock())

    status = manager.snapshot(now=clock())
    assert status.lifecycle == ControlLifecycle.FAULTED
    assert "transport offline" in str(status.fault)
    assert controller.stops[-1].startswith("controller_update_failed")
    with pytest.raises(ControlNotReadyError, match="physical stopping"):
        manager.clear_fault()

    clock.advance(0.001)
    source.state = _state(clock(), sequence=3)
    manager.clear_fault()
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.IDLE


def test_failed_stop_is_retried_while_feedback_still_reports_motion() -> None:
    clock = FakeClock()
    manager, controller, source = _manager(clock)
    manager.set_target(VelocityCommand(vx=0.2), source="manual")
    manager.tick(now=clock())
    source.state = _state(clock(), sequence=2, velocity=VelocityCommand(vx=0.2))
    controller.stop_failures = 1

    with pytest.raises(RuntimeError, match="stop transport offline"):
        manager.stop("operator_stop")

    failed_count = len(controller.stops)
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.FAULTED
    clock.advance(manager.timing.stop_retry_s + 0.001)
    source.state = _state(clock(), sequence=3, velocity=VelocityCommand(vx=0.15))
    manager.tick(now=clock())

    assert len(controller.stops) == failed_count + 1
    assert controller.stops[-1] == "fault_stop_retry"


def test_threaded_state_source_failure_faults_and_attempts_stop() -> None:
    source = FakeStateSource(_state(time.monotonic()))
    source.latest_error = None
    original_latest = source.latest

    def latest():
        if source.latest_error is not None:
            raise source.latest_error
        return original_latest()

    source.latest = latest
    controller = RecordingController()
    controller.capabilities = ControllerCapabilities(requires_stop_confirmation=False)
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(
            control_hz=100.0,
            state_timeout_s=0.5,
            stop_settled_samples=1,
        ),
    )
    manager.start()
    source.state = _state(time.monotonic(), sequence=2)
    try:
        deadline = time.monotonic() + 0.5
        while manager.snapshot().lifecycle != ControlLifecycle.IDLE:
            assert time.monotonic() < deadline
            time.sleep(0.005)
        manager.set_target(VelocityCommand(vx=0.1), source="manual")
        assert controller.update_delivered.wait(0.5)
        source.latest_error = RuntimeError("feedback callback failed")

        deadline = time.monotonic() + 0.5
        while manager.snapshot().lifecycle != ControlLifecycle.FAULTED:
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert any(reason.startswith("robot_state_read_failed") for reason in controller.stops)
    finally:
        source.latest_error = None
        source.state = _state(time.monotonic(), sequence=3)
        manager.close()


class BlockingUpdateController(RecordingController):
    def __init__(self) -> None:
        super().__init__()
        self.update_started = threading.Event()
        self.release_update = threading.Event()
        self.actions: list[str] = []

    def update(self, target, state, *, now: float) -> None:
        del target, state, now
        self.update_started.set()
        assert self.release_update.wait(1.0)
        self.actions.append("move")

    def stop(self, reason: str) -> None:
        del reason
        self.actions.append("stop")

    def emergency_stop(self) -> None:
        self.actions.append("emergency_stop")
        self.emergency_delivered.set()


class BlockingActivateController(RecordingController):
    def __init__(self) -> None:
        super().__init__()
        self.activate_started = threading.Event()
        self.release_activate = threading.Event()

    def activate(self) -> None:
        self.activate_started.set()
        assert self.release_activate.wait(1.0)
        super().activate()


class BlockingClearController(RecordingController):
    capabilities = ControllerCapabilities(requires_stop_confirmation=False)

    def __init__(self) -> None:
        super().__init__()
        self.clear_started = threading.Event()
        self.release_clear = threading.Event()

    def clear_emergency_stop(self) -> None:
        self.clear_started.set()
        assert self.release_clear.wait(1.0)
        super().clear_emergency_stop()


class BlockingCloseController(RecordingController):
    def __init__(self) -> None:
        super().__init__()
        self.close_started = threading.Event()
        self.release_close = threading.Event()
        self.close_in_progress = False
        self.stop_overlapped_close = False

    def stop(self, reason: str) -> None:
        if self.close_in_progress:
            self.stop_overlapped_close = True
        super().stop(reason)

    def close(self) -> None:
        self.close_in_progress = True
        self.close_started.set()
        assert self.release_close.wait(1.0)
        self.close_in_progress = False
        super().close()


def test_emergency_stop_latches_while_passive_activation_is_in_flight() -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))
    controller = BlockingActivateController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(stop_settled_samples=1),
        clock=clock,
    )
    errors: list[Exception] = []

    def start_manager() -> None:
        try:
            manager.start(threaded=False)
        except Exception as error:  # noqa: BLE001 - asserted below
            errors.append(error)

    worker = threading.Thread(target=start_manager)
    worker.start()
    assert controller.activate_started.wait(0.5)

    started = time.monotonic()
    manager.emergency_stop()
    assert time.monotonic() - started < 0.1
    assert manager.snapshot(now=clock()).emergency_stopped

    controller.release_activate.set()
    worker.join(0.5)

    assert not worker.is_alive()
    assert errors == []
    assert controller.emergency_stops == 1
    assert controller.stops == []
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.EMERGENCY_STOPPED

    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    manager.close()


def test_startup_base_exception_always_releases_resources() -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))

    class InterruptedController(RecordingController):
        def activate(self) -> None:
            raise KeyboardInterrupt

    controller = InterruptedController()
    manager = ControlManager(controller, source, clock=clock)

    with pytest.raises(KeyboardInterrupt):
        manager.start(threaded=False)

    assert controller.closed == 1
    assert source.closed == 1
    assert not manager._starting
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.DISARMED


def test_worker_start_failure_does_not_poison_later_cleanup(monkeypatch) -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))
    controller = RecordingController()
    controller.capabilities = ControllerCapabilities(requires_stop_confirmation=False)
    manager = ControlManager(controller, source, clock=clock)

    def fail_start(_thread) -> None:
        raise RuntimeError("thread unavailable")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with pytest.raises(RuntimeError, match="thread unavailable"):
        manager.start()

    assert manager._thread is None
    manager.close()
    assert controller.closed == 1
    assert source.closed == 1


def test_emergency_worker_start_failure_falls_back_and_closes_cleanly(monkeypatch) -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))
    controller = RecordingController()
    controller.capabilities = ControllerCapabilities(requires_stop_confirmation=False)
    manager = ControlManager(controller, source, clock=clock)
    manager.start(threaded=False)

    def fail_start(_thread) -> None:
        raise RuntimeError("thread unavailable")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    manager.emergency_stop()

    assert manager._emergency_thread is None
    assert controller.stops[-1] == "emergency_stop_thread_failed"
    manager.close()
    assert controller.closed == 1


def test_emergency_stop_is_nonblocking_and_compensates_inflight_update() -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))
    controller = BlockingUpdateController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(stop_settled_samples=1),
        clock=clock,
    )
    manager.start(threaded=False)
    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    manager.set_target(VelocityCommand(vx=0.1), source="manual")
    controller.actions.clear()
    worker = threading.Thread(target=lambda: manager.tick(now=clock()))
    worker.start()
    assert controller.update_started.wait(0.5)

    started = time.monotonic()
    manager.emergency_stop()
    assert time.monotonic() - started < 0.1
    assert controller.emergency_delivered.wait(0.5)
    controller.release_update.set()
    worker.join(0.5)

    assert not worker.is_alive()
    assert controller.actions[-1] == "stop"
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.EMERGENCY_STOPPED
    clock.advance(0.001)
    source.state = _state(clock(), sequence=3)
    manager.tick(now=clock())
    manager.close()


def test_persistent_motion_after_stop_latches_fault() -> None:
    clock = FakeClock()
    manager, controller, source = _manager(clock)
    manager.set_target(VelocityCommand(vx=0.2), source="manual")
    manager.tick(now=clock())
    source.state = _state(
        clock(),
        sequence=2,
        velocity=VelocityCommand(vx=0.2),
    )

    manager.stop("operator_stop")

    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.STOPPING
    assert controller.stops[-1] == "operator_stop"

    clock.advance(manager.timing.stop_timeout_s)
    source.state = _state(
        clock(),
        sequence=3,
        velocity=VelocityCommand(vx=0.15),
    )
    manager.tick(now=clock())
    status = manager.snapshot(now=clock())
    assert status.lifecycle == ControlLifecycle.FAULTED
    assert status.fault == "physical_stop_not_confirmed"
    assert not status.stop_confirmed


def test_emergency_stop_latches_and_does_not_replay_target() -> None:
    clock = FakeClock()
    manager, controller, source = _manager(clock)
    manager.set_target(VelocityCommand(vx=0.1), source="manual")
    manager.tick(now=clock())

    manager.emergency_stop()
    assert controller.emergency_delivered.wait(0.5)
    manager.tick(now=clock())

    assert controller.emergency_stops == 1
    assert manager.snapshot().lifecycle == ControlLifecycle.EMERGENCY_STOPPED
    assert not manager.snapshot().stop_confirmed
    with pytest.raises(ControlNotReadyError, match="emergency_stopped"):
        manager.set_target(VelocityCommand(vx=0.1), source="manual")

    clock.advance(0.01)
    sequence = 3
    source.state = _state(clock(), sequence=sequence)
    deadline = time.monotonic() + 0.5
    while True:
        try:
            manager.clear_emergency_stop()
            break
        except ControlNotReadyError as error:
            assert "still in flight" in str(error) or "physical stopping" in str(error)
            assert time.monotonic() < deadline
            clock.advance(0.001)
            sequence += 1
            source.state = _state(clock(), sequence=sequence)
            time.sleep(0.005)
    manager.tick(now=clock())
    status = manager.snapshot(now=clock())
    assert status.lifecycle == ControlLifecycle.IDLE
    assert status.target == VelocityCommand()
    assert controller.clears == 1


def test_close_waits_for_feedback_after_its_final_stop() -> None:
    source = FakeStateSource(_state(time.monotonic()))
    controller = RecordingController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(
            state_timeout_s=0.5,
            stop_timeout_s=0.25,
            stop_settled_samples=1,
        ),
    )
    manager.start(threaded=False)
    source.state = _state(time.monotonic(), sequence=2)
    manager.tick()
    manager.set_target(VelocityCommand(vx=0.1), source="manual")
    manager.tick()

    errors: list[Exception] = []

    def close_manager() -> None:
        try:
            manager.close()
        except Exception as error:  # noqa: BLE001 - asserted below
            errors.append(error)

    worker = threading.Thread(target=close_manager)
    worker.start()
    deadline = time.monotonic() + 0.2
    while len(controller.stops) < 2:
        assert time.monotonic() < deadline
        time.sleep(0.002)

    assert manager.snapshot().lifecycle == ControlLifecycle.CLOSING
    with pytest.raises(ControlNotReadyError, match="closing"):
        manager.set_target(VelocityCommand(vx=0.2), source="late_producer")

    # The callback can race with StopMove's return. Publish one additional
    # sample so at least one is strictly newer than the final stop boundary.
    source.state = _state(time.monotonic(), sequence=3)
    time.sleep(0.01)
    source.state = _state(time.monotonic(), sequence=4)
    worker.join(0.5)

    assert not worker.is_alive()
    assert errors == []
    assert controller.closed == 1
    assert source.closed == 1
    assert manager.snapshot().lifecycle == ControlLifecycle.CLOSED


def test_close_waits_for_inflight_update_then_compensates_before_teardown() -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))
    controller = BlockingUpdateController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(stop_timeout_s=0.5, stop_settled_samples=1),
        clock=clock,
    )
    manager.start(threaded=False)
    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    manager.set_target(VelocityCommand(vx=0.1), source="manual")
    controller.actions.clear()

    update_worker = threading.Thread(target=lambda: manager.tick(now=clock()))
    update_worker.start()
    assert controller.update_started.wait(0.5)

    close_errors: list[Exception] = []

    def close_manager() -> None:
        try:
            manager.close()
        except Exception as error:  # noqa: BLE001 - asserted below
            close_errors.append(error)

    close_worker = threading.Thread(target=close_manager)
    close_worker.start()
    deadline = time.monotonic() + 0.2
    while manager.snapshot(now=clock()).lifecycle != ControlLifecycle.CLOSING:
        assert time.monotonic() < deadline
        time.sleep(0.002)
    assert controller.closed == 0

    manager.emergency_stop()
    assert controller.emergency_delivered.wait(0.5)
    assert "emergency_stop" in controller.actions

    controller.release_update.set()
    update_worker.join(0.5)
    assert not update_worker.is_alive()
    assert controller.actions[-1] == "stop"
    clock.advance(0.001)
    source.state = _state(clock(), sequence=3)
    close_worker.join(0.5)

    assert not close_worker.is_alive()
    assert close_errors == []
    assert controller.closed == 1
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.CLOSED


def test_close_timeout_leaves_controller_open_and_can_be_safely_retried() -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))
    controller = BlockingUpdateController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(
            stop_timeout_s=0.2,
            io_quiesce_timeout_s=0.03,
            stop_settled_samples=1,
        ),
        clock=clock,
    )
    manager.start(threaded=False)
    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    manager.set_target(VelocityCommand(vx=0.1), source="manual")

    update_worker = threading.Thread(target=lambda: manager.tick(now=clock()))
    update_worker.start()
    assert controller.update_started.wait(0.5)

    with pytest.raises(ControlNotReadyError, match="retry close"):
        manager.close()

    assert controller.closed == 0
    assert source.closed == 0
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.CLOSING
    with pytest.raises(ControlNotReadyError, match="closing"):
        manager.set_target(VelocityCommand(vx=0.2), source="late_producer")

    controller.release_update.set()
    update_worker.join(0.5)
    assert not update_worker.is_alive()
    clock.advance(0.001)
    source.state = _state(clock(), sequence=3)

    manager.close()

    assert controller.closed == 1
    assert source.closed == 1
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.CLOSED


def test_late_feedback_failure_cannot_start_io_after_teardown_commit() -> None:
    clock = FakeClock()
    controller = BlockingCloseController()

    class FailingDuringControllerClose(FakeStateSource):
        def latest(self) -> RobotMotionState | None:
            if controller.close_started.is_set():
                raise RuntimeError("feedback closed")
            return super().latest()

    source = FailingDuringControllerClose(_state(clock()))
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(
            stop_timeout_s=0.03,
            stop_retry_s=0.005,
            stop_settled_samples=1,
        ),
        clock=clock,
    )
    manager.start(threaded=False)
    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    manager.set_target(VelocityCommand(vx=0.1), source="manual")
    manager.tick(now=clock())

    close_errors: list[Exception] = []
    close_worker = threading.Thread(
        target=lambda: _capture_error(manager.close, close_errors)
    )
    close_worker.start()
    assert controller.close_started.wait(0.5)
    stops_before_late_tick = len(controller.stops)

    clock.advance(manager.timing.stop_retry_s + 0.001)
    manager.tick(now=clock())

    assert len(controller.stops) == stops_before_late_tick
    assert not controller.stop_overlapped_close
    controller.release_close.set()
    close_worker.join(0.5)

    assert not close_worker.is_alive()
    assert len(close_errors) == 1
    assert isinstance(close_errors[0], ControlNotReadyError)
    assert "not confirmed" in str(close_errors[0])
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.CLOSED


def test_new_emergency_stop_supersedes_inflight_clear() -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))
    controller = BlockingClearController()
    manager = ControlManager(controller, source, clock=clock)
    manager.start(threaded=False)
    manager.emergency_stop()
    deadline = time.monotonic() + 0.5
    while controller.emergency_stops < 1 or not manager.snapshot(now=clock()).stop_confirmed:
        assert time.monotonic() < deadline
        time.sleep(0.002)

    clear_errors: list[Exception] = []

    def clear_manager() -> None:
        try:
            manager.clear_emergency_stop()
        except Exception as error:  # noqa: BLE001 - asserted below
            clear_errors.append(error)

    worker = threading.Thread(target=clear_manager)
    worker.start()
    assert controller.clear_started.wait(0.5)
    manager.emergency_stop()
    controller.release_clear.set()
    worker.join(0.5)

    assert not worker.is_alive()
    assert len(clear_errors) == 1
    assert "reasserted" in str(clear_errors[0])
    deadline = time.monotonic() + 0.5
    while controller.emergency_stops < 2:
        assert time.monotonic() < deadline
        time.sleep(0.002)
    assert manager.snapshot(now=clock()).emergency_stopped
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.EMERGENCY_STOPPED
    manager.close()


def test_close_supersedes_inflight_emergency_clear_without_reopening_manager() -> None:
    clock = FakeClock()
    source = FakeStateSource(_state(clock()))
    controller = BlockingClearController()
    manager = ControlManager(controller, source, clock=clock)
    manager.start(threaded=False)
    manager.emergency_stop()
    deadline = time.monotonic() + 0.5
    while controller.emergency_stops < 1 or not manager.snapshot(now=clock()).stop_confirmed:
        assert time.monotonic() < deadline
        time.sleep(0.002)

    clear_errors: list[Exception] = []
    close_errors: list[Exception] = []
    clear_worker = threading.Thread(
        target=lambda: _capture_error(manager.clear_emergency_stop, clear_errors)
    )
    clear_worker.start()
    assert controller.clear_started.wait(0.5)
    close_worker = threading.Thread(target=lambda: _capture_error(manager.close, close_errors))
    close_worker.start()

    deadline = time.monotonic() + 0.2
    while manager.snapshot(now=clock()).lifecycle != ControlLifecycle.CLOSING:
        assert time.monotonic() < deadline
        time.sleep(0.002)
    controller.release_clear.set()
    clear_worker.join(0.5)
    close_worker.join(0.5)

    assert not clear_worker.is_alive()
    assert not close_worker.is_alive()
    assert len(clear_errors) == 1
    assert "closing" in str(clear_errors[0])
    assert close_errors == []
    assert controller.stops[-1] == "manager_closed"
    assert manager.snapshot(now=clock()).lifecycle == ControlLifecycle.CLOSED


def test_close_tears_down_but_reports_unconfirmed_physical_stop() -> None:
    source = FakeStateSource(_state(time.monotonic()))
    controller = RecordingController()
    manager = ControlManager(
        controller,
        source,
        timing=ControlTiming(
            state_timeout_s=0.5,
            stop_timeout_s=0.03,
            stop_retry_s=0.01,
            stop_settled_samples=1,
        ),
    )
    manager.start(threaded=False)
    source.state = _state(time.monotonic(), sequence=2)
    manager.tick()
    manager.set_target(VelocityCommand(vx=0.1), source="manual")
    manager.tick()
    source.state = _state(
        time.monotonic(),
        sequence=3,
        velocity=VelocityCommand(vx=0.1),
    )

    with pytest.raises(ControlNotReadyError, match="not confirmed"):
        manager.close()

    assert controller.closed == 1
    assert source.closed == 1
    assert manager.snapshot().lifecycle == ControlLifecycle.CLOSED


class FakeSubscriber:
    def __init__(self, topic: str, message_type: object) -> None:
        self.topic = topic
        self.message_type = message_type
        self.callback = None
        self.queue_depth = None

    def Init(self, callback, queue_depth: int) -> None:
        self.callback = callback
        self.queue_depth = queue_depth


class FakeSportClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.timeout = None
        self.initialized = 0
        self.moves: list[tuple[float, float, float]] = []
        self.stop_count = 0
        self.move_code = 0
        self.stop_code = 0
        self.lease_id = 1

    def SetTimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def Init(self) -> None:
        self.initialized += 1

    def Move(self, vx: float, vy: float, vyaw: float) -> int:
        self.moves.append((vx, vy, vyaw))
        return self.move_code

    def StopMove(self) -> int:
        self.stop_count += 1
        return self.stop_code

    def GetLeaseId(self) -> int:
        return self.lease_id


def test_unitree_state_source_converts_odometry_velocity_to_body_frame() -> None:
    initialized = []
    subscribers = []
    channel = UnitreeChannelContext(
        0, "enp3s0", lambda domain, nic: initialized.append((domain, nic))
    )

    def factory(topic, message_type):
        subscriber = FakeSubscriber(topic, message_type)
        subscribers.append(subscriber)
        return subscriber

    clock = FakeClock(20.0)
    source = UnitreeSportStateSource(
        channel,
        subscriber_factory=factory,
        message_type=object,
        clock=clock,
    )
    source.start()
    message = SimpleNamespace(
        position=[1.0, 2.0, 0.3],
        velocity=[0.0, 1.0, 0.0],
        yaw_speed=0.2,
        imu_state=SimpleNamespace(rpy=[0.01, -0.02, math.pi / 2]),
        foot_force=[10, 11, 12, 13],
        mode=3,
        error_code=0,
    )
    subscribers[0].callback(message)

    state = source.latest()
    assert initialized == [(0, "enp3s0")]
    assert subscribers[0].topic == "rt/sportmodestate"
    assert subscribers[0].queue_depth == 1
    assert state is not None
    assert state.velocity.vx == pytest.approx(1.0)
    assert state.velocity.vy == pytest.approx(0.0, abs=1e-8)
    assert state.velocity.vyaw == pytest.approx(0.2)
    assert state.foot_forces == (10.0, 11.0, 12.0, 13.0)


def test_unitree_sport_controller_maps_body_velocity_and_refreshes() -> None:
    initialized = []
    client = FakeSportClient()
    channel = UnitreeChannelContext(
        0, "eth0", lambda domain, nic: initialized.append((domain, nic))
    )
    controller = UnitreeSportController(
        channel,
        rpc_timeout_s=0.5,
        refresh_s=0.1,
        allowed_modes=(1,),
        client_factory=lambda **kwargs: client,
    )
    controller.activate()
    state = _state(10.0)
    target = TimedVelocitySetpoint(
        VelocityCommand(vx=0.2, vy=-0.1, vyaw=0.3),
        source="manual",
        sequence=1,
        issued_at=10.0,
        valid_until=11.0,
    )

    controller.update(target, state, now=10.0)
    controller.update(target, state, now=10.05)
    controller.update(target, state, now=10.101)
    controller.stop("done")
    controller.stop("idempotent")
    controller.close()

    assert initialized == [(0, "eth0")]
    assert client.timeout == 0.5
    assert client.initialized == 1
    assert client.moves == [(0.2, -0.1, 0.3), (0.2, -0.1, 0.3)]
    # close() must not append a new, unobservable StopMove after its caller has
    # already delivered the final stop boundary.
    assert client.stop_count == 2


def test_unitree_controller_requires_an_explicit_mode_allowlist() -> None:
    channel = UnitreeChannelContext(0, "eth0", lambda *_: None)

    with pytest.raises(ValueError, match="explicitly commissioned"):
        UnitreeSportController(channel, allowed_modes=())


@pytest.mark.parametrize(
    "sport, exception, message",
    [
        (
            {"enable_lease": False, "allowed_modes": [1, 3]},
            ValueError,
            "enable_lease must be true",
        ),
        (
            {
                "enable_lease": True,
                "axes_commissioned": True,
                "state_frame_commissioned": True,
                "allowed_modes": [],
            },
            ValueError,
            "explicitly commissioned",
        ),
        (
            {
                "enable_lease": True,
                "axes_commissioned": True,
                "state_frame_commissioned": True,
                "allowed_modes": [True, 3],
            },
            TypeError,
            "must contain integers",
        ),
        (
            {
                "enable_lease": True,
                "axes_commissioned": False,
                "state_frame_commissioned": True,
                "allowed_modes": [1, 3],
            },
            ValueError,
            "axes_commissioned",
        ),
        (
            {
                "enable_lease": True,
                "axes_commissioned": True,
                "state_frame_commissioned": False,
                "allowed_modes": [1, 3],
            },
            ValueError,
            "state_frame_commissioned",
        ),
    ],
)
def test_physical_factory_fails_closed_without_lease_or_modes(sport, exception, message) -> None:
    with pytest.raises(exception, match=message):
        build_unitree_sport_control_manager(
            {"unitree_sport": sport},
            SafetyLimits(),
        )


def test_physical_factory_builds_only_after_all_commissioning_gates() -> None:
    manager = build_unitree_sport_control_manager(
        {
            "unitree_sport": {
                "interface": "dedicated-nic",
                "enable_lease": True,
                "axes_commissioned": True,
                "state_velocity_frame": "base_link",
                "state_frame_commissioned": True,
                "lateral_sign": -1,
                "yaw_sign": 1,
                "allowed_modes": [1, 3],
            }
        },
        SafetyLimits(),
    )

    assert isinstance(manager.controller, UnitreeSportController)
    assert isinstance(manager.state_source, UnitreeSportStateSource)
    assert manager.state_source.velocity_frame == "base_link"
    assert manager.controller.allowed_modes == frozenset({1, 3})


def test_physical_factory_requires_shutdown_budget_to_cover_lease_activation() -> None:
    with pytest.raises(ValueError, match="io_quiesce_timeout_s"):
        build_unitree_sport_control_manager(
            {
                "io_quiesce_timeout_s": 0.5,
                "unitree_sport": {
                    "enable_lease": True,
                    "lease_acquire_timeout_s": 1.0,
                    "axes_commissioned": True,
                    "state_frame_commissioned": True,
                    "allowed_modes": [1],
                },
            },
            SafetyLimits(),
        )


def test_unitree_controller_rejects_disallowed_mode_before_move() -> None:
    client = FakeSportClient()
    channel = UnitreeChannelContext(0, "eth0", lambda *_: None)
    controller = UnitreeSportController(
        channel,
        allowed_modes=(1, 3),
        client_factory=lambda **kwargs: client,
    )
    controller.activate()
    target = TimedVelocitySetpoint(
        VelocityCommand(vx=0.05),
        source="manual",
        sequence=1,
        issued_at=10.0,
        valid_until=11.0,
    )

    with pytest.raises(RuntimeError, match="mode 10"):
        controller.update(target, _state(10.0, mode=10), now=10.0)

    assert client.moves == []


def test_unitree_controller_fails_if_lease_is_not_acquired() -> None:
    clock = FakeClock()
    client = FakeSportClient()
    client.lease_id = 0
    channel = UnitreeChannelContext(0, "eth0", lambda *_: None)
    controller = UnitreeSportController(
        channel,
        lease_acquire_timeout_s=0.1,
        allowed_modes=(1,),
        client_factory=lambda **kwargs: client,
        clock=clock,
        sleeper=clock.advance,
    )

    with pytest.raises(RuntimeError, match="lease was not acquired"):
        controller.activate()


def test_unitree_controller_suppresses_move_after_lease_loss() -> None:
    client = FakeSportClient()
    channel = UnitreeChannelContext(0, "eth0", lambda *_: None)
    controller = UnitreeSportController(
        channel,
        allowed_modes=(1,),
        client_factory=lambda **kwargs: client,
    )
    controller.activate()
    target = TimedVelocitySetpoint(
        VelocityCommand(vx=0.05),
        source="manual",
        sequence=1,
        issued_at=10.0,
        valid_until=11.0,
    )
    controller.update(target, _state(10.0), now=10.0)
    client.lease_id = 0

    with pytest.raises(RuntimeError, match="lease was lost"):
        controller.update(target, _state(10.01, sequence=2), now=10.01)

    assert client.moves == [(0.05, 0.0, 0.0)]


def test_unitree_nonzero_transport_code_faults_manager_and_stops() -> None:
    clock = FakeClock()
    client = FakeSportClient()
    client.move_code = 9
    channel = UnitreeChannelContext(0, "eth0", lambda *_: None)
    controller = UnitreeSportController(
        channel,
        allowed_modes=(1, 3),
        client_factory=lambda **kwargs: client,
    )
    source = FakeStateSource(_state(clock()))
    manager = ControlManager(
        controller,
        source,
        limits=ControlLimits(),
        timing=ControlTiming(stop_settled_samples=1),
        clock=clock,
    )
    manager.start(threaded=False)
    clock.advance(0.001)
    source.state = _state(clock(), sequence=2)
    manager.tick(now=clock())
    manager.set_target(VelocityCommand(vx=0.1), source="manual")

    manager.tick(now=clock())

    status = manager.snapshot(now=clock())
    assert status.lifecycle == ControlLifecycle.FAULTED
    assert "code 9" in str(status.fault)
    assert client.stop_count >= 1
