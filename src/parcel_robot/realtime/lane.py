"""The Realtime conversational lane (card R1, task_7).

WHAT THIS OWNS
--------------
One hosted voice session and everything that has to be true around it:

* **session lifecycle** — instructions + memory tail up before any audio,
  a watchdog for the silent-stall case, and a 60-minute rollover that takes the
  same reconnect path (the provider was never holding the memory, so a rollover
  is invisible);
* **the playback bridge** — provider PCM16 coalesced to >=240 ms and
  WAV-wrapped at 24 kHz before it reaches ``SpeakerSink``. Both halves are
  load-bearing: the sink infers its rate from the first RIFF header and
  otherwise plays hosted audio at 16 kHz (50% slow), and ``prosody`` returns
  zero accents for chunks under 200 ms;
* **sink ownership** — ``begin_utterance()`` at every hosted response start,
  because the sink latches suppression on ``interrupt()`` and never re-arms on
  ``enqueue``; plus an explicit refusal to enqueue while a DuplexVoiceSession
  output is live, asserted rather than assumed;
* **barge-in** — server VAD ``speech_started`` while a response plays means
  sink interrupt, ``response.cancel``, and ``conversation.item.truncate`` at the
  milliseconds the sink actually PLAYED, so the provider's belief about its own
  reply matches what the owner heard;
* **the ledger** — both sides of every turn, with the provider's item id kept
  as an annotation;
* **the arming gate** — fail-closed, same shape as ``MicArmingDecision``;
* **the tool broker** — which in R1 refuses every call. Tools are R3.

WHAT THIS DELIBERATELY DOES NOT OWN
-----------------------------------
Deciding anything. Hosted transcripts reach the robot only through
``RobotRuntime.submit_realtime_transcript`` — a closed, four-step ingress — and
tool calls are refused outright. The lane relays, plays, ledgers, and reconnects.

A NOTE ON WHAT "STOP" MEANS HERE
--------------------------------
A spoken "stop" during a hosted session is transcribed in the cloud. It is
supplemental. The cloud-independent stop paths — the panel STOP button, the
operator stop, every local watchdog — are untouched by this module and remain
the guarantee.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from parcel_robot.voice_audio import pcm16_wav

from .config import RealtimeConfig
from .ingress import RealtimeTranscriptOutcome
from .protocol import (
    PCM16_SAMPLE_RATE_HZ,
    ConversationItemCreate,
    ConversationItemTruncate,
    ErrorEvent,
    FunctionCallArgumentsDone,
    FunctionCallOutput,
    InputAudioBufferAppend,
    InputTranscriptionCompleted,
    OutputAudioDelta,
    OutputAudioDone,
    OutputTranscriptDelta,
    OutputTranscriptDone,
    RealtimeProtocolError,
    ResponseCancel,
    ResponseDone,
    ServerEvent,
    SessionCreated,
    SessionUpdate,
    SpeechStarted,
    SpeechStopped,
    parse_server_event,
)
from .transport import Transport, TransportClosed

#: Minimum audible chunk handed to the sink. Below ~200 ms the prosody analyzer
#: returns no accents at all, so a smaller coalesce would silently cost the
#: hosted voice its beat nods.
DEFAULT_COALESCE_MS = 240.0

#: Every function call in R1 gets exactly this.
TOOL_REFUSAL_OUTPUT = json.dumps({"error": "tools are not enabled in R1"})

#: Ear-oriented instructions layered under the personality. Not persona: these
#: are the rules that keep a hosted voice honest about a physical robot.
GUARDRAILS = (
    "You are speaking aloud through a robot dog's speaker. "
    "Use short spoken sentences. "
    "Never narrate your own mechanics or mention tools, sessions, or transcripts. "
    "Acknowledge a request before anything happens, and never claim to have "
    "arrived anywhere or completed a physical action — the robot reports that "
    "itself. "
    "Admit plainly what you cannot do. "
    "If the robot's own systems report an action, describe it; never decide it."
)

CODE_ARMED = "armed"
CODE_DISABLED = "realtime_disabled"
CODE_NO_HANDSHAKE = "no_handshake_token"
CODE_NO_MIC_GESTURE = "no_mic_gesture"
CODE_NO_TRANSPORT = "no_transport"
CODE_BUDGET_EXHAUSTED = "monthly_budget_exhausted"

SPEAKER_OWNER = "owner"
SPEAKER_ROBOT = "robot"
SPEAKER_SYSTEM = "system"


class RealtimeLaneError(RuntimeError):
    """The lane refused to do something. Never a silent no-op."""


class SinkOwnershipError(RealtimeLaneError):
    """Two speakers tried to own one mouth."""


@dataclass(frozen=True)
class RealtimeArmingDecision:
    """May the hosted lane open a session? Mirrors ``MicArmingDecision``.

    Deliberately NOT ``decide_microphone_arming``: that gate requires a local
    recognizer, and passing "the cloud is reachable" as recognizer availability
    is precisely the service-reachability arming FIX-A exists to ban.
    """

    armed: bool
    code: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {"armed": self.armed, "code": self.code, "reason": self.reason}


def decide_realtime_arming(
    *,
    config: RealtimeConfig,
    handshake_token: str | None,
    mic_gesture: bool,
    transport_available: bool = True,
    spend_usd: float = 0.0,
) -> RealtimeArmingDecision:
    """Fail closed. Three independent yeses are required, plus a budget.

    An enabled flag is consent to the FEATURE; an authenticated handshake is
    proof the caller is the local panel; the mic gesture is the owner's
    per-connection act. None of the three substitutes for another, and none of
    them is "the service answered".
    """

    if not config.enabled:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_DISABLED,
            reason=(
                "Realtime lane not armed: realtime.enabled is false "
                f"(config source: {config.source})."
            ),
        )
    if not handshake_token:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_NO_HANDSHAKE,
            reason=(
                "Realtime lane not armed: no authenticated handshake token. The audio "
                "listener requires the panel's per-process CSRF token, exactly as "
                "_authorize_post does."
            ),
        )
    if not mic_gesture:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_NO_MIC_GESTURE,
            reason=(
                "Realtime lane not armed: the owner has not pressed the microphone "
                "button for this connection. A reachable service is not consent."
            ),
        )
    if spend_usd >= config.monthly_budget_usd:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_BUDGET_EXHAUSTED,
            reason=(
                f"Realtime lane not armed: ${spend_usd:.2f} of this month's "
                f"${config.monthly_budget_usd:.2f} budget is already spent."
            ),
        )
    if not transport_available:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_NO_TRANSPORT,
            reason=(
                "Realtime lane not armed: no transport is configured. R1 ships the "
                "in-process fake transport only; the live WebSocket transport is R1.5 "
                "and needs `websockets` plus a key."
            ),
        )
    return RealtimeArmingDecision(
        armed=True,
        code=CODE_ARMED,
        reason=(
            f"Realtime lane armed on {config.model} (voice={config.voice}); "
            "handshake token supplied and microphone gesture given."
        ),
    )


def build_instructions(
    *,
    personality: str,
    reply_style: Sequence[str] = (),
    guardrails: str = GUARDRAILS,
) -> str:
    """Persona from the repo's own prompt library, plus ear-oriented rules."""

    parts = [personality.strip()]
    for line in reply_style:
        text = str(line).strip()
        if text:
            parts.append(f"- {text}")
    parts.append(guardrails)
    return "\n".join(part for part in parts if part)


class SinkLike(Protocol):
    """The part of ``SpeakerSink`` the playback bridge uses."""

    first_chunk_started_monotonic: float | None

    def begin_utterance(self) -> None: ...

    def enqueue(self, chunk: bytes, token: object = None) -> None: ...

    def interrupt(self) -> None: ...


class LedgerLike(Protocol):
    """The part of ``ConversationMemory`` the lane writes through."""

    def write_realtime_turn(
        self,
        *,
        session_id: str | None,
        speaker: str,
        text: str,
        origin: str,
        provider_item_id: str | None = None,
    ) -> int: ...


def _never() -> bool:
    return False


@dataclass
class _ResponseState:
    """Bookkeeping for the one hosted response currently in flight."""

    response_id: str = ""
    item_id: str = ""
    playing: bool = False
    enqueued_ms: float = 0.0
    transcript_parts: list[str] = field(default_factory=list)

    @property
    def transcript(self) -> str:
        return "".join(self.transcript_parts)


class RealtimeLane:
    """One hosted session, its mouth, its ledger, and its failure handling."""

    def __init__(
        self,
        *,
        config: RealtimeConfig,
        instructions: str,
        transport_factory: Callable[[], Transport] | None = None,
        sink: SinkLike | None = None,
        sink_factory: Callable[[], SinkLike] | None = None,
        ingress: Callable[..., RealtimeTranscriptOutcome] | None = None,
        ledger: LedgerLike | None = None,
        memory_tail: Callable[[], Sequence[Mapping[str, str]]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        cost_log_path: Path | None = None,
        duplex_output_active: Callable[[], bool] = _never,
        coalesce_ms: float = DEFAULT_COALESCE_MS,
        sample_rate_hz: int = PCM16_SAMPLE_RATE_HZ,
        session_id_factory: Callable[[], str] | None = None,
        summarize_hook: Callable[[str], str | None] | None = None,
        transcript_origin: str = "realtime",
    ) -> None:
        self.config = config
        self.instructions = instructions
        self._transport_factory = transport_factory
        self._sink = sink
        # The sink is constructed here when the local synthesizer never loaded:
        # runtime.py only builds one under `if speech_stack.synthesizer is not
        # None`, and hosted playback must work with zero local speech models.
        self._sink_factory = sink_factory
        self._ingress = ingress
        self._ledger = ledger
        self._memory_tail = memory_tail
        self._clock = clock
        self._cost_log_path = cost_log_path
        self._duplex_output_active = duplex_output_active
        self._sample_rate_hz = int(sample_rate_hz)
        self._bytes_per_ms = (self._sample_rate_hz * 2) / 1000.0
        self._coalesce_bytes = max(1, int(coalesce_ms * self._bytes_per_ms))
        self._session_id_factory = session_id_factory or (lambda: f"rt_{uuid.uuid4().hex[:12]}")
        self._summarize_hook = summarize_hook
        self._transcript_origin = transcript_origin

        self.transport: Transport | None = None
        self.session_id: str | None = None
        self.provider_session_id: str | None = None
        self.arming: RealtimeArmingDecision | None = None
        self.usage_rows: list[dict[str, object]] = []
        self.refused_tool_calls: list[str] = []
        self.truncations: list[dict[str, object]] = []
        self.protocol_errors: list[str] = []
        self.server_errors: list[ErrorEvent] = []
        self.events: list[str] = []
        self.reconnects = 0
        self.rollovers = 0
        self.stalls = 0
        self.disconnects = 0
        self.tail_items_injected = 0
        self.outcomes: list[RealtimeTranscriptOutcome] = []

        #: Items already ledgered by a barge-in truncation. A late
        #: ``transcript.done`` for one of these must not write a SECOND, longer
        #: robot row — the ledger records what was heard, not what was drafted.
        self._truncated_items: set[str] = set()
        self._response = _ResponseState()
        self._pcm = bytearray()
        self._expecting_server = False
        self._last_event_at = clock()
        self._session_started_at: float | None = None
        self._handshake_token: str | None = None
        self._mic_gesture = False
        self._audio_sent_this_session = 0

    # ------------------------------------------------------------ properties
    @property
    def active(self) -> bool:
        return self.transport is not None and not self.transport.closed

    @property
    def playback_owned(self) -> bool:
        """True while the lane is the exclusive owner of the speaker."""

        return self._response.playing

    @property
    def enqueued_ms(self) -> float:
        return self._response.enqueued_ms

    # ------------------------------------------------------------- lifecycle
    def arm(self, *, handshake_token: str | None, mic_gesture: bool) -> RealtimeArmingDecision:
        decision = decide_realtime_arming(
            config=self.config,
            handshake_token=handshake_token,
            mic_gesture=mic_gesture,
            transport_available=self._transport_factory is not None,
        )
        self.arming = decision
        return decision

    def open_session(
        self,
        *,
        handshake_token: str | None = None,
        mic_gesture: bool = False,
    ) -> str:
        """Arm, connect, send instructions, then inject the tail. In that order.

        The tail goes up BEFORE any audio append, and the ordering is asserted
        by test rather than assumed: mid-session history edits bust the prompt
        cache, and the cached-audio discount is the entire cost model.
        """

        decision = self.arm(handshake_token=handshake_token, mic_gesture=mic_gesture)
        if not decision.armed:
            raise RealtimeLaneError(decision.reason)
        self._handshake_token = handshake_token
        self._mic_gesture = mic_gesture
        self.session_id = self._session_id_factory()
        self._connect()
        return self.session_id

    def _connect(self) -> None:
        factory = self._transport_factory
        if factory is None:  # pragma: no cover - the arming gate refuses first
            raise RealtimeLaneError("realtime lane has no transport factory")
        self.transport = factory()
        self._response = _ResponseState()
        self._pcm.clear()
        self._expecting_server = False
        self._audio_sent_this_session = 0
        now = self._clock()
        self._last_event_at = now
        self._session_started_at = now
        self._send(
            SessionUpdate(
                instructions=self.instructions,
                model=self.config.model,
                voice=self.config.voice,
            )
        )
        self._inject_tail()

    def _inject_tail(self) -> None:
        self.tail_items_injected = 0
        if self._memory_tail is None:
            return
        for row in self._memory_tail():
            role = str(row.get("role", "")).strip()
            content = str(row.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            self._send(ConversationItemCreate(role=role, text=content))
            self.tail_items_injected += 1

    def close(self) -> None:
        if self.transport is not None:
            try:
                self.transport.close()
            except OSError:  # pragma: no cover - defensive
                pass
        self.transport = None
        self._response = _ResponseState()
        self._pcm.clear()
        self._expecting_server = False
        self._session_started_at = None

    # ------------------------------------------------------------------ relay
    def send_audio(self, pcm: bytes) -> None:
        """Owner microphone frames going up. Requires an open session."""

        if not self.active:
            raise RealtimeLaneError("realtime lane has no open session")
        if not pcm:
            return
        self._send(InputAudioBufferAppend(audio=bytes(pcm)))
        self._audio_sent_this_session += 1
        # From here the provider owes us something. Silence past
        # stall_timeout_s is the watchdog's trigger; without this flag a
        # dead session looks exactly like an idle one.
        self._expecting_server = True

    def pump(self) -> int:
        """Drain and dispatch every pending server frame. Returns the count."""

        if self.transport is None:
            return 0
        handled = 0
        while True:
            try:
                frame = self.transport.receive()
            except TransportClosed:
                self._on_disconnect()
                return handled
            if frame is None:
                return handled
            self._last_event_at = self._clock()
            handled += 1
            try:
                event = parse_server_event(frame)
            except RealtimeProtocolError as error:
                # Fail closed and LOUD-in-the-record: an unrecognized frame is
                # never treated as "nothing happened". The session survives —
                # dropping the conversation because the provider shipped a new
                # event type would be a worse failure than ignoring one frame.
                self.protocol_errors.append(str(error))
                self._note(f"protocol refusal: {error}")
                continue
            self._dispatch(event)

    def tick(self) -> str | None:
        """Watchdog + rollover. Returns the reason a reconnect was taken."""

        if not self.active:
            return None
        now = self._clock()
        started = self._session_started_at
        if started is not None and (now - started) >= self.config.session_max_s:
            return self._rollover(now)
        if self._expecting_server and (now - self._last_event_at) > self.config.stall_timeout_s:
            self.stalls += 1
            self._note(
                f"watchdog: no server event for {now - self._last_event_at:.1f}s "
                f"while a response was expected (limit {self.config.stall_timeout_s:.1f}s)"
            )
            self._reconnect("stall")
            return "stall"
        return None

    # -------------------------------------------------------------- dispatch
    def _dispatch(self, event: ServerEvent) -> None:
        if isinstance(event, SessionCreated):
            self.provider_session_id = event.session_id
            self._note(f"session created: {event.session_id}")
            return
        if isinstance(event, SpeechStarted):
            self._on_speech_started()
            return
        if isinstance(event, SpeechStopped):
            return
        if isinstance(event, InputTranscriptionCompleted):
            self._on_owner_transcript(event)
            return
        if isinstance(event, OutputTranscriptDelta):
            self._response.transcript_parts.append(event.delta)
            return
        if isinstance(event, OutputTranscriptDone):
            self._on_robot_transcript(event)
            return
        if isinstance(event, OutputAudioDelta):
            self._on_audio(event)
            return
        if isinstance(event, OutputAudioDone):
            self._flush_audio(final=True)
            return
        if isinstance(event, FunctionCallArgumentsDone):
            self._on_function_call(event)
            return
        if isinstance(event, ResponseDone):
            self._on_response_done(event)
            return
        if isinstance(event, ErrorEvent):
            self.server_errors.append(event)
            self._note(f"server error {event.code}: {event.message}")
            return

    # -------------------------------------------------------- playback bridge
    def assert_sink_free(self, claimant: str = "realtime lane") -> None:
        """Refuse to share the mouth. Called before every claim, both ways.

        ``SpeakerSink`` is an ordered queue with no notion of who filled it: two
        concurrent enqueuers interleave sentences. ``speak_system``'s busy check
        cannot see hosted playback, so the rule is stated here and asserted.
        """

        if self._duplex_output_active():
            raise SinkOwnershipError(
                f"{claimant} may not enqueue while a DuplexVoiceSession output is live; "
                "the sink is an ordered queue and the two would interleave"
            )

    def assert_lane_not_speaking(self, claimant: str = "duplex voice session") -> None:
        """The other direction of the same rule, for the local output lane."""

        if self._response.playing:
            raise SinkOwnershipError(
                f"{claimant} may not enqueue while the realtime lane owns the sink"
            )

    def _begin_response(self, response_id: str, item_id: str) -> None:
        self.assert_sink_free()
        sink = self._require_sink()
        # The sink NEVER re-arms on enqueue: after any interrupt() every later
        # chunk is dropped until begin_utterance() clears the latch. A hosted
        # reply that followed a barge-in would otherwise be silent.
        sink.begin_utterance()
        self._response = _ResponseState(response_id=response_id, item_id=item_id, playing=True)
        self._pcm.clear()

    def _on_audio(self, event: OutputAudioDelta) -> None:
        if not self._response.playing or self._response.response_id != event.response_id:
            self._begin_response(event.response_id, event.item_id)
        if not self._response.item_id:
            self._response.item_id = event.item_id
        self._pcm.extend(event.audio)
        while len(self._pcm) >= self._coalesce_bytes:
            self._emit_audio(self._coalesce_bytes)

    def _flush_audio(self, *, final: bool = False) -> None:
        if not self._pcm:
            return
        if final or len(self._pcm) >= self._coalesce_bytes:
            self._emit_audio(len(self._pcm))

    def _emit_audio(self, size: int) -> None:
        chunk = bytes(self._pcm[:size])
        del self._pcm[:size]
        if not chunk:
            return
        self.assert_sink_free()
        sink = self._require_sink()
        # WAV-wrapped, with the rate stated. SpeakerSink._decode reads the rate
        # from the first RIFF header and otherwise keeps the last one it saw
        # (default 16 kHz), so raw 24 kHz PCM would play ~50% slow.
        sink.enqueue(pcm16_wav(chunk, sample_rate_hz=self._sample_rate_hz))
        self._response.enqueued_ms += len(chunk) / self._bytes_per_ms

    def _require_sink(self) -> SinkLike:
        if self._sink is None:
            if self._sink_factory is None:
                raise RealtimeLaneError(
                    "realtime lane has no speaker sink and no factory to build one"
                )
            self._sink = self._sink_factory()
        return self._sink

    def played_ms(self) -> float:
        """Milliseconds the SINK actually started playing, not what we queued.

        Anchored to ``first_chunk_started_monotonic`` — the speaker worker's own
        clock — and clamped by what was enqueued, because a truncate that
        overstates what the owner heard makes the provider's transcript lie in
        the ledger's favour.
        """

        if self._sink is None:
            return 0.0
        started = getattr(self._sink, "first_chunk_started_monotonic", None)
        if started is None:
            return 0.0
        elapsed_ms = max(0.0, (self._clock() - float(started)) * 1000.0)
        return min(self._response.enqueued_ms, elapsed_ms)

    # -------------------------------------------------------------- barge-in
    def _on_speech_started(self) -> None:
        if not self._response.playing:
            return
        played = self.played_ms()
        sink = self._sink
        if sink is not None:
            sink.interrupt()
        self._send(ResponseCancel(response_id=self._response.response_id or None))
        if self._response.item_id:
            self._send(
                ConversationItemTruncate(
                    item_id=self._response.item_id,
                    audio_end_ms=int(played),
                )
            )
        self.truncations.append(
            {
                "item_id": self._response.item_id,
                "audio_end_ms": int(played),
                "enqueued_ms": round(self._response.enqueued_ms, 3),
            }
        )
        heard = self._response.transcript
        if self._response.item_id:
            self._truncated_items.add(self._response.item_id)
        if heard:
            self._write_ledger(
                SPEAKER_ROBOT,
                f"{heard} [interrupted after {int(played)} ms]",
                item_id=self._response.item_id,
            )
        self._response.playing = False
        self._pcm.clear()
        self._note(f"barge-in: cancelled {self._response.response_id!r} at {int(played)} ms")

    # --------------------------------------------------------------- content
    def _on_owner_transcript(self, event: InputTranscriptionCompleted) -> None:
        """The owner's words: approximate (a separate ASR pass), and restricted.

        This is the ONLY place a hosted transcript can reach the robot, and it
        reaches it through ``submit_realtime_transcript`` — never
        ``submit_voice_text``, which is the front door to the whole local agent.
        """

        if self._ingress is None:
            # Lane-only wiring (unit tests, or a runtime with no ingress): the
            # lane is then the ledger writer for both sides.
            self._write_ledger(SPEAKER_OWNER, event.transcript, item_id=event.item_id)
            return
        try:
            outcome = self._ingress(
                event.transcript,
                item_id=event.item_id,
                session_id=self.session_id,
            )
        except (RuntimeError, TypeError, ValueError) as error:
            self._note(f"ingress refused {event.transcript!r}: {error}")
            self._write_ledger(SPEAKER_OWNER, event.transcript, item_id=event.item_id)
            return
        self.outcomes.append(outcome)
        narration = outcome.narration()
        if narration:
            # The agent NARRATES what the robot did; it never decides it.
            self._send(ConversationItemCreate(role="system", text=narration))

    def _on_robot_transcript(self, event: OutputTranscriptDone) -> None:
        if event.item_id in self._truncated_items:
            self._note(f"suppressed post-truncation transcript for {event.item_id}")
            return
        self._write_ledger(SPEAKER_ROBOT, event.transcript, item_id=event.item_id)

    def _on_function_call(self, event: FunctionCallArgumentsDone) -> None:
        """R1 has no tool surface. Every call is refused, explicitly."""

        self.refused_tool_calls.append(event.name)
        self._send(FunctionCallOutput(call_id=event.call_id, output=TOOL_REFUSAL_OUTPUT))
        self._note(f"tool call refused: {event.name}")

    def _on_response_done(self, event: ResponseDone) -> None:
        self._flush_audio(final=True)
        self._response.playing = False
        self._expecting_server = False
        row = {
            "session_id": self.session_id,
            "response_id": event.response_id,
            "status": event.status,
            "monotonic_s": round(self._clock(), 6),
            **event.usage.as_dict(),
        }
        self.usage_rows.append(row)
        self._append_cost_row(row)

    def _append_cost_row(self, row: Mapping[str, object]) -> None:
        """Usage lands in a JSONL beside the ledger, not in the sqlite ledger.

        Chosen over a sqlite table so that "invoice / committed turns" stays a
        one-file query and a cost-log write can never take a lock the
        conversation ledger needs mid-turn.
        """

        if self._cost_log_path is None:
            return
        try:
            self._cost_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._cost_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(dict(row), sort_keys=True) + "\n")
        except OSError as error:  # pragma: no cover - disk boundary
            self._note(f"cost row not written: {error}")

    # ------------------------------------------------------- session recovery
    def _on_disconnect(self) -> None:
        self.disconnects += 1
        self._note("transport disconnected mid-session")
        self._reconnect("disconnect")

    def _rollover(self, now: float) -> str:
        """The 60-minute cap. Same reconnect path, plus a summarize marker.

        The summarizer itself is R2 (the Voice Spine's idle-time distiller on
        the local reasoner). R1 ledgers the marker so a rollover is visible in
        the record rather than inferred from a gap.
        """

        del now
        self.rollovers += 1
        summary = None
        if self._summarize_hook is not None:
            try:
                summary = self._summarize_hook(self.session_id or "")
            except (RuntimeError, TypeError, ValueError) as error:  # pragma: no cover
                self._note(f"summarize hook failed: {error}")
        marker = summary or "[session rollover] summarization is not implemented in R1"
        self._write_ledger(SPEAKER_SYSTEM, marker, item_id=None)
        self._reconnect("rollover")
        return "rollover"

    def _reconnect(self, reason: str) -> None:
        """New session, same memory. The provider was never holding anything."""

        if self._transport_factory is None:
            self._note(f"cannot reconnect after {reason}: no transport factory")
            return
        if self.transport is not None:
            try:
                self.transport.close()
            except OSError:  # pragma: no cover - defensive
                pass
        previous = self.session_id
        self.session_id = self._session_id_factory()
        self.reconnects += 1
        self._write_ledger(
            SPEAKER_SYSTEM,
            f"[session {reason}] reconnected {previous} -> {self.session_id}",
            item_id=None,
        )
        self._connect()
        self._note(
            f"reconnected after {reason}: re-sent instructions and "
            f"{self.tail_items_injected} tail item(s)"
        )

    # ----------------------------------------------------------------- plumbing
    def _send(self, event: Any) -> None:
        if self.transport is None:
            raise RealtimeLaneError("realtime lane has no transport")
        try:
            self.transport.send(event)
        except TransportClosed:
            self._note("send dropped: transport closed")

    def _write_ledger(self, speaker: str, text: str, *, item_id: str | None) -> None:
        if self._ledger is None or not text.strip():
            return
        try:
            self._ledger.write_realtime_turn(
                session_id=self.session_id,
                speaker=speaker,
                text=text,
                origin=self._transcript_origin,
                provider_item_id=item_id,
            )
        except (RuntimeError, TypeError, ValueError) as error:
            # A ledger write must never take down a turn (runtime.py:5996 keeps
            # the same rule for the tiered store).
            self._note(f"ledger write failed: {error}")

    def _note(self, message: str) -> None:
        self.events.append(message)

    def snapshot(self) -> dict[str, object]:
        """What ``/api/state`` would show about the lane."""

        return {
            "enabled": self.config.enabled,
            "active": self.active,
            "session_id": self.session_id,
            "provider_session_id": self.provider_session_id,
            "arming": None if self.arming is None else self.arming.as_dict(),
            "reconnects": self.reconnects,
            "stalls": self.stalls,
            "rollovers": self.rollovers,
            "disconnects": self.disconnects,
            "refused_tool_calls": list(self.refused_tool_calls),
            "protocol_errors": list(self.protocol_errors),
            "usage_rows": len(self.usage_rows),
            "audio_frames_sent": self._audio_sent_this_session,
            "tail_items_injected": self.tail_items_injected,
        }


__all__ = [
    "CODE_ARMED",
    "CODE_BUDGET_EXHAUSTED",
    "CODE_DISABLED",
    "CODE_NO_HANDSHAKE",
    "CODE_NO_MIC_GESTURE",
    "CODE_NO_TRANSPORT",
    "DEFAULT_COALESCE_MS",
    "GUARDRAILS",
    "SPEAKER_OWNER",
    "SPEAKER_ROBOT",
    "SPEAKER_SYSTEM",
    "TOOL_REFUSAL_OUTPUT",
    "LedgerLike",
    "RealtimeArmingDecision",
    "RealtimeLane",
    "RealtimeLaneError",
    "SinkLike",
    "SinkOwnershipError",
    "build_instructions",
    "decide_realtime_arming",
]
