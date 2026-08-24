"""The MAP-role localizer contract: scans in, ``T_map_odom`` out.

Three types and nothing else.  :class:`ScanFrame` is what a planar LiDAR hands
over, :class:`LocalizationUpdate` is what a localizer publishes, and
:class:`LocalizerProvider` is the one method between them.

**Why the output is ``T_map_odom`` and not a pose.**  REP-105 (and the
docstring at the top of ``pose.py``) says ``MAP`` may jump while ``ODOM`` must
stay continuous.  A localizer that published a base pose would force every
consumer to reconcile two independent estimates; publishing the *correction*
between the two frames keeps ODOM the sole continuous integrator and makes the
discontinuity a single, measurable quantity.  That quantity is ``jump_m`` — the
term ``bridge/timing.py`` carries as ``localization_jump_m`` and has never had
a measured value on any host ("Metres. Largest single-update discontinuity of
the LIO ``T_map_odom``").  It is a required field here so that a provider
cannot ship without publishing it.

**Fail-closed, like ``PoseEstimate``.**  A non-finite entry, an asymmetric
covariance, a negative variance or a negative jump raises at construction
rather than reaching an arrival check.  The validation is deliberately the same
shape as ``pose.PoseEstimate.__post_init__`` so the two cannot drift apart in
what they consider a legal covariance.

**The fourth type: :class:`RelocalizationMatch` (card A3).**  A relocalization
that reports only where it decided it is cannot answer the question the
milestone's re-arm rule asks — CLAUDE_RESPONSE addendum A4 path (a) wants "a
relocalization match whose second-best candidate is worse by a pre-registered
margin across the whole map, not a local residual gate".  NAV-CORE measured
that the shipped provider could not answer it at all
(``research/20260824/nav-core/RESULTS.md`` fix 4: "``_relocalize`` scores
keyframes, keeps the best and never reports a runner-up"), so the update now
carries the *pair* and the gap between them.  A localizer that finds no rival
publishes ``runner_up_residual_m = inf`` and an infinite margin, which is the
honest reading of "nothing else in the map looked like this".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from parcel_robot.pose import PoseHealth

__all__ = [
    "IDENTITY_SE2",
    "LocalizationUpdate",
    "LocalizerProvider",
    "RelocalizationMatch",
    "ScanFrame",
    "compose_se2",
    "invert_se2",
    "wrap_angle",
]

#: The null correction: MAP and ODOM coincide.
IDENTITY_SE2: tuple[float, float, float] = (0.0, 0.0, 0.0)

#: Symmetry / PSD slack, copied from ``pose._COVARIANCE_TOLERANCE`` on purpose.
COVARIANCE_TOLERANCE = 1e-9


def wrap_angle(angle: float) -> float:
    """Wrap to ``(-pi, pi]`` — the same helper ``pose.py`` keeps private."""

    return math.atan2(math.sin(angle), math.cos(angle))


def compose_se2(
    outer: tuple[float, float, float],
    inner: tuple[float, float, float],
) -> tuple[float, float, float]:
    """``outer * inner`` for SE(2) triples ``(x, y, yaw)``."""

    cos_t = math.cos(outer[2])
    sin_t = math.sin(outer[2])
    return (
        outer[0] + cos_t * inner[0] - sin_t * inner[1],
        outer[1] + sin_t * inner[0] + cos_t * inner[1],
        wrap_angle(outer[2] + inner[2]),
    )


def invert_se2(pose: tuple[float, float, float]) -> tuple[float, float, float]:
    """The SE(2) inverse of ``(x, y, yaw)``."""

    cos_t = math.cos(pose[2])
    sin_t = math.sin(pose[2])
    return (
        -(cos_t * pose[0] + sin_t * pose[1]),
        -(-sin_t * pose[0] + cos_t * pose[1]),
        wrap_angle(-pose[2]),
    )


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"localization {name} must be a real number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"localization {name} must be finite")
    return out


def _residual(value: object, name: str) -> float:
    """Like :func:`_finite` but ``inf`` is legal: it means "nothing matched"."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"localization {name} must be a real number")
    out = float(value)
    if math.isnan(out):
        raise ValueError(f"localization {name} must not be NaN")
    if out < 0.0:
        raise ValueError(f"localization {name} is a magnitude and must be non-negative")
    return out


@dataclass(frozen=True)
class RelocalizationMatch:
    """Where a relocalization decided it is, and how alone that answer was.

    ``pose`` / ``residual_m`` are the winning hypothesis and its scan residual;
    ``runner_up`` / ``runner_up_residual_m`` are the best *competing* hypothesis
    at least ``separation_m`` away from it — a candidate nearer than that is the
    same hypothesis re-scored, not a rival.  ``hypotheses`` is how many were
    scored, so a reader can tell a whole-map answer from a two-candidate one.

    :attr:`margin` is the pre-registered quantity A4 path (a) gates on: the
    runner-up's residual excess as a FRACTION of the winner's.  Relative rather
    than absolute because the residual scale is set by the sensor and the room,
    and a fixed metre threshold would mean something different in every venue.

    A negative margin is legal and is the strongest possible refusal: it says
    the competitor fitted BETTER than the pose the provider committed to.
    """

    pose: tuple[float, float, float]
    residual_m: float
    runner_up: tuple[float, float, float]
    runner_up_residual_m: float
    separation_m: float
    hypotheses: int
    source: str

    def __post_init__(self) -> None:
        for name in ("pose", "runner_up"):
            raw = tuple(getattr(self, name))
            if len(raw) != 3:
                raise ValueError(f"RelocalizationMatch.{name} must be (x, y, yaw)")
            object.__setattr__(
                self, name, tuple(_finite(value, name) for value in raw)
            )
        object.__setattr__(self, "residual_m", _residual(self.residual_m, "residual_m"))
        object.__setattr__(
            self,
            "runner_up_residual_m",
            _residual(self.runner_up_residual_m, "runner_up_residual_m"),
        )
        object.__setattr__(
            self, "separation_m", _residual(self.separation_m, "separation_m")
        )
        if int(self.hypotheses) < 1:
            raise ValueError("a match must have scored at least one hypothesis")
        object.__setattr__(self, "hypotheses", int(self.hypotheses))
        object.__setattr__(self, "source", str(self.source))

    @property
    def margin(self) -> float:
        """``(runner_up_residual - residual) / residual``.

        The degenerate cases are spelled out rather than left to float
        arithmetic: a perfect fit (zero residual) against any finite rival is
        infinitely discriminative, and two infinities mean nothing matched at
        all, which is not evidence of anything and scores 0.
        """

        if not math.isfinite(self.residual_m) or self.residual_m <= 0.0:
            return math.inf if math.isfinite(self.runner_up_residual_m) else 0.0
        if not math.isfinite(self.runner_up_residual_m):
            return math.inf
        return (self.runner_up_residual_m - self.residual_m) / self.residual_m

    def is_discriminative(self, minimum_margin: float) -> bool:
        """Is this answer globally alone enough to re-arm on (A4 path (a))?"""

        return self.margin >= float(minimum_margin)


@dataclass(frozen=True)
class ScanFrame:
    """One body-frame planar scan and the monotonic nanoseconds it was taken.

    ``points_xy`` is an ``(N, 2)`` float array in the *body* frame — already
    stripped of the dropout/no-return rays the sensor contract encodes as NaN
    and ``range_max``, because a localizer that has to know a specific
    simulator's NaN convention is not portable.  ``build_scan_frame`` in the
    bench harness is the only place that convention is read.
    """

    points_xy: Any
    stamp_ns: int

    def __post_init__(self) -> None:
        points = self.points_xy
        shape = getattr(points, "shape", None)
        if shape is None or len(shape) != 2 or shape[1] != 2:
            raise TypeError("ScanFrame.points_xy must be an (N, 2) array")
        object.__setattr__(self, "stamp_ns", int(self.stamp_ns))

    @property
    def count(self) -> int:
        return int(self.points_xy.shape[0])


@dataclass(frozen=True)
class LocalizationUpdate:
    """What a MAP-role localizer publishes on every tick, healthy or not.

    ``T_map_odom`` is the SE(2) correction ``(x, y, yaw)``; composing it with
    the ODOM pose gives the MAP pose.  ``cov`` is a row-major 3x3 over
    ``(x, y, yaw)`` of the resulting MAP pose, in the same units as
    ``PoseEstimate.covariance``.  ``jump_m`` is the translation magnitude of
    the change in ``T_map_odom`` since the previous update — zero on a tick
    that produced no correction, and the quantity a stopping envelope needs.
    ``source`` names the estimator so a record can be traced to it.
    """

    T_map_odom: tuple[float, float, float]
    cov: tuple[float, ...]
    health: PoseHealth
    jump_m: float
    stamp_ns: int
    source: str
    #: Card A3 / fix 4.  The whole-map second-best evidence, on the ticks that
    #: produced a relocalization; ``None`` on ordinary tracking ticks, where
    #: there was no global question to answer.  Optional and defaulted so the
    #: field is additive: every construction that predates A3 still validates.
    match: RelocalizationMatch | None = None

    def __post_init__(self) -> None:
        raw_transform = tuple(self.T_map_odom)
        if len(raw_transform) != 3:
            raise ValueError("T_map_odom must be (x, y, yaw)")
        transform = tuple(_finite(value, "T_map_odom") for value in raw_transform)
        object.__setattr__(self, "T_map_odom", transform)
        if not isinstance(self.health, PoseHealth):
            raise TypeError("LocalizationUpdate.health must be a PoseHealth member")
        object.__setattr__(self, "jump_m", _finite(self.jump_m, "jump_m"))
        if self.jump_m < 0.0:
            raise ValueError("jump_m is a magnitude and must be non-negative")
        object.__setattr__(self, "stamp_ns", int(self.stamp_ns))
        object.__setattr__(self, "source", str(self.source))
        object.__setattr__(self, "cov", _validated_covariance(self.cov))
        if self.match is not None and not isinstance(self.match, RelocalizationMatch):
            raise TypeError("LocalizationUpdate.match must be a RelocalizationMatch")

    @property
    def position_sigma_m(self) -> float:
        """Isotropic-equivalent 1-sigma, the scalar the envelope consumes."""

        return math.sqrt(max(0.0, self.cov[0] + self.cov[4]))


def _validated_covariance(raw: object) -> tuple[float, ...]:
    entries = tuple(raw)  # type: ignore[call-overload]
    if len(entries) != 9:
        raise ValueError("localization covariance must be a row-major 3x3")
    cov = tuple(_finite(value, "covariance") for value in entries)
    for index in (0, 4, 8):
        if cov[index] < -COVARIANCE_TOLERANCE:
            raise ValueError("localization covariance diagonal must be non-negative")
    for i, j in ((0, 1), (0, 2), (1, 2)):
        if abs(cov[3 * i + j] - cov[3 * j + i]) > COVARIANCE_TOLERANCE:
            raise ValueError("localization covariance must be symmetric")
    if cov[0] * cov[4] - cov[1] * cov[3] < -COVARIANCE_TOLERANCE:
        raise ValueError("localization covariance xy block must be positive semidefinite")
    return cov


@runtime_checkable
class LocalizerProvider(Protocol):
    """One method.  A tick with no scan is still a tick, and still reports.

    ``update`` is called on every control tick, with ``scan=None`` when the
    sensor produced nothing this tick.  That is what lets a dropout be a
    *health transition* rather than a silence: a provider that only heard from
    its consumer when a scan arrived could never report DEGRADED.
    """

    def update(
        self,
        scan: ScanFrame | None,
        odom_pose: tuple[float, float, float],
        *,
        stamp_ns: int,
    ) -> LocalizationUpdate: ...

    def reset(self) -> None: ...
