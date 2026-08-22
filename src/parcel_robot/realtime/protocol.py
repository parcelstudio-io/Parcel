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
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar

#: Sample rate the provider emits and accepts for ``pcm16`` audio. The local
#: ``SpeakerSink`` infers its rate from the first RIFF header and otherwise
#: assumes 16 kHz, so this number has to travel with the bytes.
PCM16_SAMPLE_RATE_HZ = 24_000

#: Discriminator the provider requires inside every ``session.update`` object.
#: Verified live 2026-08-18: a ``session`` without it is refused whole with
#: ``missing_required_parameter``, which means the instructions, the voice and
#: the tool surface in that frame all silently do not apply. Named here so both
#: this module's :class:`SessionUpdate` and the tool broker's session frame read
#: it from one place.
SESSION_OBJECT_TYPE = "realtime"

#: Wire name of the PCM16 audio format object. Paired with
#: :data:`PCM16_SAMPLE_RATE_HZ` inside ``session.audio.output.format``.
PCM16_FORMAT_TYPE = "audio/pcm"

#: Content type each conversation-item ROLE must carry, per role. Card R8.
#:
#: Verified live 2026-08-19 against ``gpt-realtime-2.1-mini`` by sending all
#: nine ``(role x content type)`` pairs down one socket, each tagged with its
#: own client ``event_id``, and reading the refusals back. The provider is
#: exact, it is loud, and it is NOT symmetric:
#:
#: ===========  ==============  =====================================================
#: role         accepted        what the provider says about the other two
#: ===========  ==============  =====================================================
#: ``user``     ``input_text``  "Supported values are: 'input_text' and 'input_audio'"
#: ``system``   ``input_text``  "Invalid value: 'text'. Value must be 'input_text'"
#: ``assistant`` ``output_text`` "Invalid value: 'text'. Value must be 'output_text'"
#: ===========  ==============  =====================================================
#:
#: Before this table every non-``user`` item this lane sent carried ``"text"``
#: and was therefore REFUSED WHOLE. The consequences were silent and had been
#: running since R1: every session open and every reconnect replayed the
#: owner's half of the conversation and none of the robot's, and
#: ``narrate_event`` — the entire delivery channel for mission narration — was
#: a no-op on the wire while the lane still counted a narration. R6 found it in
#: a live trace (``scrum/20260818/task_3/R6_STATUS.md``, "two live findings")
#: and R8 is the card that fixed it.
#:
#: A mapping rather than a conditional expression on purpose: the role list and
#: the content-type list are then the same list, so a fourth role cannot be
#: admitted by ``__post_init__`` without someone stating what it puts on the
#: wire.
CONTENT_TYPE_BY_ROLE: Mapping[str, str] = MappingProxyType(
    {
        "user": "input_text",
        "system": "input_text",
        "assistant": "output_text",
    }
)


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


# ---------------------------------------------------- CARD TURN-1 · endpointing
#: Wire names of the two endpointers the provider offers.
#:
#: ``server_vad`` is an energy VAD: it ends the owner's turn after a fixed
#: silence tail, so a person who pauses to think mid-sentence gets interrupted
#: by arithmetic. ``semantic_vad`` asks the model whether the sentence sounded
#: finished, and takes :attr:`TurnDetection.eagerness` instead of a millisecond
#: count. Which one a companion wants is a matter of taste and of measurement —
#: which is the whole reason this stopped being a string literal.
TURN_DETECTION_SERVER_VAD = "server_vad"
TURN_DETECTION_SEMANTIC_VAD = "semantic_vad"
TURN_DETECTION_TYPES: tuple[str, ...] = (TURN_DETECTION_SERVER_VAD, TURN_DETECTION_SEMANTIC_VAD)

#: How quickly ``semantic_vad`` decides the owner is done. ``low`` waits, ``high``
#: jumps in, ``auto`` is the provider's own balance. ``medium`` is documented by
#: the provider and is accepted here even though card TURN-1's text names only
#: three: refusing a value the provider takes would be a wrong refusal, and this
#: card's whole point is that the owner gets to choose.
TURN_DETECTION_EAGERNESS: tuple[str, ...] = ("low", "medium", "high", "auto")

#: Bound on ``silence_duration_ms``, from card TURN-1: below 200 ms the tail is
#: shorter than the pause inside an ordinary two-clause sentence (the recording
#: protocol uses ~400 ms), and above 800 ms the robot reads as deaf. Outside the
#: band is a typo, and a typo here costs every turn of every session.
SILENCE_DURATION_MS_RANGE: tuple[int, int] = (200, 800)

#: Bound on ``prefix_padding_ms`` — how much audio before the VAD trigger is kept.
#: Zero is legal (keep nothing); past two seconds it is not a padding, it is a
#: mistyped ``silence_duration_ms``.
PREFIX_PADDING_MS_RANGE: tuple[int, int] = (0, 2_000)

#: ``threshold`` is a normalised activation probability, so it lives in [0, 1].
THRESHOLD_RANGE: tuple[float, float] = (0.0, 1.0)

#: Knobs the provider reads only for ``server_vad``, and only for ``semantic_vad``.
#: Sending one to the wrong endpointer is accepted on the wire and then ignored,
#: which is exactly the failure this module was written after: on 2026-08-18 every
#: session before that date ran with its voice and its VAD silently discarded.
#: A switch that cannot take effect is refused here rather than shipped.
SERVER_VAD_ONLY_KEYS: tuple[str, ...] = ("threshold", "prefix_padding_ms", "silence_duration_ms")
SEMANTIC_VAD_ONLY_KEYS: tuple[str, ...] = ("eagerness",)


@dataclass(frozen=True)
class TurnDetection:
    """WHEN THE OWNER'S TURN ENDS — card TURN-1.

    Until this card, endpointing was the string literal ``"server_vad"`` inside
    :meth:`SessionUpdate.to_payload`, and the provider's ~500 ms silence tail was
    therefore not a setting: it was a property of the source code. ``robot.yaml``'s
    ``speech.endpointing: semantic`` (Silero + Smart Turn) applies only to the
    ``--legacy`` local loop and never reached the hosted lane at all.

    EVERY OPTIONAL FIELD DEFAULTS TO ``None``, AND THAT IS THE CONTRACT
    ------------------------------------------------------------------
    ``None`` means "the key is not sent", not "send the provider's default". So
    ``TurnDetection()`` renders exactly ``{"type": "server_vad"}`` — byte-identical
    to the literal it replaced — and a config that says nothing about endpointing
    produces the same session frame it produced before this card existed. That is
    a pre-registered, seeded row (TURN-1 T1/T2), not an intention.

    Validation happens in ``__post_init__`` so the object cannot exist in a shape
    the wire would refuse or, worse, silently ignore. See
    :data:`SERVER_VAD_ONLY_KEYS`.
    """

    type: str = TURN_DETECTION_SERVER_VAD
    #: Energy VAD activation probability, ``server_vad`` only.
    threshold: float | None = None
    #: Audio kept from before the trigger, ``server_vad`` only.
    prefix_padding_ms: int | None = None
    #: Silence tail that ends the turn, ``server_vad`` only.
    silence_duration_ms: int | None = None
    #: ``semantic_vad`` only. See :data:`TURN_DETECTION_EAGERNESS`.
    eagerness: str | None = None
    #: Whether the provider cancels its own in-flight reply when it hears the
    #: owner start talking. The lane ALSO barges in locally (``_on_speech_started``),
    #: so this is the provider's half of the same behaviour and both halves are
    #: wanted; ``False`` leaves the lane as the only one that reacts.
    interrupt_response: bool | None = None
    #: Whether the provider creates a response of its own when it commits the
    #: turn. ``False`` means the lane's watchdog is the only thing that will ever
    #: answer the owner — a real knob with a real footgun, documented in the
    #: shipped example rather than hidden.
    create_response: bool | None = None

    def __post_init__(self) -> None:
        if self.type not in TURN_DETECTION_TYPES:
            raise RealtimeProtocolError(
                f"turn_detection.type must be one of {', '.join(TURN_DETECTION_TYPES)}; "
                f"got {self.type!r}"
            )
        if self.threshold is not None:
            _in_range("threshold", float(self.threshold), THRESHOLD_RANGE)
        if self.prefix_padding_ms is not None:
            _in_range("prefix_padding_ms", int(self.prefix_padding_ms), PREFIX_PADDING_MS_RANGE)
        if self.silence_duration_ms is not None:
            _in_range(
                "silence_duration_ms", int(self.silence_duration_ms), SILENCE_DURATION_MS_RANGE
            )
        if self.eagerness is not None and self.eagerness not in TURN_DETECTION_EAGERNESS:
            raise RealtimeProtocolError(
                f"turn_detection.eagerness must be one of "
                f"{', '.join(TURN_DETECTION_EAGERNESS)}; got {self.eagerness!r}"
            )
        wrong = (
            SEMANTIC_VAD_ONLY_KEYS
            if self.type == TURN_DETECTION_SERVER_VAD
            else SERVER_VAD_ONLY_KEYS
        )
        for key in wrong:
            if getattr(self, key) is None:
                continue
            raise RealtimeProtocolError(
                f"turn_detection.{key} is not read when turn_detection.type is "
                f"{self.type!r}; the provider would accept the frame and ignore the "
                f"knob. Remove it, or change the type."
            )

    def to_payload(self) -> dict[str, Any]:
        """The ``session.audio.input.turn_detection`` object, keys-set-only."""

        payload: dict[str, Any] = {"type": self.type}
        for key in (
            "threshold",
            "prefix_padding_ms",
            "silence_duration_ms",
            "eagerness",
            "interrupt_response",
            "create_response",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload

    def as_dict(self) -> dict[str, Any]:
        """What ``/api/state`` shows: exactly what goes on the wire."""

        return self.to_payload()


def _in_range(key: str, value: float, bounds: tuple[float, float]) -> None:
    """Refuse a knob outside its band, naming the band. Card TURN-1."""

    low, high = bounds
    if not low <= value <= high:
        raise RealtimeProtocolError(
            f"turn_detection.{key} must be between {low} and {high} inclusive; got {value}"
        )


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
    #: Card TURN-1. Was the string ``"server_vad"``; is now the validated object
    #: above. The default renders the identical payload — see :class:`TurnDetection`.
    turn_detection: TurnDetection = TurnDetection()

    def to_payload(self) -> dict[str, Any]:
        session: dict[str, Any] = {
            # 2026-08-18, found live on the FIRST session that checked: without
            # this the provider answers `error{code: missing_required_parameter,
            # message: "Missing required parameter: 'session.type'."}` and
            # DISCARDS the whole frame. R1.5's live test only asserted that a
            # reply arrived, so a session that was running with no instructions
            # at all looked green. See SESSION_OBJECT_TYPE.
            "type": SESSION_OBJECT_TYPE,
            "model": self.model,
            "instructions": self.instructions,
            "output_modalities": ["audio"],
            "audio": {
                # 2026-08-18, live: BOTH ``session.voice`` and
                # ``session.turn_detection`` are refused at the top level with
                # `unknown_parameter`. Every session before this ran on the
                # provider's default voice and default VAD while believing it
                # had set them. They belong to the audio input/output objects.
                "input": {
                    # Card TURN-1: was ``{"type": self.turn_detection}`` with a
                    # string field. ``TurnDetection().to_payload()`` is that dict,
                    # exactly, and every added key is one an operator wrote down.
                    "turn_detection": self.turn_detection.to_payload(),
                    # Same relocation, same reason. Without transcription the
                    # owner's half of every spoken conversation never reaches
                    # the ledger, so a silently-discarded switch here is the
                    # most expensive of the three.
                    "transcription": (
                        {"model": "whisper-1"} if self.input_audio_transcription else None
                    ),
                },
                # ``format`` is an OBJECT carrying its own rate, not the string
                # "pcm16" beside a ``sample_rate_hz`` sibling — both of those
                # were refused live on 2026-08-18 (`invalid_type` and
                # `unknown_parameter`). :data:`PCM16_SAMPLE_RATE_HZ` is still
                # the number the lane WAV-wraps with, which is where it was
                # always load-bearing: the sink reads the rate from the RIFF
                # header and otherwise plays hosted audio 50% slow.
                "output": {
                    "format": {"type": PCM16_FORMAT_TYPE, "rate": PCM16_SAMPLE_RATE_HZ},
                    "voice": self.voice,
                },
            },
        }
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
    """A synthetic history item: memory tail, or a post-hoc action report.

    ``event_id`` is optional and is the lane's handle on its own frame. The
    provider echoes it inside the ``error`` frame it sends when it refuses an
    item (``error.event_id``, verified live 2026-08-19), which is what turns "a
    server error happened at some point" into "the narration you counted was
    dropped, and here it is". Nothing on the wire requires it, so it is only
    emitted when a caller asks for one.
    """

    TYPE: ClassVar[str] = "conversation.item.create"

    role: str
    text: str
    item_id: str | None = None
    event_id: str | None = None

    def __post_init__(self) -> None:
        if self.role not in CONTENT_TYPE_BY_ROLE:
            raise RealtimeProtocolError(f"unsupported conversation item role: {self.role!r}")

    def to_payload(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "type": "message",
            "role": self.role,
            # Card R8, live-verified per role. This was ``input_text`` for user
            # and ``"text"`` for everything else, and ``"text"`` is accepted for
            # no role at all — see :data:`CONTENT_TYPE_BY_ROLE`.
            "content": [{"type": CONTENT_TYPE_BY_ROLE[self.role], "text": self.text}],
        }
        if self.item_id is not None:
            item["id"] = self.item_id
        payload: dict[str, Any] = {"type": self.TYPE, "item": item}
        if self.event_id is not None:
            payload["event_id"] = self.event_id
        return payload


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
class LifecycleEvent(ServerEvent):
    """A frame the provider narrates but the lane does not act on.

    Added 2026-08-17 from the FIRST live session (`gpt-realtime-2.1-mini`).
    R1's codec was written from documentation and knew only the frames the lane
    consumes, so real traffic refused ten frames across eight types before a
    single word was spoken. Every one is response/item lifecycle bookkeeping —
    the content arrives in the transcript, audio and ``response.done`` frames
    the lane already handles.

    Recognizing them is NOT a relaxation of the fail-closed rule. A genuinely
    unknown ``type`` still raises :class:`UnknownEventType`; this list is
    exactly the set observed on the wire, each named so a reader can see why it
    is ignorable. ``_dispatch`` has no branch for this class, so it falls
    through as a deliberate no-op.
    """

    TYPE: ClassVar[str] = ""

    type_name: str


#: Observed live 2026-08-17; capture in the session record. Ignorable because
#: the lane reads content from the transcript/audio/response.done frames.
LIFECYCLE_EVENT_TYPES: tuple[str, ...] = (
    "conversation.item.added",  # an item appeared in the conversation
    "conversation.item.done",  # …and finished
    "response.created",  # a response began; response.done carries the usage
    "response.output_item.added",  # output item envelope open
    "response.output_item.done",  # …closed
    "response.content_part.added",  # content part envelope open
    "response.content_part.done",  # …closed
    "rate_limits.updated",  # quota headroom; not a conversational fact
    # Observed live 2026-08-18, on the first session whose ``session.update``
    # was actually ACCEPTED (see SESSION_OBJECT_TYPE) and the first session
    # that ever declared tools. Neither could appear before those two fixes,
    # which is why R1.5's capture did not contain them.
    "session.updated",  # the provider's ack of our own session.update
    "response.function_call_arguments.delta",  # argument fragments; .done is the event
)


@dataclass(frozen=True)
class RetainedEvent(ServerEvent):
    """A frame the lane does not act on, whose CONTENT is worth keeping.

    Card EV-1, work item 1. :class:`LifecycleEvent` is the right answer for
    envelope bookkeeping — ``response.created`` says nothing a reader wants
    later, so keeping only its name is complete. These are the other kind: the
    frame is still a no-op for the lane, but throwing its payload away throws
    away the only signal an eval has about HOW a transcript was produced.

    THE MEASUREMENT THIS EXISTS BECAUSE OF
    --------------------------------------
    ``evals/20260820/voice_corpus_v1/live_run_1`` recorded 95 protocol refusals
    in ``state.realtime.lane.protocol_errors``, and they are three types:

    ====================================================  =====  ============
    type                                                  count  what it is
    ====================================================  =====  ============
    ``conversation.item.input_audio_transcription.delta``    44  ASR, streaming
    ``input_audio_buffer.committed``                         44  ASR, boundary
    ``conversation.item.truncated``                           7  barge-in ack
    ====================================================  =====  ============

    The 88 ASR frames are the run's only surviving trace of how the owner's
    words were transcribed, and that run's two most expensive findings are both
    about transcription: a Korean broadcast sign-off attributed to the owner,
    and a spoken emergency phrase rendered "Dice out!" and never matched. Both
    were unattributable afterwards because the transcript arrives as ONE
    finished string (:class:`InputTranscriptionCompleted`) with no record of
    what it was assembled from. The deltas are that record.

    WHAT THIS IS NOT
    ----------------
    Not a relaxation of the fail-closed rule: a genuinely unknown ``type``
    still raises :class:`UnknownEventType`. Not a lane change either —
    ``_dispatch`` has no branch for this class, exactly as it has none for
    :class:`LifecycleEvent`, so these frames remain a deliberate no-op. What
    changes is that they stop being counted as protocol REFUSALS (they are
    understood, not rejected) and that their payload survives parsing, so the
    card that teaches the lane to persist them has something to persist.
    """

    TYPE: ClassVar[str] = ""

    type_name: str
    #: Everything the frame carried that this codec understands. Deliberately a
    #: plain mapping rather than a per-type dataclass: the provider adds fields
    #: to ASR frames between releases, and a retained event that silently drops
    #: the new one would be the same defect one layer down.
    #: ``default_factory``, not a bare ``MappingProxyType({})`` — card GATE-0
    #: (``scrum/20260822/task_20``). A shared class-level mappingproxy is a
    #: MUTABLE default as far as ``dataclasses`` is concerned, and CPython <=
    #: 3.11 raises ``ValueError: mutable default <class 'mappingproxy'> for
    #: field fields`` **at import time**. That made ``requires-python >= 3.10``
    #: false on exactly 3.11: the whole realtime package failed to import, and
    #: it was invisible here because the dev venv is 3.14 (which allows it) and
    #: hosted CI never ran. The empty mapping is still immutable and still
    #: shared-by-value; it is now built per instance.
    fields: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


#: Observed live 2026-08-20 (``live_run_1``), refused as unknown until EV-1.
#: The value is the tuple of payload keys retained for that type; a key that is
#: absent from the frame is simply absent from ``fields``.
RETAINED_EVENT_TYPES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        # The streaming ASR transcript. ``delta`` is the fragment; ``item_id``
        # joins it to the ledger row the completed transcript becomes.
        "conversation.item.input_audio_transcription.delta": ("item_id", "delta", "content_index"),
        # The utterance boundary server VAD chose. Pairs with the audio-capture
        # index: this is where the provider decided one turn ended.
        "input_audio_buffer.committed": ("item_id", "previous_item_id"),
        # The lane's own truncate, echoed. R7's barge-in arithmetic is only
        # checkable against this.
        "conversation.item.truncated": ("item_id", "audio_end_ms", "content_index"),
    }
)


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
    """A refusal. ``event_id`` says WHICH of our frames it is about.

    Card R8. The provider echoes the client ``event_id`` of the offending frame
    inside the nested error object — verified live 2026-08-19, where nine
    tagged ``conversation.item.create`` frames produced six refusals and every
    one of them named its own probe. Deliberately read from ``error.event_id``
    and never from the frame's own top-level ``event_id``, which is the id of
    the ERROR and would attribute every refusal to itself.

    Defaults to ``""`` so an error frame that carries no echo — and every error
    frame this codec parsed before R8 — is unchanged.
    """

    TYPE: ClassVar[str] = "error"

    code: str
    message: str
    event_id: str = ""


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
    # ONLY from the nested error object (card R8). The top-level ``event_id``
    # on an error frame identifies the error itself, so reading it here would
    # hand every refusal a unique id that matches nothing the lane ever sent —
    # attribution that is always wrong is worse than none.
    echoed = _text(raw, "event_id", required=False) if isinstance(raw, Mapping) else ""
    return ErrorEvent(
        code=_text(detail, "code", required=False) or "unknown",
        message=_text(detail, "message", required=False) or "no message",
        event_id=echoed,
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

# Lifecycle frames parse to a no-op event rather than raising. Registered from
# LIFECYCLE_EVENT_TYPES so the list above stays the single place a reader looks.
_SERVER_PARSERS.update(
    {
        name: (lambda p, _name=name: LifecycleEvent(type_name=_name))
        for name in LIFECYCLE_EVENT_TYPES
    }
)


def _retain(payload: Mapping[str, Any], name: str, keys: tuple[str, ...]) -> RetainedEvent:
    kept = {key: payload[key] for key in keys if key in payload}
    return RetainedEvent(type_name=name, fields=MappingProxyType(kept))


# Card EV-1. Same registration shape as the lifecycle block above, one line
# lower, so both lists stay the single place a reader looks for "frames the
# lane does not act on". The difference is only what survives parsing.
_SERVER_PARSERS.update(
    {
        name: (lambda p, _name=name, _keys=keys: _retain(p, _name, _keys))
        for name, keys in RETAINED_EVENT_TYPES.items()
    }
)

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
    "CONTENT_TYPE_BY_ROLE",
    "LIFECYCLE_EVENT_TYPES",
    "PCM16_SAMPLE_RATE_HZ",
    "PREFIX_PADDING_MS_RANGE",
    "RETAINED_EVENT_TYPES",
    "SEMANTIC_VAD_ONLY_KEYS",
    "SERVER_EVENT_TYPES",
    "SERVER_VAD_ONLY_KEYS",
    "SESSION_OBJECT_TYPE",
    "SILENCE_DURATION_MS_RANGE",
    "THRESHOLD_RANGE",
    "TURN_DETECTION_EAGERNESS",
    "TURN_DETECTION_SEMANTIC_VAD",
    "TURN_DETECTION_SERVER_VAD",
    "TURN_DETECTION_TYPES",
    "ClientEvent",
    "ConversationItemCreate",
    "ConversationItemTruncate",
    "ErrorEvent",
    "FunctionCallArgumentsDone",
    "FunctionCallOutput",
    "InputAudioBufferAppend",
    "InputTranscriptionCompleted",
    "LifecycleEvent",
    "MalformedEvent",
    "OutputAudioDelta",
    "OutputAudioDone",
    "OutputTranscriptDelta",
    "OutputTranscriptDone",
    "RealtimeProtocolError",
    "ResponseCancel",
    "ResponseCreate",
    "ResponseDone",
    "RetainedEvent",
    "ServerEvent",
    "SessionCreated",
    "SessionUpdate",
    "SpeechStarted",
    "SpeechStopped",
    "TurnDetection",
    "UnknownEventType",
    "Usage",
    "parse_client_event_type",
    "parse_server_event",
]
