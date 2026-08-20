"""Card R1: the Realtime wire codec must fail CLOSED on anything it does not know.

WHY THIS FILE EXISTS
--------------------
The lane's inbound events come from a remote model over a JSON stream. That is
the least trusted boundary in this repo, and every other boundary here already
refuses what it does not recognize: ``providers.py`` refuses unknown ``speech:``
keys, ``submit_voice_text`` refuses unknown transcript origins,
``SafetySupervisor`` refuses tools outside an exact-name allowlist.

The failure mode this pins is quiet, not loud: a codec that returns ``None`` (or
an empty dataclass) for an unrecognized frame lets the lane treat "I did not
understand that" as "nothing happened". A response that never ends, audio that
never plays, or — worst — a barge-in signal that was silently dropped while the
robot kept talking over its owner.
"""

from __future__ import annotations

import base64

import pytest

from parcel_robot.realtime.protocol import (
    CLIENT_EVENT_TYPES,
    CONTENT_TYPE_BY_ROLE,
    LIFECYCLE_EVENT_TYPES,
    PCM16_SAMPLE_RATE_HZ,
    SERVER_EVENT_TYPES,
    ConversationItemCreate,
    ConversationItemTruncate,
    ErrorEvent,
    FunctionCallArgumentsDone,
    FunctionCallOutput,
    InputAudioBufferAppend,
    InputTranscriptionCompleted,
    LifecycleEvent,
    MalformedEvent,
    OutputAudioDelta,
    OutputAudioDone,
    OutputTranscriptDelta,
    OutputTranscriptDone,
    RealtimeProtocolError,
    ResponseCancel,
    ResponseCreate,
    ResponseDone,
    SessionCreated,
    SessionUpdate,
    SpeechStarted,
    SpeechStopped,
    UnknownEventType,
    parse_client_event_type,
    parse_server_event,
)

#: The events the R1 lane depends on. This list IS the contract: an entry
#: leaving it is a lane feature leaving with it.
REQUIRED_SERVER_EVENTS = {
    "session.created",
    "input_audio_buffer.speech_started",
    "input_audio_buffer.speech_stopped",
    "conversation.item.input_audio_transcription.completed",
    "response.output_audio_transcript.delta",
    "response.output_audio_transcript.done",
    "response.output_audio.delta",
    "response.output_audio.done",
    "response.function_call_arguments.done",
    "response.done",
    "error",
}

REQUIRED_CLIENT_EVENTS = {
    "session.update",
    "input_audio_buffer.append",
    "conversation.item.create",
    "conversation.item.truncate",
    "response.create",
    "response.cancel",
}


# ------------------------------------------------------------------ coverage
def test_the_frozen_event_surface_is_exactly_what_r1_needs() -> None:
    """The known surface is the CONSUMED events plus the IGNORED lifecycle ones.

    The lifecycle half was added 2026-08-17 from the first live session: R1's
    codec was written from documentation and refused ten real frames across
    eight types before a word was spoken. Splitting the assertion keeps the
    distinction that matters — ``REQUIRED_SERVER_EVENTS`` are events a lane
    feature depends on, ``LIFECYCLE_EVENT_TYPES`` are events the provider
    narrates and the lane deliberately does nothing with. An unknown type is
    still refused; that is pinned directly below.
    """

    assert SERVER_EVENT_TYPES == REQUIRED_SERVER_EVENTS | set(LIFECYCLE_EVENT_TYPES)
    assert not REQUIRED_SERVER_EVENTS & set(LIFECYCLE_EVENT_TYPES), (
        "an event cannot be both consumed and ignored"
    )
    assert CLIENT_EVENT_TYPES == REQUIRED_CLIENT_EVENTS


def test_every_live_observed_lifecycle_event_parses_to_a_no_op() -> None:
    """Each type below was captured on the wire on 2026-08-17."""

    for name in LIFECYCLE_EVENT_TYPES:
        event = parse_server_event({"type": name, "extra": "ignored"})
        assert isinstance(event, LifecycleEvent)
        assert event.type_name == name


# ------------------------------------------------------------- fail-closed
def test_an_unknown_server_event_type_is_refused_not_ignored() -> None:
    with pytest.raises(UnknownEventType) as caught:
        parse_server_event({"type": "response.telepathy.delta", "delta": "trust me"})
    assert "response.telepathy.delta" in str(caught.value)


def test_an_unknown_client_event_type_is_refused() -> None:
    with pytest.raises(UnknownEventType):
        parse_client_event_type({"type": "session.hypnotize"})


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"type": ""},
        {"type": 7},
        "not a mapping",
        None,
    ],
)
def test_a_frame_without_a_usable_type_is_malformed(payload: object) -> None:
    with pytest.raises(MalformedEvent):
        parse_server_event(payload)


def test_every_refusal_is_one_exception_family() -> None:
    """Callers catch one thing; nothing escapes as a bare KeyError/TypeError."""

    assert issubclass(UnknownEventType, RealtimeProtocolError)
    assert issubclass(MalformedEvent, RealtimeProtocolError)
    assert issubclass(RealtimeProtocolError, ValueError)


def test_a_known_type_missing_a_required_field_is_malformed() -> None:
    with pytest.raises(MalformedEvent):
        parse_server_event(
            {"type": "conversation.item.input_audio_transcription.completed", "item_id": "i1"}
        )


def test_audio_that_is_not_base64_is_malformed_rather_than_empty() -> None:
    """Silently decoding to b"" would present a corrupt frame as a silent one."""

    with pytest.raises(MalformedEvent):
        parse_server_event(
            {
                "type": "response.output_audio.delta",
                "response_id": "r1",
                "item_id": "i1",
                "delta": "!!!not base64!!!",
            }
        )


# --------------------------------------------------------------- server side
def test_session_created_reads_either_shape() -> None:
    nested = parse_server_event({"type": "session.created", "session": {"id": "sess_9"}})
    flat = parse_server_event({"type": "session.created", "session_id": "sess_9"})
    assert nested == flat == SessionCreated(session_id="sess_9")


def test_speech_markers_carry_their_offsets() -> None:
    started = parse_server_event(
        {"type": "input_audio_buffer.speech_started", "audio_start_ms": 320}
    )
    stopped = parse_server_event({"type": "input_audio_buffer.speech_stopped", "audio_end_ms": 980})
    assert started == SpeechStarted(audio_start_ms=320)
    assert stopped == SpeechStopped(audio_end_ms=980)


def test_input_transcription_carries_the_provider_item_id() -> None:
    event = parse_server_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item_owner_4",
            "transcript": "Stop.",
        }
    )
    assert event == InputTranscriptionCompleted(item_id="item_owner_4", transcript="Stop.")


def test_output_transcript_delta_and_done() -> None:
    delta = parse_server_event(
        {
            "type": "response.output_audio_transcript.delta",
            "response_id": "r2",
            "item_id": "i2",
            "delta": "Warm and ",
        }
    )
    done = parse_server_event(
        {
            "type": "response.output_audio_transcript.done",
            "response": {"id": "r2"},
            "item_id": "i2",
            "transcript": "Warm and quiet.",
        }
    )
    assert delta == OutputTranscriptDelta(response_id="r2", item_id="i2", delta="Warm and ")
    assert done == OutputTranscriptDone(
        response_id="r2", item_id="i2", transcript="Warm and quiet."
    )


def test_output_audio_delta_decodes_to_bytes_and_done_closes_it() -> None:
    pcm = bytes(range(64))
    delta = parse_server_event(
        {
            "type": "response.output_audio.delta",
            "response_id": "r3",
            "item_id": "i3",
            "delta": base64.b64encode(pcm).decode("ascii"),
        }
    )
    assert isinstance(delta, OutputAudioDelta)
    assert delta.audio == pcm
    assert parse_server_event(
        {"type": "response.output_audio.done", "response_id": "r3", "item_id": "i3"}
    ) == OutputAudioDone(response_id="r3", item_id="i3")


def test_function_call_arguments_done_is_typed_so_the_broker_can_refuse_it() -> None:
    event = parse_server_event(
        {
            "type": "response.function_call_arguments.done",
            "call_id": "call_7",
            "name": "navigate_to",
            "arguments": '{"place": "the sidewalk"}',
        }
    )
    assert event == FunctionCallArgumentsDone(
        call_id="call_7", name="navigate_to", arguments='{"place": "the sidewalk"}'
    )


def test_response_done_carries_usage_including_the_cached_discount() -> None:
    """Cached input tokens are the entire cost model; losing them loses the case."""

    event = parse_server_event(
        {
            "type": "response.done",
            "response": {
                "id": "r4",
                "status": "completed",
                "usage": {
                    "input_tokens": 1_200,
                    "output_tokens": 300,
                    "input_token_details": {"audio_tokens": 900, "cached_tokens": 1_000},
                    "output_token_details": {"audio_tokens": 250},
                },
            },
        }
    )
    assert isinstance(event, ResponseDone)
    assert event.response_id == "r4"
    assert event.usage.as_dict() == {
        "input_tokens": 1_200,
        "output_tokens": 300,
        "input_audio_tokens": 900,
        "output_audio_tokens": 250,
        "cached_tokens": 1_000,
    }


def test_response_done_without_usage_reports_zeros_not_a_crash() -> None:
    event = parse_server_event({"type": "response.done", "response": {"id": "r5"}})
    assert isinstance(event, ResponseDone)
    assert event.usage.as_dict() == {
        "input_tokens": 0,
        "output_tokens": 0,
        "input_audio_tokens": 0,
        "output_audio_tokens": 0,
        "cached_tokens": 0,
    }


def test_error_frames_survive_both_nesting_shapes() -> None:
    nested = parse_server_event(
        {"type": "error", "error": {"code": "rate_limit_exceeded", "message": "slow down"}}
    )
    assert nested == ErrorEvent(code="rate_limit_exceeded", message="slow down")
    bare = parse_server_event({"type": "error"})
    assert bare == ErrorEvent(code="unknown", message="no message")


# --------------------------------------------------------------- client side
def test_session_update_turns_input_transcription_on() -> None:
    """It is OFF by default at the provider, and off means no owner ledger."""

    payload = SessionUpdate(
        instructions="be a good dog", model="gpt-realtime-2.1", voice="cedar"
    ).to_payload()
    assert payload["type"] == "session.update"
    assert payload["session"]["instructions"] == "be a good dog"
    # 2026-08-18 (card R1.6+R3): the provider refuses `transcription`,
    # `turn_detection` and `voice` at the top level of the session object with
    # `unknown_parameter`, and refuses the WHOLE frame when `session.type` is
    # missing. Verified live; the old shape below was never applied by the
    # provider at all, which is why this assertion moved rather than the code.
    assert payload["session"]["type"] == "realtime"
    audio_input = payload["session"]["audio"]["input"]
    assert audio_input["transcription"] is not None
    assert audio_input["turn_detection"] == {"type": "server_vad"}
    assert payload["session"]["audio"]["output"]["voice"] == "cedar"


def test_session_update_states_the_output_format() -> None:
    """2026-08-18: the RATE is no longer stated on the wire, and must not be.

    ``session.audio.output.sample_rate_hz`` is refused as an unknown parameter
    (pcm16 output is 24 kHz by definition). :data:`PCM16_SAMPLE_RATE_HZ` is
    still the number the lane WAV-wraps with, which is where it was always
    load-bearing.
    """

    payload = SessionUpdate(instructions="x", model="m", voice="v").to_payload()
    audio = payload["session"]["audio"]["output"]
    assert audio["format"] == {"type": "audio/pcm", "rate": PCM16_SAMPLE_RATE_HZ}
    assert "sample_rate_hz" not in audio
    assert PCM16_SAMPLE_RATE_HZ == 24_000


def test_audio_append_is_base64_on_the_wire() -> None:
    payload = InputAudioBufferAppend(audio=b"\x01\x02\x03").to_payload()
    assert base64.b64decode(payload["audio"]) == b"\x01\x02\x03"


def test_conversation_items_refuse_an_unreviewed_role() -> None:
    with pytest.raises(RealtimeProtocolError):
        ConversationItemCreate(role="robot", text="hello")


def test_conversation_item_create_round_trips_a_memory_tail_row() -> None:
    payload = ConversationItemCreate(role="user", text="I like the park").to_payload()
    assert payload["item"]["role"] == "user"
    assert payload["item"]["content"][0]["text"] == "I like the park"


# ------------------------------------------------ card R8: the content types
# The three assertions below are the whole of R6's decisive live finding turned
# into pins. Every one of these values was read off the wire on 2026-08-19 by
# sending all nine (role x content type) pairs down one socket to
# ``gpt-realtime-2.1-mini`` and reading the refusals back — the API is the
# authority here, not documentation and not this repo's earlier guess.
#
# What the guess cost: from R1 to R7 every non-``user`` item carried
# ``{"type": "text"}``, which is accepted for NO role at all. So each session
# open and each reconnect replayed the owner's half of the conversation and
# none of the robot's, and ``narrate_event`` — the delivery channel for every
# mission narration — was a no-op on the wire while the lane counted it as
# delivered. None of it was visible, because nothing pinned the content TYPE.
@pytest.mark.parametrize(
    ("role", "content_type", "refusal_the_provider_returns"),
    [
        ("user", "input_text", "Supported values are: 'input_text' and 'input_audio'"),
        ("system", "input_text", "Invalid value: 'text'. Value must be 'input_text'"),
        ("assistant", "output_text", "Invalid value: 'text'. Value must be 'output_text'"),
    ],
)
def test_each_role_carries_the_content_type_the_provider_accepts(
    role: str, content_type: str, refusal_the_provider_returns: str
) -> None:
    """One role, one content type, verified live. The third column is evidence.

    ``refusal_the_provider_returns`` is the message the API sends when this role
    is given the wrong type. It is carried through the parametrization so that a
    reader who wonders "says who?" has the provider's own sentence in front of
    them rather than a claim.
    """

    payload = ConversationItemCreate(role=role, text="a fact").to_payload()
    content = payload["item"]["content"]
    assert len(content) == 1, "one text part per item"
    assert content[0]["type"] == content_type, (
        f"the provider refuses a {role} item that is not {content_type!r}: "
        f"{refusal_the_provider_returns}"
    )
    assert content[0]["text"] == "a fact"
    assert CONTENT_TYPE_BY_ROLE[role] == content_type


def test_no_role_sends_the_bare_text_type_that_every_role_refuses() -> None:
    """``"text"`` is not a legal content type for ANY role on this API.

    Stated separately from the per-role pins because it is the specific
    regression that ran for seven cards: a single shared "everything that is not
    a user item" branch, sending a value the provider accepts nowhere.
    """

    for role in CONTENT_TYPE_BY_ROLE:
        payload = ConversationItemCreate(role=role, text="x").to_payload()
        assert payload["item"]["content"][0]["type"] != "text", (
            f"{role} items must never carry the bare 'text' content type"
        )


def test_the_content_type_table_covers_exactly_the_roles_the_codec_admits() -> None:
    """A role the codec accepts but the table does not know would raise at send.

    Keeping the admitted-role list and the content-type list as ONE list is what
    makes that impossible: a fourth role cannot be admitted without someone
    stating what it puts on the wire.
    """

    assert set(CONTENT_TYPE_BY_ROLE) == {"user", "assistant", "system"}
    with pytest.raises(RealtimeProtocolError):
        ConversationItemCreate(role="tool", text="hello")


def test_an_item_can_carry_an_event_id_so_a_refusal_can_name_it() -> None:
    """Card R8: the outbound half of per-item attribution.

    The provider echoes this id inside any error frame the item causes, which is
    the difference between "a server error happened" and "the narration you
    counted was thrown away, and here it is".
    """

    tagged = ConversationItemCreate(role="system", text="arrived", event_id="itm7").to_payload()
    assert tagged["event_id"] == "itm7"
    # And it stays optional: an item nobody wants to trace sends no id at all.
    plain = ConversationItemCreate(role="system", text="arrived").to_payload()
    assert "event_id" not in plain


def test_an_error_frame_echoes_the_client_event_id_it_is_about() -> None:
    """The inbound half. Verified live: six refusals, six correct echoes."""

    event = parse_server_event(
        {
            "type": "error",
            "event_id": "event_the_error_itself",
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_value",
                "message": "Invalid value: 'text'. Value must be 'output_text'.",
                "param": "item.content[0].type",
                "event_id": "itm4",
            },
        }
    )
    assert isinstance(event, ErrorEvent)
    assert event.code == "invalid_value"
    assert event.event_id == "itm4", "the refusal must name the item it is about"


def test_the_error_frames_own_id_is_never_mistaken_for_the_echo() -> None:
    """An attribution that is always wrong is worse than no attribution.

    Every error frame carries a top-level ``event_id`` identifying the ERROR.
    Reading that one would hand each refusal a unique id matching nothing the
    lane ever sent — every refusal would then be attributed to a phantom item
    and the real one would never be named.
    """

    event = parse_server_event(
        {"type": "error", "event_id": "event_the_error_itself", "error": {"code": "boom"}}
    )
    assert isinstance(event, ErrorEvent)
    assert event.event_id == "", "an error with no echo attributes to nothing"


def test_an_error_frame_without_an_echo_still_parses_exactly_as_before() -> None:
    """R8 must not change what a pre-R8 error frame decodes to."""

    nested = parse_server_event(
        {"type": "error", "error": {"code": "rate_limit_exceeded", "message": "slow down"}}
    )
    assert nested == ErrorEvent(code="rate_limit_exceeded", message="slow down")
    assert nested.event_id == ""


def test_truncate_carries_played_milliseconds_as_a_whole_number() -> None:
    payload = ConversationItemTruncate(item_id="i9", audio_end_ms=812.7).to_payload()
    assert payload == {
        "type": "conversation.item.truncate",
        "item_id": "i9",
        "content_index": 0,
        "audio_end_ms": 812,
    }


def test_response_create_and_cancel_are_minimal() -> None:
    assert ResponseCreate().to_payload() == {"type": "response.create", "response": {}}
    assert ResponseCancel().to_payload() == {"type": "response.cancel"}
    assert ResponseCancel(response_id="r7").to_payload()["response_id"] == "r7"


def test_function_call_output_is_a_conversation_item() -> None:
    payload = FunctionCallOutput(call_id="c1", output='{"error":"nope"}').to_payload()
    assert payload["type"] == "conversation.item.create"
    assert payload["item"]["type"] == "function_call_output"
    assert payload["item"]["call_id"] == "c1"


def test_every_client_event_serializes_to_a_type_the_codec_admits() -> None:
    events = [
        SessionUpdate(instructions="i", model="m", voice="v"),
        InputAudioBufferAppend(audio=b"\x00\x00"),
        ConversationItemCreate(role="assistant", text="hi"),
        FunctionCallOutput(call_id="c", output="{}"),
        ConversationItemTruncate(item_id="i", audio_end_ms=1),
        ResponseCreate(),
        ResponseCancel(),
    ]
    for event in events:
        assert parse_client_event_type(event.to_payload()) in CLIENT_EVENT_TYPES
