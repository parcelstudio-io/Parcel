"""S4: stimulus bus lifecycle + prosody/name fusion scorers."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from parcel_robot.attention.stimuli import (
    Stimulus,
    StimulusBus,
    StimulusKind,
    name_fusion_score,
    summons_prosody_score,
)

SAMPLE_RATE = 16_000


def _rising_call(duration_s: float = 0.4) -> np.ndarray:
    n = int(duration_s * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    # Linear chirp 180 → 320 Hz with rising amplitude.
    f0 = 180.0 + 140.0 * (t / duration_s)
    phase = 2.0 * np.pi * np.cumsum(f0) / SAMPLE_RATE
    amp = 0.25 + 0.55 * (t / duration_s)
    return (amp * np.sin(phase)).astype(np.float64)


def _monotone(duration_s: float = 0.4, hz: float = 180.0) -> np.ndarray:
    n = int(duration_s * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    return (0.2 * np.sin(2.0 * np.pi * hz * t)).astype(np.float64)


def test_rising_call_scores_higher_than_monotone_and_silence() -> None:
    rising = summons_prosody_score(_rising_call(), SAMPLE_RATE)
    flat = summons_prosody_score(_monotone(), SAMPLE_RATE)
    silence = summons_prosody_score(np.zeros(SAMPLE_RATE // 2), SAMPLE_RATE)
    assert silence == 0.0
    assert rising > flat
    assert rising > 0.45


def test_name_fusion_never_hard_gates() -> None:
    weak = name_fusion_score(0.05, facing_deg=10.0, distance_m=1.5)
    strong = name_fusion_score(0.9, facing_deg=5.0, distance_m=1.5)
    behind = name_fusion_score(0.9, facing_deg=160.0, distance_m=1.5)
    assert 0.0 < weak < strong
    assert behind < strong


def test_revoke_before_commit_removes() -> None:
    bus = StimulusBus()
    unit = bus.add(
        Stimulus(StimulusKind.SPEECH_ONSET, at_s=1.0, confidence=0.8)
    )
    assert bus.revoke(unit) is True
    assert bus.commit(unit) is False
    assert bus.drain(now_s=1.1) == ()


def test_drain_drops_stale_and_returns_fifo() -> None:
    bus = StimulusBus()
    a = bus.add(Stimulus(StimulusKind.SPEECH_ONSET, at_s=0.0, confidence=0.5))
    b = bus.add(Stimulus(StimulusKind.NAME_HIT, at_s=1.5, confidence=0.7))
    assert bus.commit(a)
    assert bus.commit(b)
    drained = bus.drain(now_s=2.0, max_age_s=1.0)
    assert len(drained) == 1
    assert drained[0].kind is StimulusKind.NAME_HIT
    assert drained[0].unit_id == b


def test_thread_safety_smoke() -> None:
    bus = StimulusBus()

    def writer() -> None:
        for i in range(50):
            unit = bus.add(Stimulus(StimulusKind.AFFECT, at_s=float(i), confidence=0.5))
            if i % 2 == 0:
                bus.commit(unit)
            else:
                bus.revoke(unit)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    bus.drain(now_s=100.0)


def test_confidence_bounds() -> None:
    with pytest.raises(ValueError):
        Stimulus(StimulusKind.KEYWORD, at_s=0.0, confidence=1.5)
