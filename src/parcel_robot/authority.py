"""The embodiment authority triple: RobotProfile x SpeedRegime x SafetyEnvelope.

Nav2's own history shows that exposing every constant to YAML does not stop
footprint drift — it multiplies the number of places that can drift. This
module is the opposite move: **derivation, not exposure**. One authority, low
in the import graph (it imports :mod:`parcel_robot.robot_profile` and nothing
else from the package), from which every proximity / arrival / stand-off /
speed number in navigation is *derived by reference*. The knob count goes down.

Three types, plus one derived view:

* :class:`~parcel_robot.robot_profile.RobotProfile` — the body (lives in
  ``robot_profile.py``; this module adds nothing to it, it only consumes it).
* :class:`SpeedRegime` — CRUISE / SEARCH / APPROACH / RECOVER velocity and
  acceleration caps, with a Froude constructor.
* :class:`SafetyEnvelope` — the ISO/TS-15066 shaped stopping envelope.
* :class:`StandOffEnvelope` — the arrival / stand-off composite, expressed in
  terms of a :class:`SafetyEnvelope` rather than as a bare literal sum.

Scaling buckets
---------------

Every field carries PX4-style metadata (``unit``, ``source``, ``date``,
``bucket``) reachable from tests and docs via ``FIELD_META`` / ``field_meta``.
The bucket is the field's **scaling law** under a change of robot size. With
``L`` the characteristic length (``RobotProfile.leg_length_m``) and
``lambda = L_new / L_ref``:

``embodiment`` (``proportional to L``)
    Body geometry: footprint radius, obstacle clearance height, every
    stand-off term that wraps the body. A half-size dog gets a half-size
    footprint.

``dynamics`` (``proportional to sqrt(L)`` for speed, invariant for
acceleration)
    Dynamic similarity for legged locomotion is the **Froude number**
    ``Fr = v^2 / (g * L)`` (Alexander). Holding ``Fr`` constant gives
    ``v ~ sqrt(lambda)``, ``t ~ sqrt(lambda)``, ``omega ~ 1/sqrt(lambda)``,
    ``a = v/t ~ lambda^0`` (invariant), ``alpha = omega/t ~ 1/lambda``. This is
    the **sqrt-L law**: a half-size dog does not walk at half speed, it walks
    at ``1/sqrt(2)`` of the speed.

``latency`` (``tau`` invariant; the product ``v * tau`` scales as ``sqrt(L)``)
    Sense-to-actuate delay is a property of the compute and comms stack, not
    of the body. Shrinking the robot does not shrink the control tick. The
    *distance* travelled during that delay does shrink, as ``sqrt(L)``.

``human`` (**never scales**)
    Constants set by something other than this robot: the human personal-space
    zone, and the sensing/pose uncertainty terms that are properties of the
    sensor stack and the environment. **A half-size dog does not get half a
    personal-space zone.** Proxemic distance is set by the person, not by the
    approaching body; the quadruped-proxemics measurements the 1.2 m social
    zone comes from are reported per-person, not per-robot-size. This bucket is
    named after its dominant member; its defining property is
    ``never_scales``, and the sensor/environment terms (``Zs``, ``Zr``) live
    here for exactly that reason.

Arbitration
-----------

There are five independent speed authorities in the stack today (see
``LANE_A_STATUS.md`` for the site list); two consecutive speed raises each
missed some of them. The rule this module establishes is the **elementwise
minimum**: :meth:`RegimeLimits.elementwise_min` / :func:`arbitrate_limits`.
No authority may raise another's cap; the effective command bound is the
componentwise floor over every contributing authority. Wiring the five sites
into it is a later card — this round establishes the authority and its tests.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, replace
from typing import Any, ClassVar, Final

from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE, RobotProfile

#: Standard gravity, the ``g`` in the Froude number.
GRAVITY_MPS2: Final[float] = 9.80665

#: The four scaling buckets. Binding vocabulary — ``FieldMeta`` fails closed on
#: anything else.
SCALING_BUCKETS: Final[frozenset[str]] = frozenset(
    {"embodiment", "dynamics", "latency", "human"}
)

#: The bucket whose members never scale with robot size.
HUMAN_BUCKET: Final[str] = "human"

#: Single declared clearance convention for authority / collision / reactive_safety.
#: Distances are robot-base-center to obstacle/person surface; footprint enters
#: ``stop_distance`` exactly once and must not be added again by consumers.
CLEARANCE_CONVENTION: Final[str] = "base_center_to_obstacle_surface"

#: Human prediction horizon formerly smuggled in as the dimensionless
#: ``person_latency_factor`` (1.4) times ``reaction_latency_s`` (0.12 s) and
#: then illegally added to metres. Kept as an explicit seconds field so
#: ``closing_speed_mps * person_latency_s`` is dimensionally metres.
PERSON_LATENCY_S: Final[float] = 0.168

#: Canonical regime names, in the arbitration-documentation order.
REGIME_NAMES: Final[tuple[str, ...]] = ("cruise", "search", "approach", "recover")


@dataclass(frozen=True)
class FieldMeta:
    """PX4-style parameter metadata for one authority field."""

    unit: str
    source: str
    date: str
    bucket: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.unit.strip():
            raise ValueError("field metadata requires a unit")
        if not self.source.strip():
            raise ValueError("field metadata requires a source")
        if not self.date.strip():
            raise ValueError("field metadata requires a date")
        if self.bucket not in SCALING_BUCKETS:
            raise ValueError(
                f"unknown scaling bucket {self.bucket!r}; expected one of "
                f"{sorted(SCALING_BUCKETS)}"
            )

    @property
    def never_scales(self) -> bool:
        """True for the human/environment bucket — the HUMAN-BUCKET marker."""

        return self.bucket == HUMAN_BUCKET

    def as_dict(self) -> dict[str, str]:
        return {
            "unit": self.unit,
            "source": self.source,
            "date": self.date,
            "bucket": self.bucket,
            "note": self.note,
        }


class _MetadataMixin:
    """Shared ``FIELD_META`` accessor + completeness check."""

    FIELD_META: ClassVar[Mapping[str, FieldMeta]] = {}

    @classmethod
    def field_meta(cls, name: str) -> FieldMeta:
        """Metadata for one field; unknown names fail closed."""

        try:
            return cls.FIELD_META[name]
        except KeyError:
            raise KeyError(
                f"{cls.__name__} has no field metadata for {name!r}; "
                f"known: {sorted(cls.FIELD_META)}"
            ) from None

    @classmethod
    def metadata_covers_every_field(cls) -> bool:
        """Every dataclass field carries metadata (pinned by a test)."""

        return {item.name for item in fields(cls)} == set(cls.FIELD_META)

    @classmethod
    def fields_in_bucket(cls, bucket: str) -> tuple[str, ...]:
        if bucket not in SCALING_BUCKETS:
            raise ValueError(f"unknown scaling bucket {bucket!r}")
        return tuple(
            sorted(name for name, meta in cls.FIELD_META.items() if meta.bucket == bucket)
        )


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _non_negative(value: float, name: str) -> float:
    value = _finite(value, name)
    if value < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _positive(value: float, name: str) -> float:
    value = _finite(value, name)
    if value <= 0.0:
        raise ValueError(f"{name} must be positive")
    return value


def _reject_unknown(raw: Mapping[str, Any], allowed: Iterable[str], what: str) -> None:
    unknown = set(raw) - set(allowed)
    if unknown:
        raise ValueError(f"unsupported {what} keys: {sorted(unknown)}")


# ---------------------------------------------------------------------------
# SpeedRegime
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeLimits(_MetadataMixin):
    """One regime's velocity triple ``[vx, vy, vyaw]`` plus its accel pair."""

    vx_mps: float
    vy_mps: float
    vyaw_radps: float
    accel_mps2: float
    yaw_accel_radps2: float

    FIELD_META: ClassVar[Mapping[str, FieldMeta]] = {
        "vx_mps": FieldMeta(
            unit="m/s",
            source="configs/navigation/models/grid.yaml controller.cruise_vx and the "
            "four regime sites listed in LANE_A_STATUS.md",
            date="2026-08-07",
            bucket="dynamics",
            note="Froude: v ~ sqrt(L) at constant Fr.",
        ),
        "vy_mps": FieldMeta(
            unit="m/s",
            source="configs/navigation/default.yaml safety.max_vy",
            date="2026-08-07",
            bucket="dynamics",
        ),
        "vyaw_radps": FieldMeta(
            unit="rad/s",
            source="configs/navigation/models/grid.yaml controller.max_yaw_rate",
            date="2026-08-07",
            bucket="dynamics",
            note="Angular rate is an inverse time: omega ~ 1/sqrt(L).",
        ),
        "accel_mps2": FieldMeta(
            unit="m/s^2",
            source="configs/navigation/models/grid.yaml controller.max_linear_accel",
            date="2026-08-07",
            bucket="dynamics",
            note="Invariant under Froude scaling (a = v/t ~ lambda^0).",
        ),
        "yaw_accel_radps2": FieldMeta(
            unit="rad/s^2",
            source="configs/navigation/models/grid.yaml controller.max_yaw_accel",
            date="2026-08-07",
            bucket="dynamics",
            note="alpha ~ 1/L under Froude scaling.",
        ),
    }

    def __post_init__(self) -> None:
        _non_negative(self.vx_mps, "vx_mps")
        _non_negative(self.vy_mps, "vy_mps")
        _non_negative(self.vyaw_radps, "vyaw_radps")
        _positive(self.accel_mps2, "accel_mps2")
        _positive(self.yaw_accel_radps2, "yaw_accel_radps2")

    @property
    def velocity_triple(self) -> tuple[float, float, float]:
        """``[vx, vy, vyaw]`` — the triple the arbiter clamps against."""

        return (self.vx_mps, self.vy_mps, self.vyaw_radps)

    @property
    def accel_pair(self) -> tuple[float, float]:
        return (self.accel_mps2, self.yaw_accel_radps2)

    def elementwise_min(self, other: RegimeLimits) -> RegimeLimits:
        """The arbitration rule: componentwise floor over two authorities."""

        return RegimeLimits(
            vx_mps=min(self.vx_mps, other.vx_mps),
            vy_mps=min(self.vy_mps, other.vy_mps),
            vyaw_radps=min(self.vyaw_radps, other.vyaw_radps),
            accel_mps2=min(self.accel_mps2, other.accel_mps2),
            yaw_accel_radps2=min(self.yaw_accel_radps2, other.yaw_accel_radps2),
        )

    def scaled(
        self,
        *,
        speed_scale: float,
        time_scale: float,
    ) -> RegimeLimits:
        """Dimensionally-correct rescale by a speed ratio and a time ratio."""

        speed_scale = _positive(speed_scale, "speed_scale")
        time_scale = _positive(time_scale, "time_scale")
        return RegimeLimits(
            vx_mps=self.vx_mps * speed_scale,
            vy_mps=self.vy_mps * speed_scale,
            vyaw_radps=self.vyaw_radps / time_scale,
            accel_mps2=self.accel_mps2 * speed_scale / time_scale,
            yaw_accel_radps2=self.yaw_accel_radps2 / (time_scale * time_scale),
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RegimeLimits:
        """Build from a mapping; unknown keys fail closed (repo pattern)."""

        if not isinstance(raw, Mapping):
            raise TypeError("regime limits must be a mapping")
        allowed = {item.name for item in fields(cls)}
        _reject_unknown(raw, allowed, "regime limits")
        missing = allowed - set(raw)
        if missing:
            raise ValueError(f"missing regime limits keys: {sorted(missing)}")
        return cls(**{name: float(raw[name]) for name in allowed})

    def as_dict(self) -> dict[str, float]:
        return {item.name: float(getattr(self, item.name)) for item in fields(self)}


def arbitrate_limits(limits: Iterable[RegimeLimits]) -> RegimeLimits:
    """Elementwise minimum over every contributing speed authority.

    Fail-closed: an empty iterable raises rather than returning an unbounded
    "no limit" object, because an absent authority must never read as
    permission.
    """

    ordered = list(limits)
    if not ordered:
        raise ValueError("arbitration requires at least one contributing authority")
    result = ordered[0]
    for item in ordered[1:]:
        result = result.elementwise_min(item)
    return result


#: Reference regimes, transcribed from the live configuration on 2026-08-07.
#: Each value's source is recorded in ``SpeedRegime.REGIME_SOURCES``. These are
#: the *authority's* view of the five scattered speed sites; nothing consumes
#: them yet (wiring is a later card), so changing one here changes nothing.
_REFERENCE_CRUISE = RegimeLimits(
    vx_mps=0.85,
    vy_mps=0.25,
    vyaw_radps=0.90,
    accel_mps2=0.9,
    yaw_accel_radps2=1.8,
)
_REFERENCE_SEARCH = RegimeLimits(
    vx_mps=0.22,
    vy_mps=0.0,
    vyaw_radps=0.35,
    accel_mps2=0.9,
    yaw_accel_radps2=1.8,
)
_REFERENCE_APPROACH = RegimeLimits(
    vx_mps=0.35,
    vy_mps=0.25,
    vyaw_radps=0.75,
    accel_mps2=0.9,
    yaw_accel_radps2=1.8,
)
_REFERENCE_RECOVER = RegimeLimits(
    vx_mps=0.12,
    vy_mps=0.0,
    vyaw_radps=0.35,
    accel_mps2=0.9,
    yaw_accel_radps2=1.8,
)


@dataclass(frozen=True)
class SpeedRegime:
    """The four navigation speed regimes, as one arbitrable authority.

    ``leg_length_m`` is carried so the regime can state its own Froude number
    without importing a whole profile; :meth:`from_froude` is the constructor
    that makes a scaled robot's regimes dynamically similar to this one.
    """

    cruise: RegimeLimits = _REFERENCE_CRUISE
    search: RegimeLimits = _REFERENCE_SEARCH
    approach: RegimeLimits = _REFERENCE_APPROACH
    recover: RegimeLimits = _REFERENCE_RECOVER
    leg_length_m: float = DEFAULT_ROBOT_PROFILE.leg_length_m

    #: Where each reference regime's numbers came from. Kept beside the values
    #: so the eventual wiring card can check them off site by site.
    REGIME_SOURCES: ClassVar[Mapping[str, str]] = {
        "cruise": "configs/navigation/models/grid.yaml controller "
        "(cruise_vx / max_yaw_rate / max_linear_accel / max_yaw_accel) + "
        "configs/navigation/default.yaml safety.max_vy",
        "search": "navigation/models/__init__.py frontier crawl cap (0.22) + "
        "navigation/pipeline.py frontier probe vx (0.22) + "
        "configs/navigation/default.yaml semantic_search.yaw_rate",
        "approach": "navigation/follow.py FollowConfig.max_vx / max_vyaw + "
        "configs/navigation/default.yaml safety.max_vy",
        "recover": "configs/navigation/models/grid.yaml controller "
        "(recovery_reverse_vx magnitude / recovery_yaw_rate)",
    }

    def __post_init__(self) -> None:
        _positive(self.leg_length_m, "leg_length_m")
        for name in REGIME_NAMES:
            value = getattr(self, name)
            if not isinstance(value, RegimeLimits):
                raise TypeError(f"speed regime {name!r} must be a RegimeLimits")

    def limits(self, name: str) -> RegimeLimits:
        """Look up one regime by name; unknown names fail closed."""

        key = str(name).strip().lower()
        if key not in REGIME_NAMES:
            raise KeyError(f"unknown speed regime {name!r}; expected one of {REGIME_NAMES}")
        return getattr(self, key)

    @property
    def froude(self) -> float:
        """``Fr = v_cruise^2 / (g * L)`` — the dimensionless gait similarity number."""

        return (self.cruise.vx_mps * self.cruise.vx_mps) / (GRAVITY_MPS2 * self.leg_length_m)

    def arbitrated(self, names: Iterable[str] = REGIME_NAMES) -> RegimeLimits:
        """Elementwise min over the named regimes (documentation of the rule)."""

        return arbitrate_limits(self.limits(name) for name in names)

    @classmethod
    def from_froude(
        cls,
        profile: RobotProfile,
        froude: float,
        *,
        reference: SpeedRegime | None = None,
    ) -> SpeedRegime:
        """Regimes for ``profile`` at the requested Froude number.

        The cruise speed is set directly by ``v = sqrt(Fr * g * L)``. Every
        other quantity is carried across by the dimensional laws in the module
        docstring, so a robot half this one's size at the *same* Froude number
        gets ``1/sqrt(2)`` of the speed, the same linear acceleration, and
        ``sqrt(2)`` times the yaw rate — not half of everything.
        """

        reference = reference if reference is not None else cls()
        froude = _positive(froude, "froude")
        leg_length_m = _positive(profile.leg_length_m, "profile.leg_length_m")
        cruise_vx = math.sqrt(froude * GRAVITY_MPS2 * leg_length_m)
        speed_scale = cruise_vx / reference.cruise.vx_mps
        length_scale = leg_length_m / reference.leg_length_m
        time_scale = length_scale / speed_scale
        return cls(
            **{
                name: reference.limits(name).scaled(
                    speed_scale=speed_scale, time_scale=time_scale
                )
                for name in REGIME_NAMES
            },
            leg_length_m=leg_length_m,
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> SpeedRegime:
        """Build from a config mapping; unknown keys fail closed."""

        raw = dict(raw or {})
        allowed = {*REGIME_NAMES, "leg_length_m"}
        _reject_unknown(raw, allowed, "speed regime")
        kwargs: dict[str, Any] = {}
        for name in REGIME_NAMES:
            if name in raw:
                kwargs[name] = RegimeLimits.from_mapping(raw[name])
        if "leg_length_m" in raw:
            kwargs["leg_length_m"] = float(raw["leg_length_m"])
        return cls(**kwargs)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {name: self.limits(name).as_dict() for name in REGIME_NAMES}
        payload["leg_length_m"] = float(self.leg_length_m)
        return payload


# ---------------------------------------------------------------------------
# SafetyEnvelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyEnvelope(_MetadataMixin):
    """ISO/TS-15066 shaped stopping envelope — the one proximity authority.

    Clearance convention: :data:`CLEARANCE_CONVENTION`
    (``base_center_to_obstacle_surface``). Footprint is included exactly once
    inside ``stop_distance``; collision / reactive_safety consumers compare
    center-to-surface ranges against envelope-derived thresholds and must not
    re-add the footprint.

    ``stop_distance(v) = r_foot + v*tau + v^2/(2*a) + Zs + Zr``  [metres]

    The four terms after the footprint are, in ISO/TS-15066 vocabulary, the
    reaction distance, the braking distance, the intrusion distance of the
    sensing system (``Zs``), and the position uncertainty of the robot
    (``Zr``). ``Zr`` is 0.0 today and is the single field that widens every
    envelope in the stack the moment stratum-1 pose covariance goes live —
    Lane B sets it, no consumer changes.

    ``person_stop(v, v_close) = max(
         person_social_zone_m,
         stop_distance(v) + max(0, v_close) * person_latency_s
    )``  [metres — P0-H]

    The social zone is a floor, not a term: at Go2 scale and zero speed /
    zero closing the ISO sum is the footprint alone and the floor binds.
    """

    clearance_convention: ClassVar[str] = CLEARANCE_CONVENTION

    footprint_radius_m: float = DEFAULT_ROBOT_PROFILE.footprint_radius_m
    reaction_latency_s: float = DEFAULT_ROBOT_PROFILE.reaction_latency_s
    decel_max_mps2: float = DEFAULT_ROBOT_PROFILE.decel_max_mps2
    sensing_intrusion_m: float = 0.0
    pose_uncertainty_m: float = 0.0
    person_social_zone_m: float = 1.2
    person_latency_s: float = PERSON_LATENCY_S
    obstacle_comfort_band_m: float = 1.2
    person_comfort_band_m: float = 2.5
    obstacle_stop_floor_m: float = 0.6

    FIELD_META: ClassVar[Mapping[str, FieldMeta]] = {
        "footprint_radius_m": FieldMeta(
            unit="m",
            source="RobotProfile.footprint_radius_m (was geometry.ROBOT_FOOTPRINT_RADIUS_M)",
            date="2026-08-07",
            bucket="embodiment",
        ),
        "reaction_latency_s": FieldMeta(
            unit="s",
            source="RobotProfile.reaction_latency_s (CollisionPolicy / "
            "ReactiveSafetyPolicy reaction_time_s = 0.12)",
            date="2026-08-07",
            bucket="latency",
            note="tau itself is invariant; the distance v*tau scales as sqrt(L).",
        ),
        "decel_max_mps2": FieldMeta(
            unit="m/s^2",
            source="RobotProfile.decel_max_mps2 (configs/robot.yaml "
            "motion.smoothing.linear_decel)",
            date="2026-08-07",
            bucket="dynamics",
            note="Invariant under Froude scaling.",
        ),
        "sensing_intrusion_m": FieldMeta(
            unit="m",
            source="ISO/TS 15066 Zs; no measured value yet, pinned at 0.0",
            date="2026-08-07",
            bucket="human",
            note="Sensor-stack property, not a body property — never scales with L.",
        ),
        "pose_uncertainty_m": FieldMeta(
            unit="m",
            source="ISO/TS 15066 Zr; consumed by Lane B (stratum-1 pose covariance)",
            date="2026-08-07",
            bucket="human",
            note="0.0 while pose is sim truth. Set this and every envelope widens.",
        ),
        "person_social_zone_m": FieldMeta(
            unit="m",
            source="quadruped-proxemics study via STRATA_GENERALIZATION_PLAN.md; "
            "resolves the live 1.25-vs-1.2 drift to 1.2",
            date="2026-08-07",
            bucket="human",
            note="HUMAN BUCKET — never scales. A half-size dog does not get half "
            "a personal-space zone.",
        ),
        "person_latency_s": FieldMeta(
            unit="s",
            source="DESIGN_B P0-H / SHARED_FOUNDATION §5; replaces dimensionless "
            "person_latency_factor (1.4) that was added as seconds-to-metres",
            date="2026-08-09",
            bucket="human",
            note="Human prediction horizon. Distance term is "
            "max(0, closing_speed_mps) * person_latency_s (metres).",
        ),
        "obstacle_comfort_band_m": FieldMeta(
            unit="m",
            source="configs/robot.yaml safety.obstacle_slow_m (6 copies collapsed here)",
            date="2026-08-07",
            bucket="human",
            note="Comfort slowdown band, not a stopping term. Environment bucket.",
        ),
        "person_comfort_band_m": FieldMeta(
            unit="m",
            source="navigation/collision.py CollisionPolicy.person_slow_m",
            date="2026-08-07",
            bucket="human",
        ),
        "obstacle_stop_floor_m": FieldMeta(
            unit="m",
            source="navigation/collision.py CollisionPolicy.obstacle_stop_m",
            date="2026-08-07",
            bucket="human",
            note="Envelope floor under base_center_to_obstacle_surface. Reactive "
            "gate may keep a stricter commissioning floor (0.65) via max(); "
            "never looser. configs/navigation/default.yaml stop_distance_m=0.8 "
            "remains a separate planner term (F-stop-distance).",
        ),
    }

    def __post_init__(self) -> None:
        _non_negative(self.footprint_radius_m, "footprint_radius_m")
        _non_negative(self.reaction_latency_s, "reaction_latency_s")
        _positive(self.decel_max_mps2, "decel_max_mps2")
        _non_negative(self.sensing_intrusion_m, "sensing_intrusion_m")
        _non_negative(self.pose_uncertainty_m, "pose_uncertainty_m")
        _non_negative(self.person_social_zone_m, "person_social_zone_m")
        _non_negative(self.person_latency_s, "person_latency_s")
        _positive(self.obstacle_comfort_band_m, "obstacle_comfort_band_m")
        _positive(self.person_comfort_band_m, "person_comfort_band_m")
        _positive(self.obstacle_stop_floor_m, "obstacle_stop_floor_m")

    def stop_distance(self, speed_mps: float) -> float:
        """Center-to-surface distance needed to stop from ``speed_mps``."""

        speed = _non_negative(speed_mps, "speed_mps")
        return (
            self.footprint_radius_m
            + speed * self.reaction_latency_s
            + (speed * speed) / (2.0 * self.decel_max_mps2)
            + self.sensing_intrusion_m
            + self.pose_uncertainty_m
        )

    def person_stop(
        self,
        speed_mps: float,
        *,
        closing_speed_mps: float | None = None,
    ) -> float:
        """Person clearance (metres): social floor vs stop + closing×latency.

        ``closing_speed_mps`` defaults to ``speed_mps`` (robot speed as the
        relative-closing bound when no track closing speed is supplied).
        """

        speed = _non_negative(speed_mps, "speed_mps")
        if closing_speed_mps is None:
            closing = speed
        else:
            closing = max(0.0, _finite(closing_speed_mps, "closing_speed_mps"))
        return max(
            self.person_social_zone_m,
            self.stop_distance(speed) + closing * self.person_latency_s,
        )

    @property
    def social_zone_is_binding(self) -> bool:
        """True when the human floor, not the ISO sum, sets ``person_stop(0)``."""

        return self.person_stop(0.0) == self.person_social_zone_m

    @classmethod
    def from_profile(cls, profile: RobotProfile, **overrides: Any) -> SafetyEnvelope:
        """Envelope for one body; only the embodiment/dynamics/latency terms move."""

        base = cls(
            footprint_radius_m=profile.footprint_radius_m,
            reaction_latency_s=profile.reaction_latency_s,
            decel_max_mps2=profile.decel_max_mps2,
        )
        if not overrides:
            return base
        allowed = {item.name for item in fields(cls)}
        _reject_unknown(overrides, allowed, "safety envelope override")
        return replace(base, **overrides)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> SafetyEnvelope:
        """Build from a config mapping; unknown keys fail closed."""

        raw = dict(raw or {})
        allowed = {item.name for item in fields(cls)}
        _reject_unknown(raw, allowed, "safety envelope")
        return cls(**{name: float(value) for name, value in raw.items()})

    def as_dict(self) -> dict[str, float]:
        return {item.name: float(getattr(self, item.name)) for item in fields(self)}


#: The Go2-scale envelope every un-injected call site resolves against.
DEFAULT_SAFETY_ENVELOPE: SafetyEnvelope = SafetyEnvelope()

#: The Go2-scale speed regimes.
DEFAULT_SPEED_REGIME: SpeedRegime = SpeedRegime()

#: The person social zone, as a named import for call sites that only need the
#: HUMAN-BUCKET constant. Never scales.
PERSON_SOCIAL_ZONE_M: Final[float] = DEFAULT_SAFETY_ENVELOPE.person_social_zone_m


# ---------------------------------------------------------------------------
# StandOffEnvelope — the arrival / stand-off family, decomposed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StandOffEnvelope(_MetadataMixin):
    """Named decomposition of the near-object stand-off composite.

    Before this existed the composite was written as a bare literal sum in two
    places (``instructnav/scoring.py`` and ``navigation/approach.py``) and the
    lamppost case as the single literal ``1.32``, which embedded the 0.32
    footprint by value. Each method below reproduces its predecessor
    **bit-for-bit** at Go2 scale (same terms, same association order); the
    equality is pinned in ``tests/test_authority_family_equality.py``.
    """

    envelope: SafetyEnvelope = field(default=DEFAULT_SAFETY_ENVELOPE)
    target_surface_clearance_m: float = 0.8
    arrival_radius_m: float = 0.06
    stand_off_margin_m: float = 0.04
    vicinity_margin_m: float = 1.0
    building_vicinity_pad_m: float = 0.3
    towards_stop_short_m: float = 1.2
    near_stand_off_floor_m: float = 1.2

    FIELD_META: ClassVar[Mapping[str, FieldMeta]] = {
        "envelope": FieldMeta(
            unit="SafetyEnvelope",
            source="the stopping envelope this stand-off wraps",
            date="2026-08-07",
            bucket="embodiment",
            note="Supplies footprint_radius_m; every other term is additive here.",
        ),
        "target_surface_clearance_m": FieldMeta(
            unit="m",
            source="city_semantics target_min_surface_clearance_m = 0.8 and "
            "navigation/approach.py safe_approach_pose obstacle_stop_m default",
            date="2026-08-07",
            bucket="human",
            note="Comfort clearance to the target's own surface; environment bucket.",
        ),
        "arrival_radius_m": FieldMeta(
            unit="m",
            source="city_semantics object metadata arrival_radius_m = 0.06",
            date="2026-08-07",
            bucket="embodiment",
            note="Controller position tolerance at the terminal pose.",
        ),
        "stand_off_margin_m": FieldMeta(
            unit="m",
            source="the trailing 0.04 of the near-object composite in "
            "instructnav/scoring.py and navigation/approach.py",
            date="2026-08-07",
            bucket="embodiment",
        ),
        "vicinity_margin_m": FieldMeta(
            unit="m",
            source="instructnav/scoring.py object_near_envelope_m vicinity term",
            date="2026-08-07",
            bucket="human",
        ),
        "building_vicinity_pad_m": FieldMeta(
            unit="m",
            source="instructnav/scoring.py object_near_envelope_m building branch",
            date="2026-08-07",
            bucket="human",
        ),
        "towards_stop_short_m": FieldMeta(
            unit="m",
            source="navigation/approach.py towards_waypoint stop_short_m and "
            "instructnav/relations.py towards_waypoint default",
            date="2026-08-07",
            bucket="human",
            note="Directive semantics ('towards' means short of), not a body size.",
        ),
        "near_stand_off_floor_m": FieldMeta(
            unit="m",
            source="navigation/approach.py near-relation stand_off_m metadata default",
            date="2026-08-07",
            bucket="human",
        ),
    }

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, SafetyEnvelope):
            raise TypeError("StandOffEnvelope.envelope must be a SafetyEnvelope")
        _non_negative(self.target_surface_clearance_m, "target_surface_clearance_m")
        _non_negative(self.arrival_radius_m, "arrival_radius_m")
        _non_negative(self.stand_off_margin_m, "stand_off_margin_m")
        _non_negative(self.vicinity_margin_m, "vicinity_margin_m")
        _non_negative(self.building_vicinity_pad_m, "building_vicinity_pad_m")
        _non_negative(self.towards_stop_short_m, "towards_stop_short_m")
        _non_negative(self.near_stand_off_floor_m, "near_stand_off_floor_m")

    @property
    def footprint_radius_m(self) -> float:
        return self.envelope.footprint_radius_m

    def stand_off(self, object_radius_m: float) -> float:
        """``r_obj + r_foot + surface_clearance + arrival_radius + margin``.

        Association order is left-to-right and identical to the literal sum it
        replaced, so the double-precision result is bit-identical.
        """

        return (
            float(object_radius_m)
            + self.envelope.footprint_radius_m
            + self.target_surface_clearance_m
            + self.arrival_radius_m
            + self.stand_off_margin_m
        )

    def minimum_vicinity(self, object_radius_m: float) -> float:
        return (
            float(object_radius_m)
            + self.envelope.footprint_radius_m
            + self.target_surface_clearance_m
        )

    def vicinity(self, object_radius_m: float) -> float:
        return float(object_radius_m) + self.envelope.footprint_radius_m + self.vicinity_margin_m

    def point_anchor_stand_off(self) -> float:
        """Stand-off for a pole-like anchor treated as a zero-radius point.

        This is exactly ``vicinity(0.0)`` — footprint plus the full vicinity
        margin. At Go2 scale it evaluates to the retired ``1.32`` literal
        bit-for-bit (``0.32 + 1.0 == 1.32`` in IEEE-754 double).
        """

        return self.vicinity(0.0)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> StandOffEnvelope:
        """Build from a config mapping; unknown keys fail closed."""

        raw = dict(raw or {})
        allowed = {item.name for item in fields(cls)}
        _reject_unknown(raw, allowed, "stand-off envelope")
        kwargs: dict[str, Any] = {}
        for name, value in raw.items():
            kwargs[name] = (
                SafetyEnvelope.from_mapping(value) if name == "envelope" else float(value)
            )
        return cls(**kwargs)


#: The Go2-scale stand-off decomposition.
DEFAULT_STAND_OFF_ENVELOPE: StandOffEnvelope = StandOffEnvelope()


__all__ = [
    "DEFAULT_SAFETY_ENVELOPE",
    "DEFAULT_SPEED_REGIME",
    "DEFAULT_STAND_OFF_ENVELOPE",
    "GRAVITY_MPS2",
    "HUMAN_BUCKET",
    "PERSON_SOCIAL_ZONE_M",
    "REGIME_NAMES",
    "SCALING_BUCKETS",
    "FieldMeta",
    "RegimeLimits",
    "SafetyEnvelope",
    "SpeedRegime",
    "StandOffEnvelope",
    "arbitrate_limits",
]
