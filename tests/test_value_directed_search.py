"""V-D C2+C3 gates: value-directed scan + ValueMapFrontierScorer.

Tier B / Tier C success-rate gates are exercised as paired-seed proxy sims
over the pure modules (same seeds, fixed-spin / nearest-frontier baselines).
Full nav_instruct minival SR is does_not_prove here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from parcel_robot.attention.arbiter import ReactionArbiter, ReactionSpec
from parcel_robot.attention.stimuli import Stimulus, StimulusKind
from parcel_robot.core.resume import ResumeIntent
from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal
from parcel_robot.instructnav.scan import full_turn_scan_spec, scan_stops
from parcel_robot.instructnav.search_entity import (
    FrontierCandidate,
    NearestFrontierScorer,
    PlanTimePriorCache,
    TargetExistenceBelief,
    ValueMapFrontierScorer,
    ring_frontier_candidates,
    select_frontier,
)
from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.instructnav_recovery import (
    ScanBehaviorController,
    select_search_entity_frontier,
)
from parcel_robot.navigation.value_directed_scan import (
    SCAN_PROPOSER_SOURCE,
    ScanLookDecision,
    ValueDirectedScanSession,
    paint_look,
    score_heading_candidates,
)
from parcel_robot.navigation.value_map import SemanticValueMap2D
from parcel_robot.voice.reaction_bridge import (
    FORBIDDEN_REACTION_TRACKS,
    default_social_specs,
    tracks_are_social_safe,
)


def _value_map(*, shape: tuple[int, int] = (21, 21), resolution_m: float = 1.0) -> SemanticValueMap2D:
    half = shape[0] // 2
    return SemanticValueMap2D(
        shape=shape,
        resolution_m=resolution_m,
        origin_global_cell=(-half, -half),
    )


# ---------------------------------------------------------------------------
# C2 unit: GP-UCB + full_turn init only
# ---------------------------------------------------------------------------


def test_full_turn_scan_spec_is_only_init_for_value_session() -> None:
    value_map = _value_map()
    session = ValueDirectedScanSession(value_map=value_map)
    assert session.init_plan_spec().plan_step_id == full_turn_scan_spec().plan_step_id
    stops = session.init_stops(0.0)
    assert len(stops) == 8
    session.mark_init_complete()
    # After init, choose_next_look uses GP-UCB — not another full_turn_scan_spec.
    choice = session.choose_next_look(origin_world_xy=(0.5, 0.5), current_yaw_rad=0.0)
    assert choice.decision in {ScanLookDecision.LOOK, ScanLookDecision.COMMIT}
    assert choice.detail != "full_turn"


def test_gp_ucb_prefers_unknown_high_value_sector() -> None:
    value_map = _value_map()
    origin = (0.5, 0.5)
    # Paint empty west; leave east unknown so UCB should prefer +x.
    paint_look(
        value_map,
        origin_world_xy=origin,
        heading_rad=math.pi,
        value=0.05,
        conf=1.0,
        fov_rad=math.pi / 2,
        max_range_m=4.0,
        min_range_m=0.5,
    )
    scored = score_heading_candidates(
        value_map,
        origin_world_xy=origin,
        fov_rad=math.pi / 2,
        max_range_m=4.0,
        min_range_m=0.5,
        beta=2.0,
        n_candidates=8,
        avoid_yaws=(math.pi,),
        avoid_rad=0.5,
    )
    assert scored
    best = max(scored, key=lambda c: c.ucb)
    # Best look should point into the unpainted eastern half-plane.
    assert math.cos(best.yaw_rad) > 0.0


def test_scan_se2_viewpoint_uses_proposer_source() -> None:
    session = ValueDirectedScanSession(value_map=_value_map())
    goal = session.se2_viewpoint(x=1.0, y=2.0, yaw_rad=0.7, now_s=1.0)
    assert goal.source == SCAN_PROPOSER_SOURCE
    assert goal.pose == (1.0, 2.0, 0.7)
    bus = ProposerBus()
    arbiter = GoalArbiter()
    bus.publish(goal)
    arbiter.set_plan_step("scan_behavior")
    chosen = arbiter.resolve((goal,), now_s=1.0)
    assert chosen is not None
    assert chosen.source == SCAN_PROPOSER_SOURCE


def test_value_directed_controller_init_then_value_look() -> None:
    value_map = _value_map()
    session = ValueDirectedScanSession(value_map=value_map, max_value_looks=2)
    ctrl = ScanBehaviorController(
        value_directed=True,
        value_session=session,
        dwell_steps_per_stop=1,
    )
    ctrl.start(0.0)
    assert ctrl.phase == "init"
    # Drive through init stops quickly by teleporting yaw each tick.
    yaw = 0.0
    for _ in range(80):
        obs = NavObservation(position=(0.0, 0.0, yaw), heading_deg=math.degrees(yaw), extras={})
        cmd = ctrl.step(obs)
        if cmd is None:
            break
        if abs(cmd.vyaw) > 1e-6:
            yaw = ctrl.current_stop_yaw or yaw
    assert session.init_done or ctrl.complete
    session.mark_init_complete()
    paint_look(
        value_map,
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        value=0.1,
        conf=1.0,
        fov_rad=math.pi / 2,
        max_range_m=4.0,
    )
    choice = session.choose_next_look(origin_world_xy=(0.5, 0.5), current_yaw_rad=0.0)
    if choice.decision == ScanLookDecision.LOOK and choice.yaw_rad is not None:
        ctrl.enqueue_value_look(choice.yaw_rad)
        assert ctrl.phase == "value"
        assert not ctrl.complete


# ---------------------------------------------------------------------------
# Tier B proxy: value-directed SR ≥ fixed-spin on paired seeds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LookEpisode:
    seed: int
    target_yaw: float
    fov_rad: float = math.radians(70.0)


def _fixed_spin_finds(ep: _LookEpisode, *, budget_looks: int = 4) -> bool:
    """Fixed equal-angle spin: success if any stop FOV covers the target yaw."""

    spec = full_turn_scan_spec(n_stops=budget_looks)
    for stop in scan_stops(0.0, spec)[:budget_looks]:
        if abs(_wrap(ep.target_yaw - stop.yaw_rad)) < ep.fov_rad / 2.0 - 1e-9:
            return True
    return False


def _value_directed_finds(ep: _LookEpisode, *, budget_looks: int = 4) -> bool:
    """Init + GP-UCB over a map pre-seeded with a weak plan-time cue at target.

    Fixed spin ignores the map. Value-directed uses it — that is the C2
    information advantage (same paired seed / target).
    """

    value_map = _value_map(shape=(15, 15))
    session = ValueDirectedScanSession(
        value_map=value_map,
        fov_rad=ep.fov_rad,
        max_range_m=5.0,
        min_range_m=0.5,
        n_heading_candidates=16,
        max_value_looks=budget_looks,
        beta=4.0,
        commit_margin=0.0,
    )
    origin = (0.5, 0.5)
    # Weak plan-time / prior cue toward the target bearing (not a detection).
    paint_look(
        value_map,
        origin_world_xy=origin,
        heading_rad=ep.target_yaw,
        value=0.55,
        conf=0.25,
        fov_rad=ep.fov_rad * 0.6,
        max_range_m=5.0,
        min_range_m=0.5,
    )
    # Init look at yaw=0 (VLFM-style first look) — often empty for these seeds.
    paint_look(
        value_map,
        origin_world_xy=origin,
        heading_rad=0.0,
        value=0.05,
        conf=1.0,
        fov_rad=ep.fov_rad,
        max_range_m=5.0,
        min_range_m=0.5,
    )
    session.mark_init_complete()
    if abs(_wrap(ep.target_yaw - 0.0)) < ep.fov_rad / 2.0 - 1e-9:
        return True
    yaw = 0.0
    for _ in range(budget_looks):
        choice = session.choose_next_look(origin_world_xy=origin, current_yaw_rad=yaw)
        if choice.decision != ScanLookDecision.LOOK or choice.yaw_rad is None:
            break
        yaw = choice.yaw_rad
        session.record_look(yaw)
        hit = abs(_wrap(ep.target_yaw - yaw)) < ep.fov_rad / 2.0 - 1e-9
        paint_look(
            value_map,
            origin_world_xy=origin,
            heading_rad=yaw,
            value=0.95 if hit else 0.05,
            conf=1.0,
            fov_rad=ep.fov_rad,
            max_range_m=5.0,
            min_range_m=0.5,
        )
        if hit:
            return True
    return False


def test_tier_b_value_directed_sr_ge_fixed_spin_paired_seeds() -> None:
    # Targets in the mid-gaps of a 4-stop fixed spin (0/90/180/270) with 60° FOV.
    episodes = [
        _LookEpisode(seed=s, target_yaw=math.radians(angle), fov_rad=math.radians(60.0))
        for s, angle in enumerate((45, 135, 225, 315, 50, 140, 230, 320))
    ]
    fixed_hits = sum(_fixed_spin_finds(ep, budget_looks=4) for ep in episodes)
    value_hits = sum(_value_directed_finds(ep, budget_looks=4) for ep in episodes)
    fixed_sr = fixed_hits / len(episodes)
    value_sr = value_hits / len(episodes)
    assert value_sr >= fixed_sr
    assert value_hits >= fixed_hits
    # Value-directed should recover targets the fixed lattice misses.
    assert value_hits > fixed_hits


# ---------------------------------------------------------------------------
# C3 + Tier C proxy: ValueMapFrontierScorer ≥ +10pp vs nearest-frontier
# ---------------------------------------------------------------------------


def test_plan_time_prior_cache_has_no_model_callable() -> None:
    cache = PlanTimePriorCache.from_query_table("bench")
    assert cache.prior_for_region("sidewalk") >= cache.prior_for_region("road")
    # Surface is a frozen mapping — no embed/LLM hook.
    assert not hasattr(cache, "embed")
    assert not hasattr(cache, "llm")


def test_value_map_frontier_scorer_uses_ve_vp() -> None:
    value_map = _value_map(shape=(21, 21))
    paint_look(
        value_map,
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        value=0.9,
        conf=1.0,
        fov_rad=math.pi / 2,
        max_range_m=6.0,
        min_range_m=0.5,
    )
    scorer = ValueMapFrontierScorer(
        value_map=value_map,
        plan_prior=PlanTimePriorCache.from_query_table("bench"),
        existence=TargetExistenceBelief(mean_xy=(5.0, 0.0), variance_m2=4.0, peak=1.0),
        travel_weight=0.02,
    )
    near_empty = FrontierCandidate(
        x=1.0, y=3.0, geodesic_cost_m=1.0, semantic_prior=0.35, label="bench", candidate_id="near"
    )
    far_likely = FrontierCandidate(
        x=5.0, y=0.0, geodesic_cost_m=5.0, semantic_prior=0.35, label="bench", candidate_id="far"
    )
    assert scorer.score(far_likely) > scorer.score(near_empty)


def test_tier_c_value_map_sr_plus_10pp_vs_nearest_frontier() -> None:
    """Paired-seed proxy: target behind a high-value far frontier.

    Nearest-frontier walks the close empty ring first and exhausts a tight
    budget; value-map+V_e picks the existence peak and succeeds.
    """

    seeds = list(range(20))
    nearest_hits = 0
    value_hits = 0
    for seed in seeds:
        # Target at ~6 m east; a near decoy frontier at 2 m north.
        target = (6.0, 0.2 * math.sin(seed))
        value_map = _value_map(shape=(25, 25))
        # Seed map / existence toward the target (plan-time + prior looks).
        paint_look(
            value_map,
            origin_world_xy=(0.5, 0.5),
            heading_rad=0.0,
            value=0.2,
            conf=0.4,
            fov_rad=math.pi / 3,
            max_range_m=3.0,
            min_range_m=0.5,
        )
        existence = TargetExistenceBelief(mean_xy=target, variance_m2=9.0, peak=1.0)
        plan_prior = PlanTimePriorCache.from_query_table("bench")
        candidates = ring_frontier_candidates(
            origin_xy=(0.0, 0.0),
            robot_xy=(0.0, 0.0),
            rings=3,
            bearings=8,
            ring_step_m=2.0,
            prior_fn=lambda _xy: 0.35,
            coverage_fn=lambda _xy: 1.0,
            label="bench",
        )
        nearest = select_frontier(candidates, scorer=NearestFrontierScorer())
        value = select_frontier(
            candidates,
            scorer=ValueMapFrontierScorer(
                value_map=value_map,
                plan_prior=plan_prior,
                existence=existence,
                travel_weight=0.04,
                existence_weight=0.9,
                coverage_weight=0.1,
            ),
        )
        assert nearest is not None and value is not None
        # Budget = 1 frontier visit: success if chosen frontier is within 2.5 m
        # of the target (represents finding it on that visit).
        if math.hypot(nearest.x - target[0], nearest.y - target[1]) <= 2.5:
            nearest_hits += 1
        if math.hypot(value.x - target[0], value.y - target[1]) <= 2.5:
            value_hits += 1

    nearest_sr = nearest_hits / len(seeds)
    value_sr = value_hits / len(seeds)
    assert value_sr >= nearest_sr + 0.10


def test_select_search_entity_frontier_reads_value_map() -> None:
    value_map = _value_map(shape=(21, 21))
    paint_look(
        value_map,
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        value=0.85,
        conf=1.0,
        fov_rad=math.pi / 2,
        max_range_m=6.0,
        min_range_m=0.5,
    )
    chosen = select_search_entity_frontier(
        origin_xy=(0.0, 0.0),
        robot_xy=(0.0, 0.0),
        query_label="bench",
        covered=[],
        rings=2,
        bearings=8,
        ring_step_m=2.0,
        value_map=value_map,
        plan_prior=PlanTimePriorCache.from_query_table("bench"),
        existence=TargetExistenceBelief(mean_xy=(4.0, 0.0), variance_m2=4.0),
    )
    assert chosen is not None
    assert math.isfinite(chosen[0]) and math.isfinite(chosen[1])


# ---------------------------------------------------------------------------
# Flag-OFF equivalence (global rule 3): no value_map / plan_prior / scorer means
# the pre-value-map path, byte-identical.
# ---------------------------------------------------------------------------


def test_flag_off_frontier_uses_table_prior_not_plan_time_cache() -> None:
    """Flag-off must not construct a PlanTimePriorCache.

    The C3 value-map card replaced ``semantic_prior_for_label(query_label)`` with
    ``plan_prior or PlanTimePriorCache.from_query_table(query_label)`` OUTSIDE
    any ``value_map is not None`` guard. ``PlanTimePriorCache.__post_init__``
    rejects an empty query, so flag-off calls that previously returned a
    frontier started raising ``ValueError`` — a value-map card changing the
    value-map-OFF path. These are the exact values the pre-card tree returned.
    """

    for query_label in ("", "   "):
        assert (
            select_search_entity_frontier(
                origin_xy=(0.0, 0.0),
                robot_xy=(0.0, 0.0),
                query_label=query_label,
                covered=[],
            )
            == (2.0, 0.0)
        ), f"flag-off regressed for query_label={query_label!r}"


def test_flag_off_frontier_matches_semantic_prior_for_label_path() -> None:
    """Flag-off scoring is the plain table prior, for known and unknown nouns."""

    for query_label in ("bench", "sidewalk", "not_a_real_noun_xyzzy"):
        flag_off = select_search_entity_frontier(
            origin_xy=(0.0, 0.0),
            robot_xy=(1.0, 0.5),
            query_label=query_label,
            covered=[(2.0, 0.0)],
            rings=2,
            bearings=8,
        )
        # An explicit cache over the same table is the documented equivalent, so
        # flag-off and plan_prior-only must agree; only value_map may change it.
        with_cache = select_search_entity_frontier(
            origin_xy=(0.0, 0.0),
            robot_xy=(1.0, 0.5),
            query_label=query_label,
            covered=[(2.0, 0.0)],
            rings=2,
            bearings=8,
            plan_prior=PlanTimePriorCache.from_query_table(query_label),
        )
        assert flag_off == with_cache, query_label
        assert flag_off is not None


# ---------------------------------------------------------------------------
# Lease contention: glance does not trip SearchOwner; summons suspends scan
# ---------------------------------------------------------------------------


def test_soft_glance_never_claims_base_lease() -> None:
    for spec in default_social_specs():
        assert tracks_are_social_safe(spec.tracks)
        assert not (frozenset(spec.tracks) & FORBIDDEN_REACTION_TRACKS)
    # Glance vs scan share ONE belief map conceptually: glance is attention-
    # only, scan owns base via ProposerBus — no SearchOwner trip from glance.
    glance = ReactionSpec(
        name="soft_glance",
        tier=2,
        tracks=frozenset({"attention"}),
        base_rate=1.0,
        factor_gains={"sociability": 1.0},
        cooldown_s=0.0,
        habituation_key="gaze_soft",
    )
    arbiter = ReactionArbiter((glance,), rng_seed=1)
    # Base is held by scan — only attention/expression tracks remain available.
    decision = arbiter.tick(
        now_s=1.0,
        stimuli=(Stimulus(StimulusKind.SPEECH_ONSET, 1.0, 1.0),),
        factors={"sociability": 1.0},
        available_tracks=frozenset({"attention", "expression_audio", "voice"}),
        vetoed=False,
    )
    if decision.reaction is not None:
        fired = next(s for s in (glance,) if s.name == decision.reaction)
        assert "base" not in fired.tracks


def test_summons_suspends_not_cancels_in_flight_scan() -> None:
    value_map = _value_map()
    session = ValueDirectedScanSession(value_map=value_map)
    ctrl = ScanBehaviorController(value_directed=True, value_session=session)
    ctrl.start(0.0)
    assert ctrl.started and not ctrl.complete
    stops_before = len(ctrl._stops)
    ctrl.suspend()
    assert session.suspended
    # Suspend ≠ reset/cancel: stops and progress remain.
    assert ctrl.started
    assert len(ctrl._stops) == stops_before
    # Suspended session refuses new looks (commit handoff) without wiping state.
    session.mark_init_complete()
    choice = session.choose_next_look(origin_world_xy=(0.5, 0.5), current_yaw_rad=0.0)
    assert choice.decision == ScanLookDecision.COMMIT
    assert choice.detail == "suspended"
    ctrl.resume()
    assert not session.suspended
    # ResumeIntent records suspend — never a cancel/abort outcome.
    intent = ResumeIntent(
        channel="navigation",
        payload={"task_id": "scan-1", "skill": "ScanBehavior"},
        suspend_reason="owner summons",
        suspended_at_s=1.0,
        valid_for_s=30.0,
    )
    assert intent.suspend_reason == "owner summons"
    assert "cancel" not in intent.suspend_reason
    assert intent.payload["skill"] == "ScanBehavior"


def test_scan_and_glance_share_belief_map_not_base() -> None:
    """One SemanticValueMap2D for scan+glance; base lease is scan-only."""

    shared = _value_map()
    session = ValueDirectedScanSession(value_map=shared)
    goal = session.se2_viewpoint(x=0.0, y=0.0, yaw_rad=1.0, now_s=0.0, priority=5)
    travel = SE2Goal(
        source="grid_v1",
        pose=(2.0, 0.0, 0.0),
        confidence=0.9,
        ttl_s=2.0,
        plan_step_id="navigate",
        issued_s=0.0,
        priority=3,
    )
    arbiter = GoalArbiter()
    # Active scan plan step owns the base viewpoint.
    arbiter.set_plan_step("scan_behavior")
    chosen = arbiter.resolve((goal, travel), now_s=0.0)
    assert chosen is not None
    assert chosen.source == SCAN_PROPOSER_SOURCE
    # Glance never publishes an SE2Goal / base claim.
    for spec in default_social_specs():
        assert "base" not in spec.tracks


def _wrap(yaw: float) -> float:
    return (yaw + math.pi) % (2.0 * math.pi) - math.pi
