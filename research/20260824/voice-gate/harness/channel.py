#!/usr/bin/env python
"""The air this study does not have, written down as an explicit model.

This host has no loudspeaker but the robot's own DAC, so no stimulus can be
presented through air (``corpus.py`` header). Rather than quietly feed clean
files to the gate and call the numbers "through-air", every replay row passes
through THIS module, which states exactly what it is pretending:

* **distance** — free-field spreading only: 1 m is the reference, 3 m is
  −9.5 dB. Nothing here models a real room's direct-to-reverberant ratio.
* **off-axis** — a first-order high-shelf cut above 2 kHz (0°: 0 dB, 30°:
  −1.5 dB, 60°: −4 dB), the shape of a talker turning away from a mic. The
  XVF3800's own beamformer would partly undo this; it is not modeled.
* **room** — a real bed: samples cut from the array's own ambient tape, the one
  genuinely measured thing in the chain.
* **reverb** — three sparse exponentially decaying taps at 3 m. A stand-in for
  a room impulse response, not a measurement of one.
* **replay** — the extra loudspeaker-and-microphone pass a spoofer's phone adds:
  band-limit 200–6500 Hz, mild soft clipping, and a second room bed.

Everything it produces is tier ``replay``. Nothing it produces is evidence about
the robot's acoustics, its speaker, or its AEC.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

RATE_HZ = 16_000

DISTANCE_DB = {1.0: 0.0, 3.0: -9.5}
OFF_AXIS_DB = {0: 0.0, 30: -1.5, 60: -4.0}


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(samples, dtype=np.float64) ** 2)) + 1e-12)


def db(value: float) -> float:
    return 20.0 * float(np.log10(max(value, 1e-12)))


def shelf_above(samples: np.ndarray, *, cut_db: float, corner_hz: float = 2000.0) -> np.ndarray:
    """Attenuate everything above ``corner_hz`` by ``cut_db`` with a smooth knee."""

    if cut_db >= -0.01:
        return samples
    spectrum = np.fft.rfft(samples)
    frequencies = np.fft.rfftfreq(samples.size, 1.0 / RATE_HZ)
    gain = np.ones_like(frequencies)
    knee = frequencies > corner_hz
    ratio = np.clip((frequencies[knee] - corner_hz) / corner_hz, 0.0, 1.0)
    gain[knee] = 10.0 ** ((cut_db * ratio) / 20.0)
    return np.fft.irfft(spectrum * gain, samples.size)


def reverb(samples: np.ndarray, *, taps_ms=(11.0, 23.0, 41.0), decay_db=(-9.0, -14.0, -19.0)):
    out = samples.copy()
    for delay_ms, level_db in zip(taps_ms, decay_db, strict=True):
        shift = int(delay_ms * RATE_HZ / 1000.0)
        gain = 10.0 ** (level_db / 20.0)
        out[shift:] += gain * samples[: samples.size - shift]
    return out


def band_limit(samples: np.ndarray, low_hz: float, high_hz: float) -> np.ndarray:
    spectrum = np.fft.rfft(samples)
    frequencies = np.fft.rfftfreq(samples.size, 1.0 / RATE_HZ)
    spectrum[(frequencies < low_hz) | (frequencies > high_hz)] = 0.0
    return np.fft.irfft(spectrum, samples.size)


@dataclass(frozen=True)
class Geometry:
    distance_m: float = 1.0
    off_axis_deg: int = 0

    @property
    def label(self) -> str:
        return f"{self.distance_m:g}m/{self.off_axis_deg}deg"


class RoomBed:
    """Real recorded room noise, handed out in deterministic slices."""

    def __init__(self, tape: np.ndarray, *, seed: int = 20260824) -> None:
        self.tape = np.asarray(tape, dtype=np.float64)
        self.rng = np.random.default_rng(seed)

    @property
    def floor_dbfs(self) -> float:
        return db(rms(self.tape))

    def slice(self, count: int) -> np.ndarray:
        if self.tape.size <= count:
            repeats = int(np.ceil(count / max(1, self.tape.size)))
            return np.tile(self.tape, repeats)[:count]
        start = int(self.rng.integers(0, self.tape.size - count))
        return self.tape[start : start + count]


ON_AXIS_1M = Geometry()


def present(
    clip: np.ndarray,
    bed: RoomBed,
    *,
    geometry: Geometry | None = None,
    speech_dbfs_at_1m: float = -26.0,
    replay: bool = False,
) -> np.ndarray:
    """One stimulus as the array would (approximately) have heard it.

    ``speech_dbfs_at_1m`` is the calibration handle: it is set from the array's
    own measured room floor so that the 1 m level corresponds to conversational
    speech (see ``calibrate.py``), because this host has no SPL meter.
    """

    geometry = geometry or ON_AXIS_1M
    voiced = clip[np.abs(clip) > 1e-4]
    level = rms(voiced if voiced.size > 32 else clip)
    target = 10.0 ** (speech_dbfs_at_1m / 20.0)
    out = clip * (target / level)
    if replay:
        out = band_limit(out, 200.0, 6500.0)
        out = np.tanh(out * 1.8) / 1.8
        out = out + 0.35 * bed.slice(out.size)
    out = shelf_above(out, cut_db=OFF_AXIS_DB[geometry.off_axis_deg])
    out = out * (10.0 ** (DISTANCE_DB[geometry.distance_m] / 20.0))
    if geometry.distance_m >= 3.0:
        out = reverb(out)
    return out + bed.slice(out.size)


__all__ = [
    "DISTANCE_DB",
    "OFF_AXIS_DB",
    "RATE_HZ",
    "Geometry",
    "RoomBed",
    "band_limit",
    "db",
    "present",
    "rms",
    "shelf_above",
]
