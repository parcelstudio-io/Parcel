"""A scripted stand-in for the OpenAI Realtime server (card R1, task_7).

WHAT THIS IS
------------
R1 ships no live transport and no credentials, so every claim about the lane is
a claim about its behaviour against THIS server. It is deliberately dumb: a
list of :class:`Step` records, each naming the client event that triggers it
and the frames it emits in response. There is no model, no VAD, no timing — the
script says what happens and the test says when.

WHAT IT MUST BE ABLE TO EXPRESS
-------------------------------
The failure modes the design's review named, not just the happy path:

``happy_turn``        owner audio → speech markers → input transcript →
                      N audio deltas + transcript deltas → done + usage
``barge_in_turn``     ``speech_started`` arriving WHILE a response is playing
``silent_stall``      accepts audio, emits nothing at all (the watchdog case)
``disconnect_turn``   emits part of a response, then hangs up
``malformed_turn``    a frame the typed codec must refuse
``function_call_turn`` a tool call, so the R1 refusal stub is testable

A test that only ever drives ``happy_turn`` proves the lane can talk. The other
five are the ones that prove it can survive.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .protocol import PCM16_SAMPLE_RATE_HZ, parse_client_event_type
from .transport import InProcessTransport, TransportClosed

#: Bytes per millisecond of mono PCM16 at the provider's rate.
BYTES_PER_MS = (PCM16_SAMPLE_RATE_HZ * 2) // 1000


def pcm_tone(duration_ms: int, *, seed: int = 1) -> bytes:
    """Deterministic non-silent PCM16 of a given duration.

    Non-silent on purpose: a wrapper bug that drops samples is visible in a
    byte count, but a *rate* bug is only visible if the payload can be told
    apart from padding.
    """

    samples = max(0, int(duration_ms)) * (PCM16_SAMPLE_RATE_HZ // 1000)
    return bytes(
        byte
        for index in range(samples)
        for byte in ((index * seed) % 251, ((index * seed) // 251) % 251)
    )


# ------------------------------------------------------------------- frames
def session_created(session_id: str = "sess_fake_1") -> dict[str, Any]:
    return {"type": "session.created", "session": {"id": session_id}}


def speech_started(audio_start_ms: int = 0) -> dict[str, Any]:
    return {"type": "input_audio_buffer.speech_started", "audio_start_ms": audio_start_ms}


def speech_stopped(audio_end_ms: int = 0) -> dict[str, Any]:
    return {"type": "input_audio_buffer.speech_stopped", "audio_end_ms": audio_end_ms}


def input_transcript(item_id: str, transcript: str) -> dict[str, Any]:
    return {
        "type": "conversation.item.input_audio_transcription.completed",
        "item_id": item_id,
        "transcript": transcript,
    }


def transcript_delta(response_id: str, item_id: str, delta: str) -> dict[str, Any]:
    return {
        "type": "response.output_audio_transcript.delta",
        "response_id": response_id,
        "item_id": item_id,
        "delta": delta,
    }


def transcript_done(response_id: str, item_id: str, transcript: str) -> dict[str, Any]:
    return {
        "type": "response.output_audio_transcript.done",
        "response_id": response_id,
        "item_id": item_id,
        "transcript": transcript,
    }


def audio_delta(response_id: str, item_id: str, pcm: bytes) -> dict[str, Any]:
    return {
        "type": "response.output_audio.delta",
        "response_id": response_id,
        "item_id": item_id,
        "delta": base64.b64encode(pcm).decode("ascii"),
    }


def audio_done(response_id: str, item_id: str) -> dict[str, Any]:
    return {"type": "response.output_audio.done", "response_id": response_id, "item_id": item_id}


def function_call(call_id: str, name: str, arguments: str = "{}") -> dict[str, Any]:
    return {
        "type": "response.function_call_arguments.done",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }


def response_done(
    response_id: str,
    *,
    input_tokens: int = 120,
    output_tokens: int = 64,
    input_audio_tokens: int = 90,
    output_audio_tokens: int = 48,
    cached_tokens: int = 30,
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "type": "response.done",
        "response": {
            "id": response_id,
            "status": status,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "input_token_details": {
                    "audio_tokens": input_audio_tokens,
                    "cached_tokens": cached_tokens,
                },
                "output_token_details": {"audio_tokens": output_audio_tokens},
            },
        },
    }


def error_frame(code: str = "rate_limit_exceeded", message: str = "slow down") -> dict[str, Any]:
    return {"type": "error", "error": {"code": code, "message": message}}


def malformed_frame() -> dict[str, Any]:
    """A frame the typed codec has never heard of. Must be refused, not ignored."""

    return {"type": "response.telepathy.delta", "delta": "trust me"}


# -------------------------------------------------------------------- script
@dataclass(frozen=True)
class Step:
    """One scripted reaction.

    ``trigger`` is the client event type that fires this step, ``"*"`` for any,
    or ``None`` to chain immediately behind the step before it (so one client
    frame can drive several).
    """

    trigger: str | None
    emit: tuple[Mapping[str, Any], ...] = ()
    close_after: bool = False
    label: str = ""


def handshake(session_id: str = "sess_fake_1") -> list[Step]:
    return [Step("session.update", (session_created(session_id),), label="handshake")]


def happy_turn(
    *,
    response_id: str = "resp_1",
    item_id: str = "item_robot_1",
    owner_item_id: str = "item_owner_1",
    heard: str = "how was your day",
    reply: str = "Warm and quiet. Yours?",
    audio_chunks: Sequence[int] = (100, 100, 100),
    trigger: str = "input_audio_buffer.append",
) -> list[Step]:
    """One complete voice-to-voice turn, owner side included."""

    frames: list[Mapping[str, Any]] = [
        speech_started(0),
        speech_stopped(len(heard) * 40),
        input_transcript(owner_item_id, heard),
    ]
    for chunk_ms in audio_chunks:
        frames.append(audio_delta(response_id, item_id, pcm_tone(chunk_ms)))
    frames.append(transcript_delta(response_id, item_id, reply))
    frames.append(transcript_done(response_id, item_id, reply))
    frames.append(audio_done(response_id, item_id))
    frames.append(response_done(response_id))
    return [Step(trigger, tuple(frames), label="happy_turn")]


def barge_in_turn(
    *,
    response_id: str = "resp_barge",
    item_id: str = "item_robot_barge",
    played_chunks: Sequence[int] = (120, 120),
) -> list[Step]:
    """A response in flight, then the owner talks over it.

    Two client frames drive it: the first starts the reply, the second (the
    next audio append) is when server VAD notices the owner.
    """

    started: list[Mapping[str, Any]] = [
        audio_delta(response_id, item_id, pcm_tone(chunk_ms)) for chunk_ms in played_chunks
    ]
    return [
        Step("input_audio_buffer.append", tuple(started), label="barge_in:response"),
        Step("input_audio_buffer.append", (speech_started(1_000),), label="barge_in:owner"),
    ]


def silent_stall() -> list[Step]:
    """Accepts audio and says nothing. The watchdog's whole reason to exist."""

    return [Step("input_audio_buffer.append", (), label="silent_stall")]


def disconnect_turn(
    *,
    response_id: str = "resp_drop",
    item_id: str = "item_robot_drop",
    before_drop_ms: int = 120,
) -> list[Step]:
    return [
        Step(
            "input_audio_buffer.append",
            (audio_delta(response_id, item_id, pcm_tone(before_drop_ms)),),
            close_after=True,
            label="disconnect_mid_turn",
        )
    ]


def malformed_turn() -> list[Step]:
    return [Step("input_audio_buffer.append", (malformed_frame(),), label="malformed")]


def function_call_turn(
    *,
    call_id: str = "call_1",
    name: str = "navigate_to",
    arguments: str = '{"place": "the sidewalk"}',
    response_id: str = "resp_tool",
) -> list[Step]:
    return [
        Step(
            "input_audio_buffer.append",
            (function_call(call_id, name, arguments), response_done(response_id)),
            label="function_call",
        )
    ]


# -------------------------------------------------------------------- server
@dataclass
class FakeRealtimeServer:
    """Drives a :class:`Step` script against one end of a transport pair."""

    transport: InProcessTransport
    script: Sequence[Step]
    clock: Callable[[], float] = time.monotonic
    received: list[Mapping[str, Any]] = field(default_factory=list)
    emitted: list[Mapping[str, Any]] = field(default_factory=list)
    fired: list[str] = field(default_factory=list)
    _cursor: int = 0

    @property
    def exhausted(self) -> bool:
        return self._cursor >= len(self.script)

    def received_types(self) -> list[str]:
        return [str(frame.get("type")) for frame in self.received]

    def frames_of_type(self, event_type: str) -> list[Mapping[str, Any]]:
        return [frame for frame in self.received if frame.get("type") == event_type]

    def pump(self) -> int:
        """Consume every pending client frame; return how many were handled."""

        handled = 0
        while True:
            try:
                frame = self.transport.receive()
            except TransportClosed:
                return handled
            if frame is None:
                return handled
            # A lane that emits an event this protocol build does not define is
            # a lane defect, and the fake server is the only thing that would
            # ever notice. Refuse it loudly rather than script around it.
            parse_client_event_type(frame)
            self.received.append(frame)
            handled += 1
            self._advance(str(frame.get("type")))

    def _advance(self, client_type: str) -> None:
        first = True
        while self._cursor < len(self.script):
            step = self.script[self._cursor]
            if first:
                if step.trigger is None:
                    return
                if step.trigger != "*" and step.trigger != client_type:
                    return
            elif step.trigger is not None:
                return
            self._cursor += 1
            first = False
            self.fired.append(step.label or f"step[{self._cursor - 1}]")
            for payload in step.emit:
                self._emit(payload)
            if step.close_after:
                self.transport.close()
                return

    def _emit(self, payload: Mapping[str, Any]) -> None:
        self.emitted.append(payload)
        try:
            self.transport.send(payload)
        except TransportClosed:
            return


__all__ = [
    "BYTES_PER_MS",
    "FakeRealtimeServer",
    "Step",
    "audio_delta",
    "audio_done",
    "barge_in_turn",
    "disconnect_turn",
    "error_frame",
    "function_call",
    "function_call_turn",
    "handshake",
    "happy_turn",
    "input_transcript",
    "malformed_frame",
    "malformed_turn",
    "pcm_tone",
    "response_done",
    "session_created",
    "silent_stall",
    "speech_started",
    "speech_stopped",
    "transcript_delta",
    "transcript_done",
]
