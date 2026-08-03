from __future__ import annotations

import math
from dataclasses import replace

import pytest

from parcel_robot.backends.base import LidarObstacle, OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.follow import (
    FollowConfig,
    FollowDecision,
    FollowOwnerController,
)


def _observation(
    timestamp: float,
    *,
    owner_x: float,
    owner_y: float = 0.0,
    robot_x: float = -3.0,
    robot_y: float = 0.0,
    robot_yaw: float = 0.0,
    confidence: float = 1.0,
    obstacle_m: float | None = None,
    obstacle_bearing_rad: float | None = None,
    person_m: float | None = None,
    person_bearing_rad: float | None = None,
) -> SimObservation:
    lidar = (
        (
            LidarObstacle(
                distance_m=obstacle_m,
                bearing_rad=obstacle_bearing_rad or 0.0,
                obstacle_id="obstacle-test",
            ),
        )
        if obstacle_m is not None and obstacle_bearing_rad is not None
        else ()
    )
    return SimObservation(
        timestamp=timestamp,
        robot=RobotPose(x=robot_x, y=robot_y, yaw=robot_yaw),
        owner=OwnerTrack(
            owner_id="owner-camera-track",
            x=owner_x,
            y=owner_y,
            visible=True,
            confidence=confidence,
        ),
        nearest_obstacle_m=obstacle_m,
        nearest_obstacle_bearing_rad=obstacle_bearing_rad,
        nearest_obstacle_id="obstacle-test" if obstacle_m is not None else None,
        lidar_obstacles=lidar,
        nearest_person_m=person_m,
        nearest_person_bearing_rad=person_bearing_rad,
        nearest_person_id="person-test" if person_m is not None else None,
        backend="camera-track-test",
    )


def _acquire_heading(
    controller: FollowOwnerController,
    *,
    robot_x: float = -3.0,
    robot_y: float = 0.0,
) -> FollowDecision:
    controller.step(
        _observation(0.0, owner_x=0.0, robot_x=robot_x, robot_y=robot_y),
        now=0.0,
    )
    controller.step(
        _observation(0.2, owner_x=0.1, robot_x=robot_x, robot_y=robot_y),
        now=0.2,
    )
    return controller.step(
        _observation(0.4, owner_x=0.2, robot_x=robot_x, robot_y=robot_y),
        now=0.4,
    )


def _segment_clearance(
    owner: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    sx, sy = start[0] - owner[0], start[1] - owner[1]
    ex, ey = end[0] - owner[0], end[1] - owner[1]
    dx, dy = ex - sx, ey - sy
    length_sq = dx * dx + dy * dy
    fraction = 0.0 if length_sq == 0.0 else -(sx * dx + sy * dy) / length_sq
    fraction = max(0.0, min(1.0, fraction))
    return math.hypot(sx + fraction * dx, sy + fraction * dy)


def test_behind_formation_holds_until_filtered_owner_heading_is_available() -> None:
    controller = FollowOwnerController()
    controller.start_formation("behind")

    seeded = controller.step(_observation(0.0, owner_x=0.0), now=0.0)
    first_motion = controller.step(_observation(0.2, owner_x=0.1), now=0.2)
    tracking = controller.step(_observation(0.4, owner_x=0.2), now=0.4)

    assert seeded.state == "acquiring_heading"
    assert seeded.reason == "owner_heading_unavailable"
    assert seeded.command == VelocityCommand()
    assert first_motion.state == "acquiring_heading"
    assert first_motion.reason == "owner_heading_unavailable"
    assert first_motion.command == VelocityCommand()
    assert tracking.state == "tracking_behind"
    assert tracking.mode == "behind"
    assert tracking.owner_heading_rad == pytest.approx(0.0)
    assert tracking.command.vx > 0.0


def test_passive_camera_tracks_admit_formation_without_erasing_fresh_heading() -> None:
    controller = FollowOwnerController()

    assert controller.observe_owner(_observation(0.0, owner_x=0.0), now=0.0) == "seeded"
    assert controller.observe_owner(_observation(0.2, owner_x=0.1), now=0.2) == "updated"
    assert controller.observe_owner(_observation(0.4, owner_x=0.2), now=0.4) == "updated"
    assert not controller.enabled
    assert controller.heading_available(now=0.4)
    heading = controller.heading_snapshot(now=0.4)
    assert heading["available"] is True
    assert heading["heading_rad"] == pytest.approx(0.0)

    controller.start_formation("behind")
    assert controller.heading_available(now=0.4)
    decision = controller.step(_observation(0.4, owner_x=0.2), now=0.4)
    assert decision.state == "tracking_behind"
    assert decision.command.vx > 0.0

    controller.stop()
    stopped = controller.step(_observation(0.5, owner_x=0.25), now=0.5)
    assert stopped.command == VelocityCommand()
    assert stopped.reason == "follow_disabled"


def test_passive_heading_fails_closed_on_staleness_and_owner_id_change() -> None:
    controller = FollowOwnerController()
    controller.observe_owner(_observation(0.0, owner_x=0.0), now=0.0)
    controller.observe_owner(_observation(0.2, owner_x=0.1), now=0.2)
    controller.observe_owner(_observation(0.4, owner_x=0.2), now=0.4)
    assert controller.heading_available(now=0.4)

    assert not controller.heading_available(now=1.21)
    changed = _observation(1.22, owner_x=0.21)
    changed = replace(changed, owner=replace(changed.owner, owner_id="owner-new"))
    assert controller.observe_owner(changed, now=1.22) == "seeded"
    assert not controller.heading_available(now=1.22)
    assert controller.heading_snapshot(now=1.22)["owner_id"] == "owner-new"


def test_behind_formation_rejects_track_outlier_and_expires_stale_heading() -> None:
    controller = FollowOwnerController()
    controller.start_formation("behind")
    _acquire_heading(controller)

    stale = controller.step(_observation(1.25, owner_x=0.2), now=1.25)
    assert stale.state == "acquiring_heading"
    assert stale.reason == "owner_heading_stale"
    assert stale.command == VelocityCommand()

    controller.start_formation("behind")
    controller.step(_observation(2.0, owner_x=0.0), now=2.0)
    outlier = controller.step(_observation(2.1, owner_x=2.0), now=2.1)
    assert outlier.state == "holding"
    assert outlier.reason == "owner_motion_outlier"
    assert outlier.command == VelocityCommand()


def test_front_to_behind_transition_uses_persistent_collision_clear_side_stage() -> None:
    controller = FollowOwnerController()
    controller.start_formation("behind")
    decision = _acquire_heading(controller, robot_x=2.2)

    assert decision.state == "staging"
    assert decision.reason == "staging_around_owner"
    assert decision.stage_side in {"left", "right"}
    assert decision.target_x_m is not None
    assert decision.target_y_m is not None
    clearance = _segment_clearance(
        (0.2, 0.0),
        (2.2, 0.0),
        (decision.target_x_m, decision.target_y_m),
    )
    assert clearance >= controller.config.owner_keepout_m

    next_decision = controller.step(
        _observation(0.6, owner_x=0.3, owner_y=0.01, robot_x=2.3),
        now=0.6,
    )
    assert next_decision.state == "staging"
    assert next_decision.stage_side == decision.stage_side


@pytest.mark.parametrize("hazard", ["lidar", "person"])
def test_behind_formation_stops_translation_for_camera_lidar_safety_hazards(
    hazard: str,
) -> None:
    controller = FollowOwnerController()
    controller.start_formation("behind")
    _acquire_heading(controller)
    kwargs = (
        {"obstacle_m": 0.5, "obstacle_bearing_rad": 0.0}
        if hazard == "lidar"
        else {"person_m": 0.8, "person_bearing_rad": 0.0}
    )

    decision = controller.step(_observation(0.6, owner_x=0.3, **kwargs), now=0.6)

    assert decision.state == "blocked"
    assert decision.reason == "formation_proximity_stop"
    assert decision.command.vx == 0.0
    assert decision.command.vy == 0.0


def test_behind_formation_does_not_rotate_or_translate_during_collision_contact() -> None:
    controller = FollowOwnerController()
    controller.start_formation("behind")
    _acquire_heading(controller)
    observation = replace(_observation(0.6, owner_x=0.3), collision=True)

    decision = controller.step(observation, now=0.6)

    assert decision.state == "blocked"
    assert decision.reason == "collision_contact"
    assert decision.command == VelocityCommand()


def test_moving_front_to_behind_formation_never_enters_owner_keepout() -> None:
    config = FollowConfig(
        max_vx=0.5,
        heading_min_displacement_m=0.005,
        heading_min_speed_mps=0.05,
        heading_min_updates=1,
    )
    controller = FollowOwnerController(config)
    controller.start_formation("behind")
    robot_x, robot_y, robot_yaw = 2.1, 0.0, 0.0
    minimum_distance = math.inf

    for index in range(601):
        timestamp = index * 0.1
        owner_x = 0.1 * timestamp
        decision = controller.step(
            _observation(
                timestamp,
                owner_x=owner_x,
                robot_x=robot_x,
                robot_y=robot_y,
                robot_yaw=robot_yaw,
            ),
            now=timestamp,
        )
        robot_yaw = _wrap(robot_yaw + decision.command.vyaw * 0.1)
        robot_x += decision.command.vx * math.cos(robot_yaw) * 0.1
        robot_y += decision.command.vx * math.sin(robot_yaw) * 0.1
        minimum_distance = min(
            minimum_distance,
            math.hypot(robot_x - owner_x, robot_y),
        )

    owner_x = 6.0
    assert minimum_distance >= config.owner_keepout_m
    assert robot_x - owner_x < -config.owner_keepout_m
    assert abs(robot_y) < 0.25


def test_formation_distance_is_bounded_at_the_controller_boundary() -> None:
    controller = FollowOwnerController()

    with pytest.raises(ValueError, match="formation distance"):
        controller.start_formation("behind", distance_m=0.5)
    with pytest.raises(ValueError, match="formation distance"):
        controller.start_formation("behind", distance_m=10.0)
    with pytest.raises(ValueError, match="unsupported"):
        controller.start_formation("beside")


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
