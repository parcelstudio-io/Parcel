"""PG-1 item 4 — the contention guard, the safety-relevant half of the card.

The measured finding these pin: with a model GENERATING on the same GPU, detector
p95 goes 56.0 -> 150.4 ms (n=30, 1280x720), which is 50.1% of the 300 ms
detection freshness TTL, and the source-downscale trick that buys 2.75x on a
quiet GPU collapses to 1.20x under contention. So the scheduling has to be
explicit: a long-running generation may not START while a safety-relevant
inference holds a lease.

Every cell is deterministic — the guard takes an injected clock, so lease expiry
is exercised without sleeping.
"""

from __future__ import annotations

import logging
import threading

import pytest

from parcel_robot.perception.contention import (
    BENCH_INPROCESS_P95_IDLE_MS,
    BENCH_INPROCESS_P95_VLM_GENERATING_MS,
    DETECTION_TTL_MS,
    MEASURED_P95_IDLE_MS,
    MEASURED_P95_VLM_GENERATING_MS,
    ContentionPolicy,
    ContentionPolicyError,
    PerceptionContentionGuard,
    default_guard,
    set_default_guard,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def guard(clock: FakeClock) -> PerceptionContentionGuard:
    return PerceptionContentionGuard(clock=clock)


# ---------------------------------------------------------------------------
# SEED TARGET: "contention guard removed"
# ---------------------------------------------------------------------------


def test_a_generation_is_refused_while_a_safety_lease_is_held(
    guard: PerceptionContentionGuard,
) -> None:
    """The single rule the card asks for, stated as a test."""

    assert guard.try_admit_generation(estimated_ms=800.0).admitted is True

    with guard.mission_lease("person query in flight"):
        verdict = guard.try_admit_generation(estimated_ms=800.0, kind="scene description")
        assert verdict.admitted is False
        assert bool(verdict) is False
        assert "person query in flight" in verdict.blocking_leases
        assert "scene description" in verdict.reason

    # released -> admitted again; the guard delays speech, it does not ban it
    assert guard.try_admit_generation(estimated_ms=800.0).admitted is True


def test_the_refusal_cites_the_measurement_that_justifies_it(
    guard: PerceptionContentionGuard,
) -> None:
    """A refusal a human cannot audit is a refusal that gets deleted."""

    with guard.mission_lease("person"):
        reason = guard.try_admit_generation(estimated_ms=500.0).reason
    assert f"{MEASURED_P95_IDLE_MS:.0f}" in reason
    assert f"{MEASURED_P95_VLM_GENERATING_MS:.0f}" in reason
    assert f"{DETECTION_TTL_MS:.0f}" in reason


def test_the_measured_contention_constants_are_the_shipping_path_numbers() -> None:
    """The guard is sized against onnxruntime + a SEPARATE-PROCESS generator.

    That is how Parcel deploys (``llama-server`` is its own binary), so those are
    the numbers the refusal cites. The bench's in-process torch figures are kept
    beside them for provenance, not used for sizing.
    """

    assert MEASURED_P95_IDLE_MS == 85.5
    assert MEASURED_P95_VLM_GENERATING_MS == 131.8
    assert DETECTION_TTL_MS == 300.0
    # contention is real on the shipping path...
    assert MEASURED_P95_VLM_GENERATING_MS > MEASURED_P95_IDLE_MS * 1.5
    # ...and it pushes one inference from under a third to over 40% of the TTL
    assert MEASURED_P95_IDLE_MS / DETECTION_TTL_MS < 0.30
    assert MEASURED_P95_VLM_GENERATING_MS / DETECTION_TTL_MS > 0.40
    # the inherited in-process numbers are recorded but NOT reused for sizing
    assert BENCH_INPROCESS_P95_IDLE_MS == 56.0
    assert BENCH_INPROCESS_P95_VLM_GENERATING_MS == 150.4
    assert BENCH_INPROCESS_P95_IDLE_MS != MEASURED_P95_IDLE_MS


def test_the_detection_ttl_constant_tracks_the_contract_it_is_sized_against() -> None:
    """This module hard-codes 300 ms to stay dependency-free on the safety path.

    If the contract moves and this constant does not, the guard is sized against a
    budget that no longer exists — so the two are pinned together here.
    """

    from parcel_robot.contracts.freshness import DEFAULT_DETECTION_TTL_NS

    assert DETECTION_TTL_MS == DEFAULT_DETECTION_TTL_NS / 1e6


# ---------------------------------------------------------------------------
# fail-closed behaviour
# ---------------------------------------------------------------------------


def test_an_undeclared_generation_duration_is_refused(guard: PerceptionContentionGuard) -> None:
    """Unknown length is treated as unbounded, not as short."""

    with guard.mission_lease("person"):
        verdict = guard.try_admit_generation(estimated_ms=None)
    assert verdict.admitted is False
    assert "undeclared" in verdict.reason
    assert "fail-closed" in verdict.reason


@pytest.mark.parametrize("bad", [float("nan"), -1.0])
def test_a_nonsensical_duration_is_refused(guard: PerceptionContentionGuard, bad: float) -> None:
    with guard.mission_lease("person"):
        assert guard.try_admit_generation(estimated_ms=bad).admitted is False


def test_the_default_budget_admits_no_generation_at_all_while_active(
    guard: PerceptionContentionGuard,
) -> None:
    """Default is 0 ms: the bench found no measured "short enough to be free" generation."""

    assert guard.policy.max_generation_ms_while_active == 0.0
    with guard.mission_lease("person"):
        assert guard.try_admit_generation(estimated_ms=0.001).admitted is False
        # exactly-at-budget is admitted, which is what makes 0.0 mean "nothing real"
        assert guard.try_admit_generation(estimated_ms=0.0).admitted is True


def test_a_loosened_budget_admits_only_within_it(clock: FakeClock) -> None:
    g = PerceptionContentionGuard(ContentionPolicy(max_generation_ms_while_active=20.0), clock=clock)
    with g.mission_lease("person"):
        assert g.try_admit_generation(estimated_ms=19.9).admitted is True
        assert g.try_admit_generation(estimated_ms=20.1).admitted is False


# ---------------------------------------------------------------------------
# SEED TARGET: a policy that disables the guard by construction
# ---------------------------------------------------------------------------


def test_an_infinite_budget_is_rejected_at_construction() -> None:
    """An inf budget admits everything while still LOOKING installed.

    That is the failure a deferred audit cannot catch by reading call sites, so it
    is refused where it is written instead.
    """

    with pytest.raises(ContentionPolicyError, match="finite"):
        ContentionPolicy(max_generation_ms_while_active=float("inf"))
    with pytest.raises(ContentionPolicyError):
        ContentionPolicy(max_generation_ms_while_active=float("nan"))
    with pytest.raises(ContentionPolicyError):
        ContentionPolicy(max_generation_ms_while_active=-1.0)


def test_a_budget_beyond_the_freshness_ttl_is_rejected() -> None:
    """Admitting a generation longer than the TTL guarantees a stale detection."""

    with pytest.raises(ContentionPolicyError, match="freshness"):
        ContentionPolicy(max_generation_ms_while_active=DETECTION_TTL_MS)
    with pytest.raises(ContentionPolicyError, match="freshness"):
        ContentionPolicy(max_generation_ms_while_active=DETECTION_TTL_MS + 1.0)


def test_a_never_expiring_lease_is_rejected() -> None:
    with pytest.raises(ContentionPolicyError, match="finite"):
        ContentionPolicy(lease_ttl_s=float("inf"))
    with pytest.raises(ContentionPolicyError):
        ContentionPolicy(lease_ttl_s=0.0)


# ---------------------------------------------------------------------------
# leases: expiry, renewal, reentrancy, threads
# ---------------------------------------------------------------------------


def test_a_lease_expires_so_a_crashed_mission_cannot_starve_speech(
    guard: PerceptionContentionGuard, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    lease = guard.acquire_lease("mission leg that will never release")
    assert guard.try_admit_generation(estimated_ms=500.0).admitted is False

    clock.advance(guard.policy.lease_ttl_s + 0.01)
    with caplog.at_level(logging.WARNING, logger="parcel_robot.perception.contention"):
        verdict = guard.try_admit_generation(estimated_ms=500.0)

    assert verdict.admitted is True, "an abandoned lease must not block speech forever"
    assert guard.active_leases() == ()
    assert any("expired" in r.getMessage() for r in caplog.records), "expiry must be loud"
    assert guard.stats()["expired_leases"] == 1
    guard.release_lease(lease)  # releasing an already-reaped lease is a no-op


def test_renewal_pushes_expiry_out(guard: PerceptionContentionGuard, clock: FakeClock) -> None:
    lease = guard.acquire_lease("long mission leg")
    clock.advance(guard.policy.lease_ttl_s * 0.9)
    lease = guard.renew_lease(lease)
    clock.advance(guard.policy.lease_ttl_s * 0.9)
    assert guard.try_admit_generation(estimated_ms=500.0).admitted is False
    assert len(guard.active_leases()) == 1


def test_renewing_a_released_lease_raises(guard: PerceptionContentionGuard) -> None:
    lease = guard.acquire_lease("x")
    guard.release_lease(lease)
    with pytest.raises(KeyError):
        guard.renew_lease(lease)


def test_leases_are_reentrant_and_all_must_clear(guard: PerceptionContentionGuard) -> None:
    with guard.mission_lease("outer person query"):
        with guard.mission_lease("inner person query"):
            verdict = guard.try_admit_generation(estimated_ms=500.0)
            assert verdict.admitted is False
            assert len(verdict.blocking_leases) == 2
        # inner released, outer still holds
        assert guard.try_admit_generation(estimated_ms=500.0).admitted is False
    assert guard.try_admit_generation(estimated_ms=500.0).admitted is True


def test_a_lease_is_released_even_when_the_body_raises(
    guard: PerceptionContentionGuard,
) -> None:
    with pytest.raises(RuntimeError), guard.mission_lease("person"):
        raise RuntimeError("inference blew up")
    assert guard.active_leases() == ()
    assert guard.try_admit_generation(estimated_ms=500.0).admitted is True


def test_retry_after_tells_the_caller_when_to_come_back(
    guard: PerceptionContentionGuard, clock: FakeClock
) -> None:
    with guard.mission_lease("person", ttl_s=1.5):
        verdict = guard.try_admit_generation(estimated_ms=500.0)
        assert verdict.retry_after_s == pytest.approx(1.5)
        clock.advance(0.5)
        assert guard.try_admit_generation(estimated_ms=500.0).retry_after_s == pytest.approx(1.0)


def test_concurrent_leases_and_admissions_are_consistent() -> None:
    """The detector runs on a worker thread; the generator asks from another."""

    g = PerceptionContentionGuard()
    started = threading.Barrier(2)
    verdicts: list[bool] = []
    holding = threading.Event()
    done = threading.Event()

    def holder() -> None:
        started.wait()
        with g.mission_lease("person"):
            holding.set()
            done.wait(timeout=5)

    def asker() -> None:
        started.wait()
        assert holding.wait(timeout=5)
        verdicts.append(g.try_admit_generation(estimated_ms=500.0).admitted)
        done.set()

    threads = [threading.Thread(target=holder), threading.Thread(target=asker)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert verdicts == [False]
    assert g.active_leases() == ()


# ---------------------------------------------------------------------------
# the process-wide guard
# ---------------------------------------------------------------------------


def test_the_default_guard_is_a_single_shared_instance() -> None:
    """Both halves must consult ONE guard or the rule is unenforceable."""

    set_default_guard(None)
    try:
        assert default_guard() is default_guard()
    finally:
        set_default_guard(None)


def test_stats_count_admissions_refusals_and_expiries(guard: PerceptionContentionGuard) -> None:
    guard.try_admit_generation(estimated_ms=10.0)
    with guard.mission_lease("person"):
        guard.try_admit_generation(estimated_ms=10.0)
    stats = guard.stats()
    assert stats["admitted"] == 1
    assert stats["refused"] == 1
    assert stats["active_leases"] == 0
