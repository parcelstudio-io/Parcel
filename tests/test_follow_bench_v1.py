"""Gate for the FOLLOW_BENCH_V1 companion-navigation integration eval.

Covers: pure-metric unit tests on synthetic traces, scenario-table validation
against the real city geometry, two fast end-to-end smoke episodes, and the
CLI report/ledger contract. The full eight-scenario run is marked ``slow`` and
is excluded from the default gate.
"""

from __future__ import annotations

import json
import math
import os
import time

import pytest

from evals.companion_nav import run_follow_bench_v1
from evals.companion_nav.metrics import (
    EpisodeResult,
    StepRecord,
    band_fraction,
    compute_episode_metrics,
    occlusion_spans_s,
    path_irregularity_rad_per_m,
    pedestrian_contact_count,
    reacquire_times_s,
    rms_commanded_jerk_mps3,
    social_space_time_s,
)
from evals.companion_nav.runner import FollowBenchRunner
from evals.companion_nav.scenarios import (
    CONTROL_DT_S,
    FOLLOW_BENCH_V1,
    MAX_SCENARIO_DURATION_S,
    MAX_SCRIPTED_PEDESTRIANS,
    Scenario,
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
) -> StepRecord:
    return StepRecord(
        time_s=time_s,
        robot_x=0.0,
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


# ---------------------------------------------------------------------------
# Full suite (excluded from the gate)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("PARCEL_FOLLOW_BENCH_SLOW"),
    reason="full FOLLOW_BENCH_V1 run; set PARCEL_FOLLOW_BENCH_SLOW=1 to enable",
)
def test_full_follow_bench_v1_suite(tmp_path) -> None:
    out_dir = tmp_path / "results"
    assert run_follow_bench_v1.main(["--scenario", "all", "--out", str(out_dir)]) == 0
    (report_path,) = sorted(out_dir.glob("follow-bench-v1-*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    aggregate = report["aggregate"]
    assert aggregate["episode_count"] == len(FOLLOW_BENCH_V1)
    assert aggregate["hard_collision_total"] == 0
    assert aggregate["follow_success_count"] == aggregate["follow_episode_count"]
    assert aggregate["navigate_success_count"] == aggregate["navigate_episode_count"]
