"""Card R1: the Realtime lane, end-to-end against the scripted fake server.

WHAT THIS FILE IS FOR
---------------------
R1 ships no live transport and no credentials, so every claim about the lane is
a claim about its behaviour against ``FakeRealtimeServer``. These tests drive
the six shapes that matter — a normal turn, barge-in mid-response, a silent
stall, a mid-turn disconnect, a malformed frame, a function call — plus the
four constraints an adversarial review of the design named as blocking:

1. hosted transcripts NEVER enter ``submit_voice_text`` (that is the front door
   to the whole local agent, and its barge-in machinery mutes hosted playback);
2. punctuation is normalized before any phrase match (covered exhaustively in
   ``test_realtime_ingress.py``; the end-to-end proof lives here);
3. the lane owns the sink exclusively — ``begin_utterance`` at every response,
   24 kHz WAV wrapping, and an explicit refusal to share the mouth;
4. spoken stop is cloud-dependent, so what is proven here is that the hosted
   path latches the SAME e-stop the panel does — not that it is independent
   of the cloud. It is not.

TIME AND AUDIO ARE INJECTED
---------------------------
No sleeps, no wall clock, no devices. ``_Clock`` is advanced by hand and
``_FakeSink`` reproduces the two ``SpeakerSink`` behaviours the lane depends on:
``begin_utterance`` clears the first-chunk anchor, and the anchor is set at the
moment a chunk actually starts playing.
"""

from __future__ import annotations

import base64
import io
import json
import sqlite3
import wave
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.memory import REALTIME_COLUMNS, ConversationMemory
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.config import (
    REALTIME_CONFIG_ENV,
    RealtimeConfig,
    RealtimeConfigError,
    load_realtime_config,
    realtime_config_from_mapping,
    resolve_realtime_config_path,
)
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    barge_in_turn,
    disconnect_turn,
    function_call_turn,
    handshake,
    happy_turn,
    malformed_turn,
    pcm_tone,
    silent_stall,
)
from parcel_robot.realtime.lane import (
    CODE_ARMED,
    CODE_BUDGET_EXHAUSTED,
    CODE_DISABLED,
    CODE_NO_HANDSHAKE,
    CODE_NO_MIC_GESTURE,
    CODE_NO_TRANSPORT,
    TOOL_REFUSAL_OUTPUT,
    RealtimeLane,
    RealtimeLaneError,
    SinkOwnershipError,
    build_instructions,
    decide_realtime_arming,
)
from parcel_robot.realtime.protocol import PCM16_SAMPLE_RATE_HZ
from parcel_robot.realtime.transport import transport_pair
from parcel_robot.runtime import (
    TRANSCRIPT_ORIGIN_MIC,
    TRANSCRIPT_ORIGIN_PANEL,
    TRANSCRIPT_ORIGIN_REALTIME,
    TRANSCRIPT_ORIGINS,
    RobotRuntime,
)

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r1-realtime"

#: 240 ms of mono PCM16 at 24 kHz, in bytes. The coalescing floor.
COALESCE_BYTES = int(0.240 * PCM16_SAMPLE_RATE_HZ) * 2


# ------------------------------------------------------------------ fixtures
class _Clock:
    """Monotonic time as a number a test advances by hand."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _FakeSink:
    """The two ``SpeakerSink`` behaviours the playback bridge depends on.

    ``begin_utterance`` clears the first-chunk anchor (voice_audio.py:829-841)
    and the anchor is stamped when a chunk starts playing (voice_audio.py:942).
    Here "starts playing" is "was enqueued", which is the one honest
    simplification in this file — see ``does_not_prove`` in R1_STATUS.md.
    """

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self.chunks: list[bytes] = []
        self.begin_calls = 0
        self.interrupts = 0
        self.first_chunk_started_monotonic: float | None = None

    def begin_utterance(self) -> None:
        self.begin_calls += 1
        self.first_chunk_started_monotonic = None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token
        self.chunks.append(chunk)
        if self.first_chunk_started_monotonic is None:
            self.first_chunk_started_monotonic = self._clock()

    def interrupt(self) -> None:
        self.interrupts += 1


class _Rig:
    """A lane, a clock, a sink, and a fresh fake server per connection."""

    def __init__(
        self,
        script: list[Step],
        *,
        config: RealtimeConfig | None = None,
        ledger: ConversationMemory | None = None,
        memory_tail=None,
        ingress=None,
        cost_log_path: Path | None = None,
        duplex_output_active=None,
        sink: _FakeSink | None = None,
    ) -> None:
        self.clock = _Clock()
        self.script = script
        self.servers: list[FakeRealtimeServer] = []
        self.sink = sink if sink is not None else _FakeSink(self.clock)
        self.ledger = ledger
        counter = {"n": 0}

        def _session_id() -> str:
            counter["n"] += 1
            return f"rt_session_{counter['n']}"

        self.lane = RealtimeLane(
            config=config or RealtimeConfig(enabled=True, source="test"),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=self.sink,
            ingress=ingress,
            ledger=ledger,
            memory_tail=memory_tail,
            clock=self.clock,
            cost_log_path=cost_log_path,
            duplex_output_active=duplex_output_active or (lambda: False),
            session_id_factory=_session_id,
        )

    def _factory(self):
        lane_end, server_end = transport_pair(clock=self.clock)
        self.servers.append(
            FakeRealtimeServer(
                transport=server_end,
                script=list(self.script),
                clock=self.clock,
            )
        )
        return lane_end

    @property
    def server(self) -> FakeRealtimeServer:
        return self.servers[-1]

    def open(self) -> str:
        session = self.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
        self.step()
        return session

    def step(self) -> None:
        """One full exchange: server consumes, server emits, lane consumes."""

        self.server.pump()
        self.lane.pump()

    def speak(self, ms: int = 100) -> None:
        self.lane.send_audio(pcm_tone(ms, seed=3))
        self.step()


def _wav_rate(chunk: bytes) -> int:
    with wave.open(io.BytesIO(chunk), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2
        return reader.getframerate()


def _wav_frames(chunk: bytes) -> int:
    with wave.open(io.BytesIO(chunk), "rb") as reader:
        return reader.getnframes()


def _sent_types(rig: _Rig) -> list[str]:
    transport = rig.lane.transport
    assert transport is not None
    return [str(frame.get("type")) for frame in transport.sent]  # type: ignore[attr-defined]


# ============================================================ the happy turn
def test_a_normal_turn_plays_wav_wrapped_24k_audio_and_closes_with_usage() -> None:
    rig = _Rig(handshake() + happy_turn())
    rig.open()
    assert rig.lane.provider_session_id == "sess_fake_1"

    rig.speak()

    assert rig.sink.begin_calls == 1, "begin_utterance must precede each hosted reply"
    assert rig.sink.chunks, "hosted audio never reached the sink"
    for chunk in rig.sink.chunks:
        assert chunk[:4] == b"RIFF", "the sink infers its rate from a RIFF header"
        assert _wav_rate(chunk) == 24_000
    assert rig.lane.usage_rows and rig.lane.usage_rows[0]["cached_tokens"] == 30
    assert rig.lane.playback_owned is False, "response.done releases the sink"


def test_raw_24k_pcm_would_play_slow_which_is_why_the_wrapper_exists() -> None:
    """The defect stated as a fact: an unwrapped chunk carries no rate at all.

    ``SpeakerSink._decode`` only learns a rate from a RIFF header; a raw chunk
    plays at the last rate it saw, default 16 kHz — 24 kHz audio at 16 kHz is
    50% slow. Every chunk this lane enqueues therefore carries a header.
    """

    rig = _Rig(handshake() + happy_turn())
    rig.open()
    rig.speak()
    total_frames = sum(_wav_frames(chunk) for chunk in rig.sink.chunks)
    assert total_frames == 300 * (PCM16_SAMPLE_RATE_HZ // 1000)  # 3 x 100 ms delivered whole


def test_audio_is_coalesced_to_at_least_240ms_so_prosody_can_see_accents() -> None:
    """Chunks under 200 ms return zero accents (prosody.py:29,128-135)."""

    rig = _Rig(handshake() + happy_turn(audio_chunks=(60, 60, 60, 60, 60)))
    rig.open()
    rig.speak()
    assert len(rig.sink.chunks) >= 1
    # Everything except the utterance's final remainder clears the floor.
    for chunk in rig.sink.chunks[:-1]:
        assert len(chunk) - 44 >= COALESCE_BYTES, "coalescing floor breached"


def test_the_memory_tail_goes_up_before_any_audio_does() -> None:
    """History is a static, append-only prefix: mid-session edits bust the cache."""

    tail = [
        {"role": "user", "content": "I liked the bench by the water"},
        {"role": "assistant", "content": "The one under the willow."},
    ]
    rig = _Rig(handshake() + happy_turn(), memory_tail=lambda: tail)
    rig.open()
    rig.speak()
    types = _sent_types(rig)
    assert types[0] == "session.update"
    assert types[1:3] == ["conversation.item.create"] * 2
    assert "input_audio_buffer.append" in types
    assert types.index("input_audio_buffer.append") > 2
    assert rig.lane.tail_items_injected == 2


def test_the_replayed_tail_carries_BOTH_halves_of_the_conversation() -> None:
    """Card R8 — the headline defect, pinned end to end at the lane.

    ``_inject_tail`` always SELECTED the assistant rows and always sent them.
    The provider always refused them, because every non-``user`` item carried
    ``{"type": "text"}`` — a content type it accepts for no role at all. So from
    R1 to R7 every session open and every reconnect replayed the owner's
    sentences with the robot's answers missing from between them, silently,
    while ``tail_items_injected`` counted a full tail.

    The consequence was not academic: R6's live session 2 repaid a turn onto a
    session whose replayed history had no assistant turns in it, and the model
    answered a different, stale question. This test is the reason that cannot
    happen again without a test going red.
    """

    tail = [
        {"role": "user", "content": "I liked the bench by the water"},
        {"role": "assistant", "content": "The one under the willow."},
    ]
    rig = _Rig(handshake() + happy_turn(), memory_tail=lambda: tail)
    rig.open()

    transport = rig.lane.transport
    assert transport is not None
    items = [
        frame
        for frame in transport.sent  # type: ignore[attr-defined]
        if frame.get("type") == "conversation.item.create"
    ]
    assert [frame["item"]["role"] for frame in items] == ["user", "assistant"], (
        "both halves of the conversation must go up, in order"
    )
    # And each half in the content type the provider actually accepts for it —
    # live-verified 2026-08-19. Getting this wrong is not a degraded replay, it
    # is a refused item and a missing turn.
    assert items[0]["item"]["content"][0]["type"] == "input_text"
    assert items[1]["item"]["content"][0]["type"] == "output_text"
    assert items[1]["item"]["content"][0]["text"] == "The one under the willow."


def test_both_sides_of_a_turn_reach_the_ledger_with_provenance() -> None:
    memory = ConversationMemory(":memory:")
    rig = _Rig(handshake() + happy_turn(), ledger=memory)
    session = rig.open()
    rig.speak()

    rows = memory.realtime_turns()
    assert [row["speaker"] for row in rows] == ["owner", "robot"]
    assert rows[0]["content"] == "how was your day"
    assert rows[1]["content"] == "Warm and quiet. Yours?"
    assert {row["origin"] for row in rows} == {TRANSCRIPT_ORIGIN_REALTIME}
    assert {row["session_id"] for row in rows} == {session}
    assert rows[0]["provider_item_id"] == "item_owner_1"


# ================================================================= barge-in
def test_barge_in_interrupts_cancels_and_truncates_at_played_milliseconds() -> None:
    """Binding constraint 3, and the truncate the review said must be honest.

    The provider believes it said the whole reply. The owner heard 100 ms of it.
    ``conversation.item.truncate`` carries the SINK's number, not the number of
    bytes the lane happened to queue, so the two beliefs agree afterwards.
    """

    rig = _Rig(handshake() + barge_in_turn())
    rig.open()
    rig.speak()  # 240 ms enqueued, playback anchored at t0
    assert rig.lane.enqueued_ms == pytest.approx(240.0)
    assert rig.sink.interrupts == 0

    rig.clock.advance(0.100)  # the owner hears 100 ms and starts talking
    rig.speak()

    assert rig.sink.interrupts == 1, "the sink must be aborted, not merely cancelled"
    types = _sent_types(rig)
    assert "response.cancel" in types
    assert "conversation.item.truncate" in types
    truncate = next(
        frame
        for frame in rig.lane.transport.sent  # type: ignore[union-attr]
        if frame.get("type") == "conversation.item.truncate"
    )
    assert truncate["audio_end_ms"] == 100, "truncate must carry PLAYED ms"
    assert truncate["item_id"] == "item_robot_barge"
    assert rig.lane.truncations[0]["enqueued_ms"] == pytest.approx(240.0)


def test_a_truncated_reply_is_ledgered_as_what_was_heard() -> None:
    memory = ConversationMemory(":memory:")
    script = handshake() + [
        Step(
            "input_audio_buffer.append",
            (
                {
                    "type": "response.output_audio.delta",
                    "response_id": "r",
                    "item_id": "i",
                    "delta": base64.b64encode(pcm_tone(240)).decode("ascii"),
                },
                {
                    "type": "response.output_audio_transcript.delta",
                    "response_id": "r",
                    "item_id": "i",
                    "delta": "The park is lovely at",
                },
            ),
        ),
        Step("input_audio_buffer.append", ({"type": "input_audio_buffer.speech_started"},)),
        Step(
            "input_audio_buffer.append",
            (
                {
                    "type": "response.output_audio_transcript.done",
                    "response_id": "r",
                    "item_id": "i",
                    "transcript": "The park is lovely at this hour, all gold and empty.",
                },
            ),
        ),
    ]
    rig = _Rig(script, ledger=memory)
    rig.open()
    rig.speak()
    rig.clock.advance(0.080)
    rig.speak()
    rig.speak()  # the provider's full transcript arrives AFTER the cancel

    robot_rows = [row for row in memory.realtime_turns() if row["speaker"] == "robot"]
    assert len(robot_rows) == 1, "the drafted continuation must not be ledgered too"
    assert robot_rows[0]["content"] == "The park is lovely at [interrupted after 80 ms]"


def test_the_sink_is_rearmed_for_the_reply_after_a_barge_in() -> None:
    """``interrupt()`` latches suppression; only ``begin_utterance`` clears it."""

    rig = _Rig(handshake() + barge_in_turn() + happy_turn(response_id="resp_2"))
    rig.open()
    rig.speak()
    rig.clock.advance(0.05)
    rig.speak()  # barge-in
    rig.speak()  # the next hosted reply
    assert rig.sink.begin_calls == 2, "a post-barge-in reply must re-arm the sink"


# ============================================================== the watchdog
def test_the_watchdog_fires_on_a_silent_stall_and_reinjects_the_tail() -> None:
    tail = [
        {"role": "user", "content": "remember the willow"},
        {"role": "assistant", "content": "I do."},
    ]
    memory = ConversationMemory(":memory:")
    rig = _Rig(
        handshake() + silent_stall(),
        config=RealtimeConfig(enabled=True, stall_timeout_s=4.0, source="test"),
        memory_tail=lambda: tail,
        ledger=memory,
    )
    first = rig.open()
    rig.speak()  # accepted; the server says nothing at all

    assert rig.lane.tick() is None, "not yet past the timeout"
    rig.clock.advance(5.0)
    assert rig.lane.tick() == "stall"

    assert rig.lane.stalls == 1
    assert rig.lane.reconnects == 1
    assert rig.lane.session_id != first
    assert len(rig.servers) == 2
    rig.step()
    reopened = rig.servers[-1].received_types()
    assert reopened[0] == "session.update"
    assert reopened.count("conversation.item.create") == 2, "the tail must be re-injected"
    markers = [row["content"] for row in memory.realtime_turns() if row["speaker"] == "system"]
    assert any("[session stall]" in marker for marker in markers)


def test_the_watchdog_does_not_fire_while_nothing_is_expected() -> None:
    """An idle session is not a dead one; RECONNECTING it would be churn.

    Card R16 sharpened this test rather than changing what it claims. The
    watchdog's rule is unchanged and is asserted twice here — before AND after
    the idle window, ``reconnects`` stays at zero, because a session nobody is
    waiting on has not stalled no matter how long it sits. What R16 adds is the
    other half of the sentence: past ``idle_close_after_s`` the lane does not sit
    there either. It hangs up. The one thing that must never happen — a silent
    session being reconnected by the stall watchdog — is what both halves pin.
    """

    rig = _Rig(
        handshake() + silent_stall(),
        config=RealtimeConfig(
            enabled=True, stall_timeout_s=2.0, idle_close_after_s=600.0, source="test"
        ),
    )
    rig.open()
    rig.clock.advance(599.0)
    assert rig.lane.tick() is None, "300x the stall timeout, and nothing was expected"
    assert rig.lane.reconnects == 0

    rig.clock.advance(2.0)
    assert rig.lane.tick() == "idle", "past the idle window the lane hangs up (card R16)"
    assert rig.lane.reconnects == 0, "a hang-up is not a reconnect"
    assert rig.lane.stalls == 0
    assert rig.lane.active is False


def test_a_disconnect_mid_turn_is_survived_by_the_same_reconnect_path() -> None:
    rig = _Rig(handshake() + disconnect_turn(before_drop_ms=260))
    rig.open()
    rig.speak()
    assert rig.lane.disconnects == 1
    assert rig.lane.reconnects == 1
    assert rig.lane.active, "the lane must come back up, not stay down"
    assert rig.sink.chunks, "audio received before the drop still played"


def test_frames_already_in_flight_are_delivered_before_the_hang_up_is_seen() -> None:
    """Otherwise a mid-turn drop is indistinguishable from a server that never spoke."""

    rig = _Rig(handshake() + disconnect_turn(before_drop_ms=120))
    rig.open()
    rig.speak()
    # 120 ms never cleared the coalescing floor, so nothing reached the sink and
    # the partial buffer is discarded with the dead session — but the frame WAS
    # parsed, which is what proves the drain-then-report ordering.
    assert rig.sink.chunks == []
    assert rig.lane.disconnects == 1
    assert rig.lane.protocol_errors == []


# ============================================================== the rollover
def test_the_sixty_minute_cap_rolls_over_and_ledgers_a_summary_marker() -> None:
    memory = ConversationMemory(":memory:")
    rig = _Rig(
        handshake() + happy_turn(),
        config=RealtimeConfig(enabled=True, session_max_s=60.0, source="test"),
        ledger=memory,
    )
    first = rig.open()
    rig.clock.advance(61.0)
    assert rig.lane.tick() == "rollover"

    assert rig.lane.rollovers == 1
    assert rig.lane.session_id != first
    markers = [row["content"] for row in memory.realtime_turns() if row["speaker"] == "system"]
    assert any("summarization is not implemented in R1" in marker for marker in markers)
    assert any("[session rollover]" in marker for marker in markers)


def test_a_summarize_hook_replaces_the_stub_marker_when_one_is_wired() -> None:
    memory = ConversationMemory(":memory:")
    rig = _Rig(
        handshake() + happy_turn(),
        config=RealtimeConfig(enabled=True, session_max_s=10.0, source="test"),
        ledger=memory,
    )
    rig.lane._summarize_hook = lambda session: f"[summary of {session}] we talked about willows"
    rig.open()
    rig.clock.advance(11.0)
    rig.lane.tick()
    markers = [row["content"] for row in memory.realtime_turns() if row["speaker"] == "system"]
    assert any("we talked about willows" in marker for marker in markers)


# ========================================================== hostile payloads
def test_a_malformed_frame_is_refused_and_the_session_survives() -> None:
    rig = _Rig(handshake() + malformed_turn())
    rig.open()
    rig.speak()
    assert len(rig.lane.protocol_errors) == 1
    assert "response.telepathy.delta" in rig.lane.protocol_errors[0]
    assert rig.lane.active, "one bad frame must not tear down the conversation"


def test_every_function_call_gets_the_r1_refusal_and_no_local_effect() -> None:
    rig = _Rig(handshake() + function_call_turn())
    rig.open()
    rig.speak()
    assert rig.lane.refused_tool_calls == ["navigate_to"]
    outputs = [
        frame
        for frame in rig.lane.transport.sent  # type: ignore[union-attr]
        if frame.get("type") == "conversation.item.create"
        and frame["item"].get("type") == "function_call_output"
    ]
    assert len(outputs) == 1
    assert json.loads(outputs[0]["item"]["output"]) == {"error": "tools are not enabled in R1"}
    assert TOOL_REFUSAL_OUTPUT == outputs[0]["item"]["output"]


def test_a_server_error_frame_is_recorded_rather_than_raised() -> None:
    rig = _Rig(handshake() + [Step("input_audio_buffer.append", ({"type": "error"},))])
    rig.open()
    rig.speak()
    assert rig.lane.server_errors and rig.lane.server_errors[0].code == "unknown"


# =========================================================== sink ownership
def test_the_lane_refuses_to_enqueue_while_a_duplex_output_is_live() -> None:
    """Binding constraint 3: assert, do not assume. One mouth, one owner.

    ``SpeakerSink`` is an ordered queue with no notion of who filled it, and
    ``speak_system``'s busy check cannot see hosted playback — two concurrent
    enqueuers would interleave sentences chunk by chunk.
    """

    rig = _Rig(handshake() + happy_turn(), duplex_output_active=lambda: True)
    rig.open()
    with pytest.raises(SinkOwnershipError):
        rig.speak()
    assert rig.sink.chunks == []
    assert rig.sink.begin_calls == 0


def test_the_duplex_lane_is_refused_while_the_hosted_lane_owns_the_sink() -> None:
    rig = _Rig(handshake() + barge_in_turn())
    rig.open()
    rig.speak()
    assert rig.lane.playback_owned is True
    with pytest.raises(SinkOwnershipError):
        rig.lane.assert_lane_not_speaking()
    rig.clock.advance(0.05)
    rig.speak()  # barge-in releases the mouth
    rig.lane.assert_lane_not_speaking()


def test_a_lane_with_no_sink_and_no_factory_refuses_loudly() -> None:
    lane = RealtimeLane(
        config=RealtimeConfig(enabled=True, source="test"),
        instructions="x",
        transport_factory=lambda: transport_pair()[0],
    )
    lane.open_session(handshake_token="t", mic_gesture=True)
    with pytest.raises(RealtimeLaneError):
        lane._begin_response("r", "i")


# ================================================================== the cost
def test_every_response_writes_one_usage_row_to_the_cost_log(tmp_path: Path) -> None:
    """Invoice / committed turns has to be a query, not an estimate."""

    log = tmp_path / "realtime" / "cost.jsonl"
    rig = _Rig(handshake() + happy_turn(), cost_log_path=log)
    rig.open()
    rig.speak()
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["response_id"] == "resp_1"
    assert rows[0]["input_audio_tokens"] == 90
    assert rows[0]["cached_tokens"] == 30
    assert rows[0]["session_id"] == rig.lane.session_id


# ================================================================== arming
def _config(**overrides) -> RealtimeConfig:
    return RealtimeConfig(**{"enabled": True, "source": "test", **overrides})


@pytest.mark.parametrize(
    ("enabled", "token", "gesture", "transport", "spend", "code"),
    [
        (False, "t", True, True, 0.0, CODE_DISABLED),
        (True, None, True, True, 0.0, CODE_NO_HANDSHAKE),
        (True, "", True, True, 0.0, CODE_NO_HANDSHAKE),
        (True, "t", False, True, 0.0, CODE_NO_MIC_GESTURE),
        (True, "t", True, True, 25.0, CODE_BUDGET_EXHAUSTED),
        (True, "t", True, False, 0.0, CODE_NO_TRANSPORT),
        (True, "t", True, True, 0.0, CODE_ARMED),
    ],
)
def test_arming_requires_every_yes_independently(
    enabled: bool,
    token: str | None,
    gesture: bool,
    transport: bool,
    spend: float,
    code: str,
) -> None:
    decision = decide_realtime_arming(
        config=_config(enabled=enabled),
        handshake_token=token,
        mic_gesture=gesture,
        transport_available=transport,
        spend_usd=spend,
    )
    assert decision.code == code
    assert decision.armed is (code == CODE_ARMED)
    assert decision.reason.strip(), "every outcome carries a one-line reason"


def test_arming_never_treats_a_reachable_service_as_consent() -> None:
    """The named shipped defect of 2026-08-11, in this lane's vocabulary."""

    decision = decide_realtime_arming(config=_config(), handshake_token="csrf", mic_gesture=False)
    assert decision.armed is False
    assert "reachable service is not consent" in decision.reason


def test_an_unarmed_lane_cannot_open_a_session() -> None:
    lane = RealtimeLane(
        config=RealtimeConfig(enabled=False, source="absent"),
        instructions="x",
        transport_factory=lambda: transport_pair()[0],
    )
    with pytest.raises(RealtimeLaneError):
        lane.open_session(handshake_token="t", mic_gesture=True)
    assert lane.transport is None


def test_sending_audio_without_a_session_is_refused() -> None:
    lane = RealtimeLane(config=RealtimeConfig(source="absent"), instructions="x")
    with pytest.raises(RealtimeLaneError):
        lane.send_audio(b"\x00\x00")


# =========================================================== instructions
def test_instructions_layer_persona_reply_style_and_guardrails() -> None:
    text = build_instructions(
        personality="You are a warm, curious robot dog.",
        reply_style=("Keep replies to two sentences.", ""),
    )
    assert text.startswith("You are a warm, curious robot dog.")
    assert "- Keep replies to two sentences." in text
    assert "never claim to have" in text
    assert "\n- \n" not in text


# ================================================================== config
def test_an_absent_config_file_is_a_disabled_lane_not_an_error(tmp_path: Path) -> None:
    config = load_realtime_config(tmp_path / "nope.yaml")
    assert config.enabled is False
    assert config.present is False
    assert config.source == "absent"


def test_an_unknown_config_key_refuses_at_load(tmp_path: Path) -> None:
    path = tmp_path / "realtime.yaml"
    path.write_text("enabled: true\nvocie: cedar\n", encoding="utf-8")
    with pytest.raises(RealtimeConfigError) as caught:
        load_realtime_config(path)
    assert "vocie" in str(caught.value)


@pytest.mark.parametrize(
    "body",
    [
        "enabled: yes-please",
        "enabled: true\nstall_timeout_s: 0",
        "enabled: true\nstall_timeout_s: -1",
        "enabled: true\nmonthly_budget_usd: 'lots'",
        "enabled: true\nmodel: ''",
        "enabled: true\nsession_max_s: false",
    ],
)
def test_wrong_types_and_impossible_values_refuse(tmp_path: Path, body: str) -> None:
    path = tmp_path / "realtime.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(RealtimeConfigError):
        load_realtime_config(path)


def test_a_valid_config_round_trips_every_field(tmp_path: Path) -> None:
    path = tmp_path / "realtime.yaml"
    path.write_text(
        "enabled: true\nmodel: gpt-realtime-2.1-mini\nvoice: marin\n"
        "stall_timeout_s: 6.5\nsession_max_s: 1800\nmonthly_budget_usd: 40\n",
        encoding="utf-8",
    )
    config = load_realtime_config(path)
    assert config.enabled is True
    assert config.model == "gpt-realtime-2.1-mini"
    assert config.voice == "marin"
    assert config.stall_timeout_s == 6.5
    assert config.session_max_s == 1_800.0
    assert config.monthly_budget_usd == 40.0
    assert config.present is True


def test_an_empty_config_body_is_present_but_disabled(tmp_path: Path) -> None:
    path = tmp_path / "realtime.yaml"
    path.write_text("", encoding="utf-8")
    config = load_realtime_config(path)
    assert config.present is True
    assert config.enabled is False


def test_a_non_mapping_config_body_refuses() -> None:
    with pytest.raises(RealtimeConfigError):
        realtime_config_from_mapping(["enabled"])  # type: ignore[arg-type]


def test_the_repo_ships_no_realtime_config_so_flag_off_is_file_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    assert not (REPO / "configs" / "realtime.yaml").exists()
    assert resolve_realtime_config_path() is None


# =================================================================== ledger
def test_the_messages_schema_change_is_purely_additive() -> None:
    memory = ConversationMemory(":memory:")
    columns = {
        row[1]: row for row in memory.connection.execute("PRAGMA table_info(messages)").fetchall()
    }
    for name, _type in REALTIME_COLUMNS:
        assert name in columns
        assert columns[name][3] == 0, f"{name} must be NULLABLE"
        assert columns[name][4] is None, f"{name} must have no default"
    # Every pre-existing reader keeps working, unchanged.
    memory.add("user", "typed command")
    memory.add("assistant", "typed reply")
    assert memory.recent(2) == [
        {"role": "user", "content": "typed command"},
        {"role": "assistant", "content": "typed reply"},
    ]


def test_the_migration_upgrades_a_pre_existing_database(tmp_path: Path) -> None:
    """The live parcel_memory.sqlite3 predates these columns. It must survive."""

    path = tmp_path / "legacy.sqlite3"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT NOT NULL, "
        "content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    legacy.execute("INSERT INTO messages(role, content) VALUES ('user', 'older turn')")
    legacy.commit()
    legacy.close()

    memory = ConversationMemory(path)
    assert memory.recent(1) == [{"role": "user", "content": "older turn"}]
    memory.write_realtime_turn(
        session_id="s1", speaker="owner", text="a hosted turn", origin="realtime"
    )
    assert [row["content"] for row in memory.realtime_turns()] == ["a hosted turn"]
    # Re-opening the same file must not attempt the ALTER a second time.
    again = ConversationMemory(path)
    assert len(again.realtime_turns()) == 1


def test_legacy_rows_are_never_replayed_to_the_provider_as_hosted_history() -> None:
    memory = ConversationMemory(":memory:")
    memory.add("user", "a typed command from the panel")
    memory.write_realtime_turn(
        session_id="s", speaker="owner", text="a spoken one", origin="realtime"
    )
    assert [row["content"] for row in memory.realtime_turns()] == ["a spoken one"]


def test_the_ledger_refuses_an_unreviewed_speaker_or_empty_text() -> None:
    memory = ConversationMemory(":memory:")
    with pytest.raises(ValueError):
        memory.write_realtime_turn(session_id="s", speaker="oracle", text="hi", origin="realtime")
    with pytest.raises(ValueError):
        memory.write_realtime_turn(session_id="s", speaker="owner", text="   ", origin="realtime")


# ================================================= the runtime, end to end
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
    """If this is ever consulted for a hosted transcript, the lane leaked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context
        self.calls.append(str(transcript))
        return AgentDecision("Understood.")


def _runtime(tmp_path: Path, model: _SilentModel | None = None) -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "r1-realtime.yaml"
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
        language_model=model or _SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r1 realtime fixture",
        ),
    )


def _spy(runtime: RobotRuntime, name: str) -> list[tuple]:
    """Record calls to one runtime/session method WITHOUT suppressing it."""

    owner = runtime if hasattr(runtime, name) else runtime.voice_session
    original = getattr(owner, name)
    calls: list[tuple] = []

    def wrapper(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    setattr(owner, name, wrapper)
    return calls


def test_flag_off_leaves_the_lane_unconstructed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S6. Absent config file ⇒ nothing new exists in the runtime at all."""

    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        assert runtime.realtime_lane is None
        assert runtime.realtime_config.enabled is False
        assert runtime.realtime_config.source == "absent"
        # And the pre-existing voice path is exactly what it was.
        assert runtime.submit_voice_text("hello there") == 1
        assert runtime.voice_session.wait_until_idle(3.0)
    finally:
        runtime.close()


def test_flag_on_constructs_the_lane_and_wires_it_to_the_restricted_ingress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nvoice: marin\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        lane = runtime.realtime_lane
        assert lane is not None
        assert lane.config.voice == "marin"
        assert lane._ingress == runtime.submit_realtime_transcript
        # No transport exists in R1, so the gate refuses — fail closed, loudly.
        decision = lane.arm(handshake_token="csrf", mic_gesture=True)
        assert decision.armed is False
        assert decision.code == CODE_NO_TRANSPORT
    finally:
        runtime.close()


def test_the_transcript_origin_is_registered_and_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    assert TRANSCRIPT_ORIGINS == {
        TRANSCRIPT_ORIGIN_MIC,
        TRANSCRIPT_ORIGIN_PANEL,
        TRANSCRIPT_ORIGIN_REALTIME,
    }
    lane = RealtimeLane(config=RealtimeConfig(source="absent"), instructions="x")
    assert lane._transcript_origin == TRANSCRIPT_ORIGIN_REALTIME


def test_submit_voice_text_refuses_the_hosted_origin_outright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Binding constraint 1, enforced at the door rather than by convention."""

    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        with pytest.raises(ValueError) as caught:
            runtime.submit_voice_text("hello", origin=TRANSCRIPT_ORIGIN_REALTIME)
        assert "submit_realtime_transcript" in str(caught.value)
    finally:
        runtime.close()


def test_a_punctuated_stop_latches_the_emergency_stop_through_the_ingress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S1. "Stop." is what a hosted transcriber writes. It must halt."""

    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    submits = _spy(runtime, "submit_text")
    try:
        assert runtime.agent.safety.emergency_stopped is False
        outcome = runtime.submit_realtime_transcript("Stop.", item_id="item_1", session_id="s1")
        assert runtime.agent.safety.emergency_stopped is True
        assert outcome.kind == "emergency"
        assert outcome.executed is True
        assert outcome.transcript == "Stop", "the ACTED-ON text is the normalized one"
        assert submits == [], "the hosted lane must never touch the voice session's front door"
        # The record keeps the sentence as spoken; normalization is for matching.
        assert runtime.agent.memory.realtime_turns()[0]["content"] == "Stop."
    finally:
        runtime.close()


@pytest.mark.parametrize("phrase", ["Stop.", "stop now!", "Emergency stop.", "Halt!"])
def test_every_punctuated_emergency_phrase_halts_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phrase: str
) -> None:
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path / phrase.replace(" ", "_").replace("!", "").replace(".", ""))
    try:
        runtime.submit_realtime_transcript(phrase)
        assert runtime.agent.safety.emergency_stopped is True
    finally:
        runtime.close()


def test_follow_me_executes_once_and_never_reaches_the_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2. One utterance, one authority, and no second reply from the local agent."""

    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    model = _SilentModel()
    runtime = _runtime(tmp_path, model)
    behaviors = _spy(runtime, "set_behavior")
    agent_calls = _spy(runtime, "handle_text")
    submits = _spy(runtime, "submit_text")
    try:
        outcome = runtime.submit_realtime_transcript("follow me.")
        assert outcome.kind == "follow"
        assert outcome.executed is True
        assert [call[0] for call in behaviors] == [("follow",)], "exactly once"
        assert agent_calls == [], "the local agent must not run a hosted turn"
        assert submits == [], "no epoch bump, no barge-in, no duplex turn"
        assert model.calls == [], "the local conversation model must never be consulted"
    finally:
        runtime.close()


def test_stay_takes_the_hold_door_and_come_takes_the_follow_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    behaviors = _spy(runtime, "set_behavior")
    try:
        assert runtime.submit_realtime_transcript("Stay.").kind == "hold"
        assert runtime.submit_realtime_transcript("Come here.").kind == "closed_intent"
        assert [call[0] for call in behaviors] == [("stay",), ("follow",)]
    finally:
        runtime.close()


def test_a_pause_intent_takes_the_same_executive_cap_as_a_typed_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        outcome = runtime.submit_realtime_transcript("Slow down.")
        assert outcome.kind == "closed_intent"
        assert outcome.name == "slower"
        assert outcome.executed is True
        assert runtime._pace_cap.scale < 1.0, "the pace cap really moved"
    finally:
        runtime.close()


def test_chit_chat_executes_nothing_locally_but_is_still_ledgered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3, at the runtime door: the ledger is the product memory, always on."""

    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    model = _SilentModel()
    runtime = _runtime(tmp_path, model)
    behaviors = _spy(runtime, "set_behavior")
    submits = _spy(runtime, "submit_text")
    try:
        outcome = runtime.submit_realtime_transcript(
            "How was your day?", item_id="item_9", session_id="s9"
        )
        assert outcome.kind == "none"
        assert outcome.executed is False
        assert outcome.narration() == ""
        assert behaviors == []
        assert submits == []
        assert model.calls == []
        assert runtime.agent.safety.emergency_stopped is False
        rows = runtime.agent.memory.realtime_turns()
        assert len(rows) == 1
        assert rows[0]["content"] == "How was your day?"
        assert rows[0]["speaker"] == "owner"
        assert rows[0]["origin"] == TRANSCRIPT_ORIGIN_REALTIME
        assert rows[0]["provider_item_id"] == "item_9"
    finally:
        runtime.close()


def test_both_sides_land_in_the_ledger_for_a_full_hosted_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3, wired the way it actually ships: runtime ingress + lane writer."""

    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        rig = _Rig(
            handshake() + happy_turn(heard="how was your day", reply="Warm and quiet."),
            ledger=runtime.agent.memory,
            ingress=runtime.submit_realtime_transcript,
        )
        rig.open()
        rig.speak()
        rows = runtime.agent.memory.realtime_turns()
        assert [(row["speaker"], row["content"]) for row in rows] == [
            ("owner", "how was your day"),
            ("robot", "Warm and quiet."),
        ]
        assert rig.lane.outcomes[0].executed is False
    finally:
        runtime.close()


def test_a_hosted_command_is_narrated_back_to_the_model_after_the_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent narrates what happened; it never decides it."""

    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        rig = _Rig(
            handshake() + happy_turn(heard="Stay.", reply="Right here."),
            ledger=runtime.agent.memory,
            ingress=runtime.submit_realtime_transcript,
        )
        rig.open()
        rig.speak()
        reports = [
            frame
            for frame in rig.lane.transport.sent  # type: ignore[union-attr]
            if frame.get("type") == "conversation.item.create"
            and frame["item"].get("role") == "system"
        ]
        assert len(reports) == 1
        assert "'hold'" in reports[0]["item"]["content"][0]["text"]
    finally:
        runtime.close()


def test_an_ingress_failure_never_takes_down_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)

    def _explode(text, *, item_id=None, session_id=None):
        raise RuntimeError("boom")

    memory = ConversationMemory(":memory:")
    rig = _Rig(handshake() + happy_turn(), ledger=memory, ingress=_explode)
    rig.open()
    rig.speak()
    assert rig.lane.active
    assert any("ingress refused" in note for note in rig.lane.events)
    assert [row["speaker"] for row in memory.realtime_turns()] == ["owner", "robot"]


def test_an_empty_or_oversized_hosted_transcript_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        with pytest.raises(ValueError):
            runtime.submit_realtime_transcript("   ...   ")
        with pytest.raises(ValueError):
            runtime.submit_realtime_transcript("word " * 500)
    finally:
        runtime.close()
