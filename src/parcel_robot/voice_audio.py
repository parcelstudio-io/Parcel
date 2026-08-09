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
import time
import wave
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE_HZ = 16_000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE_HZ * FRAME_MS // 1000
# Silero v6 is fixed at 512-sample (32 ms) windows, which do not divide the
# 30 ms capture frame; the loop re-buffers rather than resampling.
SILERO_FRAME_SAMPLES = 512


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

        self.update_floor(rms, voiced=voiced, segmenting=True)

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
                    self.reseed_floor(
                        self.frame_rms(np.frombuffer(utterance, dtype=np.int16))
                    )
                self._reset_segment()
                events.append(VadEvent("speech_end", utterance))
        return events

    def update_floor(self, rms: float, *, voiced: bool, segmenting: bool = False) -> None:
        """Adapt the noise floor for one frame.

        Quiet inactive frames adapt fast; voiced frames leak upward ~50x
        slower so a shifted ambient level (fan, traffic) eventually
        re-baselines while a short utterance barely moves the threshold.
        Public so external segmenters (the semantic endpointing path) keep the
        floor — and therefore the playback echo guard — calibrated instead of
        freezing it at the initial value (2026-08-04 sprint review).
        """

        if voiced:
            if rms > self._noise_rms:
                self._noise_rms += (rms - self._noise_rms) * (self.noise_adapt_rate / 50.0)
        elif not (segmenting and self._active):
            # During internal segmentation, hangover silence inside an active
            # utterance does not adapt (unchanged historical behavior).
            self._noise_rms += (rms - self._noise_rms) * self.noise_adapt_rate
            self._noise_rms = max(20.0, self._noise_rms)

    def reseed_floor(self, segment_rms: float) -> None:
        """Escape hatch after a max-length flush: pull the floor toward the
        flushed segment so ambient noise cannot restart immediately."""

        if math.isfinite(segment_rms) and segment_rms > 0.0:
            self._noise_rms = max(self._noise_rms, segment_rms * 0.8)

    def _reset_segment(self) -> None:
        self._active = False
        self._silence_run = 0
        self._voiced_run = 0
        self._speech_frames = []


class AecStage:
    """In-process acoustic echo canceller (AEC ladder rung L1).

    Sits between capture and the VAD: it is handed the near-end microphone
    frame plus whatever far-end audio the playback clock says was emitted in
    that window, and returns the frame with the far-end's contribution
    subtracted. The VAD, the endpointer and the echo guard all then see a
    signal the robot's own voice has been removed from — which is the whole
    point of barge-in without shouting.

    ALGORITHM
        Normalized least-mean-squares adaptive FIR. Deterministic, dependency
        free, and unit-testable against synthetic delayed+attenuated echo. It
        is deliberately NOT the ambition of WebRTC's AEC3: there is no double-
        talk detector, no residual-echo suppressor and no nonlinear
        processing, so it handles a linear echo path and degrades gracefully
        (toward doing nothing) on anything else.

    WHY NOT WebRTC AEC3
        The named upstream wheel (``pywebrtc-audio``) does not install on this
        host: 0.0.1 on PyPI is an empty placeholder and 0.1.0 is source-only
        and needs a C compiler that is not present. Rather than leave the rung
        empty, this is a real canceller behind the seam an AEC3 backend would
        later occupy — swap ``process`` for the wheel's ``AudioProcessor`` and
        nothing upstream of it changes.

    OFF BY DEFAULT
        ``MicrophoneVoiceLoop`` does not construct one unless asked. With no
        AEC stage the frame path is byte-for-byte what it was before.

    LIMITS
        Cross-process clock drift between the far-end reference and the near
        signal is the known killer for any AEC; ``stream_delay_ms`` is the
        mitigation and it must come from the playback clock, not a guess.
        Convergence takes a few hundred ms of far-end activity, so the first
        moments after playback starts are not cancelled.
    """

    def __init__(
        self,
        *,
        filter_taps: int = 512,
        step_size: float = 0.30,
        regularization: float = 1e-6,
        stream_delay_ms: float = 0.0,
    ):
        if filter_taps < 16 or filter_taps > 8192:
            raise ValueError("AEC filter length must be between 16 and 8192 taps")
        if not 0.0 < step_size <= 2.0 or not math.isfinite(step_size):
            raise ValueError("AEC step size must be in (0, 2]")
        if regularization <= 0.0 or not math.isfinite(regularization):
            raise ValueError("AEC regularization must be positive")
        if stream_delay_ms < 0.0 or not math.isfinite(stream_delay_ms):
            raise ValueError("AEC stream delay must be non-negative")
        self.filter_taps = int(filter_taps)
        self.step_size = float(step_size)
        self.regularization = float(regularization)
        self._weights = np.zeros(self.filter_taps, dtype=np.float64)
        self._far_history = np.zeros(self.filter_taps, dtype=np.float64)
        self._far_buffer = np.zeros(0, dtype=np.float64)
        self.frames_processed = 0
        self.set_stream_delay_ms(stream_delay_ms)

    def set_stream_delay_ms(self, stream_delay_ms: float) -> None:
        """Update the near/far alignment from the playback clock."""

        if stream_delay_ms < 0.0 or not math.isfinite(stream_delay_ms):
            raise ValueError("AEC stream delay must be non-negative")
        self.stream_delay_ms = float(stream_delay_ms)
        self._delay_samples = int(self.stream_delay_ms * SAMPLE_RATE_HZ / 1000.0)

    def submit_far(self, pcm: np.ndarray) -> None:
        """Register far-end (loudspeaker) audio as the cancellation reference."""

        if pcm.dtype != np.int16:
            raise TypeError("AEC far-end frames must be int16 PCM")
        self._far_buffer = np.concatenate(
            [self._far_buffer, pcm.astype(np.float64)]
        )
        # Bound the reference buffer: an unconsumed far end must not grow
        # without limit when playback outruns capture.
        limit = SAMPLE_RATE_HZ * 5
        if self._far_buffer.size > limit:
            self._far_buffer = self._far_buffer[-limit:]

    def process(self, near: np.ndarray) -> np.ndarray:
        """Return ``near`` with the far-end's echo estimate removed."""

        if near.dtype != np.int16:
            raise TypeError("AEC near-end frames must be int16 PCM")
        count = near.size
        if count == 0:
            return near

        # Pull the aligned far-end slice; pad with silence when the reference
        # has not arrived (nothing is playing, or the delay outruns the data).
        far = np.zeros(count, dtype=np.float64)
        available = self._far_buffer.size - self._delay_samples
        if available > 0:
            take = min(count, available)
            far[:take] = self._far_buffer[:take]
            self._far_buffer = self._far_buffer[take:]

        near_f = near.astype(np.float64)
        out = np.empty(count, dtype=np.float64)
        weights = self._weights
        history = self._far_history
        for index in range(count):
            history[1:] = history[:-1]
            history[0] = far[index]
            estimate = float(weights @ history)
            error = near_f[index] - estimate
            out[index] = error
            power = float(history @ history) + self.regularization
            weights += (self.step_size * error / power) * history
        self._weights = weights
        self._far_history = history
        self.frames_processed += 1
        return np.clip(out, -32768.0, 32767.0).astype(np.int16)

    @staticmethod
    def erle_db(raw: np.ndarray, cleaned: np.ndarray) -> float:
        """Echo return loss enhancement, 10*log10(P_raw / P_cleaned)."""

        raw_power = float(np.mean(np.square(raw.astype(np.float64))))
        clean_power = float(np.mean(np.square(cleaned.astype(np.float64))))
        if clean_power <= 0.0:
            return float("inf")
        if raw_power <= 0.0:
            return 0.0
        return 10.0 * math.log10(raw_power / clean_power)


def resolve_audio_device(
    spec: object, *, kind: str, query: Callable[[], object] | None = None
) -> tuple[int | None, str]:
    """Resolve a configured device spec to a PortAudio index plus a detail line.

    ``spec`` is ``None`` (system default), an integer PortAudio index, or a
    case-insensitive substring of the device name — the practical form for a
    USB array whose index moves between reboots. Raises ``OSError`` when a
    *requested* device cannot be resolved so the caller degrades loudly; an
    unset spec never raises, because "no configuration" must keep working on
    hosts without PortAudio at all.
    """

    if kind not in {"input", "output"}:
        raise ValueError("device kind must be 'input' or 'output'")
    if spec is None or (isinstance(spec, str) and not spec.strip()):
        return None, "system default"
    if isinstance(spec, bool):
        raise OSError(f"{kind} device must be an index or a name, not a boolean")

    if query is None:

        def query() -> object:
            import sounddevice

            return sounddevice.query_devices()

    try:
        devices = list(query())  # type: ignore[arg-type]
    except Exception as error:
        raise OSError(f"cannot enumerate audio devices: {error}") from error

    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"

    def usable(entry: object) -> bool:
        try:
            return int(entry[channel_key]) > 0  # type: ignore[index]
        except (KeyError, TypeError, ValueError):
            return False

    if isinstance(spec, int):
        if not 0 <= spec < len(devices):
            raise OSError(f"{kind} device index {spec} is out of range")
        entry = devices[spec]
        if not usable(entry):
            raise OSError(f"device {spec} has no {kind} channels")
        return spec, f"{entry['name']} (index {spec})"  # type: ignore[index]

    needle = str(spec).strip().lower()
    matches = [
        (index, entry)
        for index, entry in enumerate(devices)
        if usable(entry) and needle in str(entry["name"]).lower()  # type: ignore[index]
    ]
    if not matches:
        raise OSError(f"no {kind} device matches {spec!r}")
    if len(matches) > 1:
        names = ", ".join(f"{index}:{entry['name']}" for index, entry in matches)  # type: ignore[index]
        raise OSError(f"{kind} device {spec!r} is ambiguous ({names})")
    index, entry = matches[0]
    return index, f"{entry['name']} (index {index})"  # type: ignore[index]


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
        on_speech_start: Callable[[], None] | None = None,
        on_speech_end: Callable[[], None] | None = None,
        device: int | None = None,
        neural_vad: object | None = None,
        endpointer: object | None = None,
        on_turn_commit: Callable[[float], None] | None = None,
        aec: AecStage | None = None,
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
        # Observers for expressive reactions (orient toward the speaker); they
        # are decorative and must never break capture.
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self.device = device
        # Semantic endpointing (cards A3/A4). When an endpointer is supplied
        # it owns turn segmentation instead of the VAD's fixed hangover;
        # ``neural_vad`` (Silero) replaces the energy voiced decision.
        # NOTE: the endpointer must see RAW per-frame speech flags. Feeding it
        # hangover-smoothed state would add the whole hangover to every
        # commit, turning a ~200 ms semantic decision into ~560 ms.
        self.neural_vad = neural_vad
        self.endpointer = endpointer
        self.on_turn_commit = on_turn_commit
        # AEC ladder rung L1, off unless supplied. With aec=None the frame
        # path below is byte-for-byte unchanged.
        self.aec = aec
        self._silero_tail = np.zeros(0, dtype=np.int16)
        self._utterance = bytearray()
        self._turn_active = False
        self._last_is_speech = False
        self._elapsed_s = 0.0
        self._speech_started_at: float | None = None
        self.turn_commits = 0
        self.utterances_submitted = 0
        self.barge_ins_triggered = 0
        self.echo_guard_suppressions = 0
        # Acoustic-side clocks for the latency ledger. `_elapsed_s` is a
        # SAMPLE clock (frames * 30 ms) with no monotonic anchor, so on its
        # own it cannot be compared with anything else in the ledger. These
        # capture time.monotonic() at the two moments that matter — the last
        # speech frame of the turn, and the endpointer's commit — which is
        # what makes "acoustically anchored end of owner speech" a real
        # timestamp instead of a lower bound. Plain data: nothing here reaches
        # into the tracker, so the capture path stays dependency free.
        self.last_turn_clocks: dict[str, float] | None = None
        self._speech_end_monotonic: float | None = None

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
                    device=self.device,
                    samplerate=SAMPLE_RATE_HZ,
                    channels=1,
                    dtype="int16",
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
            device=self.device,
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
        if self.aec is not None:
            # Cancel BEFORE the echo guard and the VAD, so every downstream
            # decision is made on a signal the robot's own voice has been
            # removed from. A failing canceller must not deafen the robot:
            # it is dropped and capture continues on the raw frame.
            try:
                frame = self.aec.process(frame)
            except Exception as error:  # noqa: BLE001 - AEC boundary
                logger.warning("AEC failed; continuing without it: %s", error)
                self.aec = None
        # Echo guard (N17). During playback the robot's own voice bleeds into
        # the speaker-adjacent mic, and with no AEC we must not treat that bleed
        # as the owner barging in. The guard used to RETURN on every
        # below-threshold frame, i.e. it removed frames from the VAD's INPUT.
        # For the neural VAD that was actively harmful: Silero was trained on a
        # continuous stream, and feeding it only the loud survivors manufactured
        # artificial onsets that it scored as speech, driving the false-barge-in
        # rate to 1.00 on noise-only injections. Instead compute the guard here
        # but let every frame reach the VAD; ``echo_suppressed`` gates the
        # DECISION (may this frame start / sustain a barge-in?), never the input.
        echo_suppressed = False
        if playback:
            rms = EnergyVad.frame_rms(frame)
            guard = self.vad.noise_rms * self.vad.threshold_scale * self.echo_guard_scale
            if rms <= guard:
                echo_suppressed = True
                self.echo_guard_suppressions += 1
        if self.endpointer is not None:
            # Neural path: Silero must see the CONTINUOUS stream (the N17 fix),
            # so the frame is always processed; ``echo_suppressed`` only decides
            # whether the resulting speech flag may act.
            self._handle_frame_semantic(
                frame, playback=playback, echo_suppressed=echo_suppressed
            )
            return
        # Energy path (legacy, no neural VAD). The energy segmenter is stateful
        # hangover logic, not a continuous neural model, so the historical
        # swallow is preserved unchanged: a guard-suppressed frame is not fed to
        # it at all. This keeps the shipped half-duplex barge-in behaviour when
        # semantic endpointing is off.
        if echo_suppressed:
            return
        for event in self.vad.process(frame):
            if event.kind == "speech_start":
                self._notify(self.on_speech_start)
                if playback:
                    self.barge_ins_triggered += 1
                    try:
                        self.barge_in()
                    except Exception as error:  # noqa: BLE001
                        logger.warning("barge-in failed: %s", error)
            elif event.kind == "speech_end":
                self._notify(self.on_speech_end)
                self._finish_utterance(event.utterance)

    def _frame_is_speech(self, frame: np.ndarray) -> bool:
        """Raw per-frame speech decision: Silero when usable, energy else.

        Either way the EnergyVad noise floor keeps adapting — the playback
        echo guard compares against it, so freezing it at the initial value
        would mis-calibrate barge-in for the whole session (sprint review).
        """

        vad = self.neural_vad
        if vad is not None and getattr(vad, "available", False):
            self._silero_tail = np.concatenate([self._silero_tail, frame])
            decided = False
            # Silero wants 512-sample windows; the capture frame is 480.
            while self._silero_tail.size >= SILERO_FRAME_SAMPLES:
                window = self._silero_tail[:SILERO_FRAME_SAMPLES]
                self._silero_tail = self._silero_tail[SILERO_FRAME_SAMPLES:]
                try:
                    probability = float(vad.process(window))
                except Exception as error:  # noqa: BLE001 - model boundary
                    logger.warning("neural VAD failed; using energy VAD: %s", error)
                    self.neural_vad = None
                    return self._energy_is_speech(frame)
                self._last_is_speech = probability >= getattr(vad, "threshold", 0.5)
                decided = True
            del decided  # incomplete window: hold the previous decision
            self.vad.update_floor(
                EnergyVad.frame_rms(frame), voiced=self._last_is_speech
            )
            return self._last_is_speech
        return self._energy_is_speech(frame)

    def _energy_is_speech(self, frame: np.ndarray) -> bool:
        rms = EnergyVad.frame_rms(frame)
        self._last_is_speech = rms > self.vad.noise_rms * self.vad.threshold_scale
        self.vad.update_floor(rms, voiced=self._last_is_speech)
        return self._last_is_speech

    def _handle_frame_semantic(
        self, frame: np.ndarray, *, playback: bool, echo_suppressed: bool = False
    ) -> None:
        """Turn segmentation owned by the semantic endpointer."""

        frame_s = frame.size / SAMPLE_RATE_HZ
        self._elapsed_s += frame_s
        # Silero always consumes the frame so its input stays continuous (N17).
        raw_is_speech = self._frame_is_speech(frame)
        # ...but a frame the echo guard flagged as the robot's own bleed cannot
        # COUNT as owner speech: it neither starts a barge-in nor advances the
        # endpointer toward a commit. This is the guard applied to the decision
        # rather than to the model's input.
        is_speech = raw_is_speech and not echo_suppressed

        if is_speech:
            # The last frame that still carried speech is the acoustic end of
            # the owner's turn; everything after it is the endpointer thinking.
            self._speech_end_monotonic = time.monotonic()
        if is_speech and not self._turn_active:
            self._turn_active = True
            self._utterance.clear()
            self._speech_started_at = self._elapsed_s
            self._notify(self.on_speech_start)
            if playback:
                self.barge_ins_triggered += 1
                try:
                    self.barge_in()
                except Exception as error:  # noqa: BLE001
                    logger.warning("barge-in failed: %s", error)
        if self._turn_active:
            self._utterance.extend(frame.tobytes())
            # Same bound the energy path enforces via max_utterance_frames:
            # without it, unbroken "speech" (sustained noise, a stuck VAD)
            # grows the buffer without limit and never commits (sprint
            # review regression). Re-seed the floor exactly like the energy
            # path's too-long flush so noise cannot restart immediately.
            limit_bytes = self.vad.max_utterance_frames * FRAME_SAMPLES * 2
            if len(self._utterance) >= limit_bytes:
                segment = np.frombuffer(bytes(self._utterance), dtype=np.int16)
                self.vad.reseed_floor(EnergyVad.frame_rms(segment))
                self._commit_turn()
                return

        tail = (
            np.frombuffer(bytes(self._utterance), dtype=np.int16)
            if self._utterance
            else None
        )
        try:
            decision = self.endpointer.observe(
                is_speech=is_speech, audio_tail=tail, now_s=self._elapsed_s
            )
        except Exception as error:  # noqa: BLE001 - endpointer boundary
            logger.warning("endpointer failed; reverting to energy VAD: %s", error)
            self.endpointer = None
            if self._turn_active:
                # Do not strand the turn: commit what was captured so the
                # orient reaction releases and the owner is not ignored.
                self._commit_turn()
            return
        if decision == "commit" and self._turn_active:
            self._commit_turn()

    def _commit_turn(self) -> None:
        utterance = bytes(self._utterance)
        latency_s = 0.0
        if self._speech_started_at is not None:
            latency_s = max(0.0, self._elapsed_s - self._speech_started_at)
        commit_monotonic = time.monotonic()
        # A turn with no observed speech frame (max-length flush of pure noise)
        # has no acoustic end; collapsing it onto the commit instant reports a
        # zero decision time, which is true and not misleading.
        speech_end = self._speech_end_monotonic or commit_monotonic
        self.last_turn_clocks = {
            "speech_end_monotonic": speech_end,
            "semantic_commit_monotonic": commit_monotonic,
            # How long the endpointer deliberated after the owner stopped
            # talking. This is the span that ep50 measures acoustically.
            "endpoint_decision_s": max(0.0, commit_monotonic - speech_end),
            "utterance_s": len(utterance) / 2 / SAMPLE_RATE_HZ,
        }
        self._speech_end_monotonic = None
        self._turn_active = False
        self._utterance.clear()
        self._speech_started_at = None
        self.turn_commits += 1
        self._notify(self.on_speech_end)
        if self.on_turn_commit is not None:
            try:
                self.on_turn_commit(latency_s)
            except Exception as error:  # noqa: BLE001 - metric boundary
                logger.warning("turn-commit observer failed: %s", error)
        self._finish_utterance(utterance)

    @staticmethod
    def _notify(observer: Callable[[], None] | None) -> None:
        if observer is None:
            return
        try:
            observer()
        except Exception as error:  # noqa: BLE001 - decorative observer boundary
            logger.warning("voice observer failed: %s", error)

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

    def __init__(
        self,
        *,
        player: Callable[[bytes, int], None] | None = None,
        device: int | None = None,
        on_chunk_start: Callable[[object], None] | None = None,
    ):
        self._player = player
        self.device = device
        # Fired on the worker thread the moment a chunk actually begins
        # playing, carrying whatever token was attached at enqueue time.
        # This is the only honest anchor for the audio playback clock: a
        # chunk enqueued now may not be audible for seconds.
        self._on_chunk_start = on_chunk_start
        self._queue: queue.Queue[tuple[bytes, object] | None] = queue.Queue(maxsize=256)
        self._interrupted = threading.Event()
        self._playing = threading.Event()
        # AEC ladder rung L2 (ducking). 1.0 is unity: with no duck ever
        # requested the sample path is byte-for-byte what it was before.
        self._gain = 1.0
        self._duck_started_at: float | None = None
        self.ducks_applied = 0
        self.ducks_restored = 0
        # Speaker-worker first-sample clock (the third of the ledger's four
        # missing clocks). on_chunk_start already fires at the true start of a
        # chunk, but today it only anchors beat motion; recording the instant
        # here makes it available to the ledger without changing that callback
        # contract. Note honestly what this is: the moment the worker began
        # WRITING the chunk, not the moment it became audible. The virtual-rig
        # eval measured 0.54-0.64 s between the two.
        self.first_chunk_started_monotonic: float | None = None
        self.last_chunk_started_monotonic: float | None = None
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
        # A new reply gets a new first-sample anchor; the previous turn's
        # value would otherwise make every later turn look instantaneous.
        self.first_chunk_started_monotonic = None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        """Session-facing ``audio_chunk_player`` callback.

        ``token`` travels with the chunk and is handed to ``on_chunk_start``
        when this exact chunk begins playing (used to anchor beat-synced
        motion to the playback clock).
        """

        if not chunk:
            return
        try:
            self._queue.put_nowait((chunk, token))
        except queue.Full:
            logger.warning("speaker queue overflow; dropping audio chunk")

    @property
    def gain(self) -> float:
        """Current output gain multiplier (1.0 = unity, <1.0 = ducked)."""

        return self._gain

    @property
    def ducked(self) -> bool:
        return self._gain < 1.0

    def duck(self, attenuation_db: float = 10.0) -> None:
        """Drop output level on a PROVISIONAL barge-in hit (AEC rung L2).

        The roadmap's provisional-epoch design: when the VAD thinks the owner
        may have started talking but nothing is confirmed yet, do not tear the
        turn down — just get quieter. A 9-12 dB drop improves the owner's
        near-end-to-echo ratio by the same amount, which is usually enough for
        the endpointer to hear them properly and decide. If it was a false
        alarm, ``restore()`` puts the level back and the turn was never
        damaged; supersession still requires the normal commit criteria.

        The gain is applied per ~50 ms output block, so it takes effect within
        one block rather than at the next chunk boundary.
        """

        if not math.isfinite(attenuation_db) or not 0.0 < attenuation_db <= 60.0:
            raise ValueError("duck attenuation must be in (0, 60] dB")
        self._gain = float(10.0 ** (-attenuation_db / 20.0))
        self._duck_started_at = time.monotonic()
        self.ducks_applied += 1

    def restore(self) -> None:
        """Return to unity gain (the barge-in was not confirmed)."""

        if self._gain != 1.0:
            self.ducks_restored += 1
        self._gain = 1.0
        self._duck_started_at = None

    @property
    def ducked_for_s(self) -> float:
        """How long the current duck has been held, for the confirm window."""

        started = self._duck_started_at
        if started is None:
            return 0.0
        return max(0.0, time.monotonic() - started)

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
            item = self._queue.get()
            if item is None:
                return
            chunk, token = item
            if self._interrupted.is_set():
                continue
            try:
                pcm, sample_rate = self._decode(chunk)
                if not pcm:
                    continue
                self._playing.set()
                started = time.monotonic()
                self.last_chunk_started_monotonic = started
                if self.first_chunk_started_monotonic is None:
                    self.first_chunk_started_monotonic = started
                if self._on_chunk_start is not None:
                    try:
                        self._on_chunk_start(token)
                    except Exception as error:  # noqa: BLE001 - observer boundary
                        logger.warning("playback-start observer failed: %s", error)
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
            device=self.device, samplerate=sample_rate, channels=1, dtype="int16"
        ) as stream:
            for start in range(0, len(data), block):
                if self._interrupted.is_set():
                    # N16: ceasing to WRITE is not enough to stop being heard.
                    # PortAudio has already buffered up to a full output-latency
                    # worth of samples, and the OutputStream context manager
                    # exits through stop(), which *drains* that buffer — the
                    # acoustic rig measured ~0.6 s of the robot still talking
                    # after a correct barge-in decision. abort() discards the
                    # already-queued frames immediately (stop() would play them
                    # out), so the sink goes acoustically silent within one
                    # block of the interrupt instead of one output latency.
                    stream.abort()
                    return
                chunk = data[start : start + block]
                # Read the gain per block so a duck requested mid-chunk takes
                # effect within one ~50 ms block instead of at the next chunk.
                gain = self._gain
                if gain != 1.0:
                    chunk = np.clip(
                        chunk.astype(np.float32) * gain, -32768, 32767
                    ).astype(np.int16)
                stream.write(chunk)
