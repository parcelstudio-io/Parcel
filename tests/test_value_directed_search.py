"""V-D C2+C3 gates: value-directed scan + ValueMapFrontierScorer.

Tier B / Tier C success-rate gates are exercised as paired-seed proxy sims
over the pure modules (same seeds, fixed-spin / nearest-frontier baselines).
Full nav_instruct minival SR is does_not_prove here.
"""

from __future__ import annotations

import math
import random
import struct
from dataclasses import dataclass
from pathlib import Path

from parcel_robot.attention.arbiter import ReactionArbiter, ReactionSpec
from parcel_robot.attention.stimuli import Stimulus, StimulusKind
from parcel_robot.core.resume import ResumeIntent
from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal
from parcel_robot.instructnav.scan import full_turn_scan_spec, scan_stops
from parcel_robot.instructnav.search_entity import (
    FrontierCandidate,
    NearestFrontierScorer,
    PlanTimePriorCache,
    SemanticMinusGeodesicScorer,
    TargetExistenceBelief,
    ValueMapFrontierScorer,
    ring_frontier_candidates,
    select_frontier,
)
from parcel_robot.navigation import DirectiveNavigator, ModelRegistry, PlaceGrounder
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
    # A weak but REAL sighting toward the target bearing. VS-5 note: under
    # VS-3's contract ``is_evidence`` is decided by the MATCH (did it clear the
    # SigLIP operating point?) while the painted VALUE is match x observation
    # confidence — so an unsure look at the right thing is exactly this: a
    # genuine evidence paint whose value is low. Without ``is_evidence`` this
    # would be a MISS, and the empty-map contract would (correctly) make the
    # session commit instead of looking again.
    paint_look(
        value_map,
        origin_world_xy=origin,
        heading_rad=ep.target_yaw,
        value=0.55,
        conf=0.25,
        fov_rad=ep.fov_rad * 0.6,
        max_range_m=5.0,
        min_range_m=0.5,
        is_evidence=True,
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
            is_evidence=hit,
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
    # VS-5: a 0.9 paint is a sighting, so it is an EVIDENCE paint. Without that
    # the scorer delegates to the flag-off scorer and V_e/V_p are not consulted
    # at all — which is the whole point of the empty-map contract.
    paint_look(
        value_map,
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        value=0.9,
        conf=1.0,
        fov_rad=math.pi / 2,
        max_range_m=6.0,
        min_range_m=0.5,
        is_evidence=True,
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
        # Seed map / existence toward the target: a real (weak) sighting, which
        # is what makes the existence belief admissible at all. VS-5's empty-map
        # contract is explicit that V_e must NOT fire on an evidence-free map —
        # that firing is the measured V-D no-op (record §2.1(2), "the empty-map
        # ValueMapFrontierScorer is NOT the baseline scorer ... the 0-flip tie
        # was accidental"). The paired-seed claim below is therefore a claim
        # about a map with evidence in it, which is the only claim it can be.
        paint_look(
            value_map,
            origin_world_xy=(0.5, 0.5),
            heading_rad=0.0,
            value=0.2,
            conf=0.4,
            fov_rad=math.pi / 3,
            max_range_m=3.0,
            min_range_m=0.5,
            is_evidence=True,
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
        is_evidence=True,  # VS-5: an evidence-free map delegates and reads nothing
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


# ---------------------------------------------------------------------------
# VS-5 — empty-map delegation: evidence_count == 0 IS the flag-off path
#
# The measured V-D defect was a value map that ran EMPTY (record §2.1(2)): the
# painter marked every scanned cone with a floor instead of evidence, and the
# empty-map ValueMapFrontierScorer is NOT the baseline scorer (coverage + V_e +
# prior-blend all fire on an empty belief), so "meets baseline" was an accident
# rather than a property. These cells make it a property.
# ---------------------------------------------------------------------------


def _paint_misses(value_map: SemanticValueMap2D, count: int, *, origin=(0.5, 0.5)) -> None:
    """``count`` looks that found nothing — value 0.0, full look confidence."""

    for index in range(count):
        paint_look(
            value_map,
            origin_world_xy=origin,
            heading_rad=-math.pi + (2.0 * math.pi * index) / max(count, 1),
            value=0.0,
            conf=1.0,
            fov_rad=math.radians(70.0),
            max_range_m=6.0,
            min_range_m=0.5,
        )


def _ring(seed: int) -> tuple[FrontierCandidate, ...]:
    rng = random.Random(seed)
    return ring_frontier_candidates(
        origin_xy=(rng.uniform(-2.0, 2.0), rng.uniform(-2.0, 2.0)),
        robot_xy=(rng.uniform(-2.0, 2.0), rng.uniform(-2.0, 2.0)),
        rings=3,
        bearings=12,
        ring_step_m=2.0,
        prior_fn=lambda _xy: rng.uniform(0.0, 1.0),
        coverage_fn=lambda _xy: rng.uniform(0.0, 1.0),
        label="bench",
    )


def test_empty_map_scorer_delegates_to_the_flag_off_scorer_object() -> None:
    """The delegate is the flag-off scorer OBJECT, not a copy of its arithmetic."""

    scorer = ValueMapFrontierScorer(
        value_map=_value_map(),
        plan_prior=PlanTimePriorCache.from_query_table("bench"),
        travel_weight=0.06,
        coverage_weight=0.45,
    )
    delegate = scorer.baseline_scorer()
    assert isinstance(delegate, SemanticMinusGeodesicScorer)
    # ``select_frontier`` builds exactly this object when no scorer is passed.
    assert delegate == SemanticMinusGeodesicScorer(
        travel_weight=0.06, prior_weight=1.0, coverage_weight=0.45
    )
    assert scorer.has_evidence() is False


def test_evidence_free_map_scores_are_float_identical_to_the_baseline() -> None:
    """struct.pack identity, not a tolerance — over misses, not just an empty map."""

    value_map = _value_map(shape=(41, 41))
    _paint_misses(value_map, 24)
    assert value_map.evidence_count == 0
    scorer = ValueMapFrontierScorer(
        value_map=value_map,
        plan_prior=PlanTimePriorCache.from_query_table("bench"),
        existence=TargetExistenceBelief(mean_xy=(6.0, 0.0), variance_m2=9.0),
        travel_weight=0.06,
        coverage_weight=0.45,
    )
    baseline = SemanticMinusGeodesicScorer(
        travel_weight=0.06, prior_weight=1.0, coverage_weight=0.45
    )
    compared = 0
    for seed in range(30):
        for candidate in _ring(seed):
            got = scorer.score(candidate)
            want = baseline.score(candidate)
            assert struct.pack("<d", got) == struct.pack("<d", want)
            compared += 1
    assert compared >= 30 * 36


def test_one_evidence_paint_is_what_turns_the_scorer_on() -> None:
    """The predicate is EVIDENCE, not paint count: 24 misses change nothing."""

    value_map = _value_map(shape=(41, 41))
    _paint_misses(value_map, 24)
    scorer = ValueMapFrontierScorer(
        value_map=value_map,
        plan_prior=PlanTimePriorCache.from_query_table("bench"),
        existence=TargetExistenceBelief(mean_xy=(6.0, 0.0), variance_m2=9.0),
    )
    candidates = _ring(0)
    delegated = [scorer.score(c) for c in candidates]

    paint_look(
        value_map,
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        value=0.95,
        conf=1.0,
        fov_rad=math.radians(70.0),
        max_range_m=6.0,
        min_range_m=0.5,
        is_evidence=True,
    )
    assert value_map.evidence_count == 1
    directed = [scorer.score(c) for c in candidates]
    assert directed != delegated
    assert scorer.has_evidence() is True


def _frontier_pair(seed: int, *, misses: int) -> tuple[tuple | None, tuple | None]:
    rng = random.Random(1000 + seed)
    origin = (rng.uniform(-4.0, 4.0), rng.uniform(-4.0, 4.0))
    robot = (rng.uniform(-4.0, 4.0), rng.uniform(-4.0, 4.0))
    covered = [(rng.uniform(-4.0, 4.0), rng.uniform(-4.0, 4.0)) for _ in range(3)]
    value_map = _value_map(shape=(41, 41))
    if misses:
        _paint_misses(value_map, misses, origin=robot)
    assert value_map.evidence_count == 0
    directed = select_search_entity_frontier(
        origin_xy=origin,
        robot_xy=robot,
        query_label="bench",
        covered=list(covered),
        value_map=value_map,
        plan_prior=PlanTimePriorCache.from_query_table("bench"),
    )
    flag_off = select_search_entity_frontier(
        origin_xy=origin,
        robot_xy=robot,
        query_label="bench",
        covered=list(covered),
    )
    return directed, flag_off


def test_untouched_map_frontier_selection_is_float_identical_to_flag_off() -> None:
    """The card's gate-(1) shape: painting disabled ⇒ the whole selection is flag-off's.

    With nothing painted, ``unknown_fraction`` is 1.0 for every candidate, which
    is the same number the flag-off novelty test stamps, and the scorer
    delegates — so the callee agrees to the bit as well as the scorer.
    """

    for seed in range(25):
        directed, flag_off = _frontier_pair(seed, misses=0)
        assert (directed is None) == (flag_off is None)
        if directed is not None and flag_off is not None:
            assert struct.pack("<dd", *directed) == struct.pack("<dd", *flag_off)


def test_misses_move_the_callee_which_is_why_the_wiring_gates_at_the_call_site() -> None:
    """Honest limit of the scorer-level delegation, pinned rather than assumed.

    ``select_search_entity_frontier`` stamps ``coverage_gain`` from the map's
    ``unknown_fraction`` whenever it is HANDED a map, and a map full of MISSES is
    no longer unknown — a candidate field the scorer never sees and therefore
    cannot delegate away. So scorer-level delegation alone is not sufficient for
    "evidence_count == 0 ⇒ bit-identical"; the pipeline additionally passes
    ``value_map=None`` on that predicate, which is not an approximation of the
    flag-off call but the same call
    (``test_pipeline_frontier_is_the_flag_off_call_until_evidence_arrives``).
    """

    moved = 0
    for seed in range(25):
        directed, flag_off = _frontier_pair(seed, misses=12)
        if directed is not None and flag_off is not None and directed != flag_off:
            moved += 1
    assert moved > 0


def test_empty_map_scan_session_commits_instead_of_looking_again() -> None:
    """C2 half of the contract: no evidence ⇒ exactly the baseline full turn."""

    value_map = _value_map(shape=(41, 41))
    _paint_misses(value_map, 16)
    session = ValueDirectedScanSession(value_map=value_map)
    session.mark_init_complete()
    choice = session.choose_next_look(origin_world_xy=(0.5, 0.5), current_yaw_rad=0.0)
    assert choice.decision is ScanLookDecision.COMMIT
    assert choice.yaw_rad is None
    assert choice.detail == "empty_map_no_evidence"

    paint_look(
        value_map,
        origin_world_xy=(0.5, 0.5),
        heading_rad=math.pi / 2.0,
        value=0.95,
        conf=1.0,
        fov_rad=math.radians(70.0),
        max_range_m=6.0,
        min_range_m=0.5,
        is_evidence=True,
    )
    engaged = session.choose_next_look(origin_world_xy=(0.5, 0.5), current_yaw_rad=0.0)
    assert engaged.decision is ScanLookDecision.LOOK
    assert engaged.yaw_rad is not None


# ---------------------------------------------------------------------------
# VS-5 — the wiring: evidence-fed painting, miss painting, delegation, telemetry
# ---------------------------------------------------------------------------

MODELS = Path(__file__).resolve().parents[1] / "configs" / "navigation" / "models"

#: Substrings ``evals/nav_instruct/runner.py`` keys on when it reads a step
#: note. The telemetry suffix must introduce none of them, and must not displace
#: the ``semantic_search_scan`` PREFIX test.
RUNNER_NOTE_KEYS = ("frontier", "semantic_target_not_found", "scan_for_target")


def _nav(**flags: bool) -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        **flags,
    )


def _tree_item(xy: tuple[float, float]) -> dict:
    return {
        "id": "tree_1",
        "label": "tree",
        "kind": "object",
        "position": [xy[0], xy[1], 0.0],
        "confidence": 0.98,
        "reachable": True,
        "metadata": {"radius_m": 0.35},
    }


def _obs(
    robot_xy: tuple[float, float] = (0.0, 0.0),
    *,
    items: tuple[dict, ...] = (),
    time_s: float = 0.0,
) -> NavObservation:
    return NavObservation(
        position=(robot_xy[0], robot_xy[1], 0.0),
        heading_deg=0.0,
        extras={
            "collision": False,
            "perception_fresh": True,
            "time_s": time_s,
            "semantic_candidates": list(items),
        },
    )


def _drive(nav: DirectiveNavigator, ticks: int, items=()) -> list:
    mission = nav.start("walk to the tree")
    assert mission.status == "searching"
    return [
        nav.step(_obs(items=tuple(items), time_s=0.1 * tick)) for tick in range(ticks)
    ]


def test_value_directed_flag_defaults_off_and_builds_no_map() -> None:
    off = _nav()
    assert off.value_directed_search is False
    assert off.semantic_value_map is None
    assert off._value_evidence is None
    on = _nav(value_directed_search=True)
    assert on.value_directed_search is True
    assert on.semantic_value_map is not None
    assert on._value_evidence is not None


def test_a_look_at_nothing_paints_a_miss_and_never_counts_as_evidence() -> None:
    """The replaced painter's 0.15 scanned-cone floor is gone."""

    nav = _nav(value_directed_search=True)
    _drive(nav, 12)
    assert nav.value_paints == 12
    assert nav.value_miss_paints == 12
    assert nav.value_evidence_paints == 0
    assert nav.semantic_value_map is not None
    assert nav.semantic_value_map.evidence_count == 0
    assert nav.value_cells_painted > 0
    # Every covered cell is at 0.0, not at the retired 0.15 / 0.05 floors.
    resolution = nav.semantic_value_map.resolution_m
    covered = [
        cell
        for cell in (
            (int(x), int(y))
            for x in range(int(6.0 / resolution))
            for y in range(-2, 3)
        )
        if nav.semantic_value_map.read(cell)[1] > 0.0
    ]
    assert covered
    for cell in covered:
        assert nav.semantic_value_map.read(cell)[0] == 0.0


def test_a_look_that_matches_the_query_is_evidence_and_engages_the_path() -> None:
    nav = _nav(value_directed_search=True)
    _drive(nav, 6, items=(_tree_item((3.0, 0.0)),))
    assert nav.semantic_value_map is not None
    assert nav.semantic_value_map.evidence_count > 0
    assert nav.value_evidence_paints > 0
    assert nav._value_map_has_evidence() is True


def test_evidence_is_mission_scoped_and_a_fresh_start_empties_the_map() -> None:
    nav = _nav(value_directed_search=True)
    _drive(nav, 6, items=(_tree_item((3.0, 0.0)),))
    assert nav.semantic_value_map is not None
    assert nav.semantic_value_map.evidence_count > 0
    nav.start("walk to the tree")
    assert nav.semantic_value_map.evidence_count == 0
    assert nav._value_evidence is not None
    assert nav._value_evidence.evidence_count == 0
    assert nav._value_map_has_evidence() is False


def test_pipeline_frontier_is_the_flag_off_call_until_evidence_arrives() -> None:
    """The delegation predicate, at the seam the pipeline actually calls.

    A map full of misses (evidence_count 0) must produce the SAME frontier point
    the flag-off navigator produces — bit for bit — and the counter must record
    that the delegated branch was the one taken.
    """

    on = _nav(value_directed_search=True)
    off = _nav()
    on.start("walk to the tree")
    off.start("walk to the tree")
    for tick in range(40):
        on.step(_obs(items=(), time_s=0.1 * tick))
    assert on.semantic_value_map is not None
    assert on.semantic_value_map.evidence_count == 0
    assert on.value_miss_paints >= 40

    for seed in range(20):
        rng = random.Random(77 + seed)
        origin = (rng.uniform(-5.0, 5.0), rng.uniform(-5.0, 5.0))
        robot = (rng.uniform(-5.0, 5.0), rng.uniform(-5.0, 5.0))
        chosen_on = on._select_semantic_frontier(origin, robot, query_label="tree")
        chosen_off = off._select_semantic_frontier(origin, robot, query_label="tree")
        assert (chosen_on is None) == (chosen_off is None)
        if chosen_on is not None and chosen_off is not None:
            assert struct.pack("<dd", *chosen_on) == struct.pack("<dd", *chosen_off)
    assert on.value_baseline_frontiers == 20
    assert on.value_directed_frontiers == 0


def test_evidence_switches_the_frontier_onto_the_value_directed_branch() -> None:
    nav = _nav(value_directed_search=True)
    nav.start("walk to the tree")
    for tick in range(6):
        nav.step(_obs(items=(_tree_item((3.0, 0.0)),), time_s=0.1 * tick))
    assert nav._value_map_has_evidence() is True
    nav._select_semantic_frontier((0.0, 0.0), (0.0, 0.0), query_label="tree")
    assert nav.value_directed_frontiers == 1
    assert nav.value_baseline_frontiers == 0


def test_flag_off_navigator_never_paints_and_never_stamps_telemetry() -> None:
    off = _nav()
    commands = _drive(off, 12, items=(_tree_item((3.0, 0.0)),))
    assert off.value_paints == 0
    assert off.value_evidence_paints == 0
    assert all("value_map=" not in (cmd.note or "") for cmd in commands)


def test_telemetry_rides_the_note_without_touching_the_runners_own_keys() -> None:
    nav = _nav(value_directed_search=True)
    commands = _drive(nav, 12, items=(_tree_item((3.0, 0.0)),))
    stamped = [cmd for cmd in commands if "value_map=" in (cmd.note or "")]
    assert stamped
    for cmd in stamped:
        assert cmd.stop is False  # terminal notes become the runner's ``reason``
        head, _, suffix = (cmd.note or "").partition("|value_map=")
        assert suffix
        for key in RUNNER_NOTE_KEYS:
            assert key not in f"value_map={suffix}"
        # The prefix the runner counts scan steps by is preserved verbatim.
        if head.startswith("semantic_search_scan"):
            assert (cmd.note or "").startswith("semantic_search_scan")
    last = stamped[-1].note or ""
    body = last.split("|value_map=")[1]
    counters = dict(kv.split("=") for kv in body.split(","))
    assert set(counters) == {
        "evidence",
        "paints",
        "hits",
        "misses",
        "cells",
        "directed",
        "delegated",
    }
    assert int(counters["evidence"]) == nav.semantic_value_map.evidence_count
    assert int(counters["paints"]) == nav.value_paints


# ---------------------------------------------------------------------------
# AF-2 — the scan-viewpoint side channel (audit should-fix 4)
#
# Provenance: scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md — "document the
# scan-viewpoint side channel (and verify it cannot perturb a zero-evidence
# episode's decisions)". Under ``value_directed_search`` the scan path does two
# things the flag-off path does not: it PUBLISHES an SE2 viewpoint into the
# shared ProposerBus and latches the GoalArbiter's active plan step
# (``_publish_scan_viewpoint``), and it may ENQUEUE a value look that changes
# where the body points (``choose_next_look`` ⇒ LOOK). The first is state the
# empty-map delegation does not gate; the second is gated by C2.
# ---------------------------------------------------------------------------


def test_the_scan_viewpoint_side_channel_cannot_steer_an_evidence_free_episode() -> None:
    """Two mechanisms, both shown inert while ``evidence_count == 0``."""

    nav = _nav(value_directed_search=True)
    commands = _drive(nav, 40, items=())
    assert commands
    assert nav.semantic_value_map is not None
    assert nav.semantic_value_map.evidence_count == 0
    assert nav.value_miss_paints > 0, "the arm never painted, so nothing is being shown"

    # (1) The value LOOK — the only thing that can move the body — is never
    # requested: C2 returns COMMIT while the map holds no evidence.
    decision = nav.mission.metadata.get("scan_look_decision")
    assert decision in {None, ScanLookDecision.COMMIT.value}, decision

    # (2) The published viewpoint is real state in the SHARED buffers ...
    buffered = {goal.source for goal in nav.proposer_bus.poll(now_s=0.0)}
    assert SCAN_PROPOSER_SOURCE in buffered, "the side channel is not even exercised"
    # ... and it cannot reach a decision: every resolve site in the pipeline
    # sets its own plan step and resolves over a SINGLE-element tuple it has
    # just built, so neither the arbiter's latch nor the bus buffer is read.
    source = Path(DirectiveNavigator.__module__.replace(".", "/") + ".py")
    text = (Path(__file__).resolve().parents[1] / "src" / source).read_text(encoding="utf-8")
    resolves = [line.strip() for line in text.splitlines() if ".goal_arbiter.resolve(" in line]
    assert resolves, "no resolve site found — the guard below would be vacuous"
    for line in resolves:
        assert "((" in line or "(proposed,)" in line or "(chosen,)" in line, line
    assert ".proposer_bus.poll(" not in text, (
        "the pipeline started polling the shared bus; the scan viewpoint can now "
        "reach a decision and the empty-map delegation no longer covers it"
    )


def test_one_evidence_paint_turns_the_scan_look_channel_on() -> None:
    """The control: the side channel is inert by evidence, not by construction."""

    value_map = _value_map(shape=(41, 41))
    _paint_misses(value_map, 16)
    session = ValueDirectedScanSession(value_map=value_map)
    session.mark_init_complete()
    assert session.choose_next_look(
        origin_world_xy=(0.5, 0.5), current_yaw_rad=0.0
    ).decision is ScanLookDecision.COMMIT
    paint_look(
        value_map,
        origin_world_xy=(0.5, 0.5),
        heading_rad=math.pi / 2.0,
        value=0.95,
        conf=1.0,
        fov_rad=math.radians(70.0),
        max_range_m=6.0,
        min_range_m=0.5,
        is_evidence=True,
    )
    assert session.choose_next_look(
        origin_world_xy=(0.5, 0.5), current_yaw_rad=0.0
    ).decision is ScanLookDecision.LOOK
