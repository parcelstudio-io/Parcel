"""S2: ResumeIntent store + per-channel generation tokens."""

from __future__ import annotations

import threading

from parcel_robot.core.resume import GenerationTokens, ResumeIntent, ResumeStore


def _intent(
    channel: str = "follow",
    *,
    at: float = 10.0,
    valid_for: float = 5.0,
) -> ResumeIntent:
    return ResumeIntent(
        channel=channel,
        payload={"mode": "behind", "distance_m": 1.4},
        suspend_reason="search_started",
        suspended_at_s=at,
        valid_for_s=valid_for,
        requires_fresh_observation=True,
    )


def test_expiry() -> None:
    intent = _intent(at=10.0, valid_for=5.0)
    assert not intent.expired(14.9)
    assert intent.expired(15.0)


def test_replace_on_suspend_and_take_clears() -> None:
    store = ResumeStore()
    store.record(_intent(at=1.0))
    store.record(_intent(at=2.0, valid_for=10.0))
    peeked = store.peek("follow")
    assert peeked is not None
    assert peeked.suspended_at_s == 2.0
    taken = store.take("follow", now_s=3.0)
    assert taken is not None
    assert store.peek("follow") is None
    assert store.take("follow", now_s=3.0) is None


def test_take_drops_expired() -> None:
    store = ResumeStore()
    store.record(_intent(at=0.0, valid_for=1.0))
    assert store.take("follow", now_s=2.0) is None
    assert store.peek("follow") is None


def test_peek_drops_expired() -> None:
    store = ResumeStore()
    store.record(_intent(at=0.0, valid_for=1.0))
    assert store.peek("follow", now_s=0.5) is not None
    assert store.peek("follow", now_s=2.0) is None
    assert store.peek("follow") is None


def test_clear_all_and_snapshot() -> None:
    store = ResumeStore()
    store.record(_intent("follow"))
    store.record(_intent("navigation", at=1.0))
    snap = store.snapshot()
    assert set(snap) == {"follow", "navigation"}
    store.clear()
    assert store.snapshot() == {}


def test_unknown_channel_token_starts_at_zero() -> None:
    tokens = GenerationTokens()
    assert tokens.current("navigation") == 0
    assert tokens.is_current("navigation", 0)


def test_bump_isolation_between_channels_named_regression() -> None:
    """Bumping one channel must not invalidate another's in-flight check."""

    tokens = GenerationTokens()
    nav = tokens.bump("navigation")
    follow = tokens.bump("follow")
    assert tokens.is_current("navigation", nav)
    assert tokens.is_current("follow", follow)
    tokens.bump("navigation")
    assert not tokens.is_current("navigation", nav)
    assert tokens.is_current("follow", follow)


def test_generation_tokens_thread_safety_smoke() -> None:
    tokens = GenerationTokens()

    def worker(channel: str) -> None:
        for _ in range(200):
            tokens.bump(channel)

    threads = [
        threading.Thread(target=worker, args=("navigation",)),
        threading.Thread(target=worker, args=("follow",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert tokens.current("navigation") == 200
    assert tokens.current("follow") == 200
