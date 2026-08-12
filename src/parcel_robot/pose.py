"""Stratum-1 pose authority — the localization SEAM, never a localizer.

This module is the single place navigation is allowed to learn where the robot
is.  It exists because ``NavObservation.position`` is MuJoCo ground truth and
every world-frame consumer (goals, semantic memory, K0 arrival) silently
presumes a globally consistent pose that no component actually provides
(NAV_GENERALIZATION_AUDIT stratum 1).

**What this is not.**  There is no SLAM, no EKF, no filter of any kind here and
none is planned in sim (STRATA_GENERALIZATION_PLAN anti-goals, binding).  A real
localizer slots into the ``MAP`` role behind :class:`PoseProvider` with zero
consumer changes; that is a P5 HR-ledger item.

**REP-105 frame discipline.**  Two frames, two contracts:

``MAP``
    Globally consistent, *may jump*.  Serves world-frame goals, semantic memory
    writes, and K0 arrival verification.

``ODOM``
    Continuous and smooth, *drifts without bound*.  Serves the reactive gate,
    TTC, and short-horizon control.

:class:`TruthPoseProvider` returns the identical sim-truth pose on both frames
with zero covariance, so installing it is behavior-preserving by construction.
:class:`DriftingOdomProvider` corrupts ``ODOM`` with the Probabilistic-Robotics
alpha odometry model so the binding can actually be measured.

Sources: REP-105 (frame conventions) · Thrun, Burgard & Fox, *Probabilistic
Robotics*, Table 5.6 (``sample_motion_model_odometry``) · DogLegs (Unitree Go2
leg-odometry drift bands) · Spot GraphNav (LOST/DEGRADED health as a first-class
arrival gate).
"""

from __future__ import annotations

import math
import random
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ZERO_COVARIANCE",
    "DriftingOdomProvider",
    "Frame",
    "OdometryNoiseParams",
    "PoseConfig",
    "PoseEstimate",
    "PoseHealth",
    "PoseProvider",
    "TruthPoseProvider",
    "default_pose_provider",
    "legacy_position_yaw",
    "load_pose_config",
    "observation_pose",
    "p_inside_polygon",
    "point_in_polygon_with_clearance_pure",
    "provider_from_config",
    "use_pose_provider",
]

# Row-major 3x3 covariance over (x, y, yaw).  Sim truth is exact.
ZERO_COVARIANCE: tuple[float, ...] = (0.0,) * 9

#: Symmetry / PSD slack.  Covariances arrive from float arithmetic, not algebra.
_COVARIANCE_TOLERANCE = 1e-9


class Frame(str, Enum):
    """REP-105 frame roles.  The value is the REP-105 frame name."""

    MAP = "map"
    ODOM = "odom"


class PoseHealth(str, Enum):
    """Localization health.  ``DEGRADED``/``LOST`` are refusals, not guesses."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    LOST = "lost"


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"pose {name} must be a real number, got {type(value).__name__}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"pose {name} must be finite")
    return out


@dataclass(frozen=True)
class PoseEstimate:
    """One SE(2) pose in one frame, with uncertainty and health.

    ``covariance`` is a row-major 3x3 over ``(x, y, yaw)`` in m^2 / m*rad /
    rad^2.  Validation is **fail-closed**: a non-finite entry, an asymmetric
    matrix, a negative variance, or an indefinite xy block raises rather than
    letting a corrupt estimate reach an arrival check.
    """

    x: float
    y: float
    yaw: float
    frame: Frame
    health: PoseHealth = PoseHealth.HEALTHY
    covariance: tuple[float, ...] = ZERO_COVARIANCE
    stamp_monotonic_s: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _finite(self.x, "x"))
        object.__setattr__(self, "y", _finite(self.y, "y"))
        object.__setattr__(self, "yaw", _finite(self.yaw, "yaw"))
        object.__setattr__(
            self, "stamp_monotonic_s", _finite(self.stamp_monotonic_s, "stamp_monotonic_s")
        )
        if not isinstance(self.frame, Frame):
            raise TypeError("pose frame must be a Frame member")
        if not isinstance(self.health, PoseHealth):
            raise TypeError("pose health must be a PoseHealth member")
        raw = tuple(self.covariance)
        if len(raw) != 9:
            raise ValueError("pose covariance must be a row-major 3x3 (9 entries)")
        cov = tuple(_finite(value, "covariance") for value in raw)
        object.__setattr__(self, "covariance", cov)
        for index in (0, 4, 8):
            if cov[index] < -_COVARIANCE_TOLERANCE:
                raise ValueError("pose covariance diagonal must be non-negative")
        for i, j in ((0, 1), (0, 2), (1, 2)):
            if abs(cov[3 * i + j] - cov[3 * j + i]) > _COVARIANCE_TOLERANCE:
                raise ValueError("pose covariance must be symmetric")
        # PSD-ish: the xy block is the one the chance constraint integrates over.
        if cov[0] * cov[4] - cov[1] * cov[3] < -_COVARIANCE_TOLERANCE:
            raise ValueError("pose covariance xy block must be positive semidefinite")

    @property
    def xy(self) -> tuple[float, float]:
        return (self.x, self.y)

    @property
    def is_healthy(self) -> bool:
        return self.health is PoseHealth.HEALTHY

    @property
    def is_exact(self) -> bool:
        """True when the xy block is exactly zero — the boolean-geometry regime."""

        return self.covariance[0] == 0.0 and self.covariance[4] == 0.0 and self.covariance[1] == 0.0

    @property
    def xy_covariance(self) -> tuple[float, float, float, float]:
        """Row-major 2x2 xy block ``(sxx, sxy, syx, syy)``."""

        return (self.covariance[0], self.covariance[1], self.covariance[3], self.covariance[4])

    @property
    def position_sigma_m(self) -> float:
        """Isotropic-equivalent 1-sigma position uncertainty (trace-based).

        This is the scalar ``Z_r`` hand-off to
        :class:`parcel_robot.authority.SafetyEnvelope` — one number that widens
        every envelope when a real localizer lands.
        """

        return math.sqrt(max(0.0, self.covariance[0] + self.covariance[4]))

    @property
    def yaw_sigma_rad(self) -> float:
        return math.sqrt(max(0.0, self.covariance[8]))


@runtime_checkable
class PoseProvider(Protocol):
    """The one interface navigation may use to learn where the robot is."""

    def get_pose(self, frame: Frame) -> PoseEstimate: ...


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class TruthPoseProvider:
    """Sim ground truth on both frames, zero covariance, always ``HEALTHY``.

    Installing this changes nothing: it returns exactly the floats the caller
    fed in.  That equality is the entire point — the seam lands first, the
    localizer never (in sim).
    """

    name = "truth"

    def __init__(
        self,
        x: float = 0.0,
        y: float = 0.0,
        yaw: float = 0.0,
        *,
        stamp_monotonic_s: float = 0.0,
    ) -> None:
        self._x = _finite(x, "x")
        self._y = _finite(y, "y")
        self._yaw = _finite(yaw, "yaw")
        self._stamp = _finite(stamp_monotonic_s, "stamp_monotonic_s")

    def update_truth(
        self,
        x: float,
        y: float,
        yaw: float,
        *,
        stamp_monotonic_s: float | None = None,
    ) -> None:
        self._x = _finite(x, "x")
        self._y = _finite(y, "y")
        self._yaw = _finite(yaw, "yaw")
        if stamp_monotonic_s is not None:
            self._stamp = _finite(stamp_monotonic_s, "stamp_monotonic_s")

    def reset(self, x: float = 0.0, y: float = 0.0, yaw: float = 0.0) -> None:
        self.update_truth(x, y, yaw, stamp_monotonic_s=0.0)

    def get_pose(self, frame: Frame) -> PoseEstimate:
        if not isinstance(frame, Frame):
            raise TypeError("frame must be a Frame member")
        return PoseEstimate(
            x=self._x,
            y=self._y,
            yaw=self._yaw,
            frame=frame,
            health=PoseHealth.HEALTHY,
            covariance=ZERO_COVARIANCE,
            stamp_monotonic_s=self._stamp,
        )


@dataclass(frozen=True)
class OdometryNoiseParams:
    """Probabilistic Robotics Table 5.6 alpha odometry model parameters.

    ``alpha1`` rotation-from-rotation, ``alpha2`` rotation-from-translation,
    ``alpha3`` translation-from-translation, ``alpha4``
    translation-from-rotation.  All four are variance coefficients, so the
    sampled standard deviation of a straight ``d``-metre increment is
    ``sqrt(alpha3) * d``.

    **The units trap, stated plainly.**  Because the variance scales with the
    *increment squared*, the relative drift a given alpha produces depends on
    the update cadence: accumulating ``N`` steps of length ``d`` over a total
    ``D = N*d`` gives variance ``alpha3 * D * d``, i.e. sigma grows like
    ``sqrt(D)``, not like ``D``.  A drift **percentage** is therefore only
    meaningful with the trajectory length and step length stated.  See
    ``configs/navigation/pose.yaml`` for the derivation that lands the
    ``calibrated_go2`` profile inside the published DogLegs Go2 band.

    **Foot slip** (``slip_jump_*``) is a *discrete* error source the alpha model
    cannot express: a leg loses traction, the body moves while the kinematic
    chain says it did not, and the estimate takes a step displacement.  It is a
    Poisson process along *distance* (not time), and it is OFF unless both the
    magnitude and the rate are strictly positive — see
    :meth:`DriftingOdomProvider.update_truth` for why that guard is load-bearing.
    """

    # The plan's named defaults.  These are a stated starting point, not a
    # calibration: at the 0.1 m sim step they produce ~3% / 20 m (stress tier).
    alpha1: float = 0.2
    alpha2: float = 0.2
    alpha3: float = 0.2
    alpha4: float = 0.2
    #: Per-run systematic error (a miscalibrated leg length / wheel radius):
    #: a constant multiplicative scale on translation, drawn once per run.
    systematic_translation_scale_sigma: float = 0.0
    #: Per-run systematic yaw bias in rad per metre travelled, drawn once.
    systematic_yaw_bias_sigma_rad_per_m: float = 0.0
    seed: int = 20260807
    # NOTE: the slip knobs are appended *after* ``seed`` on purpose.  Inserting
    # them mid-list would silently re-map any positional construction of this
    # dataclass; appending cannot.  Field order is API surface here.
    #: Displacement of one slip event, in metres, applied in a uniformly random
    #: direction.  ``0.0`` disables slip entirely (the shipping default).
    slip_jump_magnitude_m: float = 0.0
    #: Mean slip-event rate in events per metre TRAVELLED.  ``0.0`` disables
    #: slip entirely.  Distance-rated rather than time-rated because slip is
    #: caused by stepping, not by the clock.
    slip_jump_rate_per_m: float = 0.0

    @property
    def slip_enabled(self) -> bool:
        """True only when a slip event can actually occur.

        Both knobs must be positive: a zero-magnitude event is a no-op and a
        zero-rate process never fires, so either zero means "off" and the
        provider must not even draw for it.
        """

        return self.slip_jump_magnitude_m > 0.0 and self.slip_jump_rate_per_m > 0.0

    def __post_init__(self) -> None:
        for name in (
            "alpha1",
            "alpha2",
            "alpha3",
            "alpha4",
            "systematic_translation_scale_sigma",
            "systematic_yaw_bias_sigma_rad_per_m",
            "slip_jump_magnitude_m",
            "slip_jump_rate_per_m",
        ):
            value = _finite(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"odometry {name} must be non-negative")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "seed", int(self.seed))

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> OdometryNoiseParams:
        raw = dict(data or {})
        unknown = set(raw) - {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        if unknown:
            raise ValueError(f"unknown odometry noise keys: {sorted(unknown)}")
        return cls(**raw)


def _wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def _normalize_lost_windows(
    windows: Sequence[Sequence[float]] | None,
) -> tuple[tuple[float, float], ...]:
    """Validate scheduled ``(start_s, duration_s)`` LOST windows; fail closed.

    Windows are episode-relative (measured from the provider's first stamped
    truth sample, exactly like ``lost_after_s``) and half-open — ``[start,
    start + duration)`` — so a window's duration is exactly ``duration_s`` and
    recovery happens at a single well-defined instant.  Overlapping windows are
    legal and mean their union; the tuple is sorted so two configs that name the
    same set of windows compare equal regardless of authoring order.
    """

    if windows is None:
        return ()
    if isinstance(windows, (str, bytes)) or not isinstance(windows, Sequence):
        raise TypeError("lost_windows must be a sequence of (start_s, duration_s) pairs")
    out: list[tuple[float, float]] = []
    for entry in windows:
        if isinstance(entry, (str, bytes)) or not isinstance(entry, Sequence) or len(entry) != 2:
            raise ValueError("each lost window must be a (start_s, duration_s) pair")
        start = _finite(entry[0], "lost window start_s")
        duration = _finite(entry[1], "lost window duration_s")
        if start < 0.0:
            raise ValueError("lost window start_s must be non-negative")
        if duration <= 0.0:
            raise ValueError("lost window duration_s must be positive")
        out.append((start, duration))
    return tuple(sorted(out))


class DriftingOdomProvider:
    """``ODOM`` drifts under the alpha odometry model; ``MAP`` is re-anchored.

    Truth deltas are fed in incrementally (``update_truth``); each delta is
    decomposed into ``(rot1, trans, rot2)``, corrupted per Probabilistic
    Robotics Table 5.6, and integrated onto the previous *estimated* pose.  The
    result is smooth and unbounded-drifting — exactly the ``ODOM`` contract.

    ``MAP`` is **not** a localizer.  By default it is the truth pose passed
    straight through, standing in for a perfect global reference so the frame
    binding can be measured without building SLAM (a binding anti-goal).  With
    ``map_correction.enabled``, ``MAP`` instead follows ``ODOM`` and snaps back
    to truth every ``interval_s`` — a discontinuous re-anchor that exercises the
    "MAP may jump" half of REP-105.

    **Health has two independent schedules**, and they answer different
    questions.  ``lost_after_s`` is a one-way trapdoor: once elapsed, the
    provider reports ``LOST`` forever.  ``lost_windows`` is a list of
    ``(start_s, duration_s)`` dropouts that **recover** — the robot walks under
    a gantry, localization drops, and it comes back.  Only the second one can
    exercise a consumer's re-acquisition path, which is why it exists.  Both are
    episode-relative, both default to off, and ``forced_health`` still overrides
    both.

    Drift integration is **independent of health**: ``ODOM`` keeps accumulating
    through a LOST window exactly as it would have without one.  That is the
    honest model — a localizer announcing it is lost does not stop the legs — and
    it is pinned by a test that drives the same seed with and without windows and
    demands bit-identical ODOM.
    """

    name = "drifting_odom"

    def __init__(
        self,
        params: OdometryNoiseParams | None = None,
        *,
        map_correction_enabled: bool = False,
        map_correction_interval_s: float = 5.0,
        forced_health: PoseHealth | None = None,
        lost_after_s: float | None = None,
        lost_windows: Sequence[Sequence[float]] | None = None,
        map_covariance_floor_m2: float = 0.0,
    ) -> None:
        self.params = params or OdometryNoiseParams()
        self.map_correction_enabled = bool(map_correction_enabled)
        self.map_correction_interval_s = _finite(
            map_correction_interval_s, "map_correction_interval_s"
        )
        if self.map_correction_interval_s <= 0.0:
            raise ValueError("map_correction_interval_s must be positive")
        if forced_health is not None and not isinstance(forced_health, PoseHealth):
            raise TypeError("forced_health must be a PoseHealth member or None")
        self.forced_health = forced_health
        self.lost_after_s = None if lost_after_s is None else _finite(lost_after_s, "lost_after_s")
        self.lost_windows = _normalize_lost_windows(lost_windows)
        self.map_covariance_floor_m2 = _finite(
            map_covariance_floor_m2, "map_covariance_floor_m2"
        )
        if self.map_covariance_floor_m2 < 0.0:
            raise ValueError("map_covariance_floor_m2 must be non-negative")
        self.reset()

    # -- lifecycle ---------------------------------------------------------

    def reset(self, x: float = 0.0, y: float = 0.0, yaw: float = 0.0) -> None:
        """Start a fresh run: odom == truth, zero accumulated covariance.

        The first :meth:`update_truth` after a reset **re-baselines** rather
        than integrating a delta, so a caller never has to know the robot's
        start pose to install a provider.  That matters: the obvious
        alternative — reading the world once at construction — perturbs the
        simulator's LiDAR noise RNG and silently shifts every downstream
        result.  A real odometry source has the same property: it cannot know
        where it started until its first sample arrives.
        """

        self._rng = random.Random(self.params.seed)
        self._seeded = False
        self._truth = (_finite(x, "x"), _finite(y, "y"), _finite(yaw, "yaw"))
        self._odom = self._truth
        self._map = self._truth
        self._stamp = 0.0
        self._start_stamp: float | None = None
        self._last_correction_s = 0.0
        self._distance_m = 0.0
        self._slip_events = 0
        # Accumulated ODOM covariance: isotropic xy plus a yaw term.  A
        # documented approximation, not a filter — there is no filter here.
        self._var_xy = 0.0
        self._var_yaw = 0.0
        # Per-run systematic error, drawn once (a miscalibrated body, not noise).
        self._scale_bias = 1.0 + self._rng.gauss(
            0.0, self.params.systematic_translation_scale_sigma
        )
        self._yaw_bias_rad_per_m = self._rng.gauss(
            0.0, self.params.systematic_yaw_bias_sigma_rad_per_m
        )

    # -- truth ingestion ---------------------------------------------------

    def update_truth(
        self,
        x: float,
        y: float,
        yaw: float,
        *,
        stamp_monotonic_s: float | None = None,
    ) -> None:
        x = _finite(x, "x")
        y = _finite(y, "y")
        yaw = _finite(yaw, "yaw")
        previous = self._truth
        self._truth = (x, y, yaw)
        if stamp_monotonic_s is not None:
            self._stamp = _finite(stamp_monotonic_s, "stamp_monotonic_s")
            if self._start_stamp is None:
                self._start_stamp = self._stamp
        if not self._seeded:
            # First sample after a reset: adopt it as the origin of all three
            # frames. No delta, no noise, no drift attributed to arriving.
            self._seeded = True
            self._odom = self._truth
            self._map = self._truth
            return

        dx = x - previous[0]
        dy = y - previous[1]
        trans = math.hypot(dx, dy)
        if trans < 1e-12 and abs(_wrap_angle(yaw - previous[2])) < 1e-12:
            self._maybe_correct_map()
            return
        # Table 5.6 decomposition.  A pure in-place rotation has no meaningful
        # rot1 heading, so attribute the whole turn to rot2 (standard guard).
        if trans < 1e-6:
            rot1 = 0.0
            rot2 = _wrap_angle(yaw - previous[2])
        else:
            rot1 = _wrap_angle(math.atan2(dy, dx) - previous[2])
            rot2 = _wrap_angle(yaw - previous[2] - rot1)

        p = self.params
        var_rot1 = p.alpha1 * rot1 * rot1 + p.alpha2 * trans * trans
        var_trans = p.alpha3 * trans * trans + p.alpha4 * (rot1 * rot1 + rot2 * rot2)
        var_rot2 = p.alpha1 * rot2 * rot2 + p.alpha2 * trans * trans

        hat_rot1 = rot1 - self._rng.gauss(0.0, math.sqrt(var_rot1))
        hat_trans = trans * self._scale_bias - self._rng.gauss(0.0, math.sqrt(var_trans))
        hat_rot2 = rot2 - self._rng.gauss(0.0, math.sqrt(var_rot2))
        hat_rot2 += self._yaw_bias_rad_per_m * trans

        ox, oy, oyaw = self._odom
        nx = ox + hat_trans * math.cos(oyaw + hat_rot1)
        ny = oy + hat_trans * math.sin(oyaw + hat_rot1)
        nyaw = _wrap_angle(oyaw + hat_rot1 + hat_rot2)

        # Foot slip — a discrete mis-integration event, not Gaussian noise.
        #
        # THE GUARD IS LOAD-BEARING. ``self._rng`` is a single shared stream, so
        # drawing here when slip is off would advance it and change every
        # pre-existing profile's trajectory bit-for-bit — the calibrated band,
        # the pinned stress figures, all of it. Slip therefore draws NOTHING
        # unless it is genuinely enabled, and ``tests/test_pose_degraded_
        # profiles.py`` pins the pre-slip ODOM endpoints to prove it.
        #
        # Model: a Poisson process along distance with rate ``slip_jump_rate_
        # per_m``, thinned to at most one event per increment. Over an increment
        # of length ``trans`` the event probability is ``1 - exp(-rate*trans)``,
        # which is exact for the "at least one event" question and negligibly
        # different from the count at the 0.1 m increments this runs at.
        slip_var = 0.0
        if p.slip_enabled:
            slip_var = 0.5 * p.slip_jump_rate_per_m * trans * p.slip_jump_magnitude_m**2
            if self._rng.random() < -math.expm1(-p.slip_jump_rate_per_m * trans):
                heading = self._rng.uniform(-math.pi, math.pi)
                nx += p.slip_jump_magnitude_m * math.cos(heading)
                ny += p.slip_jump_magnitude_m * math.sin(heading)
                self._slip_events += 1
        self._odom = (nx, ny, nyaw)

        self._distance_m += trans
        # ``slip_var`` is the EXPECTED per-axis variance the slip process
        # contributes over this increment (a fixed-magnitude jump in a uniform
        # direction has per-axis variance ``m^2/2``, and the expected event
        # count is ``rate*trans``). Expectation, not the realized jump, because
        # covariance reports uncertainty — the same convention the alpha terms
        # already use. It is exactly 0.0 when slip is off, so the accumulation
        # stays bit-identical for every pre-existing profile.
        self._var_xy += var_trans + slip_var
        self._var_yaw += var_rot1 + var_rot2
        if self.map_correction_enabled:
            self._map = (
                self._map[0] + (nx - ox),
                self._map[1] + (ny - oy),
                _wrap_angle(self._map[2] + _wrap_angle(nyaw - oyaw)),
            )
        self._maybe_correct_map()

    def _maybe_correct_map(self) -> None:
        if not self.map_correction_enabled:
            self._map = self._truth
            return
        if self._stamp - self._last_correction_s >= self.map_correction_interval_s:
            self._last_correction_s = self._stamp
            self._map = self._truth  # the re-anchor jump

    # -- health ------------------------------------------------------------

    def _health(self) -> PoseHealth:
        """Resolve health.  Precedence: forced > one-way trapdoor > windows.

        The order is not arbitrary.  ``forced_health`` is a test hook and must
        win outright.  ``lost_after_s`` is permanent, so once it has fired no
        window can un-fire it — checking it first makes that irreversibility
        structural rather than incidental.  Scheduled windows are last and are
        the only branch that can ever return to ``HEALTHY``.
        """

        if self.forced_health is not None:
            return self.forced_health
        if (
            self.lost_after_s is not None
            and self._start_stamp is not None
            and self._stamp - self._start_stamp >= self.lost_after_s
        ):
            return PoseHealth.LOST
        if self.lost_windows and self._start_stamp is not None:
            elapsed = self._stamp - self._start_stamp
            for start, duration in self.lost_windows:
                if start <= elapsed < start + duration:
                    return PoseHealth.LOST
        return PoseHealth.HEALTHY

    # -- provider ----------------------------------------------------------

    @property
    def travelled_m(self) -> float:
        return self._distance_m

    @property
    def slip_events(self) -> int:
        """Slip events fired since the last reset — non-vacuity evidence.

        A slip profile that reports zero events over an episode did not
        actually exercise the mechanism, and a test or eval row that claims it
        did would be lying.  This counter is how that claim gets checked.
        """

        return self._slip_events

    @property
    def odom_error_m(self) -> float:
        """Truth-vs-ODOM position error, for calibration measurement only."""

        return math.hypot(self._odom[0] - self._truth[0], self._odom[1] - self._truth[1])

    @property
    def odom_yaw_error_rad(self) -> float:
        return abs(_wrap_angle(self._odom[2] - self._truth[2]))

    def get_pose(self, frame: Frame) -> PoseEstimate:
        if not isinstance(frame, Frame):
            raise TypeError("frame must be a Frame member")
        health = self._health()
        if frame is Frame.ODOM:
            x, y, yaw = self._odom
            var_xy = self._var_xy
            var_yaw = self._var_yaw
        else:
            x, y, yaw = self._map
            # A re-anchoring MAP inherits ODOM's growth between corrections;
            # a truth-passthrough MAP carries only the configured floor.
            var_xy = self._var_xy if self.map_correction_enabled else 0.0
            var_xy = max(var_xy, self.map_covariance_floor_m2)
            var_yaw = self._var_yaw if self.map_correction_enabled else 0.0
        return PoseEstimate(
            x=x,
            y=y,
            yaw=yaw,
            frame=frame,
            health=health,
            covariance=(var_xy, 0.0, 0.0, 0.0, var_xy, 0.0, 0.0, 0.0, var_yaw),
            stamp_monotonic_s=self._stamp,
        )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PoseConfig:
    """Parsed ``configs/navigation/pose.yaml``.  Unknown keys fail closed."""

    provider: str = "truth"
    noise: OdometryNoiseParams = field(default_factory=OdometryNoiseParams)
    map_correction_enabled: bool = False
    map_correction_interval_s: float = 5.0
    forced_health: PoseHealth | None = None
    lost_after_s: float | None = None
    #: Scheduled ``(start_s, duration_s)`` LOST windows that RECOVER.  Empty by
    #: default, so every pre-existing profile parses to exactly the config it
    #: parsed to before this field existed.
    lost_windows: tuple[tuple[float, float], ...] = ()
    map_covariance_floor_m2: float = 0.0
    inside_probability_threshold: float = 0.9

    def __post_init__(self) -> None:
        if self.provider not in {"truth", "drifting_odom"}:
            raise ValueError(f"unknown pose provider: {self.provider!r}")
        if not 0.0 < self.inside_probability_threshold <= 1.0:
            raise ValueError("inside_probability_threshold must be in (0, 1]")
        object.__setattr__(self, "lost_windows", _normalize_lost_windows(self.lost_windows))

    def build(self) -> PoseProvider:
        if self.provider == "truth":
            return TruthPoseProvider()
        return DriftingOdomProvider(
            self.noise,
            map_correction_enabled=self.map_correction_enabled,
            map_correction_interval_s=self.map_correction_interval_s,
            forced_health=self.forced_health,
            lost_after_s=self.lost_after_s,
            lost_windows=self.lost_windows,
            map_covariance_floor_m2=self.map_covariance_floor_m2,
        )


_TOP_LEVEL_KEYS = {"provider", "profiles", "chance_constrained"}
_PROFILE_KEYS = {
    "noise",
    "map_correction",
    "health",
    "map_covariance_floor_m2",
}
# Nested key sets. The profile level already failed closed; the two sub-maps did
# NOT — a typo'd ``health: {los_after_s: 3}`` used to be silently ignored, which
# is the exact failure mode fail-closed parsing exists to prevent. Adding a new
# nested key (``lost_windows``) without closing that hole would have widened it,
# so both sub-maps are now validated. No pre-existing profile carries an unknown
# nested key, so no parsed config moves; tests pin all of them.
_MAP_CORRECTION_KEYS = {"enabled", "interval_s"}
_HEALTH_KEYS = {"force", "lost_after_s", "lost_windows"}
_LOST_WINDOW_KEYS = {"start_s", "duration_s"}


def _lost_windows_from_yaml(raw: object, profile: str) -> tuple[tuple[float, float], ...]:
    """Parse ``health.lost_windows`` from yaml.  One shape only, fail closed.

    Entries are mappings — ``{start_s: 4.0, duration_s: 3.0}`` — rather than
    bare pairs, because ``[4.0, 3.0]`` is ambiguous between (start, duration)
    and (start, end) at a glance, and a silently misread dropout schedule would
    invalidate every eval row that ran under it.

    Wrong *shape* raises :class:`TypeError`; well-shaped but invalid *values*
    raise :class:`ValueError`.  Both fail closed — the distinction only tells a
    reader whether the yaml is malformed or merely wrong.
    """

    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise TypeError(f"pose profile {profile!r} health.lost_windows must be a list")
    windows: list[tuple[float, float]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise TypeError(
                f"pose profile {profile!r} health.lost_windows entries must be mappings "
                "with start_s and duration_s"
            )
        unknown = set(entry) - _LOST_WINDOW_KEYS
        if unknown:
            raise ValueError(
                f"unknown keys in pose profile {profile!r} lost window: {sorted(unknown)}"
            )
        missing = _LOST_WINDOW_KEYS - set(entry)
        if missing:
            raise ValueError(
                f"pose profile {profile!r} lost window is missing keys: {sorted(missing)}"
            )
        windows.append((entry["start_s"], entry["duration_s"]))
    return _normalize_lost_windows(windows)


def load_pose_config(
    path: str | Path | None = None,
    *,
    profile: str | None = None,
) -> PoseConfig:
    """Load ``configs/navigation/pose.yaml``; fail closed on unknown keys."""

    import yaml

    if path is None:
        try:
            from parcel_robot.paths import resolve_navigation_config

            cfg_path = resolve_navigation_config("configs/navigation/pose.yaml")
        except (ImportError, FileNotFoundError):
            cfg_path = (
                Path(__file__).resolve().parents[2] / "configs/navigation/pose.yaml"
            ).resolve()
    else:
        cfg_path = Path(path).expanduser().resolve()
    data = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise ValueError(f"unknown keys in {cfg_path}: {sorted(unknown)}")
    profiles = dict(data.get("profiles") or {})
    name = profile or str(data.get("provider") or "truth")
    if name == "truth":
        threshold = float(
            (data.get("chance_constrained") or {}).get("inside_probability_threshold", 0.9)
        )
        return PoseConfig(provider="truth", inside_probability_threshold=threshold)
    if name not in profiles:
        raise ValueError(f"pose profile {name!r} is not defined in {cfg_path}")
    raw = dict(profiles[name] or {})
    unknown = set(raw) - _PROFILE_KEYS
    if unknown:
        raise ValueError(f"unknown keys in pose profile {name!r}: {sorted(unknown)}")
    correction = dict(raw.get("map_correction") or {})
    unknown = set(correction) - _MAP_CORRECTION_KEYS
    if unknown:
        raise ValueError(
            f"unknown keys in pose profile {name!r} map_correction: {sorted(unknown)}"
        )
    health = dict(raw.get("health") or {})
    unknown = set(health) - _HEALTH_KEYS
    if unknown:
        raise ValueError(f"unknown keys in pose profile {name!r} health: {sorted(unknown)}")
    forced = health.get("force")
    return PoseConfig(
        provider="drifting_odom",
        noise=OdometryNoiseParams.from_mapping(raw.get("noise")),
        map_correction_enabled=bool(correction.get("enabled", False)),
        map_correction_interval_s=float(correction.get("interval_s", 5.0)),
        forced_health=None if forced in (None, "healthy") else PoseHealth(str(forced)),
        lost_after_s=(
            None if health.get("lost_after_s") is None else float(health["lost_after_s"])
        ),
        lost_windows=_lost_windows_from_yaml(health.get("lost_windows"), name),
        map_covariance_floor_m2=float(raw.get("map_covariance_floor_m2", 0.0)),
        inside_probability_threshold=float(
            (data.get("chance_constrained") or {}).get("inside_probability_threshold", 0.9)
        ),
    )


def provider_from_config(
    path: str | Path | None = None,
    *,
    profile: str | None = None,
) -> PoseProvider:
    """Build a ready-to-use provider by profile NAME.  The whole seam.

    This is the entire integration contract for a degraded-pose eval arm — a
    caller names a profile and gets a provider; it never constructs
    :class:`OdometryNoiseParams`, never learns what an alpha coefficient is, and
    never needs a code change here to add a tier.  The degraded-pose ladder
    (DR-1, ``scrum/20260811/task_2``) is therefore reachable as::

        provider_from_config(profile="calibrated_go2")    # nominal rung
        provider_from_config(profile="go2_aggressive")    # 2x the published band
        provider_from_config(profile="go2_degraded")      # 4x, plus foot slip
        provider_from_config(profile=f"{name}_lost")      # + a recovering dropout

    ``profile=None`` yields the shipping truth passthrough.  Unknown profiles
    and unknown yaml keys raise — a mistyped arm fails loudly instead of
    quietly measuring the nominal tier and reporting it as degraded.

    Providers are stateful and accumulate drift, so callers build a FRESH one
    per episode (``HeadlessCityQualityHarness.new_pose_provider``).
    """

    return load_pose_config(path, profile=profile).build()


# ---------------------------------------------------------------------------
# The seam: the ONE way navigation reads a pose
# ---------------------------------------------------------------------------

_DEFAULT_LOCK = threading.Lock()
_DEFAULT_PROVIDER: PoseProvider | None = None


def default_pose_provider() -> PoseProvider | None:
    with _DEFAULT_LOCK:
        return _DEFAULT_PROVIDER


@contextmanager
def use_pose_provider(provider: PoseProvider | None) -> Iterator[PoseProvider | None]:
    """Install a process-default provider for the duration of the block.

    This is an **eval / test injection seam**, not a production wiring path:
    ``runtime.py`` and the headless harness attach their provider explicitly to
    each observation.  It exists so a drift tier can be measured through an
    unmodified eval runner (Wave-0-owned files stay untouched).
    """

    global _DEFAULT_PROVIDER
    with _DEFAULT_LOCK:
        previous = _DEFAULT_PROVIDER
        _DEFAULT_PROVIDER = provider
    try:
        yield provider
    finally:
        with _DEFAULT_LOCK:
            _DEFAULT_PROVIDER = previous


#: The extras key production code uses to attach a provider to an observation.
POSE_PROVIDER_KEY = "pose_provider"


def _feed_from_observation(provider: PoseProvider, observation: Any) -> None:
    """Hand one observation's truth to a provider that accepts truth updates."""

    update = getattr(provider, "update_truth", None)
    if not callable(update):
        return
    position = getattr(observation, "position", (0.0, 0.0, 0.0))
    extras = getattr(observation, "extras", None)
    stamp = None
    if isinstance(extras, dict):
        raw = extras.get("time_s")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw):
            stamp = float(raw)
    update(
        float(position[0]),
        float(position[1]),
        math.radians(float(getattr(observation, "heading_deg", 0.0))),
        stamp_monotonic_s=stamp,
    )


def observation_pose(observation: Any, frame: Frame) -> PoseEstimate:
    """Return the robot pose in ``frame`` — the only sanctioned pose read.

    Resolution order:

    1. a :class:`PoseProvider` attached to ``observation.extras`` (production),
    2. the process-default provider (eval/test injection),
    3. otherwise the observation's own truth fields, which is *exactly*
       :class:`TruthPoseProvider` semantics.  Step 3 is what makes the migration
       equality-preserving: an unmigrated caller that builds a bare
       ``NavObservation`` gets the same floats it always did.

    ``yaw`` is ``radians(observation.heading_deg)`` — the observation's *correct*
    heading channel.  See :func:`legacy_position_yaw` for the one that is not.
    """

    extras = getattr(observation, "extras", None)
    provider: PoseProvider | None = None
    if isinstance(extras, dict):
        candidate = extras.get(POSE_PROVIDER_KEY)
        if candidate is not None:
            if not isinstance(candidate, PoseProvider):
                raise TypeError("extras['pose_provider'] must implement PoseProvider")
            provider = candidate
    if provider is None:
        injected = default_pose_provider()
        if injected is not None:
            # The process-default seam has no other truth source, so it takes
            # it from the observation the unmodified caller already built. This
            # is idempotent: a second call in the same tick sees a zero delta
            # and adds no extra noise. An *attached* provider is the caller's to
            # feed and is never touched here.
            _feed_from_observation(injected, observation)
            provider = injected
    if provider is not None:
        pose = provider.get_pose(frame)
        if not isinstance(pose, PoseEstimate):
            raise TypeError("PoseProvider.get_pose must return a PoseEstimate")
        if pose.frame is not frame:
            raise ValueError(f"provider returned frame {pose.frame} for request {frame}")
        return pose
    position = getattr(observation, "position", (0.0, 0.0, 0.0))
    return PoseEstimate(
        x=float(position[0]),
        y=float(position[1]),
        yaw=math.radians(float(getattr(observation, "heading_deg", 0.0))),
        frame=frame,
        health=PoseHealth.HEALTHY,
        covariance=ZERO_COVARIANCE,
        stamp_monotonic_s=0.0,
    )


def legacy_position_yaw(observation: Any, *, zero_default: bool = False) -> float:
    """Reproduce the pre-seam ``position[2]``-as-yaw read, defect included.

    **This is a bug, preserved deliberately.**  ``NavObservation.position`` is
    ``(x, y, z)`` — ``z`` is the robot's *standing height* (0.27 m on the Go2),
    not a heading.  Four sites in ``navigation/pipeline.py`` have always read
    ``position[2]`` as yaw in radians, so a standing Go2 believes it is facing
    15.5 degrees off its true heading during scan/frontier geometry.

    Fixing it changes behavior and therefore belongs in its own paired-seed
    commit (STRATA plan: equality first, value changes separately).  This
    function exists so the defect lives in exactly ONE named place instead of
    four anonymous ones, and so the pose-authority archon rule can point at it.
    Deleting this function is the fix.

    ``zero_default`` selects between the two *different* fallbacks the four
    original sites used when ``position`` was shorter than three entries
    (three sites fell back to ``radians(heading_deg)``, one to ``0.0``). Both
    are reproduced exactly rather than unified, because unifying them would be
    a behavior change hiding inside a refactor.
    """

    position = getattr(observation, "position", ())
    if len(position) > 2:
        return float(position[2])
    if zero_default:
        return 0.0
    return math.radians(float(getattr(observation, "heading_deg", 0.0)))


# ---------------------------------------------------------------------------
# Chance-constrained polygon membership
# ---------------------------------------------------------------------------


def _standard_normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _signed_area(polygon: Sequence[Sequence[float]]) -> float:
    total = 0.0
    count = len(polygon)
    for index in range(count):
        x0, y0 = float(polygon[index][0]), float(polygon[index][1])
        x1, y1 = float(polygon[(index + 1) % count][0]), float(polygon[(index + 1) % count][1])
        total += x0 * y1 - x1 * y0
    return 0.5 * total


def point_in_polygon_with_clearance_pure(
    point: tuple[float, float],
    polygon: Sequence[Sequence[float]],
    clearance_m: float = 0.0,
) -> bool:
    """Boolean membership with an inward margin — the zero-covariance answer.

    Kept local (rather than imported from ``navigation.approach``) so this
    module stays at the bottom of the import graph.  A test pins it against
    ``approach.point_in_polygon_with_clearance`` over a dense grid.
    """

    count = len(polygon)
    if count < 3:
        return False
    x, y = float(point[0]), float(point[1])
    inside = False
    j = count - 1
    for i in range(count):
        xi, yi = float(polygon[i][0]), float(polygon[i][1])
        xj, yj = float(polygon[j][0]), float(polygon[j][1])
        if (yi > y) != (yj > y):
            cross = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < cross:
                inside = not inside
        j = i
    if not inside:
        return False
    # The +1e-9 slack is not decoration: it is copied from
    # ``navigation.approach._has_clearance`` verbatim, because a point exactly
    # ``clearance`` from an edge lands on the wrong side of a bare ``>=`` by one
    # ULP. Any divergence here would be a behavior change wearing a refactor's
    # clothes; ``test_pose_seam`` pins the two against each other on a grid.
    return _distance_to_boundary(point, polygon) + 1e-9 >= clearance_m


def _distance_to_boundary(
    point: tuple[float, float],
    polygon: Sequence[Sequence[float]],
) -> float:
    x, y = float(point[0]), float(point[1])
    best = float("inf")
    count = len(polygon)
    for index in range(count):
        x0, y0 = float(polygon[index][0]), float(polygon[index][1])
        x1, y1 = float(polygon[(index + 1) % count][0]), float(polygon[(index + 1) % count][1])
        dx, dy = x1 - x0, y1 - y0
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:  # same degenerate-edge guard as approach.py
            best = min(best, math.hypot(x - x0, y - y0))
            continue
        t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / length_sq))
        best = min(best, math.hypot(x - (x0 + t * dx), y - (y0 + t * dy)))
    return best


def p_inside_polygon(
    pose: PoseEstimate,
    polygon: Sequence[Sequence[float]],
    *,
    clearance_m: float = 0.0,
) -> float:
    """``P(robot inside polygon)`` under the pose's xy covariance.

    Half-space Gaussian approximation: for each polygon edge, the inward signed
    distance ``d_i`` is projected onto the edge normal, giving
    ``sigma_i = sqrt(n_i^T Sigma_xy n_i)``, and the per-edge satisfaction
    probability is ``Phi(d_i / sigma_i)``.  The product over edges is the
    (independence-assuming) membership probability — the standard
    chance-constraint form, exact only for a *convex* polygon and an
    upper bound on correlated edges otherwise.

    **Exact reduction.**  At zero xy covariance the function short-circuits to
    :func:`point_in_polygon_with_clearance_pure`, so it returns exactly ``1.0``
    or ``0.0`` and cannot disagree with today's boolean geometry by a single
    ULP.  That is what lets it be wired behind a zero-covariance equality.
    """

    if not isinstance(pose, PoseEstimate):
        raise TypeError("p_inside_polygon requires a PoseEstimate")
    points = [(float(px), float(py)) for px, py in polygon]
    if len(points) < 3:
        return 0.0
    if pose.is_exact:
        return 1.0 if point_in_polygon_with_clearance_pure(pose.xy, points, clearance_m) else 0.0

    sxx, sxy, syx, syy = pose.xy_covariance
    orientation = 1.0 if _signed_area(points) >= 0.0 else -1.0
    probability = 1.0
    for index in range(len(points)):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % len(points)]
        ex, ey = x1 - x0, y1 - y0
        length = math.hypot(ex, ey)
        if length <= 0.0:
            continue
        # Inward unit normal for the polygon's own winding.
        nx = -ey / length * orientation
        ny = ex / length * orientation
        distance = (pose.x - x0) * nx + (pose.y - y0) * ny - clearance_m
        variance = nx * (sxx * nx + sxy * ny) + ny * (syx * nx + syy * ny)
        if variance <= 0.0:
            probability *= 1.0 if distance >= 0.0 else 0.0
            continue
        probability *= _standard_normal_cdf(distance / math.sqrt(variance))
        if probability == 0.0:
            return 0.0
    return probability


def p_inside_disc(
    pose: PoseEstimate,
    center: tuple[float, float],
    radius_m: float,
) -> float:
    """``P(robot within radius of center)`` — the disc analogue, same contract.

    Uses the one-sided Gaussian on the radial distance; reduces exactly to the
    boolean test at zero covariance.
    """

    if not isinstance(pose, PoseEstimate):
        raise TypeError("p_inside_disc requires a PoseEstimate")
    distance = math.hypot(pose.x - float(center[0]), pose.y - float(center[1]))
    if pose.is_exact:
        return 1.0 if distance <= float(radius_m) else 0.0
    sigma = math.sqrt(max(pose.xy_covariance[0], pose.xy_covariance[3], 0.0))
    if sigma <= 0.0:
        return 1.0 if distance <= float(radius_m) else 0.0
    return _standard_normal_cdf((float(radius_m) - distance) / sigma)


def make_truth_provider(observation: Any) -> TruthPoseProvider:
    """Build a :class:`TruthPoseProvider` seeded from a ``SimObservation``."""

    robot = observation.robot
    return TruthPoseProvider(
        float(robot.x),
        float(robot.y),
        float(robot.yaw),
        stamp_monotonic_s=float(getattr(observation, "timestamp", 0.0)),
    )


def update_provider_from_sim(provider: PoseProvider, observation: Any) -> PoseProvider:
    """Feed one sim-truth sample into a provider that accepts truth updates."""

    update = getattr(provider, "update_truth", None)
    if callable(update):
        robot = observation.robot
        update(
            float(robot.x),
            float(robot.y),
            float(robot.yaw),
            stamp_monotonic_s=float(getattr(observation, "timestamp", 0.0)),
        )
    return provider
