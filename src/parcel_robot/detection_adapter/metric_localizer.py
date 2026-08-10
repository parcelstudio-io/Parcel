"""Pure static-landmark metric fusion for confirmed pixel detections (D2).

Frozen surfaces
---------------
``MetricLocalizer.update(MetricMeasurement) -> MetricEstimate | None`` fuses a
world-frame planar point and 2x2 covariance with a static-state Kalman filter.
``measurement_from_localized(...)`` consumes B2's ``LocalizedDetection``
without changing its contract.  ``MetricEstimate`` emits ``position`` and
``covariance`` as immutable tuples.

Depth-backed measurements are the primary PBVS-style path.  Bearing-only
motion parallax is used *only* when ``depth_reliable=False`` and requires two
separated camera viewpoints; it never silently replaces usable depth.
Low-viewpoint/high-elevation observations are explicitly marked and receive a
configurable covariance inflation before fusion.

The state is the static landmark ``[x, y]`` (no image-based servoing and no
velocity state).  The implementation uses Joseph-form covariance updates and
contains no runtime or navigation wiring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parcel_robot.detection_adapter.pixel_detections import LocalizedDetection

DOES_NOT_PROVE = (
    (
        "The pure Kalman/metamorphic cells prove deterministic planar fusion, not "
        "real D455 calibration, depth quality, or detector recognition."
    ),
    (
        "Motion parallax is a two-ray fallback for unreliable depth, not a full "
        "bundle-adjustment or moving-target estimator."
    ),
)

Covariance2 = tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True, slots=True)
class MetricLocalizerConfig:
    """Frozen numeric policy for the static-landmark estimator."""

    covariance_floor_m2: float = 1e-8
    low_viewpoint_elevation_rad: float = math.radians(20.0)
    low_viewpoint_covariance_scale: float = 4.0
    parallax_min_baseline_m: float = 0.20
    parallax_min_sine: float = math.sin(math.radians(3.0))
    parallax_sigma_m: float = 0.35
    max_bearing_history: int = 8

    def __post_init__(self) -> None:
        positive = (
            "covariance_floor_m2",
            "low_viewpoint_covariance_scale",
            "parallax_min_baseline_m",
            "parallax_min_sine",
            "parallax_sigma_m",
        )
        for name in positive:
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not 0.0 < self.parallax_min_sine <= 1.0:
            raise ValueError("parallax_min_sine must be in (0, 1]")
        if not 0.0 <= self.low_viewpoint_elevation_rad <= math.pi / 2.0:
            raise ValueError("low_viewpoint_elevation_rad must be in [0, pi/2]")
        if self.max_bearing_history < 2:
            raise ValueError("max_bearing_history must be >= 2")


@dataclass(frozen=True, slots=True)
class MetricMeasurement:
    """One world-frame depth point or bearing-only fallback observation."""

    x: float | None
    y: float | None
    covariance: Covariance2 | None
    depth_reliable: bool = True
    camera_x: float | None = None
    camera_y: float | None = None
    world_bearing_rad: float | None = None
    low_viewpoint: bool = False
    source_id: str = ""

    def __post_init__(self) -> None:
        if self.depth_reliable:
            if self.x is None or self.y is None or self.covariance is None:
                raise ValueError("reliable depth requires x, y, and covariance")
            _finite(self.x, "x")
            _finite(self.y, "y")
            _validate_covariance(self.covariance)
        else:
            if (
                self.camera_x is None
                or self.camera_y is None
                or self.world_bearing_rad is None
            ):
                raise ValueError(
                    "unreliable depth requires camera_x, camera_y, and world_bearing_rad"
                )
            _finite(self.camera_x, "camera_x")
            _finite(self.camera_y, "camera_y")
            _finite(self.world_bearing_rad, "world_bearing_rad")


@dataclass(frozen=True, slots=True)
class MetricEstimate:
    """Immutable fused static-landmark result."""

    position: tuple[float, float]
    covariance: Covariance2
    measurement_count: int
    mode: str
    low_viewpoint_seen: bool


def measurement_from_localized(
    localized: LocalizedDetection,
    *,
    camera_x: float,
    camera_y: float,
    camera_height_m: float = 0.35,
    depth_reliable: bool = True,
    source_id: str = "",
    config: MetricLocalizerConfig | None = None,
) -> MetricMeasurement:
    """Adapt B2's additive ``LocalizedDetection`` to the frozen D2 input.

    ``low_viewpoint`` is true when a target is viewed from the nominal dog
    height at an elevation at or above the configured threshold.  Callers may
    mark depth unreliable after B2's validity checks; that switches this sample
    to bearing-only parallax and discards its depth point.
    """

    cfg = config if config is not None else MetricLocalizerConfig()
    cx = _finite(camera_x, "camera_x")
    cy = _finite(camera_y, "camera_y")
    camera_z = _finite(camera_height_m, "camera_height_m")
    x = _finite(localized.world_x, "localized.world_x")
    y = _finite(localized.world_y, "localized.world_y")
    z = _finite(localized.world_z, "localized.world_z")
    planar_range = math.hypot(x - cx, y - cy)
    elevation = math.atan2(z - camera_z, max(planar_range, 1e-12))
    bearing = math.atan2(y - cy, x - cx)
    low_viewpoint = elevation >= cfg.low_viewpoint_elevation_rad
    if depth_reliable:
        return MetricMeasurement(
            x=x,
            y=y,
            covariance=_as_covariance(localized.covariance_xy),
            depth_reliable=True,
            camera_x=cx,
            camera_y=cy,
            world_bearing_rad=bearing,
            low_viewpoint=low_viewpoint,
            source_id=source_id or localized.message.envelope.evidence_id,
        )
    return MetricMeasurement(
        x=None,
        y=None,
        covariance=None,
        depth_reliable=False,
        camera_x=cx,
        camera_y=cy,
        world_bearing_rad=bearing,
        low_viewpoint=low_viewpoint,
        source_id=source_id or localized.message.envelope.evidence_id,
    )


class MetricLocalizer:
    """Static 2D Kalman fusion with guarded motion-parallax fallback."""

    def __init__(self, config: MetricLocalizerConfig | None = None) -> None:
        self.config = config if config is not None else MetricLocalizerConfig()
        self._mean: tuple[float, float] | None = None
        self._covariance: Covariance2 | None = None
        self._measurement_count = 0
        self._last_mode = "none"
        self._low_viewpoint_seen = False
        self._bearings: list[tuple[float, float, float, bool]] = []

    @property
    def estimate(self) -> MetricEstimate | None:
        if self._mean is None or self._covariance is None:
            return None
        return MetricEstimate(
            position=self._mean,
            covariance=self._covariance,
            measurement_count=self._measurement_count,
            mode=self._last_mode,
            low_viewpoint_seen=self._low_viewpoint_seen,
        )

    def reset(self) -> None:
        self._mean = None
        self._covariance = None
        self._measurement_count = 0
        self._last_mode = "none"
        self._low_viewpoint_seen = False
        self._bearings.clear()

    def update(self, measurement: MetricMeasurement) -> MetricEstimate | None:
        if not isinstance(measurement, MetricMeasurement):
            raise TypeError("measurement must be MetricMeasurement")
        self._low_viewpoint_seen |= measurement.low_viewpoint
        if measurement.depth_reliable:
            assert measurement.x is not None
            assert measurement.y is not None
            assert measurement.covariance is not None
            covariance = measurement.covariance
            if measurement.low_viewpoint:
                covariance = _scale_covariance(
                    covariance, self.config.low_viewpoint_covariance_scale
                )
            self._fuse((measurement.x, measurement.y), covariance, mode="depth")
            return self.estimate

        assert measurement.camera_x is not None
        assert measurement.camera_y is not None
        assert measurement.world_bearing_rad is not None
        current = (
            measurement.camera_x,
            measurement.camera_y,
            measurement.world_bearing_rad,
            measurement.low_viewpoint,
        )
        parallax_point = self._parallax_point(current)
        self._bearings.append(current)
        if len(self._bearings) > self.config.max_bearing_history:
            del self._bearings[: len(self._bearings) - self.config.max_bearing_history]
        if parallax_point is None:
            return self.estimate
        variance = self.config.parallax_sigma_m**2
        covariance = ((variance, 0.0), (0.0, variance))
        if measurement.low_viewpoint:
            covariance = _scale_covariance(
                covariance, self.config.low_viewpoint_covariance_scale
            )
        self._fuse(parallax_point, covariance, mode="parallax")
        return self.estimate

    def update_localized(
        self,
        localized: LocalizedDetection,
        *,
        camera_x: float,
        camera_y: float,
        camera_height_m: float = 0.35,
        depth_reliable: bool = True,
        source_id: str = "",
    ) -> MetricEstimate | None:
        """Convenience consumer for B2 without modifying B2's contract."""

        return self.update(
            measurement_from_localized(
                localized,
                camera_x=camera_x,
                camera_y=camera_y,
                camera_height_m=camera_height_m,
                depth_reliable=depth_reliable,
                source_id=source_id,
                config=self.config,
            )
        )

    def _fuse(
        self, point: tuple[float, float], covariance: Covariance2, *, mode: str
    ) -> None:
        r = _regularize(covariance, self.config.covariance_floor_m2)
        if self._mean is None or self._covariance is None:
            self._mean = (float(point[0]), float(point[1]))
            self._covariance = r
        else:
            p = self._covariance
            innovation = _add(p, r)
            k = _mul(p, _inv(innovation))
            residual = (point[0] - self._mean[0], point[1] - self._mean[1])
            correction = _matvec(k, residual)
            self._mean = (
                self._mean[0] + correction[0],
                self._mean[1] + correction[1],
            )
            identity_minus_k = (
                (1.0 - k[0][0], -k[0][1]),
                (-k[1][0], 1.0 - k[1][1]),
            )
            # Joseph form: (I-K)P(I-K)' + K R K'.
            left = _mul(_mul(identity_minus_k, p), _transpose(identity_minus_k))
            right = _mul(_mul(k, r), _transpose(k))
            self._covariance = _regularize(
                _symmetrize(_add(left, right)), self.config.covariance_floor_m2
            )
        self._measurement_count += 1
        self._last_mode = mode

    def _parallax_point(
        self, current: tuple[float, float, float, bool]
    ) -> tuple[float, float] | None:
        x2, y2, a2, _low = current
        d2 = (math.cos(a2), math.sin(a2))
        for x1, y1, a1, _ in reversed(self._bearings):
            if math.hypot(x2 - x1, y2 - y1) < self.config.parallax_min_baseline_m:
                continue
            d1 = (math.cos(a1), math.sin(a1))
            cross = _cross(d1, d2)
            if abs(cross) < self.config.parallax_min_sine:
                continue
            delta = (x2 - x1, y2 - y1)
            t1 = _cross(delta, d2) / cross
            t2 = _cross(delta, d1) / cross
            if t1 <= 0.0 or t2 <= 0.0:
                continue
            return (x1 + t1 * d1[0], y1 + t1 * d1[1])
        return None


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def _as_covariance(value: object) -> Covariance2:
    rows = tuple(tuple(float(item) for item in row) for row in value)  # type: ignore[union-attr]
    if len(rows) != 2 or any(len(row) != 2 for row in rows):
        raise ValueError("covariance must be 2x2")
    covariance: Covariance2 = (rows[0], rows[1])
    _validate_covariance(covariance)
    return covariance


def _validate_covariance(value: Covariance2) -> None:
    a, b = _finite(value[0][0], "covariance[0][0]"), _finite(
        value[0][1], "covariance[0][1]"
    )
    c, d = _finite(value[1][0], "covariance[1][0]"), _finite(
        value[1][1], "covariance[1][1]"
    )
    if abs(b - c) > 1e-9:
        raise ValueError("covariance must be symmetric")
    if a < 0.0 or d < 0.0 or a * d - b * c < -1e-12:
        raise ValueError("covariance must be positive semidefinite")


def _regularize(value: Covariance2, floor: float) -> Covariance2:
    _validate_covariance(value)
    return ((value[0][0] + floor, value[0][1]), (value[1][0], value[1][1] + floor))


def _scale_covariance(value: Covariance2, scale: float) -> Covariance2:
    return (
        (value[0][0] * scale, value[0][1] * scale),
        (value[1][0] * scale, value[1][1] * scale),
    )


def _add(left: Covariance2, right: Covariance2) -> Covariance2:
    return (
        (left[0][0] + right[0][0], left[0][1] + right[0][1]),
        (left[1][0] + right[1][0], left[1][1] + right[1][1]),
    )


def _mul(left: Covariance2, right: Covariance2) -> Covariance2:
    return (
        (
            left[0][0] * right[0][0] + left[0][1] * right[1][0],
            left[0][0] * right[0][1] + left[0][1] * right[1][1],
        ),
        (
            left[1][0] * right[0][0] + left[1][1] * right[1][0],
            left[1][0] * right[0][1] + left[1][1] * right[1][1],
        ),
    )


def _transpose(value: Covariance2) -> Covariance2:
    return ((value[0][0], value[1][0]), (value[0][1], value[1][1]))


def _symmetrize(value: Covariance2) -> Covariance2:
    off = 0.5 * (value[0][1] + value[1][0])
    return ((value[0][0], off), (off, value[1][1]))


def _inv(value: Covariance2) -> Covariance2:
    a, b = value[0]
    c, d = value[1]
    determinant = a * d - b * c
    if not math.isfinite(determinant) or determinant <= 0.0:
        raise ValueError("covariance sum must be positive definite")
    return ((d / determinant, -b / determinant), (-c / determinant, a / determinant))


def _matvec(
    matrix: Covariance2, vector: tuple[float, float]
) -> tuple[float, float]:
    return (
        matrix[0][0] * vector[0] + matrix[0][1] * vector[1],
        matrix[1][0] * vector[0] + matrix[1][1] * vector[1],
    )


def _cross(left: tuple[float, float], right: tuple[float, float]) -> float:
    return left[0] * right[1] - left[1] * right[0]
