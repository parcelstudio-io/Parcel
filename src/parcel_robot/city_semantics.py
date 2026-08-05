"""City-block semantic extraction shared by live sim, headless, and eval.

Vocabulary table (prefix → class) with aliases drives both region and object
tracks. Goal-region metadata (polygons for regions, vicinity discs for objects)
is the single definition consumed by the scorer, grounder, and viewer.
"""

from __future__ import annotations

import math
from typing import Any

import mujoco

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M

# Longer prefixes must precede shorter siblings (tree_top_ before tree_).
OBJECT_PREFIX_TABLE: tuple[tuple[str, str], ...] = (
    ("lamp_post_", "lamppost"),
    ("bench_", "bench"),
    ("tree_top_", "tree"),  # canopy geoms fold into the tree instance
    ("tree_", "tree"),
    ("planter_", "planter"),
    ("bldg_", "building"),
)

REGION_PREFIX_TABLE: tuple[tuple[str, str], ...] = (
    ("sidewalk", "sidewalk"),
    ("xw", "crosswalk"),
    ("crosswalk", "crosswalk"),
)

CLASS_ALIASES: dict[str, tuple[str, ...]] = {
    "lamppost": ("lamp post", "streetlight", "street light", "lamp"),
    "bench": ("seat", "park bench", "bench seat"),
    "tree": ("trees", "street tree"),
    "planter": ("plant pot", "flower box", "pot"),
    "building": ("bldg", "storefront", "building face"),
    "sidewalk": ("pavement", "safe region"),
    "crosswalk": ("crossing", "zebra crossing", "cross walk"),
}

def extract_city_semantics(
    model: mujoco.MjModel,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract test-camera regions and landmarks from a MuJoCo city model.

    These coordinates remain inside the simulator perception adapter. Runtime
    consumers receive only validated semantic tracks and LiDAR measurements.
    """

    regions: list[dict[str, Any]] = []
    object_parts: dict[str, list[tuple[str, float, float, float]]] = {}

    for geom_id in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or ""
        region_label = _match_prefix(name, REGION_PREFIX_TABLE)
        if region_label and int(model.geom_type[geom_id]) == int(mujoco.mjtGeom.mjGEOM_BOX):
            x, y = float(model.geom_pos[geom_id, 0]), float(model.geom_pos[geom_id, 1])
            sx, sy = float(model.geom_size[geom_id, 0]), float(model.geom_size[geom_id, 1])
            polygon = [
                [x - sx, y - sy],
                [x + sx, y - sy],
                [x + sx, y + sy],
                [x - sx, y + sy],
            ]
            regions.append(
                {
                    "id": name if region_label != "crosswalk" else _crosswalk_id(name, regions),
                    "label": region_label,
                    "polygon": polygon,
                    "metadata": _region_metadata(region_label, polygon),
                }
            )
            continue

        object_label = _match_prefix(name, OBJECT_PREFIX_TABLE)
        if not object_label:
            continue
        instance_id = _instance_id(name, object_label)
        radius = _geom_radius_m(model, geom_id)
        object_parts.setdefault(instance_id, []).append(
            (
                name,
                float(model.geom_pos[geom_id, 0]),
                float(model.geom_pos[geom_id, 1]),
                radius,
            )
        )

    # Merge crosswalk stripes into one goal region when multiple xw* boxes exist.
    regions = _merge_crosswalk_regions(regions)

    objects: list[dict[str, Any]] = []
    for instance_id, parts in sorted(object_parts.items()):
        label = _label_for_instance(instance_id)
        xs = [p[1] for p in parts]
        ys = [p[2] for p in parts]
        x = sum(xs) / len(xs)
        y = sum(ys) / len(ys)
        radius = max(p[3] for p in parts)
        lidar_ids = sorted({p[0] for p in parts})
        support = next(
            (
                region["polygon"]
                for region in regions
                if region["label"] == "sidewalk"
                and _inside((x, y), tuple(tuple(point) for point in region["polygon"]))
            ),
            None,
        )
        metadata = _object_metadata(label, radius, lidar_ids)
        if support is not None:
            metadata["support_label"] = "sidewalk"
            metadata["support_polygon"] = support
        # Goal-region disc shared with scorer/viewer.
        metadata["goal_region"] = {
            "kind": "disc",
            "center": [x, y],
            "radius_m": metadata["vicinity_radius_m"],
            "anchor_entity": instance_id,
        }
        objects.append(
            {
                "id": instance_id,
                "label": label,
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


def vocabulary_aliases() -> dict[str, tuple[str, ...]]:
    """Shared alias table for grounder + semantics (N-O1 / N-O2)."""

    return {key: tuple(values) for key, values in CLASS_ALIASES.items()}


def _region_metadata(label: str, polygon: list[list[float]]) -> dict[str, Any]:
    return {
        "diagnostics_only": True,
        "aliases": list(CLASS_ALIASES.get(label, ())),
        "terminal_clearance_m": 0.32,
        "arrival_radius_m": 0.12,
        # Robot center to observed obstacle surface. This
        # includes footprint, the 0.8 m hard-stop envelope,
        # arrival tolerance, and commissioning margin.
        "target_obstacle_clearance_m": 1.30,
        "goal_region": {
            "kind": "polygon",
            "polygon": polygon,
            "anchor_entity": None,
        },
    }


def _object_metadata(
    label: str,
    radius: float,
    lidar_ids: list[str],
) -> dict[str, Any]:
    stand_off = radius + ROBOT_FOOTPRINT_RADIUS_M + 0.8 + 0.06 + 0.04
    # Lampposts keep the historical commissioning standoff.
    if label == "lamppost":
        stand_off = 1.32
    vicinity = radius + ROBOT_FOOTPRINT_RADIUS_M + 1.0
    if label == "building":
        # Buildings are approached as "near the face", not inside.
        stand_off = max(stand_off, radius + ROBOT_FOOTPRINT_RADIUS_M + 1.0)
        vicinity = max(vicinity, stand_off + 0.3)
    return {
        "diagnostics_only": True,
        "aliases": list(CLASS_ALIASES.get(label, ())),
        "associated_lidar_ids": list(lidar_ids),
        "radius_m": radius,
        "stand_off_m": stand_off,
        "arrival_radius_m": 0.06,
        "minimum_vicinity_radius_m": radius + ROBOT_FOOTPRINT_RADIUS_M + 0.8,
        "vicinity_radius_m": vicinity,
        "target_min_surface_clearance_m": 0.8,
        "non_target_obstacle_clearance_m": 1.25,
        "terminal_support_clearance_m": 0.32,
    }


def _match_prefix(name: str, table: tuple[tuple[str, str], ...]) -> str:
    for prefix, label in table:
        if name.startswith(prefix):
            return label
    return ""


def _instance_id(name: str, label: str) -> str:
    if label == "bench":
        return "bench_1"
    if label == "tree":
        # tree_1 / tree_top_1 → tree_1
        suffix = name.rsplit("_", 1)[-1]
        if suffix.isdigit():
            return f"tree_{suffix}"
        return name
    if label == "lamppost":
        return name  # lamp_post_1
    return name


def _label_for_instance(instance_id: str) -> str:
    if instance_id.startswith("lamp_post_"):
        return "lamppost"
    if instance_id.startswith("bench_"):
        return "bench"
    if instance_id.startswith("tree_"):
        return "tree"
    if instance_id.startswith("planter_"):
        return "planter"
    if instance_id.startswith("bldg_"):
        return "building"
    return "object"


def _geom_radius_m(model: mujoco.MjModel, geom_id: int) -> float:
    geom_type = int(model.geom_type[geom_id])
    size = model.geom_size[geom_id]
    if geom_type == int(mujoco.mjtGeom.mjGEOM_SPHERE):
        return float(size[0])
    if geom_type == int(mujoco.mjtGeom.mjGEOM_CYLINDER):
        return float(size[0])
    # Box: horizontal circumscribed radius.
    return math.hypot(float(size[0]), float(size[1]))


def _crosswalk_id(name: str, regions: list[dict[str, Any]]) -> str:
    # Keep individual stripe ids during extraction; merge later.
    return name


def _merge_crosswalk_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sidewalks = [r for r in regions if r["label"] != "crosswalk"]
    stripes = [r for r in regions if r["label"] == "crosswalk"]
    if not stripes:
        return regions
    xs = [p[0] for stripe in stripes for p in stripe["polygon"]]
    ys = [p[1] for stripe in stripes for p in stripe["polygon"]]
    polygon = [
        [min(xs), min(ys)],
        [max(xs), min(ys)],
        [max(xs), max(ys)],
        [min(xs), max(ys)],
    ]
    merged = {
        "id": "crosswalk",
        "label": "crosswalk",
        "polygon": polygon,
        "metadata": _region_metadata("crosswalk", polygon),
    }
    return sidewalks + [merged]


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
