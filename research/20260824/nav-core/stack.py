"""The physical-shaped input stack: drifting ODOM, scan-matched MAP, one body.

Everything the arms see comes through here, and nothing in here hands the
navigator a truth value.  Sim truth reaches exactly one object — the ODOM
source, standing in for proprioception, which is the H7 bench's rule.  The
navigator reads MAP through the ``PoseProvider`` seam; the obstacle channel is
derived from the *scan*, not from the room's rectangles; and
``NavObservation.position`` carries the robot's own MAP estimate rather than
truth, because a study about non-oracle inputs cannot leave a truth field on
the observation for some layer to read.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from room import RoomWorld

from parcel_robot.backends.base import (
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SimObservation,
    VelocityCommand,
)
from parcel_robot.localization.contract import ScanFrame
from parcel_robot.localization.gicp_provider import ScanMatchConfig, ScanMatchLocalizer
from parcel_robot.localization.pose_adapter import LocalizedPoseProvider
from parcel_robot.navigation.base import NavObservation
from parcel_robot.pose import POSE_PROVIDER_KEY, Frame, PoseEstimate, provider_from_config
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE
from parcel_robot.simulation.mujoco_lidar import PlanarScan

CONTROL_HZ = 10.0
CONTROL_DT_S = 1.0 / CONTROL_HZ
#: The pre-registered ODOM tier.  ``configs/navigation/pose.yaml``.
ODOM_PROFILE = "calibrated_go2"
#: Pre-registered: one 2 s scan dropout per episode.
SCAN_DROPOUT_S = 2.0
#: The owner is not in this study; the tracks below park them out of the room
#: so the person channel is inert rather than absent.
_OWNER_XY = (60.0, 60.0)


def scan_points(scan: PlanarScan) -> np.ndarray:
    """Body-frame ``(N, 2)`` returns; ignored and no-return rays dropped."""

    ranges = np.asarray(scan.ranges_m, dtype=np.float64)
    angles = scan.angle_min_rad + scan.angle_increment_rad * np.arange(len(ranges))
    keep = (
        np.isfinite(ranges)
        & (ranges > scan.range_min_m)
        & (ranges < scan.range_max_m - 1e-6)
    )
    return np.stack(
        [ranges[keep] * np.cos(angles[keep]), ranges[keep] * np.sin(angles[keep])],
        axis=1,
    )


def nearest_from_scan(scan: PlanarScan | None) -> tuple[float | None, float | None]:
    """``(clearance_m, bearing_rad)`` of the closest return, or ``(None, None)``.

    Clearance is surface-to-body-circle, the convention
    ``SimObservation.nearest_obstacle_m`` carries, so the reactive gate reads
    the same quantity it reads in the product.
    """

    if scan is None:
        return None, None
    ranges = np.asarray(scan.ranges_m, dtype=np.float64)
    keep = (
        np.isfinite(ranges)
        & (ranges > scan.range_min_m)
        & (ranges < scan.range_max_m - 1e-6)
    )
    if not keep.any():
        return None, None
    index = int(np.flatnonzero(keep)[np.argmin(ranges[keep])])
    bearing = scan.angle_min_rad + scan.angle_increment_rad * index
    clearance = float(ranges[index]) - DEFAULT_ROBOT_PROFILE.footprint_radius_m
    return max(0.0, clearance), float(math.atan2(math.sin(bearing), math.cos(bearing)))


@dataclass
class Body:
    """A kinematically integrated planar body.  Velocities are body-frame."""

    x: float
    y: float
    yaw: float
    contacts: int = 0
    path_m: float = 0.0
    _touching: bool = field(default=False, repr=False)

    def step(self, world: RoomWorld, command: VelocityCommand) -> None:
        cos_t, sin_t = math.cos(self.yaw), math.sin(self.yaw)
        dx = (command.vx * cos_t - command.vy * sin_t) * CONTROL_DT_S
        dy = (command.vx * sin_t + command.vy * cos_t) * CONTROL_DT_S
        proposed_x, proposed_y = self.x + dx, self.y + dy
        if world.clearance_m(proposed_x, proposed_y) <= 0.0:
            # Blocked rather than penetrating, as ``HeadlessCityWorld._integrate``
            # does; the contact is edge-counted so one continuous press is one
            # event.
            if not self._touching:
                self.contacts += 1
                self._touching = True
        else:
            self._touching = False
            self.path_m += math.hypot(dx, dy)
            self.x, self.y = proposed_x, proposed_y
        self.yaw = math.atan2(
            math.sin(self.yaw + command.vyaw * CONTROL_DT_S),
            math.cos(self.yaw + command.vyaw * CONTROL_DT_S),
        )

    @property
    def pose(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.yaw)


class PoseStack:
    """``DriftingOdomProvider(calibrated_go2)`` under ``ScanMatchLocalizer``.

    The kidnap is injected the way H7 injects it: the ODOM feed stays
    continuous across the jump (the post-kidnap truth re-expressed relative to
    the landing pose and re-attached where the body left), so proprioception
    cannot see it and the only evidence is that the scan stopped matching.
    """

    def __init__(self, seed_offset: int = 0) -> None:
        odom = provider_from_config(profile=ODOM_PROFILE)
        params = odom.params
        odom.params = type(params)(
            **{
                **{f: getattr(params, f) for f in params.__dataclass_fields__},
                "seed": int(params.seed) + int(seed_offset),
            }
        )
        self.localizer = ScanMatchLocalizer(ScanMatchConfig())
        self._scan: ScanFrame | None = None
        self.provider = LocalizedPoseProvider(
            self.localizer, odom, scan_source=lambda _t: self._scan
        )
        self.provider.reset()
        self._anchor: tuple[float, float, float] | None = None
        self._landing: tuple[float, float, float] | None = None

    def kidnap(self, truth_before: tuple[float, float, float],
               truth_after: tuple[float, float, float]) -> None:
        """Re-base the ODOM feed so the jump is invisible to proprioception."""

        self._anchor = truth_before
        self._landing = truth_after

    def _feed(self, truth: tuple[float, float, float]) -> tuple[float, float, float]:
        if self._anchor is None or self._landing is None:
            return truth
        from parcel_robot.localization.contract import compose_se2, invert_se2

        return compose_se2(self._anchor, compose_se2(invert_se2(self._landing), truth))

    def update(
        self, truth: tuple[float, float, float], scan: PlanarScan | None, t_s: float
    ) -> Any:
        self._scan = (
            None
            if scan is None
            else ScanFrame(points_xy=scan_points(scan), stamp_ns=round(t_s * 1e9))
        )
        return self.provider.update_truth(*self._feed(truth), stamp_monotonic_s=t_s)

    def map_pose(self) -> PoseEstimate:
        return self.provider.get_pose(Frame.MAP)

    def odom_pose(self) -> PoseEstimate:
        return self.provider.get_pose(Frame.ODOM)


def dropout_window(episode: int, seed_index: int) -> tuple[float, float]:
    """The episode's 2 s scan dropout, pre-registered as a function of the ids.

    Deterministic and spread over the first half of a nominal traverse, so the
    gap lands mid-leg rather than always at the same phase of the mission.
    """

    start = 3.0 + ((episode * 7 + seed_index * 11) % 9) * 0.5
    return (start, start + SCAN_DROPOUT_S)


def sim_observation(
    *,
    believed: PoseEstimate,
    scan: PlanarScan | None,
    contact: bool,
    t_s: float,
) -> SimObservation:
    """What the reactive safety gate reads.  Pose is BELIEVED, not truth."""

    clearance, bearing = nearest_from_scan(scan)
    obstacles = (
        ()
        if clearance is None
        else (LidarObstacle(distance_m=clearance, bearing_rad=bearing or 0.0,
                            obstacle_id="scan_return"),)
    )
    return SimObservation(
        timestamp=t_s,
        robot=RobotPose(x=believed.x, y=believed.y, z=0.0, yaw=believed.yaw),
        owner=OwnerTrack(x=_OWNER_XY[0], y=_OWNER_XY[1]),
        nearest_obstacle_m=clearance,
        nearest_obstacle_bearing_rad=bearing,
        nearest_obstacle_id="scan_return" if clearance is not None else None,
        lidar_obstacles=obstacles,
        collision=contact,
        backend="navcore_room",
        lidar_ranges=() if scan is None else tuple(scan.ranges_m),
        lidar_angle_min_rad=None if scan is None else scan.angle_min_rad,
        lidar_angle_increment_rad=None if scan is None else scan.angle_increment_rad,
        lidar_range_min_m=None if scan is None else scan.range_min_m,
        lidar_range_max_m=None if scan is None else scan.range_max_m,
    )


def nav_observation(
    *,
    stack: PoseStack,
    scan: PlanarScan | None,
    candidates: list[dict[str, Any]],
    contact: bool,
    t_s: float,
    measured: VelocityCommand,
    stopped: bool,
) -> NavObservation:
    """``_nav_observation``'s payload, with every oracle field removed.

    Two deliberate differences from ``headless_city._nav_observation``, both
    forced by the study's premise:

    * ``position`` is the MAP estimate, not ``observation.robot`` truth.  The
      product builder is an eval helper and its truth field is harmless there
      because a provider is attached; here it would be a truth channel into any
      layer that reads ``position`` directly.
    * the obstacle channel is derived from the scan rather than from the room's
      rectangles, so a scan dropout really is an absence of evidence.
    """

    believed = stack.map_pose()
    clearance, bearing = nearest_from_scan(scan)
    return NavObservation(
        position=(believed.x, believed.y, 0.0),
        heading_deg=math.degrees(believed.yaw),
        nearest_person_m=None,
        nearest_obstacle_m=clearance,
        lidar=None if scan is None else tuple(scan.ranges_m),
        extras={
            POSE_PROVIDER_KEY: stack.provider,
            "time_s": float(t_s),
            "collision": contact,
            "perception_fresh": scan is not None,
            "lidar_angle_min_rad": None if scan is None else scan.angle_min_rad,
            "lidar_angle_increment_rad": (
                None if scan is None else scan.angle_increment_rad
            ),
            "lidar_range_min_m": None if scan is None else scan.range_min_m,
            "lidar_range_max_m": None if scan is None else scan.range_max_m,
            "obstacle_bearing_rad": bearing,
            "obstacle_id": "scan_return" if clearance is not None else None,
            "person_bearing_rad": None,
            "person_id": None,
            "person_ttc_s": None,
            "semantic_candidates": candidates,
            "lidar_obstacles": (
                []
                if clearance is None
                else [
                    {
                        "id": "scan_return",
                        "distance_m": clearance,
                        "bearing_rad": bearing,
                    }
                ]
            ),
            "motion_feedback": {
                "fresh": True,
                "stop_confirmed": stopped,
                "linear_speed_mps": math.hypot(measured.vx, measured.vy),
                "yaw_speed_rad_s": abs(measured.vyaw),
                "settled_linear_speed_mps": 0.08,
                "settled_yaw_speed_rad_s": 0.12,
            },
        },
    )
