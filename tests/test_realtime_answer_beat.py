"""Card R19 — the silent companion. The beat that carries the ANSWER.

WHY THIS FILE EXISTS, in the owner's own words and the run's own counters.

On 2026-08-20 the 52-query voice corpus was spoken to the live robot for the
first time (``evals/20260820/voice_corpus_v1/live_run_1``). From 14:27:34 to
14:28:18 the owner asked nine consecutive questions and the dog produced three
sentences, all of them promises to check::

    14:27:49  owner  How's your battery?          → get_status executed
    14:27:57  robot  Let me think through what I can safely check and describe.
    14:27:57  robot  Let me check what I can safely report and then we'll go from there.
    14:28:07  owner  So, what do you remember about me?
    14:28:08  robot  Nice question—let me think about what I can pull from past chats.
              ~      recall_memory executed
    14:28:18  robot   let me take a [interrupted after 0 ms]

``get_status`` fetched 90.0% battery. ``recall_memory`` fetched the memory.
Neither number nor memory was ever spoken.

The scoring blamed R6's suppression policy. The lane's own counters refute
that: ``tool_beats_requested=10, tool_beats_suppressed=8`` over 18 brokered
calls decomposes exactly once, and in that decomposition **both answer tools
had their beat REQUESTED**. So this file pins four separate claims, which are
the four mechanisms R19_STATUS §0 root-caused:

A. an ANSWER beat is told to say the answer (:data:`ANSWER_BEAT_RULE`);
B. filler is not speech — "let me check" may not buy the turn's silence;
C. a beat the PROVIDER refused (``conversation_already_has_active_response``,
   which ate three of the run's four e-stop refusals) is asked for again;
D. an activity that expired undelivered is narrated instead of vanishing.

R6's two directions, R11's bands and R15's tense contract are the frame this
lives inside; every one of their tests is still green and unmodified.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from parcel_robot.core.activities import ActivityContext
from parcel_robot.models import ActionProposal
from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    error_frame,
    function_call,
    handshake,
    response_done,
    transcript_delta,
    transcript_done,
)
from parcel_robot.realtime.lane import (
    ANSWER_BEAT_RULE,
    CODE_RESPONSE_ALREADY_ACTIVE,
    DEFAULT_ANSWER_TOOLS,
    DEFAULT_RECEIPT_TOOLS,
    RESULT_BEAT_RULE,
    RealtimeLane,
    clause_is_filler,
    speech_is_substantive,
)
from parcel_robot.realtime.tool_broker import (
    ANSWER_RESULT_KEY,
    ANSWER_TOOLS,
    BROKER_TOOLS,
    STATUS_DEFERRED,
    STATUS_DROPPED,
    STATUS_OK,
    STATUS_REJECTED,
    RealtimeToolBroker,
    ToolDoors,
)
from parcel_robot.realtime.transport import transport_pair
from parcel_robot.runtime import ACTIVITY_STATUS_EXPIRED

STALL_TIMEOUT_S = 4.0

#: The announcement R6 measured live and built its rule around. It names the
#: destination and commits to the act, so the owner learned something from it —
#: which is why R19 leaves R6's suppression of this exact turn intact.
SUBSTANTIVE_ANNOUNCEMENT = "Okay, let's head over to the sidewalk."

#: What ``gpt-realtime-2.1-mini`` actually said before the tool call in
#: live_run_1, verbatim from ``ledger.json`` id 2737.
FILLER_ANNOUNCEMENT = "Okay, let me check how to get you there."


# ---------------------------------------------------------------- the rig
class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Sink:
    def begin_utterance(self) -> None:
        return None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del chunk, token

    def interrupt(self) -> None:
        return None


class _ScriptedBroker:
    """A broker seam that answers with whatever JSON the test names."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[str] = []

    def session_events(self) -> tuple:
        return ()

    def handle(self, *, name: str, call_id: str, arguments: str) -> str:
        del call_id, arguments
        self.calls.append(name)
        return self.output


class _Rig:
    """A lane plus one scripted server per connection. Card R6's shape."""

    def __init__(self, script: list[Step], **lane_kwargs: object) -> None:
        self.clock = _Clock()
        self.script = script
        self.transports: list[object] = []
        self.servers: list[FakeRealtimeServer] = []
        counter = {"n": 0}

        def _session_id() -> str:
            counter["n"] += 1
            return f"rt_session_{counter['n']}"

        self.lane = RealtimeLane(
            config=RealtimeConfig(enabled=True, stall_timeout_s=STALL_TIMEOUT_S, source="test"),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=_Sink(),
            clock=self.clock,
            session_id_factory=_session_id,
            sleep=lambda _delay: None,
            jitter=lambda: 1.0,
            **lane_kwargs,  # type: ignore[arg-type]
        )

    def _factory(self) -> object:
        lane_end, server_end = transport_pair(clock=self.clock)
        self.transports.append(lane_end)
        self.servers.append(
            FakeRealtimeServer(transport=server_end, script=list(self.script), clock=self.clock)
        )
        return lane_end

    @property
    def server(self) -> FakeRealtimeServer:
        return self.servers[-1]

    def settle(self, rounds: int = 4) -> None:
        for _ in range(rounds):
            self.server.pump()
            self.lane.pump()

    def open(self) -> None:
        self.lane.open_session(handshake_token="tok", mic_gesture=True)
        self.settle()

    def turn(self, text: str) -> None:
        self.lane.send_text(text)
        self.settle()


def _creates(rig: _Rig, *, index: int = -1) -> list[dict]:
    return [
        dict(frame)
        for frame in rig.transports[index].sent  # type: ignore[attr-defined]
        if frame.get("type") == "response.create"
    ]


def _beats(rig: _Rig) -> list[dict]:
    """``response.create`` frames after the owner's own — i.e. the beats."""

    return _creates(rig)[1:]


def _tool_turn(
    *,
    announcement: str | None = SUBSTANTIVE_ANNOUNCEMENT,
    tool: str = "navigate_to",
    arguments: str = '{"place": "the sidewalk"}',
    response_id: str = "resp_tool",
    close: bool = True,
) -> list[Step]:
    """R5's live shape: the announcement is CO-EMITTED with the call."""

    frames: list[dict] = []
    if announcement is not None:
        frames.append(transcript_delta(response_id, "item_say", announcement))
        frames.append(transcript_done(response_id, "item_say", announcement))
    frames.append(function_call("call_1", tool, arguments))
    if close:
        frames.append(response_done(response_id))
    return handshake() + [Step("response.create", tuple(frames), label="announced_tool_call")]


def _ok(tool: str, detail: str = "started: the robot is walking to the sidewalk") -> str:
    return json.dumps({"status": STATUS_OK, "tool": tool, "detail": detail})


# ==========================================================================
# Mechanism B — filler is not speech
# ==========================================================================
@pytest.mark.parametrize(
    "line",
    [
        "Okay, let me check how to get you there.",
        "Let me think through what I can safely check and describe.",
        "Let me check what I can safely report and then we’ll go from there.",
        "Nice question—let me think about what I can pull from past chats.",
        " let me take a",
        "Okay, let me see what my navigation can do—and we’ll see how far we can go.",
        "Okay, give me a moment to try that.",
        # R6's own live sessions, which is where the habit was first recorded.
        "Okay, let me see what I can do with that request.",
        "Alright, let me check where we can head together.",
        "Sure, one moment.",
        "Okay.",
        "Got it.",
        "",
    ],
)
def test_the_filler_the_robot_actually_said_is_not_an_answer(line: str) -> None:
    """Every one of these is a real sentence from a real session.

    Not invented phrasings: these are the lines ``gpt-realtime-2.1-mini``
    produced in live_run_1 and in R6's own live proofs. A rule that lets any of
    them stand in for the turn's answer is the rule that produced nine silent
    owner turns.
    """

    assert speech_is_substantive(line) is False


@pytest.mark.parametrize(
    "line",
    [
        SUBSTANTIVE_ANNOUNCEMENT,
        "Oh, that sounds kind of hectic. I can tell you’re feeling the crowd.",
        "That tie-dye top is awesome.",
        "The tallest building in New York City is One World Trade Center.",
        "It's at 90 percent.",
        "I'm walking to the bench now.",
    ],
)
def test_speech_that_told_the_owner_something_counts_as_speech(line: str) -> None:
    """The other direction, and the one that keeps R6's fix from being reverted.

    If everything is filler then every tool turn gets two beats again, which is
    the defect R6 exists to remove. ``"Okay, let's head over to the sidewalk."``
    names the destination and commits to the act.
    """

    assert speech_is_substantive(line) is True


def test_a_deferral_bolted_onto_real_content_is_still_real_content() -> None:
    """Filler is matched as a clause PREFIX, never anywhere inside the sentence."""

    assert clause_is_filler("let me check the map") is True
    assert clause_is_filler("the bench is clear, so let me check the map") is False
    assert speech_is_substantive("I can see the bench from here, so let me check.") is True


@pytest.mark.parametrize(
    ("line", "substantive"),
    [
        ("Sure, no problem.", False),
        ("Okay, fine.", False),
        ("Hmm, tricky.", False),
        ("Okay, the bench is clear.", True),
        ("Sure, it is at ninety percent.", True),
    ],
)
def test_a_two_word_remainder_is_an_acknowledgement_wearing_a_coat(
    line: str, substantive: bool
) -> None:
    """MIN_SUBSTANTIVE_WORDS, pinned on its own.

    The filler PREFIX list catches the deliberations; this catches what is left
    when a response is an acknowledgement plus a shrug. "Sure, no problem."
    tells the owner nothing about the battery they just asked about, and a rule
    that lets it stand in for the answer has the same hole as the one that let
    "let me check" do it. Two words is a shrug; three is a sentence, and the
    failure direction of being too strict here is one extra beat.
    """

    assert speech_is_substantive(line) is substantive


def test_a_filler_announcement_is_not_the_turns_answer() -> None:
    """MECHANISM B, as a frame count. The card's first required seed.

    live_run_1, ledger id 2737: the model said *"Okay, let me check how to get
    you there."*, the lane read it as the turn's beat, and the fact R15 had just
    moved into the broker result — *"started: the robot is walking to the
    sidewalk"* — was never spoken by anybody.
    """

    broker = _ScriptedBroker(_ok("navigate_to"))
    rig = _Rig(_tool_turn(announcement=FILLER_ANNOUNCEMENT), tool_handler=broker)
    rig.open()
    rig.turn("go to the sidewalk")

    assert broker.calls == ["navigate_to"]
    assert len(_beats(rig)) == 1, "a promise to check is not an answer; the beat must survive"
    assert rig.lane.snapshot()["tool_beats_suppressed"] == 0
    assert any("filler" in note for note in rig.lane.events), rig.lane.events[-3:]


def test_the_announcement_R6_measured_still_buys_its_silence() -> None:
    """R6's direction 1, unreverted. The regression the card asks to pin BOTH ways.

    R19 narrows R6's condition; it does not withdraw it. The turn R6 proved live
    — a substantive announcement, an ok receipt tool — is still exactly one beat,
    and this test failing means R19 has quietly turned every tool turn back into
    the two-beat shape R6 removed.
    """

    broker = _ScriptedBroker(_ok("navigate_to"))
    rig = _Rig(_tool_turn(), tool_handler=broker)
    rig.open()
    rig.turn("go to the sidewalk")

    assert _beats(rig) == []
    assert rig.lane.snapshot()["tool_beats_suppressed"] == 1
    assert rig.lane.snapshot()["tool_beats_requested"] == 0


# ==========================================================================
# Mechanism A — an answer tool is never suppressible, and is told to answer
# ==========================================================================
@pytest.mark.parametrize("tool", ["get_status", "recall_memory"])
def test_an_answer_tool_is_never_suppressed_even_when_named_a_receipt(tool: str) -> None:
    """The card's second required seed, and the property R6 only had by omission.

    R6 protected ``get_status``/``recall_memory`` by leaving them OUT of
    ``DEFAULT_RECEIPT_TOOLS`` — and then shipped a ``receipt_tools=``
    constructor argument that can put them back in. This test names them there
    deliberately, with a SUBSTANTIVE announcement so the filler gate cannot be
    what saves the beat, and requires the answer to be spoken anyway.

    The tool names are literals, not ``sorted(DEFAULT_ANSWER_TOOLS)``: a test
    parametrised from the constant it is guarding vanishes into a SKIP the
    moment somebody empties the constant, which is precisely the regression it
    exists to catch. The constant is asserted separately, below.
    """

    assert tool in DEFAULT_ANSWER_TOOLS, "an answer tool was dropped from the lane's set"
    broker = _ScriptedBroker(json.dumps({"status": STATUS_OK, "tool": tool, "detail": "90%"}))
    rig = _Rig(
        _tool_turn(tool=tool, arguments='{"query": "the willow"}'),
        tool_handler=broker,
        receipt_tools=[*DEFAULT_RECEIPT_TOOLS, tool],
    )
    rig.open()
    rig.turn("how's your battery")

    assert len(_beats(rig)) == 1, f"{tool}'s answer was swallowed by the receipt list"
    assert rig.lane.snapshot()["tool_beats_suppressed"] == 0
    assert any("IS the answer" in note for note in rig.lane.events), rig.lane.events[-3:]


def test_a_result_that_declares_itself_an_answer_is_never_suppressed() -> None:
    """The half that does not need the lane to know the tool surface at all.

    live_run_1 re-cut F3 as a MISSING perception tool. Whatever that tool ends
    up being called, the lane has never heard of it and the receipt list will
    not mention it — so the classification has to be able to travel inside the
    result. This is R6 Open risk 4, closed from the side that fails safe.
    """

    output = json.dumps(
        {"status": STATUS_OK, "tool": "describe_scene", ANSWER_RESULT_KEY: True, "detail": "a bench"}
    )
    broker = _ScriptedBroker(output)
    rig = _Rig(
        _tool_turn(tool="describe_scene", arguments="{}"),
        tool_handler=broker,
        receipt_tools=["describe_scene"],
    )
    rig.open()
    rig.turn("what do you see around you")

    assert len(_beats(rig)) == 1, "a result that said it was an answer was answered with silence"


def test_the_answer_beat_is_told_to_say_the_answer() -> None:
    """MECHANISM A. The beat fired in live_run_1 and still said "let me check".

    ``RESULT_BEAT_RULE`` asks for "one short spoken sentence about what actually
    came back" and spends its longest concrete clause on R15's activity tense,
    which an answer tool has none of. Nothing in it ever said *the owner asked a
    question and this is the answer — say the figure*.
    """

    broker = _ScriptedBroker(
        json.dumps({"status": STATUS_OK, "tool": "get_status", "detail": "battery 90.0%"})
    )
    rig = _Rig(_tool_turn(tool="get_status", arguments="{}"), tool_handler=broker)
    rig.open()
    rig.turn("how's your battery")

    beats = _beats(rig)
    assert len(beats) == 1
    instructions = beats[0]["response"]["instructions"]
    # R6's property, unchanged: the persona and every guardrail still ride it.
    assert instructions.startswith(rig.lane.instructions)
    # R15's property, unchanged: the tense rule is still there.
    assert RESULT_BEAT_RULE in instructions
    # R19's addition, and it is an ADDITION.
    assert ANSWER_BEAT_RULE in instructions


def test_a_receipt_beat_is_not_told_to_answer_a_question_nobody_asked() -> None:
    """The answer rule is scoped, not global.

    A ``navigate_to`` receipt is not an answer, and telling the model to "say
    the figures in the result" for one would invite it to read a route id out
    loud. The two rules are separate objects for this reason.
    """

    broker = _ScriptedBroker(_ok("play_gesture", detail="waiting: Deferred paw_wave"))
    rig = _Rig(
        _tool_turn(announcement=None, tool="play_gesture", arguments='{"name": "paw_wave"}'),
        tool_handler=broker,
    )
    rig.open()
    rig.turn("wave at me")

    instructions = _beats(rig)[0]["response"]["instructions"]
    assert RESULT_BEAT_RULE in instructions
    assert ANSWER_BEAT_RULE not in instructions


def test_the_result_beat_rule_forbids_the_deliberation_opening() -> None:
    """Card item 3, the wording half. The SI is NOT touched to get this."""

    rule = RESULT_BEAT_RULE.lower()
    assert "never open this sentence by saying you are checking" in rule
    # R6's four claims and R15's tense sentence, both still intact.
    assert "one short spoken sentence" in rule
    assert "refused, deferred or dropped" in rule
    assert "present progressive" in rule
    assert "never say it is done" in rule
    answer = ANSWER_BEAT_RULE.lower()
    assert "answer" in answer
    assert "first words" in answer
    assert "do not say you are checking" in answer


# ==========================================================================
# The CURRENT tool surface, pinned tool by tool
# ==========================================================================
@pytest.mark.parametrize("tool", sorted(BROKER_TOOLS))
def test_every_tool_on_the_current_broker_surface_has_a_pinned_beat_verdict(tool: str) -> None:
    """The card asks for the property to be pinned against the CURRENT surface.

    Seven tools today, including R10's ``circle_owner``/``follow_owner``. The
    verdict for each is stated here so that adding an eighth is a decision
    somebody has to write down rather than an accident of which frozenset it
    landed in. An unknown tool is never a receipt, so a new one always speaks.
    """

    suppressible = tool in DEFAULT_RECEIPT_TOOLS and tool not in DEFAULT_ANSWER_TOOLS
    broker = _ScriptedBroker(_ok(tool, detail="started: something is happening"))
    rig = _Rig(_tool_turn(tool=tool, arguments="{}"), tool_handler=broker)
    rig.open()
    rig.turn("do the thing")

    assert (len(_beats(rig)) == 0) is suppressible, (
        f"{tool}: expected suppressible={suppressible}"
    )
    assert (tool in ANSWER_TOOLS) == (tool in DEFAULT_ANSWER_TOOLS), (
        "the broker and the lane disagree about which tools carry an answer"
    )


@pytest.mark.parametrize("tool", sorted(BROKER_TOOLS))
@pytest.mark.parametrize("status", [STATUS_DEFERRED, STATUS_DROPPED, STATUS_REJECTED])
def test_a_call_that_did_not_succeed_is_narrated_for_every_tool(tool: str, status: str) -> None:
    """R6's over-correction guard, widened to the whole surface.

    live_run_1 latched the e-stop and then rejected four motion calls. Exactly
    one was ever narrated. Whatever else changes, a call that did not succeed
    speaks — for every tool, on every non-ok disposition.
    """

    broker = _ScriptedBroker(
        json.dumps({"status": status, "tool": tool, "detail": "Motion is disabled by emergency stop"})
    )
    rig = _Rig(_tool_turn(tool=tool, arguments="{}"), tool_handler=broker)
    rig.open()
    rig.turn("go to the bench")

    assert len(_beats(rig)) == 1, f"a {status} {tool} went unnarrated"
    assert rig.lane.snapshot()["tool_beats_suppressed"] == 0


# ==========================================================================
# Mechanism C — a beat the provider refused is asked for again
# ==========================================================================
def _refused_beat_turn(*, tool: str = "navigate_to") -> list[Step]:
    """The live sequence: the call, the provider refusing the beat, then done.

    This is what 14:29:11.502 looked like on the wire — a ``function_call``
    inside a response that had not finished, the lane's ``response.create``
    landing in that window, and the provider saying no.
    """

    return handshake() + [
        Step(
            "response.create",
            (
                transcript_delta("resp_1", "item_say", "Let me do a quick gesture."),
                transcript_done("resp_1", "item_say", "Let me do a quick gesture."),
                function_call("call_1", tool, "{}"),
            ),
            label="call_inside_an_open_response",
        ),
        Step(
            "response.create",
            (
                error_frame(
                    code=CODE_RESPONSE_ALREADY_ACTIVE,
                    message=(
                        "Conversation already has an active response in progress: "
                        "resp_1. Wait until the response is finished before creating a new one."
                    ),
                ),
                response_done("resp_1"),
            ),
            label="the_provider_refuses_the_beat_then_closes",
        ),
    ]


def test_a_beat_the_provider_refused_is_asked_for_again() -> None:
    """MECHANISM C, and the card's "rejection unnarrated" seed.

    Three of live_run_1's four e-stop refusals died exactly here: the beat's
    ``response.create`` arrived while the response that made the call was still
    open, the provider refused it, the lane counted it as sent and never
    mentioned it again. The owner spoke 18 more turns to a robot that could not
    move and was never told.
    """

    broker = _ScriptedBroker(
        json.dumps(
            {
                "status": STATUS_REJECTED,
                "tool": "navigate_to",
                "detail": "Motion is disabled by emergency stop",
            }
        )
    )
    rig = _Rig(_refused_beat_turn(), tool_handler=broker)
    rig.open()
    rig.turn("go to the bench")

    beats = _beats(rig)
    assert len(beats) == 2, "the refused beat was never asked for again"
    snapshot = rig.lane.snapshot()
    assert snapshot["tool_beats_refused"] == 1
    assert snapshot["tool_beats_deferred"] == 1
    assert snapshot["tool_beats_requested"] == 1, "a refused frame is not a beat the owner heard"
    assert snapshot["tool_beats_lost"] == 0
    assert any("refused the beat" in note for note in rig.lane.events), rig.lane.events[-4:]


def test_a_refused_beat_does_not_leave_a_response_owed_forever() -> None:
    """The leak that manufactured live_run_1's only stall.

    ``_send`` increments ``_responses_pending`` for every ``response.create``
    the transport accepted. A create the PROVIDER then refuses never produces a
    ``response.done``, so the count stays up, the watchdog eventually fires, and
    a healthy session is hung up 48 s later — which is how the run's one
    narrated rejection came to be narrated at all.
    """

    broker = _ScriptedBroker(
        json.dumps({"status": STATUS_REJECTED, "tool": "navigate_to", "detail": "e-stop"})
    )
    rig = _Rig(_refused_beat_turn(), tool_handler=broker)
    rig.open()
    rig.turn("go to the bench")

    # One create is genuinely outstanding — the re-offered beat. Not two.
    assert rig.lane._responses_pending == 1


def test_a_refused_beat_that_dies_with_the_session_is_counted_and_said() -> None:
    """Fail LOUD, not silent. The one number an operator should alarm on.

    If the re-offer never happens — the socket died first — the owner was not
    told about a refusal, and that has to be visible in the snapshot rather
    than inferred from a missing sentence.
    """

    broker = _ScriptedBroker(
        json.dumps({"status": STATUS_REJECTED, "tool": "play_gesture", "detail": "e-stop"})
    )
    rig = _Rig(
        handshake()
        + [
            Step(
                "response.create",
                (
                    transcript_delta("resp_1", "item_say", "Let me check on that."),
                    transcript_done("resp_1", "item_say", "Let me check on that."),
                    function_call("call_1", "play_gesture", "{}"),
                    error_frame(
                        code=CODE_RESPONSE_ALREADY_ACTIVE,
                        message="Conversation already has an active response in progress: resp_1.",
                    ),
                ),
                label="refused_and_then_the_session_dies",
            )
        ],
        tool_handler=broker,
    )
    rig.open()
    rig.turn("wave at me")
    assert rig.lane.snapshot()["tool_beats_refused"] == 1

    rig.lane.close()

    snapshot = rig.lane.snapshot()
    assert snapshot["tool_beats_lost"] == 1
    assert any("tool beat LOST for play_gesture" in note for note in rig.lane.events), (
        rig.lane.events[-4:]
    )


def test_an_error_that_is_not_about_a_beat_leaves_the_beat_alone() -> None:
    """Attribution has to be narrow enough to be worth having.

    A rate limit is not a refused beat. If any error could claim the in-flight
    beat, the lane would re-ask for beats it already got and bill the owner for
    the privilege.
    """

    broker = _ScriptedBroker(_ok("navigate_to"))
    rig = _Rig(
        handshake()
        + [
            Step(
                "response.create",
                (
                    function_call("call_1", "navigate_to", "{}"),
                    error_frame(code="rate_limit_exceeded", message="slow down"),
                    response_done("resp_1"),
                ),
                label="silent_call_then_an_unrelated_error",
            )
        ],
        tool_handler=broker,
    )
    rig.open()
    rig.turn("go to the sidewalk")

    snapshot = rig.lane.snapshot()
    assert snapshot["tool_beats_refused"] == 0
    assert snapshot["tool_beats_requested"] == 1
    assert len(_beats(rig)) == 1, "one beat, asked for once"


# ==========================================================================
# The broker's half of mechanism A
# ==========================================================================
def _broker_answer(tool: str, arguments: str = '{"place": "the bench", "query": "x"}') -> dict:
    """Run the REAL broker's ``handle`` for ``tool`` with no doors wired.

    Every door defaults to ``_unwired``, so each tool takes its own failure
    path — which is exactly what this needs to prove: the stamp must survive
    the refusals raised before an argument is even read, because a
    ``get_status`` that failed is still the owner's question going unanswered.
    """

    def _refuse(*_args: object, **_kwargs: object) -> str:
        raise ValueError("this robot has not wired that ability up")

    doors = ToolDoors(
        validate=_refuse,
        status=_refuse,
        recall=_refuse,
        gesture=_refuse,
        pose=_refuse,
        navigate=_refuse,
    )
    broker = RealtimeToolBroker(doors)
    return json.loads(broker.handle(name=tool, call_id="call_x", arguments=arguments))


@pytest.mark.parametrize("tool", sorted(BROKER_TOOLS))
def test_the_broker_stamps_its_answer_tools_and_only_those(tool: str) -> None:
    """One stamp, one place — R15's rule, applied to the second classification."""

    answer = _broker_answer(tool)
    assert (answer.get(ANSWER_RESULT_KEY) is True) == (tool in ANSWER_TOOLS), answer


def test_the_stamp_survives_a_tool_that_could_not_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed lookup is the loudest case, not an exempt one.

    owner_session_1's F4 was the robot claiming amnesia. If ``get_status``
    raises and the lane goes quiet because the result carried no mark, the
    owner is back to a question that was simply never answered.
    """

    del monkeypatch
    answer = _broker_answer("get_status", arguments="{}")
    assert answer["status"] != STATUS_OK, "the unwired door must have refused"
    assert answer[ANSWER_RESULT_KEY] is True


def test_the_two_classifications_do_not_overlap() -> None:
    """A tool cannot be both a silent receipt and the answer to a question."""

    assert not (ANSWER_TOOLS & DEFAULT_RECEIPT_TOOLS)
    assert ANSWER_TOOLS == DEFAULT_ANSWER_TOOLS


# ==========================================================================
# Mechanism D — the activity that expired undelivered
# ==========================================================================
pytest.importorskip("mujoco", reason="the activity terminal needs a runtime")

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV, WhispererConfig
from parcel_robot.realtime.whisperer import KIND_REFUSAL, Whisperer
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "rl"


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
    def __init__(self) -> None:
        self.active = True
        self.recovering = False
        self.playback_owned = False
        self.narrated: list[str] = []
        self.usage_rows: tuple = ()

    def narrate_event(self, text: str) -> bool:
        self.narrated.append(text)
        return True

    def snapshot(self) -> dict[str, object]:
        return {"active": True, "narrations": len(self.narrated)}

    def close(self) -> None:
        return None


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    path = tmp_path / "r19.yaml"
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
            detail="r19 fixture",
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


def _expire_next_proposal(runtime: RobotRuntime) -> None:
    """Make the coordinator retire the next proposal on its TTL, not run it."""

    runtime.activities.proposal_ttl_s = 0.0


def test_the_coordinator_still_calls_a_timed_out_proposal_expired(runtime: RobotRuntime) -> None:
    """``ACTIVITY_STATUS_EXPIRED`` is a string this card does not own.

    ``core/activities.py`` is outside R19's OWNS, so the constant lives in
    ``runtime.py`` and this test is the tripwire: rename the status there and
    the expiry narration would silently stop working, which is the exact class
    of failure this card exists to end.
    """

    _expire_next_proposal(runtime)
    runtime.activities.submit(
        ActionProposal(kind="skill", name="sit", trigger="explicit_command", reason="test"),
        ActivityContext(),
    )
    recent = runtime.activities.snapshot()["recent"]
    assert [row["status"] for row in recent] == [ACTIVITY_STATUS_EXPIRED]
    assert recent[0]["detail"] == "proposal_ttl_elapsed"


def test_an_activity_that_expired_undelivered_is_narrated(runtime: RobotRuntime) -> None:
    """MECHANISM D, and the card's "expiry silent" seed.

    live_run_1 q21, verbatim from the scoring: the owner said "Sit down", the
    broker answered ``executed`` and told the model *"started: the robot is
    settling into the sit pose"*, and ``state.activities.recent`` recorded the
    same command as ``expired / proposal_ttl_elapsed``. Nothing moved. Nothing
    was said. ``broker.executed`` means "dispatched", and until this seam
    existed there was no sentence in the stack for "and then it never ran".
    """

    lane = _wire(runtime)
    name = runtime._emote_catalog[0]
    _expire_next_proposal(runtime)
    runtime._realtime_gesture(name, 1.0)

    runtime._step_activities()

    assert len(lane.narrated) == 1, lane.narrated
    said = lane.narrated[0]
    assert "NEVER RAN" in said
    assert name.replace("_", " ") in said
    assert "do not say it is done" in said.lower()
    rows = runtime.realtime_whisperer.decision_rows()
    assert rows[-1]["kind"] == KIND_REFUSAL
    assert rows[-1]["band"] == "always"
    assert rows[-1]["forwarded"] is True


def test_an_expiry_is_narrated_once_and_never_again(runtime: RobotRuntime) -> None:
    """The control loop runs this method 20 times a second."""

    lane = _wire(runtime)
    _expire_next_proposal(runtime)
    runtime._realtime_gesture(runtime._emote_catalog[0], 1.0)

    for _ in range(5):
        runtime._step_activities()

    assert len(lane.narrated) == 1, lane.narrated


def test_an_old_expiry_never_claims_a_later_requests_ending(runtime: RobotRuntime) -> None:
    """What the seen-set is actually FOR, and it is not the once-only rule.

    The one-shot mark already stops a single expiry being announced twice, and
    behind it R11's dedup window would swallow a repeat of the same key. The id
    ledger stops the OFFER being made at all, which is the layer those two
    cannot reach: the coordinator keeps 20 endings in ``recent``, so a proposal
    that expired and was already reported sits there for the rest of the
    session. Ask for the same gesture again and, without the ledger, that stale
    row claims the NEW request's mark and offers the whisperer a second
    "it never ran" about a gesture that is running — surviving only on a dedup
    window that is measured in seconds and will eventually expire.

    Asserted on the whisperer's decision log rather than on what the lane
    heard, because "offered and deduplicated" and "never offered" look
    identical from the lane and are not the same thing.
    """

    lane = _wire(runtime)
    name = runtime._emote_catalog[0]
    label = f"{name.replace('_', ' ')} movement"

    _expire_next_proposal(runtime)
    runtime._realtime_gesture(name, 1.0)
    runtime._step_activities()
    assert len(lane.narrated) == 1, "the first expiry is the one that speaks"

    # The owner asks again, and this time it is going to run.
    runtime.activities.proposal_ttl_s = 20.0
    runtime.activities.cooldown_s = 0.0
    runtime._realtime_gesture(name, 1.0)
    runtime._step_activities()

    offers = [
        row for row in runtime.realtime_whisperer.decision_rows() if row["key"] == f"refusal:{label}"
    ]
    assert len(offers) == 1, offers
    assert len(lane.narrated) == 1, lane.narrated


def test_an_ending_that_is_not_an_expiry_is_left_to_its_own_reporter(
    runtime: RobotRuntime,
) -> None:
    """The status filter, pinned where the one-shot mark cannot stand in for it.

    ``ActivityCoordinator.clear`` — an e-stop, or a new command taking over —
    retires a pending proposal as ``cancelled`` and leaves the owner's mark
    untouched, because nothing narrates a clear. That is R15's behaviour and
    R19 does not change it: a poller that spoke for every ending in ``recent``
    would announce "it NEVER RAN" for a gesture the owner themselves cancelled,
    on a path where the one-shot mark is still armed and cannot save it.
    """

    lane = _wire(runtime)
    runtime._realtime_gesture(runtime._emote_catalog[0], 1.0)
    runtime.activities.clear("estop")

    runtime._step_activities()

    assert lane.narrated == []


def test_an_expiry_nobody_asked_for_stays_silent(runtime: RobotRuntime) -> None:
    """R15's mark, inherited rather than reinvented.

    ``_speech_emote`` runs a gesture for every ``[emote:...]`` tag the robot
    writes into its own sentences. Announcing that one of those timed out would
    have the dog interrupting itself to apologise for a nod it never mentioned,
    at one billed response per tag.
    """

    lane = _wire(runtime)
    _expire_next_proposal(runtime)
    runtime._speech_emote(runtime._emote_catalog[0], 1.0)

    runtime._step_activities()

    assert lane.narrated == []


def test_an_activity_that_actually_ran_is_not_reported_as_never_run(
    runtime: RobotRuntime,
) -> None:
    """R15's completed arm must not be captured by R19's poller.

    Both endings land in the coordinator's ``recent`` deque. Only the expired
    one has no other reporter; claiming the rest would double-narrate every
    gesture and contradict R15's "done means done" in the same breath.
    """

    lane = _wire(runtime)
    name = runtime._emote_catalog[0]
    runtime._realtime_gesture(name, 1.0)
    runtime._step_activities()
    runtime._activity_complete_at = 0.0
    runtime._step_activities()

    assert len(lane.narrated) == 1, lane.narrated
    assert "FINISHED" in lane.narrated[0]
    assert "NEVER RAN" not in lane.narrated[0]
