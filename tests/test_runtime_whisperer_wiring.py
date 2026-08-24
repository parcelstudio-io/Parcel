"""Card R11: the whisperer wired into the real runtime.

WHAT THIS FILE PINS THAT THE UNIT TESTS CANNOT
----------------------------------------------
``tests/test_realtime_whisperer.py`` proves the POLICY against a frozen clock
with no robot attached. This file proves the four things that only exist once
the policy is bolted to the runtime:

1. **Telemetry never reaches the lane.** Three simulated minutes of a robot
   moving, following, flapping its navigation state and draining its battery
   produce ZERO sentences. This is the live claim the card asks for, run
   offline and deterministically so a regression is caught by the suite rather
   than by a session.
2. **``follow_owner(pace)`` has a consumer.** R10 recorded the pace and left an
   open risk saying so; this is that consumer — and it consumes it by NOTICING,
   never by applying it.
3. **No follow safety cap is a function of the pace the owner asked for.** The
   card protects those caps explicitly and the seed harness attacks this test.
4. **The knob is visible.** ``/api/state`` shows what it suppressed.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV, WhispererConfig
from parcel_robot.realtime.whisperer import (
    KIND_BATTERY_STATE,
    KIND_MISSION_ARRIVED,
    KIND_MISSION_ENDED,
    KIND_PACE_MISMATCH,
    KIND_PACE_UNKNOWN,
    NEVER_BAND,
    PACE_MISMATCH_WINDOW_S,
    PACE_SKIP_NOT_FOLLOWING,
    PACE_SKIP_REASONS,
    PACE_SKIP_UNKNOWN_HOLDING,
    RULE_DISABLED,
    RULE_PACE_KNOWN_RESUMED,
    RULE_PACE_UNKNOWN,
    StateEvent,
    Whisperer,
)
from parcel_robot.runtime import WHISPERER_TICK_INTERVAL_S, RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r11-whisperer"


class _Backend:
    name = BACKEND_NAME

    def __init__(self) -> None:
        self.x = 0.0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(x=self.x),
            # A VISIBLE owner: ``follow_owner`` is refused outright without one
            # ("I can't see you clearly enough"), and the pace watcher's whole
            # subject is a follow that is actually running.
            owner=OwnerTrack(x=2.0, y=0.0, visible=True, confidence=0.95),
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
        del tools, context, transcript
        return AgentDecision("Understood.")


class _FakeLane:
    """The three lane members the narration gate reads, plus a call log."""

    def __init__(self) -> None:
        self.active = True
        self.recovering = False
        self.playback_owned = False
        self.narrated: list[str] = []
        self.narrated_critical: list[bool] = []

    def narrate_event(self, text: str, *, critical: bool = False) -> bool:
        # Card R25 widened the lane's narration door with a cost-ceiling
        # exemption flag; a double that does not accept it makes every
        # narration raise TypeError into `_narrate_mission`'s catch, which
        # reads as "the robot had nothing to say".
        self.narrated.append(text)
        self.narrated_critical.append(bool(critical))
        return True

    def snapshot(self) -> dict[str, object]:
        return {"active": self.active, "narrations": len(self.narrated)}

    usage_rows: tuple = ()

    def close(self) -> None:
        return None


class _Clock:
    def __init__(self, start: float = 5_000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    path = tmp_path / "r11.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
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
    session = RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r11 whisperer fixture",
        ),
    )
    session._observation = session.backend.observe()
    try:
        yield session
    finally:
        session.close()


def _wire(runtime: RobotRuntime, **config) -> tuple[_FakeLane, _Clock]:
    lane = _FakeLane()
    runtime.realtime_lane = lane  # type: ignore[assignment]
    clock = _Clock()
    runtime.realtime_whisperer = Whisperer(config=WhispererConfig(**config), clock=clock)
    return lane, clock


def _tick(runtime: RobotRuntime, clock: _Clock, seconds: float = 1.0) -> None:
    clock.advance(seconds)
    runtime._observation = runtime.backend.observe()
    runtime._step_whisperer(runtime._observation, now=clock.now)


# ================================================ the never band, on the stack
def test_three_minutes_of_telemetry_says_nothing_at_all(runtime: RobotRuntime) -> None:
    """The card's live claim, offline and deterministic.

    A robot that is moving, following, flapping its navigation state and
    draining its battery for three minutes is a robot with nothing to say. The
    bench's D arm forwarded 25 noise items per ten minutes and scored 3.0/10 on
    calm downstream; realtime-mini babbled about injected nav state in 4/4
    forced responses. Zero is the only acceptable number here.
    """

    lane, clock = _wire(runtime, max_updates_per_minute=60, min_gap_s=0.0)
    runtime._navigation_detail = {
        "enabled": True,
        "state": "planned",
        "directive": "navigate to the sidewalk",
        "goal": "the sidewalk",
        "reason": "grid_track err=9.6 goal=0.8 route=2 status=planned",
    }

    for index in range(180):
        # Everything the real stack moves every tick: the pose, the navigator's
        # status word, the proximity band and the battery percentage.
        runtime.backend.x += 0.25
        runtime._navigation_detail = {
            **runtime._navigation_detail,
            "state": "planned" if index % 2 else "person_stop",
        }
        runtime._proximity_state = "slowing" if index % 3 else "clear"
        _tick(runtime, clock)

    assert lane.narrated == [], f"telemetry reached the model: {lane.narrated[:3]}"
    rows = runtime.realtime_whisperer.decision_rows()
    assert rows, "the whisperer never saw the telemetry at all"
    assert {str(row["kind"]) for row in rows} <= NEVER_BAND
    assert runtime.realtime_whisperer.forwarded == 0
    assert runtime.realtime_snapshot()["whisperer"]["updates_this_minute"] == 0


def test_the_digest_tick_is_throttled_off_the_motion_cadence(runtime: RobotRuntime) -> None:
    _wire(runtime)
    clock = _Clock()
    runtime._step_whisperer(runtime._observation, now=clock.now)
    before = len(runtime.realtime_whisperer.decision_rows())

    for _ in range(9):
        clock.advance(WHISPERER_TICK_INTERVAL_S / 10.0)
        runtime.backend.x += 1.0
        runtime._observation = runtime.backend.observe()
        runtime._step_whisperer(runtime._observation, now=clock.now)

    assert len(runtime.realtime_whisperer.decision_rows()) == before, (
        "the whisperer ran at the control-loop cadence"
    )


# ======================================================= mission terminals
def test_a_mission_terminal_goes_out_through_the_whisperer(runtime: RobotRuntime) -> None:
    lane, _ = _wire(runtime)
    runtime._navigation_detail = {
        "enabled": True,
        "state": "navigating",
        "directive": "navigate to the sidewalk",
        "goal": "the sidewalk",
        "reason": "grid_track status=planned",
    }
    runtime._navigation_directive = "navigate to the sidewalk"

    runtime._stop_navigation_channel(reason="blocked_by_person", state="failed")

    assert len(lane.narrated) == 1
    assert "the sidewalk" in lane.narrated[0]
    log = runtime.realtime_whisperer.decision_rows()
    assert log[-1]["kind"] == KIND_MISSION_ENDED
    assert log[-1]["forwarded"] is True


def test_an_arrival_is_not_asked_to_ask_twice(runtime: RobotRuntime) -> None:
    """R10's arrival table composes the ask; the whisperer must not add a second."""

    lane, _ = _wire(runtime)

    runtime._narrate_mission_terminal(state="arrived", goal="the door", reason="arrived")

    assert len(lane.narrated) == 1
    assert lane.narrated[0].lower().count("ask the owner") == 1
    assert runtime.realtime_whisperer.decision_rows()[-1]["kind"] == KIND_MISSION_ARRIVED


def test_the_owners_off_switch_stops_state_updates(runtime: RobotRuntime) -> None:
    """``enabled: false`` means no state updates at all — and no exceptions."""

    lane, _ = _wire(runtime, enabled=False)

    runtime._narrate_mission_terminal(state="arrived", goal="the door", reason="arrived")

    assert lane.narrated == []
    assert runtime.realtime_whisperer.decision_rows()[-1]["rule"] == RULE_DISABLED


def test_the_off_switch_does_not_touch_the_owners_own_voice_traffic(
    runtime: RobotRuntime,
) -> None:
    """The card is explicit: voice-command traffic is excluded from the knob.

    The whisperer sits on ``_whisper``/``_step_whisperer`` only. The owner's own
    door — ``submit_realtime_transcript`` — does not consult it, so turning
    state updates off cannot make the robot stop answering.
    """

    _wire(runtime, enabled=False)
    outcome = runtime.submit_realtime_transcript("wait here", item_id=None, session_id="s1")

    assert outcome.executed is True
    assert runtime.realtime_whisperer.forwarded == 0


# ================================================= pace_intent, and its limits
def test_the_pace_the_owner_asked_for_is_recorded(runtime: RobotRuntime) -> None:
    _wire(runtime)
    runtime._observation = runtime.backend.observe()

    runtime._realtime_follow("run")

    assert runtime._realtime_pace_intent == "run"
    assert runtime._realtime_last_pace == "run"
    assert runtime.realtime_snapshot()["pace_intent"] == "run"


def test_no_follow_safety_cap_is_a_function_of_the_pace_intent(
    runtime: RobotRuntime,
) -> None:
    """The card protects these explicitly. This is the pin the seed attacks.

    "Run with me" must not become "run". R10 left ``pace_applied: false`` and an
    open risk saying the pace was carried but not applied; R11 is the consumer
    and it consumes it by NOTICING the mismatch and asking about it. Every
    number the follow controller brakes and stands off with is byte-identical
    before and after a pace declaration AND after the watcher has fired.
    """

    lane, clock = _wire(runtime, max_updates_per_minute=10, min_gap_s=0.0)
    caps = {
        "max_vx": runtime.follow.config.max_vx,
        "max_vyaw": runtime.follow.config.max_vyaw,
        "desired_distance_m": runtime.follow.config.desired_distance_m,
        "owner_keepout_m": runtime.follow.config.owner_keepout_m,
        "person_stop_m": runtime.follow.config.person_stop_m,
        "person_slow_m": runtime.follow.config.person_slow_m,
        "obstacle_stop_m": runtime.follow.config.obstacle_stop_m,
        "obstacle_slow_m": runtime.follow.config.obstacle_slow_m,
    }
    runtime._observation = runtime.backend.observe()
    runtime._realtime_follow("run")
    # The tool call admits the plan; the behaviour channel then reaches this
    # runtime door, which is what actually starts the controller. With no
    # control loop running in a unit test, call it directly.
    runtime._enable_owner_follow("direct")

    runtime.follow.snapshot = lambda: {  # type: ignore[method-assign]
        "distance_m": 1.9,
        "owner_speed_mps": 0.9,
    }
    for _ in range(int(PACE_MISMATCH_WINDOW_S) + 4):
        _tick(runtime, clock)

    assert lane.narrated, "the watcher never fired, so this proves nothing"
    after = {name: getattr(runtime.follow.config, name) for name in caps}
    assert after == caps, "a follow safety cap moved because the owner said 'run'"


def test_run_with_a_walking_owner_asks_about_walking(runtime: RobotRuntime) -> None:
    """The end the card names: the model is TOLD to ask, and told the true gait."""

    lane, clock = _wire(runtime, max_updates_per_minute=10, min_gap_s=0.0)
    runtime._observation = runtime.backend.observe()
    runtime._realtime_follow("run")
    runtime._enable_owner_follow("direct")
    runtime.follow.snapshot = lambda: {  # type: ignore[method-assign]
        "distance_m": 1.9,
        "owner_speed_mps": 1.0,
    }

    for _ in range(int(PACE_MISMATCH_WINDOW_S) + 4):
        _tick(runtime, clock)

    assert len(lane.narrated) == 1
    text = lane.narrated[0]
    assert "ask the owner whether they would rather just walk" in text.lower()
    assert "has NOT changed speed" in text
    assert f"{runtime.follow.config.max_vx:.2f} m/s" in text
    assert runtime.realtime_whisperer.decision_rows()[-1]["kind"] == KIND_PACE_MISMATCH


def test_a_follow_that_ends_takes_its_pace_declaration_with_it(
    runtime: RobotRuntime,
) -> None:
    """Otherwise a later plain "follow me" inherits a run nobody asked for."""

    lane, clock = _wire(runtime, max_updates_per_minute=10, min_gap_s=0.0)
    runtime._observation = runtime.backend.observe()
    runtime._realtime_follow("run")
    runtime._enable_owner_follow("direct")
    assert runtime._realtime_pace_intent == "run"
    _tick(runtime, clock)

    runtime.follow.stop()
    _tick(runtime, clock)

    assert runtime._realtime_pace_intent == ""
    runtime.follow.snapshot = lambda: {  # type: ignore[method-assign]
        "distance_m": 1.9,
        "owner_speed_mps": 0.9,
    }
    for _ in range(int(PACE_MISMATCH_WINDOW_S) + 4):
        _tick(runtime, clock)
    assert lane.narrated == []


# ========== card R13: the estimator that goes blind, against the REAL estimator
class _OwnerTrackFeed:
    """Lays real owner-track evidence into the REAL heading estimator.

    TWO CLOCKS, AND WHY THAT IS THE HONEST ARRANGEMENT
    --------------------------------------------------
    The whisperer's clock is injected, as everywhere else in this file, so six
    seconds of sustained walk cost the suite nothing. The follow controller's
    estimator is NOT injectable: ``FollowOwnerController.snapshot`` reads
    ``time.monotonic()`` itself, and the digest calls that snapshot with no
    clock seam in between. So this feed writes the owner track on a timeline
    anchored to the REAL monotonic clock, ending a few tens of milliseconds in
    the past — which is how a dropout becomes provable without the test
    sleeping through it, and how "the estimator decided for itself that it had
    no speed" stays a fact about the shipping estimator rather than a stub
    returning ``None`` because a test told it to.

    E1's defect lived in exactly this seam. R11's pace tests all replace
    ``follow.snapshot`` with a two-key dict, which is why 36 seeds and a live
    proof went past it.
    """

    #: The estimator's own cadence. ``heading_history_gap_s`` is 0.9 s, so a
    #: feed at the whisperer's 1 Hz would reset the history on every sample.
    STEP_S = 0.1

    def __init__(self, runtime: RobotRuntime, *, owner_x: float = 2.0) -> None:
        self._runtime = runtime
        self.owner_x = float(owner_x)

    def lay(self, *, samples: int, step_m: float, ends_s_ago: float = 0.05) -> None:
        first = time.monotonic() - ends_s_ago - self.STEP_S * (samples - 1)
        for index in range(samples):
            at = first + index * self.STEP_S
            self.owner_x += step_m
            self._runtime.follow.observe_owner(
                SimObservation(
                    timestamp=at,
                    robot=RobotPose(x=0.0),
                    owner=OwnerTrack(
                        x=self.owner_x, y=0.0, visible=True, confidence=0.95
                    ),
                    nearest_obstacle_m=10.0,
                    backend=BACKEND_NAME,
                ),
                now=at,
            )


def _run_with_me(runtime: RobotRuntime) -> None:
    """The owner's own words, through the shipping doors: follow, pace ``run``."""

    runtime._observation = runtime.backend.observe()
    runtime._realtime_follow("run")
    runtime._enable_owner_follow("direct")


def _pace_unknown_rows(runtime: RobotRuntime) -> list[dict[str, object]]:
    return [
        row
        for row in runtime.realtime_whisperer.decision_rows()
        if row["kind"] == KIND_PACE_UNKNOWN
    ]


def test_an_owner_the_estimator_cannot_measure_is_a_row_and_not_a_silence(
    runtime: RobotRuntime,
) -> None:
    """Owner session 1's shape, reproduced with nothing faked below the seam.

    The owner stood at a desk and talked, the mocap owner never moved, and the
    follow controller's estimator had no speed to publish for the whole follow
    — ``heading_track_status: insufficient_motion``, ``owner_speed_mps: null``
    in the capture, with the robot reporting ``holding: at_follow_distance``
    every few seconds because there was nothing to keep up with. Under R11 the
    pace watcher wrote NOTHING for any of it. It now writes one row carrying the
    estimator's own word, and counts every tick it stays blind.
    """

    lane, clock = _wire(runtime, max_updates_per_minute=10, min_gap_s=0.0)
    _run_with_me(runtime)
    _OwnerTrackFeed(runtime).lay(samples=12, step_m=0.0)

    follow_snapshot = runtime.follow.snapshot()
    assert follow_snapshot["owner_speed_mps"] is None
    assert follow_snapshot["heading_track_status"] == "insufficient_motion"

    for _ in range(12):
        _tick(runtime, clock)

    rows = _pace_unknown_rows(runtime)
    assert len(rows) == 1, "one row per hole, not one per tick — the ring is finite"
    assert rows[0]["rule"] == RULE_PACE_UNKNOWN
    assert rows[0]["key"] == "pace_unknown:insufficient_motion"
    assert rows[0]["forwarded"] is False
    assert lane.narrated == [], "an unmeasurable owner is never a reason to speak"

    watch = runtime.realtime_snapshot()["whisperer"]["pace_watch"]
    assert watch["pace_unknown"] is True
    assert watch["pace_unknown_episodes"] == 1
    assert watch["skips"][PACE_SKIP_UNKNOWN_HOLDING] == 10
    assert watch["accounted"] is True


def test_the_estimator_going_blind_mid_walk_does_not_restart_the_window(
    runtime: RobotRuntime,
) -> None:
    """The card's pause, proved against the estimator that actually drops out.

    Four seconds of a measurably walking owner, then a dropout — this estimator
    publishes no speed at all when its evidence goes stale, which is what E1
    measured for ten continuous seconds across a run→walk transition — then the
    walk resumes. The ask is owed after the REMAINING measured seconds, not
    after a fresh window. Under R11 the dropout reset the window and the second
    leg had to earn the whole six all over again.

    The one real sleep in this file buys the only thing that cannot be faked
    without stubbing the estimator: ``heading_stale_after_s`` (0.8 s) elapsing
    on the estimator's own clock.
    """

    lane, clock = _wire(runtime, max_updates_per_minute=10, min_gap_s=0.0)
    _run_with_me(runtime)
    feed = _OwnerTrackFeed(runtime)

    feed.lay(samples=4, step_m=0.09)  # ~0.9 m/s: a measurable walk
    for _ in range(5):
        _tick(runtime, clock)
    assert runtime.follow.snapshot()["owner_speed_mps"] is not None
    assert lane.narrated == [], "four seconds is not a sustained walk"

    time.sleep(0.85)
    for _ in range(5):
        _tick(runtime, clock)
    assert runtime.follow.snapshot()["owner_speed_mps"] is None
    assert lane.narrated == [], "blind seconds are not measured seconds"

    resumed_at = clock.now
    feed.lay(samples=4, step_m=0.09)
    for _ in range(3):
        _tick(runtime, clock)

    assert len(lane.narrated) == 1
    assert "rather just walk" in lane.narrated[0].lower()
    assert clock.now - resumed_at < PACE_MISMATCH_WINDOW_S, (
        "the banked seconds were thrown away and the walk started over"
    )
    assert [row["rule"] for row in _pace_unknown_rows(runtime)] == [
        RULE_PACE_UNKNOWN,
        RULE_PACE_KNOWN_RESUMED,
    ]
    watch = runtime.realtime_snapshot()["whisperer"]["pace_watch"]
    assert watch["pace_unknown_episodes"] == 1
    assert watch["pace_unknown_seconds"] > 0.0


# ====================================================== the knob, from outside
def test_the_pace_watchers_ledger_reaches_the_state_endpoint(
    runtime: RobotRuntime,
) -> None:
    """The owner-session capture could not answer "was the watcher blind?".

    It had the aggregate counters, one ``last`` row and nothing else, so the
    question this card exists to answer had to be inferred from the follow
    snapshot instead of read off the whisperer. It is published now, and the
    accounting identity is published with it.
    """

    lane, clock = _wire(runtime, max_updates_per_minute=10, min_gap_s=0.0)
    for _ in range(3):
        _tick(runtime, clock)

    watch = runtime.realtime_snapshot()["whisperer"]["pace_watch"]
    assert watch["ticks"] == 3
    assert watch["logged"] + sum(watch["skips"].values()) == watch["ticks"]
    assert watch["accounted"] is True
    assert set(watch["skips"]) <= set(PACE_SKIP_REASONS)
    assert watch["skips"][PACE_SKIP_NOT_FOLLOWING] == 2
    assert lane.narrated == []


def test_the_snapshot_shows_the_knob_and_what_it_suppressed(runtime: RobotRuntime) -> None:
    lane, clock = _wire(runtime, max_updates_per_minute=1, min_gap_s=0.0)

    runtime._narrate_mission_terminal(state="arrived", goal="the door", reason="arrived")
    for index in range(3):
        clock.advance(1.0)
        runtime._whisper_refusal(f"refusal {index}", subject=f"s{index}")
    clock.advance(1.0)
    runtime._whisper(StateEvent(kind=KIND_BATTERY_STATE, key="b", fact="Battery is low."))

    published = runtime.realtime_snapshot()["whisperer"]
    assert published["max_updates_per_minute"] == 1
    assert published["min_gap_s"] == 0.0
    assert published["enabled"] is True
    assert published["updates_this_minute"] >= 1
    assert published["forwarded"] == len(lane.narrated)
    assert published["last"]["rule"]
    assert isinstance(published["suppressed_by_rule"], dict)


def test_a_narration_the_lane_refuses_does_not_spend_the_budget(
    runtime: RobotRuntime,
) -> None:
    """The floor gate and the cost knob are different things and must stay so."""

    lane, _ = _wire(runtime, max_updates_per_minute=1, min_gap_s=0.0)
    lane.playback_owned = True  # the model already has the mouth

    runtime._narrate_mission_terminal(state="arrived", goal="the door", reason="arrived")

    assert lane.narrated == []
    assert runtime.realtime_snapshot()["whisperer"]["updates_this_minute"] == 0
    assert runtime.realtime_whisperer.forwarded == 0
