"""The blocked-by-a-person yield policy, at the runtime seam (card P-1/P-2).

**What this pins.** On 2026-08-07 the traffic case was measured standing
*inside* the scored sidewalk polygon (K0 distance 0.000 m) holding
``grid_track err=0.0 goal=0.2 route=2 status=planned|person_stop`` for ~200
ticks, because pedestrians occupied the last 0.2 m of the approach. Two
correct behaviours kept it there — person-stop ticks deliberately do not count
as no-progress, and ``inside`` arrival requires a terminal clearance the robot
did not have — so the mission burned the 240 s ``NavigateTo`` budget and failed
as ``step_timeout``, a reason that names nothing.

Instrumenting the *gate* rather than the pose (2026-08-08) refined that: it is
a **stream**, not one parked person. ``person_stop`` closes and re-opens with
roughly one-second gaps for the whole run, which is why the tracker separates
episode scope from mission scope — see the chattering-gate cases below.

The residual was never geometry. It was a product decision: *how long may a
mission spend yielding, and what does the dog do about it?* The owner's answer
(2026-08-08): "When the robot determines there is a person in scene, that
should be a personality decision. By default let the robot ask for help but
make sure that this personality is configurable."

**The invariant every case below is written around.** The policy decides how
long to wait and what to say, and NOTHING else. It never sees, proposes, or
relaxes a velocity; a gate-blocked tick still commands ``vx == 0.0`` under
every policy value, and ``obstacle_stop`` — a different failure with different
machinery — can never route here.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.core.yield_policy import (
    BLOCKED_BY_PERSON_REASON,
    BLOCKED_BY_PERSON_UNANSWERED_REASON,
    DEFAULT_YIELD_POLICY,
    FORBIDDEN_ARRIVAL_PHRASES,
    OBSTACLE_BLOCK_NOTE,
    PERSON_BLOCK_NOTE,
    PersonalityPolicyConfig,
    YieldPolicy,
    YieldSpeech,
    YieldTracker,
    load_personality_policy_config,
    person_blocked_from_note,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.models import MidLevelCommand
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice.yield_speech import yield_dialogue_act

REPO = Path(__file__).resolve().parents[1]

#: The exact string the 2026-08-07 instrumented run recorded on the ticks that
#: burned the clock. Every runtime case below drives this note, verbatim.
TRAFFIC_NOTE = "grid_track err=0.0 goal=0.2 route=2 status=planned|person_stop"
#: Its obstacle sibling, from the lamppost bollard park in the same record.
OBSTACLE_NOTE = "grid_track err=0.0 goal=5.3 route=2 status=planned|obstacle_stop"


# ---------------------------------------------------------------------------
# The signal: person_stop and nothing else
# ---------------------------------------------------------------------------


def test_the_measured_traffic_note_is_recognized_as_a_person_block() -> None:
    assert person_blocked_from_note(TRAFFIC_NOTE) is True


@pytest.mark.parametrize(
    "note",
    [
        "",
        "clear",
        "grid_track err=0.0 goal=0.2 route=2 status=planned",
        "grid_track err=0.0 goal=0.2 route=2 status=planned|person_slow",
        OBSTACLE_NOTE,
        "grid_track ...|obstacle_slow",
        "grid_track ...|obstacle_projected_speed_cap",
        "pose_lost_hold",
        "navigation_no_progress",
        "semantic_target_unreachable",
    ],
)
def test_no_other_note_in_the_vocabulary_fires_the_yield_policy(note: str) -> None:
    """Requirement (d): the obstacle case is somebody else's machinery.

    ``_gate_blocked_route_recovery`` releases a commitment after 60 consecutive
    ``obstacle_stop`` ticks and deliberately excludes ``person_stop``. This
    policy is the mirror image and must be equally exclusive, or the two would
    fight over the same tick.
    """

    assert person_blocked_from_note(note) is False


def test_matching_is_on_exact_segments_not_substrings() -> None:
    assert person_blocked_from_note(f"a|{PERSON_BLOCK_NOTE}|b") is True
    assert person_blocked_from_note("no_person_stop") is False
    assert person_blocked_from_note(f"a|{OBSTACLE_BLOCK_NOTE}") is False


# ---------------------------------------------------------------------------
# The policy object: typed, validated, fail-closed
# ---------------------------------------------------------------------------


def test_the_shipped_default_is_ask_for_help() -> None:
    """The owner's explicit instruction, pinned so it cannot drift silently."""

    assert DEFAULT_YIELD_POLICY.on_blocked == "ask_for_help"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"patience_s": -1.0}, "patience_s"),
        ({"patience_s": float("inf")}, "patience_s"),
        ({"reask_interval_s": 0.0}, "reask_interval_s"),
        ({"release_grace_s": -0.5}, "release_grace_s"),
        ({"max_asks": -1}, "max_asks"),
        ({"on_blocked": "shove_past"}, "on_blocked"),
    ],
)
def test_policy_values_are_validated(raw: dict, message: str) -> None:
    with pytest.raises((ValueError, TypeError), match=message):
        YieldPolicy.from_mapping(raw)


def test_policy_rejects_unknown_keys_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown keys in yield_policy"):
        YieldPolicy.from_mapping({"patience_s": 3.0, "patence_s": 4.0})


def test_policy_rejects_wrong_types_rather_than_coercing() -> None:
    with pytest.raises(TypeError):
        YieldPolicy.from_mapping({"max_asks": 2.5})
    with pytest.raises(TypeError):
        YieldPolicy.from_mapping({"patience_s": "8"})


# ---------------------------------------------------------------------------
# The tracker: patience, edge-triggering, rate limiting, the three variants
# ---------------------------------------------------------------------------


def _tracker(**overrides) -> YieldTracker:
    return YieldTracker(YieldPolicy.from_mapping(overrides))


def test_patience_expiry_fires_exactly_one_ask() -> None:
    tracker = _tracker(patience_s=5.0, reask_interval_s=100.0, max_asks=3)
    actions = [
        tracker.observe(person_blocked=True, now_s=t).action
        for t in (0.0, 1.0, 4.9, 5.0, 5.1, 6.0, 10.0)
    ]
    assert actions == ["hold", "hold", "hold", "ask", "hold", "hold", "hold"]
    assert actions.count("ask") == 1


def test_the_ask_is_edge_triggered_not_repeated_at_control_rate() -> None:
    """10 Hz for 30 s is 300 blocked ticks; two asks, not three hundred."""

    tracker = _tracker(patience_s=2.0, reask_interval_s=10.0, max_asks=2)
    asks = 0
    for step in range(300):
        if tracker.observe(person_blocked=True, now_s=step * 0.1).action == "ask":
            asks += 1
    assert asks == 2


def test_reask_honours_the_interval() -> None:
    """Patience runs from the FIRST blocked tick, so the run starts at t=0."""

    tracker = _tracker(patience_s=1.0, reask_interval_s=10.0, max_asks=3)
    assert tracker.observe(person_blocked=True, now_s=0.0).action == "hold"
    assert tracker.observe(person_blocked=True, now_s=1.0).action == "ask"
    assert tracker.observe(person_blocked=True, now_s=10.9).action == "hold"
    second = tracker.observe(person_blocked=True, now_s=11.0)
    assert second.action == "ask"
    assert second.ask_index == 2


def test_max_asks_is_the_ceiling_and_then_it_fails_honestly() -> None:
    tracker = _tracker(patience_s=1.0, reask_interval_s=5.0, max_asks=2)
    assert tracker.observe(person_blocked=True, now_s=0.0).action == "hold"
    assert tracker.observe(person_blocked=True, now_s=1.0).ask_index == 1
    assert tracker.observe(person_blocked=True, now_s=6.0).ask_index == 2
    # The person gets one full interval to answer the LAST ask before the dog
    # gives up: an ask followed instantly by abandonment is not really an ask.
    assert tracker.observe(person_blocked=True, now_s=10.9).action == "hold"
    final = tracker.observe(person_blocked=True, now_s=11.0)
    assert final.action == "give_up"
    assert final.reason == BLOCKED_BY_PERSON_UNANSWERED_REASON


def test_give_up_is_reported_once_and_never_repeats() -> None:
    tracker = _tracker(patience_s=1.0, on_blocked="give_up_honestly")
    assert tracker.observe(person_blocked=True, now_s=0.0).action == "hold"
    assert tracker.observe(person_blocked=True, now_s=2.0).action == "give_up"
    for step in range(20):
        assert tracker.observe(person_blocked=True, now_s=3.0 + step).action == "hold"


def test_wait_reproduces_todays_behaviour_forever() -> None:
    """``wait`` is the 2026-08-07 measurement: hold until the outer budget."""

    tracker = _tracker(patience_s=1.0, on_blocked="wait")
    actions = {
        tracker.observe(person_blocked=True, now_s=step * 0.1).action
        for step in range(3000)  # 300 s > the 240 s NavigateTo ceiling
    }
    assert actions == {"hold"}


def test_give_up_honestly_fails_fast_with_the_honest_reason() -> None:
    tracker = _tracker(patience_s=4.0, on_blocked="give_up_honestly")
    assert tracker.observe(person_blocked=True, now_s=0.0).action == "hold"
    assert tracker.observe(person_blocked=True, now_s=3.9).action == "hold"
    decision = tracker.observe(person_blocked=True, now_s=4.0)
    assert decision.action == "give_up"
    assert decision.reason == BLOCKED_BY_PERSON_REASON
    assert decision.ask_index == 0


def test_zero_max_asks_degenerates_to_giving_up_at_patience() -> None:
    tracker = _tracker(patience_s=3.0, max_asks=0)
    assert tracker.observe(person_blocked=True, now_s=0.0).action == "hold"
    assert tracker.observe(person_blocked=True, now_s=2.9).action == "hold"
    decision = tracker.observe(person_blocked=True, now_s=3.0)
    assert decision.action == "give_up"
    assert decision.reason == BLOCKED_BY_PERSON_UNANSWERED_REASON


def test_patience_restarts_when_an_episode_really_ends() -> None:
    """Somebody walking past must never spend the mission's patience."""

    tracker = _tracker(patience_s=5.0, release_grace_s=1.0)
    for step in range(40):  # 4 s blocked
        assert tracker.observe(person_blocked=True, now_s=step * 0.1).action == "hold"
    for step in range(20):  # 2 s clear — outlasts the grace window
        tracker.observe(person_blocked=False, now_s=4.0 + step * 0.1)
    assert tracker.observe(person_blocked=False, now_s=6.0).action == "clear"
    for step in range(40):  # 4 s blocked again — still under patience
        assert tracker.observe(person_blocked=True, now_s=6.0 + step * 0.1).action == "hold"


# ---------------------------------------------------------------------------
# The chattering gate — the defect the first live traffic run exposed
# ---------------------------------------------------------------------------


def _chattering(tracker: YieldTracker, *, seconds: float, blocked_s=10.0, clear_s=1.0) -> dict:
    """Drive a gate that closes for ``blocked_s`` and opens for ``clear_s``.

    Shape taken from the 2026-08-08 instrumented traffic run, where a
    pedestrian *stream* — not one parked person — made ``person_stop`` come and
    go with roughly one-second gaps for the whole 240 s.
    """

    period = blocked_s + clear_s
    asks: list[float] = []
    give_ups: list[float] = []
    for step in range(int(seconds * 10)):
        now = step * 0.1
        decision = tracker.observe(person_blocked=(now % period) < blocked_s, now_s=now)
        if decision.action == "ask":
            asks.append(now)
        elif decision.action == "give_up":
            give_ups.append(now)
    return {
        "asks": asks,
        "give_ups": give_ups,
        "episodes": tracker.snapshot()["episodes"],
    }


def test_a_chattering_gate_still_produces_exactly_max_asks_and_one_give_up() -> None:
    """The measured defect: 13 asks in 240 s and no give-up, ever.

    Root cause: both the patience clock *and* the ask budget were per-episode,
    and the person gate chatters in a pedestrian stream — so every brief
    release refunded the budget and ``max_asks`` was unreachable. The budget is
    now per mission and the episode survives short releases.
    """

    tracker = _tracker(patience_s=8.0, reask_interval_s=12.0, max_asks=2, release_grace_s=3.0)
    run = _chattering(tracker, seconds=120.0)
    assert len(run["asks"]) == 2, run
    assert len(run["give_ups"]) == 1, run
    assert run["asks"][0] < 10.0, run
    assert run["give_ups"][0] < 40.0, run
    assert run["episodes"] == 1, run


def test_release_grace_is_what_makes_patience_mean_something_in_traffic() -> None:
    """Negative control for ``release_grace_s`` on the measured gate shape.

    Both settings now terminate — that half is the per-mission ask budget's
    doing. What the grace window buys is *promptness*: under the strict rule
    the first ask arrives late and the honest end arrives later still, because
    the patience clock keeps being reset by the gate's chatter rather than by
    the situation changing.
    """

    common = {"patience_s": 8.0, "reask_interval_s": 12.0, "max_asks": 2}

    # Shape A — each blockage outlasts patience on its own (10 s on, 1 s off).
    # Both act; the strict rule reaches the honest end 8 s later because the
    # give-up needs a blocked tick and its patience clock keeps restarting.
    graceful = _chattering(_tracker(**common, release_grace_s=3.0), seconds=240.0)
    strict = _chattering(_tracker(**common, release_grace_s=0.0), seconds=240.0)
    assert graceful["episodes"] == 1
    assert strict["episodes"] > 5, strict
    assert graceful["give_ups"][0] < strict["give_ups"][0], (graceful, strict)

    # Shape B — no single blockage outlasts patience (5 s on, 1 s off), which
    # is the shape that makes the strict rule completely INERT: the dog is
    # stuck for four minutes and never says a word.
    inert = _chattering(
        _tracker(**common, release_grace_s=0.0), seconds=240.0, blocked_s=5.0, clear_s=1.0
    )
    assert inert["asks"] == [] and inert["give_ups"] == [], inert
    acting = _chattering(
        _tracker(**common, release_grace_s=3.0), seconds=240.0, blocked_s=5.0, clear_s=1.0
    )
    assert len(acting["asks"]) == 2 and len(acting["give_ups"]) == 1, acting


def test_the_ask_budget_is_per_mission_and_is_never_refunded() -> None:
    """The second half: a flicker that DOES end the episode still costs an ask."""

    tracker = _tracker(patience_s=2.0, reask_interval_s=4.0, max_asks=1, release_grace_s=1.0)
    # Episode 1 — one ask.
    for step in range(60):
        tracker.observe(person_blocked=True, now_s=step * 0.1)
    assert tracker.snapshot()["asks"] == 1
    # A long clear: the episode ends, patience restarts, the budget does not.
    for step in range(50):
        tracker.observe(person_blocked=False, now_s=6.0 + step * 0.1)
    # Episode 2 — no ask left, so the honest end instead.
    decisions = [
        tracker.observe(person_blocked=True, now_s=11.0 + step * 0.1) for step in range(60)
    ]
    assert [item.action for item in decisions].count("ask") == 0
    give_ups = [item for item in decisions if item.action == "give_up"]
    assert len(give_ups) == 1
    assert give_ups[0].reason == BLOCKED_BY_PERSON_UNANSWERED_REASON
    assert tracker.snapshot()["episodes"] == 2


def test_nothing_is_said_while_the_gate_is_open_inside_the_grace_window() -> None:
    """You do not ask someone to move out of a gap you are driving through."""

    tracker = _tracker(patience_s=2.0, release_grace_s=5.0)
    for step in range(30):
        tracker.observe(person_blocked=True, now_s=step * 0.1)
    for step in range(40):  # 4 s clear, inside the 5 s grace window
        decision = tracker.observe(person_blocked=False, now_s=3.0 + step * 0.1)
        assert decision.action == "hold"
        assert decision.blocked_s > 0.0


# ---------------------------------------------------------------------------
# The words: truthfulness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", FORBIDDEN_ARRIVAL_PHRASES)
def test_an_arrival_claim_cannot_be_authored_into_a_yield_line(phrase: str) -> None:
    with pytest.raises(ValueError, match="claims arrival or completion"):
        YieldSpeech.from_mapping({"ask": f"Hello, {phrase} at the sidewalk."})


def test_a_goal_label_cannot_smuggle_an_arrival_claim_through_substitution() -> None:
    """The label is scene data, so the check is re-run after formatting."""

    speech = YieldSpeech.from_mapping({"ask": "Please help me get to {place}."})
    with pytest.raises(ValueError, match="claims arrival or completion"):
        speech.render("ask", place="the place I already arrived at")


def test_unsupported_placeholders_fail_at_load_not_mid_mission() -> None:
    with pytest.raises(ValueError, match="unsupported placeholders"):
        YieldSpeech.from_mapping({"ask": "Help me reach {place} by {deadline}."})


@pytest.mark.parametrize("kind", ["ask", "reask", "give_up"])
def test_every_shipped_utterance_builds_a_valid_dialogue_act(kind: str) -> None:
    config = load_personality_policy_config(REPO / "configs" / "personality.yaml")
    for personality_id in sorted(config.profiles):
        profile = config.for_personality(personality_id)
        text = profile.speech.render(kind, place="the sidewalk")
        act = yield_dialogue_act(turn_id=f"yield-{personality_id}-1", text=text, kind=kind)
        assert act.text == text
        # Every claim is backed. The contract forbids a verified claim without
        # evidence; what this adds is that the evidence NAMES the person gate,
        # which is the only thing the tick actually proved.
        assert act.claims, "a yield act with no claim asserts nothing it can back"
        for claim in act.claims:
            assert claim.veracity == "verified"
            assert claim.evidence_ref == "navigation:person_stop"
        assert act.asks_clarification is (kind != "give_up")


def test_a_yield_act_never_claims_arrival_and_never_claims_the_unverified() -> None:
    config = load_personality_policy_config(REPO / "configs" / "personality.yaml")
    for personality_id in sorted(config.profiles):
        profile = config.for_personality(personality_id)
        for kind in ("ask", "reask", "give_up"):
            act = yield_dialogue_act(
                turn_id="yield-truth-1",
                text=profile.speech.render(kind, place="the sidewalk"),
                kind=kind,
            )
            spoken = act.text.lower()
            for phrase in FORBIDDEN_ARRIVAL_PHRASES:
                assert phrase not in spoken, f"{personality_id}/{kind}: {act.text!r}"
            # Nothing tentative is asserted as fact, and nothing verified is
            # asserted without a handle to the evidence.
            assert all(claim.evidence_ref for claim in act.claims)


def test_an_unknown_utterance_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown yield utterance kind"):
        yield_dialogue_act(turn_id="yield-1", text="Please move.", kind="boast")


# ---------------------------------------------------------------------------
# The config file
# ---------------------------------------------------------------------------


def test_every_shipped_personality_has_an_explicit_yield_entry() -> None:
    """A new personality must state its temperament, not inherit by accident."""

    config = load_personality_policy_config(REPO / "configs" / "personality.yaml")
    shipped = {path.stem for path in (REPO / "prompts" / "personalities").glob("*.yaml")}
    assert shipped, "no personalities found"
    assert shipped <= set(config.profiles), sorted(shipped - set(config.profiles))


def test_the_shipped_config_keeps_ask_for_help_as_every_personality_default() -> None:
    config = load_personality_policy_config(REPO / "configs" / "personality.yaml")
    assert config.defaults_policy.on_blocked == "ask_for_help"
    for personality_id in sorted(config.profiles):
        assert config.for_personality(personality_id).policy.on_blocked == "ask_for_help"


def test_personalities_actually_differ_in_temperament() -> None:
    """Otherwise "personality-parameterized" is a claim with no witness."""

    config = load_personality_policy_config(REPO / "configs" / "personality.yaml")
    patience = {
        pid: config.for_personality(pid).policy.patience_s for pid in config.profiles
    }
    lines = {
        pid: config.for_personality(pid).speech.render("ask", place="the sidewalk")
        for pid in config.profiles
    }
    assert len(set(patience.values())) > 1, patience
    assert len(set(lines.values())) > 1, lines


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"schema_version": 1, "defaultz": {}}, "unknown keys in personality config"),
        ({"schema_version": 2}, "schema_version"),
        (
            {"schema_version": 1, "defaults": {"yield_polcy": {}}},
            "unknown keys in personality defaults",
        ),
        (
            {"schema_version": 1, "profiles": {"gentle_companion": {"yeild_speech": {}}}},
            "unknown keys in personality profile",
        ),
        (
            {"schema_version": 1, "profiles": {"Gentle Companion": {}}},
            "invalid personality id",
        ),
        (
            {"schema_version": 1, "defaults": {"yield_policy": {"on_blocked": "barge"}}},
            "on_blocked",
        ),
    ],
)
def test_config_validation_is_fail_closed(tmp_path: Path, payload: dict, message: str) -> None:
    path = tmp_path / "personality.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises((ValueError, TypeError), match=message):
        load_personality_policy_config(path)


def test_a_personality_with_no_entry_inherits_defaults_and_says_so() -> None:
    config = PersonalityPolicyConfig.builtin()
    profile = config.for_personality("a_new_temperament")
    assert profile.policy == DEFAULT_YIELD_POLICY
    assert profile.source == "builtin"


# ---------------------------------------------------------------------------
# The runtime seam
# ---------------------------------------------------------------------------


class _Backend:
    """The pose-health harness's backend: deterministic, records every move."""

    name = "yield-policy-test"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0),
            backend=self.name,
        )
        self.moves: list[VelocityCommand] = []
        self.stop_count = 0

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        self.stop_count += 1

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill


def _write_config(tmp_path: Path, *, personality_policy: Path | None = None) -> Path:
    path = tmp_path / "robot-yield.yaml"
    extra = "" if personality_policy is None else f"\n  personality_policy: {personality_policy}"
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
agent:
  personality: gentle_companion{extra}
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _runtime(tmp_path: Path, *, personality_policy: Path | None = None) -> RobotRuntime:
    audio_status = AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )
    backend = _Backend()
    session = RobotRuntime(
        _write_config(tmp_path, personality_policy=personality_policy),
        backend,
        audio_status=audio_status,
    )
    observation = backend.observe()
    session._observation = observation
    if session._control_state_source is not None:
        session._control_state_source.update_observation(observation)
    session.backend_under_test = backend  # type: ignore[attr-defined]
    return session


@pytest.fixture()
def runtime(tmp_path: Path):
    session = _runtime(tmp_path)
    try:
        yield session
    finally:
        session.close()


def _block_with(runtime: RobotRuntime, note: str) -> None:
    """Replace the navigator's command with the measured gated one.

    Exactly what the navigator emits on a gated tick — ``stop=False`` with a
    zeroed translation and the composed note — and nothing more. Driving a real
    pedestrian into the last 0.2 m is the e2e case's job (card P-3); what is
    under test here is the runtime's response to the command.
    """

    healthy = runtime.dog.navigate

    def gated(directive: str, **kwargs: object):
        mission, _command = healthy(directive, **kwargs)
        return mission, MidLevelCommand(vx=0.0, vy=0.0, vyaw=0.0, stop=False, note=note)

    runtime.dog.navigate = gated


def _chat(runtime: RobotRuntime) -> list[str]:
    return [str(item["text"]) for item in (runtime.snapshot().get("chat") or [])]


def _start(runtime: RobotRuntime) -> None:
    reply = runtime.handle_text("go to the sidewalk")
    assert "couldn't admit" not in reply, reply
    runtime._step_brain()
    runtime._step_navigation(runtime._observation)
    assert runtime.snapshot()["navigation"]["enabled"] is True


def _tick(runtime: RobotRuntime, clock: _Clock, *, seconds: float, step_s: float = 0.1) -> None:
    for _ in range(max(1, round(seconds / step_s))):
        clock.advance(step_s)
        runtime._step_navigation(runtime._observation)


def test_a_person_block_produces_exactly_one_ask_at_patience(runtime: RobotRuntime) -> None:
    clock = _Clock()
    runtime._yield_clock = clock
    _start(runtime)
    _block_with(runtime, TRAFFIC_NOTE)

    _tick(runtime, clock, seconds=7.0)
    assert runtime.yield_policy_snapshot()["asks_spoken"] == 0

    _tick(runtime, clock, seconds=3.0)
    snapshot = runtime.yield_policy_snapshot()
    assert snapshot["asks_spoken"] == 1
    spoken = [line for line in _chat(runtime) if "stopped" in line.lower()]
    assert len(spoken) == 1, _chat(runtime)
    assert "{place}" not in spoken[0]
    assert "sidewalk" in spoken[0]


def test_the_ask_carries_a_backed_dialogue_act(runtime: RobotRuntime) -> None:
    clock = _Clock()
    runtime._yield_clock = clock
    _start(runtime)
    _block_with(runtime, TRAFFIC_NOTE)
    _tick(runtime, clock, seconds=10.0)

    act = runtime.yield_policy_snapshot()["last_utterance"]
    assert act is not None
    assert act["asks_clarification"] is True
    assert act["claims"], act
    for claim in act["claims"]:
        assert claim["veracity"] == "verified"
        assert claim["evidence_ref"] == "navigation:person_stop"
    for phrase in FORBIDDEN_ARRIVAL_PHRASES:
        assert phrase not in str(act["text"]).lower()


def test_after_max_asks_the_mission_fails_with_an_attributable_reason(
    runtime: RobotRuntime,
) -> None:
    """Not ``step_timeout`` four minutes later — a reason that names the cause."""

    clock = _Clock()
    runtime._yield_clock = clock
    _start(runtime)
    _block_with(runtime, TRAFFIC_NOTE)
    _tick(runtime, clock, seconds=60.0)

    navigation = runtime.snapshot()["navigation"]
    assert navigation["enabled"] is False
    assert navigation["state"] == "failed"
    assert navigation["reason"] == BLOCKED_BY_PERSON_UNANSWERED_REASON
    assert runtime._navigation_directive is None
    assert runtime.yield_policy_snapshot()["asks_spoken"] == 2


def test_the_failed_step_inherits_the_attributable_reason(runtime: RobotRuntime) -> None:
    clock = _Clock()
    runtime._yield_clock = clock
    _start(runtime)
    _block_with(runtime, TRAFFIC_NOTE)
    for _ in range(600):
        clock.advance(0.1)
        runtime._step_navigation(runtime._observation)
        runtime._step_brain()

    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "failed", task
    assert task["last_detail"] == BLOCKED_BY_PERSON_UNANSWERED_REASON, task


def test_a_person_who_moves_on_costs_the_mission_nothing(runtime: RobotRuntime) -> None:
    clock = _Clock()
    runtime._yield_clock = clock
    _start(runtime)
    _block_with(runtime, TRAFFIC_NOTE)
    _tick(runtime, clock, seconds=6.0)
    _block_with(runtime, "grid_track err=0.0 goal=0.2 route=2 status=planned")
    _tick(runtime, clock, seconds=6.0)

    assert runtime.yield_policy_snapshot()["asks_spoken"] == 0
    assert runtime._navigation_directive == "go to the sidewalk"
    assert runtime.snapshot()["navigation"]["enabled"] is True


def test_an_obstacle_block_never_speaks_and_never_abandons(runtime: RobotRuntime) -> None:
    """Requirement (d), at the runtime seam and not only in the pure module."""

    clock = _Clock()
    runtime._yield_clock = clock
    _start(runtime)
    _block_with(runtime, OBSTACLE_NOTE)
    _tick(runtime, clock, seconds=120.0)

    assert runtime.yield_policy_snapshot()["asks_spoken"] == 0
    assert runtime.yield_policy_snapshot()["last_utterance"] is None
    assert runtime._navigation_directive == "go to the sidewalk"


@pytest.mark.parametrize("on_blocked", ["ask_for_help", "wait", "give_up_honestly"])
def test_a_gated_tick_still_commands_zero_under_every_policy(
    tmp_path: Path, on_blocked: str
) -> None:
    """Requirement (c). The policy is downstream of the gate, always.

    Whatever the policy decides, every velocity the runtime submits while the
    person gate is closed is zero translation. If this ever fails, the policy
    has become a command source and must be reverted, not tuned.
    """

    policy_path = tmp_path / f"personality-{on_blocked}.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "defaults": {
                    "yield_policy": {
                        "patience_s": 1.0,
                        "on_blocked": on_blocked,
                        "reask_interval_s": 2.0,
                        "max_asks": 2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    session = _runtime(tmp_path, personality_policy=policy_path)
    try:
        clock = _Clock()
        session._yield_clock = clock
        _start(session)
        backend = session.backend_under_test  # type: ignore[attr-defined]
        backend.moves.clear()
        _block_with(session, TRAFFIC_NOTE)
        _tick(session, clock, seconds=30.0)

        intent = session.arbiter.current()
        assert intent is None or (
            intent.command.vx == 0.0 and intent.command.vy == 0.0
        ), intent
        assert all(move.vx == 0.0 and move.vy == 0.0 for move in backend.moves), backend.moves
    finally:
        session.close()


def test_wait_holds_the_mission_open_exactly_as_before(tmp_path: Path) -> None:
    policy_path = tmp_path / "personality-wait.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "defaults": {"yield_policy": {"patience_s": 1.0, "on_blocked": "wait"}},
            }
        ),
        encoding="utf-8",
    )
    session = _runtime(tmp_path, personality_policy=policy_path)
    try:
        clock = _Clock()
        session._yield_clock = clock
        _start(session)
        _block_with(session, TRAFFIC_NOTE)
        _tick(session, clock, seconds=300.0, step_s=1.0)

        assert session.yield_policy_snapshot()["asks_spoken"] == 0
        assert _chat(session) == [] or all(
            "in my way" not in line for line in _chat(session)
        )
        assert session._navigation_directive == "go to the sidewalk"
        assert session.snapshot()["navigation"]["enabled"] is True
    finally:
        session.close()


def test_give_up_honestly_ends_fast_and_says_why(tmp_path: Path) -> None:
    policy_path = tmp_path / "personality-giveup.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "defaults": {
                    "yield_policy": {"patience_s": 3.0, "on_blocked": "give_up_honestly"}
                },
            }
        ),
        encoding="utf-8",
    )
    session = _runtime(tmp_path, personality_policy=policy_path)
    try:
        clock = _Clock()
        session._yield_clock = clock
        _start(session)
        _block_with(session, TRAFFIC_NOTE)
        _tick(session, clock, seconds=5.0)

        navigation = session.snapshot()["navigation"]
        assert navigation["state"] == "failed"
        assert navigation["reason"] == BLOCKED_BY_PERSON_REASON
        assert session.yield_policy_snapshot()["asks_spoken"] == 0
        act = session.yield_policy_snapshot()["last_utterance"]
        assert act is not None and act["asks_clarification"] is False
    finally:
        session.close()


def test_personality_selects_the_policy_and_the_words(runtime: RobotRuntime) -> None:
    """The owner directive: this is a personality decision, at runtime."""

    before = runtime.yield_policy_snapshot()
    assert before["personality_id"] == "gentle_companion"
    runtime.set_personality("playful_companion")
    after = runtime.yield_policy_snapshot()
    assert after["personality_id"] == "playful_companion"
    assert after["yield_policy"] != before["yield_policy"]
    assert after["yield_speech"] != before["yield_speech"]
    assert after["yield_policy"]["on_blocked"] == "ask_for_help"


def test_a_new_mission_does_not_inherit_the_previous_ones_patience(
    runtime: RobotRuntime,
) -> None:
    clock = _Clock()
    runtime._yield_clock = clock
    _start(runtime)
    _block_with(runtime, TRAFFIC_NOTE)
    _tick(runtime, clock, seconds=7.0)
    assert runtime.yield_policy_snapshot()["tracker"]["blocked"] is True

    runtime.stop_navigation()
    assert runtime.yield_policy_snapshot()["tracker"]["blocked"] is False
    assert runtime.yield_policy_snapshot()["tracker"]["asks"] == 0


# ---------------------------------------------------------------- U35: audible
# The ask, the re-ask and the give-up all leave through ``_brain_vocalize``.
# Until 2026-08-09 that door wrote chat + the event log and stopped, so every
# line measured in P-3 was *visible and silent* (backlog U35). These cases pin
# that each one now also attempts the speaker, and that the snapshot says which
# of the two it was rather than letting a transcript imply a sound.
class _SpeakerProbe:
    """Stands in for ``DuplexVoiceSession`` at the runtime's speech seam."""

    def __init__(self, *, audible: bool = True) -> None:
        self.audible = audible
        self.spoken: list[str] = []

    def speak_system(self, text: str, *, turn_id: int = 0, kind: str = "system") -> bool:
        self.spoken.append(text)
        return self.audible

    def close(self, **_kwargs: object) -> bool:
        return True

    def barge_in(self) -> None:
        return None

    @property
    def speech_epoch(self) -> int:
        return 0


def test_every_yield_utterance_attempts_the_speaker(runtime: RobotRuntime) -> None:
    probe = _SpeakerProbe()
    runtime.voice_session = probe  # type: ignore[assignment]
    clock = _Clock()
    runtime._yield_clock = clock
    _start(runtime)
    _block_with(runtime, TRAFFIC_NOTE)
    _tick(runtime, clock, seconds=60.0)

    # ask, re-ask, give-up: the exact three lines P-3 measured, all attempted
    # on the speaker rather than only written to the panel.
    assert len(probe.spoken) == 3, probe.spoken
    assert probe.spoken == [line for line in _chat(runtime) if line in probe.spoken]
    assert runtime.yield_policy_snapshot()["last_utterance_audible"] is True


def test_an_inaudible_ask_is_recorded_as_inaudible(runtime: RobotRuntime) -> None:
    """A text-only host still speaks into the transcript — and says so."""

    runtime.voice_session = _SpeakerProbe(audible=False)  # type: ignore[assignment]
    clock = _Clock()
    runtime._yield_clock = clock
    _start(runtime)
    _block_with(runtime, TRAFFIC_NOTE)
    _tick(runtime, clock, seconds=10.0)

    snapshot = runtime.yield_policy_snapshot()
    assert snapshot["asks_spoken"] == 1
    assert snapshot["last_utterance"] is not None
    assert snapshot["last_utterance_audible"] is False
    # The visible record is unchanged: the chat item is written either way.
    assert [line for line in _chat(runtime) if "stopped" in line.lower()]


def test_the_snapshot_reports_no_audibility_before_anything_is_said(
    runtime: RobotRuntime,
) -> None:
    snapshot = runtime.yield_policy_snapshot()
    assert snapshot["last_utterance"] is None
    assert snapshot["last_utterance_audible"] is None
