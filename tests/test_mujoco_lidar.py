from __future__ import annotations

import math

import mujoco
import pytest

from parcel_robot.backends.base import LidarObstacle, OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE
from parcel_robot.simulation.mujoco_lidar import (
    MAX_LIDAR_OBSTACLES,
    planar_geom_surface_hit,
    scan_mujoco_lidar,
)

_SCENE = """
<mujoco model="lidar_geometry_test">
  <worldbody>
    <geom name="obstacle_long_box" type="box" pos="0 0 0.5" size="4 0.5 0.5"/>
    <geom name="obstacle_high" type="sphere" pos="0 0 3" size="0.2"/>
  </worldbody>
</mujoco>
"""


@pytest.fixture
def model_and_data():
    model = mujoco.MjModel.from_xml_string(_SCENE)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return model, data


def test_long_box_bearing_uses_closest_surface_not_geom_center(model_and_data) -> None:
    model, data = model_and_data
    geom_id = mujoco.mj_name2id(
        model,
        mujoco.mjtObj.mjOBJ_GEOM,
        "obstacle_long_box",
    )

    hit = planar_geom_surface_hit(
        model,
        data,
        geom_id,
        robot_x=3.0,
        robot_y=2.0,
    )

    assert hit is not None
    assert hit.surface_x == pytest.approx(3.0)
    assert hit.surface_y == pytest.approx(0.5)
    assert hit.bearing_rad == pytest.approx(-math.pi / 2.0)
    assert hit.signed_clearance_m == pytest.approx(1.5 - DEFAULT_ROBOT_PROFILE.footprint_radius_m)
    center_bearing = math.atan2(-2.0, -3.0)
    assert abs(hit.bearing_rad - center_bearing) > 0.8


def test_scan_samples_large_box_perimeter_with_one_identity(model_and_data) -> None:
    model, data = model_and_data
    geom_ids = range(model.ngeom)

    first = scan_mujoco_lidar(
        model,
        data,
        geom_ids,
        robot_x=3.0,
        robot_y=2.0,
        robot_heading=0.0,
    )
    second = scan_mujoco_lidar(
        model,
        data,
        geom_ids,
        robot_x=3.0,
        robot_y=2.0,
        robot_heading=0.0,
    )

    box_hits = [item for item in first if item.obstacle_id == "obstacle_long_box"]
    assert first == second
    assert 8 < len(box_hits) <= MAX_LIDAR_OBSTACLES
    assert all(item.obstacle_id == "obstacle_long_box" for item in first)
    assert any(
        abs(item.surface_x - 2.85) <= 0.26 and item.surface_y == pytest.approx(0.5)
        for item in box_hits
    )


def test_scan_excludes_geometry_entirely_above_robot_height(model_and_data) -> None:
    model, data = model_and_data

    hits = scan_mujoco_lidar(
        model,
        data,
        range(model.ngeom),
        robot_x=0.0,
        robot_y=0.0,
        robot_heading=0.0,
    )

    assert all(item.obstacle_id != "obstacle_high" for item in hits)


def test_bounded_scan_retains_forward_hazard_among_many_closer_rear_returns() -> None:
    rear_center_x = -(DEFAULT_ROBOT_PROFILE.footprint_radius_m + 0.05 + 0.10)
    forward_center_x = DEFAULT_ROBOT_PROFILE.footprint_radius_m + 0.05 + 0.55
    rear_geoms = "\n".join(
        f'<geom name="rear_{index:02d}" type="sphere" '
        f'pos="{rear_center_x} 0 0.05" size="0.05"/>'
        for index in range(MAX_LIDAR_OBSTACLES)
    )
    model = mujoco.MjModel.from_xml_string(
        f"""
        <mujoco model="bounded_lidar_fairness">
          <worldbody>
            {rear_geoms}
            <geom name="forward_hazard" type="sphere"
                  pos="{forward_center_x} 0 0.05" size="0.05"/>
          </worldbody>
        </mujoco>
        """
    )
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    hits = scan_mujoco_lidar(
        model,
        data,
        range(model.ngeom),
        robot_x=0.0,
        robot_y=0.0,
        robot_heading=0.0,
    )

    assert len(hits) == MAX_LIDAR_OBSTACLES
    forward = next(item for item in hits if item.obstacle_id == "forward_hazard")
    assert forward.distance_m == pytest.approx(0.55)
    assert forward.bearing_rad == pytest.approx(0.0)

    observation = SimObservation(
        timestamp=1.0,
        robot=RobotPose(),
        owner=OwnerTrack(),
        lidar_obstacles=tuple(
            LidarObstacle(item.distance_m, item.bearing_rad, item.obstacle_id)
            for item in hits
        ),
    )
    command, state = apply_reactive_safety(
        VelocityCommand(vx=0.2),
        observation,
        policy=ReactiveSafetyPolicy(),
        now=1.0,
    )

    assert command == VelocityCommand()
    assert state == "stopped"
