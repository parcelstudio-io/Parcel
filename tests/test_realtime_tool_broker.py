"""Card R3: the tool broker — the first card where the voice model moves the dog.

WHAT THIS FILE PINS
-------------------
Three claims, each of which an auditor should be able to break if it were false:

1. **Nothing reaches a door without the supervisor.** Every broker tool becomes
   a ``ToolCall`` and goes through ``SafetySupervisor.validate`` first. The
   e-stop tests are the R1 audit's carry-forward made pinnable: a latched
   emergency stop refuses a hosted pose for exactly the reason it refuses a
   typed one, and the refusal text comes from ``safety.py``, not from here.
2. **Routes come from the router.** ``navigate_to`` renders directive text and
   asks ``DeterministicIntentRouter``; only its own ``navigation_directive``
   rule proceeds. No ``IntentFrame`` is fabricated anywhere, which is the
   invariant ``_accept_plan`` enforces one layer down.
3. **The seam is inert when unused.** With ``tool_handler=None`` the lane's wire
   trace is byte-identical to R1's refusal stub — same output string, same
   counter, and crucially NO ``response.create``.

Time is injected; the transport is R1's in-process pair driven by
``FakeRealtimeServer``. Nothing here sleeps and nothing here touches a network.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from commissioned_sim import (
    authorize_commissioned_voice_binding,
    commissioned_runtime_kwargs,
)

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, ToolCall, ToolResult, VelocityCommand
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV, RealtimeConfig
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    function_call_turn,
    handshake,
)
from parcel_robot.realtime.ingress import RealtimeTranscriptOutcome
from parcel_robot.realtime.lane import TOOL_REFUSAL_OUTPUT, RealtimeLane
from parcel_robot.realtime.tool_broker import (
    BROKER_TOOLS,
    MAX_INTENSITY,
    MIN_INTENSITY,
    MOTION_TOOLS,
    ORBIT_DIRECTIONS,
    ORBIT_SIZES,
    STATUS_DROPPED,
    STATUS_OK,
    STATUS_REJECTED,
    TOOL_CIRCLE_OWNER,
    TOOL_FOLLOW_OWNER,
    RealtimeToolBroker,
    SessionToolsUpdate,
    ToolDoors,
    build_tool_specs,
)
from parcel_robot.realtime.transport import transport_pair
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r3-broker"


# ------------------------------------------------------------------ fakes
class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Sink:
    def __init__(self) -> None:
        self.first_chunk_started_monotonic: float | None = None
        self.chunks: list[bytes] = []

    def begin_utterance(self) -> None:
        self.first_chunk_started_monotonic = None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token
        self.chunks.append(chunk)

    def interrupt(self) -> None:
        return


class _Doors:
    """A recording stand-in for the runtime's doors. Fails loudly by default."""

    def __init__(self, *, allow: bool = True, refusal: str = "Tool is not allowed") -> None:
        self.allow = allow
        self.refusal = refusal
        self.validated: list[ToolCall] = []
        self.gestures: list[tuple[str, float]] = []
        self.poses: list[str] = []
        self.navigations: list[str] = []
        self.dispatches = 0
        self.gesture_error: Exception | None = None
        self.pose_result = "Accepted: pose queued"
        self.gesture_result = "Accepted: gesture queued"
        self.navigate_result = "Okay—I'll navigate toward the sidewalk safely."
        self.navigate_error: Exception | None = None
        # --- card R10 ------------------------------------------------------
        self.relations: list[str] = []
        self.orbits: list[tuple[str, str, float]] = []
        self.follows: list[str] = []
        self.orbit_result = "Okay—I'll walk a circle around you."
        self.orbit_error: Exception | None = None
        self.follow_result = "Owner-follow enabled"
        self.follow_error: Exception | None = None
        self.place_vocabulary: tuple[str, ...] = ("sidewalk", "lamppost", "bench", "door")

    def validate(self, call: ToolCall) -> ToolResult:
        self.validated.append(call)
        return ToolResult(call.name, self.allow, "approved" if self.allow else self.refusal)

    def status(self) -> dict[str, object]:
        return {"emergency_stopped": False, "battery_percent": 91.0}

    def recall(self, query: str) -> str:
        return f"recalled:{query}"

    def gesture(self, name: str, intensity: float) -> str:
        self.gestures.append((name, intensity))
        if self.gesture_error is not None:
            raise self.gesture_error
        return self.gesture_result

    def pose(self, name: str) -> str:
        self.poses.append(name)
        return self.pose_result

    def navigate(self, place: str, relation: str = "") -> str:
        self.navigations.append(place)
        self.relations.append(relation)
        if self.navigate_error is not None:
            raise self.navigate_error
        return self.navigate_result

    # --- card R10 doors ---------------------------------------------------
    def places(self) -> tuple[str, ...]:
        return self.place_vocabulary

    def orbit(self, direction: str, size: str, revolutions: float) -> str:
        self.orbits.append((direction, size, revolutions))
        if self.orbit_error is not None:
            raise self.orbit_error
        return self.orbit_result

    def follow(self, pace: str) -> str:
        self.follows.append(pace)
        if self.follow_error is not None:
            raise self.follow_error
        return self.follow_result

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
            gesture_names=lambda: ("paw_wave", "head_nod"),
            pose_names=lambda: ("sit", "lie_down"),
            on_dispatch=self.on_dispatch,
        )


def _broker(**kwargs) -> tuple[RealtimeToolBroker, _Doors]:
    doors = _Doors(**kwargs)
    return RealtimeToolBroker(doors.as_doors()), doors


def _answer(broker: RealtimeToolBroker, name: str, arguments: str = "{}") -> dict:
    return json.loads(broker.handle(name=name, call_id=f"call_{name}", arguments=arguments))


# ================================================== the admission chain
def test_every_tool_is_validated_before_any_door_is_touched() -> None:
    """The R1 audit carry-forward, structurally: validate first, always."""

    broker, doors = _broker()
    _answer(broker, "get_status")
    _answer(broker, "recall_memory", '{"query": "the park"}')
    _answer(broker, "play_gesture", '{"name": "paw_wave"}')
    _answer(broker, "set_pose", '{"name": "sit"}')
    _answer(broker, "navigate_to", '{"place": "the sidewalk"}')

    assert [call.name for call in doors.validated] == [
        "get_status",
        "recall_memory",
        "run_skill",
        "run_pose",
        "navigate",
    ], "each broker tool maps onto the supervisor's own vocabulary"
    assert doors.validated[2].arguments == {"name": "paw_wave"}
    assert doors.validated[3].arguments == {"name": "sit"}
    assert doors.validated[4].arguments == {"directive": "go to the sidewalk"}


def test_a_refusing_supervisor_stops_every_door() -> None:
    """One seeded refusal must reach the model as a refusal, not an exception."""

    broker, doors = _broker(allow=False, refusal="Motion is disabled by emergency stop")
    for name, arguments in (
        ("play_gesture", '{"name": "paw_wave"}'),
        ("set_pose", '{"name": "sit"}'),
        ("navigate_to", '{"place": "the sidewalk"}'),
    ):
        result = _answer(broker, name, arguments)
        assert result["status"] == STATUS_REJECTED
        assert "emergency stop" in result["detail"]
    assert doors.gestures == []
    assert doors.poses == []
    assert doors.navigations == []
    assert doors.dispatches == 0, "no thinking pose for a request that never dispatched"


def test_an_unknown_tool_name_is_refused_by_name() -> None:
    broker, doors = _broker()
    result = _answer(broker, "launch_missile", '{"target": "moon"}')
    assert result["status"] == STATUS_REJECTED
    assert "launch_missile" in result["detail"]
    assert doors.validated == [], "an unknown name never even becomes a ToolCall"


@pytest.mark.parametrize("arguments", ["not json", "[1, 2]", '"a string"'])
def test_malformed_arguments_are_refused_not_raised(arguments: str) -> None:
    broker, _ = _broker()
    result = _answer(broker, "play_gesture", arguments)
    assert result["status"] == STATUS_REJECTED


def test_intensity_is_clamped_by_the_broker_before_the_runtime_sees_it() -> None:
    """The runtime raises outside [0.5, 1.5]; the broker clamps and says so."""

    broker, doors = _broker()
    high = _answer(broker, "play_gesture", '{"name": "paw_wave", "intensity": 9}')
    assert high["status"] == STATUS_OK
    assert high["intensity"] == MAX_INTENSITY
    assert high["intensity_clamped"] is True

    low = _answer(broker, "play_gesture", '{"name": "head_nod", "intensity": -4}')
    assert low["intensity"] == MIN_INTENSITY

    exact = _answer(broker, "play_gesture", '{"name": "paw_wave", "intensity": 1.2}')
    assert exact["intensity"] == pytest.approx(1.2)
    assert exact["intensity_clamped"] is False
    assert [value for _, value in doors.gestures] == [MAX_INTENSITY, MIN_INTENSITY, 1.2]


def test_a_cooling_down_gesture_is_dropped_with_the_reason() -> None:
    """Arbitration declining a well-formed request is a fact, not an error."""

    broker, doors = _broker()
    doors.gesture_error = RuntimeError("Rejected: Gesture is cooling down")
    result = _answer(broker, "play_gesture", '{"name": "paw_wave"}')
    assert result["status"] == STATUS_DROPPED
    # Card R15: the reason is unchanged and now wears its tense, so the model
    # cannot read a drop as a thing that half-happened.
    assert result["detail"] == "not started: Gesture is cooling down"


def test_an_unknown_gesture_is_rejected_not_dropped() -> None:
    broker, doors = _broker()
    doors.gesture_error = ValueError("unknown emote: 'backflip'")
    result = _answer(broker, "play_gesture", '{"name": "backflip"}')
    assert result["status"] == STATUS_REJECTED


def test_a_deferred_pose_reports_deferred_rather_than_ok() -> None:
    broker, doors = _broker()
    doors.pose_result = "Deferred: waiting_for_navigation"
    result = _answer(broker, "set_pose", '{"name": "sit"}')
    assert result["status"] == "deferred"
    assert result["detail"] == "waiting: waiting_for_navigation"


# ================================================ one authority per utterance
def test_the_ingress_having_acted_drops_the_matching_tool_call() -> None:
    """S: "follow me" already moved the dog; the model may not move it again."""

    broker, doors = _broker()
    broker.note_ingress(
        RealtimeTranscriptOutcome(
            kind="follow",
            name="follow",
            transcript="follow me",
            reply="Following you.",
            executed=True,
        )
    )
    dropped = _answer(broker, "navigate_to", '{"place": "the sidewalk"}')
    assert dropped["status"] == STATUS_DROPPED
    assert "already acted" in dropped["detail"]
    assert doors.navigations == []
    assert doors.validated == [], "a dropped call never reaches the supervisor either"

    # Read-only tools are never a second authority.
    assert _answer(broker, "get_status")["status"] == STATUS_OK


def test_an_ingress_that_did_nothing_leaves_the_broker_free() -> None:
    broker, doors = _broker()
    broker.note_ingress(
        RealtimeTranscriptOutcome(
            kind="none",
            name="none",
            transcript="could you go to the sidewalk",
            reply="",
            executed=False,
        )
    )
    assert _answer(broker, "navigate_to", '{"place": "the sidewalk"}')["status"] == STATUS_OK
    assert doors.navigations == ["the sidewalk"]


def test_the_next_utterance_clears_the_previous_claim() -> None:
    broker, _ = _broker()
    acted = RealtimeTranscriptOutcome(
        kind="hold", name="hold", transcript="stay", reply="Staying.", executed=True
    )
    quiet = RealtimeTranscriptOutcome(
        kind="none", name="none", transcript="thanks", reply="", executed=False
    )
    broker.note_ingress(acted)
    assert _answer(broker, "set_pose", '{"name": "sit"}')["status"] == STATUS_DROPPED
    broker.note_ingress(quiet)
    assert _answer(broker, "set_pose", '{"name": "sit"}')["status"] == STATUS_OK


# ============================================================ the tool surface
def test_the_declared_schemas_carry_the_robots_own_catalog() -> None:
    specs = build_tool_specs(gestures=("paw_wave", "bow"), poses=("sit",))
    names = [spec["name"] for spec in specs]
    assert names == list(BROKER_TOOLS)
    gesture = next(spec for spec in specs if spec["name"] == "play_gesture")
    assert gesture["parameters"]["properties"]["name"]["enum"] == ["bow", "paw_wave"]
    pose = next(spec for spec in specs if spec["name"] == "set_pose")
    assert pose["parameters"]["properties"]["name"]["enum"] == ["sit"]


def test_session_tools_update_is_a_session_update_frame() -> None:
    """It has to be, or the fake server (and the provider) refuses the type."""

    payload = SessionToolsUpdate(tools=({"type": "function", "name": "x"},)).to_payload()
    assert payload["type"] == "session.update"
    assert payload["session"]["tool_choice"] == "auto"
    assert payload["session"]["tools"] == [{"type": "function", "name": "x"}]


# ====================================================== the lane's seam
class _Rig:
    def __init__(self, script: list[Step], *, tool_handler=None) -> None:
        self.clock = _Clock()
        self.script = script
        self.servers: list[FakeRealtimeServer] = []
        self.sink = _Sink()
        self.lane = RealtimeLane(
            config=RealtimeConfig(enabled=True, source="test"),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=self.sink,
            clock=self.clock,
            tool_handler=tool_handler,
            sleep=lambda seconds: self.clock.advance(seconds),
        )

    def _factory(self):
        lane_end, server_end = transport_pair(clock=self.clock)
        self.servers.append(
            FakeRealtimeServer(transport=server_end, script=list(self.script), clock=self.clock)
        )
        return lane_end

    @property
    def server(self) -> FakeRealtimeServer:
        return self.servers[-1]

    def open(self) -> str:
        session = self.lane.open_session(handshake_token="csrf", mic_gesture=True)
        self.step()
        return session

    def step(self) -> None:
        self.server.pump()
        self.lane.pump()

    def speak(self) -> None:
        self.lane.send_audio(b"\x00\x01" * 240)
        self.step()

    def sent(self) -> list[dict]:
        transport = self.lane.transport
        assert transport is not None
        return list(transport.sent)  # type: ignore[attr-defined]

    def sent_types(self) -> list[str]:
        return [str(frame.get("type")) for frame in self.sent()]


def test_with_no_handler_the_refusal_stub_is_byte_identical() -> None:
    """S: tool-handler unset ⇒ R1's behaviour, to the byte and to the frame."""

    rig = _Rig(handshake() + function_call_turn(name="navigate_to"))
    rig.open()
    rig.speak()

    assert rig.lane.refused_tool_calls == ["navigate_to"]
    assert rig.lane.brokered_tool_calls == []
    outputs = [
        frame["item"]
        for frame in rig.sent()
        if frame.get("type") == "conversation.item.create"
        and isinstance(frame.get("item"), dict)
        and frame["item"].get("type") == "function_call_output"
    ]
    assert len(outputs) == 1
    assert outputs[0]["output"] == TOOL_REFUSAL_OUTPUT
    assert "response.create" not in rig.sent_types(), (
        "the R1 stub never asked for a follow-up response; that must not change"
    )
    assert rig.lane.snapshot()["tools_enabled"] is False


def test_a_wired_broker_answers_once_and_then_asks_for_a_reply() -> None:
    broker, doors = _broker()
    rig = _Rig(handshake() + function_call_turn(name="play_gesture", arguments='{"name": "bow"}'))
    rig.lane._tool_handler = broker
    rig.open()
    rig.speak()

    outputs = [
        frame["item"]
        for frame in rig.sent()
        if frame.get("type") == "conversation.item.create"
        and isinstance(frame.get("item"), dict)
        and frame["item"].get("type") == "function_call_output"
    ]
    assert len(outputs) == 1, "every function_call is answered exactly once"
    assert json.loads(outputs[0]["output"])["status"] == STATUS_OK
    assert outputs[0]["call_id"] == "call_1"
    types = rig.sent_types()
    assert types[-1] == "response.create", "the model must narrate what happened"
    assert rig.lane.refused_tool_calls == []
    assert rig.lane.brokered_tool_calls == ["play_gesture"]
    assert doors.gestures == [("bow", 1.0)]
    assert doors.dispatches == 1, "the thinking pose fires on dispatch"


def test_a_broker_that_raises_still_answers_the_call() -> None:
    """An unanswered function_call wedges the provider's turn forever."""

    class _Exploding:
        def session_events(self):
            return ()

        def handle(self, *, name, call_id, arguments):
            raise RuntimeError("broker exploded")

    rig = _Rig(handshake() + function_call_turn(name="set_pose"), tool_handler=_Exploding())
    rig.open()
    rig.speak()
    outputs = [
        frame["item"]
        for frame in rig.sent()
        if frame.get("type") == "conversation.item.create"
        and isinstance(frame.get("item"), dict)
        and frame["item"].get("type") == "function_call_output"
    ]
    assert len(outputs) == 1
    assert json.loads(outputs[0]["output"])["status"] == "rejected"
    assert rig.lane.active, "one bad tool call must not take down the session"


def test_the_tool_surface_is_declared_at_every_session_boundary() -> None:
    broker, _ = _broker()
    rig = _Rig(handshake(), tool_handler=broker)
    rig.open()
    updates = [frame for frame in rig.sent() if frame.get("type") == "session.update"]
    assert len(updates) == 2, "instructions, then tools"
    assert "instructions" in updates[0]["session"]
    assert [tool["name"] for tool in updates[1]["session"]["tools"]] == list(BROKER_TOOLS)

    # A reconnect re-declares them: the provider holds no session state for us.
    rig.lane._reconnect("disconnect")
    rig.step()
    reconnected = [frame for frame in rig.sent() if frame.get("type") == "session.update"]
    assert len(reconnected) == 2, "the new socket gets its own pair"


# ========================================================= the runtime, wired
class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        # A FRESH timestamp, unlike R1's fixture: plan admission revalidates
        # against ``sensor_stale_s`` and an ancient observation is refused with
        # "my camera feed is stale" long before any of this card's logic runs.
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
    def __init__(self) -> None:
        self.calls: list[str] = []

    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context
        self.calls.append(str(transcript))
        return AgentDecision("Understood.")


def _runtime(tmp_path: Path, *, realtime: str | None = None) -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "r3-broker.yaml"
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
    del realtime
    runtime = RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r3 broker fixture",
        ),
        **commissioned_runtime_kwargs(path),
    )
    authorize_commissioned_voice_binding(runtime)
    return runtime


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A runtime with the lane enabled in text mode, and no credential needed."""

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV", raising=False)
    runtime = _runtime(tmp_path)
    try:
        yield runtime
    finally:
        runtime.close()


def _observe(runtime: RobotRuntime) -> None:
    """One observation, without starting threads.

    Plan admission revalidates against a FRESH ``ObservationSnapshot``; with no
    control loop running the runtime has never observed and every mission is
    honestly refused for stale perception. This is the loop's one line.
    """

    runtime._observation = runtime.backend.observe()


def test_the_runtime_builds_a_broker_only_when_the_lane_is_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S: flag-off ⇒ the runtime boots identically; nothing new exists."""

    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        assert runtime.realtime_lane is None
        assert runtime.realtime_broker is None
        assert runtime.realtime_driver is None
        assert runtime.realtime_gateway is None
        assert runtime.realtime_snapshot() == {
            "enabled": False,
            "constructed": False,
            "mode": "text",
            "config": runtime.realtime_config.as_dict(),
            # Card R11. The whisperer is built whether or not a lane is — it is
            # a pure decision object, and "how often may the robot start a
            # billed exchange with me" is a fact about the configuration rather
            # than about the socket. Nothing about it is ON here: with no lane
            # there is nothing for it to forward to and it has decided nothing.
            "whisperer": runtime.realtime_whisperer.snapshot(),
        }
        assert runtime.realtime_whisperer.forwarded == 0
        assert runtime.realtime_whisperer.suppressed == 0
        assert "recall_memory" not in runtime.agent.safety.information_tools
        assert runtime.submit_voice_text("hello there") == 1
    finally:
        runtime.close()


def test_recall_memory_validates_because_it_joined_the_information_allowlist(wired) -> None:
    assert "recall_memory" in wired.agent.safety.information_tools
    approved = wired.agent.safety.validate(ToolCall("recall_memory", {"query": "park"}))
    assert approved.accepted is True
    # And the fail-closed default is untouched for everything else.
    assert wired.agent.safety.validate(ToolCall("teleport", {})).accepted is False


def test_a_pose_under_emergency_stop_is_refused_through_the_broker(wired) -> None:
    """The R1 audit's carry-forward, now pinned end to end."""

    broker = wired.realtime_broker
    assert broker is not None
    wired.agent.safety.engage_emergency_stop()
    result = json.loads(broker.handle(name="set_pose", call_id="c1", arguments='{"name": "sit"}'))
    assert result["status"] == STATUS_REJECTED
    assert "emergency stop" in result["detail"].lower()

    gesture = json.loads(
        broker.handle(name="play_gesture", call_id="c2", arguments='{"name": "paw_wave"}')
    )
    assert gesture["status"] == STATUS_REJECTED

    navigate = json.loads(
        broker.handle(name="navigate_to", call_id="c3", arguments='{"place": "the sidewalk"}')
    )
    assert navigate["status"] == STATUS_REJECTED


def test_get_status_reports_the_runtimes_real_state(wired) -> None:
    broker = wired.realtime_broker
    result = json.loads(broker.handle(name="get_status", call_id="c1", arguments="{}"))
    assert result["status"] == STATUS_OK
    assert result["state"]["emergency_stopped"] is False
    wired.agent.safety.engage_emergency_stop()
    wired.emergency_stop()
    after = json.loads(broker.handle(name="get_status", call_id="c2", arguments="{}"))
    assert after["state"]["emergency_stopped"] is True


def test_recall_memory_reads_the_conversation_ledger(wired) -> None:
    wired.agent.memory.write_realtime_turn(
        session_id="s1",
        speaker="owner",
        text="we walked past the blue bench",
        origin="realtime",
    )
    broker = wired.realtime_broker
    hit = json.loads(
        broker.handle(name="recall_memory", call_id="c1", arguments='{"query": "blue bench"}')
    )
    assert hit["status"] == STATUS_OK
    assert "blue bench" in hit["detail"]
    miss = json.loads(
        broker.handle(name="recall_memory", call_id="c2", arguments='{"query": "submarine"}')
    )
    assert miss["detail"] == "nothing recorded about that yet"


def test_a_gesture_proposal_reaches_the_activity_coordinator(wired) -> None:
    broker = wired.realtime_broker
    name = wired._emote_catalog[0]
    result = json.loads(
        broker.handle(
            name="play_gesture",
            call_id="c1",
            arguments=json.dumps({"name": name, "intensity": 1.3}),
        )
    )
    assert result["status"] == STATUS_OK
    pending = wired.activities.snapshot()
    assert pending["pending"], "the proposal is queued for the next control tick"

    # The same gesture immediately again is a cooldown drop, not an error.
    again = json.loads(
        broker.handle(name="play_gesture", call_id="c2", arguments=json.dumps({"name": name}))
    )
    assert again["status"] == STATUS_DROPPED


def test_set_pose_refuses_anything_that_is_not_a_catalog_pose(wired) -> None:
    broker = wired.realtime_broker
    poses = wired._realtime_pose_names()
    assert poses, "the fixture catalog must contain at least one pose skill"
    ok = json.loads(
        broker.handle(name="set_pose", call_id="c1", arguments=json.dumps({"name": poses[0]}))
    )
    assert ok["status"] in {STATUS_OK, "deferred"}
    unknown = json.loads(
        broker.handle(name="set_pose", call_id="c2", arguments='{"name": "return_to_safe_pose"}')
    )
    assert unknown["status"] == STATUS_REJECTED

    # The load-bearing half: ``head_nod`` IS a real catalog skill and IS a legal
    # gesture, so the supervisor approves the run_pose call. Only the broker's
    # own "kind must literally be pose" rule refuses it — without that rule a
    # hosted set_pose would reach the trajectory channel.
    assert "head_nod" not in poses
    trajectory = json.loads(
        broker.handle(name="set_pose", call_id="c3", arguments='{"name": "head_nod"}')
    )
    assert trajectory["status"] == STATUS_REJECTED, (
        "set_pose must refuse a trajectory skill even though run_pose validates it"
    )
    assert wired.agent.safety.validate(ToolCall("run_pose", {"name": "head_nod"})).accepted is True


def test_navigate_to_admits_a_mission_only_through_the_router(wired) -> None:
    broker = wired.realtime_broker
    _observe(wired)
    result = json.loads(
        broker.handle(name="navigate_to", call_id="c1", arguments='{"place": "the sidewalk"}')
    )
    assert result["status"] == STATUS_OK, result
    assert result["directive"] == "go to the sidewalk"
    route = wired.realtime_snapshot()["last_route"]
    assert route["route"] == "direct_skill"
    assert route["rule"] == "navigation_directive"
    assert route["turn_id"].startswith("turn-realtime-")
    assert route["directive"] == "go to the sidewalk"
    assert wired.agent.last_intent_frame is None, (
        "a hosted tool call must not masquerade as the local agent's last typed turn"
    )
    assert wired.agent.last_reasoning_source == "local_plan_sketch"
    tasks = wired.task_executive.snapshot()["tasks"]
    assert tasks, "a navigation mission must exist in the executive"


def test_the_navigate_detail_is_structured_not_the_legacy_ack(wired) -> None:
    """Card R4-lite, task_1 — Defect C.

    ``detail`` is what the MODEL reads and then says out loud. It used to be
    whatever sentence the local admission path returned ("Okay—I'll navigate
    toward … safely."), the last survival of the legacy reply template on the
    realtime path. The model needs the fact, not the robot's script — and the
    admission reply is kept alongside so the record loses nothing.
    """

    broker = wired.realtime_broker
    _observe(wired)
    result = json.loads(
        broker.handle(name="navigate_to", call_id="c1", arguments='{"place": "the sidewalk"}')
    )

    # Card R15 sharpened R4-lite's fact into a TENSED fact: "mission accepted"
    # never said whether the robot was walking yet.
    assert result["detail"] == "started: the robot is walking to the sidewalk"
    assert "Okay" not in result["detail"], "the legacy ack template must not reach the model"
    assert result["admitted"], "the admission reply must still be on the record"
    assert result["place"] == "the sidewalk"


@pytest.mark.parametrize(
    "place",
    [
        "here",  # the navigation grammar excludes deictic destinations outright
        "the sidewalk and then sit",  # a compound must never compile as a label
        "forward",  # a direction is not a destination
    ],
)
def test_navigate_to_refuses_what_the_router_does_not_call_a_navigation(wired, place: str) -> None:
    """Only ``direct_skill``/``navigation_directive`` proceeds. Nothing else."""

    broker = wired.realtime_broker
    _observe(wired)
    result = json.loads(
        broker.handle(name="navigate_to", call_id="c1", arguments=json.dumps({"place": place}))
    )
    assert result["status"] == STATUS_REJECTED
    assert "router rule" in result["detail"]
    assert wired.task_executive.snapshot()["tasks"] == []


def test_navigate_to_grants_exactly_what_a_typed_sentence_grants(wired) -> None:
    """Authority parity, unchanged as a RULE and inverted as an outcome — card R20.

    R10 wrote this test to say: whatever the typed panel grants, the broker
    grants, and nothing more. It demonstrated that with "go to narnia", which
    both lanes admitted and which then failed honestly at grounding.

    ``voice_corpus_v1/live_run_1`` §d measured what "failed honestly at
    grounding" actually looked like when spoken to the robot: **"Okay—I'll go
    wait near narnia safely."** and 4.25 s of rotate-scan for a place that
    cannot exist. So R20 changed the shared answer — ``navigation.goals.
    admit_navigation_place``, asked by BOTH lanes through
    ``RobotRuntime._place_admission`` — and both now refuse.

    The rule this test exists for is therefore intact and is what is asserted:
    the two lanes agree. The broker did not grow a private grammar; the grammar
    they share learned to ask whether the noun resolves.
    """

    broker = wired.realtime_broker
    _observe(wired)
    result = json.loads(
        broker.handle(name="navigate_to", call_id="c1", arguments='{"place": "narnia"}')
    )
    typed = wired.handle_text("go to narnia")

    assert result["status"] == STATUS_REJECTED
    assert "narnia" in result["detail"]
    assert "narnia" in typed and "don't know" in typed
    # Neither lane reached the router: an unresolvable noun is not a question
    # about grammar, so there is nothing for the router to arbitrate.
    assert wired.realtime_snapshot()["last_route"] is None
    assert wired.task_executive.snapshot()["tasks"] == []


def test_each_router_call_gets_a_fresh_turn_id(wired) -> None:
    broker = wired.realtime_broker
    _observe(wired)
    first = json.loads(
        broker.handle(name="navigate_to", call_id="c1", arguments='{"place": "the sidewalk"}')
    )
    assert first["status"] == STATUS_OK
    first_turn = wired.realtime_snapshot()["last_route"]["turn_id"]
    broker.handle(name="navigate_to", call_id="c2", arguments='{"place": "the lamppost"}')
    assert wired.realtime_snapshot()["last_route"]["turn_id"] != first_turn


def test_the_snapshot_reports_the_lane_broker_and_driver(wired) -> None:
    state = wired.snapshot()["realtime"]
    assert state["constructed"] is True
    assert state["mode"] == "text"
    assert state["lane"]["tools_enabled"] is True
    assert state["broker"]["tools"] == list(BROKER_TOOLS)
    assert state["driver"]["running"] is False
    assert state["spend_usd"] == 0.0


# ==================================================== card R10: the tool surface
#
# The bench (``csbench/reports/bench_navmodel.md``) measured what the hole cost:
# with no orbit/follow tool the mini tier fabricated ``navigate_to("with owner")``
# / ``("run route")`` / ``("run path")`` 5/6, and realtime-mini FALSELY denied the
# ability ("I can't do a full circle around you with the controls I have right
# now") for a skill the ingress can actually run. These pin that the surface now
# matches the body — and that it does so through the EXISTING admission chain.


def test_the_two_new_tools_are_declared_and_commit_the_body() -> None:
    assert TOOL_CIRCLE_OWNER in BROKER_TOOLS
    assert TOOL_FOLLOW_OWNER in BROKER_TOOLS
    # Motion tools, so the one-authority-per-utterance dedupe covers them.
    assert {TOOL_CIRCLE_OWNER, TOOL_FOLLOW_OWNER} <= MOTION_TOOLS
    names = {spec["name"] for spec in build_tool_specs()}
    assert {TOOL_CIRCLE_OWNER, TOOL_FOLLOW_OWNER} <= names


def test_circle_owner_goes_through_the_supervisors_existing_orbit_arm() -> None:
    """No new authority: the same ToolCall a typed circle already validates."""

    broker, doors = _broker()
    result = _answer(broker, "circle_owner", '{"direction": "clockwise", "size": "wide"}')

    assert result["status"] == STATUS_OK
    call = doors.validated[-1]
    assert call.name == "run_spatial_behavior"
    assert call.arguments == {
        "behavior": "orbit_owner",
        "direction": "clockwise",
        "size": "wide",
        "revolutions": 1.0,
    }
    assert doors.orbits == [("clockwise", "wide", 1.0)]


def test_follow_owner_goes_through_the_supervisors_existing_follow_arm() -> None:
    broker, doors = _broker()
    result = _answer(broker, "follow_owner", '{"pace": "run"}')

    assert result["status"] == STATUS_OK
    assert doors.validated[-1].name == "set_behavior"
    assert doors.validated[-1].arguments == {"mode": "follow"}
    assert doors.follows == ["run"]


def test_follow_owner_never_claims_a_pace_the_body_did_not_take() -> None:
    """Bench B2: the model said "I'm matching your slower pace" while the
    injected gait was still RUN. A carried pace must come back as carried."""

    broker, _doors = _broker()
    result = _answer(broker, "follow_owner", '{"pace": "run"}')
    assert result["pace"] == "run"
    assert result["pace_applied"] is False
    assert "has not changed speed" in result["pace_note"]


def test_junk_enum_values_become_the_default_and_never_reach_a_door_raw() -> None:
    broker, doors = _broker()
    _answer(broker, "circle_owner", '{"direction": "widdershins", "size": "enormous"}')
    _answer(broker, "follow_owner", '{"pace": "ludicrous"}')
    assert doors.orbits == [("counterclockwise", "normal", 1.0)]
    assert doors.follows == ["walk"]


def test_revolutions_are_clamped_into_the_supervisors_own_window() -> None:
    broker, doors = _broker()
    _answer(broker, "circle_owner", '{"revolutions": 99}')
    _answer(broker, "circle_owner", '{"revolutions": 0.01}')
    _answer(broker, "circle_owner", '{"revolutions": "lots"}')
    assert [row[2] for row in doors.orbits] == [1.0, 0.25, 1.0]


def test_an_infeasible_orbit_is_refused_with_the_validators_own_sentence() -> None:
    """The refusal must come from geometry, not from the model guessing."""

    broker, doors = _broker()
    doors.orbit_error = ValueError(
        "I can't walk around you here — a planter is in the way; "
        "there isn't room on your left."
    )
    result = _answer(broker, "circle_owner", "{}")
    assert result["status"] == STATUS_REJECTED
    assert "isn't room on your left" in result["detail"]


def test_a_latched_estop_refuses_both_new_tools_for_the_supervisors_reason() -> None:
    broker, doors = _broker(allow=False, refusal="Motion is disabled by emergency stop")
    for tool in (TOOL_CIRCLE_OWNER, TOOL_FOLLOW_OWNER):
        result = _answer(broker, tool, "{}")
        assert result["status"] == STATUS_REJECTED
        assert result["detail"] == "not started: Motion is disabled by emergency stop"
    assert doors.orbits == [] and doors.follows == []


def test_the_ingress_dedupe_covers_the_new_tools_too() -> None:
    """One utterance, one authority — including for a circle."""

    broker, doors = _broker()
    broker.note_ingress(
        RealtimeTranscriptOutcome(
            kind="spatial",
            name="orbit",
            transcript="circle around me",
            reply="Okay—I'll walk a circle around you.",
            executed=True,
        )
    )
    result = _answer(broker, "circle_owner", "{}")
    assert result["status"] == STATUS_DROPPED
    assert doors.orbits == []


def test_an_unwired_door_refuses_honestly_instead_of_pretending() -> None:
    from parcel_robot.realtime.tool_broker import ToolDoors

    doors = _Doors()
    bare = ToolDoors(
        validate=doors.validate,
        status=doors.status,
        recall=doors.recall,
        gesture=doors.gesture,
        pose=doors.pose,
        navigate=doors.navigate,
    )
    result = json.loads(
        RealtimeToolBroker(bare).handle(name="circle_owner", call_id="c1", arguments="{}")
    )
    assert result["status"] == STATUS_REJECTED
    assert "not wired" in result["detail"] or "has not wired" in result["detail"]


# --------------------------------------------------------- the junk-place gate
@pytest.mark.parametrize(
    "place",
    ["with owner", "run route", "run path"],  # verbatim from bench cell A4
)
def test_the_exact_fabrications_the_bench_measured_are_refused(place: str) -> None:
    broker, doors = _broker()
    result = _answer(broker, "navigate_to", json.dumps({"place": place}))

    assert result["status"] == STATUS_REJECTED
    assert result["reason"] == "not_a_place_name"
    assert doors.navigations == [], "the junk directive must never reach the router"
    # And the refusal is USEFUL: it names real places and the right tools.
    assert result["valid_places"], "a refusal that names nothing teaches nothing"
    assert "follow_owner" in result["detail"]
    assert "circle_owner" in result["detail"]


def test_a_real_place_is_still_admitted_with_its_relation_hint() -> None:
    broker, doors = _broker()
    result = _answer(
        broker, "navigate_to", '{"place": "the sidewalk", "relation": "inside"}'
    )
    assert result["status"] == STATUS_OK
    assert result["relation_hint"] == "inside"
    assert doors.relations == ["inside"]


def test_a_nonsense_relation_hint_is_dropped_before_the_door() -> None:
    broker, doors = _broker()
    result = _answer(
        broker, "navigate_to", '{"place": "the sidewalk", "relation": "on top of"}'
    )
    assert result["status"] == STATUS_OK
    assert doors.relations == [""], "junk must not travel as if it were a hint"


def test_an_unheard_of_but_well_formed_place_keeps_authority_parity() -> None:
    """The BROKER still does not refuse an unheard-of noun — and still must not.

    Card R20 refuses "narnia", but one layer down: in
    ``navigation.goals.admit_navigation_place``, behind the runtime's navigate
    door, which is the layer the typed panel shares. This test drives the broker
    against a fake door and therefore pins the half R20 deliberately did NOT
    change — ``validate_place`` judges argument SHAPES and nothing else, so the
    hosted lane never acquires a place grammar of its own. The end-to-end
    refusal is ``test_navigate_to_grants_exactly_what_a_typed_sentence_grants``
    and ``tests/test_unknown_place_admission.py``.
    """

    broker, doors = _broker()
    result = _answer(broker, "navigate_to", '{"place": "narnia"}')
    assert result["status"] == STATUS_OK
    assert doors.navigations == ["narnia"]


def test_a_multi_word_place_with_an_ordinary_adjective_is_not_junk() -> None:
    broker, doors = _broker()
    result = _answer(broker, "navigate_to", '{"place": "the big oak bench"}')
    assert result["status"] == STATUS_OK
    assert doors.navigations == ["the big oak bench"]


def test_every_orbit_argument_combination_renders_a_directive_the_grammar_PARSES() -> None:
    """The gap the live proof found, closed.

    ``circle_owner`` renders text for the deterministic router, exactly as
    ``navigate_to`` does. The broker's enums and the spatial grammar's
    alternation were each individually correct and disagreed on ONE word: the
    grammar has no literal "normal" (a circle with no adjective is the normal
    one), so the default request rendered "walk in a normal counterclockwise
    circle around me", matched nothing, and the router answered
    ``ambiguous_physical_request`` — the brand-new tool refusing every default
    call. No unit test could see it because neither side was wrong alone.

    This walks the FULL cross product of the declared enums and asserts the
    rendered sentence round-trips through ``parse_spatial_intent`` back to the
    arguments that produced it.
    """

    from parcel_robot.navigation.spatial import parse_spatial_intent

    for direction in ORBIT_DIRECTIONS:
        for size in ORBIT_SIZES:
            adjective = f"{size} " if size and size != "normal" else ""
            directive = f"walk in a {adjective}{direction} circle around me"
            intent = parse_spatial_intent(directive)
            assert intent is not None, f"grammar does not parse {directive!r}"
            assert intent.behavior == "orbit_owner"
            assert intent.direction == direction
            assert intent.size == size, f"{directive!r} -> size {intent.size!r}"
