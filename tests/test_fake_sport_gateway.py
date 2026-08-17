from __future__ import annotations

import dataclasses
import threading
import time

from parcel_robot.bridge.fake_gateway import FakeGatewayCoreV1
from parcel_robot.bridge.fake_gateway_process import _evidence_exit_code
from parcel_robot.bridge.fake_sport import (
    FakeSportFaultsV1,
    FakeSportServiceV1,
    NonBlockingEventSinkV1,
)
from parcel_robot.bridge.protocol import (
    GatewayAckDispositionV1,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayCommandV1,
    GatewayHashesV1,
    GatewayPhaseV1,
)

HASHES = GatewayHashesV1("a" * 64, "b" * 64, "c" * 64, "d" * 64)


class ManualClock:
    def __init__(self, value: float = 10.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _acquire(core: FakeGatewayCoreV1, *, connection: int = 1, sequence: int = 1) -> GatewayAckV1:
    response = core.acquire(
        connection,
        GatewayAcquireV1("writer", core.boot_epoch, sequence, 350, HASHES),
    )
    assert response.disposition is GatewayAckDispositionV1.ACCEPTED
    return response


def _command(
    core: FakeGatewayCoreV1,
    *,
    connection: int = 1,
    sequence: int = 2,
) -> GatewayAckV1:
    response = core.command(
        connection,
        GatewayCommandV1(
            "writer",
            core.boot_epoch,
            sequence,
            350,
            "base_link",
            0.2,
            0.0,
            0.0,
            "task",
            "trace",
            HASHES,
        ),
    )
    assert isinstance(response, GatewayAckV1)
    return response


def _wait_for(events: list[dict[str, object]], event: str, timeout_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if any(item["event"] == event for item in events):
            return
        time.sleep(0.005)
    raise AssertionError(f"event {event!r} was not observed: {events}")


def _observer(events: list[dict[str, object]]) -> NonBlockingEventSinkV1:
    return NonBlockingEventSinkV1(events.append)


def test_first_command_is_admitted_and_ack_is_not_motion_truth() -> None:
    events: list[dict[str, object]] = []
    observer = _observer(events)
    sport = FakeSportServiceV1(event_sink=observer)
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES, event_sink=observer)
    _acquire(core)
    response = _command(core)
    assert response.disposition is GatewayAckDispositionV1.ACCEPTED
    assert response.ack_scope == "gateway_admission"
    _wait_for(events, "move_applied")


def test_receiver_derives_ttl_locally_and_expiry_stops() -> None:
    clock = ManualClock(100.0)
    events: list[dict[str, object]] = []
    observer = _observer(events)
    sport = FakeSportServiceV1(clock=clock, event_sink=observer)
    core = FakeGatewayCoreV1(
        sport,
        required_hashes=HASHES,
        clock=clock,
        event_sink=observer,
    )
    _acquire(core)
    assert _command(core).disposition is GatewayAckDispositionV1.ACCEPTED
    clock.value = 100.349
    assert core.tick() is None
    clock.value = 100.350
    report = core.tick()
    assert report is not None
    assert report.reason == "local_ttl_expired"
    assert report.stationary_confirmed
    assert core.phase is GatewayPhaseV1.DISARMED


def _later_command(core: FakeGatewayCoreV1, *, sequence: int = 3) -> GatewayAckV1:
    response = core.command(
        1,
        GatewayCommandV1(
            "writer",
            core.boot_epoch,
            sequence,
            350,
            "base_link",
            0.25,
            0.0,
            0.0,
            "task",
            "late-refresh",
            HASHES,
        ),
    )
    assert isinstance(response, GatewayAckV1)
    return response


def test_command_at_or_after_local_expiry_cannot_revive_authority() -> None:
    for late_time in (100.350, 100.351):
        clock = ManualClock(100.0)
        events: list[dict[str, object]] = []
        observer = _observer(events)
        sport = FakeSportServiceV1(clock=clock, event_sink=observer)
        core = FakeGatewayCoreV1(
            sport,
            required_hashes=HASHES,
            clock=clock,
            event_sink=observer,
        )
        _acquire(core)
        assert _command(core).disposition is GatewayAckDispositionV1.ACCEPTED
        _wait_for(events, "move_applied")
        clock.value = late_time
        rejected = _later_command(core)
        assert rejected.disposition is GatewayAckDispositionV1.REJECTED
        assert rejected.reason == "local_ttl_expired"
        assert core.phase is GatewayPhaseV1.DISARMED
        assert core.active_writer is None
        assert observer.drain(timeout_s=1.0)
        physical = [
            item["event"]
            for item in events
            if item["event"] in {"move_applied", "stop_move_succeeded"}
        ]
        assert physical[-1] == "stop_move_succeeded"
        assert sum(item["event"] == "move_applied" for item in events) == 1


def test_state_query_expires_authority_before_reporting_truth() -> None:
    clock = ManualClock(100.0)
    sport = FakeSportServiceV1(clock=clock)
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES, clock=clock)
    _acquire(core)
    assert _command(core).disposition is GatewayAckDispositionV1.ACCEPTED
    clock.value = 100.350
    state = core.state()
    assert state.phase is GatewayPhaseV1.DISARMED
    assert state.stationary
    assert state.last_stop_reason == "local_ttl_expired"


def test_delayed_move_crossing_stop_epoch_gets_compensating_stop() -> None:
    events: list[dict[str, object]] = []
    observer = _observer(events)
    sport = FakeSportServiceV1(
        faults=FakeSportFaultsV1(move_delay_s=0.05),
        event_sink=observer,
    )
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES, event_sink=observer)
    _acquire(core)
    _command(core)
    _wait_for(events, "move_accepted")
    first = core.client_lost(1)
    assert first is not None and first.stationary_confirmed
    _wait_for(events, "move_applied")
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        physical = [
            item["event"]
            for item in events
            if item["event"] in {"move_applied", "stop_move_succeeded"}
        ]
        if (
            physical
            and physical[-1] == "stop_move_succeeded"
            and physical.count("stop_move_succeeded") >= 2
        ):
            break
        time.sleep(0.005)
    assert physical[-3:] == ["stop_move_succeeded", "move_applied", "stop_move_succeeded"]
    assert any(item.get("reason") == "late_move_completion_compensation" for item in events)
    assert core.phase is GatewayPhaseV1.DISARMED


def test_no_reply_move_does_not_block_independent_stop() -> None:
    events: list[dict[str, object]] = []
    observer = _observer(events)
    sport = FakeSportServiceV1(
        faults=FakeSportFaultsV1(move_no_reply=True),
        event_sink=observer,
    )
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES, event_sink=observer)
    _acquire(core)
    _command(core)
    _wait_for(events, "move_no_reply")
    report = core.client_lost(1)
    assert report is not None and report.stationary_confirmed
    assert observer.drain(timeout_s=1.0)
    assert any(item["event"] == "lease_released" for item in events)
    assert any(item["event"] == "gateway_stop_report" for item in events)
    physical = [
        item["event"] for item in events if item["event"] in {"move_applied", "stop_move_succeeded"}
    ]
    assert physical[-1] == "stop_move_succeeded"
    sport.close()


def test_stale_out_of_order_and_lease_loss_fixtures_stop() -> None:
    stale_sport = FakeSportServiceV1(faults=FakeSportFaultsV1(stale_state_by_s=0.5))
    stale = FakeGatewayCoreV1(stale_sport, required_hashes=HASHES)
    _acquire(stale)
    assert _command(stale).reason == "state_stale"
    # StopMove returned, but the only feedback remains stale, so stillness is
    # unconfirmed and the gateway must stay latched rather than claim success.
    assert stale.phase is GatewayPhaseV1.LATCHED

    reordered_sport = FakeSportServiceV1(faults=FakeSportFaultsV1(out_of_order_state=True))
    reordered = FakeGatewayCoreV1(reordered_sport, required_hashes=HASHES)
    _acquire(reordered)
    assert _command(reordered).reason == "state_out_of_order"
    assert reordered.phase is GatewayPhaseV1.LATCHED

    lease_sport = FakeSportServiceV1()
    lease = FakeGatewayCoreV1(lease_sport, required_hashes=HASHES)
    _acquire(lease)
    lease_sport.force_lease_loss()
    report = lease.tick()
    assert report is not None and report.reason == "sport_lease_lost"
    assert lease.phase is GatewayPhaseV1.DISARMED


def test_writer_conflict_stops_and_latches() -> None:
    events: list[dict[str, object]] = []
    observer = _observer(events)
    sport = FakeSportServiceV1(event_sink=observer)
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES, event_sink=observer)
    _acquire(core)
    conflict = core.acquire(
        2,
        GatewayAcquireV1("intruder", core.boot_epoch, 2, 350, HASHES),
    )
    assert conflict.disposition is GatewayAckDispositionV1.REJECTED
    assert conflict.reason == "writer_conflict"
    assert core.phase is GatewayPhaseV1.LATCHED
    assert observer.drain(timeout_s=1.0)
    assert any(item.get("reason") == "writer_conflict" for item in events)


def test_stop_move_failure_is_never_reported_as_stationary_confirmation() -> None:
    sport = FakeSportServiceV1(faults=FakeSportFaultsV1(stop_move_failure=True))
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES)
    _acquire(core)
    assert _command(core).disposition is GatewayAckDispositionV1.ACCEPTED
    report = core.client_lost(1)
    assert report is not None
    assert not report.stop_rpc_completed
    assert not report.stationary_confirmed
    assert report.state_sequence == 0
    assert core.phase is GatewayPhaseV1.LATCHED


def test_same_boot_replay_cannot_rearm_after_client_loss() -> None:
    sport = FakeSportServiceV1()
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES)
    _acquire(core)
    _command(core)
    core.client_lost(1)
    replay = core.acquire(
        2,
        GatewayAcquireV1("writer", core.boot_epoch, 1, 350, HASHES),
    )
    assert replay.disposition is GatewayAckDispositionV1.REJECTED
    assert replay.reason == "client_sequence_not_increasing"
    assert core.phase is GatewayPhaseV1.DISARMED


def test_duplicate_command_sequence_stops_and_latches_within_boot() -> None:
    sport = FakeSportServiceV1()
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES)
    _acquire(core)
    assert _command(core).disposition is GatewayAckDispositionV1.ACCEPTED
    duplicate = _command(core)
    assert duplicate.disposition is GatewayAckDispositionV1.REJECTED
    assert duplicate.reason == "client_sequence_not_increasing"
    time.sleep(0.02)
    assert core.phase is GatewayPhaseV1.LATCHED


def test_hash_epoch_and_duplicate_sequence_fail_closed() -> None:
    sport = FakeSportServiceV1()
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES)
    prior = core.acquire(1, GatewayAcquireV1("writer", "old-epoch", 1, 350, HASHES))
    assert prior.disposition is GatewayAckDispositionV1.REJECTED
    assert prior.reason == "boot_epoch_mismatch"
    assert core.phase is GatewayPhaseV1.DISARMED
    _acquire(core)
    wrong_hash = dataclasses.replace(HASHES, firmware_sha256="e" * 64)
    command = GatewayCommandV1(
        "writer", core.boot_epoch, 2, 350, "base_link", 0.2, 0.0, 0.0, "task", "trace", wrong_hash
    )
    rejected = core.command(1, command)
    assert rejected.reason == "contract_hash_mismatch"
    assert core.phase is GatewayPhaseV1.LATCHED


def test_fake_sport_writer_conflict_fixture_is_independent_of_gateway() -> None:
    sport = FakeSportServiceV1()
    assert sport.acquire_writer("writer-a")
    assert not sport.acquire_writer("writer-b")


def test_raising_observer_cannot_change_stop_effect_or_disarm() -> None:
    def raising_sink(_event: dict[str, object]) -> None:
        raise RuntimeError("seeded observer failure")

    observer = NonBlockingEventSinkV1(raising_sink)
    sport = FakeSportServiceV1(event_sink=observer)
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES, event_sink=observer)
    _acquire(core)
    assert _command(core).disposition is GatewayAckDispositionV1.ACCEPTED
    deadline = time.monotonic() + 1.0
    while sport.state().stationary and time.monotonic() < deadline:
        time.sleep(0.001)
    report = core.client_lost(1)
    state = sport.state()
    assert report is not None and report.stationary_confirmed
    assert state.stationary
    assert core.phase is GatewayPhaseV1.DISARMED
    deadline = time.monotonic() + 1.0
    while observer.sink_errors == 0 and time.monotonic() < deadline:
        time.sleep(0.001)
    assert observer.sink_errors > 0
    assert observer.drain(timeout_s=1.0)
    assert _evidence_exit_code(observer, drained=True) == 2


def test_blocked_observer_cannot_delay_stop_effect_or_disarm() -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked_sink(_event: dict[str, object]) -> None:
        entered.set()
        release.wait(timeout=2.0)

    observer = NonBlockingEventSinkV1(blocked_sink)
    sport = FakeSportServiceV1(event_sink=observer)
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES, event_sink=observer)
    _acquire(core)
    assert entered.wait(timeout=1.0)
    assert _command(core).disposition is GatewayAckDispositionV1.ACCEPTED
    deadline = time.monotonic() + 1.0
    while sport.state().stationary and time.monotonic() < deadline:
        time.sleep(0.001)
    started = time.monotonic()
    report = core.client_lost(1)
    elapsed = time.monotonic() - started
    state = sport.state()
    assert elapsed < 0.05
    assert report is not None and report.stationary_confirmed
    assert state.stationary
    assert core.phase is GatewayPhaseV1.DISARMED
    assert not observer.drain(timeout_s=0.01)
    assert _evidence_exit_code(observer, drained=False) == 2
    release.set()
    assert observer.drain(timeout_s=1.0)


def test_full_observer_queue_cannot_change_stop_and_makes_evidence_exit_nonzero() -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked_sink(_event: dict[str, object]) -> None:
        entered.set()
        release.wait(timeout=2.0)

    observer = NonBlockingEventSinkV1(blocked_sink, capacity=1)
    sport = FakeSportServiceV1(event_sink=observer)
    core = FakeGatewayCoreV1(sport, required_hashes=HASHES, event_sink=observer)
    _acquire(core)
    assert entered.wait(timeout=1.0)

    # The worker is blocked on one event and one more event fills the only
    # queue slot. Additional observation attempts must drop rather than enter
    # the control path.
    for index in range(4):
        observer({"event": "seeded_queue_pressure", "index": index})
    assert observer.dropped_events > 0

    assert _command(core).disposition is GatewayAckDispositionV1.ACCEPTED
    deadline = time.monotonic() + 1.0
    while sport.state().stationary and time.monotonic() < deadline:
        time.sleep(0.001)
    started = time.monotonic()
    report = core.client_lost(1)
    elapsed = time.monotonic() - started
    state = sport.state()
    assert elapsed < 0.05
    assert report is not None and report.stationary_confirmed
    assert state.stationary
    assert core.phase is GatewayPhaseV1.DISARMED

    release.set()
    assert observer.drain(timeout_s=1.0)
    assert observer.dropped_events > 0
    assert _evidence_exit_code(observer, drained=True) == 2
