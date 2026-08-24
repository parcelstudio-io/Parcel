"""Card R15: "done" means done — the completion over-claim, pinned shut.

THE SESSION THIS FILE EXISTS BECAUSE OF
---------------------------------------
2026-08-20, owner session 1, finding F2 (``evals/20260820/owner_session_1``).
The owner asked for a circle. The ledger, verbatim, three rows and two seconds:

    14:12:26  user       walk in a small counterclockwise circle around me
    14:12:26  assistant  Okay—I'll make the requested local circle around you safely.
    14:12:27  assistant  Done—I made a small circle around you, and it was okay.

The middle row is the broker's ``detail`` — the runtime's own acknowledgement,
passed straight through — and the third is the model narrating it one second
later. A lap the dog had barely started was reported to a human being, out loud,
as finished. The stack's own guardrail ("never claim a completed physical
action") was broken not by the model inventing something but by the tool result
handing it a promise and the beat asking it to say what came back.

WHAT IS PINNED HERE, IN THREE LAYERS
------------------------------------
1. **The result the model reads has a TENSE.** Every activity-class tool answer
   opens with ``started:`` / ``waiting:`` / ``not started:``, carries
   ``finished: False``, and contains no word that asserts the action already
   happened. The runtime's promise sentence is kept as ``admitted`` and never
   reaches the model's mouth.
2. **Completion comes from the body, not from the answer.** An activity that
   actually ends narrates through the whisperer's critical band — the same
   floor-gated channel navigation terminals have always used. An activity that
   stops short narrates as a refusal. An activity nobody asked for out loud
   (the robot's own inline ``[emote:...]`` tags) narrates nothing at all.
3. **The beat is told what to do with the tense.** ``RESULT_BEAT_RULE`` asks for
   the present progressive for accepted-not-finished work and forbids "done".

The system instructions are deliberately untouched: this is a defect in what the
robot's own systems SAY BACK, and it is fixed where it was made.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import (
    ActionProposal,
    AgentDecision,
    ToolCall,
    ToolResult,
    VelocityCommand,
)
from parcel_robot.navigation.spatial import SpatialDecision
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV, WhispererConfig
from parcel_robot.realtime.lane import DEFAULT_RECEIPT_TOOLS, RESULT_BEAT_RULE
from parcel_robot.realtime.tool_broker import (
    ACTIVITY_TOOLS,
    BROKER_TOOLS,
    COMPLETION_LANGUAGE,
    STATUS_DEFERRED,
    STATUS_DROPPED,
    STATUS_OK,
    STATUS_REJECTED,
    TENSE_NOT_STARTED,
    TENSE_STARTED,
    TENSE_WAITING,
    RealtimeToolBroker,
    ToolDoors,
    build_tool_specs,
    detail_tense_violation,
)
from parcel_robot.realtime.whisperer import (
    KIND_MISSION_ENDED,
    KIND_REFUSAL,
    Whisperer,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r15-tense"

#: The exact string the runtime handed the model on 2026-08-20 at 14:12:26.
#: Every test that uses it is asking the same question: can this sentence still
#: reach the model's mouth?
F2_ACK = "Okay—I'll make the requested local circle around you safely."

#: The mild form of the same defect, endorsed as a carry-forward by the R5
#: audit: "Accepted paw_wave for the next control tick" → "I waved. My paw
#: moved."
R8_ACK = "Accepted paw_wave for the next control tick"


# ============================================================ broker-level fakes
class _Doors:
    """Doors that answer whatever a test tells them to, and record the calls."""

    def __init__(self) -> None:
        self.allow = True
        self.refusal = "Motion is disabled by emergency stop"
        self.gesture_result = f"Accepted: {R8_ACK}"
        self.pose_result = "Accepted: Accepted sit for the next control tick"
        self.navigate_result = "Okay—I'll navigate toward the sidewalk safely."
        self.orbit_result = F2_ACK
        self.follow_result = "Okay—I'll follow you safely."
        # Card ROAM-1. The runtime's own admission sentence for a roam. Written
        # in the same first-person promise voice as its neighbours on purpose:
        # what this fixture proves is that the promise stays on the record as
        # ``admitted`` and never reaches ``detail``.
        self.roam_result = "Roaming for the next 120 seconds"
        self.errors: dict[str, Exception] = {}

    def _raise(self, tool: str) -> None:
        error = self.errors.get(tool)
        if error is not None:
            raise error

    def validate(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.name, self.allow, "approved" if self.allow else self.refusal)

    def status(self) -> dict[str, object]:
        return {"emergency_stopped": False}

    def recall(self, query: str) -> str:
        return f"recalled:{query}"

    def gesture(self, name: str, intensity: float) -> str:
        del name, intensity
        self._raise("play_gesture")
        return self.gesture_result

    def pose(self, name: str) -> str:
        del name
        self._raise("set_pose")
        return self.pose_result

    def navigate(self, place: str, relation: str = "") -> str:
        del place, relation
        self._raise("navigate_to")
        return self.navigate_result

    def places(self) -> tuple[str, ...]:
        return ("the sidewalk", "the lamppost")

    def orbit(self, direction: str, size: str, revolutions: float) -> str:
        del direction, size, revolutions
        self._raise("circle_owner")
        return self.orbit_result

    def follow(self, pace: str) -> str:
        del pace
        self._raise("follow_owner")
        return self.follow_result

    def roam(self, action: str, budget_s: float) -> str:
        del action, budget_s
        self._raise("roam")
        return self.roam_result

    def as_doors(self) -> ToolDoors:
        return ToolDoors(
            validate=self.validate,
            status=self.status,
            recall=self.recall,
            gesture=self.gesture,
            pose=self.pose,
            navigate=self.navigate,
            places=self.places,
            orbit=self.orbit,
            follow=self.follow,
            roam=self.roam,
            gesture_names=lambda: ("paw_wave",),
            pose_names=lambda: ("sit",),
        )


#: Arguments that reach each activity tool's door instead of being refused first.
ACTIVITY_ARGUMENTS = {
    "play_gesture": '{"name": "paw_wave"}',
    "set_pose": '{"name": "sit"}',
    "navigate_to": '{"place": "the sidewalk"}',
    "circle_owner": "{}",
    "follow_owner": "{}",
    # Card ROAM-1, the ninth tool.
    "roam": '{"action": "start", "minutes": 2}',
}


def _answer(broker: RealtimeToolBroker, name: str, arguments: str = "{}") -> dict:
    return json.loads(broker.handle(name=name, call_id=f"call_{name}", arguments=arguments))


def _broker() -> tuple[RealtimeToolBroker, _Doors]:
    doors = _Doors()
    return RealtimeToolBroker(doors.as_doors()), doors


# ====================================================== 1. the result has a tense
def test_the_activity_set_covers_every_tool_that_starts_something() -> None:
    """A tool that commits the body and is not in the set has no tense rule."""

    assert ACTIVITY_TOOLS <= set(BROKER_TOOLS)
    assert ACTIVITY_TOOLS == {
        "play_gesture",
        "set_pose",
        "navigate_to",
        "circle_owner",
        "follow_owner",
        # Card ROAM-1. The verdict, written down as this test asks: roam is the
        # LONGEST activity on the surface — minutes, not seconds — so it is the
        # one where "the result only ever says STARTED" matters most. A roam
        # that reported itself finished would be the F2 defect stretched over
        # two minutes instead of one second.
        "roam",
    }
    # The two read-only tools are NOT activities: their result IS the answer and
    # there is nothing about them that continues after the call returns.
    assert "get_status" not in ACTIVITY_TOOLS
    assert "recall_memory" not in ACTIVITY_TOOLS


@pytest.mark.parametrize("tool", sorted(ACTIVITY_TOOLS))
def test_every_accepted_activity_says_it_STARTED_and_never_that_it_finished(
    tool: str,
) -> None:
    """The F2 fix, over the whole surface rather than the one tool that broke."""

    broker, _doors = _broker()
    result = _answer(broker, tool, ACTIVITY_ARGUMENTS[tool])

    assert result["status"] == STATUS_OK
    assert result["tense"] == TENSE_STARTED
    assert result["finished"] is False
    assert result["detail"].startswith("started: ")
    assert detail_tense_violation(result["detail"]) == "", result["detail"]
    assert "NOT finished" in result["completion_note"]


@pytest.mark.parametrize("tool", sorted(ACTIVITY_TOOLS))
def test_the_runtimes_own_promise_is_kept_on_the_record_and_out_of_the_mouth(
    tool: str,
) -> None:
    """R4-lite's Defect C rule, applied to every activity instead of one.

    The admission sentence is a SCRIPT — first person, future tense, written for
    a text panel. ``admitted`` is where it belongs; ``detail`` is what the model
    reads out loud, and a promise read out loud one second before the body has
    moved is how "Done—I made a small circle around you" happens.
    """

    broker, _doors = _broker()
    result = _answer(broker, tool, ACTIVITY_ARGUMENTS[tool])

    assert result["admitted"], "the admission reply must still be on the record"
    assert result["admitted"] not in result["detail"]
    assert "Okay" not in result["detail"]
    assert "I'll" not in result["detail"]


@pytest.mark.parametrize(
    ("status", "tense", "door_answer"),
    [
        (STATUS_DEFERRED, TENSE_WAITING, "Deferred: Deferred paw_wave while navigating"),
        (STATUS_DROPPED, TENSE_NOT_STARTED, RuntimeError("Rejected: Gesture is cooling down")),
        (STATUS_REJECTED, TENSE_NOT_STARTED, ValueError("unknown emote: 'backflip'")),
    ],
)
def test_a_gesture_that_did_not_start_says_so_in_its_tense(
    status: str, tense: str, door_answer: object
) -> None:
    """Every disposition is tensed, not only the happy one.

    A refusal has never been at risk of being read as an accomplishment — but a
    result vocabulary where three answers out of four carry a tense marker and
    the fourth does not is one a future tool can quietly fall out of. The tense
    is stamped in ONE place for exactly that reason, and this is the pin.
    """

    broker, doors = _broker()
    if isinstance(door_answer, Exception):
        doors.errors["play_gesture"] = door_answer
    else:
        doors.gesture_result = str(door_answer)

    result = _answer(broker, "play_gesture", '{"name": "paw_wave"}')

    assert result["status"] == status
    assert result["tense"] == tense
    assert result["finished"] is False
    assert result["detail"].startswith(f"{tense}: ")
    assert detail_tense_violation(result["detail"]) == "", result["detail"]


def test_the_refusals_raised_before_any_door_is_touched_are_tensed_too() -> None:
    """Malformed arguments and a latched e-stop return through other paths."""

    broker, doors = _broker()
    doors.allow = False
    for tool in sorted(ACTIVITY_TOOLS):
        refused = _answer(broker, tool, ACTIVITY_ARGUMENTS[tool])
        assert refused["status"] == STATUS_REJECTED
        assert refused["tense"] == TENSE_NOT_STARTED, tool

    broker, _doors = _broker()
    malformed = _answer(broker, "circle_owner", "not json")
    assert malformed["tense"] == TENSE_NOT_STARTED
    assert malformed["detail"].startswith("not started: ")


def test_a_read_only_answer_is_left_exactly_as_it_was() -> None:
    """``get_status``/``recall_memory`` are answers, not activities.

    Prefixing "started:" onto "current robot state" would be a lie of a
    different kind, and the beat-suppression rule in the lane depends on these
    two staying the answers the owner is waiting for.
    """

    broker, _doors = _broker()
    status = _answer(broker, "get_status")
    memory = _answer(broker, "recall_memory", '{"query": "the willow"}')

    for result in (status, memory):
        assert "tense" not in result
        assert "finished" not in result
    assert status["detail"] == "current robot state"
    assert memory["detail"] == "recalled:the willow"


def test_no_broker_answer_of_any_kind_can_report_a_finished_action() -> None:
    """The structural claim: ``finished`` is False on every activity answer.

    It cannot be anything else. The broker returns while the body is still
    moving — there is no disposition, no door and no argument for which a
    completed physical action is a thing this module could truthfully report.
    """

    broker, doors = _broker()
    seen = []
    for tool in sorted(ACTIVITY_TOOLS):
        seen.append(_answer(broker, tool, ACTIVITY_ARGUMENTS[tool]))
    doors.allow = False
    for tool in sorted(ACTIVITY_TOOLS):
        seen.append(_answer(broker, tool, ACTIVITY_ARGUMENTS[tool]))

    assert seen
    assert all(row["finished"] is False for row in seen)
    assert not any("finished" in detail_words(row["detail"]) for row in seen)


def detail_words(detail: str) -> set[str]:
    return {word.strip(".,;:—").lower() for word in str(detail).split()}


def test_the_exact_sentence_that_produced_F2_can_no_longer_reach_the_model() -> None:
    """The regression, by its own words.

    ``doors.orbit`` returns the byte-exact sentence the runtime returned on
    2026-08-20. It must come back as a fact in the present progressive, with the
    promise filed under ``admitted``.
    """

    broker, doors = _broker()
    doors.orbit_result = F2_ACK

    result = _answer(broker, "circle_owner", '{"direction": "counterclockwise", "size": "small"}')

    assert result["detail"] == (
        "started: the robot is walking a counterclockwise circle around you, 1 of a lap"
    )
    assert result["admitted"] == F2_ACK
    assert F2_ACK not in json.dumps({"detail": result["detail"]})


def test_the_gesture_receipt_is_a_fact_and_not_the_coordinators_acceptance() -> None:
    """R5's carry-forward: "Accepted … for the next control tick" → "I waved"."""

    broker, doors = _broker()
    doors.gesture_result = f"Accepted: {R8_ACK}"

    result = _answer(broker, "play_gesture", '{"name": "paw_wave"}')

    assert result["detail"] == "started: the paw_wave gesture is running on the robot's body"
    assert result["admitted"] == R8_ACK


@pytest.mark.parametrize("tool", sorted(ACTIVITY_TOOLS))
def test_the_declared_tool_tells_the_model_the_result_is_never_an_ending(tool: str) -> None:
    """The schema the model reads BEFORE it calls anything says it too.

    The result carries the tense, but the description is what the model has in
    context while it decides what to say — and the bench's standing finding is
    that it narrates whatever it is given.
    """

    spec = next(row for row in build_tool_specs() if row["name"] == tool)
    description = str(spec["description"]).lower()
    assert "never" in description
    assert any(
        word in description
        for word in ("started", "arrived", "finished", "ends", "ending", "settled")
    )


# =============================================== 2. the beat is told the rule
def test_the_beat_rule_asks_for_the_present_progressive_and_forbids_done() -> None:
    """Card R15 item 3. One sentence added to R6's rule; SI untouched."""

    rule = RESULT_BEAT_RULE.lower()
    assert "present progressive" in rule
    assert "started" in rule
    assert "never say it is done" in rule
    # R6's original four claims survive intact — this is an addition, not a
    # rewrite, and the beat that reports a refusal is the one that matters most.
    assert "one short spoken sentence" in rule
    assert "refused, deferred or dropped" in rule


def test_the_two_R10_tools_still_always_get_their_beat() -> None:
    """Stated as a fact about this card's scope, not as an endorsement.

    ``circle_owner`` and ``follow_owner`` were never added to R6's receipt set,
    so their answer ALWAYS gets a beat — which is the beat that said "Done".
    R15 fixes what that beat is given to say; whether the beat should exist at
    all for a tool whose ending is now narrated separately is R6's question and
    is named in the status doc rather than decided here.
    """

    assert "circle_owner" not in DEFAULT_RECEIPT_TOOLS
    assert "follow_owner" not in DEFAULT_RECEIPT_TOOLS


# ============================================== 3. completion comes from the body
class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
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
        del transcript, tools, context
        return AgentDecision("Understood.")


class _FakeLane:
    """The three members the runtime's narration floor gate reads, plus a log."""

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
        return {"active": True, "narrations": len(self.narrated)}

    usage_rows: tuple = ()

    def close(self) -> None:
        return None


class _FakeSpatial:
    """A spatial controller whose terminal a test can name.

    The real controller is proven by ``tests/test_orbit_feasibility.py`` and
    ``tests/test_voice_nav_e2e.py``; what is under test HERE is the wiring
    between its terminal and the model, so the terminal is injected rather than
    walked. ``snapshot`` carries the intent because that is what
    ``_claim_orbit_terminal`` reads to tell an orbit from any other behaviour.
    """

    def __init__(self, behavior: str = "orbit_owner") -> None:
        self.active = True
        self.behavior = behavior
        self.decision = SpatialDecision(
            command=VelocityCommand(),
            done=True,
            state="completed",
            reason="orbit_complete",
            progress=1.0,
        )
        self.stopped = 0

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.active,
            "state": "orbiting",
            "intent": {"behavior": self.behavior, "direction": "counterclockwise"},
            "progress": 0.0,
        }

    def step(self, observation: object) -> SpatialDecision:
        del observation
        return self.decision

    def stop(self) -> None:
        self.active = False
        self.stopped += 1


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    path = tmp_path / "r15.yaml"
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
            detail="r15 tense fixture",
        ),
    )
    session._observation = session.backend.observe()
    try:
        yield session
    finally:
        session.close()


def _wire(runtime: RobotRuntime) -> _FakeLane:
    lane = _FakeLane()
    runtime.realtime_lane = lane  # type: ignore[assignment]
    runtime.realtime_whisperer = Whisperer(config=WhispererConfig(), clock=time.monotonic)
    return lane


def _run_one_gesture(runtime: RobotRuntime) -> str:
    """Start the first catalog emote through the hosted door and dispatch it."""

    name = runtime._emote_catalog[0]
    runtime._realtime_gesture(name, 1.0)
    runtime._step_activities()  # start_ready + dispatch
    return name


def _finish_the_running_activity(runtime: RobotRuntime) -> None:
    """Make the next control step the one where the movement is over.

    The coordinator ends an activity on wall-clock duration; rather than sleep
    through a real emote, the completion instant is moved into the past. This is
    the same field ``_step_activities`` sets itself.
    """

    runtime._activity_complete_at = 0.0
    runtime._step_activities()


def test_a_gesture_the_owner_asked_for_is_narrated_when_it_ACTUALLY_ends(
    runtime: RobotRuntime,
) -> None:
    """The other half of the pair. The broker said "started"; this says "done".

    Without this the model has a sentence for the beginning, none for the end,
    and an owner in front of it — which is the shape of the F2 defect.
    """

    lane = _wire(runtime)
    name = _run_one_gesture(runtime)
    assert lane.narrated == [], "nothing may be said while the body is still moving"

    _finish_the_running_activity(runtime)

    assert len(lane.narrated) == 1, lane.narrated
    said = lane.narrated[0]
    assert name.replace("_", " ") in said
    assert "FINISHED" in said
    assert "tell the owner it is done" in said.lower()
    rows = runtime.realtime_whisperer.decision_rows()
    assert rows[-1]["kind"] == KIND_MISSION_ENDED
    assert rows[-1]["forwarded"] is True


def test_the_robots_own_inline_emotes_end_in_silence(runtime: RobotRuntime) -> None:
    """The reason the terminal is MARKED rather than narrated unconditionally.

    ``_speech_emote`` runs a gesture for every ``[emote:...]`` tag the robot
    authors inside its own sentences. Narrating those endings would have the dog
    interrupting itself to announce a nod it never said it was making — one
    billed response per tag. Only a gesture the owner asked for is owed a word.
    """

    lane = _wire(runtime)
    name = runtime._emote_catalog[0]

    runtime._speech_emote(name, 1.0)
    runtime._step_activities()
    _finish_the_running_activity(runtime)

    assert lane.narrated == []


def test_a_gesture_that_was_cut_short_is_narrated_as_NOT_done(
    runtime: RobotRuntime,
) -> None:
    """A preempted movement is a refusal of what the owner asked for.

    R11 built ``_whisper_refusal`` with no caller and named this as the caller
    it was waiting for: "a mid-behaviour safety abort is the obvious next one".
    """

    lane = _wire(runtime)
    _run_one_gesture(runtime)
    # Navigation takes the body: the coordinator's own preemption path.
    runtime._navigation_directive = "navigate to the sidewalk"

    runtime._step_activities()

    assert len(lane.narrated) == 1, lane.narrated
    assert "STOPPED before it finished" in lane.narrated[0]
    assert "not done" in lane.narrated[0].lower()
    assert runtime.realtime_whisperer.decision_rows()[-1]["kind"] == KIND_REFUSAL


def test_one_ending_is_narrated_once(runtime: RobotRuntime) -> None:
    """The mark is one-shot: a second terminal cannot re-narrate the first."""

    lane = _wire(runtime)
    _run_one_gesture(runtime)
    _finish_the_running_activity(runtime)
    assert len(lane.narrated) == 1

    # A second, unasked-for gesture runs and ends. It inherits nothing.
    runtime._speech_emote(runtime._emote_catalog[1], 1.0)
    runtime._step_activities()
    _finish_the_running_activity(runtime)

    assert len(lane.narrated) == 1, lane.narrated


def test_a_refused_request_leaves_no_ending_owed(runtime: RobotRuntime) -> None:
    """A proposal the coordinator did NOT take must not leave a mark behind.

    ADDED BECAUSE SEED S12 CAME BACK GREEN. The seed removes the
    "``Accepted``/``Deferred`` only" condition from ``_mark_narratable_activity``
    so a REFUSED request is recorded as owed an ending, and
    ``test_one_ending_is_narrated_once`` did not notice: its second activity
    goes through ``_speech_emote``, which never reaches the marking door at all.

    The scenario the seed breaks is real. The owner asks for a pose while the
    emergency stop is latched; it is refused, and the refusal reaches them in
    the same turn as a ``rejected`` tool result. Later the same skill runs for
    some other reason. Nothing about that later movement is the thing they asked
    for, and announcing it as finished would be a completion claim attached to
    the wrong request — the F2 defect wearing a different coat.

    ``_realtime_pose`` is the door used rather than ``_realtime_gesture``
    because ``_brain_gesture`` RAISES on a rejection, so the marking line is
    never reached and the seed would be unobservable through it.
    """

    lane = _wire(runtime)
    pose = runtime._realtime_pose_names()[0]

    runtime.emergency_stop()
    refused = runtime._realtime_pose(pose)
    assert refused.startswith("Rejected"), refused
    assert runtime._narratable_activity == "", "a refused request is owed no ending"
    runtime.clear_emergency_stop()

    # The same skill now runs, but nobody asked for it over voice.
    accepted = runtime.propose_action(
        ActionProposal(
            kind="skill",
            name=pose,
            trigger="explicit_command",
            timing_preference="now",
            interruption_request="safe_checkpoint",
            reason="not a hosted request",
        )
    )
    assert accepted.startswith(("Accepted", "Deferred")), accepted
    runtime._step_activities()
    _finish_the_running_activity(runtime)

    assert lane.narrated == []


def test_the_orbit_terminal_is_the_only_thing_that_may_say_the_lap_is_over(
    runtime: RobotRuntime,
) -> None:
    """Card R15 item 2, success arm.

    R10 built the mid-orbit feasibility abort; neither outcome reached the
    model. This is the completion arm: the circle is genuinely over, and only
    now is "done" a true sentence.
    """

    lane = _wire(runtime)
    runtime.spatial = _FakeSpatial()  # type: ignore[assignment]
    runtime._narratable_orbit = True

    runtime._step_spatial(runtime.backend.observe())

    assert len(lane.narrated) == 1, lane.narrated
    assert "circle around you" in lane.narrated[0]
    assert "FINISHED" in lane.narrated[0]
    assert runtime.realtime_whisperer.decision_rows()[-1]["kind"] == KIND_MISSION_ENDED


def test_an_orbit_that_aborts_mid_lap_says_it_did_not_finish(
    runtime: RobotRuntime,
) -> None:
    """The abort arm — R10's ``orbit_annulus_blocked``, reaching the owner."""

    lane = _wire(runtime)
    spatial = _FakeSpatial()
    spatial.decision = SpatialDecision(
        command=VelocityCommand(),
        done=True,
        state="failed",
        reason="orbit_annulus_blocked",
        progress=0.32,
    )
    runtime.spatial = spatial  # type: ignore[assignment]
    runtime._narratable_orbit = True

    runtime._step_spatial(runtime.backend.observe())

    assert len(lane.narrated) == 1, lane.narrated
    assert "orbit_annulus_blocked" in lane.narrated[0]
    assert "STOPPED before it finished" in lane.narrated[0]
    assert runtime.realtime_whisperer.decision_rows()[-1]["kind"] == KIND_REFUSAL


def test_a_spatial_behaviour_nobody_asked_for_over_voice_stays_quiet(
    runtime: RobotRuntime,
) -> None:
    """A typed circle, or a relative move, has no hosted turn waiting on it."""

    lane = _wire(runtime)
    runtime.spatial = _FakeSpatial()  # type: ignore[assignment]
    runtime._narratable_orbit = False

    runtime._step_spatial(runtime.backend.observe())

    assert lane.narrated == []

    # And a marked lane still refuses a terminal that is not an orbit at all.
    lane.narrated.clear()
    runtime.spatial = _FakeSpatial(behavior="move_away")  # type: ignore[assignment]
    runtime._narratable_orbit = True
    runtime._step_spatial(runtime.backend.observe())
    assert lane.narrated == []
    assert runtime._narratable_orbit is True, "an unrelated terminal must not eat the mark"


def test_an_orbit_cancelled_from_outside_drops_its_mark_rather_than_speaking(
    runtime: RobotRuntime,
) -> None:
    """An e-stop or a new command already reaches the owner by its own channel.

    What must not happen is the mark surviving to be claimed by whatever spatial
    behaviour ends next — a completion sentence attached to the wrong movement.
    """

    lane = _wire(runtime)
    runtime.spatial = _FakeSpatial()  # type: ignore[assignment]
    runtime._narratable_orbit = True

    runtime._stop_spatial_locked("operator_stop")

    assert lane.narrated == []
    assert runtime._narratable_orbit is False


def test_the_completion_vocabulary_is_not_empty(runtime: RobotRuntime) -> None:
    """A guard on the guard: an empty word set would make the rule vacuous."""

    del runtime
    assert {"done", "finished", "made", "walked"} <= COMPLETION_LANGUAGE
    assert detail_tense_violation("started: I made a small circle around you")
