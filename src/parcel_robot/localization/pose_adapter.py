"""Compose a MAP-role localizer with an ODOM-role source into a PoseProvider.

This is the whole "zero consumer changes" claim from
``docs/STRATA_GENERALIZATION_PLAN.md`` stratum 1, made executable.  The seam
``pose.py`` shipped asks a provider for exactly one thing —
``get_pose(frame) -> PoseEstimate`` — and the eval/runtime plumbing feeds a
provider exactly one thing, ``update_truth(x, y, yaw, stamp_monotonic_s=...)``
(``pose.update_provider_from_sim`` / ``pose._feed_from_observation``).
:class:`LocalizedPoseProvider` implements both, so it drops into
``HeadlessCityQualityHarness.new_pose_provider``,
``headless_city._nav_observation`` and ``observation_pose`` without a line
changing in any of them.

**Who supplies what.**  The ODOM role is whatever object already integrates the
body's own motion — in sim, ``pose.DriftingOdomProvider``; on a robot, the
leg-odometry source.  The truth feed goes *only* there: it is the stand-in for
proprioception, not a channel the localizer can see.  The MAP role gets scans
and the ODOM pose and returns ``T_map_odom``; the MAP pose is then
``T_map_odom * T_odom_base``, which is REP-105's definition rather than a
second, independent estimate of where the robot is.

**Body-neutrality falls out of that split.**  Nothing here or in
``gicp_provider.py`` names a wheelbase, a gait, a leg count or a vendor: the
ODOM role is an object with ``update_truth`` and ``get_pose``.  Card row L8
swaps in a fake custom quadruped's odometry and this file does not move.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from parcel_robot.localization.contract import (
    IDENTITY_SE2,
    LocalizationUpdate,
    ScanFrame,
    compose_se2,
)
from parcel_robot.pose import Frame, PoseEstimate, PoseHealth

__all__ = ["LocalizedPoseProvider"]

#: What a scan source is: called with the tick's monotonic seconds, returns the
#: scan taken at that instant or ``None`` when the sensor produced nothing.
ScanSource = Callable[[float], "ScanFrame | None"]


class LocalizedPoseProvider:
    """``MAP`` from the localizer, ``ODOM`` from the odometry source.

    ``get_pose(Frame.ODOM)`` is delegated verbatim: the ODOM contract belongs to
    whatever integrates the body, and interposing here would make the smooth
    frame depend on a localizer that is allowed to be LOST.
    """

    name = "localized"

    def __init__(
        self,
        localizer: Any,
        odom: Any,
        *,
        scan_source: ScanSource | None = None,
        map_covariance_floor_m2: float = 0.0,
    ) -> None:
        if not hasattr(localizer, "update"):
            raise TypeError("localizer must implement LocalizerProvider.update")
        if not hasattr(odom, "get_pose"):
            raise TypeError("odom source must implement PoseProvider.get_pose")
        self.localizer = localizer
        self.odom = odom
        self._scan_source = scan_source
        self._floor = float(map_covariance_floor_m2)
        if self._floor < 0.0:
            raise ValueError("map_covariance_floor_m2 must be non-negative")
        self._update: LocalizationUpdate | None = None
        self._stamp_s = 0.0
        self._updates = 0
        self._max_jump_m = 0.0

    # -- lifecycle ---------------------------------------------------------

    def reset(self, x: float = 0.0, y: float = 0.0, yaw: float = 0.0) -> None:
        reset = getattr(self.odom, "reset", None)
        if callable(reset):
            reset(x, y, yaw)
        self.localizer.reset()
        self._update = None
        self._stamp_s = 0.0
        self._updates = 0
        self._max_jump_m = 0.0

    # -- ingestion ---------------------------------------------------------

    def update_truth(
        self,
        x: float,
        y: float,
        yaw: float,
        *,
        stamp_monotonic_s: float | None = None,
    ) -> LocalizationUpdate | None:
        """One tick.  Truth reaches ODOM only; the localizer sees scans."""

        self.odom.update_truth(x, y, yaw, stamp_monotonic_s=stamp_monotonic_s)
        if stamp_monotonic_s is not None:
            self._stamp_s = float(stamp_monotonic_s)
        odom_pose = self.odom.get_pose(Frame.ODOM)
        scan = None if self._scan_source is None else self._scan_source(self._stamp_s)
        self._update = self.localizer.update(
            scan,
            (odom_pose.x, odom_pose.y, odom_pose.yaw),
            stamp_ns=round(self._stamp_s * 1e9),
        )
        self._updates += 1
        self._max_jump_m = max(self._max_jump_m, float(self._update.jump_m))
        return self._update

    # -- the seam ----------------------------------------------------------

    def get_pose(self, frame: Frame) -> PoseEstimate:
        if not isinstance(frame, Frame):
            raise TypeError("frame must be a Frame member")
        odom_pose = self.odom.get_pose(Frame.ODOM)
        if frame is Frame.ODOM:
            return odom_pose
        if self._update is None:
            return PoseEstimate(
                x=odom_pose.x,
                y=odom_pose.y,
                yaw=odom_pose.yaw,
                frame=Frame.MAP,
                health=PoseHealth.LOST,
                covariance=_floored(_ZERO, self._floor),
                stamp_monotonic_s=self._stamp_s,
            )
        x, y, yaw = compose_se2(
            self._update.T_map_odom, (odom_pose.x, odom_pose.y, odom_pose.yaw)
        )
        return PoseEstimate(
            x=x,
            y=y,
            yaw=yaw,
            frame=Frame.MAP,
            health=self._update.health,
            covariance=_floored(self._update.cov, self._floor),
            stamp_monotonic_s=self._stamp_s,
        )

    # -- evidence ----------------------------------------------------------

    @property
    def last_update(self) -> LocalizationUpdate | None:
        return self._update

    @property
    def max_jump_m(self) -> float:
        """Largest single-update ``T_map_odom`` discontinuity since reset.

        This is ``bridge/timing.py``'s ``localization_jump_m`` for this run —
        the term every stopping-envelope record on every host has carried as
        UNMEASURED.
        """

        return self._max_jump_m

    @property
    def updates(self) -> int:
        return self._updates

    @property
    def T_map_odom(self) -> tuple[float, float, float]:
        return IDENTITY_SE2 if self._update is None else self._update.T_map_odom

    @property
    def odom_error_m(self) -> float:
        """Passthrough so drift-arm telemetry keeps working unchanged."""

        return float(getattr(self.odom, "odom_error_m", math.nan))

    @property
    def odom_yaw_error_rad(self) -> float:
        return float(getattr(self.odom, "odom_yaw_error_rad", math.nan))

    @property
    def travelled_m(self) -> float:
        return float(getattr(self.odom, "travelled_m", 0.0))

    @property
    def slip_events(self) -> int:
        return int(getattr(self.odom, "slip_events", 0))

    @property
    def params(self) -> Any:
        """The ODOM source's noise parameters — what the drift seeder reseeds."""

        return getattr(self.odom, "params", None)

    @params.setter
    def params(self, value: Any) -> None:
        self.odom.params = value


_ZERO: tuple[float, ...] = (0.0,) * 9


def _floored(cov: tuple[float, ...], floor: float) -> tuple[float, ...]:
    if floor <= 0.0:
        return tuple(cov)
    out = list(cov)
    out[0] = max(out[0], floor)
    out[4] = max(out[4], floor)
    return tuple(out)
