from __future__ import annotations

import math
from typing import Any

import mujoco

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M


def extract_city_semantics(
    model: mujoco.MjModel,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract test-camera regions and landmarks from a MuJoCo city model.

    These coordinates remain inside the simulator perception adapter. Runtime
    consumers receive only validated semantic tracks and LiDAR measurements.
    """

    regions: list[dict[str, Any]] = []
    object_geoms: list[tuple[str, float, float, float]] = []
    for geom_id in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or ""
        label = (
            "sidewalk"
            if name.startswith("sidewalk")
            else ("crosswalk" if name.startswith("xw") else "")
        )
        if label and int(model.geom_type[geom_id]) == int(mujoco.mjtGeom.mjGEOM_BOX):
            x, y = float(model.geom_pos[geom_id, 0]), float(model.geom_pos[geom_id, 1])
            sx, sy = float(model.geom_size[geom_id, 0]), float(model.geom_size[geom_id, 1])
            regions.append(
                {
                    "id": name,
                    "label": label,
                    "polygon": [
                        [x - sx, y - sy],
                        [x + sx, y - sy],
                        [x + sx, y + sy],
                        [x - sx, y + sy],
                    ],
                    "metadata": {
                        "diagnostics_only": True,
                        "terminal_clearance_m": 0.32,
                        "arrival_radius_m": 0.12,
                        # Robot center to observed obstacle surface. This
                        # includes footprint, the 0.8 m hard-stop envelope,
                        # arrival tolerance, and commissioning margin.
                        "target_obstacle_clearance_m": 1.30,
                    },
                }
            )
        if name.startswith("lamp_post_"):
            object_geoms.append(
                (
                    name,
                    float(model.geom_pos[geom_id, 0]),
                    float(model.geom_pos[geom_id, 1]),
                    float(model.geom_size[geom_id, 0]),
                )
            )

    objects: list[dict[str, Any]] = []
    for name, x, y, radius in object_geoms:
        support = next(
            (
                region["polygon"]
                for region in regions
                if region["label"] == "sidewalk"
                and _inside((x, y), tuple(tuple(point) for point in region["polygon"]))
            ),
            None,
        )
        metadata: dict[str, Any] = {
            "diagnostics_only": True,
            "aliases": ["lamp post", "streetlight", "street light"],
            "associated_lidar_ids": [name],
            "radius_m": radius,
            # At every accepted arrival, footprint-to-post clearance remains
            # above the 0.8 m hard stop while the physical surface gap remains
            # within the owner's common-sense 1 m "by the lamp" vicinity.
            "stand_off_m": 1.32,
            "arrival_radius_m": 0.06,
            "minimum_vicinity_radius_m": radius + ROBOT_FOOTPRINT_RADIUS_M + 0.8,
            "vicinity_radius_m": radius + ROBOT_FOOTPRINT_RADIUS_M + 1.0,
            "target_min_surface_clearance_m": 0.8,
            "non_target_obstacle_clearance_m": 1.25,
            "terminal_support_clearance_m": 0.32,
        }
        if support is not None:
            metadata["support_label"] = "sidewalk"
            metadata["support_polygon"] = support
        objects.append(
            {
                "id": name,
                "label": "lamppost",
                "position": [x, y, 0.0],
                "metadata": metadata,
            }
        )
    return regions, objects


def visible_city_semantics(
    regions: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    *,
    robot_x: float,
    robot_y: float,
    robot_heading: float,
    max_range_m: float = 12.0,
    half_fov_rad: float = math.radians(70.0),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    visible_regions = [
        _visible_payload(item)
        for item in regions
        if _visible(
            _polygon_center(item["polygon"]),
            robot_x,
            robot_y,
            robot_heading,
            max_range_m,
            half_fov_rad,
        )
    ]
    visible_objects = [
        _visible_payload(item)
        for item in objects
        if _visible(
            (float(item["position"][0]), float(item["position"][1])),
            robot_x,
            robot_y,
            robot_heading,
            max_range_m,
            half_fov_rad,
        )
    ]
    return visible_regions, visible_objects


def _visible_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "confidence": 0.98,
        "source": "simulator_semantic_camera",
        "reachable": True,
        "metadata": dict(item.get("metadata") or {}),
    }


def _visible(
    target: tuple[float, float],
    robot_x: float,
    robot_y: float,
    heading: float,
    max_range: float,
    half_fov: float,
) -> bool:
    dx, dy = target[0] - robot_x, target[1] - robot_y
    bearing = (math.atan2(dy, dx) - heading + math.pi) % (2.0 * math.pi) - math.pi
    return math.hypot(dx, dy) <= max_range and abs(bearing) <= half_fov


def _polygon_center(polygon: list[list[float]]) -> tuple[float, float]:
    return (
        sum(float(point[0]) for point in polygon) / len(polygon),
        sum(float(point[1]) for point in polygon) / len(polygon),
    )


def _inside(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside
