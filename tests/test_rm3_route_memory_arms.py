"""RM-3 — the taught-prior-route substrate, the paired estimator, the seams.

Card ``scrum/20260811/task_2/SLAM_M_PLAN.md`` (r2), Wave 3, RM-3.

Commit-tier only: everything here is either pure, or costs one world
construction. The sweeps themselves live in
``evals/nav_instruct/run_route_memory_arms.py`` and are nightly-or-manual by
design — a 60-cell paired arm is ~20 minutes of simulation and has no business
in a commit gate.

Every property test carries a **seeded-failure companion**: a hand-built
artefact that violates the property, fed to the SAME checker, which must reject
it. A property test whose checker cannot fail is a property test that proves
nothing.
"""

from __future__ import annotations

import inspect
import math

import pytest

from evals.nav_instruct.generator import (
    EPISODE_SETS,
    VISIBILITY_MAX_RANGE_M,
)
from evals.nav_instruct.route_memory_cells import (
    OBSTACLE_STOP_FLOOR_M,
    ROUTE_MEMORY_MIN_DETOUR_M,
    ROUTE_MEMORY_N_CELLS,
    ROUTE_MEMORY_REACH_M,
    ROUTE_MEMORY_SET_NAME,
    TEACH_MIN_CLEARANCE_M,
    TEACH_WAYPOINT_TOLERANCE_M,
    TaughtRoutePreDrive,
    _polyline_length,
    cells_digest,
    generate_route_memory_cells,
    taught_route_of,
    teach_tick_budget,
    truth_occupancy,
)
from evals.nav_instruct.run_route_memory_arms import (
    BUDGET_POLICY,
    mcnemar_exact,
    pair_arms,
    path_fidelity,
)
from evals.nav_instruct.runner import (
    ALLOWED_NAVIGATOR_OVERRIDES,
    NavInstructRunner,
    route_memory_record,
    scaled_step_budget,
)
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.route_memory.place_graph import (
    DEFAULT_ATTACH_RADIUS_M,
    DEFAULT_KEYFRAME_SPACING_M,
)

# Generation scans every (target, start) pair against the world's occupancy;
# ~16 s once, and then every cell-set test is a table read.
_CELLS = None


def cells():
    global _CELLS
    if _CELLS is None:
        _CELLS = generate_route_memory_cells()
    return _CELLS


def cell_payload(episode):
    return episode.placement_overrides["route_memory_cell"]


# ---------------------------------------------------------------------------
# The estimator — the pre-registered threshold sits between two attainable
# values, so this is the one place a wrong estimator would silently pass a gate.
# ---------------------------------------------------------------------------


def test_exact_mcnemar_reproduces_the_hand_computable_values() -> None:
    # 2 * P(X >= 6 | n=6, p=0.5) = 2/64.
    assert mcnemar_exact(6, 0) == pytest.approx(2.0 / 64.0)
    assert mcnemar_exact(7, 0) == pytest.approx(2.0 / 128.0)
    # n=9, P(X>=8) = (9 + 1)/512.
    assert mcnemar_exact(8, 1) == pytest.approx(2.0 * 10.0 / 512.0)
    assert mcnemar_exact(9, 1) == pytest.approx(2.0 * 11.0 / 1024.0)
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(1, 1) == 1.0


def test_the_pre_registered_threshold_is_read_literally() -> None:
    """0.031 rejects (6, 0) and admits (7, 0). Stated, so nobody rounds it."""

    threshold = 0.031
    assert mcnemar_exact(6, 0) > threshold
    assert mcnemar_exact(7, 0) <= threshold
    # ...and "6 net flips" alone is not the gate: (8, 2) is 6 net and fails.
    assert 8 - 2 >= 6
    assert mcnemar_exact(8, 2) > threshold


def test_exact_mcnemar_is_symmetric_so_a_direction_error_cannot_hide() -> None:
    for b, c in ((7, 0), (9, 1), (4, 2)):
        assert mcnemar_exact(b, c) == mcnemar_exact(c, b)


def test_seeded_a_chi_square_style_estimator_would_pass_the_failing_split() -> None:
    """The companion: why the estimator has to be the exact one.

    The uncorrected chi-square statistic for (6, 0) is 6.0, p = 0.0143 — under
    the 0.031 bar the card pre-registers, while the exact answer (0.03125) is
    over it. Same data, opposite verdict.
    """

    b, c = 6, 0
    chi_square = (b - c) ** 2 / (b + c)
    assert chi_square == pytest.approx(6.0)
    # 1 - CDF of chi2(1) at 6.0, computed from erfc to avoid a scipy dependency.
    approx_p = math.erfc(math.sqrt(chi_square / 2.0))
    assert approx_p < 0.031 < mcnemar_exact(b, c)


# ---------------------------------------------------------------------------
# The allowlist amendment (enumerated)
# ---------------------------------------------------------------------------


def test_the_runner_allowlist_carries_route_memory() -> None:
    assert "route_memory" in ALLOWED_NAVIGATOR_OVERRIDES
    # RM-3 added exactly one name; the four pre-existing ones are untouched.
    assert {
        "value_directed_search",
        "detection_lock_on",
        "person_aware_nav",
        "lock_on_verify_on_approach",
    } <= ALLOWED_NAVIGATOR_OVERRIDES
    assert len(ALLOWED_NAVIGATOR_OVERRIDES) == 5


def test_the_flag_defaults_to_off_inside_the_navigator() -> None:
    """The whole reason the allowlist may grow: naming it changes nothing."""

    assert (
        inspect.signature(DirectiveNavigator.__init__).parameters["route_memory"].default
        is False
    )


def test_an_unknown_override_is_still_refused() -> None:
    with pytest.raises(ValueError, match="pre-registered flags"):
        NavInstructRunner(navigator_overrides={"make_it_pass": True})


# ---------------------------------------------------------------------------
# The two runner seams, and their flag-off inertness
# ---------------------------------------------------------------------------


def test_the_pre_drive_seam_defaults_to_none() -> None:
    default = inspect.signature(NavInstructRunner.__init__).parameters["pre_drive"].default
    assert default is None


def test_route_memory_telemetry_is_keyed_on_the_flag_being_NAMED() -> None:
    """A run that never mentions route memory keeps the frozen row shape."""

    plain = NavInstructRunner()
    assert plain.route_memory_arm is False
    off = NavInstructRunner(navigator_overrides={"route_memory": False})
    assert off.route_memory_arm is True, "the OFF arm must record its own zeros"
    on = NavInstructRunner(navigator_overrides={"route_memory": True})
    assert on.route_memory_arm is True


def test_deferred_releases_counts_deferral_ticks_not_armings() -> None:
    """The counter semantics RM3_STATUS revision 1 conflated (audit correction 3).

    Three counters, three different units, and reading any of them as "armings"
    is wrong in a specific, reproducible way:

    * ``route_memory_routes_found`` — armings. Incremented in
      ``_arm_route_memory_chain`` exactly when ``waypoints_toward`` returns a
      non-empty chain.
    * ``route_memory_wins`` — waypoint proposals that won arbitration, which
      includes MID-CHAIN advances: ``_route_memory_navigate`` re-publishes on
      every waypoint reached, so ``wins >= routes_found`` always.
    * ``route_memory_deferred_releases`` — deferral EVENTS, not armings.
      ``_route_memory_defer_release`` returns ``True`` for an already-live chain
      **without arming anything**, and ``_unroutable_goal_recovery`` increments
      the counter on every such tick.

    Pinned on the real source rather than on prose, so the next reader of a
    persisted row cannot repeat the conflation.
    """

    import inspect

    defer = inspect.getsource(DirectiveNavigator._route_memory_defer_release)
    # The early return that makes this a deferral tick and NOT an arming.
    assert "if self._route_memory_chain:" in defer
    assert "return True" in defer.split("if self._route_memory_chain:")[1][:40]

    recovery = inspect.getsource(DirectiveNavigator._unroutable_goal_recovery)
    assert "self.route_memory_deferred_releases += 1" in recovery
    # ...and it is the ONLY writer, so trigger (ii) can never move it.
    partial = inspect.getsource(DirectiveNavigator._route_memory_partial_recovery)
    assert "route_memory_deferred_releases" not in partial

    arm = inspect.getsource(DirectiveNavigator._arm_route_memory_chain)
    assert "self.route_memory_routes_found += 1" in arm
    assert "route_memory_deferred_releases" not in arm

    publish = inspect.getsource(DirectiveNavigator._publish_route_memory_waypoint)
    assert "self.route_memory_wins += 1" in publish
    # The mid-chain re-publish that makes ``wins`` exceed ``routes_found``.
    navigate = inspect.getsource(DirectiveNavigator._route_memory_navigate)
    assert "_publish_route_memory_waypoint()" in navigate


def test_the_hook_snapshot_is_present_on_only_and_the_flag_on_navigator() -> None:
    """The asymmetry IS the evidence: a flag-off hook snapshot would be a bug."""

    runner_off = NavInstructRunner(navigator_overrides={"route_memory": False})
    runner_on = NavInstructRunner(navigator_overrides={"route_memory": True})
    off = route_memory_record(runner_off._navigator())
    on = route_memory_record(runner_on._navigator())
    assert off["enabled"] is False
    assert off["hook"] is None
    assert off["routes_found"] == 0
    assert on["enabled"] is True
    assert isinstance(on["hook"], dict)
    assert on["hook"]["keyframes"] == 0


# ---------------------------------------------------------------------------
# The substrate — one property per honesty clause, each with a companion
# ---------------------------------------------------------------------------


def test_the_set_is_candidate_only_and_cannot_be_frozen() -> None:
    assert ROUTE_MEMORY_SET_NAME not in EPISODE_SETS


def test_the_gated_set_is_the_pre_registered_size_and_balanced() -> None:
    episodes = cells()
    assert len(episodes) == ROUTE_MEMORY_N_CELLS == 60
    targets = {episode.target_entity_id for episode in episodes}
    assert len(targets) == 6, "the round-robin must spread over every target"


def test_clause_4_every_cell_is_KNOWN_and_not_sighted() -> None:
    for episode in cells():
        payload = cell_payload(episode)
        assert payload["range_m"] > VISIBILITY_MAX_RANGE_M
        assert payload["visible_from_start"] is False


def test_clause_3_every_goal_is_beyond_the_planners_reach() -> None:
    for episode in cells():
        payload = cell_payload(episode)
        assert payload["goal_edge_distance_m"] > ROUTE_MEMORY_REACH_M
        # ...and the reach is RM-1's constant, not a transcription of it.
        assert payload["reach_m"] == DEFAULT_ATTACH_RADIUS_M


def test_clause_2_both_attach_ends_are_inside_rm1s_attach_radius() -> None:
    for episode in cells():
        payload = cell_payload(episode)
        assert payload["start_attach_m"] == 0.0
        assert payload["goal_attach_m"] <= DEFAULT_ATTACH_RADIUS_M


def test_clause_1_the_taught_route_covers_start_to_inside_the_scored_region() -> None:
    for episode in cells():
        route = taught_route_of(episode)
        assert len(route) >= 2
        assert route[0] == pytest.approx(episode.start_pose[:2])
        assert episode.goal.contains(
            route[-1][0], route[-1][1], anchor_xy=episode.goal.center
        ), f"{episode.episode_id}: the taught route does not reach the scored region"


def test_the_straight_corridor_is_blocked_and_the_taught_route_is_not() -> None:
    """The two halves of "a detour the local window cannot see", per cell."""

    for episode in cells():
        payload = cell_payload(episode)
        assert payload["corridor_min_clearance_m"] <= OBSTACLE_STOP_FLOOR_M
        assert payload["route_min_clearance_m"] > OBSTACLE_STOP_FLOOR_M
        assert payload["start_clearance_m"] > TEACH_MIN_CLEARANCE_M
        assert payload["detour_excess_m"] >= ROUTE_MEMORY_MIN_DETOUR_M


def test_seeded_the_straight_line_would_fail_the_route_clearance_check() -> None:
    """The companion. The forbidden artefact is the STRAIGHT line itself.

    If the same clearance checker that admits a cell's taught route is fed the
    straight line the cell exists to avoid, it must reject it — otherwise the
    "blocked corridor / clear detour" pair is not a distinction the instrument
    can draw.
    """

    occupancy = truth_occupancy()
    episode = cells()[0]
    route = taught_route_of(episode)
    straight = (route[0], route[-1])
    assert occupancy.polyline_min_clearance(route) > OBSTACLE_STOP_FLOOR_M
    assert occupancy.polyline_min_clearance(straight) <= OBSTACLE_STOP_FLOOR_M


def test_seeded_a_disc_model_start_the_world_calls_wedged_is_not_admitted() -> None:
    """DR-2 handoff 2, pinned as the reason occupancy comes from the world.

    ``(3.5, 2.5)`` is free under the landmark-disc model and has 0.157 m of TRUE
    clearance — an unmapped crate. The first draft admitted it and its taught leg
    spent 1257 ticks without moving 3.5 m.
    """

    occupancy = truth_occupancy()
    assert occupancy.clearance(3.5, 2.5) < 0.2
    assert occupancy.clearance(3.5, 2.5) <= TEACH_MIN_CLEARANCE_M
    assert not occupancy.free_cell(occupancy.cell_of((3.5, 2.5)))
    assert all(
        (episode.start_pose[0], episode.start_pose[1]) != (3.5, 2.5)
        for episode in cells()
    )


def test_generation_is_deterministic() -> None:
    first = generate_route_memory_cells()
    second = generate_route_memory_cells()
    assert cells_digest(first) == cells_digest(second)
    assert [e.episode_id for e in first] == [e.episode_id for e in second]


def test_a_limit_the_rule_cannot_fill_raises_rather_than_shrinking() -> None:
    with pytest.raises(ValueError, match="never silently shrink"):
        generate_route_memory_cells(limit=100_000)


# ---------------------------------------------------------------------------
# Derived constants — by reference, so a retune reddens instead of lying
# ---------------------------------------------------------------------------


def test_every_derived_constant_equals_its_live_source() -> None:
    from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE

    assert ROUTE_MEMORY_REACH_M == DEFAULT_ATTACH_RADIUS_M
    assert ROUTE_MEMORY_REACH_M == DirectiveNavigator.ROUTE_MEMORY_RANGE_M
    assert OBSTACLE_STOP_FLOOR_M == DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m
    assert TEACH_WAYPOINT_TOLERANCE_M == DEFAULT_KEYFRAME_SPACING_M / 2.0
    assert TEACH_MIN_CLEARANCE_M == OBSTACLE_STOP_FLOOR_M + TEACH_WAYPOINT_TOLERANCE_M
    assert ROUTE_MEMORY_MIN_DETOUR_M == DEFAULT_KEYFRAME_SPACING_M


def test_the_taught_leg_budget_bounds_the_worst_case_rather_than_the_typical() -> None:
    route = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0))
    budget = teach_tick_budget(route, 0.5, 0.75)
    # travel: 20 m at 0.5 m/s = 400 ticks, doubled = 800.
    # turns: 3 vertices x pi / (0.75 x 0.1) = 3 x 41.9 = 125.7.
    assert budget == math.ceil(800.0 + 3.0 * math.pi / 0.075)
    assert budget > 2.0 * _polyline_length(route) / 0.05


# ---------------------------------------------------------------------------
# The budget, and the probe hold that must not straddle it (binding)
# ---------------------------------------------------------------------------


def test_no_episode_budget_can_be_decided_by_the_probe_hold() -> None:
    probe_hold_ticks = 2 * DirectiveNavigator.GRID_REPLAN_INTERVAL_STEPS
    assert probe_hold_ticks == 10
    smallest = min(
        scaled_step_budget(episode, 200, BUDGET_POLICY) for episode in cells()
    )
    # The fixed overhead term alone is 120 ticks; the smallest budget any cell
    # draws is far above it. 20x is a bound, not a measurement of the hold.
    assert smallest >= 20 * probe_hold_ticks


def test_both_arms_of_a_pair_draw_the_identical_budget() -> None:
    for episode in cells()[:5]:
        first = scaled_step_budget(episode, 200, BUDGET_POLICY)
        second = scaled_step_budget(episode, 200, BUDGET_POLICY)
        assert first == second
        assert episode.shortest_path_m == pytest.approx(
            cell_payload(episode)["taught_route_m"], abs=1e-6
        )


# ---------------------------------------------------------------------------
# The taught leg's contract
# ---------------------------------------------------------------------------


def test_the_taught_leg_drives_out_and_back_over_the_same_polyline() -> None:
    episode = cells()[0]
    route = taught_route_of(episode)
    drive = route + tuple(reversed(route))[1:]
    assert drive[0] == route[0]
    assert drive[-1] == route[0], "the leg must end where the measured mission starts"
    assert len(drive) == 2 * len(route) - 1
    assert _polyline_length(drive) == pytest.approx(2.0 * _polyline_length(route))


def test_the_pre_drive_declares_the_contract_it_discharges() -> None:
    """The clauses are load-bearing, so they are pinned as text, not folklore."""

    doc = TaughtRoutePreDrive.__doc__ or ""
    assert "OUT AND BACK" in doc
    assert "navigator.stop()" in doc
    assert "data.time" in doc


# ---------------------------------------------------------------------------
# Path fidelity (teach-and-repeat), and its companion
# ---------------------------------------------------------------------------


def _trace(points):
    return tuple({"x": x, "y": y} for x, y in points)


def test_path_fidelity_reads_zero_deviation_on_the_taught_line_itself() -> None:
    route = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0))
    fidelity = path_fidelity(_trace(route), route)
    assert fidelity["mean_m"] == pytest.approx(0.0)
    assert fidelity["max_m"] == pytest.approx(0.0)
    assert fidelity["coverage"] == pytest.approx(1.0)


def test_seeded_a_run_that_never_left_the_start_has_tiny_deviation_and_no_cover() -> None:
    """Why coverage is reported next to deviation and never instead of it.

    A robot frozen at the first taught vertex has a mean deviation of ZERO — a
    perfect fidelity score by deviation alone — and has repeated nothing.
    """

    route = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0))
    frozen = _trace([(0.0, 0.0)] * 50)
    fidelity = path_fidelity(frozen, route)
    assert fidelity["mean_m"] == pytest.approx(0.0)
    assert fidelity["coverage"] == pytest.approx(1.0 / 3.0)
    assert fidelity["path_m"] == pytest.approx(0.0)


def test_path_fidelity_measures_a_real_lateral_excursion() -> None:
    route = ((0.0, 0.0), (10.0, 0.0))
    excursion = path_fidelity(_trace([(5.0, 3.0)]), route)
    assert excursion["max_m"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Pairing — a table that cannot be built from incomparable arms
# ---------------------------------------------------------------------------


def _artifact(arm, successes, *, digest="D", matcher="default", profile=None, ids=None):
    ids = ids or [f"ep-{index}" for index in range(len(successes))]
    return {
        "arm": arm,
        "cells_digest": digest,
        "matcher_arm": matcher,
        "pose_drift_profile": profile,
        "set": "v4r",
        "aggregate": {"sr": sum(successes) / max(len(successes), 1)},
        "episodes": [
            {
                "episode_id": episode_id,
                "success": bool(success),
                "reason": "r",
                "distance_to_goal_m": 0.0,
                "measured": {},
            }
            for episode_id, success in zip(ids, successes, strict=True)
        ],
    }


def test_the_paired_table_decomposes_the_flips_in_both_directions() -> None:
    on = _artifact("on", [1, 1, 0, 1, 0])
    off = _artifact("off", [1, 0, 0, 0, 1])
    table = pair_arms(on, off)
    assert table["comparable"] is True
    assert table["table"] == {
        "both_succeed": 1,
        "on_only": 2,
        "off_only": 1,
        "neither": 1,
    }
    assert table["net_flips"] == 1
    assert table["discordant"] == 3
    assert table["mcnemar_p_exact"] == pytest.approx(mcnemar_exact(2, 1))
    assert {flip["direction"] for flip in table["flips"]} == {"on_only", "off_only"}


def test_incomparable_arms_are_refused_rather_than_averaged() -> None:
    on = _artifact("on", [1, 0])
    assert pair_arms(on, _artifact("off", [1, 0], digest="OTHER"))["comparable"] is False
    assert (
        pair_arms(on, _artifact("off", [1, 0], matcher="siglip2"))["comparable"] is False
    )
    assert (
        pair_arms(on, _artifact("off", [1, 0], profile="calibrated_go2"))["comparable"]
        is False
    )
    mislabelled = pair_arms(_artifact("off", [1, 0]), _artifact("off", [1, 0]))
    assert mislabelled["comparable"] is False


def test_disjoint_episode_sets_are_refused() -> None:
    on = _artifact("on", [1, 0], ids=["a", "b"])
    off = _artifact("off", [1, 0], ids=["a", "c"])
    assert pair_arms(on, off)["comparable"] is False
