"""Scripted 60 m traverses over the shipped MuJoCo city scenes, at 10 Hz.

The sensor is ``simulation/mujoco_lidar.raycast_planar_scan`` — the same
occlusion-true ray engine ``HeadlessCityWorld.observe`` uses, at the same
``DEFAULT_ROBOT_PROFILE.scan_height_m`` — so the localizer is fed exactly the
scan the navigator already consumes, not a bench-special one.  The base is
placed kinematically (``qpos`` + ``mj_forward``), which is what
``HeadlessCityWorld._place_robot`` does; contact physics is irrelevant to a
localization bench and would only add a second unmodelled error source.

**Where the circuits come from.**  Both rectangles were chosen by an exhaustive
search over axis-aligned circuits on a 0.1 m clearance grid of each scene
(``truth_minimum_clearance``), keeping the widest-clearance circuit with a
perimeter over ~24 m.  city_block: 27.5 m perimeter, 0.58 m minimum clearance;
city_block_b: 24.5 m, 0.62 m.  60 m is therefore 2.2 and 2.4 laps — the
revisits are deliberate, because a scan-matching localizer with no loop closure
is exactly the thing whose behaviour on a revisit needs measuring.

**Corners are filleted, not pivoted.**  A stop-and-turn corner would hand the
matcher a pure rotation with no translation, which is both unrepresentative of
a walking dog and the easiest case for ICP; a 0.6 m fillet keeps heading
changing while the body keeps moving.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np

from parcel_robot.localization.contract import ScanFrame
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE
from parcel_robot.simulation.mujoco_lidar import PlanarScan, raycast_planar_scan

SCENE_DIR = Path(__file__).resolve().parents[3] / "src" / "parcel_robot" / "scenes"

#: ``(x_min, x_max, y_min, y_max)`` of each scene's traverse circuit.
CIRCUITS: dict[str, tuple[float, float, float, float]] = {
    "city_block": (-6.00, 4.50, -2.25, 1.00),
    "city_block_b": (-2.00, 2.25, -4.50, 3.50),
}

TRAVERSE_LENGTH_M = 60.0
STEP_M = 0.1
CONTROL_HZ = 10.0
FILLET_M = 0.6


@dataclass(frozen=True)
class TraversePose:
    """One scripted 10 Hz sample: sim truth, in metres and radians."""

    t_s: float
    x: float
    y: float
    yaw: float

    @property
    def xy_yaw(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.yaw)


def _fillet_corner(
    previous: tuple[float, float],
    corner: tuple[float, float],
    following: tuple[float, float],
    radius: float,
    step: float,
) -> list[tuple[float, float]]:
    """Circular-arc cut of one polygon corner, sampled at ``step`` arc length."""

    into = np.array(corner) - np.array(previous)
    out = np.array(following) - np.array(corner)
    into = into / max(1e-9, float(np.linalg.norm(into)))
    out = out / max(1e-9, float(np.linalg.norm(out)))
    start = np.array(corner) - into * radius
    end = np.array(corner) + out * radius
    centre = start + np.array([-into[1], into[0]]) * radius * _turn_sign(into, out)
    a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
    a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
    sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    count = max(2, int(abs(sweep) * radius / step))
    return [
        (
            float(centre[0] + radius * math.cos(a0 + sweep * k / count)),
            float(centre[1] + radius * math.sin(a0 + sweep * k / count)),
        )
        for k in range(count + 1)
    ]


def _turn_sign(into: np.ndarray, out: np.ndarray) -> float:
    cross = float(into[0] * out[1] - into[1] * out[0])
    return 1.0 if cross >= 0.0 else -1.0


def circuit_polyline(rect: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    """The rounded rectangle, as a dense closed polyline."""

    x0, x1, y0, y1 = rect
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    points: list[tuple[float, float]] = []
    for index, corner in enumerate(corners):
        previous = corners[index - 1]
        following = corners[(index + 1) % len(corners)]
        points.extend(_fillet_corner(previous, corner, following, FILLET_M, STEP_M))
    return points


def traverse_poses(
    scene: str,
    *,
    length_m: float = TRAVERSE_LENGTH_M,
    step_m: float = STEP_M,
) -> list[TraversePose]:
    """Resample the circuit at constant arc length until ``length_m`` is walked."""

    polyline = circuit_polyline(CIRCUITS[scene])
    poses: list[TraversePose] = []
    travelled = 0.0
    index = 0
    cursor = np.array(polyline[0], dtype=np.float64)
    while travelled <= length_m:
        target = np.array(polyline[(index + 1) % len(polyline)], dtype=np.float64)
        span = target - cursor
        distance = float(np.linalg.norm(span))
        if distance < 1e-9:
            index += 1
            continue
        if distance < step_m:
            cursor = target
            index += 1
            continue
        direction = span / distance
        cursor = cursor + direction * step_m
        travelled += step_m
        poses.append(
            TraversePose(
                t_s=len(poses) / CONTROL_HZ,
                x=float(cursor[0]),
                y=float(cursor[1]),
                yaw=math.atan2(float(direction[1]), float(direction[0])),
            )
        )
    return poses


class SceneTraverse:
    """A headless MuJoCo scene the bench can place a body in and scan from."""

    def __init__(self, scene: str) -> None:
        self.scene = scene
        path = SCENE_DIR / f"{scene}.xml"
        self.model = mujoco.MjModel.from_xml_path(str(path))
        self.data = mujoco.MjData(self.model)
        if self.model.nkey > 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, 0)
        else:
            mujoco.mj_resetData(self.model, self.data)
        free = [
            joint
            for joint in range(self.model.njnt)
            if self.model.jnt_type[joint] == mujoco.mjtJoint.mjJNT_FREE
        ]
        self.robot_body_id = int(self.model.jnt_bodyid[free[0]]) if free else 0
        self.z = float(self.data.qpos[2]) if self.model.nq >= 3 else 0.445

    def place(self, x: float, y: float, yaw: float) -> None:
        self.data.qpos[:3] = (x, y, self.z)
        half = yaw * 0.5
        self.data.qpos[3:7] = (math.cos(half), 0.0, 0.0, math.sin(half))
        if self.model.nv >= 6:
            self.data.qvel[:6] = 0.0
        mujoco.mj_forward(self.model, self.data)

    def scan(self, x: float, y: float, yaw: float, rng: np.random.Generator) -> PlanarScan:
        return raycast_planar_scan(
            self.model,
            self.data,
            robot_x=x,
            robot_y=y,
            robot_heading=yaw,
            robot_body_id=self.robot_body_id,
            sensor_z_m=DEFAULT_ROBOT_PROFILE.scan_height_m,
            rng=rng,
        )


def scan_points(scan: PlanarScan) -> np.ndarray:
    """Body-frame ``(N, 2)`` returns; NaN (ignored) and no-return rays dropped.

    This is the only place the simulator's NaN / ``range_max`` convention is
    read.  ``contract.ScanFrame`` receives points, so the localizer never learns
    which simulator produced them.
    """

    ranges = np.asarray(scan.ranges_m, dtype=np.float64)
    angles = scan.angle_min_rad + scan.angle_increment_rad * np.arange(len(ranges))
    keep = np.isfinite(ranges) & (ranges > scan.range_min_m) & (ranges < scan.range_max_m - 1e-6)
    kept_ranges = ranges[keep]
    kept_angles = angles[keep]
    return np.stack(
        [kept_ranges * np.cos(kept_angles), kept_ranges * np.sin(kept_angles)], axis=1
    )


def build_scan_frame(scan: PlanarScan, stamp_s: float) -> ScanFrame:
    return ScanFrame(points_xy=scan_points(scan), stamp_ns=round(stamp_s * 1e9))


def scan_frame_from_ranges(
    ranges: tuple[float, ...] | None,
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    range_min_m: float,
    range_max_m: float,
    stamp_s: float,
) -> ScanFrame | None:
    """The same conversion for a ``SimObservation``'s already-flattened scan.

    ``HeadlessCityWorld.observe`` publishes the ring as bare tuples on the
    observation rather than as a :class:`PlanarScan`, so the drift-ladder
    harness rebuilds one here instead of re-raycasting the world (which would
    draw from the scan RNG a second time and move every downstream result).
    """

    if not ranges:
        return None
    scan = PlanarScan(
        ranges_m=tuple(float(value) for value in ranges),
        angle_min_rad=float(angle_min_rad),
        angle_increment_rad=float(angle_increment_rad),
        range_min_m=float(range_min_m),
        range_max_m=float(range_max_m),
    )
    return build_scan_frame(scan, stamp_s)
