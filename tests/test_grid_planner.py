from __future__ import annotations

import math

import numpy as np
import pytest

from parcel_robot.navigation.grid_planner import (
    CellState,
    GridPlannerConfig,
    LidarScan,
    Pose2D,
    RollingGridPlanner,
    RollingOccupancyGrid,
    RoutePlan,
)


def _config(**overrides: object) -> GridPlannerConfig:
    values: dict[str, object] = {
        "resolution_m": 0.10,
        "grid_size_cells": 121,
        "robot_radius_m": 0.22,
        "safety_margin_m": 0.08,
        "lidar_range_cap_m": 5.5,
        "goal_tolerance_m": 0.20,
    }
    values.update(overrides)
    return GridPlannerConfig(**values)


def _scan(
    ranges: tuple[float, ...],
    *,
    angle_min: float = 0.0,
    increment: float = 0.1,
    maximum: float = 5.0,
) -> LidarScan:
    return LidarScan(
        ranges_m=ranges,
        angle_min_rad=angle_min,
        angle_increment_rad=increment,
        range_max_m=maximum,
    )


def _vertical_wall_scan(
    *,
    wall_x: float,
    low_y: float,
    high_y: float,
    maximum: float,
    ray_count: int = 721,
) -> LidarScan:
    angle_min = -math.pi
    increment = 2.0 * math.pi / (ray_count - 1)
    ranges = []
    for index in range(ray_count):
        angle = angle_min + index * increment
        cosine = math.cos(angle)
        if cosine <= 1e-9:
            ranges.append(math.inf)
            continue
        distance = wall_x / cosine
        intersection_y = distance * math.sin(angle)
        ranges.append(
            distance if 0.0 < distance < maximum and low_y <= intersection_y <= high_y else math.inf
        )
    return LidarScan(
        ranges_m=tuple(ranges),
        angle_min_rad=angle_min,
        angle_increment_rad=increment,
        range_max_m=maximum,
    )


def _wall_corridor_plan(
    gaps_y: tuple[tuple[float, float], ...],
) -> tuple[RollingGridPlanner, RoutePlan]:
    """Build a fully observed wall with selected openings for route tests."""

    config = _config(
        grid_size_cells=121,
        robot_radius_m=0.10,
        safety_margin_m=0.10,
        hard_safety_margin_m=0.10,
        comfort_safety_margin_m=0.30,
        comfort_cost_weight=8.0,
        lidar_range_cap_m=5.0,
        allow_unknown=False,
        goal_tolerance_m=0.15,
    )
    planner = RollingGridPlanner(config)
    pose = Pose2D(-2.45, 0.05, 0.0)
    planner.update(pose, _scan((math.inf,), maximum=5.0))
    grid = planner.grid
    grid._observed.fill(True)
    grid._log_odds.fill(0.0)
    wall_x = grid.world_to_local_cell((0.05, 0.05))
    assert wall_x is not None
    for y in range(config.grid_size_cells):
        world_y = grid.local_cell_center((wall_x[0], y))[1]
        if not any(low <= world_y <= high for low, high in gaps_y):
            grid._log_odds[y, wall_x[0]] = 1.0
    grid._generation += 1
    grid._invalidate_inflation()
    return planner, planner.plan(pose, (2.45, 0.05))


def _wall_crossing_y(plan: RoutePlan, *, wall_x: float = 0.05) -> float:
    for start, end in zip(plan.waypoints_world, plan.waypoints_world[1:]):
        if min(start[0], end[0]) <= wall_x <= max(start[0], end[0]):
            if abs(end[0] - start[0]) <= 1e-12:
                return start[1]
            fraction = (wall_x - start[0]) / (end[0] - start[0])
            return start[1] + fraction * (end[1] - start[1])
    raise AssertionError("route never crossed the test wall")


def _reference_bresenham(start: tuple[int, int], end: tuple[int, int]):
    """Small scalar oracle kept independent of the production batch rasterizer."""

    x, y = start
    end_x, end_y = end
    dx = abs(end_x - x)
    dy = abs(end_y - y)
    step_x = 1 if x < end_x else -1
    step_y = 1 if y < end_y else -1
    error = dx - dy
    while True:
        yield (x, y)
        if x == end_x and y == end_y:
            return
        twice_error = 2 * error
        if twice_error > -dy:
            error -= dy
            x += step_x
        if twice_error < dx:
            error += dx
            y += step_y


def _reference_scan_update(
    log_odds: np.ndarray,
    observed: np.ndarray,
    config: GridPlannerConfig,
    pose: Pose2D,
    scan: LidarScan,
    origin: tuple[int, int],
) -> tuple[int, int, int]:
    """Original set-based inverse sensor model used as an exact test oracle."""

    resolution = config.resolution_m

    def global_cell(point: tuple[float, float]) -> tuple[int, int]:
        return (math.floor(point[0] / resolution), math.floor(point[1] / resolution))

    def local_cell(cell: tuple[int, int]) -> tuple[int, int] | None:
        result = (cell[0] - origin[0], cell[1] - origin[1])
        size = config.grid_size_cells
        return result if 0 <= result[0] < size and 0 <= result[1] < size else None

    start_global = global_cell(pose.xy)
    start = local_cell(start_global)
    assert start is not None
    free_cells = {start}
    hit_cells: set[tuple[int, int]] = set()
    valid_rays = 0
    effective_max = min(scan.range_max_m, config.lidar_range_cap_m)
    for index, raw_range in enumerate(scan.ranges_m):
        if math.isnan(raw_range) or raw_range == -math.inf or raw_range < scan.range_min_m:
            continue
        if raw_range == math.inf:
            distance = effective_max
            is_hit = False
        elif not math.isfinite(raw_range):
            continue
        else:
            distance = min(raw_range, effective_max)
            is_hit = raw_range < effective_max - 1e-6 and raw_range < scan.range_max_m - 1e-6
        if distance < scan.range_min_m:
            continue
        valid_rays += 1
        angle = pose.heading_rad + scan.angle_min_rad + index * scan.angle_increment_rad
        endpoint = global_cell(
            (
                pose.x + math.cos(angle) * distance,
                pose.y + math.sin(angle) * distance,
            )
        )
        ray = tuple(_reference_bresenham(start_global, endpoint))
        for cell in ray[1:-1] if is_hit else ray[1:]:
            local = local_cell(cell)
            if local is not None:
                free_cells.add(local)
        if is_hit:
            local = local_cell(endpoint)
            if local is not None:
                hit_cells.add(local)

    free_cells.difference_update(hit_cells)
    for x, y in sorted(free_cells, key=lambda cell: (cell[1], cell[0])):
        log_odds[y, x] = max(config.min_log_odds, float(log_odds[y, x]) - config.miss_log_odds)
        observed[y, x] = True
    for x, y in sorted(hit_cells, key=lambda cell: (cell[1], cell[0])):
        log_odds[y, x] = min(config.max_log_odds, float(log_odds[y, x]) + config.hit_log_odds)
        observed[y, x] = True
    return (valid_rays, len(hit_cells), len(free_cells))


def test_lidar_scan_can_be_built_from_observation_extras() -> None:
    ranges = [1.0, math.inf, 2.0]
    scan = LidarScan.from_extras(
        ranges,
        {
            "lidar_geometry": {
                "angle_min_rad": -1.0,
                "angle_increment_rad": 0.5,
                "range_min_m": 0.10,
                "range_max_m": 8.0,
            }
        },
    )

    ranges[0] = 99.0
    assert scan.ranges_m == (1.0, math.inf, 2.0)
    assert scan.angle_min_rad == -1.0
    assert scan.range_max_m == 8.0


def test_lidar_scan_requires_explicit_geometry() -> None:
    with pytest.raises(TypeError, match="angle_increment_rad"):
        LidarScan.from_extras((1.0,), {"angle_min_rad": 0.0, "range_max_m": 4.0})


def test_clearance_defaults_preserve_legacy_hard_inflation() -> None:
    config = _config(safety_margin_m=0.08)

    assert config.effective_hard_margin_m == 0.08
    assert config.effective_comfort_margin_m == 0.08
    assert config.inflation_radius_m == pytest.approx(0.30)
    assert config.comfort_radius_m == pytest.approx(0.30)
    assert config.comfort_cost_enabled is False


@pytest.mark.parametrize(
    "overrides",
    (
        {"hard_safety_margin_m": -0.01},
        {"hard_safety_margin_m": 0.10, "comfort_safety_margin_m": 0.09},
        {"comfort_cost_weight": -1.0},
    ),
)
def test_clearance_config_rejects_invalid_fields(overrides: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        _config(**overrides)


def test_scan_updates_free_hit_and_no_return_cells_without_phantom_ring() -> None:
    grid = RollingOccupancyGrid(_config(grid_size_cells=101, lidar_range_cap_m=4.0))
    pose = Pose2D(0.05, 0.05, 0.0)
    update = grid.update(
        pose,
        _scan((2.0, math.inf), increment=math.pi / 2.0, maximum=4.0),
    )

    assert update.valid_rays == 2
    assert update.hit_cells == 1
    assert grid.cell_state((1.0, 0.05)) is CellState.FREE
    assert grid.cell_state((2.05, 0.05)) is CellState.OCCUPIED
    assert grid.cell_state((0.05, 2.5)) is CellState.FREE
    assert grid.cell_state((0.05, 4.05)) is not CellState.OCCUPIED


def test_scan_angles_are_rotated_by_world_heading() -> None:
    grid = RollingOccupancyGrid(_config(grid_size_cells=81, lidar_range_cap_m=3.0))
    grid.update(Pose2D(0.05, 0.05, math.pi / 2.0), _scan((1.5,), maximum=3.0))

    assert grid.cell_state((0.05, 1.55)) is CellState.OCCUPIED
    assert grid.cell_state((1.55, 0.05)) is not CellState.OCCUPIED


def test_same_safe_cell_outside_metric_tolerance_emits_motion_not_arrival() -> None:
    planner = RollingGridPlanner(_config(goal_tolerance_m=0.10))
    pose = Pose2D(0.001, 0.001, 0.0)
    goal = (0.099, 0.099)
    planner.update(pose, _scan((math.inf,), maximum=3.0))

    plan = planner.plan(pose, goal)

    assert math.dist(pose.xy, goal) > planner.config.goal_tolerance_m
    assert planner.grid.world_to_local_cell(pose.xy) == planner.grid.world_to_local_cell(goal)
    assert plan.status == "planned"
    assert plan.reaches_goal_region is True
    assert plan.waypoints_world == (pose.xy, goal)
    assert plan.path_length_m == pytest.approx(math.dist(pose.xy, goal))
    assert plan.note == "same_safe_cell_exact_metric_goal"


def test_start_cell_candidate_outside_metric_tolerance_is_not_false_arrival() -> None:
    planner = RollingGridPlanner(_config(goal_tolerance_m=0.10))
    pose = Pose2D(0.001, 0.05, 0.0)
    goal = (0.199, 0.05)
    planner.update(pose, _scan((math.inf,), maximum=3.0))

    plan = planner.plan(pose, goal)

    assert math.dist(pose.xy, goal) > planner.config.goal_tolerance_m
    assert planner.grid.world_to_local_cell(pose.xy) != planner.grid.world_to_local_cell(goal)
    assert plan.status == "planned"
    assert plan.reaches_goal_region is True
    assert plan.waypoints_world[0] == pose.xy
    assert plan.waypoints_world[-1] == goal
    assert plan.path_length_m > 0.0


def test_later_free_evidence_clears_a_moving_obstacle_return() -> None:
    grid = RollingOccupancyGrid(_config(grid_size_cells=81, lidar_range_cap_m=3.0))
    pose = Pose2D(0.05, 0.05, 0.0)
    endpoint = (1.55, 0.05)
    grid.update(pose, _scan((1.5,), maximum=3.0))
    assert grid.cell_state(endpoint) is CellState.OCCUPIED

    grid.update(pose, _scan((math.inf,), maximum=3.0))

    assert grid.cell_state(endpoint) is CellState.FREE


def test_batched_scan_update_exactly_matches_scalar_unique_evidence_oracle() -> None:
    config = _config(grid_size_cells=81, lidar_range_cap_m=2.0)
    pose = Pose2D(0.05, 0.05, 0.0)
    # The first two rays duplicate a hit cell. The no-return and finite
    # max-range rays clear through that same cell, but frame-local hit evidence
    # must win. Invalid values contribute no evidence.
    scan = _scan(
        (1.0, 1.0, math.inf, 2.0, math.nan, -math.inf, 0.01),
        increment=1e-12,
        maximum=2.0,
    )
    robot_global = (
        math.floor(pose.x / config.resolution_m),
        math.floor(pose.y / config.resolution_m),
    )
    half = config.grid_size_cells // 2
    origin = (robot_global[0] - half, robot_global[1] - half)
    expected_log_odds = np.zeros((config.grid_size_cells,) * 2, dtype=np.float32)
    expected_observed = np.zeros_like(expected_log_odds, dtype=np.bool_)
    expected_counts = _reference_scan_update(
        expected_log_odds,
        expected_observed,
        config,
        pose,
        scan,
        origin,
    )

    grid = RollingOccupancyGrid(config)
    actual = grid.update(pose, scan)

    assert (actual.valid_rays, actual.hit_cells, actual.free_cells) == expected_counts
    np.testing.assert_array_equal(grid._log_odds, expected_log_odds)
    np.testing.assert_array_equal(grid._observed, expected_observed)
    assert actual.hit_cells == 1
    assert grid.cell_state((1.05, 0.05)) is CellState.OCCUPIED

    # A later no-return frame clears the former hit once, matching the same
    # scalar oracle bit-for-bit rather than accumulating duplicate ray misses.
    clearing_scan = _scan((math.inf, math.inf), increment=1e-12, maximum=2.0)
    expected_counts = _reference_scan_update(
        expected_log_odds,
        expected_observed,
        config,
        pose,
        clearing_scan,
        origin,
    )
    actual = grid.update(pose, clearing_scan)
    assert (actual.valid_rays, actual.hit_cells, actual.free_cells) == expected_counts
    np.testing.assert_array_equal(grid._log_odds, expected_log_odds)
    np.testing.assert_array_equal(grid._observed, expected_observed)
    assert grid.cell_state((1.05, 0.05)) is CellState.FREE


def test_inflation_blocks_the_configured_robot_envelope() -> None:
    grid = RollingOccupancyGrid(_config(grid_size_cells=81))
    grid.update(Pose2D(0.05, 0.05, 0.0), _scan((2.0,), maximum=5.0))

    assert grid.cell_state((2.05, 0.05)) is CellState.OCCUPIED
    assert not grid.is_traversable((1.75, 0.05))
    assert grid.is_traversable((1.55, 0.05))


def test_rolling_shift_preserves_world_aligned_overlap_and_drops_old_window() -> None:
    config = _config(
        resolution_m=0.25,
        grid_size_cells=41,
        robot_radius_m=0.10,
        safety_margin_m=0.0,
        lidar_range_cap_m=4.0,
    )
    grid = RollingOccupancyGrid(config)
    first_pose = Pose2D(0.10, 0.10, 0.0)
    grid.update(first_pose, _scan((2.0,), maximum=4.0))
    obstacle = (2.10, 0.10)
    assert grid.cell_state(obstacle) is CellState.OCCUPIED

    shifted = grid.update(
        Pose2D(1.10, 0.10, 0.0),
        _scan((math.inf,), angle_min=math.pi / 2.0, maximum=4.0),
    )
    assert shifted.shifted_cells_xy == (4, 0)
    assert grid.cell_state(obstacle) is CellState.OCCUPIED

    grid.update(
        Pose2D(20.10, 0.10, 0.0),
        _scan((math.inf,), angle_min=math.pi / 2.0, maximum=4.0),
    )
    assert grid.cell_state(obstacle) is CellState.OUT_OF_BOUNDS


def test_astar_routes_around_inflated_wall_and_is_deterministic() -> None:
    planner = RollingGridPlanner(_config())
    pose = Pose2D(0.0, 0.0, 0.0)
    scan = _vertical_wall_scan(
        wall_x=2.0,
        low_y=-1.0,
        high_y=1.0,
        maximum=5.5,
    )
    planner.update(pose, scan)

    first = planner.plan(pose, (4.0, 0.0))
    second = planner.plan(pose, (4.0, 0.0))

    assert first == second
    assert first.status == "planned"
    assert first.reaches_goal_region
    assert first.expanded_nodes > 0
    assert first.path_length_m > 4.0
    assert any(abs(y) > 1.20 for _, y in first.waypoints_world)
    for start, end in zip(first.waypoints_world, first.waypoints_world[1:]):
        steps = max(1, math.ceil(math.dist(start, end) / 0.04))
        for index in range(steps + 1):
            fraction = index / steps
            point = (
                start[0] + (end[0] - start[0]) * fraction,
                start[1] + (end[1] - start[1]) * fraction,
            )
            assert planner.grid.is_traversable(point)


def test_comfort_cost_prefers_wide_corridor_when_available() -> None:
    _, plan = _wall_corridor_plan(((-0.25, 0.25), (1.25, 2.75)))

    assert plan.status == "planned"
    assert _wall_crossing_y(plan) > 1.0


def test_comfort_cost_allows_narrow_but_hard_safe_corridor() -> None:
    _, plan = _wall_corridor_plan(((-0.25, 0.25),))

    assert plan.status == "planned"
    assert abs(_wall_crossing_y(plan)) < 0.10


def test_hard_inflation_refuses_below_footprint_corridor() -> None:
    _, plan = _wall_corridor_plan(((-0.05, 0.05),))

    assert plan.status == "no_path"
    assert not plan.waypoints_world


def test_unknown_space_is_penalized_but_traversable_for_incremental_mapping() -> None:
    pose = Pose2D(0.05, 0.05, 0.0)
    scan = _scan((math.inf,), maximum=3.0)
    incremental = RollingGridPlanner(
        _config(grid_size_cells=81, lidar_range_cap_m=3.0, allow_unknown=True)
    )
    incremental.update(pose, scan)
    assert incremental.plan(pose, (0.05, 2.0)).status == "planned"

    known_only = RollingGridPlanner(
        _config(grid_size_cells=81, lidar_range_cap_m=3.0, allow_unknown=False)
    )
    known_only.update(pose, scan)
    blocked = known_only.plan(pose, (0.05, 2.0))
    assert blocked.status == "goal_blocked"


def test_goal_outside_rolling_window_produces_forward_partial_route() -> None:
    planner = RollingGridPlanner(_config(grid_size_cells=61, lidar_range_cap_m=3.0))
    pose = Pose2D(0.05, 0.05, 0.0)
    rays = tuple(math.inf for _ in range(361))
    planner.update(
        pose,
        _scan(rays, angle_min=-math.pi, increment=2.0 * math.pi / 360.0, maximum=3.0),
    )

    plan = planner.plan(pose, (100.0, 0.05))

    assert plan.status == "partial"
    assert not plan.reaches_goal_region
    assert plan.waypoints_world[-1][0] > 2.0
    assert planner.grid.bounds.contains(plan.waypoints_world[-1])


def test_frontier_profile_clips_unknown_route_to_observed_safe_prefix() -> None:
    planner = RollingGridPlanner(
        _config(
            grid_size_cells=81,
            lidar_range_cap_m=2.0,
            reachable_frontier_fallback=True,
        )
    )
    pose = Pose2D(0.05, 0.05, 0.0)
    # One no-return ray observes a straight 2 m prefix; A* may hypothesize a
    # continuation through penalized unknown space but must not execute it.
    planner.update(pose, _scan((math.inf,), maximum=2.0))

    plan = planner.plan(pose, (10.0, 0.05))
    waypoint = planner.next_waypoint(pose, plan)

    assert plan.status == "partial"
    assert plan.note == "reachable_observed_frontier"
    assert 1.0 < plan.waypoints_world[-1][0] < 2.2
    assert waypoint is not None
    assert waypoint.forward_m > 0.0
    assert waypoint.left_m == pytest.approx(0.0, abs=1e-9)


def test_observed_first_frontier_uses_one_connectivity_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = RollingGridPlanner(
        _config(
            grid_size_cells=81,
            lidar_range_cap_m=2.0,
            reachable_frontier_fallback=True,
            frontier_search_mode="observed_first",
        )
    )
    pose = Pose2D(0.05, 0.05, 0.0)
    planner.update(pose, _scan((math.inf,), maximum=2.0))

    def reject_duplicate_astar(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("observed-first mode must not run unknown-admitting A*")

    monkeypatch.setattr(planner, "_astar", reject_duplicate_astar)
    plan = planner.plan(pose, (10.0, 0.05))

    assert plan.status == "partial"
    assert plan.note == "reachable_observed_frontier"
    assert plan.unknown_cells_on_grid_path == 0
    assert 1.0 < plan.waypoints_world[-1][0] < 2.2
    assert planner.next_waypoint(pose, plan) is not None


def test_observed_first_frontier_reuses_connectivity_for_reachable_goal() -> None:
    planner = RollingGridPlanner(
        _config(
            grid_size_cells=81,
            lidar_range_cap_m=3.0,
            reachable_frontier_fallback=True,
            frontier_search_mode="observed_first",
        )
    )
    pose = Pose2D(0.05, 0.05, 0.0)
    planner.update(
        pose,
        _scan(
            tuple(math.inf for _ in range(361)),
            angle_min=-math.pi,
            increment=2.0 * math.pi / 360.0,
            maximum=3.0,
        ),
    )

    plan = planner.plan(pose, (2.05, 0.05))

    assert plan.status == "planned"
    assert plan.reaches_goal_region is True
    assert plan.note == "astar_cost_aware_unknowns_and_known_free_los_smoothing"
    assert plan.unknown_cells_on_grid_path == 0
    assert math.dist(plan.waypoints_world[-1], (2.05, 0.05)) <= 0.20 + 1e-12


def test_observed_first_frontier_requires_feature_gate() -> None:
    with pytest.raises(
        ValueError,
        match="observed_first frontier search requires reachable_frontier_fallback",
    ):
        _config(frontier_search_mode="observed_first")

    with pytest.raises(ValueError, match="frontier_search_mode"):
        _config(
            reachable_frontier_fallback=True,
            frontier_search_mode="unsupported",  # type: ignore[arg-type]
        )


def test_body_waypoint_preserves_forward_left_unitree_convention() -> None:
    planner = RollingGridPlanner(_config(grid_size_cells=81, lidar_range_cap_m=3.0))
    pose = Pose2D(0.05, 0.05, 0.0)
    planner.update(
        pose,
        _scan(
            tuple(math.inf for _ in range(181)),
            angle_min=-math.pi,
            increment=2.0 * math.pi / 180.0,
            maximum=3.0,
        ),
    )
    plan = planner.plan(pose, (0.05, 2.0))

    waypoint = planner.next_waypoint(pose, plan)

    assert waypoint is not None
    assert waypoint.forward_m == pytest.approx(0.0, abs=1e-9)
    assert waypoint.left_m > 0.0
    assert waypoint.heading_error_rad == pytest.approx(math.pi / 2.0)


def test_body_waypoint_can_egress_an_inflated_start_cell() -> None:
    planner = RollingGridPlanner(_config(grid_size_cells=81, lidar_range_cap_m=3.0))
    pose = Pose2D(0.05, 0.05, 0.0)
    # The rear return inflates the robot's current raster cell but not the
    # first cell ahead.  The forward no-return ray observes a safe egress.
    planner.update(
        pose,
        _scan((0.30, math.inf), angle_min=-math.pi, increment=math.pi, maximum=3.0),
    )
    start = planner.grid.world_to_local_cell(pose.xy)
    assert start is not None
    assert planner.grid.inflated_occupied_mask()[start[1], start[0]]

    plan = planner.plan(pose, (2.05, 0.05))
    waypoint = planner.next_waypoint(pose, plan)

    assert plan.status == "planned"
    assert waypoint is not None
    assert waypoint.forward_m > 0.0
    assert waypoint.left_m == pytest.approx(0.0, abs=1e-9)


def test_body_waypoint_rejects_blocked_cells_after_inflated_start() -> None:
    planner = RollingGridPlanner(_config(grid_size_cells=81, lidar_range_cap_m=3.0))
    pose = Pose2D(0.05, 0.05, 0.0)
    planner.update(
        pose,
        _scan((0.30, math.inf), angle_min=-math.pi, increment=math.pi, maximum=3.0),
    )
    blocked_route = RoutePlan(
        status="planned",
        waypoints_world=(pose.xy, (-0.55, 0.05)),
        requested_goal_world=(-0.55, 0.05),
        planning_target_world=(-0.55, 0.05),
        reaches_goal_region=True,
        expanded_nodes=0,
        path_length_m=0.60,
        unknown_cells_on_grid_path=0,
        map_generation=planner.grid.generation,
    )

    assert planner.next_waypoint(pose, blocked_route) is None


def test_complete_obstacle_ring_has_no_path_without_privileged_map_data() -> None:
    planner = RollingGridPlanner(_config(grid_size_cells=81, lidar_range_cap_m=3.0))
    pose = Pose2D(0.05, 0.05, 0.0)
    planner.update(
        pose,
        _scan(
            tuple(1.0 for _ in range(721)),
            angle_min=-math.pi,
            increment=2.0 * math.pi / 720.0,
            maximum=3.0,
        ),
    )

    plan = planner.plan(pose, (2.0, 0.05))

    assert plan.status == "no_path"
    assert not plan.waypoints_world


def test_reachable_frontier_fallback_routes_toward_wall_edge_without_map_truth() -> None:
    config = _config(
        grid_size_cells=61,
        robot_radius_m=0.10,
        safety_margin_m=0.10,
        lidar_range_cap_m=3.0,
        reachable_frontier_fallback=True,
        frontier_band_m=0.40,
        frontier_min_progress_m=0.10,
    )
    planner = RollingGridPlanner(config)
    pose = Pose2D(0.05, 0.05, 0.0)
    planner.update(pose, _scan((math.inf,), maximum=3.0))

    # Fully observe a horizontal wall that joins both current map edges. The
    # direct northward rolling-horizon target is disconnected, but reaching a
    # side edge below the wall will let a subsequent rolling map reveal a way
    # around it. This private test fixture is not passed through the policy API.
    grid = planner.grid
    grid._observed.fill(True)
    grid._log_odds.fill(0.0)
    wall = grid.world_to_local_cell((0.05, 1.05))
    assert wall is not None
    grid._log_odds[wall[1], :] = 1.0
    grid._generation += 1
    grid._invalidate_inflation()

    plan = planner.plan(pose, (0.05, 10.0))

    assert plan.status == "partial"
    assert plan.note in {
        "reachable_observed_frontier",
        "reachable_window_frontier_fallback",
    }
    assert plan.planning_target_world is not None
    assert abs(plan.planning_target_world[0]) > 2.0
    assert plan.planning_target_world[1] < 1.05
    assert math.dist(plan.planning_target_world, (0.05, 10.0)) < 10.0
    for first, second in zip(plan.waypoints_world, plan.waypoints_world[1:]):
        assert planner._world_segment_is_clear(first, second)


def test_reachable_frontier_fallback_preserves_no_path_for_closed_ring() -> None:
    planner = RollingGridPlanner(
        _config(
            grid_size_cells=81,
            lidar_range_cap_m=3.0,
            reachable_frontier_fallback=True,
        )
    )
    pose = Pose2D(0.05, 0.05, 0.0)
    planner.update(
        pose,
        _scan(
            tuple(1.0 for _ in range(721)),
            angle_min=-math.pi,
            increment=2.0 * math.pi / 720.0,
            maximum=3.0,
        ),
    )

    plan = planner.plan(pose, (2.0, 0.05))

    assert plan.status == "no_path"
    assert not plan.waypoints_world
