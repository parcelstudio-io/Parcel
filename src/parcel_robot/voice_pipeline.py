from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing_extensions import Self

from .agent import VoiceAgent
from .providers import SpeechRecognizer, SpeechSynthesizer


class VoicePipeline:
    """One utterance through STT, guarded intelligence, and TTS.

    Audio capture/playback remain callbacks so ROS or the target sound hardware
    can own device selection, echo cancellation, and interruption. Text has its
    own entry point so the same safe action path works on a machine without a
    connected microphone.
    """

    def __init__(
        self,
        recognizer: SpeechRecognizer,
        agent: VoiceAgent,
        synthesizer: SpeechSynthesizer,
        audio_player: Callable[[bytes], None],
    ):
        self.recognizer = recognizer
        self.agent = agent
        self.synthesizer = synthesizer
        self.audio_player = audio_player

    def process(self, wav_audio: bytes) -> tuple[str, str]:
        transcript = self.recognizer.transcribe(wav_audio).strip()
        if not transcript:
            return "", ""
        return transcript, self.process_text(transcript)

    def process_text(self, transcript: str) -> str:
        """Process final text without requiring an audio capture device."""

        clean_text = transcript.strip()
        if not clean_text:
            return ""
        reply = self.agent.handle_text(clean_text)
        if reply:
            self.audio_player(self.synthesizer.synthesize(reply))
        return reply


@dataclass(frozen=True)
class VoiceTurn:
    turn_id: int
    transcript: str
    reply: str
    superseded: bool = False


@dataclass(frozen=True)
class VoiceStage:
    turn_id: int
    name: str
    timestamp: float
    transcript: str = ""
    reply: str = ""


@dataclass(frozen=True)
class _QueuedTurn:
    turn_id: int
    transcript: str
    speech_epoch: int


@dataclass
class _OutputState:
    turn_id: int
    speech_epoch: int
    cancel_event: threading.Event
    stream: Iterator[bytes] | None = None
    thread: threading.Thread | None = None


class DuplexVoiceSession:
    """Text-first coordinator for concurrent input and cancellable speech output.

    Capture/VAD/streaming-ASR code can call :meth:`submit_text` repeatedly with
    partial hypotheses and then one final transcript. Any new partial or final
    input immediately interrupts active speech (barge-in); only final text is
    sent to ``VoiceAgent.handle_text``. Consequently raw audio, codec tokens, and
    Fish Speech VQ tokens never enter the action-reasoning boundary.

    ``audio_chunk_player`` receives ordered chunks from a streaming synthesizer.
    For Fish S2 the first chunk is a WAV header followed by PCM16 data. Pass no
    synthesizer/player to run in text-only mode on hosts without audio hardware.
    """

    def __init__(
        self,
        agent: VoiceAgent,
        *,
        synthesizer: SpeechSynthesizer | None = None,
        audio_chunk_player: Callable[[bytes], None] | None = None,
        audio_interrupt: Callable[[], None] | None = None,
        audio_turn_start: Callable[[], None] | None = None,
        on_turn: Callable[[VoiceTurn], None] | None = None,
        on_partial: Callable[[str], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_stage: Callable[[VoiceStage], None] | None = None,
    ):
        if (synthesizer is None) != (audio_chunk_player is None):
            raise ValueError("synthesizer and audio_chunk_player must be configured together")
        self.agent = agent
        self.synthesizer = synthesizer
        self.audio_chunk_player = audio_chunk_player
        self.audio_interrupt = audio_interrupt
        self.audio_turn_start = audio_turn_start
        self.on_turn = on_turn
        self.on_partial = on_partial
        self.on_error = on_error
        self.on_stage = on_stage

        self._turn_queue: queue.Queue[_QueuedTurn | None] = queue.Queue()
        self._lock = threading.RLock()
        self._idle = threading.Condition(self._lock)
        self._latest_turn_id = 0
        self._speech_epoch = 0
        self._partial_transcript = ""
        self._input_jobs = 0
        self._output_jobs = 0
        self._active_output: _OutputState | None = None
        self._output_threads: set[threading.Thread] = set()
        self._last_error: Exception | None = None
        self._closed = False
        self._worker = threading.Thread(
            target=self._run_input,
            name="parcel-voice-input",
            daemon=True,
        )
        self._worker.start()

    @property
    def partial_transcript(self) -> str:
        with self._lock:
            return self._partial_transcript

    @property
    def last_error(self) -> Exception | None:
        with self._lock:
            return self._last_error

    def submit_text(self, text: str, *, is_final: bool = True) -> int | None:
        """Submit an ASR hypothesis or a final typed/recognized command.

        Partial text is observable through ``on_partial`` but is never executed.
        Final submissions return a monotonically increasing turn id.
        """

        if not isinstance(text, str):
            raise TypeError("voice input must be text")
        clean_text = " ".join(text.split())
        if not clean_text:
            return None

        with self._lock:
            if self._closed:
                raise RuntimeError("voice session is closed")
            self._speech_epoch += 1
            speech_epoch = self._speech_epoch
            output = self._active_output
            if output is not None:
                output.cancel_event.set()

            if not is_final:
                self._partial_transcript = clean_text
                turn_id = None
            else:
                self._partial_transcript = ""
                self._latest_turn_id += 1
                turn_id = self._latest_turn_id
                self._input_jobs += 1
                query_end = time.monotonic()

        self._interrupt_output(output)
        self._cancel_reasoning()
        if not is_final:
            self._call_partial(clean_text)
            return None

        self._call_stage(VoiceStage(turn_id, "query_end", query_end, transcript=clean_text))
        self._supersede_pending_turns()
        self._turn_queue.put(_QueuedTurn(turn_id, clean_text, speech_epoch))
        return turn_id

    def barge_in(self) -> None:
        """Interrupt current synthesis/playback without executing a command."""

        with self._lock:
            self._speech_epoch += 1
            output = self._active_output
            if output is not None:
                output.cancel_event.set()
        self._interrupt_output(output)
        self._cancel_reasoning()

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Wait for queued reasoning and all output workers to finish."""

        deadline = None if timeout is None else time.monotonic() + max(timeout, 0.0)
        with self._idle:
            while self._input_jobs or self._output_jobs:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._idle.wait(remaining)
            return True

    def close(self, *, wait: bool = True, timeout: float = 5.0) -> bool:
        """Stop accepting turns and cancel speech; return whether workers exited."""

        with self._lock:
            if not self._closed:
                self._closed = True
                self._speech_epoch += 1
                output = self._active_output
                if output is not None:
                    output.cancel_event.set()
                self._turn_queue.put(None)
            else:
                output = self._active_output
        self._interrupt_output(output)
        self._cancel_reasoning()
        if not wait:
            return True

        deadline = time.monotonic() + max(timeout, 0.0)
        current = threading.current_thread()
        if current is not self._worker:
            self._worker.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            output_threads = tuple(self._output_threads)
        for thread in output_threads:
            if thread is not current:
                thread.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            return not self._worker.is_alive() and not self._output_threads

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _run_input(self) -> None:
        while True:
            turn = self._turn_queue.get()
            if turn is None:
                return
            try:
                with self._lock:
                    should_process = not self._closed and turn.turn_id == self._latest_turn_id
                if not should_process:
                    self._call_stage(VoiceStage(turn.turn_id, "superseded", time.monotonic()))
                    self._call_stage(VoiceStage(turn.turn_id, "turn_complete", time.monotonic()))
                    continue

                self._call_stage(VoiceStage(turn.turn_id, "reasoning_start", time.monotonic()))
                guarded = getattr(self.agent, "handle_text_guarded", None)
                if callable(guarded):
                    reply = guarded(
                        turn.transcript,
                        lambda action, current_turn=turn: self._commit_current_turn(
                            current_turn, action
                        ),
                    )
                else:
                    reply = self.agent.handle_text(turn.transcript)
                self._call_stage(
                    VoiceStage(
                        turn.turn_id,
                        "reasoning_response",
                        time.monotonic(),
                        reply=reply,
                    )
                )
                with self._lock:
                    superseded = (
                        self._closed
                        or turn.turn_id != self._latest_turn_id
                        or turn.speech_epoch != self._speech_epoch
                    )
                self._call_turn(VoiceTurn(turn.turn_id, turn.transcript, reply, superseded))
                self._call_stage(
                    VoiceStage(
                        turn.turn_id,
                        "response_logged",
                        time.monotonic(),
                        reply=reply,
                    )
                )
                if reply and not superseded:
                    output_started = self._start_output(turn, reply)
                    if not output_started:
                        self._call_stage(
                            VoiceStage(turn.turn_id, "turn_complete", time.monotonic())
                        )
                else:
                    if superseded:
                        self._call_stage(VoiceStage(turn.turn_id, "superseded", time.monotonic()))
                    self._call_stage(VoiceStage(turn.turn_id, "turn_complete", time.monotonic()))
            # This is a long-lived thread boundary: one faulty adapter must not
            # permanently disable subsequent emergency voice commands.
            except Exception as error:  # noqa: BLE001
                self._call_stage(VoiceStage(turn.turn_id, "error", time.monotonic()))
                self._call_stage(VoiceStage(turn.turn_id, "turn_complete", time.monotonic()))
                self._report_error(error)
            finally:
                with self._idle:
                    self._input_jobs -= 1
                    self._idle.notify_all()

    def _commit_current_turn(
        self,
        turn: _QueuedTurn,
        action: Callable[[], str],
    ) -> str:
        """Linearize a robot action against new partial/final input."""

        with self._lock:
            if (
                self._closed
                or turn.turn_id != self._latest_turn_id
                or turn.speech_epoch != self._speech_epoch
            ):
                return "Command superseded by newer input."
        # The current-turn check is the linearization point. Do not retain the
        # voice-state lock across simulator/device I/O; barge-in and emergency
        # requests must remain responsive after an action has committed.
        ready = time.monotonic()
        self._call_stage(VoiceStage(turn.turn_id, "reasoning_first_output", ready))
        self._call_stage(VoiceStage(turn.turn_id, "action_commit_start", ready))
        try:
            return action()
        finally:
            self._call_stage(VoiceStage(turn.turn_id, "action_commit_end", time.monotonic()))

    def _start_output(self, turn: _QueuedTurn, reply: str) -> bool:
        if self.synthesizer is None or self.audio_chunk_player is None:
            return False
        state = _OutputState(turn.turn_id, turn.speech_epoch, threading.Event())
        thread = threading.Thread(
            target=self._run_output,
            args=(state, reply),
            name=f"parcel-voice-output-{turn.turn_id}",
            daemon=True,
        )
        state.thread = thread
        with self._idle:
            if (
                self._closed
                or turn.turn_id != self._latest_turn_id
                or turn.speech_epoch != self._speech_epoch
            ):
                return False
            self._active_output = state
            self._output_jobs += 1
            self._output_threads.add(thread)
        thread.start()
        return True

    def _run_output(self, state: _OutputState, reply: str) -> None:
        stream: Iterator[bytes] | None = None
        first_chunk = True
        failed = False
        try:
            self._call_stage(VoiceStage(state.turn_id, "tts_start", time.monotonic()))
            if self.audio_turn_start is not None and not state.cancel_event.is_set():
                # Re-arm the audio sink for this turn. The sink deliberately
                # never re-arms on enqueue, so a stale chunk racing a barge-in
                # flush stays suppressed.
                try:
                    self.audio_turn_start()
                except Exception as error:  # noqa: BLE001 - external audio callback
                    self._report_error(error)
            stream_method = getattr(self.synthesizer, "synthesize_stream", None)
            if callable(stream_method):
                stream = stream_method(reply, cancel_event=state.cancel_event)
                state.stream = stream
                if state.cancel_event.is_set():
                    self._cancel_stream(stream)
                    return
                for chunk in stream:
                    if state.cancel_event.is_set():
                        break
                    if chunk:
                        if first_chunk:
                            self._call_stage(
                                VoiceStage(
                                    state.turn_id,
                                    "tts_first_chunk",
                                    time.monotonic(),
                                )
                            )
                        self.audio_chunk_player(chunk)  # type: ignore[misc]
                        if first_chunk:
                            # A successful callback return is the earliest
                            # confirmed sink handoff exposed by this interface.
                            # The callback should enqueue without waiting for the
                            # entire clip. Acoustic presentation still requires a
                            # downstream PipeWire timestamp.
                            self._call_stage(
                                VoiceStage(
                                    state.turn_id,
                                    "audio_first_playback",
                                    time.monotonic(),
                                )
                            )
                            first_chunk = False
            else:
                audio = self.synthesizer.synthesize(reply)  # type: ignore[union-attr]
                if audio and not state.cancel_event.is_set():
                    self._call_stage(VoiceStage(state.turn_id, "tts_first_chunk", time.monotonic()))
                    self.audio_chunk_player(audio)  # type: ignore[misc]
                    self._call_stage(
                        VoiceStage(state.turn_id, "audio_first_playback", time.monotonic())
                    )
        # Provider and user-supplied sink implementations can raise arbitrary
        # exceptions; convert them to observable session errors at this boundary.
        except Exception as error:  # noqa: BLE001
            failed = True
            if not state.cancel_event.is_set():
                self._call_stage(VoiceStage(state.turn_id, "error", time.monotonic()))
                self._report_error(error)
        finally:
            if stream is not None:
                self._close_stream(stream)
            if state.cancel_event.is_set() and not failed:
                self._call_stage(VoiceStage(state.turn_id, "superseded", time.monotonic()))
            self._call_stage(VoiceStage(state.turn_id, "tts_complete", time.monotonic()))
            self._call_stage(VoiceStage(state.turn_id, "turn_complete", time.monotonic()))
            with self._idle:
                if self._active_output is state:
                    self._active_output = None
                self._output_jobs -= 1
                if state.thread is not None:
                    self._output_threads.discard(state.thread)
                self._idle.notify_all()

    def _interrupt_output(self, output: _OutputState | None) -> None:
        # The audio interrupt must fire even with no live output state: the
        # output worker exits as soon as it finishes ENQUEUEING, while the
        # speaker sink can still hold seconds of queued audio (the drain
        # window). Skipping the callback there let a barge-in — including a
        # spoken emergency stop — leave the robot talking to the end of its
        # queue, with stale beat nods still arming (2026-08-04 sprint review).
        # An interrupt with nothing queued is a no-op: the sink only re-arms
        # via begin_utterance at the start of the next non-cancelled reply.
        if output is not None:
            output.cancel_event.set()
            if output.stream is not None:
                self._cancel_stream(output.stream)
        if self.audio_interrupt is not None:
            try:
                self.audio_interrupt()
            except Exception as error:  # noqa: BLE001 - external audio callback
                self._report_error(error)

    def _cancel_reasoning(self) -> None:
        cancel = getattr(self.agent, "cancel_reasoning", None)
        if callable(cancel):
            try:
                cancel()
            except Exception as error:  # noqa: BLE001 - optional provider boundary
                self._report_error(error)

    def _supersede_pending_turns(self) -> None:
        """Keep at most the active generation and the newest queued final."""

        while True:
            try:
                stale = self._turn_queue.get_nowait()
            except queue.Empty:
                return
            if stale is None:
                self._turn_queue.put(None)
                return
            now = time.monotonic()
            self._call_stage(VoiceStage(stale.turn_id, "superseded", now))
            self._call_stage(VoiceStage(stale.turn_id, "turn_complete", now))
            with self._idle:
                self._input_jobs -= 1
                self._idle.notify_all()

    def _call_turn(self, turn: VoiceTurn) -> None:
        if self.on_turn is None:
            return
        try:
            self.on_turn(turn)
        except Exception as error:  # noqa: BLE001 - external event callback
            self._report_error(error)

    def _call_partial(self, transcript: str) -> None:
        if self.on_partial is None:
            return
        try:
            self.on_partial(transcript)
        except Exception as error:  # noqa: BLE001 - external event callback
            self._report_error(error)

    def _call_stage(self, stage: VoiceStage) -> None:
        if self.on_stage is None:
            return
        try:
            self.on_stage(stage)
        except Exception as error:  # noqa: BLE001 - observability callback
            self._report_error(error)

    def _report_error(self, error: Exception) -> None:
        with self._lock:
            self._last_error = error
        if self.on_error is not None:
            try:
                self.on_error(error)
            except Exception as callback_error:  # noqa: BLE001 - last-resort callback
                with self._lock:
                    self._last_error = callback_error

    @staticmethod
    def _cancel_stream(stream: Any) -> None:
        cancel = getattr(stream, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except (OSError, RuntimeError, ValueError):
                pass
            return
        DuplexVoiceSession._close_stream(stream)

    @staticmethod
    def _close_stream(stream: Any) -> None:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except (OSError, RuntimeError, ValueError):
                pass
