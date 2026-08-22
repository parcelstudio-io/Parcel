"""Card P0-B — the hosted lane's four companion unlocks, each config-gated OFF.

WHAT THIS FILE IS FOR
---------------------
The production hosted lane is the companion's voice, and the 2026-08-22 audit
(§5, §9) named four refusals that make it feel inert:

1. it may never move unless the owner spoke first, so it cannot so much as tilt
   its head when somebody walks in;
2. a place noun it has not been taught is walked at and then abandoned at
   grounding, rather than asked about;
3. it hangs up after ten quiet minutes;
4. "I'm feeling sad" reaches the body on the LEGACY voice path and nowhere else,
   so on the lane that actually ships it does nothing at all.

Each unlock here is a validated key whose ABSENT value is the pre-card
behaviour. That is what keeps the frozen realtime fixtures and the SI/DI prompt
digests untouched: nothing in this card changes what a shipped config does.

THE THREE NEGATIVE DIRECTIONS THAT MATTER MOST TO AN AUDITOR
------------------------------------------------------------
* the proactive allowlist cannot be made to hold a TRAVEL tool — not through the
  config loader (a refusal, by name, with the reason) and not through the broker
  constructor either (a second gate, for callers that bypass the loader). A
  proactive ``navigate_to`` is bench finding C1 verbatim and no key buys it back.
* an admitted proactive gesture still goes through ``SafetySupervisor.validate``
  and still reaches the same door a typed request reaches. The unlock is a hole
  in ONE gate and nowhere else.
* ``unknown_place: ask`` starts NO motion. It is a question, not a slower yes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.router import AffectEvidence
from parcel_robot.memory import ConversationMemory
from parcel_robot.models import ActionProposal, AgentDecision, ToolCall, ToolResult
from parcel_robot.realtime.config import (
    ALLOWED_KEYS,
    ALLOWED_UNKNOWN_PLACE_MODES,
    DEFAULT_WHISPERER_WINDOW_S,
    IDLE_CLOSE_NEVER,
    PROACTIVE_MOTION_ALLOWED,
    PROACTIVE_MOTION_REFUSED,
    REALTIME_CONFIG_ENV,
    UNKNOWN_PLACE_ASK,
    UNKNOWN_PLACE_REFUSE,
    WHISPERER_ALLOWED_KEYS,
    RealtimeConfig,
    RealtimeConfigError,
    WhispererConfig,
    load_realtime_config,
    realtime_config_from_mapping,
)
from parcel_robot.realtime.lane import RESPONSE_FROM_OWNER, RESPONSE_FROM_SYSTEM
from parcel_robot.realtime.tool_broker import (
    MOTION_TOOLS,
    PROACTIVE_MOTION_CEILING,
    REASON_NOT_A_PLACE_NAME,
    REASON_UNKNOWN_PLACE,
    REFUSAL_SYSTEM_INITIATED_MOTION,
    STATUS_OK,
    STATUS_REJECTED,
    STATUS_UNKNOWN_PLACE,
    TENSE_NOT_STARTED,
    TOOL_CIRCLE_OWNER,
    TOOL_FOLLOW_OWNER,
    TOOL_NAVIGATE_TO,
    TOOL_PLAY_GESTURE,
    TOOL_ROAM,
    TOOL_SET_POSE,
    RealtimeToolBroker,
    ToolDoors,
)
from parcel_robot.realtime.whisperer import (
    KIND_BATTERY_STATE,
    StateEvent,
    Whisperer,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "p0b-companion"

#: Well-formed arguments for every motion tool, so a refusal in these tests is
#: never a refusal about the ARGUMENTS.
GOOD_ARGUMENTS: dict[str, str] = {
    TOOL_PLAY_GESTURE: '{"name": "paw_wave"}',
    TOOL_SET_POSE: '{"name": "sit"}',
    TOOL_NAVIGATE_TO: '{"place": "sidewalk"}',
    TOOL_CIRCLE_OWNER: "{}",
    TOOL_FOLLOW_OWNER: "{}",
    # Card ROAM-1. The ninth tool and the fourth travel tool. Its verdict on
    # this surface is written down rather than inherited: roam is a MOTION tool
    # (so the system-initiated gate refuses it) and it is in
    # PROACTIVE_MOTION_REFUSED (so no config can buy it back).
    TOOL_ROAM: "{}",
}


# ============================================================== the broker rig
class _Doors:
    """Records every door the broker touches. A touched door is a moved body."""

    def __init__(self, *, approve: bool = True) -> None:
        self.touched: list[tuple[str, tuple]] = []
        self.validated: list[ToolCall] = []
        self.dispatches = 0
        self._approve = approve

    def validate(self, call: ToolCall) -> ToolResult:
        self.validated.append(call)
        return ToolResult(call.name, self._approve, "approved" if self._approve else "refused")

    def status(self) -> dict[str, object]:
        return {"emergency_stopped": False, "battery_percent": 91.0}

    def recall(self, query: str) -> str:
        return f"recalled:{query}"

    def gesture(self, name: str, intensity: float) -> str:
        self.touched.append(("gesture", (name, intensity)))
        return "Accepted: gesture queued"

    def pose(self, name: str) -> str:
        self.touched.append(("pose", (name,)))
        return "Accepted: pose queued"

    def navigate(self, place: str, relation: str = "") -> str:
        self.touched.append(("navigate", (place, relation)))
        return "Heading out."

    def places(self) -> tuple[str, ...]:
        return ("sidewalk", "lamppost", "bench")

    def orbit(self, direction: str, size: str, revolutions: float) -> str:
        self.touched.append(("orbit", (direction, size, revolutions)))
        return "Circling."

    def follow(self, pace: str) -> str:
        self.touched.append(("follow", (pace,)))
        return "Owner-follow enabled"

    def roam(self, action: str, budget_s: float) -> str:
        self.touched.append(("roam", (action, budget_s)))
        return "Roaming for the next 120 seconds"

    def on_dispatch(self) -> None:
        self.dispatches += 1

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
            gesture_names=lambda: ("paw_wave", "head_nod"),
            pose_names=lambda: ("sit", "lie_down"),
            on_dispatch=self.on_dispatch,
        )


def _broker(**kwargs: Any) -> tuple[RealtimeToolBroker, _Doors]:
    doors = _Doors(approve=bool(kwargs.pop("approve", True)))
    return RealtimeToolBroker(doors.as_doors(), **kwargs), doors


def _answer(broker: RealtimeToolBroker, name: str, arguments: str = "{}") -> dict:
    return json.loads(broker.handle(name=name, call_id=f"call_{name}", arguments=arguments))


# ==================================================== 1. the proactive unlock
def test_the_shipped_default_is_still_no_proactive_motion_at_all() -> None:
    """Flag-off first. Card R11's gate is untouched by a config nobody wrote."""

    assert RealtimeConfig().proactive_motion_tools == ()
    for tool in sorted(MOTION_TOOLS):
        broker, doors = _broker()
        broker.note_response_provenance(RESPONSE_FROM_SYSTEM)
        result = _answer(broker, tool, GOOD_ARGUMENTS[tool])
        assert result["status"] == STATUS_REJECTED, tool
        assert result["refusal"] == REFUSAL_SYSTEM_INITIATED_MOTION
        assert doors.touched == [], f"{tool} moved the body with the flag off"
        assert broker.snapshot()["proactive_motion_admissions"] == 0


@pytest.mark.parametrize("tool", sorted(PROACTIVE_MOTION_ALLOWED))
def test_a_listed_tool_may_run_from_a_reply_the_robot_started(tool: str) -> None:
    """The unlock itself: the companion may greet you without being spoken to."""

    broker, doors = _broker(proactive_motion_tools=[tool])
    broker.note_response_provenance(RESPONSE_FROM_SYSTEM)

    result = _answer(broker, tool, GOOD_ARGUMENTS[tool])

    assert result["status"] == STATUS_OK, result
    assert doors.touched, "the door was never reached"
    assert doors.dispatches == 1
    # The supervisor is still the authority — the gate decided only WHETHER the
    # proposal is considered, never what happens to it afterwards.
    assert [call.name for call in doors.validated] == [
        {TOOL_PLAY_GESTURE: "run_skill", TOOL_SET_POSE: "run_pose"}[tool]
    ]
    # And the transcript says who started it, so "why did the dog move" has an
    # answer that does not require reading the config.
    assert result["provenance"] == RESPONSE_FROM_SYSTEM
    snapshot = broker.snapshot()
    assert snapshot["proactive_motion_admissions"] == 1
    assert snapshot["system_initiated_motion_refusals"] == 0
    assert snapshot["proactive_motion_tools"] == [tool]


@pytest.mark.parametrize("tool", sorted(PROACTIVE_MOTION_REFUSED))
def test_a_travel_tool_smuggled_past_the_loader_is_still_refused(tool: str) -> None:
    """The ceiling, enforced in the broker as well as at config load.

    The loader refuses these by name. This is the OTHER caller — a test, a
    future wiring, anything that constructs a broker directly — and it must not
    be a second way to buy a trip the owner never asked for.
    """

    broker, doors = _broker(proactive_motion_tools=[tool])
    broker.note_response_provenance(RESPONSE_FROM_SYSTEM)

    result = _answer(broker, tool, GOOD_ARGUMENTS[tool])

    assert result["status"] == STATUS_REJECTED
    assert result["refusal"] == REFUSAL_SYSTEM_INITIATED_MOTION
    assert doors.touched == []
    assert doors.validated == []
    assert broker.snapshot()["proactive_motion_tools"] == []
    assert broker.system_initiated_motion_refusals == 1


def test_the_ceiling_is_exactly_the_two_in_place_tools() -> None:
    """Stated as a property so a tool added tomorrow cannot join it silently."""

    assert PROACTIVE_MOTION_CEILING == frozenset(PROACTIVE_MOTION_ALLOWED)
    assert PROACTIVE_MOTION_CEILING <= MOTION_TOOLS
    assert not PROACTIVE_MOTION_CEILING & set(PROACTIVE_MOTION_REFUSED)
    assert set(PROACTIVE_MOTION_ALLOWED) | set(PROACTIVE_MOTION_REFUSED) == set(MOTION_TOOLS)


def test_an_admitted_proactive_gesture_still_obeys_the_supervisor() -> None:
    """A latched e-stop refuses a proactive wave for the reason it refuses any."""

    broker, doors = _broker(proactive_motion_tools=["play_gesture"], approve=False)
    broker.note_response_provenance(RESPONSE_FROM_SYSTEM)

    result = _answer(broker, TOOL_PLAY_GESTURE, GOOD_ARGUMENTS[TOOL_PLAY_GESTURE])

    assert result["status"] == STATUS_REJECTED
    assert doors.validated, "the supervisor must have been consulted"
    assert doors.touched == [], "a refused proposal reached a door"


def test_the_unlock_changes_nothing_about_the_owners_own_requests() -> None:
    """The negative direction: an owner-initiated call was never gated at all."""

    broker, doors = _broker(proactive_motion_tools=["play_gesture", "set_pose"])
    broker.note_response_provenance(RESPONSE_FROM_OWNER)

    result = _answer(broker, TOOL_NAVIGATE_TO, GOOD_ARGUMENTS[TOOL_NAVIGATE_TO])

    assert result["status"] == STATUS_OK
    assert doors.touched == [("navigate", ("sidewalk", ""))]
    # An owner request is not a proactive admission and must not be counted as one.
    assert broker.snapshot()["proactive_motion_admissions"] == 0
    assert "provenance" not in result


def test_the_allowlist_is_a_validated_key_that_refuses_the_travel_tools() -> None:
    assert "proactive_motion_tools" in ALLOWED_KEYS
    assert realtime_config_from_mapping({}).proactive_motion_tools == ()
    assert realtime_config_from_mapping(
        {"proactive_motion_tools": ["play_gesture", "set_pose", "play_gesture"]}
    ).proactive_motion_tools == ("play_gesture", "set_pose")

    for tool in PROACTIVE_MOTION_REFUSED:
        with pytest.raises(RealtimeConfigError) as caught:
            realtime_config_from_mapping({"proactive_motion_tools": [tool]})
        assert tool in str(caught.value)
        assert "travel" in str(caught.value), "the refusal must say WHY, not just no"


@pytest.mark.parametrize(
    "value",
    ["play_gesture", 7, [7], [""], {"play_gesture": True}, ["play_guesture"], ["get_status"]],
)
def test_an_unreadable_allowlist_is_a_refusal_not_a_default(value: object) -> None:
    """A mistyped ``play_guesture`` that silently did nothing would look exactly
    like the feature being broken, so it is a load-time refusal instead."""

    with pytest.raises(RealtimeConfigError) as caught:
        realtime_config_from_mapping({"proactive_motion_tools": value})
    assert "proactive_motion_tools" in str(caught.value)


def test_the_allowlist_is_published_so_an_owner_can_see_it_is_on() -> None:
    config = realtime_config_from_mapping({"proactive_motion_tools": ["set_pose"]})
    assert config.as_dict()["proactive_motion_tools"] == ["set_pose"]


# ================================================= 2. navigate_to asks, not no
def test_refuse_is_the_default_and_routes_an_unknown_noun_exactly_as_before() -> None:
    """Authority parity with a typed sentence, unchanged (card R20)."""

    assert RealtimeConfig().unknown_place == UNKNOWN_PLACE_REFUSE
    broker, doors = _broker()

    result = _answer(broker, TOOL_NAVIGATE_TO, '{"place": "narnia"}')

    assert result["status"] == STATUS_OK
    assert doors.touched == [("navigate", ("narnia", ""))]
    assert broker.snapshot()["unknown_place_asks"] == 0


def test_ask_mode_returns_a_question_and_starts_no_motion() -> None:
    broker, doors = _broker(unknown_place=UNKNOWN_PLACE_ASK)

    result = _answer(broker, TOOL_NAVIGATE_TO, '{"place": "narnia"}')

    assert result["status"] == STATUS_UNKNOWN_PLACE
    assert result["reason"] == REASON_UNKNOWN_PLACE
    assert result["place"] == "narnia"
    # The names the model can offer back, so it says something true.
    assert result["valid_places"] == ["sidewalk", "lamppost", "bench"]
    assert "ask the owner" in result["detail"]
    # NO MOTION. Not a slower yes: a question.
    assert doors.touched == [], "the robot moved toward a place it cannot ground"
    assert doors.dispatches == 0
    assert doors.validated == [], "the router was never asked, so neither was the supervisor"
    # And it is tensed like every other activity answer, because a status the
    # model has never seen before must still say the body stayed still.
    assert result["tense"] == TENSE_NOT_STARTED
    assert result["finished"] is False
    assert result["detail"].startswith(f"{TENSE_NOT_STARTED}: ")
    assert broker.snapshot()["unknown_place_asks"] == 1
    assert broker.snapshot()["unknown_place_mode"] == UNKNOWN_PLACE_ASK


def test_ask_mode_leaves_a_place_the_robot_knows_completely_alone() -> None:
    broker, doors = _broker(unknown_place=UNKNOWN_PLACE_ASK)

    result = _answer(broker, TOOL_NAVIGATE_TO, '{"place": "the big lamppost"}')

    assert result["status"] == STATUS_OK
    assert doors.touched == [("navigate", ("the big lamppost", ""))]
    assert broker.snapshot()["unknown_place_asks"] == 0


def test_ask_mode_still_refuses_a_directive_fragment() -> None:
    """"with owner" is not an unknown PLACE, it is not a place at all (R10)."""

    broker, doors = _broker(unknown_place=UNKNOWN_PLACE_ASK)

    result = _answer(broker, TOOL_NAVIGATE_TO, '{"place": "with owner"}')

    assert result["status"] == STATUS_REJECTED
    assert result["reason"] == REASON_NOT_A_PLACE_NAME
    assert doors.touched == []
    assert broker.snapshot()["unknown_place_asks"] == 0


def test_the_unknown_place_mode_is_a_validated_key() -> None:
    assert "unknown_place" in ALLOWED_KEYS
    assert ALLOWED_UNKNOWN_PLACE_MODES == {UNKNOWN_PLACE_REFUSE, UNKNOWN_PLACE_ASK}
    assert realtime_config_from_mapping({}).unknown_place == UNKNOWN_PLACE_REFUSE
    assert realtime_config_from_mapping({"unknown_place": "ask"}).unknown_place == "ask"
    assert realtime_config_from_mapping({"unknown_place": "ASK"}).unknown_place == "ask"
    for bad in ("maybe", "", None, 3, True, ["ask"]):
        with pytest.raises(RealtimeConfigError) as caught:
            realtime_config_from_mapping({"unknown_place": bad})
        assert "unknown_place" in str(caught.value)


def test_an_unrecognised_mode_reaching_the_broker_falls_back_to_shipped() -> None:
    """Fail-closed: a broker handed junk routes, it does not invent an answer."""

    broker, doors = _broker(unknown_place="wander")
    result = _answer(broker, TOOL_NAVIGATE_TO, '{"place": "narnia"}')
    assert result["status"] == STATUS_OK
    assert doors.touched == [("navigate", ("narnia", ""))]


# ================================================== 3. idle stays live (zero)
def test_zero_is_accepted_and_means_never_hang_up() -> None:
    assert IDLE_CLOSE_NEVER == 0.0
    assert RealtimeConfig().idle_close_after_s == 600.0, "the default is unchanged"
    assert RealtimeConfig().idle_close_enabled is True

    never = realtime_config_from_mapping({"idle_close_after_s": 0})
    assert never.idle_close_after_s == 0.0
    assert never.idle_close_enabled is False
    # Honestly published, which is the whole reason zero is not a silent switch.
    assert never.as_dict()["idle_close_after_s"] == 0.0


@pytest.mark.parametrize(
    "value", [-1, -600.0, float("inf"), float("-inf"), "never", True, None, [0]]
)
def test_everything_that_is_not_seconds_or_zero_is_still_a_refusal(value: object) -> None:
    with pytest.raises(RealtimeConfigError) as caught:
        realtime_config_from_mapping({"idle_close_after_s": value})
    assert "idle_close_after_s" in str(caught.value)


def test_the_other_two_bounds_on_an_unattended_session_still_refuse_zero() -> None:
    """Zero buys a session that does not hang ITSELF up. It buys nothing else."""

    for key in ("session_max_s", "monthly_budget_usd"):
        with pytest.raises(RealtimeConfigError):
            realtime_config_from_mapping({key: 0})


# ============================================= 4. the narration cap's window
def test_the_window_is_a_validated_key_that_defaults_to_the_same_minute() -> None:
    assert "window_s" in WHISPERER_ALLOWED_KEYS
    assert DEFAULT_WHISPERER_WINDOW_S == 60.0
    assert WhispererConfig().window_s == 60.0
    assert realtime_config_from_mapping({}).whisperer.window_s == 60.0
    assert (
        realtime_config_from_mapping({"whisperer": {"window_s": 30}}).whisperer.window_s == 30.0
    )
    assert WhispererConfig().as_dict()["window_s"] == 60.0


@pytest.mark.parametrize("value", [0, 0.0, -5, float("inf"), float("nan"), "60", True, None])
def test_a_window_that_would_remove_the_cap_silently_is_refused(value: object) -> None:
    with pytest.raises(RealtimeConfigError) as caught:
        realtime_config_from_mapping({"whisperer": {"window_s": value}})
    assert "window_s" in str(caught.value)


class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def _spend_the_cap(whisperer: Whisperer, clock: _Clock) -> None:
    """Forward the two facts the cap allows, spaced past the min-gap."""

    for index in range(2):
        whisperer.offer(
            StateEvent(kind=KIND_BATTERY_STATE, key=f"b{index}", fact=f"battery note {index}")
        )
        clock.advance(1.0)


def test_a_shorter_window_lets_the_narration_budget_refill_sooner() -> None:
    """The knob, doing the only thing it is for.

    Same cap, same spacing, same events: only the window differs, and the
    prototype's shorter window is what lets the third fact be spoken.
    """

    for window, expected in ((60.0, False), (10.0, True)):
        clock = _Clock()
        whisperer = Whisperer(
            config=WhispererConfig(max_updates_per_minute=2, min_gap_s=0.0, window_s=window),
            clock=clock,
        )
        _spend_the_cap(whisperer, clock)
        assert whisperer.snapshot()["updates_this_minute"] == 2
        assert whisperer.snapshot()["window_s"] == window

        clock.advance(12.0)
        decision = whisperer.offer(
            StateEvent(kind=KIND_BATTERY_STATE, key="b3", fact="battery note 3")
        )
        forwarded = bool(decision.forwarded)
        assert forwarded is expected, f"window {window}s forwarded={forwarded}"


def test_a_hand_built_config_with_no_window_still_counts_a_minute() -> None:
    """Belt and braces: a WhispererConfig built in code cannot divide by nothing."""

    clock = _Clock()
    whisperer = Whisperer(config=WhispererConfig(min_gap_s=0.0), clock=clock)
    _spend_the_cap(whisperer, clock)
    clock.advance(30.0)
    decision = whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="b9", fact="still here"))
    assert not decision.forwarded, "30 s is inside the default minute"


# ================================================== 5. affect on the hosted lane
class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: object) -> None:
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
    """If this is consulted for a hosted transcript, the hosted lane leaked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context
        self.calls.append(str(transcript))
        return AgentDecision("Understood.")


def _runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    hosted_affect: bool | None = None,
    minimum_confidence: float = 0.5,
) -> RobotRuntime:
    """A runtime whose realtime config is a REAL file, read the shipped way.

    ``hosted_affect=None`` writes no realtime config at all, which is the
    shipped state (the lane's config file is deliberately not in the repo) and
    therefore the flag-off case. Anything else writes one with ``enabled:
    false`` — the affect path is on the ingress and needs no open session, and a
    test must never be able to reach for a hosted socket.
    """

    tmp_path.mkdir(parents=True, exist_ok=True)
    if hosted_affect is None:
        monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    else:
        realtime = tmp_path / "p0b-realtime.yaml"
        realtime.write_text(
            f"enabled: false\nmode: text\nhosted_affect: {str(bool(hosted_affect)).lower()}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv(REALTIME_CONFIG_ENV, str(realtime))
    path = tmp_path / "p0b-robot.yaml"
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
  affect:
    minimum_confidence: {minimum_confidence}
memory:
  path: ":memory:"
duplex:
  enabled: true
  logging: true
  log_dir: {tmp_path / "duplex-logs"}
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="p0b fixture",
        ),
    )


def _affect_rows(runtime: RobotRuntime) -> list[str]:
    return [
        str(row["content"])
        for row in runtime.agent.memory.realtime_turns(limit=50)
        if str(row["content"]).startswith(f"[{RobotRuntime.HOSTED_AFFECT_PREFIX} ")
    ]


def _proposals(runtime: RobotRuntime, monkeypatch: pytest.MonkeyPatch) -> list[ActionProposal]:
    """Record every ``propose_action`` WITHOUT suppressing it."""

    seen: list[ActionProposal] = []
    original = runtime.propose_action

    def _spy(proposal: ActionProposal) -> str:
        seen.append(proposal)
        return original(proposal)

    monkeypatch.setattr(runtime, "propose_action", _spy)
    return seen


SAD = "I'm feeling sad today."


def test_hosted_affect_is_off_by_default_and_the_sentence_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag-off. This is the shipped behaviour and the audit's complaint."""

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        assert runtime.realtime_config.hosted_affect is False
        proposals = _proposals(runtime, monkeypatch)

        outcome = runtime.submit_realtime_transcript(SAD)

        assert outcome.executed is False
        assert proposals == []
        assert _affect_rows(runtime) == []
    finally:
        runtime.close()


def test_hosted_affect_writes_the_row_and_proposes_the_persona_gesture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unlock: "I'm feeling sad" reaches the body on the lane that ships."""

    runtime = _runtime(tmp_path, monkeypatch, hosted_affect=True)
    try:
        proposals = _proposals(runtime, monkeypatch)

        outcome = runtime.submit_realtime_transcript(SAD, session_id="rt_1")

        # (a) the meta row, in the conversation ledger, machine-readable.
        rows = _affect_rows(runtime)
        assert len(rows) == 1, rows
        assert rows[0].startswith("[affect sad]")
        assert "action=comfort_bow" in rows[0]
        assert "confidence=1.00" in rows[0]

        # (b) the persona's gesture, PROPOSED — the coordinator owns the timing.
        assert [(p.kind, p.name, p.trigger) for p in proposals] == [
            ("skill", "comfort_bow", "inferred_affect")
        ]
        assert proposals[0].timing_preference == "when_safe"
        assert proposals[0].interruption_request == "none"

        # And none of it makes the runtime claim it ran a local command: the
        # hosted model still owns the reply, and the broker must not think this
        # utterance was already acted on.
        assert outcome.executed is False
        assert outcome.reply == ""
        assert outcome.narration() == ""
    finally:
        runtime.close()


def test_hosted_affect_never_reaches_the_postural_recovery_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A comfort bow is a social gesture; ReturnToSafePose is recovery. Card P0-B
    says the two may never share a door, and this is that, pinned."""

    runtime = _runtime(tmp_path, monkeypatch, hosted_affect=True)
    try:
        recoveries: list[tuple] = []
        monkeypatch.setattr(
            runtime,
            "_brain_return_to_safe_pose",
            lambda *args, **kwargs: recoveries.append((args, kwargs)) or "",
        )

        runtime.submit_realtime_transcript(SAD)

        assert recoveries == []
        assert _affect_rows(runtime), "the affect path must actually have run"
    finally:
        runtime.close()


def test_hosted_affect_below_the_configured_confidence_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same bar ``agent._admit_proposal`` applies to a model-proposed one."""

    runtime = _runtime(tmp_path, monkeypatch, hosted_affect=True)
    try:
        proposals = _proposals(runtime, monkeypatch)
        monkeypatch.setattr(
            "parcel_robot.runtime.explicit_affect_from_text",
            lambda text: AffectEvidence(label="sad", confidence=0.4),
        )

        runtime.submit_realtime_transcript(SAD)

        assert proposals == []
        assert _affect_rows(runtime) == []
    finally:
        runtime.close()


def test_hosted_affect_never_runs_on_an_utterance_the_ingress_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One authority per utterance. The grammar is forced to fire so the test is
    about the KIND_NONE guard and not about the regex."""

    runtime = _runtime(tmp_path, monkeypatch, hosted_affect=True)
    try:
        proposals = _proposals(runtime, monkeypatch)
        monkeypatch.setattr(
            "parcel_robot.runtime.explicit_affect_from_text",
            lambda text: AffectEvidence(label="sad", confidence=1.0),
        )

        outcome = runtime.submit_realtime_transcript("stop")

        assert outcome.executed is True, "the emergency latch is the authority here"
        assert proposals == []
        assert _affect_rows(runtime) == []
    finally:
        runtime.close()


def test_a_failing_affect_path_can_never_take_down_the_pump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It runs on the realtime pump thread; nothing here is worth a dead pump."""

    runtime = _runtime(tmp_path, monkeypatch, hosted_affect=True)
    try:

        def _boom(text: str) -> None:
            raise RuntimeError("grammar exploded")

        monkeypatch.setattr("parcel_robot.runtime.explicit_affect_from_text", _boom)

        outcome = runtime.submit_realtime_transcript(SAD)

        assert outcome.transcript
        assert _affect_rows(runtime) == []
    finally:
        runtime.close()


# ============================================ 6. the shipped example documents it
def test_the_example_config_documents_every_new_key_and_still_parses() -> None:
    body = (REPO / "configs" / "realtime.yaml.example").read_text(encoding="utf-8")
    for key in ("proactive_motion_tools", "unknown_place", "hosted_affect", "window_s"):
        assert f"{key}:" in body, f"{key} is undocumented in the shipped example"
    assert "ZERO MEANS NEVER" in body, "the new meaning of idle_close_after_s: 0"

    parsed = load_realtime_config(REPO / "configs" / "realtime.yaml.example")
    # Documented, and documented OFF, so the example is still the shipped shape.
    assert parsed.proactive_motion_tools == ()
    assert parsed.unknown_place == UNKNOWN_PLACE_REFUSE
    assert parsed.hosted_affect is False
    assert parsed.idle_close_after_s == 600.0
    assert parsed.whisperer.window_s == 60.0


def test_a_realtime_config_written_before_this_card_is_unchanged_by_it() -> None:
    """The whole flag-off claim, in one assertion set."""

    before = realtime_config_from_mapping({"enabled": True, "mode": "text"})
    assert before.proactive_motion_tools == ()
    assert before.unknown_place == UNKNOWN_PLACE_REFUSE
    assert before.hosted_affect is False
    assert before.idle_close_after_s == 600.0
    assert before.idle_close_enabled is True
    assert before.whisperer == WhispererConfig()
    assert before.whisperer.window_s == DEFAULT_WHISPERER_WINDOW_S


def test_the_broker_built_with_no_companion_keys_is_the_pre_card_broker() -> None:
    broker, _ = _broker()
    snapshot = broker.snapshot()
    assert snapshot["proactive_motion_tools"] == []
    assert snapshot["unknown_place_mode"] == UNKNOWN_PLACE_REFUSE
    assert snapshot["proactive_motion_admissions"] == 0
    assert snapshot["unknown_place_asks"] == 0


def test_the_ledger_row_never_appears_in_the_chat_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is a note ABOUT the turn, not a thing the robot said. ``system`` rows
    are exactly the role ``mirror_realtime_chat`` declines to show."""

    runtime = _runtime(tmp_path, monkeypatch, hosted_affect=True)
    try:
        mirrored: list[tuple[str, str]] = []
        original = runtime.mirror_realtime_chat

        def _spy(speaker: str, text: str) -> None:
            mirrored.append((speaker, text))
            original(speaker, text)

        monkeypatch.setattr(runtime, "mirror_realtime_chat", _spy)

        runtime.submit_realtime_transcript(SAD)

        assert ("owner", SAD) in mirrored
        assert not [row for row in mirrored if row[0] == "owner" and "affect" in row[1]]
        assert [row for row in mirrored if row[0] == "system"], "the row was written"
    finally:
        runtime.close()


def test_a_conversation_memory_can_read_the_affect_row_back(
    tmp_path: Path,
) -> None:
    """The row is a real ledger row with a real provenance, not a log line."""

    memory = ConversationMemory(":memory:")
    row_id = memory.write_realtime_turn(
        session_id="rt_x",
        speaker="system",
        text="[affect sad] confidence=1.00 action=comfort_bow transcript='I am sad'",
        origin="realtime",
    )
    assert row_id
    rows = [str(row["content"]) for row in memory.realtime_turns(limit=10)]
    assert any(row.startswith("[affect sad]") for row in rows)
