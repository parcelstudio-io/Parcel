"""V-E D3+D4 gates: detection lock-on + chance-constrained K0.

Flag-off paths must stay byte-identical to the pre-V-E frustum commit.
Zero-covariance K0 must match today's boolean (T0 byte-equal).
"""

from __future__ import annotations

import importlib
import math
from pathlib import Path

import pytest

# Eager pipeline load before instructnav.arbiter (C-B core.arbiter → navigation
# cycle otherwise leaves GoalArbiter half-initialized under isort order).
importlib.import_module("parcel_robot.navigation.pipeline")

from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus
from parcel_robot.instructnav.near_arrival import near_band_contains
from parcel_robot.instructnav.scoring import (
    INSIDE_PROBABILITY_THRESHOLD,
    differential_arrival_verdict,
    object_near_goal_region,
    p_inside_goal_region,
)
from parcel_robot.navigation import DirectiveNavigator, ModelRegistry, PlaceGrounder
from parcel_robot.navigation.detection_lock_on import (
    LOCK_ON_PROPOSER_SOURCE,
    T_CAM_ORACLE_SR_MARGIN,
    DetectionLockOnSession,
    covariance_from_candidate,
)
from parcel_robot.navigation.semantic_map import SemanticCandidate

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "configs" / "navigation" / "models"


# ---------------------------------------------------------------------------
# D4 — chance-constrained K0 / T0 byte-equal
# ---------------------------------------------------------------------------


def test_zero_covariance_contains_matches_boolean_exactly() -> None:
    region = object_near_goal_region((0.0, 0.0), 0.06, label="lamppost")
    # Mid-band point for a lamppost near envelope.
    lo, hi = region.band_m
    assert lo is not None and hi is not None
    r = 0.5 * (lo + hi)
    x, y = r, 0.0
    assert region.contains(x, y) is True
    assert region.contains(x, y, anchor_covariance=None) is True
    assert region.contains(x, y, anchor_covariance=((0.0, 0.0), (0.0, 0.0))) is True
    assert p_inside_goal_region(x, y, region) == 1.0
    assert near_band_contains((x, y), region) is True

    outside = (hi + 0.5, 0.0)
    assert region.contains(*outside) is False
    assert region.contains(*outside, anchor_covariance=((0.0, 0.0), (0.0, 0.0))) is False
    assert p_inside_goal_region(*outside, region) == 0.0


def test_noisy_far_detection_refuses_boundary_arrival() -> None:
    """Wide D2 covariance at the band edge must not claim arrival (P<0.9)."""

    region = object_near_goal_region((0.0, 0.0), 0.06, label="lamppost")
    _lo, hi = region.band_m
    assert hi is not None
    # Sit exactly on the outer edge.
    x, y = float(hi), 0.0
    assert region._contains_exact(x, y) is True
    wide = ((0.25, 0.0), (0.0, 0.25))  # σ≈0.5 m
    assert region.contains(x, y, anchor_covariance=wide) is False
    prob = p_inside_goal_region(x, y, region, anchor_covariance=wide)
    assert prob < INSIDE_PROBABILITY_THRESHOLD


def test_crisp_near_detection_still_arrives() -> None:
    region = object_near_goal_region((0.0, 0.0), 0.06, label="lamppost")
    lo, hi = region.band_m
    assert lo is not None and hi is not None
    r = 0.5 * (lo + hi)
    tight = ((1e-6, 0.0), (0.0, 1e-6))
    assert region.contains(r, 0.0, anchor_covariance=tight) is True


def test_differential_authority_zero_cov_unchanged() -> None:
    region = object_near_goal_region((1.0, 2.0), 0.06, label="lamppost")
    lo, hi = region.band_m
    assert lo is not None and hi is not None
    xy = (1.0 + 0.5 * (lo + hi), 2.0)
    v_bool = differential_arrival_verdict(region, xy, system_arrival=True)
    v_zero = differential_arrival_verdict(
        region, xy, system_arrival=True, anchor_covariance=((0.0, 0.0), (0.0, 0.0))
    )
    assert v_bool.scorer_arrival == v_zero.scorer_arrival is True
    assert v_bool.category == v_zero.category


# ---------------------------------------------------------------------------
# D3 — detection lock-on pure + SE2 stamp / P0-C mid-run correction
# ---------------------------------------------------------------------------


def _cand(
    cid: str,
    label: str,
    x: float,
    y: float,
    *,
    score: float = 0.4,
    sigma_range: float = 0.05,
) -> SemanticCandidate:
    range_m = math.hypot(x, y)
    return SemanticCandidate(
        candidate_id=cid,
        label=label,
        x=x,
        y=y,
        confidence=score,
        kind="object",
        source="pixel_detector",
        metadata={
            "range_m": range_m,
            "bearing_rad": math.atan2(y, x),
            "sigma_range_m": sigma_range,
            "radius_m": 0.06,
        },
    )


def test_lock_on_requires_m_of_n_and_siglip() -> None:
    session = DetectionLockOnSession()
    query = "lamppost"
    robot = (0.0, 0.0)
    decision = None
    for view in range(3):
        decision = session.observe_candidate(
            query=query,
            candidate=_cand("lamp-1", "lamppost", 3.0, 0.0, score=0.35 + 0.03 * view),
            robot_xy=robot,
            now_ns=1_000_000 * (view + 1),
        )
        if view < 2:
            assert decision is None
    assert decision is not None
    assert decision.credibility >= 0.65
    assert decision.siglip_score >= 0.90 or decision.siglip_score == 1.0


def test_lock_on_se2_carries_task_revision_stamp() -> None:
    session = DetectionLockOnSession()
    robot = (0.0, 0.0)
    decision = None
    for view in range(3):
        decision = session.observe_candidate(
            query="bench",
            candidate=_cand("bench-1", "bench", 2.0, 1.0, score=0.5),
            robot_xy=robot,
            now_ns=10_000 * (view + 1),
        )
    assert decision is not None
    goal = session.build_se2_goal(
        decision, task_id="nav-mission", plan_revision=2, now_s=1.5
    )
    assert goal.source == LOCK_ON_PROPOSER_SOURCE
    assert goal.task_id == "nav-mission"
    assert goal.plan_revision == 2
    assert goal.pose is not None
    assert math.isclose(goal.pose[0], decision.position[0], abs_tol=1e-9)


def test_p0c_mid_run_correction_flushes_stale_lock_on_goal() -> None:
    """Detection-triggered SE2Goal is flushed on plan_revision bump (P0-C)."""

    bus = ProposerBus()
    arbiter = GoalArbiter()
    session = DetectionLockOnSession()
    robot = (0.0, 0.0)
    decision = None
    for view in range(3):
        decision = session.observe_candidate(
            query="lamppost",
            candidate=_cand("lamp-a", "lamppost", 4.0, 0.0, score=0.5),
            robot_xy=robot,
            now_ns=1000 * (view + 1),
        )
    assert decision is not None
    old = session.build_se2_goal(
        decision, task_id="nav-1", plan_revision=1, now_s=1.0
    )
    bus.publish(old)
    arbiter.set_plan_step(old.plan_step_id)
    assert arbiter.resolve(bus.poll(now_s=1.0), now_s=1.0) is not None

    # Mid-run correction: bump revision, flush sinks.
    bus.commit_revision(task_id="nav-1", plan_revision=2)
    arbiter.commit_revision(task_id="nav-1", plan_revision=2)
    assert bus.poll(now_s=1.1) == ()
    assert arbiter.resolve((old,), now_s=1.1) is None

    # New target under revision 2 wins.
    session.reset()
    decision2 = None
    for view in range(3):
        decision2 = session.observe_candidate(
            query="lamppost",
            candidate=_cand("lamp-b", "lamppost", -5.0, 2.0, score=0.5),
            robot_xy=robot,
            now_ns=50_000 * (view + 1),
        )
    assert decision2 is not None
    new = session.build_se2_goal(
        decision2, task_id="nav-1", plan_revision=2, now_s=2.0
    )
    bus.publish(new)
    arbiter.set_plan_step(new.plan_step_id)
    chosen = arbiter.resolve(bus.poll(now_s=2.0), now_s=2.0)
    assert chosen is not None
    assert chosen.pose is not None
    assert chosen.pose[0] < 0.0  # new target, not old +x
    assert chosen.plan_revision == 2


def test_single_frame_never_locks_on() -> None:
    session = DetectionLockOnSession()
    decision = session.observe_candidate(
        query="lamppost",
        candidate=_cand("fp", "lamppost", 3.0, 0.0, score=1.0),
        robot_xy=(0.0, 0.0),
        now_ns=1,
    )
    assert decision is None


def test_covariance_from_candidate_polar_reconstruct() -> None:
    cand = _cand("c1", "tree", 2.0, 0.0, sigma_range=0.1)
    cov = covariance_from_candidate(cand, robot_xy=(0.0, 0.0))
    assert cov[0][0] > 0.0
    assert math.isclose(cov[0][1], cov[1][0], abs_tol=1e-12)


def test_flag_off_navigator_has_no_lock_on_session() -> None:
    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        detection_lock_on=False,
    )
    assert nav.detection_lock_on is False
    assert nav._detection_lock_on is None


def test_flag_on_navigator_constructs_session() -> None:
    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        detection_lock_on=True,
    )
    assert nav.detection_lock_on is True
    assert nav._detection_lock_on is not None


def test_t_cam_oracle_margin_constant_preregistered() -> None:
    assert T_CAM_ORACLE_SR_MARGIN == pytest.approx(0.10)


def test_paired_seed_lock_on_sr_within_oracle_margin() -> None:
    """Additive proxy: lock-on confirms the same paired seeds the oracle would.

    Pre-registered margin: |SR_lock − SR_oracle| ≤ T_CAM_ORACLE_SR_MARGIN.
    Oracle here = grounded candidate present each view (perfect frustum);
    lock-on = D1+SigLIP session over the same candidates.
    """

    seeds = list(range(12))
    oracle_ok = 0
    lock_ok = 0
    for seed in seeds:
        # Oracle: candidate present ⇒ "would commit" after 2 sightings.
        oracle_ok += 1
        session = DetectionLockOnSession()
        label = "lamppost"
        # Alternate a low-score true target; all should confirm by view 3.
        decision = None
        for view in range(3):
            x = 2.5 + 0.01 * seed
            decision = session.observe_candidate(
                query=label,
                candidate=_cand(
                    f"t-{seed}",
                    label,
                    x,
                    0.1 * (seed % 3),
                    score=0.30 + 0.05 * view,
                ),
                robot_xy=(0.0, 0.0),
                now_ns=1_000_000 * seed + view + 1,
            )
        if decision is not None:
            lock_ok += 1
    sr_oracle = oracle_ok / len(seeds)
    sr_lock = lock_ok / len(seeds)
    assert abs(sr_lock - sr_oracle) <= T_CAM_ORACLE_SR_MARGIN + 1e-12


def test_false_arrival_suppressed_on_absent_target() -> None:
    """Absent / FP: single-frame phantoms never lock; differential FP count = 0."""

    session = DetectionLockOnSession()
    # One-frame phantom each "episode".
    false_arrivals = 0
    for episode in range(8):
        session.reset()
        d = session.observe_candidate(
            query="bench",
            candidate=_cand(f"fp-{episode}", "tree", 5.0, 0.0, score=0.99),
            robot_xy=(0.0, 0.0),
            now_ns=episode + 1,
        )
        if d is not None:
            false_arrivals += 1
        region = object_near_goal_region((5.0, 0.0), 0.5, label="tree")
        # System did not arrive; scorer must not invent a false_arrival category
        # from a non-commit.
        verdict = differential_arrival_verdict(
            region, (0.0, 0.0), system_arrival=False
        )
        assert verdict.category.value != "false_arrival"
    assert false_arrivals == 0
