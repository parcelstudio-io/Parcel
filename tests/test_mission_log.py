"""Card R4-lite, task_1 — Defect B: a mission you can see.

WHAT THIS FILE PINS
-------------------
The live incident: the owner's mission started ("Navigating to sidewalk.") and
ended with NO terminal event anywhere. ``navigation`` was left holding
``enabled: false, goal: sidewalk, reason: navigation_disabled`` and the panel
showed nothing at all. The mission had simply stopped existing.

Three separate failures produced that, and each has its own test here:

1. ``_stop_navigation_channel`` — the choke point every non-arrival terminal
   passes through — wrote the terminal into ``_navigation_detail`` and told
   nobody. No event, no record, no sentence.
2. Even a terminal that DID emit could be evicted: the event deque is 100 slots
   shared with every chatty source, and proximity chatter can flip at the 10 Hz
   control rate. Ten seconds of a robot hovering on the slow/clear threshold is
   enough to flush a mission's whole history out of the panel.
3. Nothing ever told the MODEL, so a hosted session narrated silence while the
   dog stood in front of a pedestrian.

The mission log is a small bounded ring of lifecycle FACTS, separate from the
event deque on purpose. These tests state what belongs in it, what must never
be allowed to flood it, and — the bait the audit will pull on — that narration
is floor-gated and can never become per-tick chatter.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.contracts import FrozenDict, SuccessCondition
from parcel_robot.brain.executive import DispatchRequest
from parcel_robot.brain.runtime_adapter import ActiveSemanticDispatch
from parcel_robot.models import VelocityCommand
from parcel_robot.realtime.config import WhispererConfig
from parcel_robot.realtime.whisperer import BLOCK_DEBOUNCE_S, Whisperer
from parcel_robot.runtime import (
    MISSION_BLOCK_MIN_INTERVAL_S,
    MISSION_LOG_BLOCKED,
    MISSION_LOG_BLOCKED_MAX,
    MISSION_LOG_ENDED,
    MISSION_LOG_MAX,
    MISSION_LOG_STARTED,
    PROXIMITY_EVENT_MIN_INTERVAL_S,
    RobotRuntime,
)

REPO = Path(__file__).resolve().parents[1]

#: The exact note the navigator writes when a person gates the mission. The
#: yield policy matches it as a `|`-delimited SEGMENT, never a substring.
PERSON_STOP_NOTE = "grid_track err=0.31 goal=0.8 route=2 status=planned|person_stop"


def _live_person_note(tick: int) -> str:
    """A person-gated note as the LIVE navigator actually writes it.

    The numbers move on every 10 Hz tick. This is not decoration: the first
    version of the blocked-entry edge keyed on the whole note, so every tick
    counted as a new episode. The 2026-08-18 live proof filled the ring with 20
    rows in two seconds and drove 69 model narrations from one owner turn, and
    the offline test missed it purely because it passed a CONSTANT note. Any
    test of the edge has to vary the telemetry the way the robot does.
    """

    return f"grid_track err={9.6 - tick * 0.05:.1f} goal=0.8 route=2 status=planned|person_stop"


def _live_obstacle_note(tick: int) -> str:
    return f"grid_track err={4.2 - tick * 0.05:.1f} goal=0.8 route=2 status=planned|obstacle_stop"


class _Backend:
    """The smallest backend a runtime will boot against."""

    name = "mission-log"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=0.0,
            robot=RobotPose(x=0.0, y=0.0, z=0.0, yaw=0.0),
            owner=OwnerTrack(x=1.0, y=0.0, visible=True, confidence=1.0),
            nearest_obstacle_m=4.0,
            backend=self.name,
        )

    def observe(self) -> SimObservation:
        return self._observation

    def send_velocity(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def close(self) -> None:
        return None


class _MissionClock:
    """Monotonic seconds the test moves by hand."""

    def __init__(self, start: float = 10_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


@pytest.fixture()
def config(tmp_path: Path) -> Path:
    path = tmp_path / "robot-mission-log.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
  config: {REPO / "configs" / "navigation" / "default.yaml"}
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def runtime(config: Path):
    backend = _Backend()
    session = RobotRuntime(
        config,
        backend,
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="deterministic test status",
        ),
    )
    observation = backend.observe()
    session._observation = observation
    if session._control_state_source is not None:
        session._control_state_source.update_observation(observation)
    # The mission log's rate limit is real-time; drive it by hand so nothing
    # here depends on how fast the test machine is.
    session._mission_clock = _MissionClock()
    try:
        yield session
    finally:
        session.close()


def _advance(runtime: RobotRuntime, seconds: float) -> None:
    runtime._mission_clock.advance(seconds)


def _arm_mission(runtime: RobotRuntime, *, goal: str = "the sidewalk") -> None:
    """Put the runtime in the state a running mission leaves behind."""

    runtime._navigation_directive = f"navigate to {goal}"
    runtime._navigation_detail = {
        "enabled": True,
        "state": "navigating",
        "directive": f"navigate to {goal}",
        "goal": goal,
        "reason": "grid_track err=0.10 status=planned",
    }


def _kinds(runtime: RobotRuntime) -> list[str]:
    return [str(row["kind"]) for row in runtime.mission_log()]


class _WhispererClock:
    """Card R11. The whisperer's clock, driven by hand.

    The block debounce is measured in seconds of held block; a test that waited
    for them would be a test that takes eight seconds and still cannot say
    whether it was the debounce or the scheduler that produced the answer.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)

    def __call__(self) -> float:
        return self.now


def _whisperer_tick(runtime: RobotRuntime, now: float) -> None:
    """One control-loop whisperer step at an exact time."""

    runtime._step_whisperer(runtime._observation, now=now)


# ------------------------------------------------------- the silent terminal
def test_a_mission_terminal_is_never_silent(runtime: RobotRuntime) -> None:
    """Defect B's root cause, stated directly.

    ``_stop_navigation_channel`` is where preempt, the executive's task
    teardown, a behavior switch, an owner stop and the yield policy's give-up
    all end up. It used to write ``enabled: False`` and return.
    """

    _arm_mission(runtime)
    runtime._events.clear()

    runtime._stop_navigation_channel(reason="task_no_longer_active", state="cancelled")

    log = runtime.mission_log()
    assert log, "a mission ended and left no lifecycle record at all"
    terminal = log[-1]
    assert terminal["kind"] == MISSION_LOG_ENDED
    assert terminal["goal"] == "the sidewalk"
    assert terminal["reason"] == "task_no_longer_active"
    assert terminal["state"] == "cancelled"
    assert terminal["timestamp"]
    assert any(event["role"] == "navigation" for event in runtime._events), (
        "the terminal must also reach the event stream"
    )


def test_the_default_reason_terminal_is_recorded_too(runtime: RobotRuntime) -> None:
    """The owner's exact incident: a stop taken with the DEFAULT reason.

    ``navigation_disabled`` is the dataclass default, which is what the detail
    is left holding when a caller stops the channel without saying why. That
    caller is the one that produced an unexplained mission end, so it is
    precisely the one that must leave a record.
    """

    _arm_mission(runtime)
    runtime._stop_navigation_channel()

    terminal = runtime.mission_log()[-1]
    assert terminal["kind"] == MISSION_LOG_ENDED
    assert terminal["reason"] == "navigation_disabled"
    assert terminal["goal"] == "the sidewalk"
    assert "the sidewalk" in str(terminal["text"])


def test_stopping_an_idle_channel_records_nothing(runtime: RobotRuntime) -> None:
    """No mission, no terminal. The ring holds facts, not noise."""

    runtime._stop_navigation_channel(reason="task_no_longer_active")
    assert runtime.mission_log() == []


# ------------------------------------------------------------ blocked entries
def test_a_blocked_episode_is_one_entry_not_six_hundred(runtime: RobotRuntime) -> None:
    """The navigation step runs at 10 Hz. The ENTRY is the fact, not the tick."""

    _arm_mission(runtime)
    for tick in range(600):
        runtime._note_mission_block(goal="the sidewalk", note=_live_person_note(tick), blocked=True)

    blocked = [row for row in runtime.mission_log() if row["kind"] == MISSION_LOG_BLOCKED]
    assert len(blocked) == 1, (
        f"a minute of waiting must be one row, got {len(blocked)}; "
        "the edge must key on the block CLASS, not the live telemetry in the note"
    )
    assert blocked[0]["state"] == "blocked"
    assert "someone is in the way" in str(blocked[0]["text"]).lower()


def test_the_way_clearing_again_is_its_own_entry(runtime: RobotRuntime) -> None:
    """Two rows for an episode: entered blocked, and came out of it."""

    _arm_mission(runtime)
    runtime._note_mission_block(goal="the sidewalk", note=_live_person_note(0), blocked=True)
    _advance(runtime, MISSION_BLOCK_MIN_INTERVAL_S + 1.0)
    for tick in range(50):
        runtime._note_mission_block(
            goal="the sidewalk",
            note=f"grid_track err={tick * 0.01:.2f} status=planned",
            blocked=False,
        )

    rows = [row for row in runtime.mission_log() if row["kind"] == MISSION_LOG_BLOCKED]
    assert [str(row["state"]) for row in rows] == ["blocked", "navigating"]
    assert str(rows[0]["reason"]) == _live_person_note(0), "the row keeps the full note"
    assert str(rows[-1]["reason"]) == "clear"


def test_a_changed_block_class_is_a_new_entry(runtime: RobotRuntime) -> None:
    """The edge is coarse, but not blind: obstacle → person is a real change."""

    _arm_mission(runtime)
    for tick in range(20):
        runtime._note_mission_block(
            goal="the sidewalk", note=_live_obstacle_note(tick), blocked=True
        )
    _advance(runtime, MISSION_BLOCK_MIN_INTERVAL_S + 1.0)
    for tick in range(20):
        runtime._note_mission_block(goal="the sidewalk", note=_live_person_note(tick), blocked=True)

    rows = [row for row in runtime.mission_log() if row["kind"] == MISSION_LOG_BLOCKED]
    assert len(rows) == 2, "the block CLASS changed; that is one new entry, not twenty"
    assert "something is blocking" in str(rows[0]["text"]).lower()
    assert "someone is in the way" in str(rows[1]["text"]).lower()


def test_the_ring_survives_a_long_block_with_room_for_the_terminal(
    runtime: RobotRuntime,
) -> None:
    """The live regression, stated as the thing that actually broke.

    On 2026-08-18 a single "walk over to the sidewalk" filled all 20 slots with
    blocked rows before the mission ever ended, so the ring built to preserve
    terminals could not hold one. The whole mission — start, block, end — must
    fit with room to spare.
    """

    _arm_mission(runtime)
    runtime._log_mission(MISSION_LOG_STARTED, goal="the sidewalk", state="running")
    for tick in range(2_000):
        _advance(runtime, 0.1)
        runtime._note_mission_block(
            goal="the sidewalk", note=_live_person_note(tick % 100), blocked=True
        )
    runtime._stop_navigation_channel(reason="blocked_by_person", state="failed")

    log = runtime.mission_log()
    assert len(log) == 3, f"a whole mission should be three rows, got {len(log)}: {log}"
    assert [str(row["kind"]) for row in log] == [
        MISSION_LOG_STARTED,
        MISSION_LOG_BLOCKED,
        MISSION_LOG_ENDED,
    ]


def test_a_flapping_pedestrian_stream_cannot_fill_the_ring(runtime: RobotRuntime) -> None:
    """The second half of the live regression.

    Keying on the class was not enough: a real pedestrian stream flips
    person → clear → obstacle → person for real, and the 2026-08-18 proof still
    spent 18 of 20 slots on it. Blocked rows are rate-limited, and whatever
    survives that evicts other BLOCKED rows before anything else.
    """

    _arm_mission(runtime)
    runtime._log_mission(MISSION_LOG_STARTED, goal="the sidewalk", state="running")
    for tick in range(3_000):
        # person / clear / obstacle, over and over, exactly as the city does,
        # at the 10 Hz the navigation step actually runs at.
        _advance(runtime, 0.1)
        phase = tick % 3
        if phase == 0:
            runtime._note_mission_block(
                goal="the sidewalk", note=_live_person_note(tick), blocked=True
            )
        elif phase == 1:
            runtime._note_mission_block(
                goal="the sidewalk", note=f"grid_track err={tick} status=planned", blocked=False
            )
        else:
            runtime._note_mission_block(
                goal="the sidewalk", note=_live_obstacle_note(tick), blocked=True
            )
    runtime._stop_navigation_channel(reason="blocked_by_person", state="failed")

    log = runtime.mission_log()
    blocked = [row for row in log if row["kind"] == MISSION_LOG_BLOCKED]
    assert len(blocked) <= MISSION_LOG_BLOCKED_MAX, (
        f"blocked rows took {len(blocked)} of {len(log)} slots"
    )
    kinds = [str(row["kind"]) for row in log]
    assert MISSION_LOG_STARTED in kinds, "the start was evicted by block chatter"
    assert MISSION_LOG_ENDED in kinds, "the TERMINAL was evicted by block chatter"
    assert kinds[-1] == MISSION_LOG_ENDED
    assert any("more changes" in str(row["text"]) for row in blocked), (
        "suppressed transitions must be counted, never silently dropped"
    )


def test_blocked_rows_are_rate_limited_on_the_injected_clock(runtime: RobotRuntime) -> None:
    """The interval is real time, so the clock is driven by hand."""

    _arm_mission(runtime)

    runtime._note_mission_block(goal="the sidewalk", note=_live_person_note(0), blocked=True)
    assert len(runtime.mission_log()) == 1

    # Inside the window: counted, not written.
    for tick in range(1, 40):
        _advance(runtime, 0.1)
        blocked = tick % 2 == 0
        runtime._note_mission_block(
            goal="the sidewalk",
            note=_live_person_note(tick) if blocked else "status=planned",
            blocked=blocked,
        )
    assert len(runtime.mission_log()) == 1, "the rate limit did not hold"

    # Past the window: the next real transition writes, and says what it folded
    # in. The loop above left the class at "clear", so blocking again is a change.
    _advance(runtime, MISSION_BLOCK_MIN_INTERVAL_S + 1.0)
    runtime._note_mission_block(goal="the sidewalk", note=_live_person_note(99), blocked=True)
    log = runtime.mission_log()
    assert len(log) == 2
    assert "more changes" in str(log[-1]["text"])


def test_a_terminal_closes_the_blocked_edge(runtime: RobotRuntime) -> None:
    """The next mission's block must not be swallowed by the last one's note."""

    _arm_mission(runtime)
    runtime._note_mission_block(goal="the sidewalk", note=_live_person_note(0), blocked=True)
    runtime._stop_navigation_channel(reason="blocked_by_person", state="failed")

    _arm_mission(runtime, goal="the bench")
    runtime._note_mission_block(goal="the bench", note=_live_person_note(5), blocked=True)

    blocked = [row for row in runtime.mission_log() if row["kind"] == MISSION_LOG_BLOCKED]
    assert [str(row["goal"]) for row in blocked] == ["the sidewalk", "the bench"]


# ------------------------------------------------------------ the ring itself
def test_the_ring_is_bounded_and_keeps_the_newest(runtime: RobotRuntime) -> None:
    for index in range(MISSION_LOG_MAX * 3):
        runtime._log_mission(MISSION_LOG_STARTED, goal=f"place-{index}")

    log = runtime.mission_log()
    assert len(log) == MISSION_LOG_MAX
    assert log[-1]["goal"] == f"place-{MISSION_LOG_MAX * 3 - 1}"
    assert [row["id"] for row in log] == sorted(row["id"] for row in log)


def test_chatter_cannot_evict_the_mission_log(runtime: RobotRuntime) -> None:
    """The whole reason the ring exists, as an experiment.

    Flood the event deque exactly the way proximity chatter did. The mission
    terminal is gone from ``events`` and still present in the mission log.
    """

    _arm_mission(runtime)
    runtime._stop_navigation_channel(reason="task_no_longer_active", state="cancelled")
    assert any("Mission to" in str(event["text"]) for event in runtime._events)

    for index in range(400):
        runtime._emit("safety", f"Slowing near an obstacle {index}", "info")

    assert not any("Mission to" in str(event["text"]) for event in runtime._events), (
        "the flood should have evicted the event; that is the failure mode"
    )
    assert any(row["kind"] == MISSION_LOG_ENDED for row in runtime.mission_log()), (
        "the mission log must survive what the event deque cannot"
    )


def test_the_mission_log_reaches_the_snapshot(runtime: RobotRuntime) -> None:
    _arm_mission(runtime)
    runtime._stop_navigation_channel(reason="task_no_longer_active", state="cancelled")

    snapshot = runtime.snapshot()
    assert "mission_log" in snapshot
    rows = snapshot["mission_log"]
    assert isinstance(rows, list) and rows
    assert set(rows[-1]) >= {"id", "kind", "goal", "state", "reason", "level", "text", "timestamp"}

    # The panel renders it straight from the snapshot; it must be JSON-safe and
    # must not alias the runtime's own ring.
    rows[-1]["goal"] = "mutated"
    assert runtime.mission_log()[-1]["goal"] != "mutated"


# --------------------------------------------------- defect C: obstacle chatter
def test_proximity_chatter_is_coalesced_not_repeated(runtime: RobotRuntime) -> None:
    """A flapping threshold must not be able to flush the event deque."""

    runtime._events.clear()
    now = 100.0
    for index in range(200):
        # The exact pathology: slow/clear flipping at the 10 Hz control rate.
        runtime._emit_proximity_change("slowing" if index % 2 else "clear", now)
        now += 0.1

    safety = [event for event in runtime._events if event["role"] == "safety"]
    assert len(safety) <= 6, f"proximity chatter was not coalesced: {len(safety)} events"
    assert any("more proximity changes" in str(event["text"]) for event in safety), (
        "coalesced transitions must be counted, never silently dropped"
    )


def test_a_proximity_stop_is_never_withheld(runtime: RobotRuntime) -> None:
    """Rate limiting is for chatter. A hard stop is a safety fact."""

    runtime._events.clear()
    runtime._emit_proximity_change("slowing", 100.0)
    runtime._emit_proximity_change("stopped", 100.1)

    texts = [str(event["text"]) for event in runtime._events]
    assert any("Proximity stop" in text for text in texts)


def test_proximity_transitions_still_advance_the_state(runtime: RobotRuntime) -> None:
    """Coalescing changes the EVENT, never the gate."""

    runtime._emit_proximity_change("slowing", 100.0)
    assert runtime._proximity_state == "slowing"
    runtime._emit_proximity_change("stopped", 100.05)
    assert runtime._proximity_state == "stopped"
    runtime._emit_proximity_change("clear", 100.1 + PROXIMITY_EVENT_MIN_INTERVAL_S)
    assert runtime._proximity_state == "clear"


# ------------------------------------------------------- defect B.3: narration
class _FakeLane:
    """The three lane members the narration gate reads, plus a call log."""

    def __init__(self, *, active=True, recovering=False, playing=False) -> None:
        self.active = active
        self.recovering = recovering
        self.playback_owned = playing
        self.narrated: list[str] = []
        self.narrated_critical: list[bool] = []
        self.closed = 0

    def narrate_event(self, text: str, *, critical: bool = False) -> bool:
        # Card R25 widened the lane's narration door with a cost-ceiling
        # exemption flag; a double that does not accept it makes every
        # narration raise TypeError into `_narrate_mission`'s catch, which
        # reads as "the robot had nothing to say".
        self.narrated.append(text)
        self.narrated_critical.append(bool(critical))
        return True

    def close(self) -> None:
        self.closed += 1


def test_a_mission_terminal_is_narrated_to_the_model(runtime: RobotRuntime) -> None:
    lane = _FakeLane()
    runtime.realtime_lane = lane  # type: ignore[assignment]
    _arm_mission(runtime)

    runtime._stop_navigation_channel(reason="blocked_by_person", state="failed")

    assert lane.narrated, "the model was told nothing about a mission that ended"
    assert "the sidewalk" in lane.narrated[-1]
    assert "person" in lane.narrated[-1].lower()


def test_a_person_block_is_narrated_once_per_episode(runtime: RobotRuntime) -> None:
    """The bait: narration must never become per-tick spam.

    600 ticks of standing behind a pedestrian is ONE sentence to the model.

    CARD R11 CHANGED THE ROUTE, NOT THE CLAIM. Until R11 the block edge called
    ``_narrate_mission_block`` directly, so the claim was "600 ticks produce 1
    sentence". A block is now a MIDDLE-band fact that has to hold for
    ``BLOCK_DEBOUNCE_S`` before it is worth saying (bench B2, which caught 11/12
    gold facts with 0 spam largely on the strength of that debounce), so the
    claim is now strictly stronger and is asserted in three parts: 600 ticks
    produce ZERO sentences on their own; a block that HOLDS produces exactly
    one; and 600 more ticks after that produce no more.
    """

    lane = _FakeLane()
    runtime.realtime_lane = lane  # type: ignore[assignment]
    _arm_mission(runtime)
    clock = _WhispererClock()
    runtime.realtime_whisperer = Whisperer(config=WhispererConfig(), clock=clock)

    for tick in range(600):
        runtime._note_mission_block(goal="the sidewalk", note=_live_person_note(tick), blocked=True)

    assert lane.narrated == [], "a block edge spoke before the debounce had run"

    # The block holds. Digests at 1 Hz, exactly as the control loop feeds them.
    for _ in range(int(BLOCK_DEBOUNCE_S) + 4):
        clock.advance(1.0)
        _whisperer_tick(runtime, clock.now)

    assert len(lane.narrated) == 1, f"narration spammed the session: {len(lane.narrated)} items"
    assert "waiting" in lane.narrated[0].lower()

    for tick in range(600):
        runtime._note_mission_block(goal="the sidewalk", note=_live_person_note(tick), blocked=True)
    for _ in range(30):
        clock.advance(1.0)
        _whisperer_tick(runtime, clock.now)

    assert len(lane.narrated) == 1, "a held block said the same thing twice"


def test_narration_never_shortens_the_wait(runtime: RobotRuntime) -> None:
    """Owner-gated B22: narrate the wait, never weaken the policy.

    Recording and narrating a block must leave every yield/person-stop knob
    exactly where it was.
    """

    lane = _FakeLane()
    runtime.realtime_lane = lane  # type: ignore[assignment]
    _arm_mission(runtime)
    before = (
        runtime.person_stop_m,
        replace(runtime._yield_profile),
        runtime._yield_tracker.snapshot(),
    )

    runtime._note_mission_block(goal="the sidewalk", note=_live_person_note(0), blocked=True)

    after = (
        runtime.person_stop_m,
        replace(runtime._yield_profile),
        runtime._yield_tracker.snapshot(),
    )
    assert before == after


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"active": False}, "no session to narrate into"),
        ({"recovering": True}, "the session is being replaced"),
        ({"playing": True}, "the model already has the mouth"),
    ],
)
def test_the_floor_gate_refuses_when_the_floor_is_taken(
    runtime: RobotRuntime, kwargs: dict[str, bool], why: str
) -> None:
    lane = _FakeLane(**kwargs)
    runtime.realtime_lane = lane  # type: ignore[assignment]
    _arm_mission(runtime)

    runtime._stop_navigation_channel(reason="task_no_longer_active", state="cancelled")

    assert lane.narrated == [], why
    assert runtime.mission_log(), "the FACT is recorded whether or not it is spoken"


def test_a_narration_failure_never_takes_down_the_terminal(runtime: RobotRuntime) -> None:
    """The mission log is the guarantee; narration is the nicety."""

    class _AngryLane(_FakeLane):
        def narrate_event(self, text: str, *, critical: bool = False) -> bool:
            raise RuntimeError("provider said no")

    runtime.realtime_lane = _AngryLane()  # type: ignore[assignment]
    _arm_mission(runtime)

    runtime._stop_navigation_channel(reason="task_no_longer_active", state="cancelled")

    assert runtime.mission_log()[-1]["kind"] == MISSION_LOG_ENDED


def test_no_lane_means_no_narration_and_no_error(runtime: RobotRuntime) -> None:
    """A flag-off panel must be byte-identical on this path."""

    runtime.realtime_lane = None
    _arm_mission(runtime)
    runtime._stop_navigation_channel(reason="task_no_longer_active", state="cancelled")
    assert runtime.mission_log()[-1]["kind"] == MISSION_LOG_ENDED


# ===================================================== card R12: the reason survives
# AUDIT_R9_FABLE owner-gated finding 2, approved by the owner's ruling ("rename
# to emergency stop"). Every test above calls ``_stop_navigation_channel``
# DIRECTLY with a reason, which is why they all passed while the owner's e-stop
# was reaching the log as ``navigation_disabled``: the real callers do not call
# it directly. They call ``preempt()``, which goes through
# ``NavigationChannel.stop(reason)`` — and that adapter did ``del reason``.
#
# So these tests enter through ``preempt`` and the channel, never through the
# choke point, because the gap was in the WIRING and a test that skips the
# wiring cannot see it.
def test_a_preempt_reason_reaches_the_terminal_through_the_channel(
    runtime: RobotRuntime,
) -> None:
    """The root cause, stated at the level it actually broke.

    The owner latches the emergency stop on a running mission. What the mission
    log, the panel event and the navigation detail must all say is what ended
    it — not the dataclass default they used to be left holding.
    """

    _arm_mission(runtime)
    runtime._events.clear()

    runtime.preempt("safety", reason="emergency_stop", targets=("navigation",))

    terminal = runtime.mission_log()[-1]
    assert terminal["kind"] == MISSION_LOG_ENDED
    assert terminal["reason"] == "emergency_stop", (
        "the channel threw the preempting reason away again — this is the R9 defect"
    )
    assert terminal["goal"] == "the sidewalk"
    assert "emergency_stop" in str(terminal["text"])
    events = [event for event in runtime._events if event["role"] == "navigation"]
    assert events, "the terminal never reached the panel event stream"
    assert "emergency_stop" in str(events[-1]["text"])
    assert runtime._navigation_detail["reason"] == "emergency_stop"


@pytest.mark.parametrize(
    ("claimant", "reason"),
    [
        # Every one of these is a REAL call site in runtime.py. If a call site
        # is renamed, this list is where the rename has to be answered — a
        # reason that stops existing must not quietly become the default again.
        ("safety", "emergency_stop"),
        ("safety", "simulator_emergency_stop"),
        ("manual", "operator_stop"),
        ("manual", "manual_control"),
        ("manual", "runtime_closed"),
        ("voice", "voice_motion_started"),
        ("voice", "hold_skill"),
        ("follow", "owner_follow_started"),
        ("search", "owner_search_started"),
        ("spatial", "replaced_by_new_spatial_behavior"),
        ("pose", "pose_started"),
        ("trajectory", "trajectory_started"),
        ("safety", "perception_unavailable"),
    ],
)
def test_every_preempt_reason_survives_the_channel_verbatim(
    runtime: RobotRuntime, claimant: str, reason: str
) -> None:
    """Not just the e-stop. The fix is propagation, so all of them arrive.

    The owner's ruling named the emergency stop, but a fix that only special-
    cased the e-stop would leave the same hole under every other word and would
    have to be re-fixed once per reason.
    """

    _arm_mission(runtime)

    taken = runtime.preempt(claimant, reason=reason, targets=("navigation",))

    assert taken["navigation"] == "stop"
    assert runtime.mission_log()[-1]["reason"] == reason


def test_a_non_emergency_preempt_is_never_relabelled_an_emergency_stop(
    runtime: RobotRuntime,
) -> None:
    """The over-correction, pinned.

    "Make the e-stop say emergency_stop" has a cheap wrong answer — write
    ``emergency_stop`` into the terminal — and that answer is worse than the
    defect it replaces. ``navigation_disabled`` was uninformative; an
    ``emergency_stop`` on a mission nobody e-stopped is a false safety record.
    """

    _arm_mission(runtime)
    lane = _FakeLane()
    runtime.realtime_lane = lane  # type: ignore[assignment]

    runtime.preempt("manual", reason="operator_stop", targets=("navigation",))

    terminal = runtime.mission_log()[-1]
    assert terminal["reason"] == "operator_stop"
    assert "emergency" not in str(terminal["reason"]).lower()
    assert "emergency" not in str(terminal["text"]).lower()
    assert lane.narrated, "the owner's own stop was not narrated at all"
    assert "emergency" not in lane.narrated[-1].lower()
    assert not runtime.arbiter.emergency_stopped, (
        "nothing here may latch the arbiter — this test would otherwise be "
        "asserting the wording of a real emergency stop"
    )


def test_a_latched_estop_is_narrated_as_a_latched_estop(runtime: RobotRuntime) -> None:
    """The narrated FACT, not just the log row.

    Before propagation the model was told the trip "ended (idle) because of:
    navigation_disabled" — a sentence about a config flag, offered to a
    companion that was being asked to explain to a person why the dog stopped.
    """

    _arm_mission(runtime)
    lane = _FakeLane()
    runtime.realtime_lane = lane  # type: ignore[assignment]

    runtime.preempt("safety", reason="emergency_stop", targets=("navigation",))

    assert lane.narrated, "the model was told nothing about an e-stopped mission"
    said = lane.narrated[-1].lower()
    assert "emergency stop was latched" in said
    assert "the sidewalk" in said
    assert "navigation_disabled" not in said


def test_the_estop_wording_is_chosen_by_membership_never_by_substring(
    runtime: RobotRuntime,
) -> None:
    """R11's lesson, applied to a set instead of a dedup key.

    ``EMERGENCY_STOP_TERMINAL_REASONS`` picks the narrated wording, and the
    tempting cheap form is ``any(word in reason ...)``. A navigator note or a
    compound reason that merely CONTAINS the word would then be narrated as a
    latched emergency stop — a fabricated safety event, spoken aloud to the
    owner. Reasons are whole tokens; membership is the whole test.
    """

    _arm_mission(runtime)
    lane = _FakeLane()
    runtime.realtime_lane = lane  # type: ignore[assignment]

    runtime.preempt("manual", reason="deferred_emergency_stop_release", targets=("navigation",))

    assert runtime.mission_log()[-1]["reason"] == "deferred_emergency_stop_release"
    assert lane.narrated
    assert "was latched" not in lane.narrated[-1].lower(), (
        "a reason that merely contains the word was narrated as an e-stop"
    )


def test_a_blank_reason_falls_back_to_the_default_not_to_a_blank(
    runtime: RobotRuntime,
) -> None:
    """The hole propagation OPENS, closed in the same change.

    While the reason was discarded, no caller could put an empty string in the
    terminal. Now that it is carried, one can — and a mission whose recorded
    end is ``""`` is exactly as unexplained as the incident that started this.
    """

    _arm_mission(runtime)
    channel = runtime._channels.get("navigation")
    assert channel is not None

    channel.stop("")

    terminal = runtime.mission_log()[-1]
    assert terminal["reason"] == "navigation_disabled"
    assert runtime._navigation_detail["reason"] == "navigation_disabled"


def _plant_a_running_executive_step(runtime: RobotRuntime) -> None:
    """Leave behind exactly what a dispatched ``NavigateTo`` step leaves behind.

    NOT a shortcut for ``semantic_tasks.dispatch``: dispatch would start a real
    navigation. What this reproduces is the STATE the executive is holding when
    the owner hits the e-stop — one active dispatch whose executive record is
    about to disappear — because that state is what turns the interrupt into a
    channel teardown, and the teardown is what wins the race with the caller's
    own preempt.
    """

    request = DispatchRequest(
        task_id="r12-estop",
        plan_revision=1,
        step_id="step-1",
        attempt=1,
        skill="NavigateTo",
        arguments=FrozenDict({"place": "the sidewalk"}),
        success=SuccessCondition(fact="at_place", target="the sidewalk"),
        resources=("base",),
        timeout_s=240.0,
    )
    active = ActiveSemanticDispatch(request=request, started_at_monotonic_s=0.0)
    runtime.semantic_tasks._active[active.key] = active


@pytest.mark.parametrize(
    ("door", "expected"),
    [
        ("emergency_stop", "emergency_stop"),
        ("action_emergency_stop", "emergency_stop"),
        ("action_stop", "operator_stop"),
        ("manual_motion", "manual_control"),
    ],
)
def test_the_executive_teardown_records_the_cause_that_interrupted_it(
    runtime: RobotRuntime, door: str, expected: str
) -> None:
    """THE LIVE DEFECT, reproduced offline. Found by the R12 live proof.

    Every test above arms the mission by hand, so no executive task exists and
    the caller's own ``preempt`` writes the terminal. On the real stack there IS
    an executive task, and the order inside ``emergency_stop`` is:

        _interrupt_brain(...)   # tears the task down -> stops the channel
        preempt("safety", reason="emergency_stop", ...)   # nothing left to stop

    so the teardown wrote the terminal with its own generic
    ``task_no_longer_active`` and the owner's reason never reached the log —
    even with the channel propagation in place. The live run recorded exactly
    that: ``Mission to sidewalk ended (idle): task_no_longer_active``.

    The cause now travels with the interrupt, so whichever of the two writes
    the terminal, it writes the same word.
    """

    _arm_mission(runtime)
    _plant_a_running_executive_step(runtime)

    if door == "emergency_stop":
        runtime.emergency_stop()
    elif door == "action_emergency_stop":
        runtime.action("emergency_stop")
    elif door == "action_stop":
        runtime.action("stop")
    else:
        runtime.manual_motion(0.2, 0.0, 0.0)

    terminal = runtime.mission_log()[-1]
    assert terminal["kind"] == MISSION_LOG_ENDED
    assert terminal["reason"] == expected, (
        "the executive teardown overwrote the caller's cause with its own "
        "generic word — this is the defect the live proof found"
    )
    assert terminal["goal"] == "the sidewalk"


def test_a_plan_step_that_simply_ended_still_says_so(runtime: RobotRuntime) -> None:
    """The default is not collateral damage.

    ``task_no_longer_active`` is the right word when reconciliation runs on the
    executive's own tick — no owner, no e-stop, just a plan step whose record is
    gone. Propagating the interrupting cause must not repaint that case.
    """

    _arm_mission(runtime)
    _plant_a_running_executive_step(runtime)

    runtime._reconcile_semantic_tasks()

    assert runtime.mission_log()[-1]["reason"] == "task_no_longer_active"


def test_the_channel_adapter_does_not_invent_a_reason_of_its_own(
    runtime: RobotRuntime,
) -> None:
    """``NavigationChannel`` is a pass-through, not an author.

    Asserted against the adapter directly so the claim survives a refactor of
    the runtime side: whatever word the caller used is the word that arrives.
    """

    _arm_mission(runtime)
    channel = runtime._channels.get("navigation")
    assert channel is not None

    channel.stop("a reason no call site uses")

    assert runtime.mission_log()[-1]["reason"] == "a reason no call site uses"
