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

from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal
from parcel_robot.instructnav.near_arrival import near_band_contains
from parcel_robot.instructnav.scoring import (
    INSIDE_PROBABILITY_THRESHOLD,
    differential_arrival_verdict,
    object_near_goal_region,
    p_inside_goal_region,
)
from parcel_robot.navigation.detection_lock_on import (
    LOCK_ON_PROPOSER_SOURCE,
    T_CAM_ORACLE_SR_MARGIN,
    DetectionLockOnSession,
    covariance_from_candidate,
)
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry
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



# ---------------------------------------------------------------------------
# VS-4 — arrival integrity + verify-on-approach wiring
#
# Card VS-4 (scrum/20260811/task_1/FOLLOWUP_DESIGNS.md §2.2(a)+(b), §6). Each
# test names the gate clause it covers. The Wave-2 pure modules (VS-1's session
# and per-kind gate, VS-2's negative-evidence memory) are consumed FROZEN —
# nothing here re-implements them.
# ---------------------------------------------------------------------------

from parcel_robot.instructnav.scoring import ApproachVerifyState, object_near_envelope_m
from parcel_robot.navigation.base import MidLevelCommand, NavObservation
from parcel_robot.navigation.lock_on_verify import REGION_DILATION_M, checkpoint_radii_m

# RM-2 extension of the AF-2 interleaving suite (see the block below
# ``test_flush_task_clears_the_buffer_without_moving_the_ledger``).
from parcel_robot.route_memory.proposer import PLACE_ROUTE_SOURCE

#: The measured B-05 displacement: the fused point sat on the SOUTH sidewalk
#: while the mission's grounded reference was the north polygon (record
#: §2.1(1)); VS-1's unit suite pins the same number.
B05_DISPLACEMENT_M = 4.778530810034543
NORTH_SIDEWALK = ((-6.0, 2.2), (6.0, 2.2), (6.0, 4.2), (-6.0, 4.2))
SOUTH_SIDEWALK_POINT = (1.3480, 2.2 - B05_DISPLACEMENT_M)
LAMP_ENVELOPE = object_near_envelope_m(0.06, label="lamppost")


def _nav(**flags: bool) -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        **flags,
    )


def _object_item(
    xy: tuple[float, float],
    *,
    cid: str = "lamp_post_1",
    label: str = "lamppost",
) -> dict:
    return {
        "id": cid,
        "label": label,
        "kind": "object",
        "position": [xy[0], xy[1], 0.0],
        "confidence": 0.98,
        "reachable": True,
        "metadata": {
            "radius_m": 0.06,
            "stand_off_m": LAMP_ENVELOPE[0],
            "minimum_vicinity_radius_m": LAMP_ENVELOPE[1],
            "vicinity_radius_m": LAMP_ENVELOPE[2],
        },
    }


def _region_candidate(cid: str, polygon: tuple[tuple[float, float], ...]) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=cid,
        label="sidewalk",
        x=sum(p[0] for p in polygon) / len(polygon),
        y=sum(p[1] for p in polygon) / len(polygon),
        confidence=0.98,
        kind="region",
        polygon=polygon,
        source="simulator_semantic_camera",
        reachable=True,
        metadata={"radius_m": 0.0},
    )


def _observation(
    robot_xy: tuple[float, float] = (0.0, 0.0),
    *,
    items: tuple[dict, ...] = (),
    time_s: float = 0.0,
    lidar_target_xy: tuple[float, float] | None = None,
) -> NavObservation:
    """One tick, in the shape the eval harness publishes.

    ``lidar_target_xy`` puts a range return on the target's near surface — the
    "something behind the detection" a phantom does not have.
    """

    lidar: list[dict] = []
    if lidar_target_xy is not None:
        dx = lidar_target_xy[0] - robot_xy[0]
        dy = lidar_target_xy[1] - robot_xy[1]
        lidar.append(
            {
                "distance_m": max(0.0, math.hypot(dx, dy) - 0.4),
                "bearing_rad": math.atan2(dy, dx),
            }
        )
    return NavObservation(
        position=(robot_xy[0], robot_xy[1], 0.0),
        heading_deg=0.0,
        extras={
            "collision": False,
            "perception_fresh": True,
            "time_s": time_s,
            "semantic_candidates": list(items),
            "lidar_obstacles": lidar,
        },
    )


def _drive_to_commit(nav: DirectiveNavigator, mission, items_for_tick, budget: int = 90):
    for tick in range(budget):
        nav.step(_observation((0.0, 0.0), items=items_for_tick(tick), time_s=0.1 * tick))
        if mission.goal is not None:
            return tick
    raise AssertionError("the mission never committed inside the budget")


def test_verify_flag_defaults_off_and_cannot_run_without_the_lock_on_flag() -> None:
    """Flag-gated default-OFF; the verify path is a layer ON the D3 lock-on."""

    off = _nav()
    assert off.lock_on_verify_on_approach is False
    assert off._lock_on_fp_memory is None
    assert off._lock_on_verify is None

    alone = _nav(lock_on_verify_on_approach=True)
    assert alone.lock_on_verify_on_approach is False, (
        "verify-on-approach without detection_lock_on must stay inert"
    )

    both = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
    assert both.lock_on_verify_on_approach is True
    assert both._lock_on_fp_memory is not None


def test_committed_arrival_region_provenance_is_the_grounded_reference() -> None:
    """Gate (3), half one: the region comes from the REFERENCE, never the fused point.

    The estimator is looking at a displaced reading of the same class (inside
    the vicinity, so the refinement gate accepts and the commit proceeds). The
    committed geometry must be the GROUNDED instance's, bit-for-bit — the
    rewrite at ``:1673-1686`` feeding ``:1809-1826`` is what produced the B-05
    false arrival, and it is what must not happen here.
    """

    # The reading is displaced along the bearing by well under its own range
    # sigma, so the per-kind gate ACCEPTS it (a consistent refinement) and the
    # commit proceeds — this test is about provenance, not about refusal.
    grounded_xy, seen_xy = (4.0, 0.0), (4.10, 0.0)
    nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
    mission = nav.start("go to the lamppost")
    grounded = _cand("lamp_post_1", "lamppost", *grounded_xy, score=0.98)
    seen = _cand("lamp_post_1", "lamppost", *seen_xy, score=0.98, sigma_range=0.6)
    observation = _observation((0.0, 0.0), items=(_object_item(seen_xy),))
    assert nav._lock_on_fuse(mission.semantic_goal, observation, seen) is not None
    estimate = nav._detection_lock_on.localizer.estimate
    assert estimate is not None
    assert math.hypot(
        estimate.position[0] - grounded_xy[0], estimate.position[1] - grounded_xy[1]
    ) > 1e-9, "estimate and reference coincide; the test would prove nothing"

    nav._commit_semantic_candidate(
        mission.semantic_goal, grounded, observation, grounding_outcome="resolved"
    )
    assert mission.goal is not None, "the commit was refused; provenance untested"
    assert mission.metadata["goal_landmark_id"] == "lamp_post_1"
    assert mission.metadata["candidate_position"][:2] == grounded_xy
    region = mission.metadata["arrival_goal_region"]
    assert tuple(region["center"]) == grounded_xy, (
        "arrival region built from the fused estimate — the V-E rewrite"
    )
    assert tuple(region["center"]) != tuple(estimate.position)
    assert region["anchor_entity"] == "lamp_post_1"
    # And the verify session is opened against that same grounded reference.
    assert nav._lock_on_verify is not None
    assert nav._lock_on_verify.reference.landmark_id == "lamp_post_1"


def test_b05_wrong_instance_fused_point_is_refused_and_remembered() -> None:
    """Gate (3)+(4): the measured B-05 displacement is a REFUTATION, not a commit."""

    nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
    mission = nav.start("walk onto the sidewalk")
    north = _region_candidate("sidewalk_north", NORTH_SIDEWALK)
    south_polygon = tuple(
        (SOUTH_SIDEWALK_POINT[0] + dx, SOUTH_SIDEWALK_POINT[1] + dy)
        for dx, dy in ((-6.0, -1.0), (6.0, -1.0), (6.0, 1.0), (-6.0, 1.0))
    )
    south = _region_candidate("sidewalk_south", south_polygon)
    observation = _observation((0.0, 0.0))
    # The estimator has been looking at the SOUTH instance.
    assert nav._lock_on_fuse(mission.semantic_goal, observation, south) is not None

    refused = nav._commit_semantic_candidate(
        mission.semantic_goal, north, observation, grounding_outcome="resolved"
    )
    assert refused is not None
    assert mission.goal is None, "committed a reference the estimate contradicts"
    assert mission.metadata["lock_on_refusal"] == "fused_point_outside_dilated_region"
    assert nav.lock_on_refutations == 1
    displacement = float(mission.metadata["lock_on_refinement_displacement_m"])
    assert displacement == pytest.approx(B05_DISPLACEMENT_M, abs=1e-9)
    assert displacement > REGION_DILATION_M
    assert nav._lock_on_fp_memory.suppressed(
        "sidewalk", SOUTH_SIDEWALK_POINT, view_index=nav._lock_on_view_index
    )

    # Re-encounter (adjudication #19's third conjunct): the next hypothesis at
    # the remembered place is suppressed BEFORE any commit is considered.
    nav._commit_semantic_candidate(
        mission.semantic_goal, south, observation, grounding_outcome="resolved"
    )
    assert nav.lock_on_suppressions == 1
    assert mission.goal is None


def test_lock_on_defers_to_the_ranking_for_interchangeable_queries() -> None:
    """Gate (3), half two: the instance is chosen by the flag-OFF authority.

    Structural proof: with the flag on, the searching path never reaches the
    lock-on commit door — the seam that produced the wrong-instance commit is
    unreachable — while the deference counter shows the session still observing.
    """

    nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
    mission = nav.start("walk onto the sidewalk")
    assert mission.semantic_goal.kind == "region"

    def _forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("lock-on took the commit door on an interchangeable query")

    nav._try_detection_lock_on = _forbidden  # type: ignore[method-assign]
    region_item = {
        "id": "sidewalk_north",
        "label": "sidewalk",
        "kind": "region",
        "polygon": [list(point) for point in NORTH_SIDEWALK],
        "confidence": 0.98,
        "reachable": True,
        "metadata": {"radius_m": 0.0},
    }
    for tick in range(12):
        nav.step(_observation((0.0, 0.0), items=(region_item,), time_s=0.1 * tick))
    assert nav.lock_on_deferred_ticks > 0, "the lock-on session never observed"


def test_verify_on_approach_refutes_a_detection_with_nothing_behind_it() -> None:
    """Gate (4): a COMMITTED hypothesis is refuted on approach, and flushed.

    Persistence is the pipeline's own association between the detection and the
    range channel. The control arm — identical geometry, a range return where
    the detection says the body is — clears its checkpoints instead, so the
    refusal is evidence rather than a constant.
    """

    target = (2.0, 0.0)
    states: dict[bool, list[str]] = {}
    for supported in (True, False):
        nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
        mission = nav.start("go to the lamppost")
        _drive_to_commit(nav, mission, lambda tick: (_object_item(target),))
        assert nav._lock_on_verify is not None
        revision_before = nav._active_plan_revision
        for tick in range(40):
            if nav._lock_on_verify is None:
                break
            robot = (target[0] - 6.0 + 0.25 * tick, 0.0)
            nav._verify_lock_on_on_approach(
                _observation(
                    robot,
                    items=(_object_item(target),),
                    time_s=10.0 + 0.1 * tick,
                    lidar_target_xy=target if supported else None,
                )
            )
        states[supported] = [state for _sid, state in nav.lock_on_verify_states]
        if supported:
            assert ApproachVerifyState.REJECTED.value not in states[supported]
            assert nav.lock_on_refutations == 0
            assert nav._active_plan_revision == revision_before
            assert mission.goal is not None
        else:
            assert states[supported][-1] == ApproachVerifyState.REJECTED.value
            assert states[supported][0] in {
                ApproachVerifyState.APPROACH.value,
                ApproachVerifyState.VERIFY.value,
                ApproachVerifyState.VERIFIED.value,
            }, "no committed state preceded the refutation"
            assert nav.lock_on_refutations == 1
            assert nav.lock_on_flushes == 1
            # AF-2 amendment (AUDIT_WAVE2_FABLE.md, BLOCKING): the refusal purge
            # is revision-NEUTRAL. It used to assert ``revision_before + 1``,
            # which is the ledger usurpation that permanently vetoed the task.
            assert nav._active_plan_revision == revision_before
            assert nav.proposer_bus.committed_revision(nav._active_task_id) == 0
            assert nav.goal_arbiter.committed_revision(nav._active_task_id) == 0
            assert mission.goal is None
            assert nav._lock_on_fp_memory.suppressed(
                "lamppost", target, view_index=nav._lock_on_view_index
            )
    assert states[True] != states[False]


def test_visible_but_unroutable_window_keeps_the_proposal_pending() -> None:
    """The ~8-12 m window (W2_EVAL_STATUS.md §3) must refute nothing.

    The grid planner's local costmap reaches ~8 m while the frustum reaches
    12 m, so a locked target is visible-but-unroutable in between. The near-object
    envelope's checkpoints are metres, not tens of metres, so none is due there:
    the proposal simply stays PENDING and keeps being re-verified. Nothing is
    loosened to make that true — the window is quiet because no evidence is due.
    """

    target = (12.0, 0.0)
    nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
    mission = nav.start("go to the lamppost")
    _drive_to_commit(nav, mission, lambda tick: (_object_item(target),))
    session = nav._lock_on_verify
    assert session is not None
    pending_before = session.pending_checkpoints
    for tick in range(40):
        robot = (0.1 * tick, 0.0)  # 12 m -> 8 m of range, no range return at all
        assert (
            nav._verify_lock_on_on_approach(
                _observation(robot, items=(_object_item(target),), time_s=10.0 + 0.1 * tick)
            )
            is None
        )
    assert nav._lock_on_verify is session
    assert session.state is ApproachVerifyState.APPROACH
    assert session.pending_checkpoints == pending_before
    assert nav.lock_on_refutations == 0
    assert mission.goal is not None, "the mission dropped its reference in the window"


def test_telemetry_note_carries_the_conjuncts_without_a_runner_keyword() -> None:
    """The counters ride the one navigator channel the frozen runner persists."""

    off = _nav()
    assert off._lock_on_telemetry_note("semantic_search_scan") == "semantic_search_scan"

    nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
    note = nav._lock_on_telemetry_note("semantic_search_scan")
    assert note.startswith("semantic_search_scan"), "the runner's scan counter must survive"
    payload = note.split("|", 1)[1]
    for keyword in ("frontier", "semantic_target_not_found", "scan_for_target"):
        assert keyword not in payload
    for field in ("sessions=", "commits=", "refutations=", "suppressions="):
        assert field in payload


# ---------------------------------------------------------------------------
# AF-2 — the refusal purge must not usurp the revision authority
#
# Provenance: scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md, "BLOCKING — VS-4's
# refusal flush usurps the revision authority". The pipeline used to self-commit
# ``plan_revision + 1`` into the ProposerBus/GoalArbiter ledgers; the runtime
# restamps the navigator with the EXECUTIVE's (lower) revision on every nav
# start/resume and plan accept, so from then on every published goal was stale,
# ``resolve`` returned ``None``, and the mission died ``arbiter_veto`` forever
# (the ledger never lowers, so it could not self-heal).
# ---------------------------------------------------------------------------

AF2_TASK_ID = "nav-mission"


def _refute_on_approach(nav: DirectiveNavigator, target: tuple[float, float]) -> None:
    """Drive the committed reference to a REJECTED verdict (no range support)."""

    for tick in range(40):
        if nav._lock_on_verify is None:
            break
        robot = (target[0] - 6.0 + 0.25 * tick, 0.0)
        nav._verify_lock_on_on_approach(
            _observation(
                robot,
                items=(_object_item(target),),
                time_s=10.0 + 0.1 * tick,
                lidar_target_xy=None,
            )
        )
    assert nav.lock_on_refutations == 1, "the refutation never fired"
    assert nav.lock_on_flushes == 1


def _committed_and_stamped(nav: DirectiveNavigator) -> tuple[int, int, int]:
    return (
        nav.proposer_bus.committed_revision(AF2_TASK_ID),
        nav.goal_arbiter.committed_revision(AF2_TASK_ID),
        nav._active_plan_revision,
    )


def _publish_and_resolve(nav: DirectiveNavigator, revision: int):
    goal = SE2Goal(
        source="grounder",
        pose=(3.0, 4.0, 0.0),
        confidence=1.0,
        ttl_s=10.0,
        plan_step_id="align_then_translate",
        issued_s=0.0,
        priority=10,
        task_id=AF2_TASK_ID,
        plan_revision=revision,
    )
    nav.proposer_bus.publish(goal)
    nav.goal_arbiter.set_plan_step("align_then_translate")
    return nav.goal_arbiter.resolve(nav.proposer_bus.poll(now_s=0.0), now_s=0.0)


def _refuted_navigator() -> tuple[DirectiveNavigator, object, tuple[float, float]]:
    nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
    nav.set_active_revision(AF2_TASK_ID, 1)
    mission = nav.start("go to the lamppost")
    target = (2.0, 0.0)
    _drive_to_commit(nav, mission, lambda tick: (_object_item(target),))
    sources = {goal.source for goal in nav.proposer_bus.poll(now_s=0.0)}
    assert "grounder" in sources, "the commit never published a proposal to buffer"
    _refute_on_approach(nav, target)
    return nav, mission, target


def test_refusal_purge_is_revision_neutral_and_the_task_is_not_vetoed() -> None:
    """The audit's exact repro: refute -> restamp-lower -> publish -> resolve.

    Under the defect this ended ``resolve() is None`` forever. Three claims:
    the ledger is untouched, the refuted proposal is genuinely gone from the
    buffer, and a proposal published after the runtime's restamp still wins.
    """

    nav, _mission, _target = _refuted_navigator()

    # (a) revision authority stayed with the executive: nothing was committed.
    assert _committed_and_stamped(nav) == (0, 0, 1)

    # (b) the refuted proposal is genuinely withdrawn (this is the purge's job).
    assert "grounder" not in {goal.source for goal in nav.proposer_bus.poll(now_s=0.0)}

    # (c) the runtime restamps the navigator with the executive's revision on the
    # next nav start / resume / plan accept (runtime._apply_active_nav_revision).
    nav.set_active_revision(AF2_TASK_ID, 1)
    assert _publish_and_resolve(nav, 1) is not None, "the task is still vetoed"


def test_refused_mission_can_commit_again_on_the_product_path() -> None:
    """End to end: after a refutation the navigator still reaches a new goal.

    The defect's signature was ``resolution_state == "arbiter_veto"`` on the very
    next commit, because the pipeline's own ledger bump outranked its own stamp.
    """

    nav, mission, _target = _refuted_navigator()
    assert mission.goal is None
    elsewhere = (-4.0, 3.0)
    for tick in range(90):
        nav.step(
            _observation(
                (0.0, 0.0),
                items=(_object_item(elsewhere, cid="lamp_post_2"),),
                time_s=20.0 + 0.1 * tick,
                lidar_target_xy=elsewhere,
            )
        )
        if mission.goal is not None:
            break
    assert mission.metadata.get("resolution_state") != "arbiter_veto"
    assert mission.goal is not None, "the mission never re-committed after a refusal"


def test_refusal_survives_pause_resume_restamp() -> None:
    """Pause/resume restamps the navigator (runtime._start_or_resume_navigation)."""

    nav, _mission, _target = _refuted_navigator()
    nav.pause()
    nav.resume()
    # runtime._start_or_resume_navigation_locked stamps on EVERY start and resume.
    nav.set_active_revision(AF2_TASK_ID, 1)
    assert _committed_and_stamped(nav) == (0, 0, 1)
    assert _publish_and_resolve(nav, 1) is not None


def test_refusal_then_new_directive_on_the_same_task_is_not_vetoed() -> None:
    """Mission end -> new directive under the same task and revision."""

    nav, mission, _target = _refuted_navigator()
    mission.status = "failed"
    nav.set_active_revision(AF2_TASK_ID, 1)  # nav start restamp
    nav.start("go to the bench")
    assert _committed_and_stamped(nav) == (0, 0, 1)
    assert _publish_and_resolve(nav, 1) is not None


def test_a_real_executive_revision_still_drops_stale_proposals_after_a_refusal() -> None:
    """The purge must not weaken P0-C: real corrections still fail closed."""

    nav, _mission, _target = _refuted_navigator()
    # The OWNER corrects the mission; the executive commits revision 2 into both
    # sinks, exactly as brain.executive._notify_revision_committed does.
    nav.proposer_bus.commit_revision(task_id=AF2_TASK_ID, plan_revision=2)
    nav.goal_arbiter.commit_revision(task_id=AF2_TASK_ID, plan_revision=2)
    assert _publish_and_resolve(nav, 1) is None, "a corrected-away straggler won"
    assert _publish_and_resolve(nav, 2) is not None


def test_flush_task_clears_the_buffer_without_moving_the_ledger() -> None:
    """The amended P0-C API, at the contract level."""

    bus = ProposerBus()
    arbiter = GoalArbiter(episode_id="af2-flush")
    bus.commit_revision(task_id=AF2_TASK_ID, plan_revision=3)
    mine = SE2Goal(
        source="grounder", pose=(1.0, 0.0, 0.0), issued_s=0.0, ttl_s=10.0,
        task_id=AF2_TASK_ID, plan_revision=3,
    )
    other = SE2Goal(
        source="search_entity", pose=(2.0, 0.0, 0.0), issued_s=0.0, ttl_s=10.0,
        task_id="other-task", plan_revision=1,
    )
    bus.publish(mine)
    bus.publish(other)

    assert bus.flush_task(AF2_TASK_ID) == 1
    assert {goal.source for goal in bus.poll(now_s=0.0)} == {"search_entity"}
    # The ledger did NOT move — that is the whole amendment.
    assert bus.committed_revision(AF2_TASK_ID) == 3
    # ... and the same revision may buffer and win again immediately.
    bus.publish(mine)
    assert arbiter.resolve(bus.poll(now_s=0.0), now_s=0.0) is not None
    # A stale one still cannot.
    bus.flush_task(AF2_TASK_ID)
    stale = SE2Goal(
        source="grounder", pose=(1.0, 0.0, 0.0), issued_s=0.0, ttl_s=10.0,
        task_id=AF2_TASK_ID, plan_revision=2,
    )
    bus.publish(stale)
    assert "grounder" not in {goal.source for goal in bus.poll(now_s=0.0)}

    # The arbiter holds no buffer; its flush is a documented, ledger-neutral no-op.
    arbiter.commit_revision(task_id=AF2_TASK_ID, plan_revision=3)
    assert arbiter.flush_task(AF2_TASK_ID) == 0
    assert arbiter.committed_revision(AF2_TASK_ID) == 3


# ---------------------------------------------------------------------------
# RM-2 EXTENSION of the AF-2 interleaving suite above (2026-08-12).
# Provenance: ``scrum/20260811/task_2/SLAM_M_PLAN.md`` card RM-2, gate (d) —
# "correction mid-chain flushes pending waypoints (AF-2 interleaving
# extension)". Additive only: nothing above this block is edited.
#
# Route memory publishes an SE2Goal like any other proposer, so it inherits the
# whole P0-C contract AF-2 closed — and it inherits AF-2's defect too if it ever
# reaches for ``commit_revision``. These cells pin the three interleavings the
# card names, against the SAME ``AF2_TASK_ID`` and the SAME
# ``_committed_and_stamped`` reading the cases above use.
# ---------------------------------------------------------------------------


class _RouteBlockedNavigator:
    """``goal_blocked`` forever, so the RM-2 deferral trigger is reached."""

    def __init__(self) -> None:
        self.last_route_status = "goal_blocked"

    def reset(self, mission) -> None:
        mission.status = "running"

    def act(self, observation, mission) -> MidLevelCommand:
        return MidLevelCommand(vx=0.0, vyaw=0.2, note="grid_recover_scan status=goal_blocked")

    def close(self) -> None:
        return None


#: 18 m out along +x: the object is far beyond the planner's 8.05 m reach, which
#: is the only condition under which route memory is consulted at all.
RM2_TARGET_XY = (18.0, 0.0)


def _navigator_with_a_live_waypoint_chain():
    """A pipeline mid-chain: taught route, committed goal, waypoint winning."""

    nav = _nav(route_memory=True)
    nav.set_active_revision(AF2_TASK_ID, 1)
    # AUTO-TEACH: drive the straight corridor the mission will later need.
    nav.start("go to the lamppost")
    for step in range(41):
        nav.step(_observation((step * 0.5, 0.0), time_s=0.1 * step))
    # A fresh mission (mission boundary => reset_track), robot back at the origin.
    mission = nav.start("go to the lamppost")
    _drive_to_commit(nav, mission, lambda _tick: (_object_item(RM2_TARGET_XY),))
    nav._navigator = _RouteBlockedNavigator()
    for tick in range(DirectiveNavigator.UNROUTABLE_GOAL_STEPS + 4):
        nav.step(
            _observation(
                (0.0, 0.0), items=(_object_item(RM2_TARGET_XY),), time_s=10.0 + 0.1 * tick
            )
        )
        if nav._route_memory_chain:
            break
    assert nav._route_memory_chain, "no waypoint chain was ever armed; the case is vacuous"
    assert nav._route_memory_target is not None
    buffered = {goal.source for goal in nav.proposer_bus.poll(now_s=0.0)}
    assert PLACE_ROUTE_SOURCE in buffered, "the waypoint never reached the shared bus"
    return nav, mission


def test_rm2_a_correction_mid_chain_flushes_the_pending_waypoints() -> None:
    """Card RM-2 gate (d), on AF-2's own contract.

    A correction is exactly a change of the active revision key. The chain was
    derived under the old one, so it goes — and it goes the way AF-2's BLOCKING
    finding says it must: through the revision-NEUTRAL ``flush_task`` purge, not
    through ``commit_revision``. The ledger reading is AF-2's own
    ``_committed_and_stamped``.
    """

    nav, mission = _navigator_with_a_live_waypoint_chain()

    nav.set_active_revision(AF2_TASK_ID, 2)

    assert nav._route_memory_chain == ()
    assert nav._route_memory_target is None
    assert PLACE_ROUTE_SOURCE not in {goal.source for goal in nav.proposer_bus.poll(now_s=0.0)}
    assert mission.metadata["route_memory_flush"] == "revision_changed"
    assert nav.route_memory_flushes == 1
    # AF-2's whole point: the purge did not usurp the executive's authority.
    assert _committed_and_stamped(nav) == (0, 0, 2)
    # ...and the task is not vetoed afterwards.
    assert _publish_and_resolve(nav, 2) is not None
    # The mission goal is untouched by the flush: a correction that keeps the
    # same target simply re-derives the chain on the next trigger.
    assert mission.goal is not None


def test_rm2_a_lock_on_refusal_mid_chain_withdraws_the_waypoint_too() -> None:
    """A refutation is a statement about ONE commitment — and its chain."""

    nav, mission = _navigator_with_a_live_waypoint_chain()

    nav._flush_lock_on_proposal()

    assert nav._route_memory_chain == ()
    assert nav._route_memory_target is None
    assert mission.metadata["route_memory_flush"] == "lock_on_refusal"
    assert PLACE_ROUTE_SOURCE not in {goal.source for goal in nav.proposer_bus.poll(now_s=0.0)}
    # Revision-neutral, exactly as in the cases above.
    assert _committed_and_stamped(nav) == (0, 0, 1)
    assert _publish_and_resolve(nav, 1) is not None


def test_rm2_a_real_executive_revision_still_drops_a_stale_waypoint() -> None:
    """P0-C is not weakened by adding a proposer to it.

    The executive commits revision 2 into both sinks (the correction path
    ``brain.executive._notify_revision_committed`` takes). A waypoint stamped 1
    can no longer buffer and can no longer win, and the pipeline's own
    ``_route_memory_stale`` reads the same ledger and refuses to drive it.
    """

    nav, _mission = _navigator_with_a_live_waypoint_chain()
    stale = SE2Goal(
        source=PLACE_ROUTE_SOURCE,
        pose=(8.0, 0.0, 0.0),
        waypoints=((4.0, 0.0), (8.0, 0.0)),
        issued_s=0.0,
        ttl_s=10.0,
        plan_step_id="align_then_translate",
        priority=3,
        task_id=AF2_TASK_ID,
        plan_revision=1,
    )
    nav.proposer_bus.commit_revision(task_id=AF2_TASK_ID, plan_revision=2)
    nav.goal_arbiter.commit_revision(task_id=AF2_TASK_ID, plan_revision=2)

    nav.proposer_bus.publish(stale)
    assert PLACE_ROUTE_SOURCE not in {goal.source for goal in nav.proposer_bus.poll(now_s=0.0)}
    nav.goal_arbiter.set_plan_step("align_then_translate")
    assert nav.goal_arbiter.resolve((stale,), now_s=0.0) is None
    # The pipeline reaches the same verdict from its own side, without waiting
    # for the runtime's restamp.
    assert nav._route_memory_stale() is True


# ---------------------------------------------------------------------------
# AF-2 — FP-memory keying (should-fix 2) and re-anchoring the verify reference
# (should-fix 3). Provenance: scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md.
# ---------------------------------------------------------------------------


def test_a_refuted_wrong_reference_is_not_immediately_recommitted() -> None:
    """AF-2 should-fix 2: the audit's scenario, keyed at BOTH cells.

    Refinement refusals are the dominant refutation class (23 of 24 on the live
    v4s arm) and they used to record only at the ESTIMATE's cell while the
    admission guard consults at the CANDIDATE's — so a wrong reference more than
    a cell or two from its estimate was re-committed and re-refuted until the
    replan ladder was spent (24 refutations, 1 suppression).
    """

    nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
    mission = nav.start("go to the lamppost")
    observation = _observation((0.0, 0.0))
    seen = SemanticCandidate(
        candidate_id="lamp_post_2",
        label="lamppost",
        x=2.0,
        y=0.0,
        confidence=0.98,
        kind="object",
        source="simulator_semantic_camera",
        reachable=True,
        metadata={"radius_m": 0.06},
    )
    wrong = SemanticCandidate(
        candidate_id="lamp_post_1",
        label="lamppost",
        x=6.0,
        y=0.0,
        confidence=0.98,
        kind="object",
        source="simulator_semantic_camera",
        reachable=True,
        metadata={"radius_m": 0.06},
    )
    # The estimator is on lamp_post_2; grounding hands it lamp_post_1, 4 m away.
    assert nav._lock_on_fuse(mission.semantic_goal, observation, seen) is not None
    memory = nav._lock_on_fp_memory
    assert memory.key("lamppost", (2.0, 0.0)) != memory.key("lamppost", (6.0, 0.0))

    refused = nav._commit_semantic_candidate(
        mission.semantic_goal, wrong, observation, grounding_outcome="resolved"
    )
    assert refused is not None
    assert mission.goal is None
    assert nav.lock_on_refutations == 1
    # ONE refutation, TWO cells: the estimate's and the grounded candidate's.
    assert nav.lock_on_refutation_cells == 2
    assert memory.suppressed("lamppost", (2.0, 0.0), view_index=nav._lock_on_view_index)
    assert memory.suppressed("lamppost", (6.0, 0.0), view_index=nav._lock_on_view_index)

    # The gate: re-grounding THE SAME wrong reference is suppressed, not
    # re-committed. Pre-AF-2 the candidate's cell held nothing and this
    # re-committed, burning one rung of the replan ladder per sighting.
    nav._commit_semantic_candidate(
        mission.semantic_goal, wrong, observation, grounding_outcome="resolved"
    )
    assert nav.lock_on_suppressions == 1
    assert mission.goal is None


def test_one_refutation_never_reinforces_a_single_cell_twice() -> None:
    """VS-2's contract is intact: co-located estimate and candidate write once."""

    nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
    mission = nav.start("go to the lamppost")
    target = (2.0, 0.0)
    _drive_to_commit(nav, mission, lambda tick: (_object_item(target),))
    _refute_on_approach(nav, target)
    assert nav.lock_on_refutations == 1
    assert nav.lock_on_refutation_cells == 1
    entries = nav._lock_on_fp_memory.entries()
    assert len(entries) == 1
    assert entries[0].refutations == 1, "a single refutation doubled the TTL horizon"


def _drifted_arms(drift_m: float) -> dict[str, dict]:
    """One committed lamppost, one frame drift, two arms.

    Real frame drift moves the MAP, so a fresh sighting of the same landmark and
    the estimate perception rebuilds from it are both in the drifted frame; the
    stored reference is the only pre-drift thing left. That is modelled here by
    re-acquiring the D2 estimate at the drift instant (``reset()``) — without it
    the Kalman prior lags the jump and BOTH arms refute on the transient, which
    is a property of this static harness's estimator, not of the defect.

    The control arm leaves the session reference behind, i.e. the pre-AF-2
    behaviour, and is what makes this measurement evidence rather than notation.
    """

    committed = (4.0, 0.0)
    drifted = (committed[0] + drift_m, committed[1])
    arms: dict[str, dict] = {}
    for arm in ("translated", "left_behind"):
        nav = _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
        mission = nav.start("go to the lamppost")
        _drive_to_commit(nav, mission, lambda tick: (_object_item(committed),))
        session = nav._lock_on_verify
        assert session is not None
        assert session.reference.center == pytest.approx(committed)
        goal_before = (mission.goal.x, mission.goal.y)
        if arm == "left_behind":
            # The pre-AF-2 behaviour: the goal re-anchors, the reference does not.
            def _leave_behind(dx, dy, _session=session):
                return _session.reference

            session.reanchor = _leave_behind  # type: ignore[method-assign]
        nav._detection_lock_on.reset()
        observation = _observation(
            (0.0, 0.0),
            items=(_object_item(drifted),),
            time_s=30.0,
            lidar_target_xy=drifted,
        )
        moved = nav._reanchor_landmark_goal(observation)
        nav._verify_lock_on_on_approach(observation)
        arms[arm] = {
            "nav": nav,
            "mission": mission,
            "session": session,
            "moved": moved,
            "goal_before": goal_before,
            "drifted": drifted,
        }
    return arms


def test_reanchor_translates_the_verify_reference_in_the_same_transaction() -> None:
    """AF-2 should-fix 3: drift must not refute a healthy commitment.

    Gate: re-anchor by more than ``REGION_DILATION_M``; the next verify tick
    refutes nothing, and the negative-evidence-at-the-true-target
    self-suppression the audit names is pinned dead.
    """

    drift = 2.0
    assert drift > REGION_DILATION_M
    arms = _drifted_arms(drift)
    fixed, control = arms["translated"], arms["left_behind"]
    nav, mission, session = fixed["nav"], fixed["mission"], fixed["session"]
    drifted = fixed["drifted"]

    # One transaction: goal, arrival region, candidate position AND the verify
    # reference all moved by the same displacement.
    assert fixed["moved"] is True
    assert nav.lock_on_reanchors == 1
    assert nav._lock_on_verify is session, "the session was torn down"
    assert session.reference.center == pytest.approx(drifted)
    assert session.reference.landmark_id == "lamp_post_1"
    assert (mission.goal.x, mission.goal.y) != fixed["goal_before"]
    assert tuple(mission.metadata["arrival_goal_region"]["center"]) == pytest.approx(drifted)
    assert tuple(mission.metadata["candidate_position"][:2]) == pytest.approx(drifted)
    # A re-anchor moves WHERE the reference is, never WHAT it is.
    assert session.reference.label == "lamppost"
    assert session.reference.checkpoint_radii_m() == checkpoint_radii_m(
        session.reference.radius_m,
        label="lamppost",
        relation=session.reference.relation,
        arrival_band_m=session.reference.arrival_band_m,
    )

    # The gate itself.
    assert nav.lock_on_refutations == 0
    assert mission.goal is not None
    assert len(nav._lock_on_fp_memory) == 0
    assert not nav._lock_on_fp_memory.suppressed(
        "lamppost", drifted, view_index=nav._lock_on_view_index
    )

    # The control: the pre-AF-2 behaviour refutes a healthy commitment AND
    # writes negative evidence at the TRUE target, self-suppressing it.
    stale_nav, stale_mission = control["nav"], control["mission"]
    assert stale_nav.lock_on_refutations == 1
    assert stale_mission.goal is None
    assert stale_nav._lock_on_fp_memory.suppressed(
        "lamppost", drifted, view_index=stale_nav._lock_on_view_index
    ), "the control was expected to self-suppress the true target"


def test_a_stale_reference_would_have_refuted_the_drifted_target() -> None:
    """The control that makes the drift test evidence rather than notation."""

    from parcel_robot.navigation.lock_on_verify import (
        GroundedReference,
        ReferenceKind,
        refinement_gate,
    )

    stale = GroundedReference(
        landmark_id="lamp_post_1",
        kind=ReferenceKind.OBJECT,
        label="lamppost",
        center=(4.0, 0.0),
        radius_m=0.06,
        relation="near",
    )
    drifted_estimate = (6.0, 0.0)
    assert refinement_gate(stale, drifted_estimate).rejected
    assert refinement_gate(stale.translated(2.0, 0.0), drifted_estimate).accepted


def test_lock_on_without_verify_warns_loudly_but_is_not_refused(caplog) -> None:
    """AF-2 item 5(d): the OLD defective arm stays reachable, and says so.

    Hard-refusing the combination is owner decision-queue item 6 of the Wave-2
    audit, not this card's to take — so the constructor warns and constructs.
    """

    import logging

    with caplog.at_level(logging.WARNING, logger="parcel_robot.navigation.pipeline"):
        defective = _nav(detection_lock_on=True)
    assert defective.detection_lock_on is True
    assert defective.lock_on_verify_on_approach is False, "the arm must stay reachable"
    message = "\n".join(record.getMessage() for record in caplog.records)
    assert "V-E" in message
    assert "lock_on_verify_on_approach" in message
    assert "AUDIT_WAVE2_FABLE" in message

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="parcel_robot.navigation.pipeline"):
        _nav(detection_lock_on=True, lock_on_verify_on_approach=True)
        _nav()
    assert not [r for r in caplog.records if "V-E" in r.getMessage()]
