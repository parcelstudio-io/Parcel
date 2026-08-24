"""Card A2: pure-DSP ProsodyTap contract and acceptance tests."""

from __future__ import annotations

import io
import time
import wave

import numpy as np
import pytest

from parcel_robot.audio.prosody import Accent, BeatTrack, analyze_pcm16, analyze_wav_chunk

SAMPLE_RATE = 16_000


def _pcm(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0 - 1.0 / 32768.0)
    return np.rint(clipped * 32768.0).astype("<i2").tobytes()


def _wav(samples: np.ndarray, *, sample_rate: int = SAMPLE_RATE) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(_pcm(samples))
    return output.getvalue()


def _am_tone(duration_s: float, *, amplitude: float, modulation_hz: float) -> np.ndarray:
    time_axis = np.arange(round(duration_s * SAMPLE_RATE), dtype=np.float32) / SAMPLE_RATE
    modulation = 0.2 + 0.8 * (0.5 + 0.5 * np.sin(2.0 * np.pi * modulation_hz * time_axis))
    return amplitude * modulation * np.sin(2.0 * np.pi * 200.0 * time_axis)


def test_contract_dataclasses_are_frozen() -> None:
    accent = Accent(time_s=0.1, strength=0.8)
    track = BeatTrack(0.2, (accent,), 0.01, (0.5,), 0.3)
    with pytest.raises(AttributeError):
        accent.strength = 0.1  # type: ignore[misc]
    with pytest.raises(AttributeError):
        track.arousal = 0.9  # type: ignore[misc]


def test_synthetic_click_train_finds_accents_within_15_ms() -> None:
    samples = np.zeros(2 * SAMPLE_RATE, dtype=np.float32)
    expected = (0.25, 0.55, 0.86, 1.25, 1.67)
    click_width = round(0.002 * SAMPLE_RATE)
    for click_s in expected:
        start = round(click_s * SAMPLE_RATE)
        samples[start : start + click_width] = 0.9

    track = analyze_wav_chunk(_wav(samples))

    assert track.envelope_hop_s == 0.010
    assert len(track.accents) == len(expected)
    for accent, expected_s in zip(track.accents, expected, strict=True):
        assert accent.time_s == pytest.approx(expected_s, abs=0.015)
        assert 0.0 < accent.strength <= 1.0


def test_silence_has_zero_arousal_and_no_accents() -> None:
    track = analyze_pcm16(_pcm(np.zeros(SAMPLE_RATE, dtype=np.float32)), SAMPLE_RATE)

    assert track.duration_s == 1.0
    assert track.accents == ()
    assert track.arousal == 0.0
    assert track.rms_envelope
    assert set(track.rms_envelope) == {0.0}


@pytest.mark.parametrize("carrier_hz", [70.0, 80.0, 220.0, 261.6, 500.0])
def test_steady_voiced_tone_does_not_create_repeating_false_accents(
    carrier_hz: float,
) -> None:
    time_axis = np.arange(3 * SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE
    tone = 0.7 * np.sin(2.0 * np.pi * carrier_hz * time_axis)

    track = analyze_pcm16(_pcm(tone), SAMPLE_RATE)

    # The one permitted event is the real onset at the beginning of the chunk.
    assert len(track.accents) <= 1
    if track.accents:
        assert track.accents[0].time_s <= track.envelope_hop_s


def test_loud_fast_am_tone_is_more_aroused_than_quiet_slow_tone() -> None:
    loud_fast = analyze_pcm16(_pcm(_am_tone(2.0, amplitude=0.85, modulation_hz=4.0)), SAMPLE_RATE)
    quiet_slow = analyze_pcm16(_pcm(_am_tone(2.0, amplitude=0.08, modulation_hz=0.8)), SAMPLE_RATE)

    assert loud_fast.arousal > quiet_slow.arousal
    assert len(loud_fast.accents) > len(quiet_slow.accents)
    assert 0.0 <= quiet_slow.arousal < loud_fast.arousal <= 1.0


def test_short_chunk_uses_rms_only_and_never_emits_accents() -> None:
    short = _am_tone(0.150, amplitude=0.5, modulation_hz=5.0)
    track = analyze_pcm16(_pcm(short), SAMPLE_RATE)

    assert track.duration_s == pytest.approx(0.150)
    assert track.accents == ()
    assert 0.0 < track.arousal <= 1.0


@pytest.mark.parametrize(
    "payload",
    [b"", b"not a wave", b"RIFF\x00\x00\x00\x00WAVE"],
)
def test_malformed_wav_raises_value_error(payload: bytes) -> None:
    with pytest.raises(ValueError):
        analyze_wav_chunk(payload)


def test_wav_rejects_non_mono_or_non_pcm16() -> None:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(b"\x00\x00" * 40)
    with pytest.raises(ValueError, match="mono"):
        analyze_wav_chunk(output.getvalue())

    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(1)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(b"\x80" * 40)
    with pytest.raises(ValueError, match="16-bit"):
        analyze_wav_chunk(output.getvalue())


def test_wav_rejects_payload_shorter_than_declared_frame_count() -> None:
    valid = _wav(np.zeros(160, dtype=np.float32))

    # ``wave.readframes`` silently returns a short payload unless the caller
    # checks it against the frame count in the header.
    with pytest.raises(ValueError, match="truncated"):
        analyze_wav_chunk(valid[:-2])


def test_pcm_validation_and_empty_input() -> None:
    with pytest.raises(ValueError, match="sample rate"):
        analyze_pcm16(b"\x00\x00", 0)
    with pytest.raises(ValueError, match="complete"):
        analyze_pcm16(b"\x00", SAMPLE_RATE)

    empty = analyze_pcm16(b"", SAMPLE_RATE)
    assert empty == BeatTrack(0.0, (), 0.010, (), 0.0)


def test_rms_envelope_is_normalized_and_accepts_non_16khz_audio() -> None:
    sample_rate = 22_050
    time_axis = np.arange(sample_rate, dtype=np.float32) / sample_rate
    track = analyze_wav_chunk(_wav(0.4 * np.sin(2.0 * np.pi * 220.0 * time_axis), sample_rate=sample_rate))

    assert track.duration_s == pytest.approx(1.0)
    assert len(track.rms_envelope) == 100
    assert min(track.rms_envelope) >= 0.0
    assert max(track.rms_envelope) == pytest.approx(1.0)


def test_three_second_chunk_stays_inside_three_times_cpu_budget() -> None:
    samples = _am_tone(3.0, amplitude=0.7, modulation_hz=3.0)
    pcm = _pcm(samples)
    analyze_pcm16(pcm, SAMPLE_RATE)  # warm NumPy's FFT machinery and allocator

    start = time.perf_counter()
    analyze_pcm16(pcm, SAMPLE_RATE)
    elapsed_s = time.perf_counter() - start

    assert elapsed_s < 0.015, f"ProsodyTap took {elapsed_s * 1_000:.2f} ms"
