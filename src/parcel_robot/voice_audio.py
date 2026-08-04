"""Real-time microphone/speaker transport for the duplex voice session.

This module gives ``DuplexVoiceSession`` actual ears and a mouth:

- ``EnergyVad``: a dependency-free frame-energy voice activity detector with
  hangover smoothing and an adaptive noise floor. It is deliberately simple
  and fully unit-testable; a Silero-class model can replace it behind the same
  interface once onnxruntime ships on the target computer.
- ``MicrophoneVoiceLoop``: streams mono 16 kHz frames from a capture source,
  segments utterances with the VAD, transcribes finished utterances, and
  submits the text to the session. Speech onset during robot playback triggers
  acoustic barge-in, gated by an echo-guard multiplier because no acoustic
  echo cancellation exists yet (documented limitation: the guard suppresses
  self-triggering at the cost of requiring the owner to speak up while the
  robot is talking; hardware AEC is the planned fix).
- ``SpeakerSink``: an ordered-chunk audio player for the session's streaming
  synthesizer output with immediate interruption.

The loop takes any ``frames`` iterable so tests inject synthetic audio; the
default source opens a ``sounddevice`` input stream.
"""

from __future__ import annotations

import io
import logging
import math
import queue
import threading
import wave
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE_HZ = 16_000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE_HZ * FRAME_MS // 1000


@dataclass(frozen=True)
class VadEvent:
    kind: str  # "speech_start" | "speech_end"
    utterance: bytes = b""


class EnergyVad:
    """Frame-energy VAD with adaptive noise floor and hangover smoothing."""

    def __init__(
        self,
        *,
        threshold_scale: float = 4.0,
        min_speech_frames: int = 4,
        hangover_frames: int = 12,
        max_utterance_frames: int = 1000,
        noise_adapt_rate: float = 0.05,
        initial_noise_rms: float = 120.0,
    ):
        if threshold_scale <= 1.0 or not math.isfinite(threshold_scale):
            raise ValueError("VAD threshold scale must exceed 1.0")
        if min_speech_frames < 1 or hangover_frames < 1:
            raise ValueError("VAD frame counts must be positive")
        if max_utterance_frames < min_speech_frames:
            raise ValueError("max utterance must exceed the minimum speech length")
        if not 0.0 < noise_adapt_rate <= 1.0:
            raise ValueError("noise adaptation rate must be in (0, 1]")
        self.threshold_scale = threshold_scale
        self.min_speech_frames = min_speech_frames
        self.hangover_frames = hangover_frames
        self.max_utterance_frames = max_utterance_frames
        self.noise_adapt_rate = noise_adapt_rate
        self._noise_rms = float(initial_noise_rms)
        self._speech_frames: list[bytes] = []
        self._active = False
        self._silence_run = 0
        self._voiced_run = 0

    @property
    def noise_rms(self) -> float:
        return self._noise_rms

    @property
    def active(self) -> bool:
        return self._active

    @staticmethod
    def frame_rms(frame: np.ndarray) -> float:
        if frame.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(frame.astype(np.float64)))))

    def process(self, frame: np.ndarray) -> list[VadEvent]:
        """Feed one int16 mono frame; return zero or more segmentation events."""

        if frame.dtype != np.int16:
            raise TypeError("VAD frames must be int16 PCM")
        rms = self.frame_rms(frame)
        threshold = self._noise_rms * self.threshold_scale
        voiced = rms > threshold
        events: list[VadEvent] = []

        if voiced and rms > self._noise_rms:
            # Upward-only slow leak: a genuinely shifted ambient level (fan,
            # traffic) eventually re-baselines the floor even though every
            # frame reads as voiced, while a short real utterance barely
            # moves it. Without this, sustained noise above threshold locks
            # the VAD into back-to-back max-length flushes forever.
            self._noise_rms += (rms - self._noise_rms) * (self.noise_adapt_rate / 50.0)

        if not self._active:
            if voiced:
                self._voiced_run += 1
                self._speech_frames.append(frame.tobytes())
                if self._voiced_run >= self.min_speech_frames:
                    self._active = True
                    self._silence_run = 0
                    events.append(VadEvent("speech_start"))
            else:
                self._voiced_run = 0
                self._speech_frames.clear()
                # Only quiet frames adapt the floor; otherwise speech would
                # raise its own detection threshold.
                self._noise_rms += (rms - self._noise_rms) * self.noise_adapt_rate
                self._noise_rms = max(20.0, self._noise_rms)
        else:
            self._speech_frames.append(frame.tobytes())
            if voiced:
                self._silence_run = 0
            else:
                self._silence_run += 1
            too_long = len(self._speech_frames) >= self.max_utterance_frames
            if self._silence_run >= self.hangover_frames or too_long:
                utterance = b"".join(self._speech_frames)
                if too_long:
                    # A segment that never went quiet for a full hangover is
                    # almost certainly ambient noise, not speech. Re-seed the
                    # floor toward it so the next segment cannot start
                    # immediately (stuck-floor escape found in review).
                    segment = np.frombuffer(utterance, dtype=np.int16)
                    self._noise_rms = max(
                        self._noise_rms, self.frame_rms(segment) * 0.8
                    )
                self._reset_segment()
                events.append(VadEvent("speech_end", utterance))
        return events

    def _reset_segment(self) -> None:
        self._active = False
        self._silence_run = 0
        self._voiced_run = 0
        self._speech_frames = []


def pcm16_wav(pcm: bytes, sample_rate_hz: int = SAMPLE_RATE_HZ) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate_hz)
        writer.writeframes(pcm)
    return buffer.getvalue()


class MicrophoneVoiceLoop:
    """VAD-segmented microphone capture feeding a duplex voice session."""

    def __init__(
        self,
        *,
        recognizer,
        submit_text: Callable[..., object],
        barge_in: Callable[[], None],
        playback_active: Callable[[], bool],
        vad: EnergyVad | None = None,
        frames: Iterable[np.ndarray] | None = None,
        echo_guard_scale: float = 2.5,
        min_utterance_s: float = 0.25,
        on_failure: Callable[[Exception], None] | None = None,
    ):
        if echo_guard_scale < 1.0 or not math.isfinite(echo_guard_scale):
            raise ValueError("echo guard scale must be at least 1.0")
        if not 0.05 <= min_utterance_s <= 10.0:
            raise ValueError("minimum utterance must be between 0.05 and 10 seconds")
        self.recognizer = recognizer
        self.submit_text = submit_text
        self.barge_in = barge_in
        self.playback_active = playback_active
        self.vad = vad or EnergyVad()
        self.echo_guard_scale = echo_guard_scale
        self.min_utterance_samples = int(min_utterance_s * SAMPLE_RATE_HZ)
        self._frames = frames
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failure: Exception | None = None
        self.on_failure = on_failure
        self.utterances_submitted = 0
        self.barge_ins_triggered = 0
        self.echo_guard_suppressions = 0

    @property
    def running(self) -> bool:
        """True only while the capture thread is alive and has not failed."""

        thread = self._thread
        return thread is not None and thread.is_alive() and self._failure is None

    @property
    def failure(self) -> Exception | None:
        return self._failure

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("microphone loop is already running")
        if self._frames is None:
            # Preflight on the caller's thread so a missing PortAudio or
            # capture device raises into the runtime's degrade-to-text branch
            # instead of silently killing the worker thread after start()
            # already reported success.
            try:
                import sounddevice

                sounddevice.check_input_settings(
                    samplerate=SAMPLE_RATE_HZ, channels=1, dtype="int16"
                )
            except Exception as error:
                raise OSError(f"audio capture unavailable: {error}") from error
        self._thread = threading.Thread(
            target=self._run,
            name="parcel-voice-microphone",
            daemon=True,
        )
        self._thread.start()

    def close(self, timeout: float = 3.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self._thread = None

    def run_once(self, frame: np.ndarray) -> None:
        """Process one frame synchronously (test and embedding entry point)."""

        self._handle_frame(frame)

    def _run(self) -> None:
        try:
            source = self._frames if self._frames is not None else self._sounddevice_frames()
            for frame in source:
                if self._stop.is_set():
                    return
                self._handle_frame(frame)
        except Exception as error:  # noqa: BLE001 - device thread boundary
            logger.warning("microphone loop stopped: %s", error)
            self._failure = error
            if self.on_failure is not None:
                try:
                    self.on_failure(error)
                except Exception:  # noqa: BLE001, S110 - observer must not mask the fault
                    pass

    def _sounddevice_frames(self) -> Iterator[np.ndarray]:
        import sounddevice

        frame_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)

        def callback(indata, _frames, _time, status) -> None:
            if status:
                logger.debug("audio capture status: %s", status)
            try:
                frame_queue.put_nowait(np.array(indata[:, 0], dtype=np.int16))
            except queue.Full:
                pass  # drop rather than stall the audio driver thread

        with sounddevice.InputStream(
            samplerate=SAMPLE_RATE_HZ,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            callback=callback,
        ):
            while not self._stop.is_set():
                try:
                    yield frame_queue.get(timeout=0.25)
                except queue.Empty:
                    continue

    def _handle_frame(self, frame: np.ndarray) -> None:
        playback = False
        try:
            playback = bool(self.playback_active())
        except Exception:  # noqa: BLE001 - observability callback
            playback = False
        if playback:
            # No AEC yet: require the speaker-adjacent microphone to hear the
            # owner clearly ABOVE the robot's own speech before treating sound
            # as barge-in. Crude but honest; hardware AEC replaces this.
            rms = EnergyVad.frame_rms(frame)
            guard = self.vad.noise_rms * self.vad.threshold_scale * self.echo_guard_scale
            if rms <= guard:
                self.echo_guard_suppressions += 1
                return
        for event in self.vad.process(frame):
            if event.kind == "speech_start":
                if playback:
                    self.barge_ins_triggered += 1
                    try:
                        self.barge_in()
                    except Exception as error:  # noqa: BLE001
                        logger.warning("barge-in failed: %s", error)
            elif event.kind == "speech_end":
                self._finish_utterance(event.utterance)

    def _finish_utterance(self, utterance_pcm: bytes) -> None:
        if len(utterance_pcm) // 2 < self.min_utterance_samples:
            return
        wav_audio = pcm16_wav(utterance_pcm)
        try:
            transcript = self.recognizer.transcribe(wav_audio).strip()
        except Exception as error:  # noqa: BLE001 - STT service boundary
            logger.warning("speech recognition failed: %s", error)
            return
        if not transcript:
            return
        self.utterances_submitted += 1
        try:
            self.submit_text(transcript, is_final=True)
        except Exception as error:  # noqa: BLE001 - session boundary
            logger.warning("voice submission failed: %s", error)


class SpeakerSink:
    """Ordered audio-chunk player with immediate interruption.

    Receives WAV (first chunk carries the header) or raw PCM16 chunks from the
    session's synthesizer stream and plays them through ``sounddevice``. A
    dedicated worker owns the output stream; ``interrupt()`` flushes queued
    chunks and aborts the default player's in-flight chunk at the next ~50 ms
    block boundary without blocking the caller. Injected test players are
    only abortable between chunks. ``playback_active`` stays true until the
    in-flight player call actually returns.
    """

    def __init__(self, *, player: Callable[[bytes, int], None] | None = None):
        self._player = player
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=256)
        self._interrupted = threading.Event()
        self._playing = threading.Event()
        self._sample_rate = SAMPLE_RATE_HZ
        self._header_parsed = False
        self._worker = threading.Thread(
            target=self._run,
            name="parcel-voice-speaker",
            daemon=True,
        )
        self._worker.start()

    @property
    def playback_active(self) -> bool:
        return self._playing.is_set()

    def begin_utterance(self) -> None:
        """Re-arm playback at the start of a NEW (non-cancelled) reply.

        Clearing the interrupt latch here instead of on every ``enqueue``
        closes the barge-in race found in review: a stale chunk enqueued by
        an output thread that lost the race against ``interrupt()`` stays
        suppressed instead of un-interrupting the flush.
        """

        self._interrupted.clear()

    def enqueue(self, chunk: bytes) -> None:
        """Session-facing ``audio_chunk_player`` callback."""

        if not chunk:
            return
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            logger.warning("speaker queue overflow; dropping audio chunk")

    def interrupt(self) -> None:
        """Session-facing ``audio_interrupt`` callback: flush and stop now.

        ``_playing`` is deliberately NOT cleared here — the in-flight chunk
        keeps the flag (and therefore the microphone echo guard) up until the
        player actually returns, so the robot's own audible tail can never be
        transcribed as an owner command.
        """

        self._interrupted.set()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def close(self, timeout: float = 3.0) -> None:
        self.interrupt()
        self._queue.put(None)
        self._worker.join(timeout)

    def _run(self) -> None:
        while True:
            chunk = self._queue.get()
            if chunk is None:
                return
            if self._interrupted.is_set():
                continue
            try:
                pcm, sample_rate = self._decode(chunk)
                if not pcm:
                    continue
                self._playing.set()
                self._play(pcm, sample_rate)
            except Exception as error:  # noqa: BLE001 - device boundary
                logger.warning("audio playback failed: %s", error)
            finally:
                if self._queue.empty():
                    self._playing.clear()

    def _decode(self, chunk: bytes) -> tuple[bytes, int]:
        if chunk[:4] == b"RIFF":
            with wave.open(io.BytesIO(chunk), "rb") as reader:
                self._sample_rate = reader.getframerate()
                self._header_parsed = True
                return reader.readframes(reader.getnframes()), self._sample_rate
        return chunk, self._sample_rate

    def _play(self, pcm: bytes, sample_rate: int) -> None:
        if self._player is not None:
            self._player(pcm, sample_rate)
            return
        import sounddevice

        data = np.frombuffer(pcm, dtype=np.int16)
        # Stream in ~50 ms blocks and poll the interrupt latch between them:
        # a mid-sentence barge-in aborts the in-flight chunk within one block
        # instead of letting a whole sentence play to completion.
        block = max(1, sample_rate // 20)
        with sounddevice.OutputStream(
            samplerate=sample_rate, channels=1, dtype="int16"
        ) as stream:
            for start in range(0, len(data), block):
                if self._interrupted.is_set():
                    return
                stream.write(data[start : start + block])
