"""Small, engine-independent prosody analysis for speech-synchronised motion.

``ProsodyTap`` runs on synthesized PCM immediately before playback.  It does
not decide *what* the robot should do; it exposes a normalized loudness
envelope and likely acoustic accents so a higher layer can place an already
approved gesture on the playback clock.

The implementation intentionally depends only on NumPy and the Python
standard library.  All sample-domain work is vectorized; the only loop below
operates over the (small) set of accent candidates.
"""

from __future__ import annotations

import io
import math
import wave
from dataclasses import dataclass

import numpy as np

ENVELOPE_HOP_S = 0.010
_PITCH_WINDOW_S = 0.040
_RMS_WINDOW_S = 0.040
_MIN_ACCENT_SPACING_S = 0.120
_MIN_F0_HZ = 70.0
_MAX_F0_HZ = 500.0
_VOICED_PROMINENCE = 0.30
_SHORT_CHUNK_S = 0.200


@dataclass(frozen=True)
class Accent:
    """One likely pitch/onset accent on the chunk-local audio clock."""

    time_s: float
    strength: float


@dataclass(frozen=True)
class BeatTrack:
    """Prosodic timing information for one contiguous audio chunk."""

    duration_s: float
    accents: tuple[Accent, ...]
    envelope_hop_s: float
    rms_envelope: tuple[float, ...]
    arousal: float


def analyze_wav_chunk(wav_bytes: bytes) -> BeatTrack:
    """Analyze a mono, uncompressed, 16-bit PCM WAV byte string.

    The sample rate is deliberately unrestricted.  Invalid containers and
    unsupported encodings raise ``ValueError`` rather than leaking the
    several exception types used by :mod:`wave`.
    """

    if not isinstance(wav_bytes, (bytes, bytearray, memoryview)):
        raise TypeError("WAV input must be bytes-like")
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
            if reader.getnchannels() != 1:
                raise ValueError("WAV input must be mono")
            if reader.getsampwidth() != 2:
                raise ValueError("WAV input must contain 16-bit PCM")
            if reader.getcomptype() != "NONE":
                raise ValueError("WAV input must be uncompressed PCM")
            sample_rate_hz = reader.getframerate()
            frame_count = reader.getnframes()
            pcm = reader.readframes(frame_count)
            if len(pcm) != frame_count * 2:
                raise ValueError("malformed WAV input: truncated PCM payload")
    except ValueError:
        raise
    except (EOFError, OSError, wave.Error) as exc:
        raise ValueError("malformed WAV input") from exc

    return analyze_pcm16(pcm, sample_rate_hz)


def analyze_pcm16(pcm: bytes, sample_rate_hz: int) -> BeatTrack:
    """Analyze little-endian, mono PCM16 sampled at ``sample_rate_hz``."""

    if isinstance(sample_rate_hz, bool) or not isinstance(sample_rate_hz, int):
        raise TypeError("sample rate must be a positive integer")
    if sample_rate_hz <= 0:
        raise ValueError("sample rate must be a positive integer")
    if not isinstance(pcm, (bytes, bytearray, memoryview)):
        raise TypeError("PCM input must be bytes-like")
    if len(pcm) % 2:
        raise ValueError("PCM16 input must contain complete 16-bit samples")

    sample_count = len(pcm) // 2
    duration_s = sample_count / sample_rate_hz
    if sample_count == 0:
        return _empty_track(duration_s)

    # Convert once.  Float32 is ample for 16-bit input and materially faster
    # than float64 on the small CPUs targeted by Parcel.
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    samples *= 1.0 / 32768.0

    frame_ends = _envelope_frame_ends(sample_count, sample_rate_hz)
    rms = _rms_frames(
        samples,
        frame_ends,
        max(1, round(sample_rate_hz * _RMS_WINDOW_S)),
    )
    rms = _smooth_envelope(rms)
    peak_rms = float(np.max(rms, initial=0.0))
    if peak_rms <= 0.0:
        return BeatTrack(
            duration_s=duration_s,
            accents=(),
            envelope_hop_s=ENVELOPE_HOP_S,
            rms_envelope=tuple(0.0 for _ in range(rms.size)),
            arousal=0.0,
        )

    normalized_rms = np.clip(rms / peak_rms, 0.0, 1.0)
    envelope = tuple(float(value) for value in normalized_rms)

    # Short fragments cannot support stable pitch/rate estimates.  Preserve
    # their useful loudness signal but never invent an accent.
    mean_rms = float(np.mean(rms))
    rms_arousal = _normalized_rms_arousal(mean_rms)
    if duration_s < _SHORT_CHUNK_S:
        return BeatTrack(
            duration_s=duration_s,
            accents=(),
            envelope_hop_s=ENVELOPE_HOP_S,
            rms_envelope=envelope,
            arousal=rms_arousal,
        )

    onset = np.empty_like(rms)
    onset[0] = rms[0]
    np.subtract(rms[1:], rms[:-1], out=onset[1:])
    np.maximum(onset, 0.0, out=onset)
    onset_max = float(np.max(onset, initial=0.0))

    candidate_indices = _local_maxima(onset)
    # A long RMS window removes most carrier-phase scalloping; this final
    # relative floor rejects the sub-percent residue without suppressing
    # actual syllable/click onsets.
    onset_floor = max(peak_rms * 0.02, 2.0 / 32768.0)
    candidate_indices = candidate_indices[onset[candidate_indices] >= onset_floor]
    if onset_max <= np.finfo(np.float32).eps or candidate_indices.size == 0:
        accents: tuple[Accent, ...] = ()
        voiced_f0 = np.empty(0, dtype=np.float32)
    else:
        f0_hz, prominence = _candidate_pitch(
            samples,
            sample_rate_hz,
            frame_ends[candidate_indices],
        )
        voiced = prominence >= _VOICED_PROMINENCE
        voiced_f0 = f0_hz[voiced]
        median_f0 = float(np.median(voiced_f0)) if voiced_f0.size else math.inf
        top_quartile = float(np.quantile(onset[candidate_indices], 0.75))
        # Numerically equal clicks can differ by a few ULPs after cumulative
        # RMS calculation.  Treat those ties as ties instead of discarding an
        # arbitrary subset at the quartile boundary.
        strong_onset = onset[candidate_indices] >= top_quartile - onset_max * 1e-6
        accepted = (
            (voiced & (f0_hz > median_f0))
            | strong_onset
        )
        accepted_indices = candidate_indices[accepted]
        strengths = onset[accepted_indices] / onset_max
        accents = _space_accents(
            accepted_indices,
            strengths,
            duration_s,
        )

    accent_rate = len(accents) / max(duration_s, ENVELOPE_HOP_S)
    rate_arousal = min(1.0, accent_rate / 4.0)
    pitch_arousal = _pitch_range_arousal(voiced_f0)
    arousal = float(
        np.clip(0.5 * rms_arousal + 0.3 * rate_arousal + 0.2 * pitch_arousal, 0.0, 1.0)
    )
    return BeatTrack(
        duration_s=duration_s,
        accents=accents,
        envelope_hop_s=ENVELOPE_HOP_S,
        rms_envelope=envelope,
        arousal=arousal,
    )


def _empty_track(duration_s: float) -> BeatTrack:
    return BeatTrack(
        duration_s=duration_s,
        accents=(),
        envelope_hop_s=ENVELOPE_HOP_S,
        rms_envelope=(),
        arousal=0.0,
    )


def _envelope_frame_ends(sample_count: int, sample_rate_hz: int) -> np.ndarray:
    """Sample boundaries on an exact 10 ms public clock.

    Using ``round(sample_rate * .01)`` as a fixed hop drifts at rates such as
    22.05 kHz.  Rounding each absolute boundary independently distributes the
    fractional samples while keeping frame ``i`` anchored to ``(i + 1)*10ms``.
    """

    frame_count = (sample_count * 100 + sample_rate_hz - 1) // sample_rate_hz
    frame_numbers = np.arange(1, frame_count + 1, dtype=np.int64)
    ends = (frame_numbers * sample_rate_hz + 99) // 100
    return np.minimum(ends, sample_count)


def _rms_frames(
    samples: np.ndarray,
    ends: np.ndarray,
    window_samples: int,
) -> np.ndarray:
    """Return causal 40 ms RMS windows evaluated every exact 10 ms."""

    starts = np.maximum(0, ends - window_samples)
    squared = samples * samples
    cumulative = np.empty(samples.size + 1, dtype=np.float64)
    cumulative[0] = 0.0
    np.cumsum(squared, dtype=np.float64, out=cumulative[1:])
    powers = (cumulative[ends] - cumulative[starts]) / (ends - starts)
    return np.sqrt(np.maximum(powers, 0.0)).astype(np.float32, copy=False)


def _smooth_envelope(rms: np.ndarray) -> np.ndarray:
    """Suppress hop/carrier beating with a centered 30 ms moving average."""

    if rms.size < 3:
        return rms
    padded = np.pad(rms, (1, 1), mode="edge")
    return np.convolve(padded, np.full(3, 1.0 / 3.0, dtype=np.float32), mode="valid")


def _local_maxima(signal: np.ndarray) -> np.ndarray:
    """Indices of positive local maxima, retaining one edge candidate."""

    if signal.size == 0:
        return np.empty(0, dtype=np.int64)
    if signal.size == 1:
        return np.array([0], dtype=np.int64) if signal[0] > 0.0 else np.empty(0, dtype=np.int64)

    middle = np.flatnonzero(
        (signal[1:-1] > 0.0)
        & (signal[1:-1] >= signal[:-2])
        & (signal[1:-1] > signal[2:])
    ) + 1
    first = np.array([0], dtype=np.int64) if signal[0] > signal[1] else np.empty(0, dtype=np.int64)
    last = (
        np.array([signal.size - 1], dtype=np.int64)
        if signal[-1] > 0.0 and signal[-1] >= signal[-2]
        else np.empty(0, dtype=np.int64)
    )
    return np.concatenate((first, middle, last))


def _candidate_pitch(
    samples: np.ndarray,
    sample_rate_hz: int,
    centers: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized autocorrelation F0/prominence around accent candidates."""

    window_samples = max(8, round(sample_rate_hz * _PITCH_WINDOW_S))
    half_window = window_samples // 2
    offsets = np.arange(window_samples, dtype=np.int64)
    sample_indices = centers[:, None] - half_window + offsets[None, :]
    valid = (sample_indices >= 0) & (sample_indices < samples.size)
    clipped = np.clip(sample_indices, 0, samples.size - 1)
    windows = samples[clipped] * valid
    valid_counts = np.maximum(np.sum(valid, axis=1, keepdims=True), 1)
    window_means = np.sum(windows, axis=1, keepdims=True) / valid_counts
    windows = (windows - window_means) * valid
    windows *= np.hanning(window_samples).astype(np.float32)

    fft_size = 1 << (2 * window_samples - 1).bit_length()
    spectrum = np.fft.rfft(windows, n=fft_size, axis=1)
    autocorrelation = np.fft.irfft(spectrum * spectrum.conj(), n=fft_size, axis=1)[
        :, :window_samples
    ]
    zero_lag = autocorrelation[:, :1]
    # Compensate for fewer overlapping samples at larger lags.  This makes a
    # true periodic peak comparable with the deceptively high first few lags.
    overlap = 1.0 - np.arange(window_samples, dtype=np.float32) / window_samples
    normalized = np.divide(
        autocorrelation,
        zero_lag * overlap[None, :],
        out=np.zeros_like(autocorrelation),
        where=zero_lag > 1e-10,
    )

    min_lag = max(1, math.floor(sample_rate_hz / _MAX_F0_HZ))
    max_lag = min(window_samples - 2, math.ceil(sample_rate_hz / _MIN_F0_HZ))
    if max_lag < min_lag:
        return (
            np.zeros(centers.size, dtype=np.float32),
            np.zeros(centers.size, dtype=np.float32),
        )

    band = normalized[:, min_lag : max_lag + 1]
    # Compare against neighbors *outside* the search band too.  Otherwise the
    # zero-lag shoulder is mistaken for a 500 Hz peak at the left boundary.
    left = normalized[:, min_lag - 1 : max_lag]
    right = normalized[:, min_lag + 1 : max_lag + 2]
    local_peak = (band >= left) & (band > right)
    ranked = np.where(local_peak, band, -np.inf)
    # The first prominent periodic peak is the fundamental period for a clean
    # signal; choosing the global maximum can select its 2x/3x multiple and
    # report an octave or more too low.
    prominent = local_peak & (band >= _VOICED_PROMINENCE)
    has_prominent = np.any(prominent, axis=1)
    first_prominent = np.argmax(prominent, axis=1)
    strongest_peak = np.argmax(ranked, axis=1)
    best_offset = np.where(has_prominent, first_prominent, strongest_peak)
    best_value = ranked[np.arange(ranked.shape[0]), best_offset]
    no_peak = ~np.isfinite(best_value)
    if np.any(no_peak):
        fallback = np.argmax(band[no_peak], axis=1)
        best_offset[no_peak] = fallback
        best_value[no_peak] = band[no_peak, fallback]
    best_lag = best_offset + min_lag
    f0_hz = sample_rate_hz / best_lag
    prominence = np.clip(best_value, 0.0, 1.0)
    return f0_hz.astype(np.float32), prominence.astype(np.float32)


def _space_accents(
    frame_indices: np.ndarray,
    strengths: np.ndarray,
    duration_s: float,
) -> tuple[Accent, ...]:
    """Non-maximum suppression with the stronger accent always winning."""

    times = np.minimum(frame_indices.astype(np.float64) * ENVELOPE_HOP_S, duration_s)
    selected: list[int] = []
    # Stable ordering makes equal-strength synthetic click trains deterministic.
    for index in np.argsort(-strengths, kind="stable"):
        if all(abs(times[index] - times[kept]) >= _MIN_ACCENT_SPACING_S for kept in selected):
            selected.append(int(index))
    selected.sort(key=times.__getitem__)
    return tuple(
        Accent(
            time_s=float(times[index]),
            strength=float(np.clip(strengths[index], np.finfo(np.float32).eps, 1.0)),
        )
        for index in selected
    )


def _normalized_rms_arousal(mean_rms: float) -> float:
    # A quarter-scale sine is already energetic speech.  Anchoring to an
    # absolute full-scale reference preserves the loud-vs-quiet distinction
    # that per-chunk envelope normalization intentionally removes.
    return float(np.clip(mean_rms / 0.25, 0.0, 1.0))


def _pitch_range_arousal(f0_hz: np.ndarray) -> float:
    if f0_hz.size < 2:
        return 0.0
    low = float(np.min(f0_hz))
    high = float(np.max(f0_hz))
    if low <= 0.0 or high <= low:
        return 0.0
    # One octave of voiced range saturates the pitch contribution.
    return float(np.clip(math.log2(high / low), 0.0, 1.0))
