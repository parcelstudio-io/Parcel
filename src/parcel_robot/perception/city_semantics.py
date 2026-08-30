"""City-block semantic extraction shared by live sim, headless, and eval.

Vocabulary table (prefix → class) with aliases drives both region and object
tracks. Goal-region metadata (polygons for regions, near relative bands for
objects) is the single arrival authority consumed by navigator verification,
the NAV_INSTRUCT scorer, and the viewer (K0).

The vocabulary itself is **no longer literal here**: prefixes, class kinds, and
aliases are read from the per-scene semantics sidecar
(``configs/scenes/city_block.semantics.yaml``) by
:mod:`parcel_robot.perception.scene_semantics`, which fails closed on anything it does not
recognize. ``tests/test_scene_semantics.py`` pins the derived tables
bit-for-bit against the literals that used to live in this module. Geometry is
still read from the MJCF and never from the sidecar.
"""

from __future__ import annotations

import math
from typing import Any

import mujoco

from parcel_robot.instructnav.scoring import object_near_envelope_m, object_near_goal_region
from parcel_robot.navigation.poi_admission import (
    publish_scene_semantics,
    scene_id_from_model,
)
from parcel_robot.perception.scene_semantics import scene_semantics

_SCENE = scene_semantics()

#: Geom-name prefix → object class. Ordered by the sidecar, which enforces that
#: a longer prefix precedes any shorter one it starts with (tree_top_ / tree_).
OBJECT_PREFIX_TABLE: tuple[tuple[str, str], ...] = _SCENE.object_prefix_table()

REGION_PREFIX_TABLE: tuple[tuple[str, str], ...] = _SCENE.region_prefix_table()

CLASS_ALIASES: dict[str, tuple[str, ...]] = _SCENE.alias_table()

#: Extra per-class attribute metadata declared by the sidecar (empty today).
#: Keys are validated against ``navigation.attributes.SIZE_METADATA_KEYS`` at
#: load time, so the attribute matcher and the sidecar cannot drift: the
#: matcher owns which keys mean "size", the sidecar owns their values.
CLASS_ATTRIBUTE_METADATA: dict[str, dict[str, float]] = {
    item.name: item.metadata_dict() for item in _SCENE.classes
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
        # Goal-region band shared with navigator verification + scorer (K0).
        metadata["goal_region"] = object_near_goal_region(
            (x, y),
            radius,
            label=label,
            entity_id=instance_id,
        ).as_dict()
        objects.append(
            {
                "id": instance_id,
                "label": label,
                "position": [x, y, 0.0],
                "metadata": metadata,
            }
        )
    # Card C1 (POI-ORACLE-1), follow-up F1. The loaded scene publishes ITSELF —
    # its MJCF `model` name and what it declares — so `navigation.poi_admission`
    # can refuse the demo POI table on any scene but the one it was surveyed on.
    # This is the one place that holds both the compiled model (the identity)
    # and the specs, and every venue passes through it before it builds a
    # navigator, which is what makes the answer available in `parse`, before the
    # first observation exists.
    publish_scene_semantics(regions, objects, scene_id=scene_id_from_model(model))
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
    stand_off, minimum, vicinity = object_near_envelope_m(radius, label=label)
    return {
        "diagnostics_only": True,
        # Sidecar-declared attribute metadata (empty for every class today, so
        # this is bit-for-bit identical). This is the seam by which a scene can
        # supply, e.g., a per-class height the attribute matcher can read
        # without any code change: navigation/attributes.py already looks for
        # height_m and finds nothing today.
        **CLASS_ATTRIBUTE_METADATA.get(label, {}),
        "aliases": list(CLASS_ALIASES.get(label, ())),
        "associated_lidar_ids": list(lidar_ids),
        "radius_m": radius,
        "stand_off_m": stand_off,
        "arrival_radius_m": 0.06,
        "minimum_vicinity_radius_m": minimum,
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
    """Class of an instance id, from the same prefix table extraction used.

    This used to be a second hand-written copy of ``OBJECT_PREFIX_TABLE``; a
    class added to the sidecar but forgotten here would have extracted with a
    label of ``"object"`` and grounded against nothing.
    """

    return _match_prefix(instance_id, OBJECT_PREFIX_TABLE) or "object"


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
