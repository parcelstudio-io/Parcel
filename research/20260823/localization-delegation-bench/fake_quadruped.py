"""A second body's odometry — the L8 body-neutrality probe.

Row L8 asks whether the same provider runs unchanged for "a fake custom
quadruped".  A second *profile* of ``pose.DriftingOdomProvider`` would not
answer that: it would only show that one class's constructor takes different
numbers.  So this is a genuinely different implementation — different error
model, different report cadence, different body constants — that shares nothing
with ``DriftingOdomProvider`` except the two methods the seam actually uses
(``update_truth`` and ``get_pose``) and the one method the adapter calls to
start a run (``reset``).

The body it models: a larger custom quadruped with a 0.62 m stride pair (the Go2
figure the repo uses elsewhere is 0.36 m), a 2 % stride-length calibration error
(a long leg reporting short), a yaw bias from a mismatched left/right stride,
and a proprioception update that lands at 25 Hz — so a 10 Hz consumer reads a
value that is up to one stride stale.  None of those constants appear anywhere
in ``src/parcel_robot/localization/``; that is the point of the row.
"""

from __future__ import annotations

import math
import random

from parcel_robot.pose import Frame, PoseEstimate, PoseHealth

__all__ = ["FakeQuadrupedOdom"]


class FakeQuadrupedOdom:
    """Leg odometry for a body Parcel has never seen, in the ODOM role."""

    name = "fake_quadruped"

    def __init__(
        self,
        *,
        stride_pair_m: float = 0.62,
        stride_scale_error: float = 0.02,
        yaw_bias_rad_per_m: float = 0.0045,
        step_noise_m: float = 0.004,
        step_yaw_noise_rad: float = 0.0025,
        report_hz: float = 25.0,
        seed: int = 20260823,
    ) -> None:
        self.stride_pair_m = float(stride_pair_m)
        self.stride_scale_error = float(stride_scale_error)
        self.yaw_bias_rad_per_m = float(yaw_bias_rad_per_m)
        self.step_noise_m = float(step_noise_m)
        self.step_yaw_noise_rad = float(step_yaw_noise_rad)
        self.report_period_s = 1.0 / float(report_hz)
        self.seed = int(seed)
        self.reset()

    def reset(self, x: float = 0.0, y: float = 0.0, yaw: float = 0.0) -> None:
        self._rng = random.Random(self.seed)
        self._truth = (float(x), float(y), float(yaw))
        self._odom = self._truth
        self._reported = self._truth
        self._seeded = False
        self._stamp = 0.0
        self._reported_stamp = 0.0
        self._distance_m = 0.0
        self._var_xy = 0.0
        self._var_yaw = 0.0

    def update_truth(
        self,
        x: float,
        y: float,
        yaw: float,
        *,
        stamp_monotonic_s: float | None = None,
    ) -> None:
        previous = self._truth
        self._truth = (float(x), float(y), float(yaw))
        if stamp_monotonic_s is not None:
            self._stamp = float(stamp_monotonic_s)
        if not self._seeded:
            self._seeded = True
            self._odom = self._truth
            self._reported = self._truth
            self._reported_stamp = self._stamp
            return
        dx = self._truth[0] - previous[0]
        dy = self._truth[1] - previous[1]
        trans = math.hypot(dx, dy)
        turn = _wrap(self._truth[2] - previous[2])
        # A stride-quantised body: the error scales with how much of a stride
        # pair the increment covers, not with wall-clock time.
        strides = trans / self.stride_pair_m
        measured = trans * (1.0 + self.stride_scale_error)
        measured += self._rng.gauss(0.0, self.step_noise_m * math.sqrt(max(strides, 1e-6)))
        measured_turn = turn + self.yaw_bias_rad_per_m * trans
        measured_turn += self._rng.gauss(0.0, self.step_yaw_noise_rad * math.sqrt(max(strides, 1e-6)))
        heading = _wrap(self._odom[2] + measured_turn * 0.5)
        self._odom = (
            self._odom[0] + measured * math.cos(heading),
            self._odom[1] + measured * math.sin(heading),
            _wrap(self._odom[2] + measured_turn),
        )
        self._distance_m += trans
        self._var_xy += (self.stride_scale_error * trans) ** 2 + self.step_noise_m**2 * strides
        self._var_yaw += self.step_yaw_noise_rad**2 * strides
        if self._stamp - self._reported_stamp >= self.report_period_s:
            self._reported = self._odom
            self._reported_stamp = self._stamp

    def get_pose(self, frame: Frame) -> PoseEstimate:
        if not isinstance(frame, Frame):
            raise TypeError("frame must be a Frame member")
        x, y, yaw = self._reported
        return PoseEstimate(
            x=x,
            y=y,
            yaw=yaw,
            frame=frame,
            health=PoseHealth.HEALTHY,
            covariance=(self._var_xy, 0.0, 0.0, 0.0, self._var_xy, 0.0, 0.0, 0.0, self._var_yaw),
            stamp_monotonic_s=self._stamp,
        )

    @property
    def travelled_m(self) -> float:
        return self._distance_m

    @property
    def odom_error_m(self) -> float:
        return math.hypot(self._odom[0] - self._truth[0], self._odom[1] - self._truth[1])

    @property
    def odom_yaw_error_rad(self) -> float:
        return abs(_wrap(self._odom[2] - self._truth[2]))


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))
