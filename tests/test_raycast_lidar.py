"""Occlusion-true planar raycast scan: the Phase 1 perception contract."""

from __future__ import annotations

import math

import mujoco
import numpy as np
import pytest

from parcel_robot.simulation.mujoco_lidar import (
    PlanarScan,
    planar_scan_payload,
    raycast_planar_scan,
)

_SCENE = """
<mujoco>
  <worldbody>
    <geom name="floor" type="plane" size="50 50 0.1"/>
    <body name="robot" pos="0 0 0.3">
      <freejoint/>
      <geom name="robot_torso" type="box" size="0.19 0.07 0.06" mass="6"/>
      <body name="robot_leg" pos="0.15 0.1 0">
        <geom name="robot_leg_geom" type="capsule" fromto="0 0 0.25 0 0 -0.25"
              size="0.02" mass="0.4"/>
      </body>
    </body>
    <body name="wall_front" pos="3.0 0 0.5">
      <geom name="wall_front_geom" type="box" size="0.1 2.0 0.5"/>
    </body>
    <body name="box_hidden" pos="5.0 0 0.5">
      <geom name="box_hidden_geom" type="box" size="0.3 0.3 0.5"/>
    </body>
    <body name="pedestrian" pos="0 -2.0 0.9" mocap="true">
      <geom name="pedestrian_geom" type="cylinder" size="0.25 0.9" contype="0"
            conaffinity="0"/>
    </body>
  </worldbody>
</mujoco>
"""


@pytest.fixture()
def world():
    model = mujoco.MjModel.from_xml_string(_SCENE)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    robot_body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "robot")
    return model, data, robot_body


def _scan(world, **kwargs) -> PlanarScan:
    model, data, robot_body = world
    defaults = {
        "robot_x": 0.0,
        "robot_y": 0.0,
        "robot_heading": 0.0,
        "robot_body_id": robot_body,
        "sensor_z_m": 0.45,
        "num_rays": 360,
        "noise_std_m": 0.0,
        "dropout_rate": 0.0,
        "rng": None,
    }
    defaults.update(kwargs)
    return raycast_planar_scan(model, data, **defaults)


def _range_at_body_angle(scan: PlanarScan, angle: float) -> float:
    index = round((angle - scan.angle_min_rad) / scan.angle_increment_rad) % len(scan.ranges_m)
    return scan.ranges_m[index]


def test_forward_ray_hits_wall_at_true_distance(world) -> None:
    scan = _scan(world)
    forward = _range_at_body_angle(scan, 0.0)
    # Wall face is at x = 3.0 - 0.1 (half depth) = 2.9 m.
    assert forward == pytest.approx(2.9, abs=1e-6)


def test_occluded_box_is_invisible_behind_wall(world) -> None:
    scan = _scan(world)
    forward = _range_at_body_angle(scan, 0.0)
    # The box at 5 m is strictly behind the wall: the ray must stop at the
    # wall, never report the hidden box. Analytic closest-point scans got
    # this wrong by construction.
    assert forward < 4.0


def test_pedestrian_mocap_body_is_visible(world) -> None:
    scan = _scan(world)
    right = _range_at_body_angle(scan, -math.pi / 2.0)
    # Pedestrian cylinder at y = -2.0 with radius 0.25 -> surface at 1.75 m.
    assert right == pytest.approx(1.75, abs=1e-6)


def test_open_direction_reports_no_return_at_range_max(world) -> None:
    scan = _scan(world)
    backward = _range_at_body_angle(scan, math.pi)
    assert backward == pytest.approx(scan.range_max_m)


def test_robot_self_returns_are_ignored_not_free(world) -> None:
    scan = _scan(world)
    # The leg capsule crosses the scan plane near +33 degrees; every ray that
    # would hit the robot's own kinematic tree must be NaN (ignored), never a
    # phantom obstacle and never free space.
    leg_angle = math.atan2(0.1, 0.15)
    value = _range_at_body_angle(scan, leg_angle)
    assert math.isnan(value)
    own_hits = [r for r in scan.ranges_m if not math.isnan(r) and r < 0.5]
    assert not own_hits, f"robot body leaked into scan as obstacles: {own_hits[:5]}"


def test_scan_rotates_with_robot_heading(world) -> None:
    scan = _scan(world, robot_heading=math.pi / 2.0)
    # Facing +y: the wall (at +x world) is now at body angle -90 degrees.
    right = _range_at_body_angle(scan, -math.pi / 2.0)
    assert right == pytest.approx(2.9, abs=1e-6)


def test_noise_is_bounded_and_seeded(world) -> None:
    rng_a = np.random.default_rng(7)
    rng_b = np.random.default_rng(7)
    scan_a = _scan(world, noise_std_m=0.01, rng=rng_a)
    scan_b = _scan(world, noise_std_m=0.01, rng=rng_b)
    # Deterministic under a seed (NaN-aware comparison for ignored rays).
    np.testing.assert_array_equal(np.array(scan_a.ranges_m), np.array(scan_b.ranges_m))
    forward = _range_at_body_angle(scan_a, 0.0)
    assert abs(forward - 2.9) < 0.08  # noise stays bounded


def test_dropout_marks_rays_ignored(world) -> None:
    rng = np.random.default_rng(3)
    scan = _scan(world, dropout_rate=0.5, rng=rng)
    dropped = sum(1 for value in scan.ranges_m if math.isnan(value))
    assert dropped > 60  # ~half the 360 rays


def test_payload_is_json_safe_and_round_trips(world) -> None:
    import json

    scan = _scan(world, dropout_rate=0.1, rng=np.random.default_rng(1))
    payload = planar_scan_payload(scan)
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded["angle_increment_rad"] == pytest.approx(scan.angle_increment_rad)
    assert len(decoded["ranges"]) == 360
    assert any(value is None for value in decoded["ranges"])
    finite = [value for value in decoded["ranges"] if value is not None]
    assert all(0.0 <= value <= scan.range_max_m for value in finite)
