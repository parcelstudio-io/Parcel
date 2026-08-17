"""Typed subset of the OpenAI Realtime wire protocol (card R1, task_7).

WHY A TYPED SUBSET AND NOT ``dict``
-----------------------------------
The lane speaks to a remote model over a JSON event stream. Every other
boundary in this repo that accepts remote input fails CLOSED — the config
loader refuses unknown ``speech:`` keys, ``submit_voice_text`` refuses unknown
transcript origins, ``SafetySupervisor`` refuses tools outside an exact-name
allowlist. A hosted-provider event stream is the newest and least trusted of
those boundaries, so it gets the same treatment: an event whose ``type`` this
module does not know is a :class:`UnknownEventType`, not a silently ignored
dict, and an event of a known type missing a required field is a
:class:`MalformedEvent`.

R1 implements only the events the lane actually needs. That is deliberate: the
refusal list is the specification. When R1.5 adds the live WebSocket transport
and the provider emits something new, the lane will say so loudly on the first
event rather than degrade three turns later.

WHAT THIS MODULE DOES NOT DO
----------------------------
No I/O, no base64 of anything but the audio fields, no session state. It is a
pure codec: mappings in, frozen dataclasses out (server side); frozen
dataclasses in, mappings out (client side).
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

#: Sample rate the provider emits and accepts for ``pcm16`` audio. The local
#: ``SpeakerSink`` infers its rate from the first RIFF header and otherwise
#: assumes 16 kHz, so this number has to travel with the bytes.
PCM16_SAMPLE_RATE_HZ = 24_000


class RealtimeProtocolError(ValueError):
    """Base class for every refusal this codec can raise."""


class UnknownEventType(RealtimeProtocolError):
    """The wire carried an event ``type`` this build does not implement."""


class MalformedEvent(RealtimeProtocolError):
    """A known event type arrived without a field the lane requires."""


# --------------------------------------------------------------- client side
@dataclass(frozen=True)
class ClientEvent:
    """Lane → server. Subclasses know their own wire ``type``."""

    TYPE: ClassVar[str] = ""

    def to_payload(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass(frozen=True)
class SessionUpdate(ClientEvent):
    """Instructions, voice, and the two switches R1 depends on.

    ``input_audio_transcription`` is on from the first session: it is OFF by
    default at the provider, and without it the owner's half of every
    conversation never reaches the ledger.
    """

    TYPE: ClassVar[str] = "session.update"

    instructions: str
    model: str
    voice: str
    input_audio_transcription: bool = True
    turn_detection: str = "server_vad"

    def to_payload(self) -> dict[str, Any]:
        session: dict[str, Any] = {
            "model": self.model,
            "voice": self.voice,
            "instructions": self.instructions,
            "output_modalities": ["audio"],
            "audio": {"output": {"format": "pcm16", "sample_rate_hz": PCM16_SAMPLE_RATE_HZ}},
            "turn_detection": {"type": self.turn_detection},
        }
        session["input_audio_transcription"] = (
            {"model": "whisper-1"} if self.input_audio_transcription else None
        )
        return {"type": self.TYPE, "session": session}


@dataclass(frozen=True)
class InputAudioBufferAppend(ClientEvent):
    """One chunk of owner microphone PCM16 going up."""

    TYPE: ClassVar[str] = "input_audio_buffer.append"

    audio: bytes

    def to_payload(self) -> dict[str, Any]:
        return {"type": self.TYPE, "audio": base64.b64encode(self.audio).decode("ascii")}


@dataclass(frozen=True)
class ConversationItemCreate(ClientEvent):
    """A synthetic history item: memory tail, or a post-hoc action report."""

    TYPE: ClassVar[str] = "conversation.item.create"

    role: str
    text: str
    item_id: str | None = None

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant", "system"}:
            raise RealtimeProtocolError(f"unsupported conversation item role: {self.role!r}")

    def to_payload(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "type": "message",
            "role": self.role,
            "content": [
                {
                    "type": "input_text" if self.role == "user" else "text",
                    "text": self.text,
                }
            ],
        }
        if self.item_id is not None:
            item["id"] = self.item_id
        return {"type": self.TYPE, "item": item}


@dataclass(frozen=True)
class FunctionCallOutput(ClientEvent):
    """The tool broker's answer. In R1 it is always a refusal."""

    TYPE: ClassVar[str] = "conversation.item.create"

    call_id: str
    output: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.TYPE,
            "item": {
                "type": "function_call_output",
                "call_id": self.call_id,
                "output": self.output,
            },
        }


@dataclass(frozen=True)
class ConversationItemTruncate(ClientEvent):
    """Tell the server how much of its own audio the owner actually heard.

    Driven by the local sink's playback marks, never by how much was enqueued:
    the point of the event is to make the provider's transcript of its own
    reply agree with what left the speaker.
    """

    TYPE: ClassVar[str] = "conversation.item.truncate"

    item_id: str
    audio_end_ms: int
    content_index: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.TYPE,
            "item_id": self.item_id,
            "content_index": self.content_index,
            "audio_end_ms": int(self.audio_end_ms),
        }


@dataclass(frozen=True)
class ResponseCreate(ClientEvent):
    TYPE: ClassVar[str] = "response.create"

    instructions: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.TYPE, "response": {}}
        if self.instructions is not None:
            payload["response"]["instructions"] = self.instructions
        return payload


@dataclass(frozen=True)
class ResponseCancel(ClientEvent):
    TYPE: ClassVar[str] = "response.cancel"

    response_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.TYPE}
        if self.response_id is not None:
            payload["response_id"] = self.response_id
        return payload


CLIENT_EVENT_TYPES = frozenset(
    {
        SessionUpdate.TYPE,
        InputAudioBufferAppend.TYPE,
        ConversationItemCreate.TYPE,
        ConversationItemTruncate.TYPE,
        ResponseCreate.TYPE,
        ResponseCancel.TYPE,
    }
)


# --------------------------------------------------------------- server side
@dataclass(frozen=True)
class ServerEvent:
    """Server → lane. ``TYPE`` is the wire discriminator."""

    TYPE: ClassVar[str] = ""


@dataclass(frozen=True)
class SessionCreated(ServerEvent):
    TYPE: ClassVar[str] = "session.created"

    session_id: str


@dataclass(frozen=True)
class SpeechStarted(ServerEvent):
    """Server VAD heard the owner start talking. The barge-in trigger."""

    TYPE: ClassVar[str] = "input_audio_buffer.speech_started"

    audio_start_ms: int = 0


@dataclass(frozen=True)
class SpeechStopped(ServerEvent):
    TYPE: ClassVar[str] = "input_audio_buffer.speech_stopped"

    audio_end_ms: int = 0


@dataclass(frozen=True)
class InputTranscriptionCompleted(ServerEvent):
    """The owner's words — from a SEPARATE ASR pass, so: approximate.

    This is the only text of the owner's side the lane ever sees, which is why
    the ledger flags it rather than presenting it as ground truth.
    """

    TYPE: ClassVar[str] = "conversation.item.input_audio_transcription.completed"

    item_id: str
    transcript: str


@dataclass(frozen=True)
class OutputTranscriptDelta(ServerEvent):
    TYPE: ClassVar[str] = "response.output_audio_transcript.delta"

    response_id: str
    item_id: str
    delta: str


@dataclass(frozen=True)
class OutputTranscriptDone(ServerEvent):
    TYPE: ClassVar[str] = "response.output_audio_transcript.done"

    response_id: str
    item_id: str
    transcript: str


@dataclass(frozen=True)
class OutputAudioDelta(ServerEvent):
    TYPE: ClassVar[str] = "response.output_audio.delta"

    response_id: str
    item_id: str
    audio: bytes


@dataclass(frozen=True)
class OutputAudioDone(ServerEvent):
    TYPE: ClassVar[str] = "response.output_audio.done"

    response_id: str
    item_id: str


@dataclass(frozen=True)
class FunctionCallArgumentsDone(ServerEvent):
    TYPE: ClassVar[str] = "response.function_call_arguments.done"

    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Usage:
    """Billed units for one response, as reported by the provider."""

    input_tokens: int = 0
    output_tokens: int = 0
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    cached_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "input_audio_tokens": self.input_audio_tokens,
            "output_audio_tokens": self.output_audio_tokens,
            "cached_tokens": self.cached_tokens,
        }


@dataclass(frozen=True)
class ResponseDone(ServerEvent):
    TYPE: ClassVar[str] = "response.done"

    response_id: str
    status: str = "completed"
    usage: Usage = Usage()


@dataclass(frozen=True)
class ErrorEvent(ServerEvent):
    TYPE: ClassVar[str] = "error"

    code: str
    message: str


# ------------------------------------------------------------------- parsing
def _mapping(payload: object, what: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise MalformedEvent(f"{what} must be a mapping, got {type(payload).__name__}")
    return payload


def _text(payload: Mapping[str, Any], key: str, *, required: bool = True) -> str:
    value = payload.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise MalformedEvent(f"{payload.get('type')!r} requires a string {key!r}")
    return value


def _whole(payload: Mapping[str, Any], key: str, default: int = 0) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MalformedEvent(f"{payload.get('type')!r} requires a number {key!r}")
    return int(value)


def _audio_bytes(payload: Mapping[str, Any]) -> bytes:
    raw = payload.get("delta", payload.get("audio"))
    if isinstance(raw, bytes):
        return raw
    if not isinstance(raw, str):
        raise MalformedEvent(f"{payload.get('type')!r} requires base64 audio")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as error:
        raise MalformedEvent(f"{payload.get('type')!r} audio is not valid base64") from error


def _usage(payload: Mapping[str, Any]) -> Usage:
    raw = payload.get("response")
    usage_map: Mapping[str, Any] = {}
    if isinstance(raw, Mapping) and isinstance(raw.get("usage"), Mapping):
        usage_map = raw["usage"]
    elif isinstance(payload.get("usage"), Mapping):
        usage_map = payload["usage"]
    input_details = usage_map.get("input_token_details")
    audio_in = 0
    cached = 0
    if isinstance(input_details, Mapping):
        audio_in = int(input_details.get("audio_tokens", 0) or 0)
        cached = int(input_details.get("cached_tokens", 0) or 0)
    output_details = usage_map.get("output_token_details")
    audio_out = 0
    if isinstance(output_details, Mapping):
        audio_out = int(output_details.get("audio_tokens", 0) or 0)
    return Usage(
        input_tokens=int(usage_map.get("input_tokens", 0) or 0),
        output_tokens=int(usage_map.get("output_tokens", 0) or 0),
        input_audio_tokens=audio_in,
        output_audio_tokens=audio_out,
        cached_tokens=cached,
    )


def _response_id(payload: Mapping[str, Any]) -> str:
    raw = payload.get("response")
    if isinstance(raw, Mapping) and isinstance(raw.get("id"), str):
        return str(raw["id"])
    return _text(payload, "response_id")


def _parse_session_created(payload: Mapping[str, Any]) -> SessionCreated:
    raw = payload.get("session")
    if isinstance(raw, Mapping) and isinstance(raw.get("id"), str):
        return SessionCreated(session_id=str(raw["id"]))
    return SessionCreated(session_id=_text(payload, "session_id"))


def _parse_error(payload: Mapping[str, Any]) -> ErrorEvent:
    raw = payload.get("error")
    detail = raw if isinstance(raw, Mapping) else payload
    return ErrorEvent(
        code=_text(detail, "code", required=False) or "unknown",
        message=_text(detail, "message", required=False) or "no message",
    )


_SERVER_PARSERS: dict[str, Callable[[Mapping[str, Any]], ServerEvent]] = {
    SessionCreated.TYPE: _parse_session_created,
    SpeechStarted.TYPE: lambda p: SpeechStarted(audio_start_ms=_whole(p, "audio_start_ms")),
    SpeechStopped.TYPE: lambda p: SpeechStopped(audio_end_ms=_whole(p, "audio_end_ms")),
    InputTranscriptionCompleted.TYPE: lambda p: InputTranscriptionCompleted(
        item_id=_text(p, "item_id"),
        transcript=_text(p, "transcript"),
    ),
    OutputTranscriptDelta.TYPE: lambda p: OutputTranscriptDelta(
        response_id=_response_id(p),
        item_id=_text(p, "item_id"),
        delta=_text(p, "delta"),
    ),
    OutputTranscriptDone.TYPE: lambda p: OutputTranscriptDone(
        response_id=_response_id(p),
        item_id=_text(p, "item_id"),
        transcript=_text(p, "transcript"),
    ),
    OutputAudioDelta.TYPE: lambda p: OutputAudioDelta(
        response_id=_response_id(p),
        item_id=_text(p, "item_id"),
        audio=_audio_bytes(p),
    ),
    OutputAudioDone.TYPE: lambda p: OutputAudioDone(
        response_id=_response_id(p),
        item_id=_text(p, "item_id"),
    ),
    FunctionCallArgumentsDone.TYPE: lambda p: FunctionCallArgumentsDone(
        call_id=_text(p, "call_id"),
        name=_text(p, "name"),
        arguments=_text(p, "arguments", required=False),
    ),
    ResponseDone.TYPE: lambda p: ResponseDone(
        response_id=_response_id(p),
        status=(
            str(p["response"].get("status", "completed"))
            if isinstance(p.get("response"), Mapping)
            else "completed"
        ),
        usage=_usage(p),
    ),
    ErrorEvent.TYPE: _parse_error,
}

SERVER_EVENT_TYPES = frozenset(_SERVER_PARSERS)


def parse_server_event(payload: object) -> ServerEvent:
    """Decode one server frame, or refuse it with a typed error.

    Fail-closed by construction: an unrecognized ``type`` raises rather than
    returning ``None``, so a caller cannot accidentally treat "I did not
    understand this frame" as "nothing happened".
    """

    frame = _mapping(payload, "realtime server event")
    raw_type = frame.get("type")
    if not isinstance(raw_type, str) or not raw_type:
        raise MalformedEvent("realtime server event has no string 'type'")
    parser = _SERVER_PARSERS.get(raw_type)
    if parser is None:
        raise UnknownEventType(f"unknown realtime server event type: {raw_type!r}")
    return parser(frame)


def parse_client_event_type(payload: object) -> str:
    """Validate a lane → server frame's ``type`` (used by the fake server)."""

    frame = _mapping(payload, "realtime client event")
    raw_type = frame.get("type")
    if not isinstance(raw_type, str) or not raw_type:
        raise MalformedEvent("realtime client event has no string 'type'")
    if raw_type not in CLIENT_EVENT_TYPES:
        raise UnknownEventType(f"unknown realtime client event type: {raw_type!r}")
    return raw_type


__all__ = [
    "CLIENT_EVENT_TYPES",
    "PCM16_SAMPLE_RATE_HZ",
    "SERVER_EVENT_TYPES",
    "ClientEvent",
    "ConversationItemCreate",
    "ConversationItemTruncate",
    "ErrorEvent",
    "FunctionCallArgumentsDone",
    "FunctionCallOutput",
    "InputAudioBufferAppend",
    "InputTranscriptionCompleted",
    "MalformedEvent",
    "OutputAudioDelta",
    "OutputAudioDone",
    "OutputTranscriptDelta",
    "OutputTranscriptDone",
    "RealtimeProtocolError",
    "ResponseCancel",
    "ResponseCreate",
    "ResponseDone",
    "ServerEvent",
    "SessionCreated",
    "SessionUpdate",
    "SpeechStarted",
    "SpeechStopped",
    "UnknownEventType",
    "Usage",
    "parse_client_event_type",
    "parse_server_event",
]
