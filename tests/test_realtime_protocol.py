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
    PCM16_SAMPLE_RATE_HZ,
    SERVER_EVENT_TYPES,
    ConversationItemCreate,
    ConversationItemTruncate,
    ErrorEvent,
    FunctionCallArgumentsDone,
    FunctionCallOutput,
    InputAudioBufferAppend,
    InputTranscriptionCompleted,
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
    assert SERVER_EVENT_TYPES == REQUIRED_SERVER_EVENTS
    assert CLIENT_EVENT_TYPES == REQUIRED_CLIENT_EVENTS


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
    assert payload["session"]["input_audio_transcription"] is not None
    assert payload["session"]["instructions"] == "be a good dog"
    assert payload["session"]["turn_detection"] == {"type": "server_vad"}


def test_session_update_states_the_output_sample_rate() -> None:
    payload = SessionUpdate(instructions="x", model="m", voice="v").to_payload()
    audio = payload["session"]["audio"]["output"]
    assert audio["format"] == "pcm16"
    assert audio["sample_rate_hz"] == PCM16_SAMPLE_RATE_HZ == 24_000


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
