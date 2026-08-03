from __future__ import annotations

import math
from pathlib import Path

import mujoco
import yaml

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M, ROBOT_OBSTACLE_HEIGHT_M

REPO = Path(__file__).resolve().parents[1]
SCENE = REPO / "src" / "parcel_robot" / "scenes" / "city_block.xml"
ROBOT_CONFIG = REPO / "configs" / "robot.yaml"

# Keep the analytic commissioning check independent of discrete path samples so
# a thin post cannot fall between test angles.
STATIC_LOGICAL_PREFIXES = (
    "obstacle_",
    "bldg_",
    "bench_",
    "planter_",
    "tree_",
    "lamp_",
    "signal_",
)


def test_default_owner_orbit_has_continuous_static_fixture_clearance() -> None:
    """Prove clearance for the full orbit circumference, not sampled poses."""

    config = yaml.safe_load(ROBOT_CONFIG.read_text(encoding="utf-8"))
    orbit_radius = float(config["spatial_behaviors"]["default_orbit_radius_m"])
    obstacle_stop = float(config["safety"]["obstacle_stop_m"])
    required_center_clearance = ROBOT_FOOTPRINT_RADIUS_M + obstacle_stop

    model = mujoco.MjModel.from_xml_path(str(SCENE))
    data = mujoco.MjData(model)
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)
    owner_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "owner")
    assert owner_body_id >= 0
    owner_mocap_id = int(model.body_mocapid[owner_body_id])
    assert owner_mocap_id >= 0
    owner = (
        float(data.mocap_pos[owner_mocap_id, 0]),
        float(data.mocap_pos[owner_mocap_id, 1]),
    )

    clearances: dict[str, float] = {}
    for geom_id in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or ""
        if not name.startswith(STATIC_LOGICAL_PREFIXES):
            continue
        geom_type = int(model.geom_type[geom_id])
        if not _intersects_robot_height(model, data, geom_id, geom_type):
            continue
        clearances[name] = _continuous_ring_to_geom_distance(
            model,
            data,
            geom_id,
            geom_type,
            owner,
            orbit_radius,
        )

    assert clearances
    for prefix in ("bldg_", "bench_", "lamp_", "signal_", "obstacle_"):
        assert any(name.startswith(prefix) for name in clearances)
    violating = {
        name: round(distance, 4)
        for name, distance in clearances.items()
        if distance + 1e-9 < required_center_clearance
    }
    assert not violating, (
        f"default owner orbit needs {required_center_clearance:.3f} m center-to-fixture "
        f"clearance (robot radius + stop distance); violations={violating}"
    )


def _intersects_robot_height(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
    geom_type: int,
) -> bool:
    if geom_type == int(mujoco.mjtGeom.mjGEOM_BOX):
        half_height = float(model.geom_size[geom_id, 2])
    elif geom_type == int(mujoco.mjtGeom.mjGEOM_SPHERE):
        half_height = float(model.geom_size[geom_id, 0])
    elif geom_type == int(mujoco.mjtGeom.mjGEOM_CYLINDER):
        half_height = float(model.geom_size[geom_id, 1])
    elif geom_type == int(mujoco.mjtGeom.mjGEOM_CAPSULE):
        half_height = float(model.geom_size[geom_id, 0] + model.geom_size[geom_id, 1])
    else:
        return False
    bottom = float(data.geom_xpos[geom_id, 2]) - half_height
    return bottom <= ROBOT_OBSTACLE_HEIGHT_M


def _continuous_ring_to_geom_distance(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
    geom_type: int,
    owner: tuple[float, float],
    orbit_radius: float,
) -> float:
    gx, gy = (float(value) for value in data.geom_xpos[geom_id, :2])
    if geom_type == int(mujoco.mjtGeom.mjGEOM_BOX):
        # A circle is rotation invariant, so transform its center into the box's
        # local frame. Distances from that center to the nearest and farthest
        # points of the solid rectangle exactly determine whether the complete
        # orbit lies outside, intersects, or encloses it.
        rotation = data.geom_xmat[geom_id].reshape(3, 3)
        assert abs(abs(float(rotation[2, 2])) - 1.0) <= 1e-9, (
            "continuous orbit fixture check does not support a pitched box"
        )
        dx, dy, _ = rotation.T @ (owner[0] - gx, owner[1] - gy, 0.0)
        sx, sy = (float(value) for value in model.geom_size[geom_id, :2])
        nearest = math.hypot(max(abs(dx) - sx, 0.0), max(abs(dy) - sy, 0.0))
        farthest = math.hypot(abs(dx) + sx, abs(dy) + sy)
        if orbit_radius < nearest:
            return nearest - orbit_radius
        if orbit_radius > farthest:
            return orbit_radius - farthest
        return 0.0
    if geom_type in {
        int(mujoco.mjtGeom.mjGEOM_CYLINDER),
        int(mujoco.mjtGeom.mjGEOM_CAPSULE),
        int(mujoco.mjtGeom.mjGEOM_SPHERE),
    }:
        if geom_type != int(mujoco.mjtGeom.mjGEOM_SPHERE):
            axis_z = abs(float(data.geom_xmat[geom_id, 8]))
            assert abs(axis_z - 1.0) <= 1e-9, (
                "continuous orbit fixture check does not support a tilted cylinder"
            )
        obstacle_radius = float(model.geom_size[geom_id, 0])
        center_distance = math.hypot(owner[0] - gx, owner[1] - gy)
        return max(0.0, abs(center_distance - orbit_radius) - obstacle_radius)
    raise AssertionError(f"unsupported logical obstacle geometry: {geom_type}")
