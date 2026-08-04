"""Gate for the FOLLOW_BENCH_V1 companion-navigation integration eval.

Covers: pure-metric unit tests on synthetic traces, scenario-table validation
against the real city geometry, two fast end-to-end smoke episodes, and the
CLI report/ledger contract. The full eight-scenario run is marked ``slow`` and
is excluded from the default gate.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import time
from dataclasses import replace

import pytest

from evals.companion_nav import run_follow_bench_v1
from evals.companion_nav.metrics import (
    EpisodeResult,
    StepRecord,
    acknowledgment_latency_s,
    band_fraction,
    blend_continuity_jerk_rad_s3,
    compute_episode_metrics,
    distance_band_error_m,
    gate_intervention_spans,
    occlusion_spans_s,
    path_irregularity_rad_per_m,
    path_length_m,
    pedestrian_contact_count,
    reacquire_times_s,
    rms_commanded_jerk_mps3,
    social_space_time_s,
    time_to_reacquire_s,
)
from evals.companion_nav.runner import BenchFeatures, FollowBenchRunner
from evals.companion_nav.scenarios import (
    CONTROL_DT_S,
    FOLLOW_BENCH_V1,
    MAX_SCENARIO_DURATION_S,
    MAX_SCRIPTED_PEDESTRIANS,
    EmoteWindow,
    ExpressionScript,
    Scenario,
    SpeechTurn,
    TimedWaypoint,
    interpolate_position,
    interpolate_velocity,
    scenario_by_id,
)
from parcel_robot.headless_city import HeadlessCityWorld

OWNER_RADIUS_M = 0.22


@pytest.fixture(scope="module")
def world() -> HeadlessCityWorld:
    return HeadlessCityWorld()


@pytest.fixture(scope="module")
def runner() -> FollowBenchRunner:
    return FollowBenchRunner()


# ---------------------------------------------------------------------------
# (a) Metric unit tests on synthetic traces
# ---------------------------------------------------------------------------


def test_band_fraction_counts_inclusive_membership() -> None:
    distances = [1.0, 1.2, 2.0, 3.0, 3.5]
    assert band_fraction(distances, band_min_m=1.2, band_max_m=3.0) == pytest.approx(0.6)
    assert band_fraction([], band_min_m=1.2, band_max_m=3.0) == 0.0
    with pytest.raises(ValueError):
        band_fraction(distances, band_min_m=3.0, band_max_m=1.0)


def test_occlusion_spans_and_reacquire_times_split_tail() -> None:
    visibility = [True, False, False, True, False]
    assert occlusion_spans_s(visibility, 0.1) == pytest.approx([0.2, 0.1])
    # The trailing occlusion never resolved, so it is not a reacquisition.
    assert reacquire_times_s(visibility, 0.1) == pytest.approx([0.2])
    assert occlusion_spans_s([True, True], 0.1) == []
    with pytest.raises(ValueError):
        occlusion_spans_s(visibility, 0.0)


def test_social_space_time_ignores_missing_pedestrians() -> None:
    centers = [None, 1.19, 1.2, 0.4, 2.0]
    assert social_space_time_s(centers, 0.1, threshold_m=1.2) == pytest.approx(0.2)
    assert social_space_time_s(centers, 0.1, threshold_m=0.45) == pytest.approx(0.1)


def test_pedestrian_contact_counts_distinct_entries() -> None:
    separations = [0.5, 0.0, -0.1, 0.4, None, -0.2, -0.3]
    assert pedestrian_contact_count(separations) == 2
    assert pedestrian_contact_count([0.5, 0.4]) == 0


def test_rms_jerk_is_zero_for_constant_and_positive_for_steps() -> None:
    assert rms_commanded_jerk_mps3([0.3] * 10, [0.0] * 10, 0.1) == 0.0
    ramp = [0.05 * index for index in range(10)]
    assert rms_commanded_jerk_mps3(ramp, [0.0] * 10, 0.1) == pytest.approx(0.0, abs=1e-9)
    step = [0.0, 0.0, 0.3, 0.3, 0.3]
    assert rms_commanded_jerk_mps3(step, [0.0] * 5, 0.1) > 0.0
    with pytest.raises(ValueError):
        rms_commanded_jerk_mps3([0.0], [0.0, 0.0], 0.1)


def test_path_irregularity_zero_for_straight_positive_for_zigzag() -> None:
    xs = [0.1 * index for index in range(20)]
    straight = path_irregularity_rad_per_m(xs, [0.0] * 20)
    zigzag = path_irregularity_rad_per_m(xs, [0.05 * (index % 2) for index in range(20)])
    assert straight == 0.0
    assert zigzag > 0.5
    # Stationary jitter must not divide by a near-zero path length.
    assert path_irregularity_rad_per_m([0.0, 1e-6, 0.0], [0.0, 0.0, 0.0]) == 0.0


def _synthetic_step(
    time_s: float,
    *,
    distance: float,
    visible: bool = True,
    surface: float | None = None,
    center: float | None = None,
    collisions: int = 0,
    proximity_state: str = "clear",
    reactive_proximity_state: str | None = None,
    search_state: str = "",
    head_yaw: float = 0.0,
    producer: str = "none",
    emote: str | None = None,
    robot_x: float = 0.0,
) -> StepRecord:
    return StepRecord(
        time_s=time_s,
        robot_x=robot_x,
        robot_y=0.0,
        robot_yaw=0.0,
        owner_x=distance,
        owner_y=0.0,
        owner_visible=visible,
        owner_distance_m=distance,
        command_vx=0.2,
        command_vy=0.0,
        command_vyaw=0.0,
        state="following",
        note="tracking_owner|clear",
        nearest_pedestrian_center_m=center,
        nearest_pedestrian_surface_m=surface,
        cumulative_static_collisions=collisions,
        proximity_state=proximity_state,
        reactive_proximity_state=(
            proximity_state if reactive_proximity_state is None else reactive_proximity_state
        ),
        search_state=search_state,
        expression_head_yaw_rad=head_yaw,
        expression_producer=producer,
        emote_label=emote,
    )


def test_compute_episode_metrics_scores_synthetic_follow_episode() -> None:
    scenario = scenario_by_id("straight_follow")
    steps = tuple(
        _synthetic_step(0.1 * index, distance=1.6, visible=index not in (5, 6))
        for index in range(20)
    )
    result = EpisodeResult(
        scenario_id=scenario.scenario_id,
        directive_kind="follow",
        control_dt_s=0.1,
        steps=steps,
        status="completed",
        reason="duration_elapsed",
        static_collision_count=0,
        minimum_static_clearance_m=0.8,
    )
    metrics = compute_episode_metrics(result, scenario)
    assert metrics.band_fraction == pytest.approx(1.0)
    assert metrics.following_success is True
    assert metrics.hard_collision_count == 0
    assert metrics.occlusion_count == 1
    assert metrics.max_time_owner_lost_s == pytest.approx(0.2)
    assert metrics.mean_time_to_reacquire_s == pytest.approx(0.2)
    assert metrics.navigate_success is None
    assert metrics.payload()["min_static_clearance_m"] == pytest.approx(0.8)


def test_compute_episode_metrics_fails_follow_on_pedestrian_contact() -> None:
    scenario = scenario_by_id("straight_follow")
    steps = tuple(
        _synthetic_step(
            0.1 * index,
            distance=1.6,
            center=0.4 if index == 3 else 2.0,
            surface=-0.05 if index == 3 else 1.5,
        )
        for index in range(10)
    )
    result = EpisodeResult(
        scenario_id=scenario.scenario_id,
        directive_kind="follow",
        control_dt_s=0.1,
        steps=steps,
        status="completed",
        reason="duration_elapsed",
        static_collision_count=0,
        minimum_static_clearance_m=0.9,
    )
    metrics = compute_episode_metrics(result, scenario)
    assert metrics.pedestrian_contact_count == 1
    assert metrics.hard_collision_count == 1
    assert metrics.following_success is False
    assert metrics.intimate_space_time_s == pytest.approx(0.1)
    assert metrics.min_pedestrian_surface_m == pytest.approx(-0.05)


# ---------------------------------------------------------------------------
# (a2) Card W9 metric unit tests
# ---------------------------------------------------------------------------


def test_distance_band_error_is_zero_inside_and_signed_to_the_near_edge() -> None:
    inside = distance_band_error_m(2.0, band_min_m=1.2, band_max_m=3.0)
    assert inside == 0.0
    assert distance_band_error_m(1.2, band_min_m=1.2, band_max_m=3.0) == 0.0
    assert distance_band_error_m(0.9, band_min_m=1.2, band_max_m=3.0) == pytest.approx(0.3)
    assert distance_band_error_m(3.5, band_min_m=1.2, band_max_m=3.0) == pytest.approx(0.5)


def test_gate_interventions_count_entries_not_steps() -> None:
    states = ["clear", "slowing", "slowing", "clear", "stopped", "stopped", "clear"]
    assert gate_intervention_spans(states) == 2
    assert gate_intervention_spans(states, only="stopped") == 1
    # A gate that is engaged for the whole episode is still one intervention.
    assert gate_intervention_spans(["slowing"] * 40) == 1


def test_time_to_reacquire_distinguishes_recovery_from_a_timeout() -> None:
    recovered = [True, True, False, False, False, True]
    assert time_to_reacquire_s(recovered, 0.1) == pytest.approx(0.3)
    # Never recovered is None, not zero and not the episode length: this is the
    # exact case owner_corner_loss exists to report honestly.
    assert time_to_reacquire_s([True, False, False, False], 0.1) is None
    assert time_to_reacquire_s([True, True], 0.1) is None


def test_path_length_only_sums_selected_spans() -> None:
    xs = [0.0, 1.0, 2.0, 3.0, 4.0]
    ys = [0.0] * 5
    assert path_length_m(xs, ys, [False, True, True, True, False]) == pytest.approx(2.0)
    assert path_length_m(xs, ys, [False] * 5) == 0.0


def test_blend_jerk_scores_hand_offs_and_ignores_smooth_stretches() -> None:
    smooth = [0.01 * index for index in range(20)]
    steady = ["idle"] * 20
    # No hand-off at all: nothing to score.
    assert blend_continuity_jerk_rad_s3(smooth, steady, 0.1) == 0.0
    # A hand-off that is genuinely smooth still scores near zero...
    handed_off = ["idle"] * 10 + ["reaction"] * 10
    assert blend_continuity_jerk_rad_s3(smooth, handed_off, 0.1) == pytest.approx(0.0)
    # ...while one that snaps the channel to zero does not.
    snapped = smooth[:10] + [0.0] * 10
    assert blend_continuity_jerk_rad_s3(snapped, handed_off, 0.1) > 1.0


def test_acknowledgment_latency_requires_the_reaction_producer() -> None:
    times = [0.1 * index for index in range(10)]
    yaws = [0.0, 0.0, 0.0, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]
    reacting = ["idle"] * 3 + ["reaction"] * 7
    assert acknowledgment_latency_s(times, yaws, reacting, onset_s=0.1) == pytest.approx(0.2)
    # The idle layer drifting past the threshold is not an acknowledgment.
    drifting = ["idle"] * 10
    assert acknowledgment_latency_s(times, yaws, drifting, onset_s=0.1) is None


def test_w9_metrics_are_scored_from_a_synthetic_trace() -> None:
    scenario = scenario_by_id("owner_turn_90")
    steps = []
    for index in range(40):
        moment = 0.1 * index
        steps.append(
            _synthetic_step(
                moment,
                # Inside the turn window the follower falls out of the band.
                distance=4.0 if 1.2 <= moment <= 2.4 else 2.0,
                proximity_state="stopped" if index in (5, 6) else "clear",
                search_state="sweep" if 10 <= index < 20 else "",
                robot_x=0.1 * index,
                head_yaw=0.25 if index >= 3 else 0.0,
                producer="reaction" if index >= 3 else "idle",
                emote="nod" if 25 <= index < 30 else None,
            )
        )
    result = EpisodeResult(
        scenario_id=scenario.scenario_id,
        directive_kind="follow",
        control_dt_s=0.1,
        steps=tuple(steps),
        status="completed",
        reason="duration_elapsed",
        static_collision_count=0,
        minimum_static_clearance_m=0.8,
    )
    # The synthetic trace uses a compressed clock, so score it against a turn
    # window and a conversation that match rather than the scenario's real ones.
    scenario = replace(
        scenario,
        turn_window_s=(1.2, 2.4),
        expression=ExpressionScript(
            speech_turns=(SpeechTurn(onset_s=0.2, end_s=1.0),),
            emotes=(EmoteWindow(label="nod", start_s=2.5, end_s=3.0),),
        ),
    )
    metrics = compute_episode_metrics(result, scenario)

    assert metrics.turn_mean_band_error_m == pytest.approx(1.0)
    assert metrics.turn_time_outside_band_s == pytest.approx(1.2)
    assert metrics.reactive_gate_stop_count == 1
    assert metrics.search_distance_m == pytest.approx(0.9)
    assert metrics.search_gave_up is False
    assert metrics.emote_active_time_s == pytest.approx(0.5)
    assert metrics.emote_hard_collision_count == 0
    assert metrics.expression_gated_fraction == 0.0
    assert metrics.acknowledgment_latency_s is not None


def test_emote_hard_collisions_are_attributed_to_the_gesture_that_owned_the_base() -> None:
    scenario = scenario_by_id("pedestrian_cut_in_predictive")
    steps = tuple(
        _synthetic_step(
            0.1 * index,
            distance=2.0,
            surface=-0.1 if index == 6 else 1.0,
            center=0.3 if index == 6 else 2.0,
            emote="tilt" if 5 <= index < 8 else None,
        )
        for index in range(12)
    )
    result = EpisodeResult(
        scenario_id=scenario.scenario_id,
        directive_kind="follow",
        control_dt_s=0.1,
        steps=steps,
        status="completed",
        reason="duration_elapsed",
        static_collision_count=0,
        minimum_static_clearance_m=0.9,
    )
    metrics = compute_episode_metrics(result, scenario)
    assert metrics.emote_hard_collision_count == 1
    assert metrics.hard_collision_count == 1


def test_scenarios_without_a_conversation_report_expression_as_not_applicable() -> None:
    scenario = scenario_by_id("straight_follow")
    assert scenario.expression.speech_turns == ()
    steps = tuple(_synthetic_step(0.1 * index, distance=2.0) for index in range(10))
    result = EpisodeResult(
        scenario_id=scenario.scenario_id,
        directive_kind="follow",
        control_dt_s=0.1,
        steps=steps,
        status="completed",
        reason="duration_elapsed",
        static_collision_count=0,
        minimum_static_clearance_m=0.9,
    )
    metrics = compute_episode_metrics(result, scenario)
    assert metrics.acknowledgment_latency_s is None
    assert metrics.emote_duty_cycle is None
    assert metrics.expression_gated_fraction is None
    # And a scenario that never searched must not report a zero search.
    assert metrics.search_distance_m is None
    assert metrics.search_gave_up is None


# ---------------------------------------------------------------------------
# (b) Scenario-table validation
# ---------------------------------------------------------------------------


def test_suite_has_required_deterministic_scenarios() -> None:
    assert len(FOLLOW_BENCH_V1) >= 8
    ids = [item.scenario_id for item in FOLLOW_BENCH_V1]
    assert len(set(ids)) == len(ids)
    seeds = [item.seed for item in FOLLOW_BENCH_V1]
    assert len(set(seeds)) == len(seeds)
    kinds = {item.directive_kind for item in FOLLOW_BENCH_V1}
    assert kinds == {"follow", "navigate"}
    for scenario in FOLLOW_BENCH_V1:
        assert isinstance(scenario.seed, int) and scenario.seed >= 0
        assert 0.0 < scenario.duration_s <= MAX_SCENARIO_DURATION_S
        assert len(scenario.pedestrians) <= MAX_SCRIPTED_PEDESTRIANS
        assert all(
            math.isfinite(value)
            for waypoint in scenario.owner_waypoints
            for value in (waypoint.time_s, waypoint.x, waypoint.y)
        )
        for pedestrian in scenario.pedestrians:
            assert all(
                math.isfinite(value)
                for waypoint in pedestrian.waypoints
                for value in (waypoint.time_s, waypoint.x, waypoint.y)
            )


def test_scenario_validation_rejects_bad_tables() -> None:
    base = scenario_by_id("straight_follow")
    with pytest.raises(ValueError):
        Scenario(
            scenario_id="bad",
            description="x",
            seed=1,
            robot_start=(0.0, 0.0, 0.0),
            owner_waypoints=(TimedWaypoint(0.0, 0.0, 0.0), TimedWaypoint(0.0, 1.0, 0.0)),
            pedestrians=(),
            directive_kind="follow",
            directive="follow me",
            duration_s=10.0,
        )
    with pytest.raises(ValueError):
        Scenario(
            scenario_id="bad",
            description="x",
            seed=1,
            robot_start=(0.0, 0.0, 0.0),
            owner_waypoints=base.owner_waypoints,
            pedestrians=(),
            directive_kind="teleport",
            directive="follow me",
            duration_s=10.0,
        )
    with pytest.raises(ValueError):
        Scenario(
            scenario_id="bad",
            description="x",
            seed=1,
            robot_start=(0.0, 0.0, 0.0),
            owner_waypoints=base.owner_waypoints,
            pedestrians=(),
            directive_kind="follow",
            directive="follow me",
            duration_s=MAX_SCENARIO_DURATION_S + 1.0,
        )
    with pytest.raises(ValueError):
        TimedWaypoint(0.0, math.nan, 0.0)


def test_scripted_actors_stay_on_free_space(world: HeadlessCityWorld) -> None:
    """Owner and pedestrian scripts must never intersect static geometry.

    ``truth_minimum_clearance`` uses the robot footprint radius (0.32 m), so an
    actor of radius r is collision-free whenever the returned clearance exceeds
    ``r - 0.32``; a small extra margin keeps the scripts from grazing walls.
    """

    for scenario in FOLLOW_BENCH_V1:
        start_clearance = world.truth_minimum_clearance(
            scenario.robot_start[0], scenario.robot_start[1]
        )
        assert start_clearance > 0.05, (scenario.scenario_id, "robot start")
        samples = int(scenario.duration_s / 0.5) + 1
        for index in range(samples):
            moment = index * 0.5
            owner_x, owner_y = interpolate_position(scenario.owner_waypoints, moment)
            clearance = world.truth_minimum_clearance(owner_x, owner_y)
            assert clearance > (OWNER_RADIUS_M - world.robot_radius_m) + 0.05, (
                scenario.scenario_id,
                "owner",
                moment,
            )
            for pedestrian in scenario.pedestrians:
                ped_x, ped_y = interpolate_position(pedestrian.waypoints, moment)
                clearance = world.truth_minimum_clearance(ped_x, ped_y)
                assert clearance > (pedestrian.radius_m - world.robot_radius_m) + 0.05, (
                    scenario.scenario_id,
                    pedestrian.agent_id,
                    moment,
                )


def test_card_w9_scenarios_are_present_and_carry_their_metrics() -> None:
    turn = scenario_by_id("owner_turn_90")
    assert turn.turn_window_s is not None
    start, end = turn.turn_window_s
    assert 0.0 <= start < end <= turn.duration_s
    # The gesture must sit outside the turn window: it preempts the base, and
    # a preempted base inside the window would contaminate the W2 measurement.
    assert all(window.start_s >= end for window in turn.expression.emotes)

    cut_in = scenario_by_id("pedestrian_cut_in_predictive")
    assert len(cut_in.pedestrians) == 1
    assert cut_in.expression.emotes, "the interruption metric needs a scripted emote"

    corner = scenario_by_id("owner_corner_loss")
    # Long enough to contain a whole search budget, or the give-up flag would
    # be reporting that the episode ended rather than that the search did.
    assert corner.duration_s > 45.0


def test_expression_script_validation_rejects_bad_tables() -> None:
    with pytest.raises(ValueError):
        SpeechTurn(onset_s=2.0, end_s=1.0)
    with pytest.raises(ValueError):
        EmoteWindow(label="", start_s=0.0, end_s=1.0)
    with pytest.raises(ValueError):
        ExpressionScript(
            speech_turns=(SpeechTurn(0.0, 2.0), SpeechTurn(1.0, 3.0)),
        )
    with pytest.raises(ValueError):
        ExpressionScript(
            emotes=(EmoteWindow("a", 0.0, 2.0), EmoteWindow("b", 1.0, 3.0)),
        )
    base = scenario_by_id("owner_turn_90")
    with pytest.raises(ValueError):
        replace(base, turn_window_s=(10.0, 5.0))
    with pytest.raises(ValueError):
        replace(base, turn_window_s=(0.0, base.duration_s + 1.0))
    with pytest.raises(ValueError):
        replace(
            base,
            expression=ExpressionScript(
                emotes=(EmoteWindow("late", base.duration_s - 1.0, base.duration_s + 5.0),),
            ),
        )


def test_bench_features_baseline_switches_every_sprint_path_off() -> None:
    shipped = BenchFeatures()
    baseline = BenchFeatures.baseline()
    assert shipped.label == "shipped"
    assert baseline.label == "baseline"
    assert not any(
        getattr(baseline, item.name) for item in dataclasses.fields(baseline)
    )
    with pytest.raises(TypeError):
        BenchFeatures(owner_prediction="yes")  # type: ignore[arg-type]

    # A baseline runner must actually disable the controllers, not just carry
    # a flag: this is what makes a baseline ledger row a real measurement.
    runner = FollowBenchRunner(features=baseline)
    assert runner.follow_prediction.enabled is False
    assert runner.time_to_collision.enabled is False
    assert runner.motion_shaping.enabled is False
    # ...and the shipped runner must pick the real configuration up, or every
    # "after" row would silently be a second baseline.
    shipped_runner = FollowBenchRunner(features=shipped)
    assert shipped_runner.follow_prediction.enabled is True
    assert shipped_runner.time_to_collision.enabled is True
    assert shipped_runner.motion_shaping.enabled is True


def test_interpolation_is_clamped_and_piecewise_linear() -> None:
    waypoints = (
        TimedWaypoint(0.0, 0.0, 0.0),
        TimedWaypoint(2.0, 2.0, 0.0),
        TimedWaypoint(3.0, 2.0, 1.0),
    )
    assert interpolate_position(waypoints, -1.0) == (0.0, 0.0)
    assert interpolate_position(waypoints, 1.0) == pytest.approx((1.0, 0.0))
    assert interpolate_position(waypoints, 2.5) == pytest.approx((2.0, 0.5))
    assert interpolate_position(waypoints, 9.0) == (2.0, 1.0)
    assert interpolate_velocity(waypoints, 1.0) == pytest.approx((1.0, 0.0))
    assert interpolate_velocity(waypoints, 2.5) == pytest.approx((0.0, 1.0))
    assert interpolate_velocity(waypoints, 9.0) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# (c) Fast end-to-end smoke episodes + (d) CLI report contract
# ---------------------------------------------------------------------------


def test_smoke_scenarios_and_cli_report(tmp_path, runner: FollowBenchRunner) -> None:
    started = time.monotonic()

    # Smoke 1: owner-stops, driven through the runner API.
    scenario = scenario_by_id("owner_stops")
    result = runner.run(scenario)
    metrics = compute_episode_metrics(result, scenario)
    assert result.static_collision_count == 0
    assert metrics.hard_collision_count == 0
    assert metrics.band_fraction is not None
    assert metrics.band_fraction >= scenario.min_band_fraction
    assert metrics.following_success is True
    assert metrics.max_time_owner_lost_s == 0.0
    assert len(result.steps) == scenario.control_steps

    # Smoke 2: straight-follow, driven through the CLI so the report and
    # ledger contracts are exercised on a real episode.
    out_dir = tmp_path / "results"
    exit_code = run_follow_bench_v1.main(
        ["--scenario", "straight_follow", "--out", str(out_dir)]
    )
    assert exit_code == 0
    reports = sorted(out_dir.glob("follow-bench-v1-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["suite"] == "follow-bench-v1"
    assert report["runner_version"]
    assert report["navigator_model_id"] == "grid_v1"
    assert report["scenario_ids"] == ["straight_follow"]
    assert report["control_dt_s"] == pytest.approx(CONTROL_DT_S)
    assert report["does_not_prove"], "reports must carry an explicit does_not_prove list"
    assert any("pedestrian" in item for item in report["does_not_prove"])
    (episode,) = report["episodes"]
    assert episode["hard_collision_count"] == 0
    assert episode["following_success"] is True
    assert episode["band_fraction"] >= scenario_by_id("straight_follow").min_band_fraction
    aggregate = report["aggregate"]
    assert aggregate["episode_count"] == 1
    assert aggregate["hard_collision_total"] == 0
    assert aggregate["follow_success_count"] == 1

    ledger_lines = (
        (out_dir / "ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
    )
    assert len(ledger_lines) == 1
    ledger_entry = json.loads(ledger_lines[0])
    assert ledger_entry["report"] == reports[0].name
    assert ledger_entry["hard_collision_total"] == 0
    assert ledger_entry["follow_success"] == "1/1"

    assert time.monotonic() - started < 60.0


def test_cli_records_which_features_produced_the_report(tmp_path) -> None:
    """A report that cannot say what was enabled cannot be compared to another."""

    out_dir = tmp_path / "results"
    assert (
        run_follow_bench_v1.main(
            [
                "--scenario",
                "straight_follow",
                "--out",
                str(out_dir),
                "--features",
                "baseline",
            ]
        )
        == 0
    )
    (report_path,) = sorted(out_dir.glob("follow-bench-v1-*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["features_label"] == "baseline"
    assert report["features"]["velocity_shaping"] is False
    assert report["aggregate"]["mean_rms_commanded_jerk_mps3"] is not None
    ledger = json.loads(
        (out_dir / "ledger.jsonl").read_text(encoding="utf-8").strip()
    )
    assert ledger["features"] == "baseline"

    # Every new scenario must be disclaimed, not just measured.
    disclaimers = " ".join(report["does_not_prove"])
    assert "re-identification" in disclaimers
    assert "owner-search plan path" in disclaimers
    assert "Gesture kinematics" in disclaimers or "gesture kinematics" in disclaimers


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("PARCEL_FOLLOW_BENCH_SLOW"),
    reason="closed-loop W9 episodes; set PARCEL_FOLLOW_BENCH_SLOW=1 to enable",
)
def test_owner_corner_loss_baseline_stands_still_and_the_search_gives_up() -> None:
    """The card's headline W7 before/after, asserted rather than asserted-about.

    The baseline must reproduce today's documented fail-closed hold, and the
    search must terminate on its own budget instead of hanging. Reacquisition
    is deliberately *not* asserted: it does not happen here, and UNVERIFIED
    U16 says why.
    """

    scenario = scenario_by_id("owner_corner_loss")
    baseline = compute_episode_metrics(
        FollowBenchRunner(features=BenchFeatures.baseline()).run(scenario), scenario
    )
    assert baseline.time_to_reacquire_s is None
    assert baseline.search_distance_m is None
    assert baseline.search_gave_up is None

    shipped = compute_episode_metrics(
        FollowBenchRunner(features=BenchFeatures()).run(scenario), scenario
    )
    assert shipped.search_gave_up is True
    assert shipped.search_distance_m is not None and shipped.search_distance_m > 0.5
    assert shipped.hard_collision_count == 0


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("PARCEL_FOLLOW_BENCH_SLOW"),
    reason="closed-loop W9 episodes; set PARCEL_FOLLOW_BENCH_SLOW=1 to enable",
)
def test_the_shaper_reduces_commanded_jerk_on_a_real_episode() -> None:
    """Card W6 end to end, which register entry U14 said the bench could not do."""

    scenario = scenario_by_id("owner_turn_90")
    baseline = compute_episode_metrics(
        FollowBenchRunner(features=BenchFeatures.baseline()).run(scenario), scenario
    )
    shipped = compute_episode_metrics(
        FollowBenchRunner(features=BenchFeatures()).run(scenario), scenario
    )
    assert shipped.rms_commanded_jerk_mps3 < 0.9 * baseline.rms_commanded_jerk_mps3
    # Smoother, and no worse at the job: the shaper must not buy comfort with
    # band membership or with clearance.
    assert shipped.band_fraction == pytest.approx(baseline.band_fraction, abs=0.05)
    assert shipped.hard_collision_count == 0


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("PARCEL_FOLLOW_BENCH_SLOW"),
    reason="closed-loop W9 episodes; set PARCEL_FOLLOW_BENCH_SLOW=1 to enable",
)
def test_the_predictive_brake_engages_without_a_contact() -> None:
    """Card W4's gate half: it must fire inside its band and hit nobody.

    A reduction in geometric-gate interventions is deliberately not asserted.
    It does not happen, because `reactive_safety.py` already brakes on the
    social candidate's own time-to-collision; UNVERIFIED U15 records that.
    """

    scenario = scenario_by_id("pedestrian_cut_in_predictive")
    baseline = compute_episode_metrics(
        FollowBenchRunner(features=BenchFeatures.baseline()).run(scenario), scenario
    )
    shipped = compute_episode_metrics(
        FollowBenchRunner(features=BenchFeatures()).run(scenario), scenario
    )
    assert baseline.min_time_to_collision_s is None
    assert shipped.min_time_to_collision_s is not None
    assert shipped.min_time_to_collision_s < 2.0
    assert baseline.hard_collision_count == 0
    assert shipped.hard_collision_count == 0
    assert shipped.emote_hard_collision_count == 0


# ---------------------------------------------------------------------------
# Full suite (excluded from the gate)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("PARCEL_FOLLOW_BENCH_SLOW"),
    reason="full FOLLOW_BENCH_V1 run; set PARCEL_FOLLOW_BENCH_SLOW=1 to enable",
)
@pytest.mark.parametrize("features", ["baseline", "shipped"])
def test_full_follow_bench_v1_suite(tmp_path, features: str) -> None:
    out_dir = tmp_path / "results"
    assert (
        run_follow_bench_v1.main(
            ["--scenario", "all", "--out", str(out_dir), "--features", features]
        )
        == 0
    )
    (report_path,) = sorted(out_dir.glob("follow-bench-v1-*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["features_label"] == features
    aggregate = report["aggregate"]
    assert aggregate["episode_count"] == len(FOLLOW_BENCH_V1)
    assert aggregate["hard_collision_total"] == 0
    assert aggregate["follow_success_count"] == aggregate["follow_episode_count"]
    assert aggregate["navigate_success_count"] == aggregate["navigate_episode_count"]
    # An emote must never be the thing that hits somebody, whichever features
    # are live: the gesture preempts the base, it does not steer it.
    assert aggregate["emote_hard_collision_total"] == 0
