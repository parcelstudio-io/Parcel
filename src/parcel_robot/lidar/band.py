"""Livox points -> a planar height band -> the scan the runtime already reads.

Card HW-3, design decision §5.3 of ``scrum/20260822/WAVE3_HW_DESIGN_FABLE.md``.
The Mid-360's vertical FOV is -7 deg..+52 deg [documented]: it sees up, not
down, so the honest planar product of one sweep is a **height band** above
``base_link``, binned into the exact angular layout
``backends/base.py:SimObservation.lidar_ranges`` already carries. Then
``navigation/reactive_safety.py`` and the grid planner are unchanged (design
§4 row S2, class VI) and HW-2's ``Go2Backend`` has nothing left to invent.

Pure by construction: standard library plus :mod:`parcel_robot.robot_profile`
(a declared leaf that imports nothing from ``parcel_robot``). No numpy, no
mujoco, no socket, no SDK — so this imports in the ``base`` extra on the
Orin's CPython 3.10 / aarch64.

The layout being reproduced, read from the sim
----------------------------------------------
``mujoco_lidar.py:raycast_planar_scan`` and its :class:`PlanarScan` docstring,
consumed via ``sim.py:307-322`` -> ``backends/mujoco.py:_parse_lidar_scan``:

* ``DEFAULT_SCAN_RAYS = 360`` bins;
* ``angle_min = -math.pi``; ``angle_increment = 2*pi/num_rays``; bearings are
  BODY-relative (``world_angles = robot_heading + body_angles``) and run
  **counter-clockwise** — index up is bearing up;
* ``DEFAULT_SCAN_RANGE_MIN_M = 0.05``, ``DEFAULT_SCAN_RANGE_MAX_M = 30.0``;
* a range equal to ``range_max_m`` is "a no-return that clears free space";
  ``float("nan")`` is "an ignored ray", which clears nothing.

Those five numbers are restated here as :class:`BandProfile` defaults rather
than imported, because importing ``mujoco_lidar`` drags ``mujoco`` into an
aarch64 ``base`` venv that will not have it. They are pinned equal to the
sim's by ``tests/test_hw3_mid360_band.py::
test_band_profile_defaults_match_the_sim_scan_contract``, which does import
``mujoco_lidar`` — the pin lives in the test so the product stays portable.

**An empty bin is NaN, not ``range_max_m``.** A MuJoCo ray that comes back at
``range_max`` has looked down that bearing and seen nothing. One Mid-360 frame
has not: the scan pattern is non-repetitive, so a bin can be empty because
nothing was sampled there, and emitting the free-space sentinel on that would
clear space on no evidence in the one channel the safety layer reads. NaN is
the sim's own word for "this ray clears nothing". How many frames must be
accumulated before a bin may be declared free is a MEASUREMENT owed on box-day
(HW-9/B11), not a number to pick at a desk.

**A sweep with no measurements at all is not a scan, it is the absence of
one.** Per-bin emptiness and whole-sweep emptiness are different facts, and
only the first is a NaN. ``reactive_safety.scan_present`` is
``bool(observation.lidar_ranges)``, so a 360-NaN tuple would answer "a scan is
present" on zero measurements and a silent sensor would read as clear space at
0.3 m/s (verifier finding F1). Below
:attr:`BandProfile.min_populated_bins` :func:`band_scan` therefore emits
``ranges_m=()`` — the ``SimObservation`` value for "no calibrated scan", on
which the health join reports SCAN missing and translation HOLDs.
``points_seen`` / ``points_in_band`` / ``populated_bins`` are still reported,
because box-day needs the coverage number even on a sweep that is not a scan.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE, RobotProfile

from .livox_udp import LivoxPointFrame

__all__ = [
    "BAND_TUNING_STEP",
    "IDENTITY_EXTRINSIC",
    "BandProfile",
    "BandScan",
    "ObstacleFix",
    "band_scan",
    "nearest_obstacle_from_scan",
    "scan_from_frames",
    "travel_bearing_rad",
]

#: The step of the box-day protocol that replaces the band defaults and the
#: extrinsic with measurements (design §7). Quoted in the profile's docstring
#: so the numbers below can never be read as measured.
BAND_TUNING_STEP = "B11"

#: Row-major 4x4 sensor -> ``base_link`` transform. Identity is a PLACEHOLDER:
#: the real mount extrinsic is a tape measure at B11 and is UNCONFIRMED until
#: the box is opened.
IDENTITY_EXTRINSIC: tuple[tuple[float, float, float, float], ...] = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)

#: Half-angle of the travel corridor, in radians. Not a new number: it is the
#: one ``sim.py:75 select_relevant_obstacle`` and
#: ``navigation/reactive_safety.py:_toward`` both use.
_CORRIDOR_HALF_ANGLE_RAD = 1.15


@dataclass(frozen=True, slots=True)
class BandProfile:
    """Every number the band filter uses, in one injectable object.

    ``z_lo_m`` / ``z_hi_m`` are PROFILE PARAMETERS, not constants: the defaults
    are the design's starting pair and are to be **tuned at B11** against the
    measured mount height. The five layout numbers default to the sim's.

    ``robot_profile`` is resolved in-body rather than bound as a default
    argument — the drift ``mujoco_lidar.py:_resolve_body`` exists to prevent
    ("evaluated once at import and can never be reached by an injected
    profile") applies to a dataclass field default in exactly the same way.
    """

    z_lo_m: float = 0.10
    z_hi_m: float = 0.60
    bins: int = 360
    angle_min_rad: float = -math.pi
    range_min_m: float = 0.05
    range_max_m: float = 30.0
    extrinsic: tuple[tuple[float, float, float, float], ...] = IDENTITY_EXTRINSIC
    corridor_half_angle_rad: float = _CORRIDOR_HALF_ANGLE_RAD
    #: How many bins must carry a measurement before the sweep is a SCAN at
    #: all. Below it :func:`band_scan` emits ``ranges_m=()`` — the
    #: ``SimObservation`` value for "no calibrated scan" — so a silent sensor
    #: reads as ABSENT evidence and not as clear space. See the module
    #: docstring. ``1`` is the floor (a sweep with zero measurements is never
    #: a scan); the venue's real minimum is **tuned at B11** against measured
    #: per-frame coverage, and until then raising it is the conservative move.
    min_populated_bins: int = 1
    robot_profile: RobotProfile | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for name in ("z_lo_m", "z_hi_m", "angle_min_rad", "range_min_m", "range_max_m"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"BandProfile.{name} must be a number, got {value!r}")
            if not math.isfinite(float(value)):
                raise ValueError(f"BandProfile.{name} must be finite, got {value!r}")
        if self.z_lo_m >= self.z_hi_m:
            raise ValueError(
                f"band must have positive height: z_lo_m {self.z_lo_m} >= z_hi_m "
                f"{self.z_hi_m}"
            )
        if isinstance(self.bins, bool) or not isinstance(self.bins, int):
            raise TypeError(f"BandProfile.bins must be an int, got {self.bins!r}")
        if not 2 <= self.bins <= 16_384:
            raise ValueError(
                f"BandProfile.bins must be 2..16384 — the range "
                f"backends/mujoco.py:_parse_lidar_scan accepts; got {self.bins}"
            )
        if not 0.0 <= self.range_min_m < self.range_max_m:
            raise ValueError(
                f"need 0 <= range_min_m < range_max_m, got {self.range_min_m} and "
                f"{self.range_max_m}"
            )
        if isinstance(self.min_populated_bins, bool) or not isinstance(
            self.min_populated_bins, int
        ):
            raise TypeError(
                f"BandProfile.min_populated_bins must be an int, got "
                f"{self.min_populated_bins!r}"
            )
        if not 1 <= self.min_populated_bins <= self.bins:
            raise ValueError(
                f"min_populated_bins must be 1..{self.bins} (a sweep with zero "
                f"measurements is never a scan), got {self.min_populated_bins}"
            )
        if not 0.0 < self.corridor_half_angle_rad <= math.pi:
            raise ValueError(
                f"corridor_half_angle_rad must be in (0, pi], got "
                f"{self.corridor_half_angle_rad}"
            )
        self._check_extrinsic()

    def _check_extrinsic(self) -> None:
        rows = self.extrinsic
        if len(rows) != 4 or any(len(row) != 4 for row in rows):
            raise ValueError("extrinsic must be a 4x4 row-major matrix")
        for row in rows:
            for value in row:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError(f"extrinsic entries must be numbers, got {value!r}")
                if not math.isfinite(float(value)):
                    raise ValueError(f"extrinsic entries must be finite, got {value!r}")
        if tuple(float(value) for value in rows[3]) != (0.0, 0.0, 0.0, 1.0):
            raise ValueError(
                f"extrinsic must be a rigid transform: its last row is "
                f"{tuple(rows[3])}, not (0, 0, 0, 1) — a projective matrix here would "
                f"scale ranges silently"
            )

    @property
    def angle_increment_rad(self) -> float:
        return 2.0 * math.pi / self.bins

    @property
    def footprint_radius_m(self) -> float:
        """The body's footprint radius, resolved in-body (see the docstring)."""

        body = self.robot_profile if self.robot_profile is not None else DEFAULT_ROBOT_PROFILE
        return float(body.footprint_radius_m)

    def bin_bearing_rad(self, index: int) -> float:
        """The body-relative bearing bin ``index`` measures along."""

        if not 0 <= index < self.bins:
            raise IndexError(f"bin {index} out of range for {self.bins} bins")
        return self.angle_min_rad + index * self.angle_increment_rad


@dataclass(frozen=True, slots=True)
class BandScan:
    """A band sweep in ``SimObservation``'s scan shape.

    The first five fields are exactly the five ``SimObservation`` scan fields,
    in their order, so HW-2's ``Go2Backend`` copies them across without
    arithmetic. ``points_seen`` / ``points_in_band`` / ``populated_bins`` are
    the coverage evidence box-day (HW-9) needs and nothing in the runtime
    reads.

    ``ranges_m == ()`` means **this sweep is not a scan** (fewer than
    :attr:`BandProfile.min_populated_bins` bins measured anything). It is not
    "a scan of nothing": the runtime reads it as absent evidence and HOLDs.
    A caller must therefore branch on it rather than copying it across — see
    :mod:`parcel_robot.lidar`'s seam snippet.
    """

    ranges_m: tuple[float, ...]
    angle_min_rad: float
    angle_increment_rad: float
    range_min_m: float
    range_max_m: float
    points_seen: int
    points_in_band: int
    populated_bins: int


@dataclass(frozen=True, slots=True)
class ObstacleFix:
    """The single obstacle a ``SimObservation`` reports, with its bin."""

    clearance_m: float
    bearing_rad: float
    bin_index: int


def band_scan(
    points: Iterable[tuple[float, float, float]],
    profile: BandProfile | None = None,
) -> BandScan:
    """Bin metric sensor-frame points into the sim's angular scan layout.

    One pass per point: the extrinsic's z row first, so a point outside the
    band costs three multiplies and a compare and nothing else. Within a bin
    the MINIMUM range wins, which is what a ray returns — the first surface it
    meets. A bin nothing landed in stays NaN; see the module docstring.
    """

    profile = profile if profile is not None else BandProfile()
    (m00, m01, m02, m03), (m10, m11, m12, m13), (m20, m21, m22, m23), _ = profile.extrinsic
    z_lo, z_hi = profile.z_lo_m, profile.z_hi_m
    range_min, range_max = profile.range_min_m, profile.range_max_m
    bins = profile.bins
    angle_min = profile.angle_min_rad
    increment = profile.angle_increment_rad
    ranges = [math.nan] * bins
    atan2, hypot, floor, isnan = math.atan2, math.hypot, math.floor, math.isnan
    seen = 0
    in_band = 0
    for x, y, z in points:
        seen += 1
        zb = m20 * x + m21 * y + m22 * z + m23
        if zb < z_lo or zb > z_hi:
            continue
        xb = m00 * x + m01 * y + m02 * z + m03
        yb = m10 * x + m11 * y + m12 * z + m13
        distance = hypot(xb, yb)
        if distance < range_min or distance > range_max:
            continue
        in_band += 1
        # Nearest ray centre: angle_min is the bearing OF bin 0, not a cell
        # edge (the LaserScan convention the sim follows). Ties go up.
        index = floor((atan2(yb, xb) - angle_min) / increment + 0.5) % bins
        current = ranges[index]
        # NaN-safe: ``nan <= distance`` is False, so an empty bin is filled.
        if not current <= distance:
            ranges[index] = distance
    populated = sum(1 for value in ranges if not isnan(value))
    # A sweep that measured nothing is NOT a scan of empty space. Emitting a
    # 360-NaN tuple made ``reactive_safety.scan_present`` — which is
    # ``bool(lidar_ranges)`` — answer True on zero measurements, and a silent
    # sensor (cable out, wrong NIC, unit off) then read as "clear" at 0.3 m/s.
    # ``()`` is the ``SimObservation`` value for "no calibrated scan"; on it
    # the core health join reports SCAN missing and translation HOLDs.
    # (Verifier finding F1, ``~/.cache/parcel-verify/hw3/VERDICT.md``.)
    if populated < profile.min_populated_bins:
        ranges = []
    return BandScan(
        ranges_m=tuple(ranges),
        angle_min_rad=angle_min,
        angle_increment_rad=increment,
        range_min_m=range_min,
        range_max_m=range_max,
        points_seen=seen,
        points_in_band=in_band,
        populated_bins=populated,
    )


def scan_from_frames(
    frames: Iterable[LivoxPointFrame],
    profile: BandProfile | None = None,
) -> BandScan:
    """**The HW-2 seam.** Decoded Livox frames -> one ``SimObservation`` scan.

    ``Go2Backend.observe()`` calls this with the frames its reader drained
    since the last tick and copies :class:`BandScan`'s first five fields onto
    the ``SimObservation`` it returns.
    """

    def _points() -> Iterable[tuple[float, float, float]]:
        for frame in frames:
            yield from frame.xyz_m()

    return band_scan(_points(), profile)


def travel_bearing_rad(vx: float, vy: float) -> float | None:
    """The travel bearing, or ``None`` when the body is not translating.

    ``sim.py:67-69`` exactly: translating is ``hypot(vx, vy) > 1e-6`` and the
    bearing is ``atan2(vy, vx)``. Kept here so HW-2 does not restate the
    threshold at the call site.
    """

    if not math.isfinite(vx) or not math.isfinite(vy):
        return None
    if math.hypot(vx, vy) <= 1e-6:
        return None
    return math.atan2(vy, vx)


def nearest_obstacle_from_scan(
    scan: BandScan,
    profile: BandProfile | None = None,
    *,
    travel_bearing: float | None = None,
) -> ObstacleFix | None:
    """**The HW-2 seam.** ``SimObservation.nearest_obstacle_m``, the sim's way.

    The sim does NOT derive this from its scan, so neither does this. It is:

    1. clearance, not range — ``mujoco_lidar.py:planar_geom_surface_hit`` sets
       ``distance_m = max(0.0, surface_distance - robot_radius_m)``;
    2. selected by ``sim.py:54-79 select_relevant_obstacle`` — while
       translating, the nearest candidate whose bearing is within
       ``corridor_half_angle_rad`` of the travel bearing if any such candidate
       exists, otherwise the globally nearest; ties go to the lower bin, which
       is the list order ``min()`` sees there too.

    Reimplemented rather than imported because ``parcel_robot.sim`` imports
    ``mujoco`` and ``numpy`` at module scope; pinned to the original by a
    differential test against the real ``select_relevant_obstacle``.
    """

    profile = profile if profile is not None else BandProfile()
    radius = profile.footprint_radius_m
    candidates: list[ObstacleFix] = []
    for index, distance in enumerate(scan.ranges_m):
        if math.isnan(distance):  # the bin measured nothing
            continue
        candidates.append(
            ObstacleFix(
                clearance_m=max(0.0, distance - radius),
                bearing_rad=scan.angle_min_rad + index * scan.angle_increment_rad,
                bin_index=index,
            )
        )
    if not candidates:
        return None
    if travel_bearing is not None:
        half_angle = profile.corridor_half_angle_rad
        directional = [
            fix
            for fix in candidates
            if abs(_wrap(fix.bearing_rad - travel_bearing)) < half_angle
        ]
        if directional:
            return min(directional, key=lambda fix: fix.clearance_m)
    return min(candidates, key=lambda fix: fix.clearance_m)


def _wrap(angle: float) -> float:
    """``mujoco_lidar.py:_wrap`` and ``sim.py:72-74``, the same arithmetic."""

    return (angle + math.pi) % (2.0 * math.pi) - math.pi
