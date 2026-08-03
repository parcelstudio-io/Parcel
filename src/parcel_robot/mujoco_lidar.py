from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import mujoco

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M, ROBOT_OBSTACLE_HEIGHT_M

MAX_LIDAR_OBSTACLES = 64
LIDAR_SURFACE_SAMPLE_SPACING_M = 0.5
MAX_SURFACE_SAMPLES_PER_GEOM = 48
LIDAR_ANGULAR_SECTORS = 32

_BOX = int(mujoco.mjtGeom.mjGEOM_BOX)
_SPHERE = int(mujoco.mjtGeom.mjGEOM_SPHERE)
_CYLINDER = int(mujoco.mjtGeom.mjGEOM_CYLINDER)
_CAPSULE = int(mujoco.mjtGeom.mjGEOM_CAPSULE)
_SUPPORTED_GEOM_TYPES = {_BOX, _SPHERE, _CYLINDER, _CAPSULE}


@dataclass(frozen=True)
class MujocoLidarHit:
    """Closest planar obstacle-surface return for one MuJoCo geometry."""

    obstacle_id: str
    geom_id: int
    distance_m: float
    signed_clearance_m: float
    bearing_rad: float
    surface_x: float
    surface_y: float


def scan_mujoco_lidar(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_ids: Iterable[int],
    *,
    robot_x: float,
    robot_y: float,
    robot_heading: float,
    robot_radius_m: float = ROBOT_FOOTPRINT_RADIUS_M,
    obstacle_height_m: float = ROBOT_OBSTACLE_HEIGHT_M,
    limit: int = MAX_LIDAR_OBSTACLES,
    surface_spacing_m: float = LIDAR_SURFACE_SAMPLE_SPACING_M,
) -> list[MujocoLidarHit]:
    """Return bounded surface measurements ordered by clearance.

    Every supported geometry contributes its exact closest point. Boxes also
    contribute deterministic perimeter samples so a local swept-path check
    cannot mistake one point on a long building face for the whole obstacle.
    """

    if limit <= 0:
        raise ValueError("LiDAR result limit must be positive")
    if not math.isfinite(surface_spacing_m) or surface_spacing_m <= 0.0:
        raise ValueError("LiDAR surface spacing must be positive and finite")
    primary_hits = []
    perimeter_hits = []
    for geom_id in geom_ids:
        hit = planar_geom_surface_hit(
            model,
            data,
            int(geom_id),
            robot_x=robot_x,
            robot_y=robot_y,
            robot_heading=robot_heading,
            robot_radius_m=robot_radius_m,
            obstacle_height_m=obstacle_height_m,
        )
        if hit is not None:
            # Keep the exact closest return separate from optional box samples.
            # A large nearby facade must not consume the bounded scan before a
            # distinct geometry (and potential hazard) is considered.
            primary_hits.append(hit)
            if int(model.geom_type[int(geom_id)]) == _BOX:
                perimeter_hits.extend(
                    _box_perimeter_hits(
                        model,
                        data,
                        int(geom_id),
                        hit.obstacle_id,
                        robot_x,
                        robot_y,
                        robot_heading,
                        robot_radius_m,
                        surface_spacing_m,
                        closest=(hit.surface_x, hit.surface_y),
                    )
                )
    return _bounded_angular_hits(primary_hits, perimeter_hits, limit)


def _bounded_angular_hits(
    primary_hits: list[MujocoLidarHit],
    perimeter_hits: list[MujocoLidarHit],
    limit: int,
) -> list[MujocoLidarHit]:
    """Select a deterministic, angularly fair bounded scan.

    Exact closest-per-geometry returns have priority over optional perimeter
    samples. Within each group, reserve its closest return in every occupied
    angular sector before filling remaining capacity by range. This prevents a
    dense cluster behind the robot from evicting the only forward hazard while
    retaining useful samples along long box faces when capacity permits.
    """

    ordered_primary = sorted(primary_hits, key=_hit_sort_key)
    ordered_perimeter = sorted(perimeter_hits, key=_hit_sort_key)
    if len(ordered_primary) + len(ordered_perimeter) <= limit:
        return sorted(ordered_primary + ordered_perimeter, key=_hit_sort_key)

    selected: list[MujocoLidarHit] = []
    selected_ids: set[int] = set()
    sector_count = min(LIDAR_ANGULAR_SECTORS, limit)

    def add(hit: MujocoLidarHit) -> None:
        if len(selected) < limit and id(hit) not in selected_ids:
            selected.append(hit)
            selected_ids.add(id(hit))

    def add_sector_representatives(hits: list[MujocoLidarHit]) -> None:
        representatives: dict[int, MujocoLidarHit] = {}
        for hit in hits:
            sector = _bearing_sector(hit.bearing_rad, sector_count)
            representatives.setdefault(sector, hit)
        for sector in sorted(representatives):
            add(representatives[sector])

    add_sector_representatives(ordered_primary)
    for hit in ordered_primary:
        add(hit)
    if len(selected) < limit:
        add_sector_representatives(ordered_perimeter)
    for hit in ordered_perimeter:
        add(hit)

    return sorted(selected, key=_hit_sort_key)


def _bearing_sector(bearing_rad: float, sector_count: int) -> int:
    normalized = (_wrap(bearing_rad) + math.pi) / (2.0 * math.pi)
    return min(sector_count - 1, int(normalized * sector_count))


def _hit_sort_key(hit: MujocoLidarHit) -> tuple[float, str, int, float, float]:
    return (
        hit.distance_m,
        hit.obstacle_id,
        hit.geom_id,
        hit.surface_x,
        hit.surface_y,
    )


def planar_geom_surface_hit(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
    *,
    robot_x: float,
    robot_y: float,
    robot_heading: float = 0.0,
    robot_radius_m: float = ROBOT_FOOTPRINT_RADIUS_M,
    obstacle_height_m: float = ROBOT_OBSTACLE_HEIGHT_M,
) -> MujocoLidarHit | None:
    """Measure clearance and bearing to a geometry's actual closest surface.

    Boxes use their world orientation and closest rectangle point. Circular
    footprints use the facing circumference point. This prevents an elongated
    box's center bearing from falsely moving a nearby surface outside the
    controller's travel corridor.
    """

    if not 0 <= geom_id < model.ngeom:
        raise IndexError(f"MuJoCo geom id is out of range: {geom_id}")
    if not math.isfinite(robot_radius_m) or robot_radius_m < 0.0:
        raise ValueError("robot radius must be finite and non-negative")
    if not math.isfinite(obstacle_height_m):
        raise ValueError("obstacle height must be finite")
    geom_type = int(model.geom_type[geom_id])
    if geom_type not in _SUPPORTED_GEOM_TYPES:
        return None
    gx, gy, gz = (float(value) for value in data.geom_xpos[geom_id, :3])
    if gz - _world_vertical_half_extent(model, data, geom_id, geom_type) > obstacle_height_m:
        return None

    if geom_type == _BOX:
        signed_center_distance, surface_x, surface_y = _box_surface(
            model,
            data,
            geom_id,
            robot_x,
            robot_y,
            gx,
            gy,
        )
    else:
        radius = float(model.geom_size[geom_id, 0])
        signed_center_distance, surface_x, surface_y = _circle_surface(
            robot_x,
            robot_y,
            gx,
            gy,
            radius,
        )
    signed_clearance = signed_center_distance - robot_radius_m
    dx, dy = surface_x - robot_x, surface_y - robot_y
    surface_bearing = math.atan2(dy, dx) if math.hypot(dx, dy) > 1e-12 else 0.0
    name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
    return MujocoLidarHit(
        obstacle_id=name or f"geom-{geom_id}",
        geom_id=geom_id,
        distance_m=max(0.0, signed_clearance),
        signed_clearance_m=signed_clearance,
        bearing_rad=_wrap(surface_bearing - robot_heading),
        surface_x=surface_x,
        surface_y=surface_y,
    )


def _box_surface(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
    robot_x: float,
    robot_y: float,
    gx: float,
    gy: float,
) -> tuple[float, float, float]:
    matrix = data.geom_xmat[geom_id]
    r00, r01 = float(matrix[0]), float(matrix[1])
    r10, r11 = float(matrix[3]), float(matrix[4])
    dx, dy = robot_x - gx, robot_y - gy
    local_x = r00 * dx + r10 * dy
    local_y = r01 * dx + r11 * dy
    size_x, size_y = (float(value) for value in model.geom_size[geom_id, :2])
    outside_x = max(abs(local_x) - size_x, 0.0)
    outside_y = max(abs(local_y) - size_y, 0.0)
    if outside_x > 0.0 or outside_y > 0.0:
        closest_x = min(size_x, max(-size_x, local_x))
        closest_y = min(size_y, max(-size_y, local_y))
        signed_distance = math.hypot(outside_x, outside_y)
    else:
        faces = (
            (size_x - local_x, size_x, local_y),
            (size_x + local_x, -size_x, local_y),
            (size_y - local_y, local_x, size_y),
            (size_y + local_y, local_x, -size_y),
        )
        penetration, closest_x, closest_y = min(faces, key=lambda item: item[0])
        signed_distance = -penetration
    surface_x = gx + r00 * closest_x + r01 * closest_y
    surface_y = gy + r10 * closest_x + r11 * closest_y
    return signed_distance, surface_x, surface_y


def _circle_surface(
    robot_x: float,
    robot_y: float,
    gx: float,
    gy: float,
    radius: float,
) -> tuple[float, float, float]:
    dx, dy = robot_x - gx, robot_y - gy
    center_distance = math.hypot(dx, dy)
    if center_distance <= 1e-12:
        return -radius, gx + radius, gy
    scale = radius / center_distance
    surface_x = gx + dx * scale
    surface_y = gy + dy * scale
    signed_distance = (
        center_distance - radius
        if center_distance >= radius
        else -(radius - center_distance)
    )
    return signed_distance, surface_x, surface_y


def _box_perimeter_hits(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
    obstacle_id: str,
    robot_x: float,
    robot_y: float,
    robot_heading: float,
    robot_radius_m: float,
    spacing_m: float,
    *,
    closest: tuple[float, float],
) -> list[MujocoLidarHit]:
    size_x, size_y = (float(value) for value in model.geom_size[geom_id, :2])
    perimeter = 4.0 * (size_x + size_y)
    sample_count = min(
        MAX_SURFACE_SAMPLES_PER_GEOM,
        max(4, math.ceil(perimeter / spacing_m)),
    )
    local_points = [
        _rectangle_perimeter_point(
            size_x,
            size_y,
            perimeter * index / sample_count,
        )
        for index in range(sample_count)
    ]

    gx, gy = (float(value) for value in data.geom_xpos[geom_id, :2])
    matrix = data.geom_xmat[geom_id]
    r00, r01 = float(matrix[0]), float(matrix[1])
    r10, r11 = float(matrix[3]), float(matrix[4])
    hits = []
    for local_x, local_y in local_points:
        surface_x = gx + r00 * local_x + r01 * local_y
        surface_y = gy + r10 * local_x + r11 * local_y
        if math.hypot(surface_x - closest[0], surface_y - closest[1]) <= 1e-9:
            continue
        dx, dy = surface_x - robot_x, surface_y - robot_y
        surface_distance = math.hypot(dx, dy)
        signed_clearance = surface_distance - robot_radius_m
        hits.append(
            MujocoLidarHit(
                obstacle_id=obstacle_id,
                geom_id=geom_id,
                distance_m=max(0.0, signed_clearance),
                signed_clearance_m=signed_clearance,
                bearing_rad=_wrap(math.atan2(dy, dx) - robot_heading),
                surface_x=surface_x,
                surface_y=surface_y,
            )
        )
    return hits


def _rectangle_perimeter_point(
    size_x: float,
    size_y: float,
    distance: float,
) -> tuple[float, float]:
    horizontal = 2.0 * size_x
    vertical = 2.0 * size_y
    if distance < horizontal:
        return -size_x + distance, -size_y
    distance -= horizontal
    if distance < vertical:
        return size_x, -size_y + distance
    distance -= vertical
    if distance < horizontal:
        return size_x - distance, size_y
    distance -= horizontal
    return -size_x, size_y - distance


def _world_vertical_half_extent(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
    geom_type: int,
) -> float:
    if geom_type == _SPHERE:
        return float(model.geom_size[geom_id, 0])
    matrix = data.geom_xmat[geom_id]
    if geom_type == _BOX:
        return sum(
            abs(float(matrix[6 + axis])) * float(model.geom_size[geom_id, axis])
            for axis in range(3)
        )
    radius = float(model.geom_size[geom_id, 0])
    half_length = float(model.geom_size[geom_id, 1])
    axis_z = abs(float(matrix[8]))
    if geom_type == _CAPSULE:
        return radius + axis_z * half_length
    radial_z = radius * math.sqrt(max(0.0, 1.0 - axis_z * axis_z))
    return axis_z * half_length + radial_z


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
