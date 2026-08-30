"""Generation-safe, interruptible local speaker transport.

``SpeakerSink`` owns its queue, observer worker, and PortAudio stream lifecycle.
The public symbols are re-exported from :mod:`parcel_robot.audio.voice_loop` for
backward compatibility.
"""

from __future__ import annotations

import io
import logging
import math
import queue
import threading
import time
import wave
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import numpy as np

# Keep the historical log category while the class moves modules. Log routing
# is observable production behaviour, and this extraction should not alter it.
logger = logging.getLogger("parcel_robot.audio.voice_loop")

# Raw chunks have always inherited 16 kHz until a RIFF header declares another
# rate. Keep that wire contract local so importing this module cannot cycle
# through voice_loop merely to obtain its microphone-rate constant.
_RAW_PCM_SAMPLE_RATE_HZ = 16_000


@dataclass(frozen=True)
class SpeakerWriteAttempt:
    """First output-buffer attempt for one generation-tagged audio chunk.

    ``monotonic_s`` is normally PortAudio's callback clock mapped onto the
    process monotonic clock. It is not a device-acceptance acknowledgement or
    a DAC/presentation timestamp.
    """

    generation: int
    token: object
    monotonic_s: float


@dataclass(frozen=True)
class _SpeakerGeneration:
    epoch: int
    cancelled: threading.Event


def _prepare_output_blocks(
    pcm: bytes, sample_rate: int
) -> tuple[int, Iterator[tuple[np.ndarray, bool]], np.ndarray]:
    """Pre-build fixed-size blocks so the PortAudio callback allocates none."""

    data = np.frombuffer(pcm, dtype=np.int16)
    block = max(1, sample_rate // 20)
    shaped = data.reshape(-1, 1)
    prepared_blocks: list[np.ndarray] = []
    for start in range(0, len(data), block):
        stop = min(start + block, len(data))
        if stop - start == block:
            prepared_blocks.append(shaped[start:stop])
        else:
            final = np.zeros((block, 1), dtype=np.int16)
            final[: stop - start, 0] = data[start:stop]
            prepared_blocks.append(final)
    blocks = tuple(
        (prepared, index == len(prepared_blocks) - 1)
        for index, prepared in enumerate(prepared_blocks)
    )
    return block, iter(blocks), np.zeros((block, 1), dtype=np.int16)


class _WorkerOwnedStream:
    """PortAudio lifecycle wrapper called only by the speaker worker."""

    def __init__(self, stream: object) -> None:
        self.stream = stream
        self.closed = False

    def close(self) -> None:
        self.stream.close(ignore_errors=False)
        self.closed = True

    def abort_and_close(self) -> None:
        try:
            self.stream.abort(ignore_errors=False)
        except Exception as error:
            logger.warning("audio output abort failed on speaker worker: %s", error)
            # close(active) is PortAudio's documented discard path. Never
            # permit a context-manager draining stop on this failure path.
            self.close()
            raise
        self.close()

    def fail_closed(self, primary: Exception) -> None:
        if self.closed:
            return
        try:
            self.close()
        except Exception as close_error:
            logger.warning(
                "audio output fail-closed close failed on speaker worker: %s",
                close_error,
            )
            raise OSError(
                f"audio output failed ({primary}); fail-closed close also failed"
            ) from close_error


class SpeakerSink:
    """Ordered audio player with generation-safe interruption.

    Every chunk carries the utterance generation that accepted it. Barge-in
    cancels that one-way generation; only :meth:`begin_utterance` advances to
    a playable generation, so a delayed old chunk cannot be resurrected.

    The speaker worker alone constructs, starts, aborts, stops, and closes the
    PortAudio stream. The bounded Python callback copies pre-built NumPy blocks
    and checks cancellation without application locks, clocks, logging, or
    observer calls. It is suitable for this prototype, but not hard real time.

    An injected ``player`` is a synchronous test/embedding seam and cannot be
    preempted after dispatch. Generation checks still guard that dispatch.
    """

    def __init__(
        self,
        *,
        player: Callable[[bytes, int], None] | None = None,
        device: int | None = None,
        on_chunk_start: Callable[[object], None] | None = None,
        on_write_attempt: Callable[[SpeakerWriteAttempt], None] | None = None,
    ):
        self._player = player
        self.device = device
        self._on_chunk_start = on_chunk_start
        self._on_write_attempt = on_write_attempt
        self._queue: queue.Queue[tuple[_SpeakerGeneration, bytes, object] | None] = queue.Queue(
            maxsize=256
        )
        self._observer_queue: queue.Queue[tuple[_SpeakerGeneration, SpeakerWriteAttempt] | None] = (
            queue.Queue(maxsize=256)
        )
        self._state_changed = threading.Condition(threading.Lock())
        self._generation = 0
        self._current_generation = _SpeakerGeneration(0, threading.Event())
        self._closed = False
        self._interrupted = threading.Event()
        self._playing = threading.Event()
        self._gain = 1.0
        self._duck_started_at: float | None = None
        self.ducks_applied = 0
        self.ducks_restored = 0
        # Historical ``*_started_*`` fields remain compatibility aliases; all
        # four clocks denote output-buffer attempts, not DAC presentation.
        self.first_chunk_write_attempt_monotonic: float | None = None
        self.last_chunk_write_attempt_monotonic: float | None = None
        self.first_chunk_started_monotonic: float | None = None
        self.last_chunk_started_monotonic: float | None = None
        self._sample_rate = _RAW_PCM_SAMPLE_RATE_HZ
        self._header_parsed = False
        self._observer_worker = threading.Thread(
            target=self._run_observers,
            name="parcel-voice-speaker-observer",
            daemon=True,
        )
        self._observer_worker.start()
        self._worker = threading.Thread(
            target=self._run,
            name="parcel-voice-speaker",
            daemon=True,
        )
        self._worker.start()

    @property
    def playback_active(self) -> bool:
        return self._playing.is_set()

    @property
    def generation(self) -> int:
        """Current utterance generation for event-boundary rejection."""

        return self._generation

    def begin_utterance(self) -> None:
        """Advance to and arm a new, non-cancelled reply generation."""

        with self._state_changed:
            if self._closed:
                return
            self._current_generation.cancelled.set()
            self._generation += 1
            self._current_generation = _SpeakerGeneration(self._generation, threading.Event())
            self._interrupted.clear()
            self.first_chunk_write_attempt_monotonic = None
            self.first_chunk_started_monotonic = None
            self._state_changed.notify_all()

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        """Accept one synthesizer chunk into the current generation."""

        if not chunk:
            return
        with self._state_changed:
            generation = self._current_generation
            if self._closed or generation.cancelled.is_set():
                return
            try:
                self._queue.put_nowait((generation, chunk, token))
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
        """Lower output on a provisional barge-in hit."""

        if not math.isfinite(attenuation_db) or not 0.0 < attenuation_db <= 60.0:
            raise ValueError("duck attenuation must be in (0, 60] dB")
        self._gain = float(10.0 ** (-attenuation_db / 20.0))
        self._duck_started_at = time.monotonic()
        self.ducks_applied += 1

    def restore(self) -> None:
        """Restore unity gain after an unconfirmed barge-in."""

        if self._gain != 1.0:
            self.ducks_restored += 1
        self._gain = 1.0
        self._duck_started_at = None

    @property
    def ducked_for_s(self) -> float:
        """Return how long the current provisional duck has been held."""

        started = self._duck_started_at
        if started is None:
            return 0.0
        return max(0.0, time.monotonic() - started)

    def interrupt(self) -> None:
        """Cancel the current generation and flush its queued audio."""

        with self._state_changed:
            if self._closed:
                return
            self._current_generation.cancelled.set()
            self._interrupted.set()
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._state_changed.notify_all()

    def close(self, timeout: float = 3.0) -> None:
        """Signal both workers and join either one that is not the caller."""

        deadline = time.monotonic() + max(0.0, timeout)
        with self._state_changed:
            first_signal = not self._closed
            if first_signal:
                self._current_generation.cancelled.set()
                self._interrupted.set()
                self._closed = True
                while True:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        break
                self._queue.put_nowait(None)
                # Reserve the observer sentinel without a potentially blocking
                # put; queued decorative notifications no longer matter.
                while True:
                    try:
                        self._observer_queue.get_nowait()
                    except queue.Empty:
                        break
                self._observer_queue.put_nowait(None)
                self._state_changed.notify_all()

        caller = threading.current_thread()
        if self._worker is not caller:
            self._worker.join(max(0.0, deadline - time.monotonic()))
        if self._observer_worker is not caller:
            self._observer_worker.join(max(0.0, deadline - time.monotonic()))

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._playing.clear()
                return
            generation, chunk, token = item
            if self._generation_cancelled(generation):
                continue
            try:
                pcm, sample_rate = self._decode(chunk)
                if not pcm or self._generation_cancelled(generation):
                    continue
                self._playing.set()
                self._play(pcm, sample_rate, token, generation)
            except Exception as error:  # noqa: BLE001 - device boundary
                if self._generation_cancelled(generation):
                    logger.debug("audio playback interrupted: %s", error)
                else:
                    logger.warning("audio playback failed: %s", error)
            finally:
                # The in-flight call is the sole authority for this flag.
                self._playing.clear()

    def _run_observers(self) -> None:
        while True:
            item = self._observer_queue.get()
            if item is None:
                return
            generation, event = item
            if self._generation_cancelled(generation):
                continue
            event_observer = self._on_write_attempt
            if event_observer is not None:
                try:
                    event_observer(event)
                except Exception as error:  # noqa: BLE001 - observer boundary
                    logger.warning("playback-write-attempt observer failed: %s", error)
            if self._generation_cancelled(generation):
                continue
            observer = self._on_chunk_start
            if observer is not None:
                try:
                    observer(event.token)
                except Exception as error:  # noqa: BLE001 - observer boundary
                    logger.warning("playback-write-attempt observer failed: %s", error)

    def _generation_cancelled(self, generation: _SpeakerGeneration) -> bool:
        return self._closed or generation.cancelled.is_set()

    def _decode(self, chunk: bytes) -> tuple[bytes, int]:
        if chunk[:4] == b"RIFF":
            with wave.open(io.BytesIO(chunk), "rb") as reader:
                self._sample_rate = reader.getframerate()
                self._header_parsed = True
                return reader.readframes(reader.getnframes()), self._sample_rate
        return chunk, self._sample_rate

    def _publish_write_attempt(
        self,
        generation: _SpeakerGeneration,
        token: object,
        monotonic_s: float,
    ) -> bool:
        """Publish callback state from the ordinary speaker worker."""

        with self._state_changed:
            if self._generation_cancelled(generation):
                return False
            event = SpeakerWriteAttempt(generation.epoch, token, monotonic_s)
            self.last_chunk_write_attempt_monotonic = monotonic_s
            self.last_chunk_started_monotonic = monotonic_s
            if self.first_chunk_write_attempt_monotonic is None:
                self.first_chunk_write_attempt_monotonic = monotonic_s
                self.first_chunk_started_monotonic = monotonic_s
            if self._on_write_attempt is not None or self._on_chunk_start is not None:
                try:
                    self._observer_queue.put_nowait((generation, event))
                except queue.Full:
                    logger.warning("playback observer queue overflow; dropping event")
            return True

    def _play(
        self,
        pcm: bytes,
        sample_rate: int,
        token: object,
        generation: _SpeakerGeneration,
    ) -> None:
        if self._player is not None:
            self._play_injected(pcm, sample_rate, token, generation)
            return
        self._play_device(pcm, sample_rate, token, generation)

    def _play_injected(
        self,
        pcm: bytes,
        sample_rate: int,
        token: object,
        generation: _SpeakerGeneration,
    ) -> None:
        if self._generation_cancelled(generation):
            return
        attempted_at = time.monotonic()
        if not self._publish_write_attempt(generation, token, attempted_at):
            return
        if self._generation_cancelled(generation):
            return
        player = self._player
        if player is not None:
            player(pcm, sample_rate)

    def _play_device(
        self,
        pcm: bytes,
        sample_rate: int,
        token: object,
        generation: _SpeakerGeneration,
    ) -> None:
        import sounddevice

        block, block_iterator, silence = _prepare_output_blocks(pcm, sample_rate)
        callback, callback_state = self._make_output_callback(
            sounddevice, block, block_iterator, silence, generation
        )
        stream = sounddevice.OutputStream(
            device=self.device,
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=block,
            callback=callback,
        )
        self._drive_output_stream(_WorkerOwnedStream(stream), callback_state, generation, token)

    def _make_output_callback(
        self,
        sounddevice: object,
        block: int,
        block_iterator: Iterator[tuple[np.ndarray, bool]],
        silence: np.ndarray,
        generation: _SpeakerGeneration,
    ) -> tuple[Callable[..., None], list[object]]:
        """Build the bounded PortAudio callback and its preallocated state."""

        cb_raw_time, cb_status, cb_error, cb_finished = range(4)
        callback_state: list[object] = [None, None, 0, False]
        callback_error_frames = 1
        callback_error_buffer = 2
        callback_stop = sounddevice.CallbackStop
        callback_abort = sounddevice.CallbackAbort

        def callback(outdata, frames, time_info, status) -> None:
            callback_state[cb_status] = status
            try:
                if frames != block:
                    callback_state[cb_error] = callback_error_frames
                    outdata[...] = silence
                    raise callback_abort
                if callback_state[cb_finished]:
                    outdata[...] = silence
                    raise callback_stop
                if generation.cancelled.is_set():
                    outdata[...] = silence
                    return
                if callback_state[cb_raw_time] is None:
                    callback_state[cb_raw_time] = time_info.currentTime
                source, final_block = next(block_iterator)
                gain = self._gain
                if gain == 1.0:
                    outdata[...] = source
                else:
                    np.multiply(source, gain, out=outdata, casting="unsafe")
                if generation.cancelled.is_set():
                    outdata[...] = silence
                    return
                if final_block:
                    callback_state[cb_finished] = True
                    raise callback_stop
            except (callback_stop, callback_abort):
                raise
            except Exception:  # noqa: BLE001 - convert to device abort signal
                callback_state[cb_error] = callback_error_buffer
                raise callback_abort

        return callback, callback_state

    def _drive_output_stream(
        self,
        owned: _WorkerOwnedStream,
        callback_state: list[object],
        generation: _SpeakerGeneration,
        token: object,
    ) -> None:
        """Drive one output stream entirely on the speaker worker."""

        stream = owned.stream
        cb_raw_time, cb_status, cb_error = 0, 1, 2
        try:
            try:
                stream_clock_offset = time.monotonic() - float(stream.time)
                if not math.isfinite(stream_clock_offset):
                    stream_clock_offset = None
            except Exception:  # noqa: BLE001 - optional PortAudio clock
                stream_clock_offset = None

            if self._generation_cancelled(generation):
                owned.close()
                return
            stream.start()
            published = False
            while True:
                raw_time = callback_state[cb_raw_time]
                if not published and raw_time is not None:
                    if stream_clock_offset is None:
                        attempted_at = time.monotonic()
                    else:
                        attempted_at = float(raw_time) + stream_clock_offset
                        if not math.isfinite(attempted_at):
                            attempted_at = time.monotonic()
                    published = self._publish_write_attempt(generation, token, attempted_at)
                if self._generation_cancelled(generation):
                    owned.abort_and_close()
                    return
                if callback_state[cb_error] != 0:
                    error_code = callback_state[cb_error]
                    owned.abort_and_close()
                    raise OSError(f"audio output callback failed (bounded error code {error_code})")
                if not stream.active:
                    break
                with self._state_changed:
                    if not self._generation_cancelled(generation):
                        self._state_changed.wait(timeout=0.005)

            stream.stop(ignore_errors=False)
            owned.close()
            status = callback_state[cb_status]
            if status:
                logger.debug("audio output status: %s", status)
        except Exception as primary:
            owned.fail_closed(primary)
            raise
