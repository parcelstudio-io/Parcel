"""D-S3: FillerPool habituation, LRU fallback, seeded determinism."""

from __future__ import annotations

import pytest

from parcel_robot.duplex.fillers import FillerEntry, FillerPool


def test_default_has_at_least_six_owner_voiced_variations() -> None:
    pool = FillerPool.default(rng_seed=1)
    texts = set(pool.texts())
    assert pool.size >= 6
    assert "Hmm, let me think…" in texts
    assert "Just a sec while I check that…" in texts
    assert "Give me a moment…" in texts
    assert "Good question — checking…" in texts


def test_consecutive_picks_never_repeat_within_min_gap() -> None:
    entries = (
        FillerEntry("a", min_gap_s=20.0),
        FillerEntry("b", min_gap_s=20.0),
        FillerEntry("c", min_gap_s=20.0),
    )
    pool = FillerPool(entries, rng_seed=7)
    first = pool.pick(now_s=0.0)
    assert first is not None
    pool.notify_spoken(first, now_s=0.0)
    second = pool.pick(now_s=1.0)
    assert second is not None
    assert second.text != first.text


def test_all_suppressed_falls_back_to_lru_not_none() -> None:
    entries = (
        FillerEntry("only", min_gap_s=100.0),
    )
    pool = FillerPool(entries, rng_seed=0)
    first = pool.pick(now_s=0.0)
    assert first is not None
    pool.notify_spoken(first, now_s=0.0)
    # Still within gap and only one entry — must not return None.
    again = pool.pick(now_s=1.0)
    assert again is not None
    assert again.text == "only"


def test_all_suppressed_multi_entry_picks_least_recent() -> None:
    entries = (
        FillerEntry("a", min_gap_s=50.0),
        FillerEntry("b", min_gap_s=50.0),
    )
    pool = FillerPool(entries, rng_seed=3)
    a = FillerEntry("a", min_gap_s=50.0)
    b = FillerEntry("b", min_gap_s=50.0)
    pool.notify_spoken(a, now_s=0.0)
    pool.notify_spoken(b, now_s=1.0)
    # Both suppressed; least-recently-used is "a".
    picked = pool.pick(now_s=2.0)
    assert picked is not None
    assert picked.text == "a"


def test_seeded_determinism() -> None:
    first = [FillerPool.default(rng_seed=42).pick(now_s=float(i)) for i in range(8)]
    second = [FillerPool.default(rng_seed=42).pick(now_s=float(i)) for i in range(8)]
    assert [entry.text if entry else None for entry in first] == [
        entry.text if entry else None for entry in second
    ]


def test_empty_pool_returns_none() -> None:
    assert FillerPool((), rng_seed=0).pick(now_s=0.0) is None


def test_invalid_entry() -> None:
    with pytest.raises(ValueError):
        FillerEntry("  ")
