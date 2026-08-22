#!/usr/bin/env python
"""Card AIR-1 — how much of the robot's own voice survives the array's AEC.

    tools/measure_erle.py --method mux --out erle_report.json     # preferred
    tools/measure_erle.py --leg floor        --out floor.json     # ... or the fallback
    tools/measure_erle.py --leg uncancelled  --out uncancelled.json --play-device 4
    tools/measure_erle.py --leg cancelled    --out cancelled.json
    tools/measure_erle.py --report floor.json uncancelled.json cancelled.json

TWO METHODS, AND THE FIRST ONE IS THE REAL ONE
-----------------------------------------------
ERLE is a ratio: echo entering the canceller over echo leaving it. On a software
AEC you read both at the same instant — the raw mic node and the cancelled node,
side by side (``docs/ACOUSTIC_BRINGUP_PLAN.md`` §5.3).

**This card's first draft claimed that was impossible here, and it was wrong.**
It asserted that the XVF3800 cancels on-chip and its 2-channel firmware "exposes
only processed beams, so there is no raw mic to read", and built a three-leg
differential around the assertion. In fact each of the two USB capture channels
is a runtime-selectable mux (``AUDIO_MGR_OP_L`` / ``AUDIO_MGR_OP_R``), and its
categories include the raw microphone, the amplified microphone as the canceller
receives it, the far-end reference, and the per-microphone AEC residual. The
same-instant measurement is available on the firmware already installed — no
flashing, no second loudspeaker, no level match. That is ``--method mux``, and
it is what you should use.

The three-leg fallback (``--leg``) remains for a host that cannot reach the
control interface — which, until the owner's udev rule lands, is this one. It
produces the numerator from a second recording in which the canceller has
nothing to cancel *with*: the same probe, at the same acoustic level, from a
loudspeaker that is **not** the array's own DAC.

    attenuation = residual(uncancelled) − residual(cancelled)      [dB]

Its two weak joints are both checked rather than assumed. The ``floor`` leg is
not bookkeeping: if the *cancelled* residual lands on the room's noise floor the
answer is a lower bound, and if the *uncancelled* leg does, the probe never
reached the microphone and there is nothing to measure at all — that one is
refused outright, because subtracting it yields ~0 dB and a confident ``fail``
blaming a clipped amplifier that was never involved.

WHY A SPEECH-SHAPED PROBE AND NOT A TONE
----------------------------------------
Every AEC worth the name has a nonlinear residual-echo suppressor after the
linear filter, and suppressors are tuned on speech. A sine gives a beautiful,
meaningless number. The default probe is deterministic speech-shaped noise with a
~4 Hz syllabic envelope: same long-term spectrum and same modulation depth as
speech, byte-identical between runs because the seed is pinned. ``--probe-wav``
takes a real robot utterance (an R17 ``robot.wav`` segment) when you want the
number for the voice the robot actually has.

THE FIRST TWO SECONDS ARE THROWN AWAY
-------------------------------------
Convergence takes 2–3 s and the suppressor clips the leading syllable. The plan
excludes 2 s; so does ``--exclude``, and the excluded span is reported so nobody
has to take it on trust.

NOTHING HERE CHANGES THE HOST. It opens streams and closes them; it never sets a
default device, never moves a volume, never writes to the array.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
import wave
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "tools") not in sys.path:  # pragma: no cover - script entry
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from xvf3800_probe import (
    ARRAY_RATE_HZ,
    ASR_CHANNEL_INDEX,
    CAPTURE_BEAMS,
    MUX_PAIR_PIPELINE,
    ProbeError,
    XvfControl,
    alsa_gain_state,
    dbfs,
    find_alsa_card,
    find_portaudio_device,
    parse_wpctl_status,
    wpctl_status_text,
)

SCHEMA = "parcel.air1.erle_leg.v1"
REPORT_SCHEMA = "parcel.air1.erle_report.v1"

#: The legs, and what each one is holding constant.
LEGS: tuple[str, ...] = ("floor", "uncancelled", "cancelled", "doubletalk")

#: Analysis frame. 20 ms is the realtime lane's own frame, so a residual measured
#: here is a residual in the units the barge-in detector thinks in.
FRAME_MS = 20

#: Pinned so two runs of the same leg differ by the room and not by the probe.
PROBE_SEED = 20260822

#: The plan's gate (``docs/ACOUSTIC_BRINGUP_PLAN.md`` §5.3, ``:350-354``).
ERLE_GATE_DB = 20.0

#: What the same-instant mux measurement produces. Different apparatus, same
#: quantity — and without the two-loudspeaker level match that the three-leg
#: fallback lives or dies by.
MEASURED_QUANTITY_MUX = (
    "ASR-beam echo attenuation, measured the same-instant way: the amplified "
    "microphone signal entering the canceller (mux category 3) against the "
    "processed beam leaving it (category 6/3), captured simultaneously on the "
    "array's two USB channels while the probe plays through the array's own "
    "amplifier. One recording, one gain, no level match to get wrong."
)

#: What the three legs actually measure. Carried in every report so the number
#: cannot travel without its own definition attached.
MEASURED_QUANTITY = (
    "ASR-beam echo attenuation: everything the XVF3800 does to an echo between "
    "the microphone and the USB endpoint (linear AEC + residual suppressor + "
    "beamformer rejection + capture gain), measured as uncancelled-leg level "
    "minus cancelled-leg level on ch1. NOT textbook ERLE, which needs a raw-mic "
    "tap this firmware does not publish."
)

#: How close the cancelled residual may come to the noise floor before the
#: subtraction stops measuring the AEC and starts measuring the room.
FLOOR_MARGIN_DB = 3.0

#: How far apart a reference microphone may hear the two legs before the level
#: match is called failed. 2 dB is roughly the repeatability of a hand-placed
#: speaker; beyond it the subtraction is measuring loudspeakers.
REFERENCE_TOLERANCE_DB = 2.0


# ================================================================= the probe
def speech_shaped_probe(seconds: float, *, seed: int = PROBE_SEED, rate_hz: int = ARRAY_RATE_HZ,
                        peak_dbfs: float = -6.0) -> np.ndarray:
    """Deterministic speech-shaped, syllable-modulated noise as int16 mono.

    Long-term spectrum: flat to 500 Hz, then −8 dB/octave, which is the usual
    single-line approximation of the long-term average speech spectrum. Envelope:
    a 4 Hz raised cosine at 70 % depth — deep enough that a residual-echo
    suppressor has gaps to open and close in, which is exactly where false
    barge-ins are born.
    """

    rate = int(rate_hz)
    count = max(rate // 10, round(float(seconds) * rate))
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(count)
    spectrum = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(count, 1.0 / rate)
    shape = np.ones_like(freqs)
    knee = 500.0
    above = freqs > knee
    # −8 dB per octave above the knee.
    shape[above] = 10.0 ** (-8.0 * np.log2(freqs[above] / knee) / 20.0)
    shape[freqs < 80.0] = 0.0  # nothing the array's amp can reproduce anyway
    shaped = np.fft.irfft(spectrum * shape, n=count)
    envelope = 0.65 + 0.35 * np.cos(2.0 * np.pi * 4.0 * np.arange(count) / rate)
    signal = shaped * envelope
    peak = float(np.max(np.abs(signal))) or 1.0
    target = (10.0 ** (peak_dbfs / 20.0)) * 32767.0
    signal = signal / peak * target
    ramp = min(count // 2, int(0.02 * rate))
    if ramp > 1:
        window = np.linspace(0.0, 1.0, ramp)
        signal[:ramp] *= window
        signal[-ramp:] *= window[::-1]
    return signal.astype(np.int16)


def load_probe_wav(path: Path, *, rate_hz: int = ARRAY_RATE_HZ) -> np.ndarray:
    """A real robot utterance as the probe. Mono int16 at ``rate_hz``."""

    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        source_rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise ProbeError(f"{path}: {width * 8}-bit WAV; this tool reads PCM16")
    samples = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return resample_linear(samples.astype(np.float64), source_rate, rate_hz).astype(np.int16)


def resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Linear resample. Good enough for a level measurement; named so nobody
    mistakes it for a playback-quality resampler."""

    if int(source_rate) == int(target_rate):
        return np.asarray(samples, dtype=np.float64)
    source = np.asarray(samples, dtype=np.float64)
    duration = source.size / float(source_rate)
    target_count = round(duration * float(target_rate))
    source_x = np.arange(source.size, dtype=np.float64) / float(source_rate)
    target_x = np.arange(target_count, dtype=np.float64) / float(target_rate)
    return np.interp(target_x, source_x, source)


# ============================================================== the analysis
def frame_levels(samples: np.ndarray, *, rate_hz: int = ARRAY_RATE_HZ,
                 frame_ms: int = FRAME_MS) -> np.ndarray:
    """Per-frame RMS (int16 counts) of a mono column."""

    column = np.asarray(samples, dtype=np.float64)
    size = max(1, int(rate_hz * frame_ms / 1000))
    usable = (column.size // size) * size
    if usable == 0:
        return np.zeros(0, dtype=np.float64)
    frames = column[:usable].reshape(-1, size)
    return np.sqrt(np.mean(np.square(frames), axis=1))


def summarise(samples: np.ndarray, *, rate_hz: int = ARRAY_RATE_HZ) -> dict[str, Any]:
    """RMS / percentile levels of one channel over the analysis window."""

    levels = frame_levels(samples, rate_hz=rate_hz)
    column = np.asarray(samples, dtype=np.float64)
    rms = float(np.sqrt(np.mean(np.square(column)))) if column.size else 0.0
    if levels.size:
        ordered = np.sort(levels)
        p50 = float(ordered[int(0.50 * (ordered.size - 1))])
        p90 = float(ordered[int(0.90 * (ordered.size - 1))])
        p99 = float(ordered[int(0.99 * (ordered.size - 1))])
    else:
        p50 = p90 = p99 = 0.0
    return {
        "frames": int(levels.size),
        "rms_dbfs": round(dbfs(rms), 3),
        "frame_p50_dbfs": round(dbfs(p50), 3),
        "frame_p90_dbfs": round(dbfs(p90), 3),
        "frame_p99_dbfs": round(dbfs(p99), 3),
        "peak_dbfs": round(dbfs(float(np.max(np.abs(column)))) if column.size else -math.inf, 3),
    }


def analysis_window(capture: np.ndarray, *, exclude_s: float,
                    rate_hz: int = ARRAY_RATE_HZ) -> np.ndarray:
    """Drop the convergence head. Raises rather than returning an empty window."""

    start = round(float(exclude_s) * rate_hz)
    if capture.shape[0] <= start:
        raise ProbeError(
            f"the capture is {capture.shape[0] / rate_hz:.2f} s but --exclude drops "
            f"{exclude_s:.2f} s; record longer"
        )
    return capture[start:]


# ================================================================== playback
def _sounddevice() -> Any:
    try:
        import sounddevice
    except Exception as error:  # noqa: BLE001 - a missing PortAudio is a result
        raise ProbeError(
            f"sounddevice is unavailable ({error}); source scripts/env-audio.sh first"
        ) from None
    return sounddevice


def default_sink_volume() -> float | None:
    """PipeWire's default-sink volume, recorded with every leg.

    Two legs compared at different volumes are two different experiments. This
    does not *set* anything — it writes down what the owner set.
    """

    status = parse_wpctl_status(wpctl_status_text())
    for row in status.get("sinks", ()):
        if row.get("default"):
            return row.get("volume")
    return None


class _StreamRecorder:
    """An input stream held as an explicit ``Stream`` object, never ``rec()``.

    THE BUG THIS EXISTS TO AVOID, in sounddevice 0.5.5. ``play()``, ``rec()`` and
    ``playrec()`` are conveniences over ONE shared module-level context, and
    ``_CallbackContext.start_stream`` opens with ``stop()`` — so

        sounddevice.play(probe, blocking=False)   # starts
        sounddevice.rec(frames, blocking=True)    # stops the play, then records

    records silence while believing it recorded an echo. ``play()``'s own
    docstring says a non-blocking invocation "can be stopped with ``stop()``";
    what it does not say is that the next ``rec()`` calls it for you. The
    uncancelled ERLE leg is exactly a play-on-one-device, record-on-another, so
    this is not a hypothetical: it would have made every uncancelled leg a
    recording of the noise floor, and ERLE would have come out at roughly zero
    with the canned "clipped amplifier" mechanism printed underneath it.

    Explicit ``InputStream``/``OutputStream`` objects are not in that shared
    context. Module-level ``stop()`` reaches ``_last_callback`` only, so these
    two classes can overlap freely — and with each other's module-level
    conveniences too, which is why the one-device ``playrec`` path below is
    still safe beside a reference recorder.
    """

    def __init__(self, backend: Any, device: int, *, rate_hz: int, channels: int = 1,
                 frames_wanted: int | None = None) -> None:
        self.backend = backend
        self.device = int(device)
        self.rate_hz = int(rate_hz)
        self.channels = int(channels)
        self.frames_wanted = None if frames_wanted is None else int(frames_wanted)
        self.frames_seen = 0
        self._blocks: list[np.ndarray] = []
        self._done = threading.Event()
        self._stream: Any = None

    def __enter__(self) -> Self:
        def _callback(indata, _frames, _time, _status) -> None:
            block = np.asarray(indata)
            self._blocks.append(block.copy())
            self.frames_seen += block.shape[0]
            if self.frames_wanted is not None and self.frames_seen >= self.frames_wanted:
                self._done.set()

        self._stream = self.backend.InputStream(
            samplerate=self.rate_hz, channels=self.channels, dtype="int16",
            device=self.device, callback=_callback,
        )
        self._stream.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.stop()
            stream.close()

    @property
    def active(self) -> bool:
        return bool(self._stream is not None and getattr(self._stream, "active", True))

    def wait(self, timeout: float) -> bool:
        """True when the wanted frame count arrived; False on timeout."""

        if self.frames_wanted is None:
            return True
        return self._done.wait(timeout)

    def samples(self) -> np.ndarray:
        """``(n, channels)`` int16, in arrival order."""

        if not self._blocks:
            return np.zeros((0, self.channels), dtype=np.int16)
        block = np.concatenate(self._blocks, axis=0)
        return block.reshape(-1, 1) if block.ndim == 1 else block


class _ProbePlayer:
    """The probe on an explicit ``OutputStream``. See :class:`_StreamRecorder`.

    Holds the whole probe in memory and hands it out from the callback, so the
    stream keeps running for exactly as long as there is probe left — and, more
    to the point, keeps running while somebody else opens an input stream.
    """

    def __init__(self, backend: Any, data: np.ndarray, device: int, *, rate_hz: int) -> None:
        self.backend = backend
        self.device = int(device)
        self.rate_hz = int(rate_hz)
        self._data = np.ascontiguousarray(data, dtype=np.int16)
        self._cursor = 0
        self._stream: Any = None

    def __enter__(self) -> Self:
        channels = int(self._data.shape[1]) if self._data.ndim > 1 else 1

        def _callback(outdata, frames, _time, _status) -> None:
            end = min(self._cursor + frames, self._data.shape[0])
            chunk = self._data[self._cursor:end]
            outdata[: chunk.shape[0]] = chunk.reshape(chunk.shape[0], channels)
            if chunk.shape[0] < frames:
                outdata[chunk.shape[0]:] = 0
            self._cursor = end

        self._stream = self.backend.OutputStream(
            samplerate=self.rate_hz, channels=channels, dtype="int16",
            device=self.device, callback=_callback,
        )
        self._stream.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.stop()
            stream.close()

    @property
    def active(self) -> bool:
        return bool(self._stream is not None and getattr(self._stream, "active", True))

    @property
    def frames_played(self) -> int:
        return int(self._cursor)


def array_gain_state() -> dict[str, Any]:
    """The array's readable mixer gain, recorded with every leg. READ-ONLY."""

    found = find_alsa_card()
    if found is None:
        return {"available": False, "reason": "no XVF3800 in /proc/asound"}
    return alsa_gain_state(found[0])


def play_and_record(probe: np.ndarray, *, capture_device: int, play_device: int | None,
                    play_rate_hz: int, capture_channels: int = 2,
                    silent: bool = False, backend: Any = None) -> np.ndarray:
    """Record the array while (optionally) a probe plays. Returns ``(n, channels)`` int16."""

    sounddevice = _sounddevice() if backend is None else backend
    seconds = probe.size / float(ARRAY_RATE_HZ)
    frames = round(seconds * ARRAY_RATE_HZ)
    if silent or play_device is None:
        return np.asarray(
            sounddevice.rec(
                frames, samplerate=ARRAY_RATE_HZ, channels=capture_channels,
                dtype="int16", device=capture_device, blocking=True,
            )
        )
    if play_device == capture_device and play_rate_hz == ARRAY_RATE_HZ:
        # One device, one clock: the array plays and listens to itself, which is
        # the whole point of the cancelled leg. ``playrec`` is ONE module-level
        # context — a single duplex stream, no overlap — so it is safe here in a
        # way ``play()`` + ``rec()`` is not.
        stereo = np.repeat(probe.reshape(-1, 1), 2, axis=1)
        return np.asarray(
            sounddevice.playrec(
                stereo, samplerate=ARRAY_RATE_HZ, channels=capture_channels,
                dtype="int16", device=(capture_device, play_device), blocking=True,
            )
        )
    # Two devices, two clocks, and therefore two explicit streams. The probe is
    # continuous and the head is excluded, so a few ms of start skew costs
    # nothing; what would cost everything is the module-level context stopping
    # the playback the moment the recording starts.
    played = resample_linear(probe.astype(np.float64), ARRAY_RATE_HZ, play_rate_hz)
    stereo = np.repeat(played.astype(np.int16).reshape(-1, 1), 2, axis=1)
    with _ProbePlayer(sounddevice, stereo, play_device, rate_hz=play_rate_hz) as player:
        recorder = _StreamRecorder(
            sounddevice, capture_device, rate_hz=ARRAY_RATE_HZ,
            channels=capture_channels, frames_wanted=frames,
        )
        with recorder:
            # THE GUARD. If the playback stopped the instant the capture opened,
            # this leg is a recording of the room and not of an echo — and the
            # ERLE that follows would be a confident zero. Refuse it here rather
            # than report it.
            if not player.active:
                raise ProbeError(
                    "the probe stopped playing the moment capture opened: this leg would "
                    "have recorded the noise floor and called it an echo. That is the "
                    "sounddevice module-level context (play() + rec() share one, and "
                    "start_stream() calls stop() first) — use explicit Stream objects"
                )
            recorder.wait(timeout=seconds + 5.0)
    captured = recorder.samples()
    if captured.shape[0] < frames:
        raise ProbeError(
            f"capture returned {captured.shape[0]} of {frames} frames "
            f"({captured.shape[0] / ARRAY_RATE_HZ:.2f} s of {seconds:.2f} s)"
        )
    return captured[:frames]


# ====================================================================== legs
def run_leg(leg: str, *, seconds: float, exclude_s: float, probe: np.ndarray,
            capture_device: int, play_device: int | None, play_rate_hz: int,
            note: str = "", reference_device: int | None = None,
            reference_rate_hz: int = 48_000) -> dict[str, Any]:
    """Record one leg and reduce it to levels. The raw audio is not kept."""

    if leg not in LEGS:
        raise ProbeError(f"unknown leg {leg!r}; one of {list(LEGS)}")
    silent = leg == "floor"
    started = time.time()
    reference: dict[str, Any] | None = None
    if reference_device is None:
        capture = play_and_record(
            probe, capture_device=capture_device, play_device=play_device,
            play_rate_hz=play_rate_hz, silent=silent,
        )
    else:
        witness = _StreamRecorder(
            _sounddevice(), reference_device, rate_hz=reference_rate_hz, channels=1
        )
        with witness:
            capture = play_and_record(
                probe, capture_device=capture_device, play_device=play_device,
                play_rate_hz=play_rate_hz, silent=silent,
            )
        heard = witness.samples().astype(np.float64)
        heard = heard.mean(axis=1) if heard.ndim > 1 else heard
        skip = round(float(exclude_s) * reference_rate_hz)
        reference = {
            "device": int(reference_device),
            "rate_hz": int(reference_rate_hz),
            **summarise(heard[skip:] if heard.size > skip else heard, rate_hz=reference_rate_hz),
        }
    window = analysis_window(capture, exclude_s=exclude_s)
    channels = {
        f"ch{index}": {
            "beam": CAPTURE_BEAMS[index] if index < len(CAPTURE_BEAMS) else "raw",
            **summarise(window[:, index]),
        }
        for index in range(window.shape[1])
    }
    return {
        "schema": SCHEMA,
        "leg": leg,
        "note": note,
        "started_unix": round(started, 3),
        "seconds_recorded": round(capture.shape[0] / ARRAY_RATE_HZ, 3),
        "seconds_excluded": round(float(exclude_s), 3),
        "seconds_analysed": round(window.shape[0] / ARRAY_RATE_HZ, 3),
        "probe_played": not silent,
        "probe_peak_dbfs": round(dbfs(float(np.max(np.abs(probe)))), 3),
        "probe_rms_dbfs": round(
            dbfs(float(np.sqrt(np.mean(np.square(probe.astype(np.float64)))))), 3
        ),
        "capture_device": capture_device,
        "play_device": play_device,
        "play_rate_hz": play_rate_hz,
        "default_sink_volume": default_sink_volume(),
        "alsa_gain": array_gain_state(),
        "asr_channel": ASR_CHANNEL_INDEX,
        "channels": channels,
        "reference_mic": reference,
    }


# ============================================ the same-instant measurement
def run_mux_leg(*, seconds: float, exclude_s: float, probe: np.ndarray,
                capture_device: int, play_device: int,
                note: str = "") -> dict[str, Any]:
    """The textbook measurement, on one recording, with no second loudspeaker.

    Re-points the array's two USB capture channels at the signal entering the
    canceller (amplified mic 0) and the processed beam leaving it, plays the
    probe through the array's OWN amplifier — the only path its canceller
    references — and records both at once. Same instant, same acoustic event,
    same gain: nothing to level-match, and the whole three-leg apparatus becomes
    unnecessary.

    THE ROUTING IS PUT BACK. ``mux_session`` restores the previous mux in a
    ``finally`` and verifies the read-back, because a capture stream left
    pointing at a raw microphone would break the owner's voice stack silently.
    Nothing is written to flash, so a power cycle also restores it.

    NEVER RUN AGAINST HARDWARE. The udev rule is an owner action and every
    control transfer on this host is ``Errno 13`` until it lands.
    """

    control = XvfControl(allow_writes=True)
    started = time.time()
    with control.mux_session(MUX_PAIR_PIPELINE) as session:
        capture = play_and_record(
            probe, capture_device=capture_device, play_device=play_device,
            play_rate_hz=ARRAY_RATE_HZ, silent=False,
        )
    window = analysis_window(capture, exclude_s=exclude_s)
    labels = {
        0: "amplified_mic_0 (into the canceller)",
        1: "processed_beam (out of the canceller)",
    }
    channels = {
        f"ch{index}": {"beam": labels.get(index, "unknown"), **summarise(window[:, index])}
        for index in range(window.shape[1])
    }
    return {
        "schema": SCHEMA,
        "leg": "same_instant",
        "method": "same_instant_mux",
        "note": note,
        "started_unix": round(started, 3),
        "seconds_recorded": round(capture.shape[0] / ARRAY_RATE_HZ, 3),
        "seconds_excluded": round(float(exclude_s), 3),
        "seconds_analysed": round(window.shape[0] / ARRAY_RATE_HZ, 3),
        "mux_previous": session["previous"],
        "mux_applied": session["applied"],
        "default_sink_volume": default_sink_volume(),
        "alsa_gain": array_gain_state(),
        "channels": channels,
    }


def build_mux_report(leg: Mapping[str, Any], *, gate_db: float = ERLE_GATE_DB) -> dict[str, Any]:
    """One same-instant recording to the same report shape the scorecard reads."""

    into = float(leg["channels"]["ch0"]["rms_dbfs"])
    out = float(leg["channels"]["ch1"]["rms_dbfs"])
    attenuation = round(into - out, 2)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "method": "same_instant_mux",
        "gate_db": gate_db,
        "measures": MEASURED_QUANTITY_MUX,
        # Same instant, same recording, same gain: there is no level match to
        # fail and no floor to be limited by, so both are trivially satisfied
        # rather than absent.
        "level_match_ok": True,
        "probe_reached_mic": bool(into > out - 1.0),
        "floor_limited": False,
        "legs": {"into_canceller_dbfs": round(into, 2), "out_of_canceller_dbfs": round(out, 2)},
        "asr_beam_echo_attenuation_db": attenuation,
        "erle_db": attenuation,
        "residual_dbfs": round(out, 2),
        "mux_previous": leg.get("mux_previous"),
        "mux_applied": leg.get("mux_applied"),
        "verdict": "unmeasured",
        "problems": [],
    }
    if attenuation >= gate_db:
        report["verdict"] = "pass"
    else:
        report["verdict"] = "fail"
        report["problems"].append(
            f"{attenuation} dB is below the {gate_db} dB gate. On this path the level match "
            "cannot be the cause, so look at the amplifier's drive level, PP_ECHOONOFF, and "
            "whether a second canceller (Chrome's AEC3) is in the loop"
        )
    return report


# ==================================================================== report
def _asr_level(leg: dict[str, Any]) -> float:
    channel = leg["channels"][f"ch{leg.get('asr_channel', ASR_CHANNEL_INDEX)}"]
    return float(channel["rms_dbfs"])


def build_report(legs: Sequence[dict[str, Any]], *, gate_db: float = ERLE_GATE_DB,
                 floor_margin_db: float = FLOOR_MARGIN_DB,
                 reference_tolerance_db: float = REFERENCE_TOLERANCE_DB) -> dict[str, Any]:
    """Turn the legs into the attenuation row, or into the reason there isn't one.

    WHAT THIS NUMBER IS CALLED, AND WHY IT IS NOT CALLED ERLE
    ---------------------------------------------------------
    Textbook ERLE compares the echo at the *microphone input* with the echo at
    the canceller's *output* — two taps on the same signal path, same instant,
    with only the adaptive filter between them. This measurement cannot do that:
    the XVF3800's 2-channel firmware publishes two post-processing beams and no
    raw microphone, so the numerator has to come from a second recording made
    with a loudspeaker the canceller could not reference.

    What the subtraction therefore measures is everything the chip does to an
    echo between the microphone and the USB endpoint — the linear AEC, the
    residual suppressor, the beamformer's spatial rejection, and any gain
    riding on the capture path. That is the number a barge-in detector actually
    lives with, and it is the right number for the gate; it is simply not ERLE,
    and calling it ERLE would have overstated what part of the chip was tested.
    So the field is ``asr_beam_echo_attenuation_db``. ``erle_db`` remains as an
    alias with the same value, because the card, the plan and
    ``ACOUSTIC_BRINGUP_PLAN.md`` §5.3 all say "ERLE ≥ 20 dB" and a reader
    looking for that key should find it rather than conclude the row is missing.
    """

    by_leg = {leg["leg"]: leg for leg in legs}
    missing = [name for name in ("uncancelled", "cancelled") if name not in by_leg]
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "gate_db": gate_db,
        "measures": MEASURED_QUANTITY,
        "level_match_ok": None,
        "probe_reached_mic": None,
        "legs": {name: _asr_level(leg) for name, leg in sorted(by_leg.items())},
        "volumes": {name: leg.get("default_sink_volume") for name, leg in sorted(by_leg.items())},
        "asr_beam_echo_attenuation_db": None,
        # Alias, same value. See the docstring: the card's row is spelled ERLE.
        "erle_db": None,
        "floor_limited": None,
        "verdict": "unmeasured",
        "problems": [],
    }
    if missing:
        report["problems"].append(
            f"no echo-attenuation figure without the {' and '.join(missing)} leg(s)"
        )
        return report

    uncancelled = _asr_level(by_leg["uncancelled"])
    cancelled = _asr_level(by_leg["cancelled"])
    attenuation = round(uncancelled - cancelled, 2)
    report["asr_beam_echo_attenuation_db"] = attenuation
    report["erle_db"] = attenuation
    report["residual_dbfs"] = round(cancelled, 2)

    # Double talk is diagnostic in every outcome, so it is computed before any
    # of the refusals below can return early.
    doubletalk = by_leg.get("doubletalk")
    if doubletalk is not None:
        channel = doubletalk["channels"][f"ch{ASR_CHANNEL_INDEX}"]
        owner_level = float(channel["frame_p90_dbfs"])
        report["doubletalk"] = {
            "owner_p90_dbfs": round(owner_level, 2),
            "residual_dbfs": round(cancelled, 2),
            # Signal-to-echo ratio: how far the owner's voice stands above what
            # survived. This, not the attenuation figure, is what a VAD sees.
            "signal_to_echo_db": round(owner_level - cancelled, 2),
        }

    floor = by_leg.get("floor")
    if floor is None:
        report["problems"].append(
            "no floor leg: cannot tell a canceller that cancelled from a room that was quiet"
        )
    else:
        floor_level = _asr_level(floor)
        report["floor_dbfs"] = round(floor_level, 2)
        report["residual_over_floor_db"] = round(cancelled - floor_level, 2)
        report["uncancelled_over_floor_db"] = round(uncancelled - floor_level, 2)
        report["floor_limited"] = bool(cancelled - floor_level < floor_margin_db)

        # THE NUMERATOR HAS TO BE AN ECHO. If the uncancelled leg is sitting on
        # the noise floor, the probe never reached the microphone — the wrong
        # play device, a muted second speaker, or the sounddevice play()+rec()
        # trap this tool now refuses at the source. Subtracting it would produce
        # an attenuation of roughly zero and a confident `fail` naming a clipped
        # amplifier that was never involved. Refuse instead.
        if uncancelled - floor_level < floor_margin_db:
            report["probe_reached_mic"] = False
            report["problems"].append(
                f"the uncancelled leg is only {uncancelled - floor_level:.1f} dB over the "
                f"noise floor (< {floor_margin_db} dB): the probe did not reach the "
                "microphone, so there is no echo to cancel and nothing to measure. Check "
                "--play-device, that the second speaker is actually playing, and that its "
                "level was matched before this leg was recorded."
            )
            report["verdict"] = "unmeasured"
            return report
        report["probe_reached_mic"] = True

        if report["floor_limited"]:
            report["problems"].append(
                f"the residual is {cancelled - floor_level:.1f} dB over the noise floor "
                f"(< {floor_margin_db} dB): the figure is a LOWER BOUND, not a measurement"
            )

    level_match_ok = True
    volumes = {
        name: by_leg[name].get("default_sink_volume") for name in ("uncancelled", "cancelled")
    }
    if volumes["uncancelled"] != volumes["cancelled"]:
        level_match_ok = False
        report["problems"].append(
            f"the default sink volume differed between legs ({volumes}); the two legs are "
            "not the same experiment"
        )

    # The gain between the microphone and the samples must not have moved either.
    gains = {name: by_leg[name].get("alsa_gain") for name in ("uncancelled", "cancelled")}
    if all(isinstance(entry, dict) and entry.get("available") for entry in gains.values()):
        report["alsa_gain_stable"] = gains["uncancelled"].get("controls") == gains[
            "cancelled"
        ].get("controls")
        if not report["alsa_gain_stable"]:
            level_match_ok = False
            report["problems"].append(
                "the array's ALSA capture/playback gain changed between the two legs, so "
                "part of the difference below is a mixer setting and not the room"
            )
    else:
        report["alsa_gain_stable"] = None

    # Were the two legs the same loudness in the room? The witness answers, if
    # there was one; if there was not, the report says the claim rests on the
    # owner's SPL match and not on anything this tool saw.
    witnesses = {
        name: by_leg[name].get("reference_mic") for name in ("uncancelled", "cancelled")
    }
    if all(isinstance(entry, dict) for entry in witnesses.values()):
        levels = {name: float(entry["rms_dbfs"]) for name, entry in witnesses.items()}
        mismatch = levels["uncancelled"] - levels["cancelled"]
        report["reference_mic"] = {**levels, "mismatch_db": round(mismatch, 2)}
        if abs(mismatch) > reference_tolerance_db:
            level_match_ok = False
            report["problems"].append(
                f"the reference microphone heard the two legs {mismatch:+.1f} dB apart "
                f"(tolerance {reference_tolerance_db} dB): the level match failed, so this "
                "subtraction is measuring two loudspeakers and not a canceller"
            )
    else:
        report["reference_mic"] = None
        # NOT a level-match failure: an SPL meter reading is a real match, it is
        # simply one this tool did not witness. The note says which kind of
        # evidence the number rests on; it does not overrule the owner.
        report["problems"].append(
            "no reference microphone in both legs: the level match rests on the SPL "
            "reading you took by hand, which is a claim this tool cannot check"
        )
    report["level_match_ok"] = level_match_ok

    if not level_match_ok:
        # The subtraction happened; it just is not evidence about a canceller.
        # The number stays visible so the failure is diagnosable, and the verdict
        # refuses to launder it into a pass.
        report["verdict"] = "unmeasured"
        return report
    if attenuation >= gate_db:
        report["verdict"] = "pass_lower_bound" if report["floor_limited"] else "pass"
    else:
        report["verdict"] = "fail"
        report["problems"].append(
            f"{attenuation} dB is below the {gate_db} dB gate; the usual mechanisms are a "
            "clipped amplifier, a speaker that is not on the array's own DAC, and a second "
            "AEC (Chrome's AEC3) cancelling against a reference that already moved"
        )
    return report


# ======================================================================== CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--method", choices=("mux", "three-leg"), default="three-leg",
        help="'mux' is the same-instant measurement through the array's output "
             "selector: one recording, no second loudspeaker, no level match. It "
             "needs pyusb and the udev rule. 'three-leg' is the fallback for a host "
             "without the control interface",
    )
    parser.add_argument("--leg", choices=LEGS, help="record one leg (three-leg method)")
    parser.add_argument("--report", nargs="+", type=Path, metavar="LEG.json",
                        help="combine recorded legs into the ERLE row")
    parser.add_argument("--out", type=Path, default=None, help="write the leg/report JSON here")
    parser.add_argument("--seconds", type=float, default=12.0,
                        help="record length; the plan wants 10 s of analysis after --exclude")
    parser.add_argument("--exclude", type=float, default=2.0,
                        help="seconds dropped for AEC convergence (plan: 2.0)")
    parser.add_argument("--probe-wav", type=Path, default=None,
                        help="use a real robot utterance instead of speech-shaped noise")
    parser.add_argument("--probe-peak-dbfs", type=float, default=-6.0,
                        help="digital peak of the generated probe")
    parser.add_argument("--capture-device", type=int, default=None,
                        help="PortAudio index of the array (default: found by name)")
    parser.add_argument("--play-device", type=int, default=None,
                        help="PortAudio index to play through (default: the array itself)")
    parser.add_argument("--play-rate", type=int, default=ARRAY_RATE_HZ,
                        help="sample rate of --play-device (the array is 16000 and only 16000)")
    parser.add_argument("--reference-device", type=int, default=None,
                        help="a SECOND microphone that hears both legs; the witness that "
                             "they were the same loudness (no SPL meter needed)")
    parser.add_argument("--reference-rate", type=int, default=48_000,
                        help="sample rate of --reference-device")
    parser.add_argument("--note", default="", help="what you did differently, in your words")
    parser.add_argument("--write-probe", type=Path, default=None,
                        help="render the probe to a WAV and exit; touches no device")
    return parser


def _write(path: Path | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2) + "\n"
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.write_probe is not None:
        probe = (
            load_probe_wav(args.probe_wav)
            if args.probe_wav
            else speech_shaped_probe(args.seconds, peak_dbfs=args.probe_peak_dbfs)
        )
        args.write_probe.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(args.write_probe), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(ARRAY_RATE_HZ)
            handle.writeframes(probe.tobytes())
        print(f"wrote {args.write_probe} ({probe.size / ARRAY_RATE_HZ:.2f} s at {ARRAY_RATE_HZ} Hz)")
        return 0

    if args.report:
        legs = [json.loads(path.read_text(encoding="utf-8")) for path in args.report]
        report = build_report(legs)
        _write(args.out, report)
        if report["verdict"] == "unmeasured" or report["problems"]:
            for problem in report["problems"]:
                print(f"PROBLEM   {problem}")
        print(
            f"attenuation {report['asr_beam_echo_attenuation_db']} dB "
            f"(ASR beam; reported as erle_db for the card's row)  "
            f"verdict={report['verdict']}"
        )
        return 0 if report["verdict"].startswith("pass") else 1

    if args.method == "mux":
        capture_device = args.capture_device
        if capture_device is None:
            capture_device = find_portaudio_device()
        if capture_device is None:
            raise ProbeError("the array is not in PortAudio's list; run tools/xvf3800_probe.py")
        probe = (
            load_probe_wav(args.probe_wav)
            if args.probe_wav
            else speech_shaped_probe(args.seconds, peak_dbfs=args.probe_peak_dbfs)
        )
        leg = run_mux_leg(
            seconds=args.seconds, exclude_s=args.exclude, probe=probe,
            capture_device=capture_device, play_device=capture_device, note=args.note,
        )
        report = build_mux_report(leg)
        _write(args.out, report)
        for problem in report["problems"]:
            print(f"PROBLEM   {problem}")
        print(
            f"attenuation {report['asr_beam_echo_attenuation_db']} dB "
            f"(same instant)  verdict={report['verdict']}"
        )
        return 0 if report["verdict"].startswith("pass") else 1

    if not args.leg:
        build_parser().print_help()
        return 2

    capture_device = args.capture_device
    if capture_device is None:
        capture_device = find_portaudio_device()
    if capture_device is None:
        raise ProbeError("the array is not in PortAudio's device list; run tools/xvf3800_probe.py")
    play_device = args.play_device if args.play_device is not None else capture_device
    probe = (
        load_probe_wav(args.probe_wav)
        if args.probe_wav
        else speech_shaped_probe(args.seconds, peak_dbfs=args.probe_peak_dbfs)
    )
    leg = run_leg(
        args.leg, seconds=args.seconds, exclude_s=args.exclude, probe=probe,
        capture_device=capture_device,
        play_device=None if args.leg == "floor" else play_device,
        play_rate_hz=args.play_rate, note=args.note,
        reference_device=args.reference_device, reference_rate_hz=args.reference_rate,
    )
    _write(args.out, leg)
    channel = leg["channels"][f"ch{ASR_CHANNEL_INDEX}"]
    print(
        f"{args.leg:<12} ASR beam rms {channel['rms_dbfs']} dBFS  "
        f"p90 {channel['frame_p90_dbfs']} dBFS over {leg['seconds_analysed']} s"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
