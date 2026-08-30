"""Unit coverage for the three acoustic-close defects N16 / N17 / N19.

These are deterministic, hardware-free tests that pin the *code paths* the
fixes changed. The wall-clock acoustic improvements the fixes target
(post-interrupt output-buffer drain for N16; a genuine attenuated echo for
N17) require a real output device with real latency and a real acoustic echo
path; the virtual `acoustic_loop_v1` null-sink rig cannot exhibit either (its
OutputStream reports ~0 s latency, and it has no acoustic coupling). See
scrum/20260809/task_8/ACOUSTIC_CLOSE_STATUS.md for the rig evidence.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from parcel_robot.audio.voice_loop import (
    FRAME_SAMPLES,
    EnergyVad,
    MicrophoneVoiceLoop,
    SpeakerSink,
    SpeakerWriteAttempt,
    pcm16_wav,
)
from parcel_robot.observability import STAGES, LatencyTracker


# --------------------------------------------------------------------- N16
class _CallbackStop(Exception):
    pass


class _CallbackAbort(Exception):
    pass


class _CallbackOutputStream:
    """Deterministic callback-mode PortAudio stand-in.

    Lifecycle methods record their calling thread. The callback runs on its
    own fake PortAudio thread, just like sounddevice, and can be held after its
    first buffer so cancellation is exercised while device output is active.
    """

    def __init__(
        self,
        *,
        index: int,
        calls: list[tuple[object, ...]],
        kwargs: dict[str, object],
        start_started: threading.Event | None = None,
        start_release: threading.Event | None = None,
        hold_after_first: threading.Event | None = None,
        first_buffer: threading.Event | None = None,
        callback_ready: threading.Event | None = None,
        callback_release: threading.Event | None = None,
        rejecting_buffer: bool = False,
        callbacks_after_stop: int = 0,
        abort_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.index = index
        self.calls = calls
        self.callback = kwargs["callback"]
        self.blocksize = int(kwargs["blocksize"])
        self.samplerate = int(kwargs["samplerate"])
        self.start_started = start_started
        self.start_release = start_release
        self.hold_after_first = hold_after_first
        self.first_buffer = first_buffer
        self.callback_ready = callback_ready
        self.callback_release = callback_release
        self.rejecting_buffer = rejecting_buffer
        self.callbacks_after_stop = callbacks_after_stop
        self.abort_error = abort_error
        self.close_error = close_error
        self._aborted = threading.Event()
        self._finished = threading.Event()
        self._started = False
        self._closed = False
        self._stream_clock = 1000.0 + index * 100.0
        self._callback_thread: threading.Thread | None = None

    @property
    def time(self) -> float:
        return self._stream_clock

    @property
    def active(self) -> bool:
        return self._started and not self._finished.is_set() and not self._closed

    def start(self) -> None:
        self.calls.append(("start", self.index, threading.current_thread().name))
        if self.start_started is not None:
            self.start_started.set()
        if self.start_release is not None:
            assert self.start_release.wait(2.0), "test did not release stream start"
        self._started = True
        self._callback_thread = threading.Thread(
            target=self._drive,
            name=f"fake-portaudio-{self.index}",
            daemon=True,
        )
        self._callback_thread.start()

    def _finish(self) -> None:
        if self._finished.is_set():
            return
        self._finished.set()

    def _drive(self) -> None:
        first = True
        while not self._aborted.is_set():
            if first and self.callback_ready is not None:
                self.callback_ready.set()
            if first and self.callback_release is not None:
                self.callback_release.wait(2.0)
            if self.rejecting_buffer:
                outdata: object = _RejectingOutputBuffer(self.blocksize)
            else:
                outdata = np.zeros((self.blocksize, 1), dtype=np.int16)
            result = "returned"
            try:
                callback_number = len(
                    [
                        call
                        for call in self.calls
                        if call[:2] == ("buffer", self.index)
                    ]
                )
                callback_time = self._stream_clock + (
                    callback_number * self.blocksize / self.samplerate
                )
                time_info = type(
                    "TimeInfo", (), {"currentTime": callback_time}
                )()
                self.callback(outdata, self.blocksize, time_info, None)
            except _CallbackStop:
                result = "stop"
            except _CallbackAbort:
                result = "abort"
            peak = int(np.max(outdata)) if isinstance(outdata, np.ndarray) else 0
            self.calls.append(("buffer", self.index, peak, result))
            if first:
                first = False
                if self.first_buffer is not None:
                    self.first_buffer.set()
                if self.hold_after_first is not None:
                    self.hold_after_first.wait(2.0)
            if result != "returned":
                if result == "stop" and self.callbacks_after_stop > 0:
                    self.callbacks_after_stop -= 1
                    continue
                self._finish()
                return
        self._finish()

    def abort(self, *, ignore_errors: bool = True) -> None:
        self.calls.append(
            ("abort", self.index, threading.current_thread().name, ignore_errors)
        )
        if self.abort_error is not None:
            raise self.abort_error
        self._aborted.set()
        if self.callback_release is not None:
            self.callback_release.set()
        if self.hold_after_first is not None:
            self.hold_after_first.set()
        self._finish()

    def stop(self, *, ignore_errors: bool = True) -> None:
        self.calls.append(
            ("stop", self.index, threading.current_thread().name, ignore_errors)
        )
        self._finish()

    def close(self, *, ignore_errors: bool = True) -> None:
        self.calls.append(
            ("close", self.index, threading.current_thread().name, ignore_errors)
        )
        self._closed = True
        self._aborted.set()
        if self.callback_release is not None:
            self.callback_release.set()
        if self.hold_after_first is not None:
            self.hold_after_first.set()
        self._finish()
        thread = self._callback_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(1.0)
        if self.close_error is not None:
            raise self.close_error


class _RejectingOutputBuffer:
    """Allows silence fill but rejects the first non-silence buffer copy."""

    ndim = 2

    def __init__(self, frames: int) -> None:
        self.frames = frames

    def fill(self, _value: int) -> None:
        return None

    def __setitem__(self, _key: object, _value: object) -> None:
        raise RuntimeError("device rejected output buffer")


class _CallbackSounddevice:
    CallbackStop = _CallbackStop
    CallbackAbort = _CallbackAbort

    def __init__(
        self,
        calls: list[tuple[object, ...]],
        *,
        first_enter_started: threading.Event | None = None,
        first_enter_release: threading.Event | None = None,
        hold_after_first: threading.Event | None = None,
        first_buffer: threading.Event | None = None,
        callback_ready: threading.Event | None = None,
        callback_release: threading.Event | None = None,
        rejecting_buffer: bool = False,
        callbacks_after_stop: int = 0,
        abort_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.calls = calls
        self.first_enter_started = first_enter_started
        self.first_enter_release = first_enter_release
        self.hold_after_first = hold_after_first
        self.first_buffer = first_buffer
        self.callback_ready = callback_ready
        self.callback_release = callback_release
        self.rejecting_buffer = rejecting_buffer
        self.callbacks_after_stop = callbacks_after_stop
        self.abort_error = abort_error
        self.close_error = close_error
        self.streams: list[_CallbackOutputStream] = []

    def OutputStream(self, **kwargs: object) -> _CallbackOutputStream:
        index = len(self.streams)
        self.calls.append(("construct", index, threading.current_thread().name))
        stream = _CallbackOutputStream(
            index=index,
            calls=self.calls,
            kwargs=kwargs,
            start_started=self.first_enter_started if index == 0 else None,
            start_release=self.first_enter_release if index == 0 else None,
            hold_after_first=self.hold_after_first if index == 0 else None,
            first_buffer=self.first_buffer if index == 0 else None,
            callback_ready=self.callback_ready if index == 0 else None,
            callback_release=self.callback_release if index == 0 else None,
            rejecting_buffer=self.rejecting_buffer,
            callbacks_after_stop=self.callbacks_after_stop,
            abort_error=self.abort_error,
            close_error=self.close_error,
        )
        self.streams.append(stream)
        return stream


def _wait_for_call(calls: list[tuple[object, ...]], name: str) -> None:
    deadline = time.monotonic() + 2.0
    while not any(call[0] == name for call in calls) and time.monotonic() < deadline:
        time.sleep(0.005)
    assert any(call[0] == name for call in calls), calls


def test_n16_interrupt_is_prompt_and_portaudio_lifecycle_is_worker_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    first_buffer = threading.Event()
    release_callback = threading.Event()
    fake = _CallbackSounddevice(
        calls,
        hold_after_first=release_callback,
        first_buffer=first_buffer,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    sink = SpeakerSink()
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 3200))
        assert first_buffer.wait(2.0), calls

        started = time.monotonic()
        sink.interrupt()
        assert time.monotonic() - started < 0.2
        _wait_for_call(calls, "abort")
    finally:
        release_callback.set()
        sink.close()

    lifecycle = [
        call
        for call in calls
        if call[0] in {"construct", "start", "abort", "stop", "close"}
    ]
    assert lifecycle, calls
    assert {call[2] for call in lifecycle} == {"parcel-voice-speaker"}, lifecycle
    abort = next(call for call in lifecycle if call[0] == "abort")
    assert abort[3] is False, abort
    assert all(call[3] is False for call in lifecycle if call[0] in {"abort", "stop", "close"})
    assert not sink.playback_active


def test_n16_rt_callback_does_not_take_application_lock_or_call_clock_clip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The callback finishes while the application Condition is held.

    Ducking forces the bounded ``np.multiply(..., out=...)`` branch. Clock and
    allocating ``np.clip`` traps make the old hot path fail deterministically.
    """

    from parcel_robot.audio import voice_loop

    calls: list[tuple[object, ...]] = []
    callback_ready = threading.Event()
    callback_release = threading.Event()
    first_buffer = threading.Event()
    hold_after_first = threading.Event()
    fake = _CallbackSounddevice(
        calls,
        callback_ready=callback_ready,
        callback_release=callback_release,
        first_buffer=first_buffer,
        hold_after_first=hold_after_first,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    real_monotonic = time.monotonic

    def guarded_monotonic() -> float:
        assert not threading.current_thread().name.startswith("fake-portaudio")
        return real_monotonic()

    def forbidden_clip(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("allocating np.clip reached the PortAudio callback")

    monkeypatch.setattr(voice_loop.time, "monotonic", guarded_monotonic)
    monkeypatch.setattr(voice_loop.np, "clip", forbidden_clip)

    observer_threads: list[str] = []
    sink = SpeakerSink(
        on_write_attempt=lambda _event: observer_threads.append(
            threading.current_thread().name
        )
    )
    try:
        sink.begin_utterance()
        sink.duck(10.0)
        sink.enqueue(pcm16_wav(b"\x10\x00" * 3200))
        assert callback_ready.wait(2.0), calls
        # If the callback still enters _state_changed this wait cannot finish
        # until the context exits, which fails the assertion below.
        with sink._state_changed:
            callback_release.set()
            assert first_buffer.wait(0.5), calls
            assert sink.first_chunk_write_attempt_monotonic is None
            assert observer_threads == []
        deadline = real_monotonic() + 2.0
        while not observer_threads and real_monotonic() < deadline:
            time.sleep(0.005)
        assert observer_threads == ["parcel-voice-speaker-observer"]
        sink.interrupt()
    finally:
        callback_release.set()
        hold_after_first.set()
        sink.close()

    assert any(call[0] == "buffer" and call[2] > 0 for call in calls), calls


def test_n16_normal_completion_drains_without_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setitem(sys.modules, "sounddevice", _CallbackSounddevice(calls))

    sink = SpeakerSink()
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 3200))
        _wait_for_call(calls, "close")
    finally:
        sink.close()
    assert not any(call[0] == "abort" for call in calls), calls
    assert any(call[0] == "stop" for call in calls)
    assert any(call[0] == "close" for call in calls)
    assert all(call[3] is False for call in calls if call[0] in {"stop", "close"})


def test_n16_post_final_portaudio_callback_repeats_graceful_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A callback already in flight after EOF must not consume the iterator."""

    calls: list[tuple[object, ...]] = []
    fake = _CallbackSounddevice(calls, callbacks_after_stop=1)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    sink = SpeakerSink()
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 800))
        _wait_for_call(calls, "close")
    finally:
        sink.close()

    buffer_results = [call[3] for call in calls if call[0] == "buffer"]
    assert buffer_results[-2:] == ["stop", "stop"], calls
    assert "abort" not in buffer_results


def test_n16_failed_worker_abort_is_not_silently_ignored(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[tuple[object, ...]] = []
    first_buffer = threading.Event()
    release_callback = threading.Event()
    fake = _CallbackSounddevice(
        calls,
        hold_after_first=release_callback,
        first_buffer=first_buffer,
        abort_error=RuntimeError("Pa_AbortStream failed"),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    sink = SpeakerSink()
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 3200))
        assert first_buffer.wait(2.0), calls
        with caplog.at_level(logging.WARNING):
            sink.interrupt()
            _wait_for_call(calls, "close")
    finally:
        release_callback.set()
        sink.close()

    abort = next(call for call in calls if call[0] == "abort")
    assert abort[2:] == ("parcel-voice-speaker", False), abort
    assert "audio output abort failed on speaker worker" in caplog.text
    assert "Pa_AbortStream failed" in caplog.text
    assert not any(call[0] == "stop" for call in calls), calls
    assert any(call[0] == "close" for call in calls), calls
    assert not sink.playback_active


def test_n16_generation_blocks_old_chunk_after_interrupt_and_new_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stream stuck in start() cannot resurrect after the ABA transition."""

    calls: list[tuple[object, ...]] = []
    enter_started = threading.Event()
    enter_release = threading.Event()
    observed: list[object] = []
    fake = _CallbackSounddevice(
        calls,
        first_enter_started=enter_started,
        first_enter_release=enter_release,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    sink = SpeakerSink(on_chunk_start=observed.append)
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x11\x00" * 1600), token="old")
        assert enter_started.wait(2.0), calls

        sink.interrupt()
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x22\x00" * 1600), token="new")
        enter_release.set()

        deadline = time.monotonic() + 2.0
        while observed != ["new"] and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        enter_release.set()
        sink.close()

    assert observed == ["new"], (observed, calls)
    old_peaks = [call[2] for call in calls if call[:2] == ("buffer", 0)]
    new_peaks = [call[2] for call in calls if call[:2] == ("buffer", 1)]
    # The worker may close before the fake callback gets a slot; if it does
    # run, every handed buffer must be silence.
    assert max(old_peaks, default=0) == 0, calls
    assert new_peaks and max(new_peaks) == 0x22, calls
    assert any(call[:2] == ("abort", 0) for call in calls), calls


def test_n16_callback_epoch_never_revalidates_after_interrupt_begin_aba(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pause after start but before callback validation: old data stays zero."""

    calls: list[tuple[object, ...]] = []
    callback_ready = threading.Event()
    callback_release = threading.Event()
    observed: list[object] = []
    fake = _CallbackSounddevice(
        calls,
        callback_ready=callback_ready,
        callback_release=callback_release,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    sink = SpeakerSink(on_chunk_start=observed.append)
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x31\x00" * 1600), token="old")
        assert callback_ready.wait(2.0), calls

        sink.interrupt()
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x42\x00" * 1600), token="new")
        callback_release.set()

        deadline = time.monotonic() + 2.0
        while observed != ["new"] and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        callback_release.set()
        sink.close()

    assert observed == ["new"], (observed, calls)
    old_peaks = [call[2] for call in calls if call[:2] == ("buffer", 0)]
    new_peaks = [call[2] for call in calls if call[:2] == ("buffer", 1)]
    assert old_peaks and max(old_peaks) == 0, calls
    assert new_peaks and max(new_peaks) == 0x42, calls


def test_n16_cancelled_late_enqueue_cannot_stick_playback_active() -> None:
    """Pin the old queue.empty()/continue race with public calls only."""

    entered = threading.Event()
    release = threading.Event()

    def blocking_player(_pcm: bytes, _rate: int) -> None:
        entered.set()
        assert release.wait(2.0)

    sink = SpeakerSink(player=blocking_player)
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 800))
        assert entered.wait(2.0)
        sink.interrupt()
        # This used to land behind the in-flight item after interrupt() had
        # drained the queue. The first item's finally saw a non-empty queue and
        # left _playing set; the stale item then continued without clearing it.
        sink.enqueue(pcm16_wav(b"\x02\x00" * 800))
        release.set()
        deadline = time.monotonic() + 2.0
        while sink.playback_active and time.monotonic() < deadline:
            time.sleep(0.005)
        assert not sink.playback_active
    finally:
        release.set()
        sink.close()


def test_n16_reentrant_close_from_player_signals_both_workers() -> None:
    """close() on the speaker worker must not self-join or leak its observer."""

    holder: dict[str, SpeakerSink] = {}
    returned = threading.Event()

    def closing_player(_pcm: bytes, _rate: int) -> None:
        holder["sink"].close(timeout=0.2)
        returned.set()

    sink = SpeakerSink(player=closing_player)
    holder["sink"] = sink
    sink.begin_utterance()
    sink.enqueue(pcm16_wav(b"\x01\x00" * 800))
    assert returned.wait(2.0)

    # A repeated close finishes joins skipped by the re-entrant first call.
    sink.close(timeout=2.0)
    assert not sink._worker.is_alive()
    assert not sink._observer_worker.is_alive()
    assert not sink.playback_active


def test_n19_clock_is_write_attempt_and_observer_cannot_block_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    first_buffer = threading.Event()
    release_callback = threading.Event()
    observer_started = threading.Event()
    observer_release = threading.Event()

    def blocking_observer(token: object) -> None:
        assert token == "beat-track"
        observer_started.set()
        assert observer_release.wait(2.0)

    fake = _CallbackSounddevice(
        calls,
        hold_after_first=release_callback,
        first_buffer=first_buffer,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    sink = SpeakerSink(on_chunk_start=blocking_observer)
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 3200), token="beat-track")
        assert first_buffer.wait(2.0), calls
        assert observer_started.wait(2.0)
        attempt = sink.first_chunk_write_attempt_monotonic
        assert attempt is not None
        assert sink.first_chunk_started_monotonic == attempt

        # The observer is still blocked, yet cancellation wakes the playback
        # worker and the worker owns the PortAudio abort.
        sink.interrupt()
        _wait_for_call(calls, "abort")
        abort = next(call for call in calls if call[0] == "abort")
        assert abort[2] == "parcel-voice-speaker"
    finally:
        observer_release.set()
        release_callback.set()
        sink.close()


def test_n19_superseded_queued_observer_token_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed old beat token cannot arm motion in the next utterance."""

    calls: list[tuple[object, ...]] = []
    first_observer_started = threading.Event()
    release_first_observer = threading.Event()
    observed: list[object] = []

    def observer(token: object) -> None:
        observed.append(token)
        if token == "old-1":
            first_observer_started.set()
            assert release_first_observer.wait(2.0)

    monkeypatch.setitem(sys.modules, "sounddevice", _CallbackSounddevice(calls))
    sink = SpeakerSink(on_chunk_start=observer)
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 800), token="old-1")
        sink.enqueue(pcm16_wav(b"\x02\x00" * 800), token="old-2")
        assert first_observer_started.wait(2.0)
        deadline = time.monotonic() + 2.0
        while (
            not any(call[:2] == ("close", 1) for call in calls)
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)
        assert any(call[:2] == ("close", 1) for call in calls), calls

        sink.interrupt()
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x03\x00" * 800), token="new")
        release_first_observer.set()
        deadline = time.monotonic() + 2.0
        while observed != ["old-1", "new"] and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        release_first_observer.set()
        sink.close()

    assert observed == ["old-1", "new"], (observed, calls)


def test_n19_delayed_event_carries_callback_write_attempt_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observer scheduling delay cannot move the event's playback anchor."""

    calls: list[tuple[object, ...]] = []
    first_started = threading.Event()
    release_first = threading.Event()
    delivered: list[tuple[SpeakerWriteAttempt, float]] = []

    def observer(event: SpeakerWriteAttempt) -> None:
        if event.token == "first":
            first_started.set()
            assert release_first.wait(2.0)
        delivered.append((event, time.monotonic()))

    monkeypatch.setitem(sys.modules, "sounddevice", _CallbackSounddevice(calls))
    sink = SpeakerSink(on_write_attempt=observer)
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 800), token="first")
        sink.enqueue(pcm16_wav(b"\x02\x00" * 800), token="second")
        assert first_started.wait(2.0), calls
        deadline = time.monotonic() + 2.0
        while (
            not any(call[:2] == ("close", 1) for call in calls)
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)
        assert any(call[:2] == ("close", 1) for call in calls), calls

        time.sleep(0.30)
        release_first.set()
        deadline = time.monotonic() + 2.0
        while len(delivered) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        release_first.set()
        sink.close()

    assert [row[0].token for row in delivered] == ["first", "second"]
    second_event, second_delivery = delivered[1]
    assert second_event.generation == sink.generation
    assert second_delivery - second_event.monotonic_s >= 0.25
    assert sink.last_chunk_write_attempt_monotonic == pytest.approx(
        second_event.monotonic_s
    )


def test_n19_repeated_close_finishes_a_previously_blocked_observer() -> None:
    observer_started = threading.Event()
    observer_release = threading.Event()

    def observer(_event: SpeakerWriteAttempt) -> None:
        observer_started.set()
        assert observer_release.wait(2.0)

    sink = SpeakerSink(
        player=lambda _pcm, _rate: None,
        on_write_attempt=observer,
    )
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 800))
        assert observer_started.wait(2.0)
        started = time.monotonic()
        sink.close(timeout=0.05)
        assert time.monotonic() - started < 0.30
        assert sink._observer_worker.is_alive()

        observer_release.set()
        sink.close(timeout=2.0)
        assert not sink._worker.is_alive()
        assert not sink._observer_worker.is_alive()
    finally:
        observer_release.set()
        sink.close()


def test_n19_failed_buffer_copy_is_recorded_only_as_an_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    observed = threading.Event()
    fake = _CallbackSounddevice(calls, rejecting_buffer=True)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    sink = SpeakerSink(on_chunk_start=lambda _token: observed.set())
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 800), token="rejected")
        assert observed.wait(2.0), calls
        _wait_for_call(calls, "abort")
        assert sink.first_chunk_write_attempt_monotonic is not None
        assert sink.first_chunk_started_monotonic == (
            sink.first_chunk_write_attempt_monotonic
        )
    finally:
        sink.close()

    # No fake buffer accepted samples. The clock/observer therefore cannot be
    # described as accepted or audible playback; it is a write-attempt fact.
    assert all(call[2] == 0 for call in calls if call[0] == "buffer"), calls


# --------------------------------------------------------------------- N17
class _ScriptedNeuralVad:
    """Silero stand-in that records every window it is asked to score.

    ``available`` and ``threshold`` mirror the SileroVad interface the loop
    probes. The recorded ``windows`` count is what proves the loop feeds the
    model a CONTINUOUS stream rather than only the frames that survived the
    echo guard.
    """

    def __init__(self, probability: float) -> None:
        self.available = True
        self.threshold = 0.5
        self._p = probability
        self.windows = 0

    def process(self, window: np.ndarray) -> float:
        self.windows += 1
        return self._p


class _NeverCommit:
    def observe(self, *, is_speech: bool, audio_tail: object, now_s: float) -> str:
        del is_speech, audio_tail, now_s
        return "hold"


def _quiet_frame() -> np.ndarray:
    return np.full(FRAME_SAMPLES, 5, dtype=np.int16)  # RMS 5, far below any guard


def _loud_frame() -> np.ndarray:
    return np.full(FRAME_SAMPLES, 6000, dtype=np.int16)  # RMS 6000, above the guard


def _make_loop(vad: _ScriptedNeuralVad, barge: list[int], *, playback: bool):
    return MicrophoneVoiceLoop(
        recognizer=type("R", (), {"transcribe": lambda self, w: ""})(),
        submit_text=lambda *a, **k: None,
        barge_in=lambda: barge.append(1),
        playback_active=lambda: playback,
        neural_vad=vad,
        endpointer=_NeverCommit(),
        echo_guard_scale=2.5,
    )


def test_n17_neural_vad_sees_quiet_frames_during_playback() -> None:
    # The defect: the echo guard RETURNed on suppressed frames, so Silero saw a
    # fragmented stream. The fix lets every frame reach the model.
    vad = _ScriptedNeuralVad(probability=0.9)
    barge: list[int] = []
    loop = _make_loop(vad, barge, playback=True)
    for _ in range(12):
        loop.run_once(_quiet_frame())  # all below the echo guard
    # Continuity: the model was scored on the quiet frames (would be 0 if the
    # guard still swallowed them before the VAD).
    assert vad.windows > 0
    # ...but a quiet frame cannot COUNT as owner speech: no barge-in, and the
    # guard bookkeeping still records the suppression.
    assert barge == []
    assert loop.echo_guard_suppressions == 12


def test_n17_loud_owner_speech_over_tts_still_barges_in() -> None:
    vad = _ScriptedNeuralVad(probability=0.9)
    barge: list[int] = []
    loop = _make_loop(vad, barge, playback=True)
    for _ in range(6):
        loop.run_once(_loud_frame())  # above the guard: a real owner over TTS
    assert vad.windows > 0
    assert barge, "loud owner speech over TTS must still barge in"
    assert loop.echo_guard_suppressions == 0


def test_n17_no_playback_leaves_the_guard_inert() -> None:
    # With no playback the echo guard must not gate anything: this is the plain
    # capture path and quiet frames simply are not speech-level.
    vad = _ScriptedNeuralVad(probability=0.9)
    barge: list[int] = []
    loop = _make_loop(vad, barge, playback=False)
    for _ in range(6):
        loop.run_once(_quiet_frame())
    assert loop.echo_guard_suppressions == 0
    assert barge == []  # barge-in only fires while the robot is speaking


def test_n17_energy_path_still_swallows_suppressed_frames() -> None:
    # The legacy energy path (no neural VAD, no endpointer) keeps its historical
    # behaviour: a guard-suppressed frame is not fed to the segmenter at all.
    barge: list[int] = []
    loop = MicrophoneVoiceLoop(
        recognizer=type("R", (), {"transcribe": lambda self, w: ""})(),
        submit_text=lambda *a, **k: None,
        barge_in=lambda: barge.append(1),
        playback_active=lambda: True,
        vad=EnergyVad(min_speech_frames=2, hangover_frames=3),
        echo_guard_scale=2.0,
    )
    for _ in range(5):
        loop.run_once(np.full(FRAME_SAMPLES, 5, dtype=np.int16))
    assert loop.echo_guard_suppressions >= 5
    assert barge == []
    for _ in range(3):
        loop.run_once(np.full(FRAME_SAMPLES, 12000, dtype=np.int16))
    assert barge


# --------------------------------------------------------------------- N19
N19_STAGES = (
    "capture_speech_end",
    "semantic_commit",
    "stt_request_start",
    "stt_final",
    "audio_first_sample",
)


def test_n19_new_stages_are_registered() -> None:
    for name in N19_STAGES:
        assert name in STAGES, name


def test_n19_tracker_marks_and_reports_the_acoustic_clocks() -> None:
    tracker = LatencyTracker()
    tracker.start(1, "come here", source="microphone", now=100.0)
    tracker.mark(1, "capture_speech_end", now=100.20)
    tracker.mark(1, "semantic_commit", now=100.40)
    tracker.mark(1, "stt_request_start", now=100.41)
    tracker.mark(1, "stt_final", now=100.70)
    tracker.mark(1, "audio_first_playback", now=100.85)  # enqueue stamp
    tracker.mark(1, "audio_first_sample", now=101.45)  # worker-write lower bound
    tracker.finish(1, "on my way", now=101.50)

    snap = tracker.snapshot()
    row = next(r for r in snap["turns"] if r["turn_id"] == 1)
    assert row["source"] == "microphone"
    offsets = row["stage_offsets_ms"]
    for name in N19_STAGES:
        assert name in offsets, name
    # The gap the ledger was blind to: enqueue stamp vs the worker's first
    # write. This still precedes acoustic presentation on a real device.
    assert offsets["audio_first_sample"] > offsets["audio_first_playback"]


def test_n19_unknown_stage_still_raises() -> None:
    tracker = LatencyTracker()
    tracker.start(1, "hello", now=0.0)
    with pytest.raises(ValueError, match="unsupported latency stage"):
        tracker.mark(1, "not_a_real_stage")


def test_n19_runtime_fans_in_acoustic_clocks_on_duplex_voice_path(
    tmp_path: Path,
) -> None:
    """Prove RobotRuntime fan-in marks fire on the duplex voice-stage path.

    Injects the same surfaces the live duplex path already measures
    (``MicrophoneVoiceLoop.last_turn_clocks``, recognizer ``last_metrics``,
    speaker first-sample callback) and drives ``_voice_stage`` /
    ``_audio_chunk_started`` exactly as DuplexVoiceSession does.
    """

    from parcel_robot.audio.devices import AudioDeviceStatus
    from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
    from parcel_robot.providers import SpeechStack
    from parcel_robot.runtime import RobotRuntime
    from parcel_robot.voice.pipeline import VoiceStage
    from tests.test_runtime import FakeSimulatorBackend

    repo = Path(__file__).resolve().parents[1]
    config = tmp_path / "robot.yaml"
    config.write_text(
        f"""
skills:
  root: {repo / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )

    class _Mic:
        def __init__(self) -> None:
            self.last_turn_clocks = {
                "speech_end_monotonic": 10.20,
                "semantic_commit_monotonic": 10.40,
            }

        def close(self) -> None:
            return None

    class _Recognizer:
        def __init__(self) -> None:
            self.last_metrics = {
                "status": "ok",
                "request_start_monotonic": 10.41,
                "final_monotonic": 10.70,
            }

    observation = SimObservation(
        timestamp=0.0,
        robot=RobotPose(),
        owner=OwnerTrack(
            owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0
        ),
        backend="fake",
    )
    runtime = RobotRuntime(
        config,
        FakeSimulatorBackend(observation),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="n19 fan-in fixture",
        ),
    )
    try:
        runtime.speech_stack = SpeechStack(
            recognizer=_Recognizer(),  # type: ignore[arg-type]
            synthesizer=runtime.speech_stack.synthesizer,
            mode=runtime.speech_stack.mode,
            stt_detail=runtime.speech_stack.stt_detail,
            tts_detail=runtime.speech_stack.tts_detail,
        )
        runtime._microphone_loop = _Mic()  # type: ignore[assignment]

        runtime._voice_stage(
            VoiceStage(
                turn_id=1, name="query_end", timestamp=10.75, transcript="come here"
            )
        )
        runtime._voice_stage(VoiceStage(turn_id=1, name="tts_start", timestamp=11.12))
        runtime._audio_chunk_started(None)
        runtime._voice_stage(VoiceStage(turn_id=1, name="turn_complete", timestamp=12.0))

        turns = runtime.latency_snapshot()["turns"]
        assert turns, "expected a completed latency turn"
        offsets = turns[0]["stage_offsets_ms"]
        for name in N19_STAGES:
            assert name in offsets, f"missing fan-in mark {name} in {sorted(offsets)}"
        assert offsets["capture_speech_end"] < 0.0
        assert offsets["audio_first_sample"] > 0.0

        ledger = tmp_path / "ledger.jsonl"
        written = runtime.write_latency_ledger_row(path=ledger, source="n19-duplex-proof")
        assert written == ledger
        row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
        assert set(N19_STAGES) <= set(row["acoustic_stages_present"])
    finally:
        runtime.close()


def test_n19_runtime_binds_write_attempt_clock_and_rejects_stale_generation() -> None:
    """The production hook preserves capture time and turn/generation lineage.

    This intentionally uses a sink whose interrupt does *not* advance its
    generation. It proves the runtime binding itself rejects an observer that
    was already queued when barge-in happened, rather than relying only on a
    later ``begin_utterance`` to make the generation unequal.
    """

    from parcel_robot.runtime import RobotRuntime

    class _Sink:
        generation = 0

        def begin_utterance(self) -> None:
            self.generation += 1

        def interrupt(self) -> None:
            return None

    class _Expression:
        def __init__(self) -> None:
            self.superseded = 0

        def supersede_speech(self) -> None:
            self.superseded += 1

    runtime = object.__new__(RobotRuntime)
    runtime._speaker_sink = _Sink()
    runtime._audio_effect_lock = threading.RLock()
    runtime._audio_output_turn_id = 41
    runtime._audio_playback_generation = -1
    runtime._audio_playback_turn_id = 0
    runtime.expression = _Expression()

    accepted: list[tuple[object, float | None, int | None]] = []
    runtime._audio_chunk_started = (  # type: ignore[method-assign]
        lambda token, *, playback_start_s=None, turn_id=None: accepted.append(
            (token, playback_start_s, turn_id)
        )
    )

    runtime._begin_audio_utterance()
    first = SpeakerWriteAttempt(1, "turn-41", 123.25)
    runtime._audio_write_attempt(first)
    assert accepted == [("turn-41", 123.25, 41)]

    runtime._audio_output_turn_id = 42
    runtime._begin_audio_utterance()
    runtime._audio_write_attempt(first)
    assert len(accepted) == 1, "old generation was credited to a newer turn"

    current = SpeakerWriteAttempt(2, "turn-42", 124.75)
    runtime._interrupt_speech_audio()
    runtime._audio_write_attempt(current)
    assert len(accepted) == 1, "queued event survived barge-in in the same generation"
    assert runtime.expression.superseded == 1
