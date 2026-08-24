from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.spatial import SpatialBehaviorConfig
from parcel_robot.simulation.headless_city import (
    DEFAULT_ROBOT_CONFIG,
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
)


@pytest.fixture(scope="module")
def world() -> HeadlessCityWorld:
    return HeadlessCityWorld()


@pytest.mark.parametrize(
    ("start", "directive", "expected_region", "max_steps"),
    [
        pytest.param(
            (0.0, -1.0, -math.pi / 2.0),
            "Can you go to the sidewalk so that you are not on the road. It's dangerous",
            "sidewalk_south",
            300,
            id="safety-rationale-from-road",
        ),
        pytest.param(
            (0.0, 0.0, 0.0),
            "walk to the sidewalk",
            # Back to "sidewalk" (north) under the 2026-08-07 region-instance
            # arbitration. History, because this row has moved twice:
            #   * originally "sidewalk" (north), reached with the U34 phantom
            #     yaw live — the north polygon read as more "in front";
            #   * Lane D's U34 fix (card D-4) removed the phantom heading and
            #     the then-current CENTROID tie-break flipped it south, because
            #     the south centroid is 3.00 m from the origin against the
            #     north centroid's 3.20 m;
            #   * the arbitration ranks interchangeable ("stuff class")
            #     instances by BOUNDARY distance — the distance to the region
            #     you can actually step onto — and by that measure the north
            #     sidewalk is nearer: 2.20 m (edge at y=+2.2) against the south
            #     sidewalk's 2.25 m (edge at y=-2.25). A 16 m-long sidewalk is
            #     not 3 m away because its middle is.
            # The south instance keeps its own case in `safety-rationale-from-
            # road`, where both measures agree on south (1.25 m boundary).
            "sidewalk",
            400,
            id="default-origin",
        ),
        pytest.param(
            # Started north of the road, where the north sidewalk is the
            # nearest instance (2.2 m against 4.0 m). Added with the U34 fix so
            # the north polygon does not lose its case to the tie-break.
            (0.0, 1.0, math.pi / 2.0),
            "walk to the sidewalk",
            "sidewalk",
            400,
            id="north-of-the-road",
        ),
    ],
)
def test_walk_to_sidewalk_reaches_safe_interior_and_stops_from_multiple_starts(
    world: HeadlessCityWorld,
    start: tuple[float, float, float],
    directive: str,
    expected_region: str,
    max_steps: int,
) -> None:
    world.reset(robot=start)

    result = HeadlessCityQualityHarness(world).run(directive, max_steps=max_steps)

    final = (result.final_observation.robot.x, result.final_observation.robot.y)
    metadata = world.truth_region_metadata(expected_region)
    assert result.succeeded, (result.status, result.reason)
    assert not result.timed_out
    assert len(result.trace) < max_steps
    assert result.target_id == expected_region
    assert result.terminal_relation == "inside"
    assert world.truth_inside_region(
        final,
        expected_region,
        clearance_m=float(metadata["terminal_clearance_m"]),
    )
    assert result.semantic_scan_steps >= 1
    assert result.collision_count == 0
    assert result.minimum_clearance_m >= result.required_obstacle_clearance_m
    assert result.stopped
    assert result.terminal_command == VelocityCommand()
    assert result.trace[-1].command == result.terminal_command
    assert any(sample.note == "semantic_stop_requested" for sample in result.trace)
    assert result.trace[-1].note == "arrived_verified"


@pytest.mark.parametrize(
    "start",
    [
        pytest.param((2.7, 1.0, math.radians(139.3)), id="road-approach"),
        pytest.param((3.2, 3.15, math.pi), id="moves-away-from-building-envelope"),
    ],
)
def test_wait_by_lamppost_uses_support_sidewalk_and_common_sense_vicinity(
    world: HeadlessCityWorld,
    start: tuple[float, float, float],
) -> None:
    max_steps = 300
    world.reset(robot=start)

    result = HeadlessCityQualityHarness(world).run(
        "Can you wait by the lamppost?",
        max_steps=max_steps,
    )

    final = (result.final_observation.robot.x, result.final_observation.robot.y)
    object_x, object_y, object_radius = world.truth_object("lamp_post_1")
    metadata = world.truth_object_metadata("lamp_post_1")
    center_distance = math.hypot(final[0] - object_x, final[1] - object_y)
    surface_distance = world.truth_object_surface_distance(final, "lamp_post_1")
    assert result.succeeded, (result.status, result.reason)
    assert not result.timed_out
    assert len(result.trace) < max_steps
    assert result.target_id == "lamp_post_1"
    assert result.terminal_relation == "near"
    assert float(metadata["minimum_vicinity_radius_m"]) <= center_distance
    assert center_distance <= float(metadata["vicinity_radius_m"])
    assert surface_distance >= float(metadata["target_min_surface_clearance_m"])
    assert surface_distance <= 1.0
    assert center_distance == pytest.approx(
        surface_distance + object_radius + world.robot_radius_m
    )
    assert world.truth_inside_region(
        final,
        "sidewalk",
        clearance_m=float(metadata["terminal_support_clearance_m"]),
    )
    assert result.collision_count == 0
    assert result.minimum_clearance_m >= result.required_obstacle_clearance_m
    assert result.stopped
    assert result.terminal_command == VelocityCommand()
    assert result.trace[-1].command == result.terminal_command
    assert any(sample.note == "semantic_stop_requested" for sample in result.trace)
    assert result.trace[-1].note == "arrived_verified"


def test_walk_once_around_owner_approaches_orbits_without_collision_and_stops(
    world: HeadlessCityWorld,
) -> None:
    config = SpatialBehaviorConfig()
    max_steps = 600
    world.reset(robot=(0.0, 0.0, 0.0))
    owner = world.owner_position()

    result = HeadlessCityQualityHarness(world).run(
        "Can you walk around the owner 1 time?",
        max_steps=max_steps,
    )

    assert result.succeeded, (result.status, result.reason)
    assert not result.timed_out
    assert len(result.trace) < max_steps
    assert result.reason == "orbit_complete"
    assert result.target_id == "owner-1"
    assert any(sample.note == "approach_orbit_ring" for sample in result.trace)
    # Extract the controller-independent world geometry only after the orbit
    # phase begins; the earlier approach trajectory receives no orbit credit.
    orbit_start = next(
        index
        for index, sample in enumerate(result.trace)
        if sample.note == "orbit_owner"
    )
    orbit_points = [
        (sample.robot.x, sample.robot.y) for sample in result.trace[orbit_start:]
    ]
    angles = [math.atan2(y - owner[1], x - owner[0]) for x, y in orbit_points]
    unwrapped = [angles[0]]
    for angle in angles[1:]:
        delta = (angle - unwrapped[-1] + math.pi) % (2.0 * math.pi) - math.pi
        unwrapped.append(unwrapped[-1] + delta)
    angular_progress = unwrapped[-1] - unwrapped[0]
    occupied_bins = {
        int(((angle % (2.0 * math.pi)) / (2.0 * math.pi)) * 12) % 12
        for angle in angles
    }
    radii = [math.hypot(x - owner[0], y - owner[1]) for x, y in orbit_points]
    endpoint_error = math.hypot(
        orbit_points[-1][0] - orbit_points[0][0],
        orbit_points[-1][1] - orbit_points[0][1],
    )
    finish_angle_tolerance = 2.0 * math.asin(
        config.waypoint_tolerance_m / (2.0 * config.default_orbit_radius_m)
    )
    assert angular_progress >= 2.0 * math.pi - finish_angle_tolerance
    assert len(occupied_bins) == 12
    assert min(radii) >= config.default_orbit_radius_m - config.waypoint_tolerance_m
    assert max(radii) <= config.default_orbit_radius_m + config.waypoint_tolerance_m
    assert endpoint_error <= 2.0 * config.waypoint_tolerance_m
    assert max(sample.progress for sample in result.trace) == pytest.approx(1.0)
    assert result.collision_count == 0
    assert result.minimum_clearance_m >= result.required_obstacle_clearance_m
    assert result.stopped
    assert result.terminal_command == VelocityCommand()
    assert result.trace[-1].command == result.terminal_command


def test_step_limit_is_reported_as_timeout_without_cleanup_laundering(
    world: HeadlessCityWorld,
) -> None:
    world.reset(robot=(0.0, -1.0, -math.pi / 2.0))

    result = HeadlessCityQualityHarness(world).run("walk to the sidewalk", max_steps=5)

    assert result.status == "timed_out"
    assert result.timed_out
    assert not result.succeeded
    assert len(result.trace) == 5
    assert result.terminal_command == result.trace[-1].command
    assert not result.stopped
    # Cleanup stops the reusable world, but cannot change recorded evidence.
    assert world.stopped


def test_rejected_directive_is_failed_not_timed_out(world: HeadlessCityWorld) -> None:
    world.reset()

    result = HeadlessCityQualityHarness(world).run(
        "Imagine the dog did not walk to the sidewalk"
    )

    assert result.status == "failed"
    assert result.reason == "directive_not_understood"
    assert not result.timed_out
    assert result.stopped


def test_harness_loads_reactive_thresholds_from_production_config(
    world: HeadlessCityWorld,
    tmp_path: Path,
) -> None:
    config = yaml.safe_load(DEFAULT_ROBOT_CONFIG.read_text(encoding="utf-8"))
    config["safety"]["obstacle_stop_m"] = 0.60
    configured = tmp_path / "robot.yaml"
    configured.write_text(yaml.safe_dump(config), encoding="utf-8")

    harness = HeadlessCityQualityHarness(world, robot_config=configured)

    assert harness.reactive_safety.obstacle_stop_m == pytest.approx(0.60)
    assert harness.spatial_config.min_orbit_radius_m == pytest.approx(
        float(config["spatial_behaviors"]["min_orbit_radius_m"])
    )


def test_harness_uses_navigation_config_selected_by_robot_config(
    world: HeadlessCityWorld,
    tmp_path: Path,
) -> None:
    navigation = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "configs/navigation/default.yaml").read_text(
            encoding="utf-8"
        )
    )
    navigation["semantic_search"]["max_steps"] = 1
    # Keep ScanForTarget frontier off so this asserts the configured scan budget.
    navigation["semantic_search"]["frontier_budget_steps"] = 0
    configured_navigation = tmp_path / "navigation.yaml"
    configured_navigation.write_text(yaml.safe_dump(navigation), encoding="utf-8")

    robot = yaml.safe_load(DEFAULT_ROBOT_CONFIG.read_text(encoding="utf-8"))
    robot["navigation"]["config"] = str(configured_navigation)
    configured_robot = tmp_path / "robot.yaml"
    configured_robot.write_text(yaml.safe_dump(robot), encoding="utf-8")
    world.reset(robot=(0.0, 0.0, 0.0))

    harness = HeadlessCityQualityHarness(world, robot_config=configured_robot)
    result = harness.run("walk to the sidewalk", max_steps=10)

    assert harness.navigation_config == configured_navigation.resolve()
    assert result.status == "failed"
    assert result.reason == "semantic_target_not_found"
    assert len(result.trace) == 1
