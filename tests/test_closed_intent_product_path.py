"""Every ClosedIntent, driven through ``handle_text`` at the runtime seam (U33).

U33's finding was not "one bad enum". It was that the closed-intent lane had
been reported as shipped while only its *components* were tested: the parser,
the cap resolver, and the sketch compiler each passed in isolation, and nothing
anywhere had ever called ``handle_text("come here")``. When someone finally
did, every "come here" dead-ended on a route/registry mismatch.

So this file is deliberately shaped like
``tests/test_navigation_admission_regression.py``: a real ``RobotRuntime`` over
a fake backend, entered at ``handle_text``, asserting the whole composition —
**route → registry → admission → executive effect** — for every member of
``ClosedIntent``. It is not an e2e sim case; it is the cheapest layer at which
the composition is real.

Two defects were found by writing it, both fixed in the same round:

* ``handle_text("halt")`` replied *"I did not understand that command"* and
  stopped nothing. ``parse_closed_intent`` mapped it to ``STOP``, but
  ``EMERGENCY_STOP_PHRASES`` was a separate literal that omitted it, and the
  agent deliberately skips ``STOP`` inside the closed-intent handler — so the
  one phrase family that must never fail silently did.
* ``pause`` / ``resume`` / ``faster`` / ``slower`` routed ``conversation_only``.
  The agent handled them correctly (it parses closed intents before consulting
  the route), but every consumer of ``IntentFrame.route`` saw an executive
  command as chat.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.router import DeterministicIntentRouter
from parcel_robot.models import ActionProposal, AgentDecision, VelocityCommand
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice.closed_intents import (
    CLOSED_INTENT_NAMES,
    ClosedIntent,
    closed_intent_phrases,
    parse_closed_intent,
)
from parcel_robot.voice.executive_caps import PACE_DEFAULT, PACE_MAX, PACE_MIN, PACE_STEP

REPO = Path(__file__).resolve().parents[1]

GENERIC_REFUSAL = "couldn't admit"
UNKNOWN_REPLY = "I did not understand that command"

#: One representative phrase per intent. GOAL_AMEND is a regex, not a phrase
#: list, so its representative comes from the correction grammar.
REPRESENTATIVE_PHRASE: dict[ClosedIntent, str] = {
    ClosedIntent.STOP: "stop",
    ClosedIntent.PAUSE: "pause",
    ClosedIntent.RESUME: "resume",
    ClosedIntent.FASTER: "faster",
    ClosedIntent.SLOWER: "slower",
    ClosedIntent.COME: "come here",
    ClosedIntent.GOAL_AMEND: "actually, the other one",
}


class _Backend:
    """Minimal deterministic backend: no threads, no sim, no timing."""

    name = "closed-intent-test"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0),
            backend=self.name,
        )
        self.moves: list[VelocityCommand] = []
        self.stop_count = 0
        self.poses: list[object] = []

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        self.stop_count += 1

    def pose(self, pose: object) -> None:
        self.poses.append(pose)

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        owner = self._observation.owner
        self._observation = replace(
            self._observation, owner=replace(owner, x=owner.x + dx, y=owner.y + dy)
        )


@pytest.fixture()
def config(tmp_path: Path) -> Path:
    path = tmp_path / "robot-closed-intent.yaml"
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
def audio_status() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


@pytest.fixture()
def runtime(config: Path, audio_status: AudioDeviceStatus):
    backend = _Backend()
    session = RobotRuntime(config, backend, audio_status=audio_status)
    # A cold runtime has no observation at all, which is fixture emptiness and
    # not a product state: admission reads the current snapshot.
    observation = backend.observe()
    session._observation = observation
    if session._control_state_source is not None:
        session._control_state_source.update_observation(observation)
    session.backend_probe = backend  # type: ignore[attr-defined]
    try:
        yield session
    finally:
        session.close()


def _start_navigation(runtime: RobotRuntime) -> None:
    """Give the runtime real work to pause/amend, through the product path."""

    reply = runtime.handle_text("go to the sidewalk")
    assert GENERIC_REFUSAL not in reply, reply
    runtime._step_brain()
    assert runtime.snapshot()["navigation"]["enabled"] is True


# --- the sweep -------------------------------------------------------------


def test_the_representative_set_covers_every_closed_intent() -> None:
    """A new ClosedIntent must fail this file until it is covered here."""

    assert {intent.value for intent in REPRESENTATIVE_PHRASE} == set(CLOSED_INTENT_NAMES)


@pytest.mark.parametrize("intent", list(ClosedIntent), ids=lambda item: item.value)
def test_every_closed_intent_is_recognized_and_routed_not_dead_ended(
    runtime: RobotRuntime,
    intent: ClosedIntent,
) -> None:
    """route → registry → admission, for every member of the enum."""

    phrase = REPRESENTATIVE_PHRASE[intent]
    reply = runtime.handle_text(phrase)
    agent = runtime.agent

    assert agent.last_closed_intent is intent, (
        f"{phrase!r} did not reach the closed-intent registry: {agent.last_closed_intent}"
    )
    assert GENERIC_REFUSAL not in reply, (
        f"admission dead-end for {phrase!r}: {reply!r} "
        f"(error={agent.last_reasoning_error!r})"
    )
    assert reply != UNKNOWN_REPLY, f"{phrase!r} fell through to the unknown-command reply"
    assert agent.last_reasoning_error is None
    frame = agent.last_intent_frame
    assert frame is not None
    # The route must not describe an executive command as conversation. STOP
    # and COME have their own reviewed rules; the caps share one.
    assert frame.route in {"direct_skill", "deliberative_plan"}, (
        f"{phrase!r} routed {frame.route!r}/{frame.matched_rule!r}"
    )


@pytest.mark.parametrize(
    ("intent", "rule", "route"),
    [
        (ClosedIntent.STOP, "emergency_stop", "direct_skill"),
        (ClosedIntent.PAUSE, "closed_intent:pause", "direct_skill"),
        (ClosedIntent.RESUME, "closed_intent:resume", "direct_skill"),
        (ClosedIntent.FASTER, "closed_intent:faster", "direct_skill"),
        (ClosedIntent.SLOWER, "closed_intent:slower", "direct_skill"),
        (ClosedIntent.COME, "come_to_owner", "direct_skill"),
        (ClosedIntent.GOAL_AMEND, "task_correction", "deliberative_plan"),
    ],
    ids=lambda item: str(item),
)
def test_router_rule_is_pinned_for_every_closed_intent(
    intent: ClosedIntent,
    rule: str,
    route: str,
) -> None:
    frame = DeterministicIntentRouter().route(
        REPRESENTATIVE_PHRASE[intent], turn_id=f"turn-{intent.value}"
    )
    assert (frame.route, frame.matched_rule) == (route, rule)


# --- per-intent executive effect -------------------------------------------


@pytest.mark.parametrize("phrase", sorted(closed_intent_phrases(ClosedIntent.STOP)))
def test_every_stop_phrase_latches_the_emergency_stop(
    runtime: RobotRuntime,
    phrase: str,
) -> None:
    """The "halt" regression: a stop word that parses must actually stop.

    Before 2026-08-07, ``halt`` parsed as ``ClosedIntent.STOP``, was skipped by
    the closed-intent handler (which deliberately does not re-implement STOP),
    was absent from ``EMERGENCY_STOP_PHRASES``, and therefore fell all the way
    through to "I did not understand that command" with the robot still moving.
    """

    assert parse_closed_intent(phrase) is ClosedIntent.STOP
    reply = runtime.handle_text(phrase)
    assert reply != UNKNOWN_REPLY, f"{phrase!r} is a stop word that did nothing"
    assert runtime.arbiter.emergency_stopped is True, f"{phrase!r} did not latch the stop"


def test_the_stop_grammar_has_exactly_one_source() -> None:
    """Three copies of "which words stop the robot" is how "halt" got lost."""

    from parcel_robot.agent import EMERGENCY_STOP_PHRASES
    from parcel_robot.brain import router

    canonical = closed_intent_phrases(ClosedIntent.STOP)
    assert EMERGENCY_STOP_PHRASES == canonical
    assert router._EMERGENCY_STOP == canonical
    assert "halt" in canonical


def test_pause_suspends_active_navigation_and_records_a_resume_intent(
    runtime: RobotRuntime,
) -> None:
    """PAUSE is a true pause, not a stop: the channel keeps its goal.

    ``enabled`` deliberately stays True — the navigation channel still owns the
    mission, it is just not advancing. Asserting ``enabled is False`` would be
    asserting a STOP, which is what the pause path is written *not* to do
    (stopping would destroy the ResumeIntent).
    """

    _start_navigation(runtime)
    reply = runtime.handle_text("pause")
    assert "pause" in reply.lower()

    navigation = runtime.snapshot()["navigation"]
    assert navigation["state"] == "paused"
    assert navigation["reason"] == "closed_intent_pause"
    assert navigation["directive"] == "go to the sidewalk"
    assert runtime._resume_store.peek("navigation", now_s=time.monotonic()) is not None
    assert [row.get("state") for row in runtime.task_executive.snapshot()["tasks"]] == [
        "suspended"
    ]


def test_resume_restores_the_paused_channel(runtime: RobotRuntime) -> None:
    _start_navigation(runtime)
    runtime.handle_text("pause")
    assert runtime.snapshot()["navigation"]["state"] == "paused"

    reply = runtime.handle_text("resume")
    assert "nothing paused" not in reply.lower(), reply
    navigation = runtime.snapshot()["navigation"]
    assert navigation["state"] != "paused"
    assert navigation["reason"] == "navigation_resumed"
    assert navigation["directive"] == "go to the sidewalk"


def test_resume_also_restores_the_executive_task_record(runtime: RobotRuntime) -> None:
    """N14, fixed 2026-08-07: the channel and its plan step resume together.

    Was xfail. The resume branch walked channels only, so the navigation
    channel came back while its task record stayed ``suspended`` — the robot
    driving with the step's verification, timeout, and recovery policy off.

    ``running``, not merely "not suspended", is the assertion: ``queued`` would
    also clear the old pin while telling the executive to *dispatch the step
    again*, which cold-starts the mission it just restored.
    """

    _start_navigation(runtime)
    runtime.handle_text("pause")
    runtime.handle_text("resume")

    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "running", task
    assert task["last_detail"] == "resumed_running:closed_intent_resume", task

    runtime._step_brain()
    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "running", f"task did not stay running after a tick: {task}"
    navigation = runtime.snapshot()["navigation"]
    assert navigation["state"] != "paused", navigation
    assert navigation["reason"] == "navigation_resumed", navigation


def test_resume_survives_a_control_tick_between_pause_and_resume(
    runtime: RobotRuntime,
) -> None:
    """The product shape: ``_step_brain`` runs at control rate, so it lands there.

    That tick is not incidental. ``_reconcile_semantic_tasks`` sees a suspended
    task, drops its dispatch record, and re-pauses the channel with reason
    ``task_suspended`` — which is how the old defect ended: a RESUME that
    "worked" was undone by the very next tick, and the mission stayed parked
    for good. The join must work from that state too, not only from the
    single-turn one.
    """

    _start_navigation(runtime)
    runtime.handle_text("pause")
    runtime._step_brain()
    assert runtime.snapshot()["navigation"]["reason"] == "task_suspended"
    assert runtime.semantic_tasks.active() == ()

    runtime.handle_text("resume")
    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "running", task
    # The dispatch record is re-bound, not re-issued: a second dispatch would
    # cold-start the mission instead of continuing the restored one.
    (dispatch,) = runtime.semantic_tasks.active()
    assert dispatch.request.skill == "NavigateTo"

    for _ in range(3):
        runtime._step_brain()
        assert runtime.snapshot()["navigation"]["state"] != "paused"
        (task,) = runtime.task_executive.snapshot()["tasks"]
        assert task["state"] == "running", task


def test_resume_continues_the_paused_mission_rather_than_restarting_it(
    runtime: RobotRuntime,
) -> None:
    """Re-binding, not re-dispatching: the mission object survives the pause."""

    _start_navigation(runtime)
    mission_before = runtime.dog.navigator.mission
    assert mission_before is not None
    runtime.handle_text("pause")
    runtime.handle_text("resume")
    runtime._step_brain()

    assert runtime.dog.navigator.mission is mission_before
    assert runtime.dog.navigator.paused is False


def test_a_stale_resume_leaves_both_the_channel_and_the_task_paused(
    runtime: RobotRuntime,
) -> None:
    """Fail-closed in the joined direction (K3/B1): neither half moves alone.

    A resume the freshness gate refuses must not leave the executive task
    running with a paused channel any more than the reverse.
    """

    _start_navigation(runtime)
    runtime.handle_text("pause")
    runtime._observation = None  # the gate's own rejection condition

    reply = runtime.handle_text("resume")
    assert "couldn't resume" in reply, reply
    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "suspended", task
    assert runtime.snapshot()["navigation"]["state"] == "paused"


def test_a_parked_task_with_no_pausable_channel_is_re_queued(
    runtime: RobotRuntime,
) -> None:
    """PAUSE suspends *every* running task; RESUME must be able to undo all of it.

    A ``Hold`` step has no ResumeIntent, because a suspend stops its controller
    outright rather than pausing it. Those tasks are therefore re-queued for a
    fresh dispatch instead of re-bound — the same distinction ``resume_task``
    and ``resume_task_running`` draw. Without this branch, "stay" → "pause" →
    "resume" answered *"There's nothing paused to resume right now"* and left
    the task suspended for good.
    """

    runtime.handle_text("stay")
    runtime._step_brain()
    runtime.handle_text("pause")
    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "suspended"

    reply = runtime.handle_text("resume")
    assert "nothing paused" not in reply.lower(), reply
    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "queued", task

    runtime._step_brain()
    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "running", task


def test_resume_does_not_restart_work_it_did_not_pause(runtime: RobotRuntime) -> None:
    """The join is on the suspend *reason*, not on "any suspended task".

    An owner summons and a goal amendment park tasks too. A spoken RESUME that
    un-suspended those would restart work the owner never paused.
    """

    _start_navigation(runtime)
    (task,) = runtime.task_executive.snapshot()["tasks"]
    runtime.task_executive.suspend_task(task["task_id"], reason="summons recall")
    runtime._step_brain()

    reply = runtime.handle_text("resume")
    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "suspended", task
    assert task["last_detail"] == "suspended:summons recall", task
    # And the channel is not released behind that task's back — releasing it
    # alone is the N14 defect reached through a different door.
    assert runtime.snapshot()["navigation"]["state"] == "paused"
    # Named for what it is: reporting this as a freshness problem would send
    # the owner to fix the wrong thing.
    assert reply == "I can't resume that yet — it's paused by something else right now."


def test_resume_with_nothing_paused_is_honest_rather_than_a_false_ack(
    runtime: RobotRuntime,
) -> None:
    """Fail closed: never claim to have resumed work that does not exist."""

    reply = runtime.handle_text("resume")
    assert reply == "There's nothing paused to resume right now."
    assert runtime.snapshot()["navigation"]["enabled"] is False


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("faster", PACE_DEFAULT + PACE_STEP),
        ("slower", PACE_DEFAULT - PACE_STEP),
    ],
)
def test_pace_intents_move_the_bounded_cap(
    runtime: RobotRuntime,
    phrase: str,
    expected: float,
) -> None:
    assert runtime._pace_cap.scale == pytest.approx(PACE_DEFAULT)
    runtime.handle_text(phrase)
    assert runtime._pace_cap.scale == pytest.approx(expected)


def test_pace_intents_saturate_at_the_authority_bounds(runtime: RobotRuntime) -> None:
    """The cap is bounded, so repeated commands clamp instead of running away."""

    for _ in range(12):
        runtime.handle_text("faster")
    assert runtime._pace_cap.scale == pytest.approx(PACE_MAX)
    for _ in range(12):
        runtime.handle_text("slower")
    assert runtime._pace_cap.scale == pytest.approx(PACE_MIN)


def test_come_admits_the_system_sketch_and_engages_the_direct_follow_lane(
    runtime: RobotRuntime,
) -> None:
    reply = runtime.handle_text("come here")
    assert GENERIC_REFUSAL not in reply, reply
    assert runtime.agent.last_reasoning_source == "local_plan_sketch"
    assert runtime.agent.last_brain_metrics["local_plan_skills"] == ["FollowFormation"]
    runtime._step_brain()
    assert runtime.follow.enabled is True
    assert runtime.follow.mode == "direct"


def test_goal_amend_suspends_active_work_before_replanning(runtime: RobotRuntime) -> None:
    _start_navigation(runtime)
    reply = runtime.handle_text("actually, the other one")
    metrics = runtime.agent.last_brain_metrics
    assert metrics["closed_intent"] == "goal-amend"
    assert metrics["goal_amend_ok"] is True, f"amend gate refused: {metrics} ({reply!r})"
    navigation = runtime.snapshot()["navigation"]
    assert navigation["state"] == "paused"
    assert navigation["reason"] == "goal_amend"
    # No planner in this fixture, and the replacement is anaphoric ("the other
    # one") — not a place this route can ground without context. Card
    # no-llm-honesty: the amendment now gives an HONEST, non-hanging reply
    # instead of the old ``deferred_no_planner`` indefinite pause behind
    # "I'll revise the current goal".
    assert metrics["goal_amend_replan"] == "no_planner_honest"
    assert "planner" in reply.lower()
    assert "new command" in reply.lower() or "start it fresh" in reply.lower()


# --- no-planner honesty (card no-llm-honesty, 2026-08-09) -------------------
#
# Without the planner model, the two most natural multi-step interactions used
# to over-promise: a compound ("go to the sidewalk and then sit") fell through
# to the single-skill navigation parser and compiled the whole conjunction as
# ONE literal destination label, sending the dog searching for a "sidewalk and
# then sit" entity behind a confident acknowledgment; and a goal amendment
# paused the mission forever behind "I'll revise the current goal". Both now
# fail honestly and never over-promise.


def test_a_compound_without_a_planner_clarifies_instead_of_compiling_a_literal():
    """The audit's 'sidewalk and then sit' case: clarify, never a literal query.

    The router routes it to the planner; without one, the turn must ask which
    part comes first rather than compile the conjunction into one NavigateTo
    label. Uses its own no-planner runtime so nothing carries over.
    """

    import tempfile

    from parcel_robot.audio_io import AudioDeviceStatus as _Status

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "robot.yaml"
        cfg.write_text(
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
        status = _Status(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="x",
        )
        backend = _Backend()
        session = RobotRuntime(cfg, backend, audio_status=status)
        obs = backend.observe()
        session._observation = obs
        if session._control_state_source is not None:
            session._control_state_source.update_observation(obs)
        try:
            reply = session.handle_text("go to the sidewalk and then sit")
            metrics = session.agent.last_brain_metrics
            assert session.agent.last_reasoning_source == "compound_clarify_no_planner"
            assert metrics["compound_without_planner"] == "clarify"
            # It split the conjunction to NAME the parts, and never compiled a
            # NavigateTo for the literal "sidewalk and then sit".
            assert metrics["compound_clauses"] == ["go to the sidewalk", "sit"]
            assert metrics.get("local_plan_skills") in (None, []), metrics
            assert "one thing at a time" in reply.lower()
            assert "sidewalk" in reply.lower() and "sit" in reply.lower()
            # No mission for the literal conjunction was ever started.
            assert session.snapshot()["navigation"]["enabled"] is False
        finally:
            session.close()


def test_a_compound_without_a_planner_is_routed_and_never_dead_ended(
    runtime: RobotRuntime,
) -> None:
    """A second navigation compound: clarified, never compiled to a literal query.

    Only compounds that reach the single-skill navigation parser (and would
    otherwise become one literal destination label) are intercepted; a
    non-navigation compound like "sit then sprint" never parses as a directive
    and stays with the conversation lane.
    """

    reply = runtime.handle_text("go to the bench and then sit down")
    metrics = runtime.agent.last_brain_metrics
    assert GENERIC_REFUSAL not in reply, reply
    assert metrics["compound_without_planner"] == "clarify"
    assert len(metrics["compound_clauses"]) >= 2
    assert metrics.get("local_plan_skills") in (None, [])  # no literal NavigateTo
    assert "planner" in reply.lower()


def test_a_goal_amend_without_a_planner_retargets_a_named_place(
    runtime: RobotRuntime,
) -> None:
    """A concrete replacement retargets deterministically — no planner needed to
    head somewhere new, and no indefinite pause."""

    _start_navigation(runtime)
    reply = runtime.handle_text("actually, go to the lamppost")
    metrics = runtime.agent.last_brain_metrics
    assert GENERIC_REFUSAL not in reply, reply
    assert metrics["goal_amend_ok"] is True
    assert metrics["goal_amend_replan"] == "local_retarget_no_planner"
    assert session_reasoning(runtime) == "local_plan_sketch"
    assert metrics["local_plan_skills"] == ["NavigateTo"]


def test_a_goal_amend_reply_never_over_promises_a_revision_it_cannot_make(
    runtime: RobotRuntime,
) -> None:
    """The honest branch says nothing it will not do — no "I'll revise the goal"
    followed by an indefinite hold."""

    _start_navigation(runtime)
    reply = runtime.handle_text("actually, the same thing but better")
    assert runtime.agent.last_brain_metrics["goal_amend_replan"] == "no_planner_honest"
    lowered = reply.lower()
    assert "planner" in lowered
    # It must not claim the revision is underway.
    assert "i'll revise" not in lowered and "revising the current goal" not in lowered


def session_reasoning(runtime: RobotRuntime) -> str:
    return str(runtime.agent.last_reasoning_source)


def test_goal_amend_with_nothing_active_is_honest(runtime: RobotRuntime) -> None:
    reply = runtime.handle_text("actually, the other one")
    assert runtime.agent.last_brain_metrics["goal_amend_ok"] is False
    assert runtime.agent.last_brain_metrics["goal_amend_reason"] == "nothing_to_amend"
    assert "nothing active" in reply.lower()


def test_the_amendment_grammar_has_one_source(runtime: RobotRuntime) -> None:
    """Router corrections and the closed-intent amend regex must not disagree.

    "the other one" parsed as GOAL_AMEND (the agent paused and replanned) while
    the router labelled the same turn ``conversation_only`` — the same
    route/registry split that hid the COME defect, one layer up.
    """

    router = DeterministicIntentRouter()
    for phrase in ("actually, the other one", "not that one", "the other bench", "instead go left"):
        assert parse_closed_intent(phrase) is ClosedIntent.GOAL_AMEND
        frame = router.route(phrase, turn_id="turn-amend")
        assert (frame.route, frame.matched_rule) == ("deliberative_plan", "task_correction"), phrase
        assert frame.speech_act == "correction"


# --- non-widening ----------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "do not stop",
        "don't pause",
        "what would happen if you came here",
        "tell me about the pause button",
        "i want to go faster on my bike",
    ],
)
def test_the_closed_grammars_do_not_widen(phrase: str) -> None:
    """Closed means closed: near-miss phrasing must not seize the executive."""

    assert parse_closed_intent(phrase) is None


# --- polite / LLM-lane physical requests (card llm-lane-dead-ends, 2026-08-09)
#
# Two dead-ends the LLM lane exists to absorb: a polite question-shaped motion
# request ("would you mind trotting over to the lamppost?") routed
# conversation_only and dead-ended in silence, and a conversation-lane decision
# that proposed the stripped-out 'navigate' tool leaked the raw internal
# "Unknown proposed skill: navigate" validator string to the owner. Neither may
# happen: the request starts NavigateTo (or clarifies), and no validator string
# ever reaches a user reply.


def test_a_polite_question_shaped_motion_request_starts_navigation(
    runtime: RobotRuntime,
) -> None:
    reply = runtime.handle_text("would you mind trotting over to the lamppost?")
    assert GENERIC_REFUSAL not in reply, reply
    assert runtime.agent.last_reasoning_source == "local_plan_sketch", reply
    assert runtime.agent.last_brain_metrics["local_plan_skills"] == ["NavigateTo"]


@pytest.mark.parametrize(
    "phrase",
    [
        "could you jog to the bench?",
        "would you mind scooting to the sidewalk?",
        "please trot over to the lamppost",
        "trot over to the bench",
    ],
)
def test_polite_gait_verb_requests_reach_the_navigation_lane(
    runtime: RobotRuntime, phrase: str
) -> None:
    reply = runtime.handle_text(phrase)
    assert GENERIC_REFUSAL not in reply, reply
    assert runtime.agent.last_brain_metrics.get("local_plan_skills") == ["NavigateTo"], (
        f"{phrase!r} did not reach navigation: {reply!r}"
    )


def test_a_polite_non_motion_question_does_not_manufacture_navigation(
    runtime: RobotRuntime,
) -> None:
    """The 'mind'/gait widening must not seize a genuine conversational turn."""

    runtime.handle_text("would you mind telling me a story?")
    assert runtime.agent.last_brain_metrics.get("local_plan_skills") in (None, [])
    assert runtime.snapshot()["navigation"]["enabled"] is False


class _NavProposingModel:
    """A conversation model that reaches for the stripped-out physical tool.

    Returns a decision proposing an ActionProposal naming a skill the
    conversation schema does not carry ("navigate") — the exact shape that used
    to leak "Unknown proposed skill: navigate" to the owner.
    """

    def __init__(self, name: str = "navigate") -> None:
        self._name = name

    def decide(self, transcript, tools, context):
        return AgentDecision(
            "Of course!",
            intent="conversation",
            next_action=ActionProposal(
                kind="skill", name=self._name, trigger="explicit_command"
            ),
        )


@pytest.mark.parametrize(
    "transcript",
    [
        "I really wish I could see the lamppost",
        "get closer to that thing over there",
        "it would be nice to be near the bench",
    ],
)
def test_a_conversation_lane_physical_proposal_never_leaks_the_validator_string(
    transcript: str,
) -> None:
    """The model proposes a stripped physical tool; the owner must never see the
    raw ``Unknown proposed skill`` string — a clarify stands in its place."""

    from parcel_robot.agent import VoiceAgent
    from parcel_robot.skills import Dog

    dog = Dog.from_config(REPO / "configs" / "robot.yaml")
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda _pose: None,
        language_model=_NavProposingModel(),
        action_proposal_publisher=lambda _proposal: "accepted",
        dog=dog,
    )
    reply = agent.handle_text(transcript)
    assert "Unknown proposed skill" not in reply, reply
    assert "navigate" not in reply.lower() or "could you" in reply.lower(), reply
    # It is a clarify, not silence and not a raw error.
    assert "?" in reply
