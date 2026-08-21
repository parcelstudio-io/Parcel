"""Card R22 — the pump that cannot die quietly.

WHAT THIS FILE PINS, AND WHY IT IS THE MOST IMPORTANT FILE IN THE REALTIME TREE
------------------------------------------------------------------------------
AUDIT_FULL_FABLE §Safety-1, CONFIRMED, refuter-verified: the realtime pump
thread died permanently and silently on any exception outside a four-type catch
list, and the conversation-ledger write (raw sqlite, no wrapper) sits on that
thread. The refuter walked the MRO and settled the question that makes it a
safety finding rather than a robustness one:

    ``sqlite3.Error`` → ``Exception`` → ``BaseException``

It subclasses NONE of ``OSError``, ``RuntimeError``, ``TypeError``,
``ValueError``. So a disk-full or a locked database mid-turn killed the pump,
and with it the SPOKEN emergency stop, the stall watchdog, the 60-minute
rollover and the idle hang-up, while the microphone stayed open and nothing
anywhere alarmed.

Five properties, and every one of them has a seeded-violation companion:

1. **The firewall.** Every loop body survives ANY ``Exception`` — proven with
   real ``sqlite3`` errors and with an exception type invented in this file, so
   the test cannot be satisfied by a longer type list.
2. **``BaseException`` still propagates.** A pump that swallowed
   ``KeyboardInterrupt`` would be its own incident.
3. **The alarm.** A dead pump sets ``alive`` False, names a reason, ages its
   heartbeat, fires a safety-class runtime event, and reaches the panel.
4. **Revival is bounded.** It restarts, it backs off, it counts, and it stops.
5. **Ledgers are firewalled at all four sites**, and a ledger failure costs a
   counted note rather than a turn — and never a thread.

Plus EV-1 §10.3's handoff: ``RetainedEvent`` frames reach the evidence log's own
sink and NOT ``_note``, because 44 ASR deltas a session through the 100-slot
panel ring is the exact flood EV-1 exists to relieve.

Every clock and sleep here is injected. Nothing in the offline tests waits.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.memory import ConversationMemory
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV, RealtimeConfig
from parcel_robot.realtime.driver import (
    ALARM_DIED,
    ALARM_REVIVED,
    DEFAULT_MAX_REVIVALS,
    DEFAULT_REVIVE_AFTER,
    RealtimeDriver,
)
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    audio_done,
    handshake,
    response_done,
    transcript_done,
)
from parcel_robot.realtime.lane import RealtimeLane
from parcel_robot.realtime.protocol import RETAINED_EVENT_TYPES, RetainedEvent
from parcel_robot.realtime.transport import transport_pair
from parcel_robot.runtime import (
    SAFETY_LOG_PUMP_DIED,
    SAFETY_LOG_PUMP_REVIVED,
    SAFETY_SOURCE_REALTIME_PUMP,
    SAFETY_SOURCES,
    RobotRuntime,
)

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r22-pump"


class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _ExoticError(Exception):
    """A type nobody could have put on a catch list, because it is defined here.

    This class is the whole methodological point of the card. A test that only
    seeded ``sqlite3.OperationalError`` could be satisfied by adding one more
    name to the four-name list — which is how the defect got written in the
    first place. This one cannot be, by construction.
    """


class _Lane:
    """A lane-shaped recorder that explodes exactly where it is told to."""

    def __init__(self, *, explode: str = "", error: BaseException | None = None) -> None:
        self.calls: list[str] = []
        self.instructions = "v1"
        self.tick_reason: str | None = None
        self.explode = explode
        self.error = error or _ExoticError("nothing on any catch list")
        self.active = True

    def pump(self) -> int:
        self.calls.append("pump")
        if self.explode == "pump":
            raise self.error
        return 0

    def tick(self) -> str | None:
        self.calls.append("tick")
        if self.explode == "tick":
            raise self.error
        return self.tick_reason


# ============================================================ 1. the firewall
#: Every exception class the audit proved was OUTSIDE the old catch list, plus
#: one this file invented. ``sqlite3.OperationalError`` is the live one — it is
#: what "database is locked" and "disk I/O error" raise.
BLINDSPOT_ERRORS: tuple[BaseException, ...] = (
    sqlite3.OperationalError("database is locked"),
    sqlite3.DatabaseError("database disk image is malformed"),
    sqlite3.Error("generic sqlite failure"),
    sqlite3.IntegrityError("constraint failed"),
    _ExoticError("nothing on any catch list"),
    KeyError("a dict the provider changed"),
    AttributeError("None has no attribute 'session_id'"),
    ZeroDivisionError("arithmetic on an empty response"),
)


def test_the_refuters_mro_claim_is_true_here_and_not_only_in_the_audit() -> None:
    """The finding's load-bearing fact, asserted rather than quoted.

    If a future Python ever made ``sqlite3.Error`` an ``OSError``, the old
    four-type list would have been adequate and this card's premise would be
    wrong. It does not, and this is where that stops being a claim in a
    markdown file.
    """

    assert issubclass(sqlite3.Error, Exception)
    assert not issubclass(sqlite3.Error, (OSError, RuntimeError, TypeError, ValueError))
    # Every subclass the engine can actually raise, not just the base.
    for error in BLINDSPOT_ERRORS:
        if isinstance(error, sqlite3.Error):
            assert not isinstance(error, (OSError, RuntimeError, TypeError, ValueError))


@pytest.mark.parametrize("where", ["pump", "tick"])
@pytest.mark.parametrize("error", BLINDSPOT_ERRORS, ids=lambda e: type(e).__name__)
def test_a_step_survives_every_exception_outside_the_old_catch_list(
    where: str, error: BaseException
) -> None:
    lane = _Lane(explode=where, error=error)
    driver = RealtimeDriver(lane)
    driver.step()
    driver.step()
    assert driver.steps == 2, "the step returned; it did not raise"
    assert driver.failure_count == 2
    # Counted BY TYPE — the audit's own vocabulary.
    assert driver.failure_types == {type(error).__name__: 2}
    assert type(error).__name__ in driver.failures[0]


def test_a_step_survives_a_raising_instruction_source_of_any_type() -> None:
    class _Broken:
        def refresh(self, lane: object) -> bool:
            raise sqlite3.OperationalError("the prompt cache is on the full disk")

    driver = RealtimeDriver(_Lane(), instructions=_Broken())
    driver.step()
    assert driver.failure_types == {"OperationalError": 1}
    assert driver.consecutive_failures == 1


def test_a_step_survives_a_raising_reason_handler() -> None:
    """The fourth call, and the one that used to be unguarded entirely.

    ``_on_reason`` runs OUTSIDE the ``tick`` guard by design (the ordering note
    in ``step``): it is what turns a tick answer into a reconnect note or a
    self-stop. Unguarded, anything it touches could kill the pump through the
    one path added to make the pump observable.
    """

    class _HostileList(list):
        def append(self, item: object) -> None:
            raise sqlite3.OperationalError("the reason log is on the full disk")

    lane = _Lane()
    lane.tick_reason = "rollover"
    driver = RealtimeDriver(lane)
    driver.reconnect_reasons = _HostileList()  # type: ignore[assignment]
    driver.step()
    assert driver.steps == 1, "the step returned; it did not raise"
    assert driver.failure_types == {"OperationalError": 1}
    assert "reason handling failed" in driver.failures[0]


def test_a_broken_note_sink_is_counted_and_never_fatal() -> None:
    """The other wire out. ``_note`` reaches the panel; it may not reach back."""

    def _explode(message: str) -> None:
        raise sqlite3.OperationalError("the event ring is on the full disk")

    lane = _Lane()
    lane.tick_reason = "rollover"
    driver = RealtimeDriver(lane, on_event=_explode)
    driver.step()
    assert driver.steps == 1
    assert driver.reconnect_reasons == ["rollover"], "the reason still landed"
    assert driver.note_failures >= 1, "and the broken wire is on the record"


def test_the_loop_survives_a_step_that_explodes_in_its_own_scaffolding() -> None:
    """The loop's own guard — the last thing before a silent thread death.

    ``step()`` firewalls its four calls, so this only fires when the scaffolding
    itself breaks (the injected clock, the counters). With no guard, the
    exception leaves ``_loop`` and the thread is gone in silence, which is
    §Safety-1 exactly. With it, the loop counts, exhausts its revival budget and
    DIES LOUDLY instead.
    """

    driver = RealtimeDriver(
        _Lane(), interval_s=0.0, max_revivals=0, sleep=_CountingSleep()
    )

    def _explode() -> int:
        raise sqlite3.OperationalError("the clock is on the full disk")

    driver.step = _explode  # type: ignore[method-assign]
    driver._loop()  # returns; it does not raise out of the thread
    assert driver.failure_count == DEFAULT_REVIVE_AFTER
    assert driver.failure_types == {"OperationalError": DEFAULT_REVIVE_AFTER}
    assert driver.deaths == 1
    assert driver.revivals_exhausted is True


def test_a_clean_step_resets_the_failure_streak() -> None:
    lane = _Lane(explode="pump")
    driver = RealtimeDriver(lane)
    driver.step()
    driver.step()
    assert driver.consecutive_failures == 2
    lane.explode = ""
    driver.step()
    assert driver.consecutive_failures == 0
    assert driver.failure_count == 2, "the total is a TOTAL and does not reset"


def test_the_failure_log_is_bounded_but_the_counts_are_exact() -> None:
    from parcel_robot.realtime.driver import FAILURE_LOG_LIMIT

    driver = RealtimeDriver(_Lane(explode="pump"))
    for _ in range(FAILURE_LOG_LIMIT + 25):
        driver.step()
    assert len(driver.failures) == FAILURE_LOG_LIMIT
    assert driver.failure_count == FAILURE_LOG_LIMIT + 25
    assert driver.failure_types["_ExoticError"] == FAILURE_LOG_LIMIT + 25


# ================================================== 2. BaseException still ends it
@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(1)])
def test_a_base_exception_is_never_swallowed(error: BaseException) -> None:
    """The line the firewall must NOT cross.

    A pump that ignored Ctrl-C or an interpreter shutdown would be a worse bug
    than the one this card fixes, so ``step`` catches ``Exception`` and the
    loop re-raises anything above it.
    """

    driver = RealtimeDriver(_Lane(explode="pump", error=error))
    with pytest.raises(type(error)):
        driver.step()
    assert driver.failure_count == 0, "nothing was recorded because nothing was caught"


def test_a_base_exception_in_the_loop_alarms_on_its_way_out() -> None:
    """It ends the thread — but LOUDLY, which is the whole card."""

    alarms: list[tuple[str, str]] = []
    driver = RealtimeDriver(
        _Lane(explode="pump", error=KeyboardInterrupt()),
        interval_s=0.0,
        on_alarm=lambda kind, message, detail: alarms.append((kind, message)),
    )
    with pytest.raises(KeyboardInterrupt):
        driver._loop()
    assert [kind for kind, _ in alarms] == [ALARM_DIED]
    assert driver.alive is False
    assert driver.deaths == 1
    assert "KeyboardInterrupt" in str(driver.death_reason)


# ================================================================ 3. the alarm
def test_a_dead_pump_is_alive_false_and_says_why() -> None:
    alarms: list[tuple[str, str, dict[str, object]]] = []
    driver = RealtimeDriver(
        _Lane(),
        interval_s=0.0,
        max_revivals=0,
        on_alarm=lambda kind, message, detail: alarms.append((kind, message, dict(detail))),
    )
    driver._die("the socket thread was killed")
    assert driver.alive is False
    assert driver.death_reason == "the socket thread was killed"
    assert driver.deaths == 1
    kinds = [kind for kind, _, _ in alarms]
    assert kinds == [ALARM_DIED]
    # LOUD: the message names what stopped, not just that something did.
    message = alarms[0][1]
    for stopped in ("spoken e-stop", "stall watchdog", "rollover", "idle hang-up"):
        assert stopped in message
    assert "local emergency stop" in message.lower(), "and what is UNAFFECTED"


def test_alive_and_running_answer_different_questions() -> None:
    """The gap between them is the shape of the incident. Card R22.

    ``running`` folds in intent and is what the runtime consults before starting
    a pump; ``alive`` is whether a thread exists. A driver that was never
    started is both False; a driver killed mid-session used to be ``running``
    False with nothing anywhere saying a thread had died.
    """

    driver = RealtimeDriver(_Lane(), interval_s=0.001, sleep=time.sleep)
    assert (driver.alive, driver.running) == (False, False)
    driver.start()
    try:
        deadline = time.monotonic() + 2.0
        while driver.steps < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert (driver.alive, driver.running) == (True, True)
    finally:
        driver.stop()
    assert (driver.alive, driver.running) == (False, False)

    # The state only ``alive`` can see, and the reason the two are not one
    # field: told to stop, thread still winding down inside its last sleep.
    # ``running`` is False so the owner's next gesture starts a replacement;
    # ``alive`` is True so nobody can claim this lane has no pump on it.
    gate = threading.Event()
    winding = threading.Thread(target=gate.wait, daemon=True)
    winding.start()
    driver._thread = winding
    driver._stop.set()
    try:
        assert driver.running is False
        assert driver.alive is True, "a second pump beside this one would be invisible"
    finally:
        gate.set()
        winding.join(timeout=2.0)


def test_the_heartbeat_ages_and_reaches_the_snapshot() -> None:
    clock = _Clock()
    driver = RealtimeDriver(_Lane(), clock=clock)
    assert driver.heartbeat_age_s() is None, "it has never stepped"
    driver.step()
    assert driver.heartbeat_age_s() == 0.0
    clock.advance(7.5)
    assert driver.heartbeat_age_s() == pytest.approx(7.5)
    snapshot = driver.snapshot()
    assert snapshot["heartbeat_age_s"] == pytest.approx(7.5)
    assert snapshot["alive"] is False
    assert snapshot["failure_count"] == 0


def test_a_broken_clock_cannot_break_the_health_question() -> None:
    def _broken() -> float:
        raise sqlite3.OperationalError("the clock is not a clock")

    driver = RealtimeDriver(_Lane(), clock=_Clock())
    driver.step()
    driver._clock = _broken  # type: ignore[assignment]
    assert driver.heartbeat_age_s() is None
    driver._die("a death recorded with a broken clock")
    assert driver.died_at is None
    assert driver.deaths == 1, "the death still counted"


def test_an_alarm_hook_that_raises_cannot_cause_a_second_death() -> None:
    def _explode(kind: str, message: str, detail: Any) -> None:
        raise sqlite3.OperationalError("the alarm sink is on the full disk")

    def _explode_note(message: str) -> None:
        raise sqlite3.OperationalError("the note sink is on the full disk too")

    driver = RealtimeDriver(_Lane(), on_alarm=_explode, on_event=_explode_note)
    driver._die("first death")
    assert driver.deaths == 1
    # Both wires out are cut, and BOTH facts are on the record here — which is
    # the only record left when they are.
    assert driver.alarm_failures == 1
    assert driver.note_failures == 1
    assert driver.snapshot()["death_reason"] == "first death"


def test_ensure_alive_names_a_death_nobody_reported() -> None:
    """The belt to ``_die``'s braces: a thread that vanished without a word."""

    alarms: list[str] = []
    driver = RealtimeDriver(_Lane(), on_alarm=lambda kind, m, d: alarms.append(kind))
    assert driver.ensure_alive() is True, "never started is not dead"

    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    driver._thread = dead
    driver._stop.clear()
    assert driver.ensure_alive() is False
    assert alarms == [ALARM_DIED]
    # Exactly once: ``_die`` sets ``_stop``, so the next probe is quiet.
    assert driver.ensure_alive() is True
    assert alarms == [ALARM_DIED]


# ========================================================= 4. bounded revival
class _CountingSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def test_repeated_failures_restart_the_loop_rather_than_waiting_for_a_gesture() -> None:
    """Work item 3. Mid-session there is no owner gesture coming."""

    sleep = _CountingSleep()
    alarms: list[str] = []
    lane = _Lane(explode="pump", error=sqlite3.OperationalError("database is locked"))
    driver = RealtimeDriver(
        lane,
        interval_s=0.0,
        sleep=sleep,
        max_revivals=2,
        on_alarm=lambda kind, m, d: alarms.append(kind),
    )
    # Drive the loop in this thread: `_revive` starts a real thread, so stop
    # the driver first and assert on the bookkeeping instead of racing it.
    for _ in range(DEFAULT_REVIVE_AFTER):
        driver.step()
    assert driver.consecutive_failures == DEFAULT_REVIVE_AFTER
    driver._stop.set()  # `_revive` refuses to start a thread once stopped
    driver._revive()
    assert driver.revivals == 1
    assert alarms == [ALARM_REVIVED]
    assert driver.revival_waits == [0.5], "the documented base of the ladder"
    assert driver.consecutive_failures == 0, "the replacement starts on a clean slate"
    assert "OperationalError" in driver.revival_reasons[0]


def test_the_revival_ladder_is_exponential_capped_and_counted() -> None:
    driver = RealtimeDriver(
        _Lane(),
        interval_s=0.0,
        sleep=_CountingSleep(),
        max_revivals=8,
        revival_backoff_s=0.5,
        revival_backoff_max_s=2.0,
    )
    driver._stop.set()
    for _ in range(6):
        driver.consecutive_failures = DEFAULT_REVIVE_AFTER
        driver._revive()
    assert driver.revival_waits == [0.5, 1.0, 2.0, 2.0, 2.0, 2.0]
    assert driver.revivals == 6


def test_revival_is_BOUNDED_and_the_last_word_is_a_death() -> None:
    """The other half of work item 3, and the reason it is not "just retry".

    An unbounded ladder against a lane whose transport is genuinely gone is a
    hot loop that bills the provider while the operator is told nothing new.
    """

    alarms: list[str] = []
    driver = RealtimeDriver(
        _Lane(),
        interval_s=0.0,
        sleep=_CountingSleep(),
        max_revivals=2,
        on_alarm=lambda kind, m, d: alarms.append(kind),
    )
    driver._stop.set()
    for _ in range(3):
        driver.consecutive_failures = DEFAULT_REVIVE_AFTER
        driver._revive()
    assert driver.revivals == 2
    assert driver.revivals_exhausted is True
    assert alarms == [ALARM_REVIVED, ALARM_REVIVED, ALARM_DIED]
    assert "revival exhausted" in str(driver.death_reason)
    assert driver.snapshot()["revivals_exhausted"] is True


def test_a_fresh_start_is_a_fresh_revival_budget_but_keeps_the_record() -> None:
    driver = RealtimeDriver(_Lane(), interval_s=0.0, sleep=_CountingSleep(), max_revivals=1)
    driver._stop.set()
    for _ in range(2):
        driver.consecutive_failures = DEFAULT_REVIVE_AFTER
        driver._revive()
    assert driver.revivals_exhausted is True
    deaths_before = driver.deaths
    driver.start()
    try:
        assert driver.revivals == 0
        assert driver.revivals_exhausted is False, "a gesture buys resilience, not one loop"
        assert driver.deaths == deaths_before, "the record outlives the restart"
        assert driver.death_reason is not None
    finally:
        driver.stop()


def test_a_pump_that_keeps_failing_really_does_hand_off_to_a_new_thread() -> None:
    """The end-to-end version of work item 3, with real threads.

    The lane fails until the third revival, then recovers. The pump must be
    turning afterwards without anybody having touched it — which is exactly
    what "rather than requiring a fresh owner gesture" means.
    """

    lane = _Lane(explode="pump", error=sqlite3.OperationalError("database is locked"))
    threads: set[int] = set()

    class _WatchingLane(_Lane):
        pass

    driver = RealtimeDriver(
        lane,
        interval_s=0.001,
        sleep=time.sleep,
        max_revivals=DEFAULT_MAX_REVIVALS,
        revival_backoff_s=0.005,
        revival_backoff_max_s=0.02,
    )
    original_step = driver.step

    def _tracking_step() -> int:
        threads.add(threading.get_ident())
        return original_step()

    driver.step = _tracking_step  # type: ignore[method-assign]
    driver.start()
    try:
        deadline = time.monotonic() + 5.0
        while driver.revivals < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        lane.explode = ""
        deadline = time.monotonic() + 5.0
        while len(threads) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert driver.revivals >= 2, "the loop restarted itself"
        assert len(threads) >= 2, "and it did so on a NEW thread"
        assert driver.alive is True, "and there is a pump turning at the end of it"
    finally:
        driver.stop()
    del _WatchingLane


# ============================================== 5. the ledger, at all four sites
def test_the_lane_ledger_write_degrades_to_a_counted_note() -> None:
    """Site 1: ``lane._write_ledger`` — the exact line the audit cited."""

    class _BrokenLedger:
        def write_realtime_turn(self, **kwargs: object) -> int:
            raise sqlite3.OperationalError("attempt to write a readonly database")

    lane = RealtimeLane(
        config=RealtimeConfig(enabled=True, source="test"),
        instructions="x",
        ledger=_BrokenLedger(),
    )
    lane._write_ledger("owner", "die stop", item_id=None)
    assert lane.ledger_failures == 1
    assert lane.ledger_failure_types == {"OperationalError": 1}
    assert "readonly" in str(lane.last_ledger_failure)
    assert any("ledger write failed" in note for note in lane.events)
    assert lane.snapshot()["ledger_failures"] == 1


def test_the_memory_write_path_firewalls_the_engine_but_not_bad_arguments() -> None:
    """Site 2: ``memory.write_realtime_turn`` — the primary, not the mirror."""

    memory = ConversationMemory(":memory:")
    row = memory.write_realtime_turn(
        session_id="s", speaker="owner", text="hello", origin="realtime"
    )
    assert row > 0
    assert memory.realtime_write_failures == 0

    memory.connection.close()  # every later write is a ProgrammingError
    lost = memory.write_realtime_turn(
        session_id="s", speaker="owner", text="die stop", origin="realtime"
    )
    assert lost == 0, "the documented 'no row was written'"
    assert memory.realtime_write_failures == 1
    assert memory.realtime_write_failure_types == {"ProgrammingError": 1}
    assert "ProgrammingError" in str(memory.last_realtime_write_error)

    # Validation is NOT swallowed: a caller passing garbage has a bug, not a
    # full disk, and three call sites depend on this raising.
    with pytest.raises(ValueError):
        memory.write_realtime_turn(session_id="s", speaker="oracle", text="x", origin="realtime")
    with pytest.raises(ValueError):
        memory.write_realtime_turn(session_id="s", speaker="owner", text="  ", origin="realtime")


def test_a_read_only_store_loses_rows_and_keeps_the_conversation(tmp_path: Path) -> None:
    """The configuration in which EVERY hosted write is guaranteed to fail."""

    path = tmp_path / "ledger.sqlite3"
    ConversationMemory(path).add("user", "seed")
    memory = ConversationMemory(path, read_only=True)
    assert memory.write_realtime_turn(
        session_id="s", speaker="owner", text="die stop", origin="realtime"
    ) == 0
    assert memory.realtime_write_failures == 1


def test_the_runtime_ledger_writer_and_its_chat_mirror_are_both_firewalled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sites 3 and 4: ``_write_realtime_ledger`` and ``_RealtimeLedgerMirror``."""

    from parcel_robot.runtime import _RealtimeLedgerMirror

    runtime = _runtime(tmp_path)
    try:
        def _explode(**kwargs: object) -> int:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(runtime.agent.memory, "write_realtime_turn", _explode)
        runtime._write_realtime_ledger("owner", "die stop", item_id=None, session_id="s")
        assert runtime._realtime_ledger_failures == 1

        # The mirror wrapper: BOTH halves, independently.
        mirror = _RealtimeLedgerMirror(runtime)
        assert (
            mirror.write_realtime_turn(
                session_id="s", speaker="robot", text="Stopping.", origin="realtime"
            )
            == 0
        )
        assert mirror.ledger_failures == 1
        monkeypatch.setattr(runtime.agent.memory, "write_realtime_turn", lambda **kw: 7)
        monkeypatch.setattr(
            runtime,
            "mirror_realtime_chat",
            lambda speaker, text: (_ for _ in ()).throw(sqlite3.OperationalError("chat")),
        )
        assert (
            mirror.write_realtime_turn(
                session_id="s", speaker="robot", text="Stopping.", origin="realtime"
            )
            == 7
        ), "a failing mirror never changes what was recorded"
        assert mirror.mirror_failures == 1
    finally:
        runtime.close()


def test_a_dispatch_that_blows_up_is_counted_and_never_leaves_the_pump() -> None:
    """The lane half of work item 1, with a real sqlite error on a real frame."""

    lane = RealtimeLane(config=RealtimeConfig(enabled=True, source="test"), instructions="x")
    lane_end, server_end = transport_pair()
    lane.transport = lane_end
    server_end.send({"type": "session.created", "session": {"id": "sess_1"}})

    def _explode(event: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    lane._dispatch = _explode  # type: ignore[method-assign]
    handled = lane._pump_locked()
    assert handled == 1, "a frame that arrived is a frame that arrived"
    assert lane.dispatch_failure_count == 1
    assert lane.dispatch_failure_types == {"OperationalError": 1}
    assert lane.protocol_errors == [], "a dispatch failure is NOT a protocol refusal"
    assert "SessionCreated" in lane.dispatch_failures[0], "the frame is named"


# ============================== 6. EV-1 §10.3 — the ASR retention handoff
def test_retained_frames_reach_the_evidence_sink_and_never_the_note_ring() -> None:
    """EV-1's last open hole, closed. The sink is the point.

    EV-1 wrote the refusal down in its own §10.3: routing 44 ASR deltas a
    session through ``_note`` would put 44 more rows a session into the
    100-slot ring that card exists to relieve.
    """

    sunk: list[tuple[str, dict[str, Any]]] = []
    lane = RealtimeLane(
        config=RealtimeConfig(enabled=True, source="test"),
        instructions="x",
        retention_sink=lambda name, fields: sunk.append((name, dict(fields))),
    )
    notes_before = len(lane.events)
    for name in RETAINED_EVENT_TYPES:
        lane._dispatch(RetainedEvent(type_name=name, fields={"item_id": "item_1"}))
    assert [name for name, _ in sunk] == list(RETAINED_EVENT_TYPES)
    assert len(lane.events) == notes_before, "not one row into the panel ring"
    assert lane.retained_events == len(RETAINED_EVENT_TYPES)
    assert lane.retained_event_types[
        "conversation.item.input_audio_transcription.delta"
    ] == 1
    assert lane.snapshot()["retention_wired"] is True


def test_a_retained_frame_changes_nothing_about_the_conversation() -> None:
    """Still a no-op for the LANE: no activity, no owed turn, no ledger."""

    clock = _Clock()
    lane = RealtimeLane(
        config=RealtimeConfig(enabled=True, source="test"),
        instructions="x",
        clock=clock,
        retention_sink=lambda name, fields: None,
    )
    lane._last_activity_at = clock()
    clock.advance(30.0)
    before = lane._last_activity_at
    lane._dispatch(RetainedEvent(type_name="input_audio_buffer.committed", fields={}))
    assert lane._last_activity_at == before, "a retained frame is not conversation"
    assert lane._voice_turn_owed is False
    assert lane.text_turns == 0


def test_a_broken_retention_sink_costs_a_counter_and_not_a_turn() -> None:
    def _explode(name: str, fields: dict[str, Any]) -> None:
        raise sqlite3.OperationalError("the evidence disk is full")

    lane = RealtimeLane(
        config=RealtimeConfig(enabled=True, source="test"),
        instructions="x",
        retention_sink=_explode,
    )
    lane._dispatch(RetainedEvent(type_name="input_audio_buffer.committed", fields={}))
    assert lane.retention_failures == 1
    assert lane.retained_events == 1


def test_an_unwired_lane_is_byte_identical_to_the_pre_r22_behaviour() -> None:
    lane = RealtimeLane(config=RealtimeConfig(enabled=True, source="test"), instructions="x")
    lane._dispatch(RetainedEvent(type_name="input_audio_buffer.committed", fields={}))
    assert lane.retained_events == 1, "still counted"
    assert lane.retention_failures == 0
    assert lane.events == [], "and still silent"
    assert lane.snapshot()["retention_wired"] is False


# ======================================================= the runtime, end to end
class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context
        raise AssertionError(f"the local conversation model saw a hosted turn: {transcript!r}")


def _runtime(tmp_path: Path) -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "r22-pump.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
duplex:
  enabled: true
  logging: false
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r22 pump fixture",
        ),
    )


def _realtime_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RobotRuntime:
    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE", "0")
    return _runtime(tmp_path)


def test_the_pump_alarm_reaches_the_safety_ring_and_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Work item 2, end to end. A ``failures`` entry is not enough — this is."""

    runtime = _realtime_runtime(tmp_path, monkeypatch)
    try:
        driver = runtime.realtime_driver
        assert driver is not None
        driver._die("sqlite3.OperationalError: database is locked")

        kinds = [row["kind"] for row in runtime.safety_log]
        assert SAFETY_LOG_PUMP_DIED in kinds
        row = next(r for r in runtime.safety_log if r["kind"] == SAFETY_LOG_PUMP_DIED)
        assert row["source"] == SAFETY_SOURCE_REALTIME_PUMP
        assert row["level"] == "error"
        assert "database is locked" in str(row["text"])
        # And the panel's own block, which is what the browser renders.
        pump = runtime.realtime_snapshot()["pump"]
        assert pump["alive"] is False
        assert pump["deaths"] == 1
        assert "database is locked" in str(pump["death_reason"])
        assert len(pump["alarms"]) == 1
        # The ordinary event ring says so too — belt AND braces.
        assert any("PUMP DEAD" in str(e["text"]) for e in runtime.snapshot()["events"])
    finally:
        runtime.close()


def test_a_revival_is_a_warning_row_and_a_death_is_an_error_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _realtime_runtime(tmp_path, monkeypatch)
    try:
        runtime._realtime_pump_alarm(ALARM_REVIVED, "restarting", {"revivals": 1})
        row = next(r for r in runtime.safety_log if r["kind"] == SAFETY_LOG_PUMP_REVIVED)
        assert row["level"] == "warning"
        assert row["source"] == SAFETY_SOURCE_REALTIME_PUMP
        assert SAFETY_SOURCE_REALTIME_PUMP in SAFETY_SOURCES
    finally:
        runtime.close()


def test_an_unarmed_pump_is_not_an_alarm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before the owner's first gesture there is no session to pump."""

    runtime = _realtime_runtime(tmp_path, monkeypatch)
    try:
        pump = runtime.realtime_snapshot()["pump"]
        assert pump["armed"] is False
        assert pump["alive"] is False
        assert pump["deaths"] == 0
    finally:
        runtime.close()


def test_the_health_loop_probes_the_pump_and_is_quiet_when_it_is_well(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two claims: the probe is silent on a healthy runtime, and it is WIRED.

    The second half is a source pin and is stated as exactly that — the health
    loop is a ten-second `while` on its own thread and asserting it end to end
    would put a ten-second sleep in the commit gate. A source pin cannot prove
    the loop runs; it can and does prove that a refactor which drops the call
    reddens rather than silently removing the supervisor.
    """

    import inspect

    from parcel_robot import runtime as runtime_module

    source = inspect.getsource(runtime_module.RobotRuntime._service_health_loop)
    assert "self._watch_realtime_pump()" in source

    runtime = _realtime_runtime(tmp_path, monkeypatch)
    try:
        runtime._watch_realtime_pump()
        runtime._watch_realtime_pump()
        assert [r for r in runtime.safety_log if r["kind"] == SAFETY_LOG_PUMP_DIED] == []
    finally:
        runtime.close()


def test_the_runtime_retention_sink_writes_evidence_and_not_panel_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EV-1 §10.3's stated reason, with its own number. Card R22, work item 5.

    "Routing 44 ASR deltas per session through ``_note`` → ``_emit`` would put
    44 more rows/session into the 100-slot ring, which is the exact resource
    this card exists to stop overflowing." Forty-four is ``live_run_1``'s
    measured count, so that is what this drives.
    """

    from parcel_robot.realtime.evidence_log import STREAM_EVENT

    runtime = _realtime_runtime(tmp_path, monkeypatch)
    try:
        offered: list[tuple[str, dict[str, Any]]] = []
        monkeypatch.setattr(
            runtime,
            "_offer_evidence",
            lambda stream, row: offered.append((stream, dict(row))),
        )
        before = len(runtime.snapshot()["events"])
        for _ in range(44):
            runtime._retain_realtime_frame(
                "conversation.item.input_audio_transcription.delta",
                {"item_id": "item_1", "delta": "die"},
            )
        assert len(offered) == 44
        assert {stream for stream, _ in offered} == {STREAM_EVENT}
        assert offered[0][1]["kind"] == "retained_event"
        assert offered[0][1]["fields"] == {"item_id": "item_1", "delta": "die"}
        assert len(runtime.snapshot()["events"]) == before, (
            "not one of the 44 reached the 100-slot ring"
        )
    finally:
        runtime.close()


def test_the_driver_docstring_states_what_it_actually_does() -> None:
    """Work item 6. The claim was false outside the caught types; now it is not.

    The module docstring said "the driver records the failure, counts it, and
    keeps going" while catching four types. A docstring that lies about a
    safety property is how the next reader decides not to check.
    """

    from parcel_robot.realtime import driver as driver_module

    doc = driver_module.__doc__ or ""
    assert "anything that is not a ``BaseException``" in doc
    assert "sqlite3.Error" in doc, "the docstring names the type that got through"
    assert "Safety-1" in doc, "and where the finding is written down"
    assert "KeyboardInterrupt" in doc, "and the line the firewall does not cross"


def test_a_store_failure_mid_turn_keeps_the_pump_and_the_spoken_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE CARD'S CENTRAL CLAIM, offline: the incident, reproduced and survived.

    A hosted turn arrives, its ledger write raises ``sqlite3.OperationalError``
    on the pump thread, and afterwards a spoken "die stop" still latches. Before
    R22 the first of those killed the pump and the third never happened.
    """

    runtime = _realtime_runtime(tmp_path, monkeypatch)
    try:
        lane = runtime.realtime_lane
        driver = runtime.realtime_driver
        assert lane is not None and driver is not None
        clock = _Clock()
        # A robot reply comes back, which is what makes ``lane._write_ledger``
        # run ON THE PUMP THREAD — the precise geometry of §Safety-1.
        script = list(handshake()) + [
            Step(
                "response.create",
                (
                    transcript_done("resp_1", "item_robot_1", "Warm and quiet."),
                    audio_done("resp_1", "item_robot_1"),
                    response_done("resp_1"),
                ),
                label="r22_turn",
            )
        ]

        def _factory():
            lane_end, server_end = transport_pair(clock=clock)
            _factory.server = FakeRealtimeServer(
                transport=server_end, script=list(script), clock=clock
            )
            return lane_end

        lane._transport_factory = _factory
        runtime.bind_panel_token("csrf-r22")

        def _explode(**kwargs: object) -> int:
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(runtime.agent.memory, "write_realtime_turn", _explode)
        # This is the gesture that also STARTS the real pump thread, so the
        # store failure below happens on the same thread §Safety-1 is about.
        runtime.submit_realtime_text("how was your day")
        _factory.server.pump()
        assert driver.running is True
        deadline = time.monotonic() + 5.0
        while lane._ledger.ledger_failures < 1 and time.monotonic() < deadline:  # type: ignore[union-attr]
            _factory.server.pump()
            time.sleep(0.01)

        # (a) THE PUMP SURVIVES. Before R22 the ledger write above raised
        # sqlite3.OperationalError out of `_dispatch`, out of `pump()`, and the
        # thread was gone for the rest of the session.
        assert driver.alive is True
        assert driver.deaths == 0
        assert lane.active is True
        # Not merely un-dead: it is still turning AFTER the failure.
        steps_at_failure = driver.steps
        deadline = time.monotonic() + 3.0
        while driver.steps <= steps_at_failure + 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert driver.steps > steps_at_failure + 2

        # (b) the failure was RECORDED rather than swallowed or fatal.
        assert lane._ledger.ledger_failures >= 1  # type: ignore[union-attr]
        assert runtime.realtime_snapshot()["pump"]["alive"] is True

        # (c) a spoken "die stop" still latches afterwards.
        runtime.submit_realtime_text("Die stop.")
        assert runtime.agent.safety.emergency_stopped is True
        assert lane.outcomes[-1].kind == "emergency"
    finally:
        runtime.close()


def test_the_panel_renders_the_alarm_beside_the_safety_log() -> None:
    """``ui/index.html`` is executed by zero tests (the audit says so), so this
    is a string pin — stated as exactly that, and it pins the WIRING, which is
    the part a refactor silently breaks."""

    panel = (REPO / "src" / "parcel_robot" / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="pump-alarm"' in panel
    assert "function renderPumpAlarm(realtime)" in panel
    # The CALL, and it must be LIVE. Asserting the bare substring is the hole a
    # seed found: `// renderPumpAlarm(snapshot.realtime);` satisfies it and
    # renders nothing. Every line that mentions the call must be a real call.
    call_lines = [
        line for line in panel.splitlines() if "renderPumpAlarm(snapshot.realtime)" in line
    ]
    assert call_lines, "the render is never called"
    for line in call_lines:
        assert not line.lstrip().startswith(("//", "/*", "*")), line
    # It reads the field the runtime actually publishes.
    assert "realtime.pump" in panel
    assert "pump.death_reason" in panel
    assert "pump.heartbeat_age_s" in panel
    # And it sits inside the same block as the safety log.
    safety_at = panel.index('id="safety-log"')
    alarm_at = panel.index('id="pump-alarm"')
    divider_at = panel.index("section-divider", safety_at)
    assert safety_at < alarm_at < divider_at, "the alarm is beside the safety log"
    # The two new safety kinds are rendered, not left as raw wire values. Same
    # hole, same fix: pin the LOOKUP, not just the function name — a
    # `safetyKindLabel` that ignores its own table renders "Pump_died".
    assert "pump_died" in panel and "pump_revived" in panel
    assert "safetyKindLabel(item.kind)" in panel
    assert "SAFETY_KIND_LABELS[key] ||" in panel
    assert '"Pump dead"' in panel and '"Pump revived"' in panel
