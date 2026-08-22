"""Card TURN-1: endpointing is a knob, and turning it costs nothing when nobody does.

WHAT THIS FILE PINS
-------------------
Before this card, ``session.audio.input.turn_detection`` was the string literal
``"server_vad"`` inside ``realtime/protocol.py``. The provider's ~500 ms silence
tail was therefore not a setting but a property of the source, and every pause
longer than it ended the owner's turn mid-sentence.

The card's first requirement is the one that is easy to break and hard to
notice: **a config that says nothing about endpointing must produce the exact
frame this repo has sent since 2026-08-18.** That is pinned here as a byte
literal (``SERVER_VAD_FRAME``) rather than recomputed from the code under test,
because a payload check that builds its own expectation passes for a bug too.

Everything else is refusals with reasons: a ``silence_duration_ms`` outside the
band it was measured for, an eagerness the provider does not take, and — the
one this repo has been bitten by before — a knob sent to an endpointer that
does not read it. On 2026-08-18 every session ever opened had run with its voice
and its VAD silently discarded because both were sent at the wrong level of the
session object. A ``threshold`` under ``semantic_vad`` is that defect again, one
layer down, so it is a refusal and not a shrug.

TIME IS INJECTED
----------------
The timing rows use the same hand-advanced ``_Clock`` the R1 lane tests use.
No sleeps, no wall clock: a stopwatch measured against a real clock in a unit
test is a flake, and a flaky measurement is worse than none.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.realtime.config import (
    TURN_DETECTION_ALLOWED_KEYS,
    RealtimeConfig,
    RealtimeConfigError,
    realtime_config_from_mapping,
    turn_detection_from_mapping,
)
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    audio_delta,
    audio_done,
    barge_in_turn,
    handshake,
    happy_turn,
    pcm_tone,
    response_done,
    session_created,
    speech_started,
    speech_stopped,
)
from parcel_robot.realtime.lane import (
    LIFECYCLE_RESPONSE_CREATED,
    RESPONSE_FROM_SYSTEM,
    RealtimeLane,
)
from parcel_robot.realtime.protocol import (
    SILENCE_DURATION_MS_RANGE,
    TURN_DETECTION_EAGERNESS,
    TURN_DETECTION_TYPES,
    RealtimeProtocolError,
    SessionUpdate,
    TurnDetection,
)
from parcel_robot.realtime.transport import transport_pair

REPO = Path(__file__).resolve().parents[1]

#: THE FRAME THIS REPO HAS SENT SINCE 2026-08-18, written out.
#:
#: Not ``TurnDetection().to_payload()`` — that would compare the code under test
#: to itself. This literal is what was captured from HEAD ``8862220`` before the
#: first line of card TURN-1 was written.
SERVER_VAD_FRAME: dict[str, Any] = {"type": "server_vad"}

#: ``RealtimeConfig().as_dict()`` at HEAD ``8862220``, captured before this card.
#: The pre-registered row is "+1 key, 0 changed", and a set literal is the only
#: way to say that without asking the new code what the old code used to do.
HEAD_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "capture",
        "enabled",
        "hosted_affect",
        "idle_close_after_s",
        "mode",
        "model",
        "monthly_budget_usd",
        "persona",
        "proactive_motion_tools",
        "session_max_s",
        "si_profile",
        "source",
        "stall_timeout_s",
        "unknown_place",
        "voice",
        "voice_identity",
        "whisperer",
    }
)


def _load_replay_tool() -> Any:
    """``tools/replay_turn_detection.py``, imported by path.

    By path rather than by package because ``tools/`` is a folder of scripts the
    owner runs and deliberately not an importable package — but the harness the
    measurement will be taken with still has to be tested, or the numbers it
    produces are un-auditable.
    """

    path = REPO / "tools" / "replay_turn_detection.py"
    spec = importlib.util.spec_from_file_location("_turn1_replay_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    """Enough of ``SpeakerSink`` for the playback bridge and the timings."""

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
    """A lane on a scripted socket, with a clock the test moves."""

    def __init__(self, script: list[Step], *, config: RealtimeConfig | None = None) -> None:
        self.clock = _Clock()
        self.script = script
        self.servers: list[FakeRealtimeServer] = []
        self.sink = _FakeSink(self.clock)
        self.lane = RealtimeLane(
            config=config or RealtimeConfig(enabled=True, source="test"),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=self.sink,
            clock=self.clock,
            session_id_factory=lambda: "rt_turn1",
        )

    def _factory(self):
        lane_end, server_end = transport_pair(clock=self.clock)
        self.servers.append(
            FakeRealtimeServer(transport=server_end, script=list(self.script), clock=self.clock)
        )
        return lane_end

    def open(self) -> str:
        session = self.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
        self.step()
        return session

    def step(self) -> None:
        self.servers[-1].pump()
        self.lane.pump()

    def speak(self, ms: int = 100) -> None:
        self.lane.send_audio(pcm_tone(ms, seed=3))
        self.step()

    def sent(self) -> list[dict[str, Any]]:
        transport = self.lane.transport
        assert transport is not None
        return [dict(frame) for frame in transport.sent]  # type: ignore[attr-defined]


def _lifecycle(type_name: str) -> dict[str, Any]:
    """One lifecycle frame, which the codec parses to a no-op event."""

    return {"type": type_name}


def _timed_turn_script() -> list[Step]:
    """A turn whose three milestones arrive on three separate client frames.

    Separate frames because the rig's clock only moves when the TEST moves it,
    and a stopwatch proven against three simultaneous events proves nothing.
    """

    return [
        Step("session.update", (session_created("sess_turn1"),), label="handshake"),
        Step(
            "input_audio_buffer.append",
            (speech_started(0), speech_stopped(2_400)),
            label="owner_spoke",
        ),
        Step(
            "input_audio_buffer.append",
            (_lifecycle(LIFECYCLE_RESPONSE_CREATED),),
            label="provider_committed",
        ),
        Step(
            "input_audio_buffer.append",
            (
                audio_delta("resp_1", "item_1", pcm_tone(100)),
                audio_delta("resp_1", "item_1", pcm_tone(100)),
                audio_delta("resp_1", "item_1", pcm_tone(100)),
                audio_done("resp_1", "item_1"),
                response_done("resp_1"),
            ),
            label="provider_answered",
        ),
    ]


# ================================================ T1 — the payload is identical
def test_absent_turn_detection_renders_the_frame_this_repo_has_always_sent() -> None:
    """The row the whole card rests on: a knob nobody turned changes nothing."""

    bare = SessionUpdate(instructions="i", model="m", voice="v").to_payload()
    explicit = SessionUpdate(
        instructions="i", model="m", voice="v", turn_detection=TurnDetection()
    ).to_payload()
    from_config = SessionUpdate(
        instructions="i",
        model="m",
        voice="v",
        turn_detection=realtime_config_from_mapping({}).turn_detection,
    ).to_payload()

    for name, payload in (("bare", bare), ("explicit", explicit), ("from_config", from_config)):
        detection = payload["session"]["audio"]["input"]["turn_detection"]
        assert detection == SERVER_VAD_FRAME, f"{name} moved the endpointing frame"
    assert json.dumps(bare) == json.dumps(explicit) == json.dumps(from_config), (
        "the three ways of not asking for endpointing must serialize identically, "
        "key order included — the provider is handed bytes, not a dict"
    )


def test_a_turn_detection_that_is_set_reaches_the_wire_whole() -> None:
    payload = SessionUpdate(
        instructions="i",
        model="m",
        voice="v",
        turn_detection=TurnDetection(
            type="semantic_vad", eagerness="low", interrupt_response=True
        ),
    ).to_payload()
    assert payload["session"]["audio"]["input"]["turn_detection"] == {
        "type": "semantic_vad",
        "eagerness": "low",
        "interrupt_response": True,
    }


def test_only_keys_the_operator_set_appear_in_the_object() -> None:
    """``None`` means "not sent", never "send the provider's default"."""

    detection = TurnDetection(silence_duration_ms=700)
    assert detection.to_payload() == {"type": "server_vad", "silence_duration_ms": 700}
    assert "threshold" not in detection.to_payload()
    assert "create_response" not in detection.to_payload()


# ================================================= T2 — the config adds one key
def test_the_config_gains_exactly_one_key_and_changes_none() -> None:
    now = RealtimeConfig().as_dict()
    added = set(now) - HEAD_CONFIG_KEYS
    assert added == {"turn_detection"}, f"unexpected /api/state churn: {sorted(added)}"
    assert not HEAD_CONFIG_KEYS - set(now), "a key /api/state used to carry disappeared"
    assert now["turn_detection"] == SERVER_VAD_FRAME


def test_a_config_file_with_no_turn_detection_block_loads_the_default() -> None:
    assert realtime_config_from_mapping({}).turn_detection == TurnDetection()
    assert turn_detection_from_mapping(None) == TurnDetection()


# ============================================== T3 — the silence band, exactly
@pytest.mark.parametrize("value", [SILENCE_DURATION_MS_RANGE[0], 400, SILENCE_DURATION_MS_RANGE[1]])
def test_silence_duration_inside_the_band_is_accepted(value: int) -> None:
    config = realtime_config_from_mapping({"turn_detection": {"silence_duration_ms": value}})
    assert config.turn_detection.silence_duration_ms == value


@pytest.mark.parametrize(
    "value",
    [SILENCE_DURATION_MS_RANGE[0] - 1, SILENCE_DURATION_MS_RANGE[1] + 1, 0, -200, 5_000],
)
def test_silence_duration_outside_the_band_is_refused(value: int) -> None:
    with pytest.raises(RealtimeConfigError) as error:
        realtime_config_from_mapping({"turn_detection": {"silence_duration_ms": value}})
    assert "silence_duration_ms" in str(error.value)
    assert str(SILENCE_DURATION_MS_RANGE[0]) in str(error.value), (
        "a refusal that does not name the band it enforces makes the operator guess"
    )


# ================================================================ T4 — the enums
@pytest.mark.parametrize("kind", TURN_DETECTION_TYPES)
def test_both_endpointers_are_accepted(kind: str) -> None:
    assert realtime_config_from_mapping({"turn_detection": {"type": kind}}).turn_detection.type == (
        kind
    )


@pytest.mark.parametrize("kind", ["sever_vad", "semantic", "vad", "", "server_vad "])
def test_a_mistyped_endpointer_is_refused(kind: str) -> None:
    with pytest.raises(RealtimeConfigError):
        realtime_config_from_mapping({"turn_detection": {"type": kind}})


@pytest.mark.parametrize("eagerness", TURN_DETECTION_EAGERNESS)
def test_every_eagerness_the_provider_documents_is_accepted(eagerness: str) -> None:
    config = realtime_config_from_mapping(
        {"turn_detection": {"type": "semantic_vad", "eagerness": eagerness}}
    )
    assert config.turn_detection.eagerness == eagerness


@pytest.mark.parametrize("eagerness", ["eager", "LOW", "fastest", ""])
def test_an_eagerness_the_provider_does_not_take_is_refused(eagerness: str) -> None:
    with pytest.raises(RealtimeConfigError):
        realtime_config_from_mapping(
            {"turn_detection": {"type": "semantic_vad", "eagerness": eagerness}}
        )


# ==================================== T5 — a knob that cannot take effect refuses
@pytest.mark.parametrize(
    "body",
    [
        {"eagerness": "low"},
        {"type": "server_vad", "eagerness": "auto"},
        {"type": "semantic_vad", "threshold": 0.5},
        {"type": "semantic_vad", "prefix_padding_ms": 300},
        {"type": "semantic_vad", "silence_duration_ms": 400},
    ],
)
def test_a_knob_the_chosen_endpointer_never_reads_is_refused(body: dict[str, Any]) -> None:
    """The 2026-08-18 defect, one layer down.

    The provider ACCEPTS these frames and ignores the key. That is exactly how
    every session before 2026-08-18 ran on the wrong voice and the wrong VAD
    while the repo believed otherwise, and it is why this is a refusal rather
    than a warning nobody reads.
    """

    with pytest.raises(RealtimeConfigError) as error:
        realtime_config_from_mapping({"turn_detection": body})
    assert "not read when" in str(error.value)


@pytest.mark.parametrize(
    "body",
    [
        {"type": "server_vad", "threshold": 0.4, "prefix_padding_ms": 300},
        {"type": "semantic_vad", "eagerness": "high", "create_response": False},
    ],
)
def test_knobs_the_chosen_endpointer_does_read_are_accepted(body: dict[str, Any]) -> None:
    config = realtime_config_from_mapping({"turn_detection": body})
    assert config.turn_detection.to_payload() == {**body}


# ========================================================= T6 — typos and types
def test_an_unknown_key_inside_the_block_names_the_allowed_set() -> None:
    with pytest.raises(RealtimeConfigError) as error:
        realtime_config_from_mapping({"turn_detection": {"silence_durations_ms": 400}})
    message = str(error.value)
    assert "silence_durations_ms" in message
    for key in TURN_DETECTION_ALLOWED_KEYS:
        assert key in message


@pytest.mark.parametrize(
    "body",
    [
        {"silence_duration_ms": True},
        {"silence_duration_ms": "400"},
        {"silence_duration_ms": 400.5},
        {"threshold": float("inf")},
        {"threshold": float("nan")},
        {"threshold": "0.5"},
        {"interrupt_response": "yes"},
        {"create_response": 1},
        {"type": 7},
    ],
)
def test_a_wrong_type_is_a_refusal_not_a_coercion(body: dict[str, Any]) -> None:
    with pytest.raises(RealtimeConfigError):
        realtime_config_from_mapping({"turn_detection": body})


def test_the_block_itself_must_be_a_mapping() -> None:
    with pytest.raises(RealtimeConfigError) as error:
        realtime_config_from_mapping({"turn_detection": ["semantic_vad"]})
    assert "mapping" in str(error.value)


def test_the_wire_object_refuses_on_its_own_too() -> None:
    """The codec is the boundary; the loader is a nicer error message on top."""

    with pytest.raises(RealtimeProtocolError):
        TurnDetection(silence_duration_ms=50)
    with pytest.raises(RealtimeProtocolError):
        TurnDetection(type="semantic", eagerness="low")


# ================================================ the knob reaches the session
def test_the_lane_sends_the_configured_endpointing_on_session_open() -> None:
    config = realtime_config_from_mapping(
        {"enabled": True, "turn_detection": {"type": "semantic_vad", "eagerness": "high"}}
    )
    rig = _Rig(handshake() + happy_turn(), config=config)
    rig.open()
    frames = [f for f in rig.sent() if f.get("type") == "session.update"]
    assert frames, "no session.update reached the socket"
    assert frames[0]["session"]["audio"]["input"]["turn_detection"] == {
        "type": "semantic_vad",
        "eagerness": "high",
    }


def test_a_lane_with_no_endpointing_configured_sends_the_old_frame() -> None:
    rig = _Rig(handshake() + happy_turn())
    rig.open()
    frames = [f for f in rig.sent() if f.get("type") == "session.update"]
    assert frames[0]["session"]["audio"]["input"]["turn_detection"] == SERVER_VAD_FRAME


# ================================================== T7 — the timings themselves
def test_a_spoken_turn_records_when_the_provider_committed_and_when_it_spoke() -> None:
    rig = _Rig(_timed_turn_script())
    rig.open()

    rig.speak()  # speech_started + speech_stopped
    assert rig.lane.turns_timed == 1
    row = rig.lane.turn_timings[0]
    assert row["audio_end_ms"] == 2_400, "the provider's own boundary index is kept"
    assert row["response_created_ms"] is None
    assert row["first_audio_ms"] is None

    rig.clock.advance(0.4)
    rig.speak()  # response.created
    assert rig.lane.turn_timings[0]["response_created_ms"] == pytest.approx(400.0)

    rig.clock.advance(0.15)
    rig.speak()  # the audio
    row = rig.lane.turn_timings[0]
    assert row["first_audio_ms"] == pytest.approx(550.0)
    assert row["first_audio_ms"] >= row["response_created_ms"] >= 0


def test_the_first_audio_stamp_does_not_move_for_later_chunks() -> None:
    """Otherwise the number stops meaning "until the owner heard anything".

    The second batch of audio has to arrive while the row is still OPEN, which
    means before ``response.created``: once both milestones are filled the row
    closes and a later chunk cannot reach it anyway, so a test that only
    delivered audio after the commit would be proving the wrong guard. And
    ``first is not None`` is asserted explicitly — the earlier version of this
    test compared ``None == None`` and passed with the stamp deleted (seed S4).
    """

    script = [
        Step("session.update", (session_created("sess_turn1"),), label="handshake"),
        Step(
            "input_audio_buffer.append",
            (speech_started(0), speech_stopped(2_400)),
            label="owner_spoke",
        ),
        Step(
            "input_audio_buffer.append",
            tuple(audio_delta("resp_1", "item_1", pcm_tone(100)) for _ in range(3)),
            label="first_audio",
        ),
        Step(
            "input_audio_buffer.append",
            tuple(audio_delta("resp_1", "item_1", pcm_tone(100)) for _ in range(3)),
            label="more_audio",
        ),
    ]
    rig = _Rig(script)
    rig.open()
    rig.speak()
    rig.clock.advance(0.4)
    rig.speak()  # the first chunks reach the sink

    first = rig.lane.turn_timings[0]["first_audio_ms"]
    assert first is not None, "the first sink byte was never stamped at all"
    assert first == pytest.approx(400.0)
    chunks_after_first = len(rig.sink.chunks)
    assert chunks_after_first >= 1

    rig.clock.advance(5.0)
    rig.speak()  # more chunks, five seconds later, same still-open row
    assert len(rig.sink.chunks) > chunks_after_first, "the script must deliver more audio"
    assert rig.lane.turn_timings[0]["response_created_ms"] is None, (
        "the row must still be OPEN, or this proves the row-close and not the once-guard"
    )
    assert rig.lane.turn_timings[0]["first_audio_ms"] == first


def test_a_reply_the_owner_never_asked_for_does_not_land_in_a_stale_row() -> None:
    """A milestone with no open turn is not recorded, never recorded as zero."""

    script = [
        Step("session.update", (session_created("sess_turn1"),), label="handshake"),
        Step(
            "input_audio_buffer.append",
            (
                _lifecycle(LIFECYCLE_RESPONSE_CREATED),
                audio_delta("resp_x", "item_x", pcm_tone(100)),
            ),
            label="unprompted",
        ),
    ]
    rig = _Rig(script)
    rig.open()
    rig.speak()
    assert rig.lane.turns_timed == 0
    assert rig.lane.turn_timings == []


def test_a_narration_the_robot_started_cannot_stamp_the_owners_row() -> None:
    """Correction pass. The row-close is not enough on its own.

    A turn answered with TEXT or a tool call only never gets a
    ``first_audio_ms``, so its row stays open. Minutes later the robot narrates
    something by itself, that reply's audio reaches the sink, and without a
    provenance check it lands in the owner's row as a wait of minutes — a
    fabricated number in the middle of the p50 this card grades.
    """

    script = [
        Step("session.update", (session_created("sess_turn1"),), label="handshake"),
        Step(
            "input_audio_buffer.append",
            (speech_started(0), speech_stopped(2_400), _lifecycle(LIFECYCLE_RESPONSE_CREATED)),
            label="owner_turn_answered_without_audio",
        ),
        Step(
            "input_audio_buffer.append",
            tuple(audio_delta("resp_sys", "item_sys", pcm_tone(100)) for _ in range(3)),
            label="the_robots_own_reply",
        ),
    ]
    rig = _Rig(script)
    rig.open()
    rig.speak()
    row = rig.lane.turn_timings[0]
    assert row["response_created_ms"] is not None
    assert row["first_audio_ms"] is None, "no audio has been heard yet"

    # The robot decides to say something itself, four minutes later.
    rig.lane._response_provenance = RESPONSE_FROM_SYSTEM
    rig.clock.advance(240.0)
    rig.speak()
    assert rig.sink.chunks, "the narration must actually have reached the sink"
    assert rig.lane.turn_timings[0]["first_audio_ms"] is None, (
        "a reply nobody asked for is not an answer to the owner's turn"
    )


def test_the_snapshot_publishes_the_endpointing_and_the_waits() -> None:
    rig = _Rig(_timed_turn_script())
    rig.open()
    rig.speak()
    snapshot = rig.lane.snapshot()
    assert snapshot["turn_detection"] == SERVER_VAD_FRAME
    assert snapshot["turns_timed"] == 1
    assert len(snapshot["turn_timings"]) == 1
    assert snapshot["turn_timings"][0]["audio_end_ms"] == 2_400
    # A copy, not the lane's own list: /api/state must not hand a caller a
    # handle it can mutate the lane through.
    snapshot["turn_timings"][0]["audio_end_ms"] = -1
    assert rig.lane.turn_timings[0]["audio_end_ms"] == 2_400


def test_the_retained_rows_are_bounded() -> None:
    script = [Step("session.update", (session_created("sess_turn1"),), label="handshake")]
    script += [
        Step("input_audio_buffer.append", (speech_stopped(index),), label=f"commit{index}")
        for index in range(10)
    ]
    rig = _Rig(script)
    rig.open()
    rig.lane._turn_timing_limit = 3
    for _ in range(10):
        rig.speak()
    assert rig.lane.turns_timed == 10, "the counter is a total and never resets"
    assert len(rig.lane.turn_timings) == 3, "an all-day lane must not grow a list forever"
    assert [row["audio_end_ms"] for row in rig.lane.turn_timings] == [7, 8, 9], (
        "the OLDEST rows are the ones evicted"
    )


# ========================================= T8 — the timing changes no behaviour
def test_the_stopwatch_adds_no_frame_and_no_row_to_a_barge_in() -> None:
    """Card TURN-1 instruments; MARK-1 owns what a barge-in DOES.

    Deliberately asserts only what TURN-1 must not break — that a barge-in
    script produces no client frame this card invented, and that
    ``speech_started`` starts no stopwatch (only ``speech_stopped`` does, and a
    turn the owner is still speaking has not ended). What the interrupt itself
    reports is card MARK-1's row and is asserted in ``test_mark1_*``; coupling
    to it here would make two cards fail together for one card's reason.
    """

    rig = _Rig(handshake() + barge_in_turn())
    rig.open()
    rig.speak()
    rig.clock.advance(0.100)
    rig.speak()
    assert rig.lane.turns_timed == 0, "a turn that has not ended has no wait to measure"
    assert {f.get("type") for f in rig.sent()} <= {
        "session.update",
        "input_audio_buffer.append",
        "response.cancel",
        "conversation.item.truncate",
    }, "the timing code must not put a new frame on the wire"


def test_an_ordinary_turn_sends_exactly_the_frames_it_used_to() -> None:
    """No new client frame; the lifecycle branch is a listener, not a talker."""

    rig = _Rig(handshake() + happy_turn())
    rig.open()
    rig.speak()
    assert [f.get("type") for f in rig.sent()] == [
        "session.update",
        "input_audio_buffer.append",
    ]


# =============================================================== T9 — the tool
def test_the_replay_tool_offers_the_four_arms_the_card_names() -> None:
    tool = _load_replay_tool()
    assert list(tool.ARMS) == [
        "server_vad_default",
        "semantic_low",
        "semantic_auto",
        "semantic_high",
    ]
    control = tool.arm_payload("server_vad_default")
    assert control["session"]["audio"]["input"]["turn_detection"] == SERVER_VAD_FRAME


def test_the_replay_tools_own_checks_all_hold() -> None:
    tool = _load_replay_tool()
    misses = [row for row in tool.offline_checks() if not row.passed]
    assert not misses, [row.row for row in misses]


def test_the_replay_refuses_a_missing_recording_and_names_the_owner_command(
    tmp_path: Path,
) -> None:
    tool = _load_replay_tool()
    with pytest.raises(tool.ReplayRefusal) as error:
        tool.replay(
            arm="semantic_auto",
            recording=tmp_path / "not_recorded",
            live=True,
            settle_s=0.0,
            out=None,
        )
    message = str(error.value)
    assert "OWNER-GATED" in message
    assert "record.sh" in message


def test_the_replay_refuses_to_spend_money_without_being_told_twice(tmp_path: Path) -> None:
    tool = _load_replay_tool()
    recording = tmp_path / "corpus"
    recording.mkdir()
    _write_wav(recording / "01.wav", b"\x00\x00" * 1_600)
    with pytest.raises(tool.ReplayRefusal) as error:
        tool.replay(arm="semantic_auto", recording=recording, live=False, settle_s=0.0, out=None)
    assert "--live" in str(error.value)


def test_the_report_always_carries_the_mid_sentence_count() -> None:
    """The row a tired reporter would leave out is a FIELD, not a remark."""

    tool = _load_replay_tool()
    results = [
        tool.UtteranceResult(utterance_id="01", end_of_speech_ms=1_000.0, commits=[1_500]),
        tool.UtteranceResult(
            utterance_id="02", end_of_speech_ms=1_000.0, commits=[600, 1_500]
        ),
    ]
    for row in results:
        row.commit_latency_ms = row.commits[0] - row.end_of_speech_ms
    summary = tool.summarise("semantic_auto", results)
    assert summary["mid_sentence_commits"] == 1
    assert summary["utterances"] == 2
    assert summary["commit_latency_p50_ms"] is not None
    assert summary["turn_detection"]["type"] == "semantic_vad"


def test_a_recording_at_the_wrong_rate_is_refused_not_resampled(tmp_path: Path) -> None:
    tool = _load_replay_tool()
    path = tmp_path / "01.wav"
    _write_wav(path, b"\x00\x00" * 800, rate=8_000)
    with pytest.raises(tool.ReplayRefusal) as error:
        tool.read_pcm(path)
    assert "8000" in str(error.value)


def test_end_of_speech_finds_the_last_loud_window() -> None:
    tool = _load_replay_tool()
    loud = b"\x00\x40" * 1_600  # 100 ms at 16 kHz, well above the floor
    quiet = b"\x00\x00" * 3_200  # 200 ms of digital silence
    at_16k = {"rate_hz": tool.INPUT_RATE_HZ}
    assert tool.end_of_speech_ms(loud + quiet, **at_16k) == pytest.approx(100.0, abs=20.0)
    assert tool.end_of_speech_ms(quiet, **at_16k) == pytest.approx(200.0, abs=1.0), (
        "a silent recording reports its full length, never a fast commit"
    )
    # The same bytes read at the provider's rate are two thirds as long. That is
    # the 1.5x the replay would have measured with, which is why the rate is a
    # required argument and not a default anyone can forget.
    assert tool.end_of_speech_ms(
        loud + quiet, rate_hz=tool.PROVIDER_RATE_HZ
    ) == pytest.approx(66.7, abs=20.0)


def test_the_plan_writes_twenty_two_clause_utterances(tmp_path: Path) -> None:
    tool = _load_replay_tool()
    assert tool.write_plan(tmp_path) == 0
    rows = (tmp_path / "utterances.tsv").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 21, "a header and the twenty the pre-registration grades"
    assert all("..." in row for row in rows[1:]), "every line must carry the mid-sentence pause"
    assert (tmp_path / "record.sh").stat().st_mode & 0o111


# ============ T9b — the replay actually opens a session, on the right stream
def _scripted_live_lane(tool: Any, arm: str, script: list[Step]) -> tuple[Any, dict[str, Any]]:
    """A lane shaped exactly like ``_build_live_lane``'s, on an in-process pair.

    Same config path, same ``_NullSink``, same ``open_session`` — only the
    transport is swapped, so everything ``replay()`` does to a hosted session it
    does here. ``pump`` is wrapped to drive the fake server first, which is the
    one thing a real socket does for itself.
    """

    from parcel_robot.realtime.lane import RealtimeLane

    holder: dict[str, Any] = {}

    def factory():
        lane_end, server_end = transport_pair()
        holder["server"] = FakeRealtimeServer(transport=server_end, script=list(script))
        return lane_end

    body: dict[str, Any] = {"enabled": True, "mode": "audio"}
    if tool.ARMS[arm]:
        body["turn_detection"] = dict(tool.ARMS[arm])
    config = realtime_config_from_mapping(body, source=f"arm:{arm}")
    lane = RealtimeLane(
        config=config,
        instructions="replay harness",
        transport_factory=factory,
        sink_factory=tool._NullSink,
    )
    original_pump = lane.pump

    def pump() -> int:
        server = holder.get("server")
        if server is not None:
            server.pump()
        return original_pump()

    lane.pump = pump  # type: ignore[method-assign]
    holder["lane"] = lane
    return lane, holder


def _corpus(directory: Path, ids: tuple[str, ...], *, loud_ms: int, total_ms: int) -> None:
    """One 16 kHz WAV per id: ``loud_ms`` of tone, then silence to ``total_ms``."""

    directory.mkdir(parents=True, exist_ok=True)
    loud = b"\x00\x40" * int(16_000 * loud_ms / 1000)
    quiet = b"\x00\x00" * int(16_000 * (total_ms - loud_ms) / 1000)
    for name in ids:
        _write_wav(directory / f"{name}.wav", loud + quiet)


def test_the_replay_opens_a_session_and_the_first_frame_is_the_arm(tmp_path: Path) -> None:
    """The row that was missing: ``replay()`` driven end to end.

    Every G1/G2/G3 command in the status doc and in both config examples goes
    through this call. Before the correction pass it passed
    ``handshake_token=None``, the lane's arming gate refused it
    (``CODE_NO_HANDSHAKE``), and the resulting ``RealtimeLaneError`` was not in
    ``main()``'s except tuple — so the owner's ten minutes of recording would
    have ended in a traceback before one frame went up.
    """

    tool = _load_replay_tool()
    recording = tmp_path / "corpus"
    _corpus(recording, ("01",), loud_ms=60, total_ms=120)
    script = [Step("session.update", (session_created("sess_replay"),), label="handshake")]
    script += [
        Step("input_audio_buffer.append", (), label=f"filler{index}") for index in range(8)
    ]
    lane, holder = _scripted_live_lane(tool, "semantic_low", script)

    out = tmp_path / "results"
    assert (
        tool.replay(
            arm="semantic_low",
            recording=recording,
            live=True,
            settle_s=0.0,
            out=out,
            build_lane=lambda arm: lane,
        )
        == 0
    )

    server = holder["server"]
    assert server.received, "no frame ever reached the socket"
    first = server.received[0]
    assert first["type"] == "session.update", "the session frame must be the first thing up"
    assert first["session"]["audio"]["input"]["turn_detection"] == {
        "type": "semantic_vad",
        "eagerness": "low",
        "interrupt_response": True,
    }, "the arm under test must be the endpointing the session actually declares"
    assert lane.provider_session_id == "sess_replay", "the provider never acknowledged"
    assert any(f["type"] == "input_audio_buffer.append" for f in server.received)
    report = json.loads((out / "semantic_low.json").read_text(encoding="utf-8"))
    assert report["analysis_rate_hz"] == tool.PROVIDER_RATE_HZ


def test_the_replay_streams_at_the_rate_the_provider_assumes(tmp_path: Path) -> None:
    """16 kHz in, 24 kHz on the wire — or the corpus plays at 1.5x."""

    tool = _load_replay_tool()
    recording = tmp_path / "corpus"
    _corpus(recording, ("01",), loud_ms=60, total_ms=120)
    script = [Step("session.update", (session_created("s"),), label="handshake")]
    script += [Step("input_audio_buffer.append", (), label=f"f{i}") for i in range(8)]
    lane, holder = _scripted_live_lane(tool, "server_vad_default", script)
    tool.replay(
        arm="server_vad_default",
        recording=recording,
        live=True,
        settle_s=0.0,
        out=None,
        build_lane=lambda arm: lane,
    )
    appended = [
        f for f in holder["server"].received if f["type"] == "input_audio_buffer.append"
    ]
    sent = sum(len(base64.b64decode(f["audio"])) for f in appended)
    #: 120 ms of audio at 24 kHz mono PCM16 = 120 * 48 bytes. At the array's
    #: 16 kHz it would be 120 * 32, and the provider — which declares no input
    #: format and so assumes 24 kHz — would hear 80 ms of a 120 ms utterance.
    assert sent == pytest.approx(120 * tool.PROVIDER_BYTES_PER_MS, abs=960), (
        f"{sent} bytes went up; the provider hears {sent / 48:.0f} ms, not 120 ms"
    )
    assert all(
        len(base64.b64decode(f["audio"])) <= 960 for f in appended
    ), "one frame must be 20 ms at the PROVIDER's rate, not at the array's"


def test_each_file_gets_its_own_zero_not_the_sessions(tmp_path: Path) -> None:
    """``audio_end_ms`` indexes the whole session; a latency does not.

    Two identical recordings, each 200 ms with speech ending at 100 ms, and the
    provider staged to commit 50 ms after the end of speech in BOTH. The second
    file starts 200 ms into the session's buffer, so its raw ``audio_end_ms`` is
    350. Without ``audio_offset_ms`` it would be reported as a 250 ms tail —
    five times the truth, and worse for every later file.
    """

    tool = _load_replay_tool()
    recording = tmp_path / "corpus"
    _corpus(recording, ("01", "02"), loud_ms=100, total_ms=200)
    # 200 ms at 24 kHz = 9600 bytes = ten 960-byte frames per file.
    script = [Step("session.update", (session_created("s"),), label="handshake")]
    script.append(Step("input_audio_buffer.append", (speech_stopped(150),), label="commit_a"))
    script += [Step("input_audio_buffer.append", (), label=f"a{i}") for i in range(9)]
    script.append(Step("input_audio_buffer.append", (speech_stopped(350),), label="commit_b"))
    script += [Step("input_audio_buffer.append", (), label=f"b{i}") for i in range(9)]
    lane, _holder = _scripted_live_lane(tool, "server_vad_default", script)

    out = tmp_path / "results"
    assert (
        tool.replay(
            arm="server_vad_default",
            recording=recording,
            live=True,
            settle_s=0.0,
            out=out,
            build_lane=lambda arm: lane,
        )
        == 0
    )
    report = json.loads((out / "server_vad_default.json").read_text(encoding="utf-8"))
    rows = {row["utterance_id"]: row for row in report["utterance_rows"]}
    assert rows["01"]["commits_raw_ms"] == [150]
    assert rows["02"]["commits_raw_ms"] == [350]
    assert rows["01"]["audio_offset_ms"] == pytest.approx(0.0, abs=1.0)
    assert rows["02"]["audio_offset_ms"] == pytest.approx(200.0, abs=1.0)
    for name in ("01", "02"):
        assert rows[name]["end_of_speech_ms"] == pytest.approx(100.0, abs=21.0)
        assert rows[name]["commit_latency_ms"] == pytest.approx(50.0, abs=21.0), (
            f"{name}: the staged tail is 50 ms; got {rows[name]['commit_latency_ms']}"
        )
    assert report["commit_latency_p50_ms"] == pytest.approx(50.0, abs=21.0)
    assert report["mid_sentence_commits"] == 0


def test_a_lane_that_refuses_to_arm_is_a_refusal_not_a_traceback(tmp_path: Path) -> None:
    """``main()`` must turn every hosted failure into an exit code and a line."""

    tool = _load_replay_tool()
    recording = tmp_path / "corpus"
    _corpus(recording, ("01",), loud_ms=60, total_ms=120)
    from parcel_robot.realtime.lane import RealtimeLaneError

    assert RealtimeLaneError in tool._live_failure_types()

    def _explode(arm: str) -> Any:
        raise RealtimeLaneError("Realtime lane not armed: no authenticated handshake token.")

    tool._build_live_lane = _explode
    assert (
        tool.main(
            ["--replay", "--live", "--recording", str(recording), "--arm", "semantic_low"]
        )
        == 2
    ), "a lane that will not arm must exit 2, not raise out of main()"


# =============================== the examples document a schema that exists
def _commented_turn_detection_blocks(path: Path) -> list[dict[str, Any]]:
    """Every commented-out ``turn_detection:`` block in one example file.

    A config example is documentation that has to compile. These blocks are
    what an operator will uncomment at 1 a.m.; if one of them names a key the
    loader refuses, the file is a lie and this is where that is caught.
    """

    import yaml

    blocks: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != "# turn_detection:":
            index += 1
            continue
        body = ["turn_detection:"]
        index += 1
        while index < len(lines):
            raw = lines[index]
            if not raw.lstrip().startswith("#"):
                break
            content = raw.lstrip()[1:].removeprefix(" ")
            if not content.strip() or not content.startswith(" "):
                break
            body.append(content)
            index += 1
        blocks.append(yaml.safe_load("\n".join(body)))
    return blocks


@pytest.mark.parametrize(
    "name", ["configs/realtime.yaml.example", "configs/realtime.prototype.yaml.example"]
)
def test_the_shipped_examples_have_no_live_turn_detection_key(name: str) -> None:
    """Copying either example must not change how the robot listens."""

    import yaml

    body = yaml.safe_load((REPO / name).read_text(encoding="utf-8"))
    assert "turn_detection" not in body, (
        "the endpointing block ships COMMENTED: the prototype default is "
        "pre-registered to come from the owner's recording, and a value guessed "
        "in a config file is how robot.yaml ended up with an endpointer that "
        "applies to a loop nobody runs"
    )
    assert realtime_config_from_mapping(body, source=name).turn_detection == TurnDetection()


@pytest.mark.parametrize(
    "name", ["configs/realtime.yaml.example", "configs/realtime.prototype.yaml.example"]
)
def test_every_documented_block_actually_validates(name: str) -> None:
    blocks = _commented_turn_detection_blocks(REPO / name)
    assert len(blocks) >= 2, f"{name} should document both endpointers"
    for block in blocks:
        config = realtime_config_from_mapping({**block}, source=name)
        assert config.turn_detection.to_payload()["type"] in TURN_DETECTION_TYPES


def _write_wav(path: Path, pcm: bytes, *, rate: int = 16_000) -> None:
    import wave

    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm)
