"""Card R11, design point 5: a state update may never start motion.

THE DEFECT THIS FILE EXISTS FOR, VERBATIM FROM THE BENCH
--------------------------------------------------------
``bench_navmodel.md`` §4, finding C1: five telemetry items injected into the
model in forced-response mode, three trials — and **2 of 3 trials fired a
spurious** ``navigate_to("picnic spot by the big oak")`` **off the FIRST
telemetry item**. No owner said anything. No utterance existed. The broker's
utterance-scoped dedupe (card R3, "one authority per utterance") therefore could
not see it at all: it drops a second authority for one SENTENCE, and here there
was no sentence — the robot told itself something and drove off.

The gate is two halves in two files, and BOTH directions are pinned here:

* the lane TAGS the response it is about to ask for. ``narrate_event`` posts a
  ``system`` item and asks for a reply; that reply is ``system``-initiated.
  Anything the owner typed or spoke is ``owner``-initiated.
* the broker REFUSES the motion classes when the tag says ``system``, with a
  structured refusal, before it parses arguments and before it touches a door.

The tests that matter most to an auditor are the ones asserting the negative
direction: an owner's request is NOT refused, and the read-only tools still work
inside a system-initiated reply, because a gate that just says no to everything
would pass a one-sided test file and break the product.
"""

from __future__ import annotations

import json

import pytest

from parcel_robot.models import ToolCall, ToolResult
from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    function_call,
    handshake,
    response_done,
    session_created,
)
from parcel_robot.realtime.lane import (
    RESPONSE_FROM_OWNER,
    RESPONSE_FROM_SYSTEM,
    SYSTEM_INITIATED_UNGATED_OUTPUT,
    RealtimeLane,
)
from parcel_robot.realtime.protocol import ResponseDone
from parcel_robot.realtime.tool_broker import (
    MOTION_TOOLS,
    REFUSAL_SYSTEM_INITIATED_MOTION,
    STATUS_OK,
    STATUS_REJECTED,
    TOOL_CIRCLE_OWNER,
    TOOL_FOLLOW_OWNER,
    TOOL_GET_STATUS,
    TOOL_NAVIGATE_TO,
    TOOL_PLAY_GESTURE,
    TOOL_RECALL_MEMORY,
    TOOL_ROAM,
    TOOL_SET_POSE,
    RealtimeToolBroker,
    ToolDoors,
)
from parcel_robot.realtime.transport import transport_pair

#: The arguments each motion tool needs to be otherwise perfectly admissible.
#: The point of the gate is that a WELL-FORMED request is refused, so nothing
#: here may be refusable for any other reason.
GOOD_ARGUMENTS = {
    TOOL_NAVIGATE_TO: '{"place": "the sidewalk"}',
    TOOL_SET_POSE: '{"name": "sit"}',
    TOOL_PLAY_GESTURE: '{"name": "paw_wave"}',
    TOOL_CIRCLE_OWNER: '{"direction": "clockwise", "size": "normal", "revolutions": 1.0}',
    TOOL_FOLLOW_OWNER: '{"pace": "walk"}',
    # Card ROAM-1. The ninth tool. Its verdict on this gate is the same one
    # every travel tool gets and is written down rather than inherited: a roam
    # the robot started because it talked to itself is bench finding C1 with a
    # longer fuse.
    TOOL_ROAM: '{"action": "start", "minutes": 2}',
}


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
    """Records every door the broker touches. A touched door is a moved body."""

    def __init__(self) -> None:
        self.touched: list[tuple[str, tuple]] = []
        self.validated: list[ToolCall] = []
        self.dispatches = 0

    def validate(self, call: ToolCall) -> ToolResult:
        self.validated.append(call)
        return ToolResult(call.name, True, "approved")

    def status(self) -> dict[str, object]:
        return {"emergency_stopped": False, "battery_percent": 88.0}

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
        return "Okay—I'll head for the sidewalk."

    def places(self) -> tuple[str, ...]:
        return ("sidewalk", "lamppost", "bench")

    def orbit(self, direction: str, size: str, revolutions: float) -> str:
        self.touched.append(("orbit", (direction, size, revolutions)))
        return "Okay—I'll circle you."

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


def _broker() -> tuple[RealtimeToolBroker, _Doors]:
    doors = _Doors()
    return RealtimeToolBroker(doors.as_doors()), doors


def _answer(broker: RealtimeToolBroker, name: str, arguments: str = "{}") -> dict:
    return json.loads(broker.handle(name=name, call_id=f"call_{name}", arguments=arguments))


# ============================================================= the broker half
@pytest.mark.parametrize("tool", sorted(MOTION_TOOLS))
def test_a_system_initiated_response_may_not_move_the_body(tool: str) -> None:
    """C1, refused. The request is well-formed; the PROVENANCE is the problem."""

    broker, doors = _broker()
    broker.note_response_provenance(RESPONSE_FROM_SYSTEM)

    result = _answer(broker, tool, GOOD_ARGUMENTS[tool])

    assert result["status"] == STATUS_REJECTED
    assert result["refusal"] == REFUSAL_SYSTEM_INITIATED_MOTION
    assert result["provenance"] == RESPONSE_FROM_SYSTEM
    assert doors.touched == [], "a door was touched by a reply the owner never asked for"
    assert doors.validated == [], "the gate must sit AHEAD of the supervisor, not behind it"
    assert doors.dispatches == 0
    assert broker.system_initiated_motion_refusals == 1


@pytest.mark.parametrize("tool", sorted(MOTION_TOOLS))
def test_the_owners_own_request_is_not_refused(tool: str) -> None:
    """The negative direction. A gate that refused everything would be useless."""

    broker, doors = _broker()
    broker.note_response_provenance(RESPONSE_FROM_OWNER)

    result = _answer(broker, tool, GOOD_ARGUMENTS[tool])

    assert result["status"] == STATUS_OK, result
    assert doors.touched, "the owner asked and nothing happened"
    assert broker.system_initiated_motion_refusals == 0


@pytest.mark.parametrize("tool", [TOOL_GET_STATUS, TOOL_RECALL_MEMORY])
def test_reading_is_always_allowed_however_the_response_started(tool: str) -> None:
    """Answering "what is your state" is not a second authority over the body."""

    broker, _ = _broker()
    broker.note_response_provenance(RESPONSE_FROM_SYSTEM)

    result = _answer(broker, tool, '{"query": "the park"}')

    assert result["status"] == STATUS_OK


def test_the_default_provenance_is_the_owner_because_that_is_what_it_always_was() -> None:
    """A broker nobody tagged behaves exactly as it did before this card."""

    broker, doors = _broker()
    assert _answer(broker, TOOL_NAVIGATE_TO, GOOD_ARGUMENTS[TOOL_NAVIGATE_TO])["status"] == (
        STATUS_OK
    )
    assert doors.touched
    assert broker.snapshot()["response_provenance"] == RESPONSE_FROM_OWNER


@pytest.mark.parametrize("tag", ["", "SYSTEM", "narration", "robot", None, 7])
def test_a_provenance_this_broker_does_not_recognise_fails_closed(tag: object) -> None:
    """Only the literal word ``owner`` opens the body. Everything else is system."""

    broker, doors = _broker()
    broker.note_response_provenance(tag)  # type: ignore[arg-type]

    result = _answer(broker, TOOL_NAVIGATE_TO, GOOD_ARGUMENTS[TOOL_NAVIGATE_TO])

    assert result["status"] == STATUS_REJECTED
    assert doors.touched == []


def test_the_tag_is_per_call_and_never_sticks() -> None:
    broker, doors = _broker()
    broker.note_response_provenance(RESPONSE_FROM_SYSTEM)
    assert _answer(broker, TOOL_SET_POSE, '{"name": "sit"}')["status"] == STATUS_REJECTED
    broker.note_response_provenance(RESPONSE_FROM_OWNER)
    assert _answer(broker, TOOL_SET_POSE, '{"name": "sit"}')["status"] == STATUS_OK
    assert [name for name, _ in doors.touched] == ["pose"]


def test_the_refusal_tells_the_model_the_rule_so_it_can_say_something_true() -> None:
    """Cell B: the model narrates whatever it is given. Give it the reason."""

    broker, _ = _broker()
    broker.note_response_provenance(RESPONSE_FROM_SYSTEM)

    detail = _answer(broker, TOOL_NAVIGATE_TO, GOOD_ARGUMENTS[TOOL_NAVIGATE_TO])["detail"]

    assert "owner" in detail
    assert "status update" in detail


# =============================================================== the lane half
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

    def outputs(self) -> list[dict]:
        transport = self.lane.transport
        assert transport is not None
        return [
            frame["item"]
            for frame in transport.sent  # type: ignore[attr-defined]
            if frame.get("type") == "conversation.item.create"
            and isinstance(frame.get("item"), dict)
            and frame["item"].get("type") == "function_call_output"
        ]


def _tool_call_on(trigger: str, *, name: str, arguments: str, response_id: str) -> list[Step]:
    """A provider that answers ONE client frame type with a function call."""

    return [
        Step("session.update", (session_created("sess_fake_1"),), label="handshake"),
        Step(
            trigger,
            (function_call("call_1", name, arguments), response_done(response_id)),
            label="tool_call",
        ),
    ]


def test_a_narration_tags_the_reply_it_asks_for_as_the_robots_own() -> None:
    broker, doors = _broker()
    rig = _Rig(handshake(), tool_handler=broker)
    rig.open()
    assert rig.lane.snapshot()["response_provenance"] == RESPONSE_FROM_OWNER

    assert rig.lane.narrate_event("The robot's navigation system reports it arrived.") is True

    assert rig.lane.snapshot()["response_provenance"] == RESPONSE_FROM_SYSTEM
    assert rig.lane.snapshot()["system_initiated_responses"] == 1
    assert doors.touched == []


def test_end_to_end_a_narration_that_makes_the_model_navigate_is_refused() -> None:
    """The whole gate, on the wire: item up, reply asked for, tool call refused.

    This is bench finding C1 replayed against the shipping stack — the provider
    answers a state item with ``navigate_to``, exactly as gpt-5-mini did in 2/3
    forced-response trials, and the body does not move.
    """

    broker, doors = _broker()
    rig = _Rig(
        _tool_call_on(
            "response.create",
            name=TOOL_NAVIGATE_TO,
            arguments='{"place": "picnic spot by the big oak"}',
            response_id="resp_system",
        ),
        tool_handler=broker,
    )
    rig.open()

    rig.lane.narrate_event("The robot's navigation system reports it is holding position.")
    rig.step()

    outputs = rig.outputs()
    assert len(outputs) == 1, "every function_call is answered exactly once"
    answer = json.loads(outputs[0]["output"])
    assert answer["status"] == STATUS_REJECTED
    assert answer["refusal"] == REFUSAL_SYSTEM_INITIATED_MOTION
    assert doors.touched == [], "a telemetry item drove the robot to a picnic spot"
    assert rig.lane.snapshot()["system_initiated_tool_calls"] == 1
    assert broker.system_initiated_motion_refusals == 1


def test_end_to_end_the_owners_typed_request_still_moves_the_body() -> None:
    """The same wire, the same tool, the other provenance."""

    broker, doors = _broker()
    rig = _Rig(
        _tool_call_on(
            "response.create",
            name=TOOL_NAVIGATE_TO,
            arguments='{"place": "the sidewalk"}',
            response_id="resp_owner",
        ),
        tool_handler=broker,
    )
    rig.open()

    rig.lane.send_text("go to the sidewalk")
    rig.step()

    answer = json.loads(rig.outputs()[0]["output"])
    assert answer["status"] == STATUS_OK, answer
    assert doors.touched == [("navigate", ("the sidewalk", ""))]
    assert rig.lane.snapshot()["system_initiated_tool_calls"] == 0


def test_the_owner_speaking_takes_the_tag_back_from_a_narration() -> None:
    """Server VAD heard the owner, so the next reply is theirs and may move.

    The lane sets this at ``_arm_voice_turn`` rather than at the transcript,
    because the transcript can arrive AFTER the response has already started.
    """

    broker, _ = _broker()
    rig = _Rig(handshake(), tool_handler=broker)
    rig.open()
    rig.lane.narrate_event("The robot reports it is waiting.")
    assert rig.lane.snapshot()["response_provenance"] == RESPONSE_FROM_SYSTEM

    rig.lane._arm_voice_turn("the owner spoke")

    assert rig.lane.snapshot()["response_provenance"] == RESPONSE_FROM_OWNER


def test_the_tag_survives_the_beat_and_clears_when_the_last_response_completes() -> None:
    """A tool turn has TWO responses in flight; the beat inherits the first's tag."""

    broker, _ = _broker()
    rig = _Rig(
        _tool_call_on(
            "response.create",
            name=TOOL_SET_POSE,
            arguments='{"name": "sit"}',
            response_id="resp_system",
        ),
        tool_handler=broker,
    )
    rig.open()
    rig.lane.narrate_event("The robot reports it arrived.")
    rig.step()
    # The refusal is not `ok`, so the lane asks for a beat: two responses were
    # created and only one `response.done` has arrived.
    assert rig.lane.snapshot()["response_provenance"] == RESPONSE_FROM_SYSTEM

    # The beat comes back too. Now nothing is outstanding, and the next thing
    # that happens on this session is the owner's.
    rig.lane._on_response_done(ResponseDone(response_id="resp_system_beat"))

    assert rig.lane.snapshot()["response_provenance"] == RESPONSE_FROM_OWNER


def test_a_handler_that_cannot_be_told_the_provenance_is_refused_by_the_lane() -> None:
    """The fail-closed arm: no seam, no motion.

    A tool handler with no ``note_response_provenance`` cannot enforce the gate.
    Rather than trust it, the lane refuses the call itself — but ONLY inside a
    system-initiated response, so a legacy handler answering the owner is
    exactly what it has always been.
    """

    class _Legacy:
        def __init__(self) -> None:
            self.handled: list[str] = []

        def session_events(self):
            return ()

        def handle(self, *, name, call_id, arguments):
            self.handled.append(name)
            return json.dumps({"status": STATUS_OK, "tool": name, "detail": "did it"})

    legacy = _Legacy()
    rig = _Rig(
        _tool_call_on(
            "response.create",
            name=TOOL_NAVIGATE_TO,
            arguments='{"place": "anywhere"}',
            response_id="resp_system",
        ),
        tool_handler=legacy,
    )
    rig.open()
    rig.lane.narrate_event("The robot reports something.")
    rig.step()

    assert legacy.handled == [], "an ungated handler was handed a system-initiated call"
    assert rig.outputs()[0]["output"] == SYSTEM_INITIATED_UNGATED_OUTPUT
    assert rig.lane.refused_tool_calls == [TOOL_NAVIGATE_TO]


def test_a_legacy_handler_still_answers_the_owner() -> None:
    class _Legacy:
        def __init__(self) -> None:
            self.handled: list[str] = []

        def session_events(self):
            return ()

        def handle(self, *, name, call_id, arguments):
            self.handled.append(name)
            return json.dumps({"status": STATUS_OK, "tool": name, "detail": "did it"})

    legacy = _Legacy()
    rig = _Rig(
        _tool_call_on(
            "response.create",
            name=TOOL_NAVIGATE_TO,
            arguments='{"place": "the sidewalk"}',
            response_id="resp_owner",
        ),
        tool_handler=legacy,
    )
    rig.open()
    rig.lane.send_text("go to the sidewalk")
    rig.step()

    assert legacy.handled == [TOOL_NAVIGATE_TO]
