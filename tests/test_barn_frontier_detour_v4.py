from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from evals.external.barn_policy_specs import parcel_experimental_config_spec
from parcel_robot.navigation.base import GoalPose, Mission, NavObservation
from parcel_robot.navigation.grid_navigator import GridNavigator
from parcel_robot.navigation.grid_planner import (
    GridPlannerConfig,
    LidarScan,
    Pose2D,
    RollingGridPlanner,
)
from parcel_robot.navigation.registry import ModelRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
SPLIT_PATH = (
    REPO_ROOT / "evals" / "external" / "development" / "barn_frontier_detour_v4" / "split.json"
)
EXPERIMENT_CONFIG = (
    REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_frontier_detour_v4.yaml"
)
RESULTS_ROOT = SPLIT_PATH.parent / "results"


def _ids_sha256(world_ids: list[int]) -> str:
    return hashlib.sha256(",".join(str(value) for value in world_ids).encode()).hexdigest()


def _retreat_corridor(*, detour_enabled: bool) -> tuple[RollingGridPlanner, Pose2D]:
    planner = RollingGridPlanner(
        GridPlannerConfig(
            resolution_m=0.10,
            grid_size_cells=81,
            robot_radius_m=0.10,
            safety_margin_m=0.10,
            lidar_range_cap_m=3.0,
            goal_tolerance_m=0.20,
            reachable_frontier_fallback=True,
            frontier_search_mode="observed_first",
            bounded_detour_frontier_fallback=detour_enabled,
            frontier_max_goal_regression_m=1.50,
            frontier_detour_min_travel_m=0.60,
        )
    )
    pose = Pose2D(0.05, 0.05, 0.0)
    planner.update(
        pose,
        LidarScan(
            ranges_m=(math.inf,),
            angle_min_rad=0.0,
            angle_increment_rad=0.1,
            range_max_m=3.0,
        ),
    )
    start = planner.grid.world_to_local_cell(pose.xy)
    assert start is not None
    start_x, start_y = start
    # Policy-visible fixture: the only observed hard-safe egress initially
    # leads south, away from a northward goal. Unknown cells remain forbidden by
    # observed-first routing. No evaluator map or reference path is introduced.
    planner.grid._observed.fill(False)
    planner.grid._log_odds.fill(0.0)
    planner.grid._observed[start_y - 15 : start_y + 1, start_x - 1 : start_x + 2] = True
    planner.grid._generation += 1
    planner.grid._invalidate_inflation()
    return planner, pose


def test_v4_split_is_deterministic_disjoint_and_sealed_before_execution() -> None:
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    partition = split["partition"]
    source = partition["source_world_ids"]
    development = partition["development_world_ids"]
    confirmation = partition["sealed_confirmation_world_ids"]
    seed = partition["seed"]
    ranked = sorted(
        source,
        key=lambda world_id: (
            hashlib.sha256(f"{seed}:{world_id}".encode()).hexdigest(),
            world_id,
        ),
    )

    assert source == list(range(5, 300, 6))
    assert sorted(development) == sorted(ranked[:30])
    assert sorted(confirmation) == sorted(ranked[30:])
    assert set(development).isdisjoint(confirmation)
    assert set(development) | set(confirmation) == set(source)
    assert _ids_sha256(source) == partition["source_world_ids_sha256"]
    assert _ids_sha256(development) == partition["development_world_ids_sha256"]
    assert _ids_sha256(confirmation) == partition["sealed_confirmation_world_ids_sha256"]
    assert split["status"]["sealed_confirmation_opened"] is False
    assert split["status"]["sealed_confirmation_run_id"] is None
    gate = split["promotion_gate_frozen_before_development"]
    assert gate["minimum_paired_success_gains"] == 2
    assert gate["maximum_paired_success_regressions"] == 0
    assert gate["all_conditions_required_for_single_sealed_confirmation"] is True


def test_development_summary_rejects_candidate_without_opening_confirmation() -> None:
    summary = json.loads((RESULTS_ROOT / "paired-run02-summary.json").read_text(encoding="utf-8"))
    assert summary["development_world_count"] == 30
    assert summary["sealed_confirmation_world_count"] == 20
    assert summary["sealed_confirmation_opened"] is False
    assert summary["paired"]["success_gains"] == 0
    assert summary["paired"]["navigation_metric_delta"] == 0.0
    assert summary["candidate"]["collision_rate"] == 0.0
    assert summary["candidate"]["detour_track_steps"] > 0
    assert summary["promotion_gate"]["all_conditions_passed"] is False
    assert summary["decision"]["selected_for_sealed_confirmation"] is False
    assert summary["decision"]["confirmation_command_authorized"] is False


def test_development_ledger_pins_full_report_hashes_without_requiring_reports() -> None:
    summary = json.loads((RESULTS_ROOT / "paired-run02-summary.json").read_text(encoding="utf-8"))
    for arm in ("reference", "candidate"):
        run_id = summary[arm]["run_id"]
        ledger = json.loads(
            (RESULTS_ROOT / "ledger" / "runs" / f"{run_id}.json").read_text(encoding="utf-8")
        )
        assert ledger["run_id"] == run_id
        assert ledger["timestamp_utc"].endswith("Z")
        assert ledger["change_description"]
        assert ledger["report"]["sha256"] == summary[arm]["report_sha256"]
        assert ledger["report"]["size_bytes"] > 80_000


def test_detour_gate_is_explicit_and_observed_first_only() -> None:
    assert GridPlannerConfig().bounded_detour_frontier_fallback is False
    with pytest.raises(ValueError, match="requires observed_first"):
        GridPlannerConfig(
            reachable_frontier_fallback=True,
            bounded_detour_frontier_fallback=True,
        )


def test_bounded_detour_moves_to_observed_safe_frontier_when_progress_only_deadlocks() -> None:
    strict, pose = _retreat_corridor(detour_enabled=False)
    strict_plan = strict.plan(pose, (0.05, 3.05))
    assert strict_plan.status == "no_path"

    challenger, pose = _retreat_corridor(detour_enabled=True)
    plan = challenger.plan(pose, (0.05, 3.05))
    waypoint = challenger.next_waypoint(pose, plan)

    assert plan.status == "partial"
    assert plan.note == "reachable_bounded_detour_frontier"
    assert plan.unknown_cells_on_grid_path == 0
    assert plan.path_length_m >= 0.60 - 1e-12
    assert plan.planning_target_world is not None
    assert plan.planning_target_world[1] < pose.y
    assert (
        math.dist(plan.planning_target_world, (0.05, 3.05)) - math.dist(pose.xy, (0.05, 3.05))
        <= 1.50 + 1e-12
    )
    assert waypoint is not None


def test_v4_model_is_forward_only_and_experiment_remains_deployment_disabled() -> None:
    registry = ModelRegistry.load(REPO_ROOT / "configs" / "navigation" / "models")
    navigator = registry.create("grid_frontier_detour_v4", arrive_radius_m=0.5)

    assert isinstance(navigator, GridNavigator)
    assert navigator._planner.config.bounded_detour_frontier_fallback is True
    assert navigator._planner.config.frontier_max_goal_regression_m == 1.50
    assert navigator._planner.config.frontier_detour_min_travel_m == 0.60
    assert navigator.detour_commitment_reached_m == 0.20
    assert navigator.recovery_reverse_steps == 0
    mission = Mission("metric goal", GoalPose(0.0, 5.0, arrival_radius_m=0.5))
    navigator.reset(mission)
    command = navigator.act(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=90.0,
            lidar=(30.0,) * 181,
            extras={
                "lidar_angle_min_rad": -math.pi / 2.0,
                "lidar_angle_increment_rad": math.pi / 180.0,
                "lidar_range_min_m": 0.05,
                "lidar_range_max_m": 30.0,
            },
        ),
        mission,
    )
    assert command.vx >= 0.0
    assert command.vy == 0.0
    navigator.close()

    spec = parcel_experimental_config_spec(
        EXPERIMENT_CONFIG,
        experiment_id="barn-grid-frontier-detour-v4-test",
        description="deployment-boundary test",
    )
    metadata = spec.report_metadata()
    assert metadata["experimental"] is True
    assert metadata["deployment_enabled"] is False
    assert metadata["production_default_behavior_modified"] is False


def test_detour_controller_commits_through_alignment_without_changing_velocity_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ModelRegistry.load(REPO_ROOT / "configs" / "navigation" / "models")
    navigator = registry.create("grid_frontier_detour_v4", arrive_radius_m=0.5)
    mission = Mission("metric goal", GoalPose(0.05, 3.05, arrival_radius_m=0.5))
    navigator.reset(mission)
    planner, pose = _retreat_corridor(detour_enabled=True)
    navigator._planner = planner

    command = navigator.act(
        NavObservation(
            position=(pose.x, pose.y, 0.0),
            heading_deg=math.degrees(pose.heading_rad),
            lidar=(math.inf, math.inf),
            extras={
                "lidar_angle_min_rad": -math.pi / 2.0,
                "lidar_angle_increment_rad": 0.001,
                "lidar_range_min_m": 0.05,
                "lidar_range_max_m": 3.0,
            },
        ),
        mission,
    )

    assert command.note.startswith("grid_detour_align")
    assert command.vx == 0.0
    assert command.vy == 0.0
    target = navigator._committed_detour_target
    assert target is not None

    def unexpected_replan(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a safe detour route must remain committed while aligning")

    monkeypatch.setattr(planner, "plan", unexpected_replan)
    target_heading_deg = math.degrees(math.atan2(target[1] - pose.y, target[0] - pose.x))
    aligned_observation = NavObservation(
        position=(pose.x, pose.y, 0.0),
        heading_deg=target_heading_deg,
        lidar=(math.inf, math.inf),
        extras={
            "lidar_angle_min_rad": -math.pi / 2.0,
            "lidar_angle_increment_rad": 0.001,
            "lidar_range_min_m": 0.05,
            "lidar_range_max_m": 3.0,
        },
    )
    commands = [navigator.act(aligned_observation, mission) for _ in range(6)]
    assert all(item.note.startswith("grid_detour_track") for item in commands)
    assert all(item.vx > 0.0 and item.vy == 0.0 for item in commands)
    navigator.close()
