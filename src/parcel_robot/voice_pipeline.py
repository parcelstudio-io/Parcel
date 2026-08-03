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
        on_turn: Callable[[VoiceTurn], None] | None = None,
        on_partial: Callable[[str], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ):
        if (synthesizer is None) != (audio_chunk_player is None):
            raise ValueError("synthesizer and audio_chunk_player must be configured together")
        self.agent = agent
        self.synthesizer = synthesizer
        self.audio_chunk_player = audio_chunk_player
        self.audio_interrupt = audio_interrupt
        self.on_turn = on_turn
        self.on_partial = on_partial
        self.on_error = on_error

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

        self._interrupt_output(output)
        if not is_final:
            self._call_partial(clean_text)
            return None

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
                    continue

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
                with self._lock:
                    superseded = (
                        self._closed
                        or turn.turn_id != self._latest_turn_id
                        or turn.speech_epoch != self._speech_epoch
                    )
                self._call_turn(VoiceTurn(turn.turn_id, turn.transcript, reply, superseded))
                if reply and not superseded:
                    self._start_output(turn, reply)
            # This is a long-lived thread boundary: one faulty adapter must not
            # permanently disable subsequent emergency voice commands.
            except Exception as error:  # noqa: BLE001
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
            return action()

    def _start_output(self, turn: _QueuedTurn, reply: str) -> None:
        if self.synthesizer is None or self.audio_chunk_player is None:
            return
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
                return
            self._active_output = state
            self._output_jobs += 1
            self._output_threads.add(thread)
        thread.start()

    def _run_output(self, state: _OutputState, reply: str) -> None:
        stream: Iterator[bytes] | None = None
        try:
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
                        self.audio_chunk_player(chunk)  # type: ignore[misc]
            else:
                audio = self.synthesizer.synthesize(reply)  # type: ignore[union-attr]
                if audio and not state.cancel_event.is_set():
                    self.audio_chunk_player(audio)  # type: ignore[misc]
        # Provider and user-supplied sink implementations can raise arbitrary
        # exceptions; convert them to observable session errors at this boundary.
        except Exception as error:  # noqa: BLE001
            if not state.cancel_event.is_set():
                self._report_error(error)
        finally:
            if stream is not None:
                self._close_stream(stream)
            with self._idle:
                if self._active_output is state:
                    self._active_output = None
                self._output_jobs -= 1
                if state.thread is not None:
                    self._output_threads.discard(state.thread)
                self._idle.notify_all()

    def _interrupt_output(self, output: _OutputState | None) -> None:
        if output is None:
            return
        output.cancel_event.set()
        if output.stream is not None:
            self._cancel_stream(output.stream)
        if self.audio_interrupt is not None:
            try:
                self.audio_interrupt()
            except Exception as error:  # noqa: BLE001 - external audio callback
                self._report_error(error)

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
