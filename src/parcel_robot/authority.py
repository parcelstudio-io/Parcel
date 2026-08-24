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

#: **The hard floor under** :attr:`SafetyEnvelope.person_social_zone_m` (card
#: P1-E, 2026-08-22). The social zone itself is a COMMISSIONING value and may
#: be moved by config — an apartment companion that keeps 1.2 m from its owner
#: cannot come when called (E2-D2: the dog stopped after 0.31 m of travel
#: because the owner stood inside the 1.2 m wedge). What may NOT move is this
#: floor: below it the system refuses to boot, by name, and that refusal is
#: part of the physical-safety core.
#:
#: Why 0.68 m and not something softer. It is the body's own ISO/TS-15066
#: stopping distance at the commissioned CRUISE speed::
#:
#:     stop_distance(0.85) = 0.32 + 0.85*0.12 + 0.85^2/(2*1.4) = 0.680036 m
#:                           ^footprint  ^v*tau   ^braking
#:
#: (``_REFERENCE_CRUISE.vx_mps`` = 0.85 m/s, the value ``SpeedRegime`` already
#: transcribes from ``configs/navigation/models/grid.yaml``.) Three properties
#: follow, and they are the reason this is the floor:
#:
#: 1. It dominates BOTH obstacle floors already in the stack —
#:    :attr:`SafetyEnvelope.obstacle_stop_floor_m` (0.60) and
#:    ``reactive_safety._REACTIVE_OBSTACLE_STOP_FLOOR_M`` (0.65) — so a person
#:    can never be commissioned less clearance than a wall.
#: 2. With the final gate's own predictive term the ISO sum is still covered at
#:    the fastest speed ``configs/robot.yaml`` permits: floor + ``max_vx*tau``
#:    = 0.68 + 1.0*0.12 = 0.80 m >= ``stop_distance(1.0)`` = 0.7971 m.
#: 3. It is a distance the body can actually produce, not a proxemics
#:    preference: every term in it is a measured Go2 quantity
#:    (``RobotProfile.footprint_radius_m`` / ``reaction_latency_s`` /
#:    ``decel_max_mps2``), which is what a real commissioning record pins.
#:
#: Written as a literal rather than as ``stop_distance(cruise)`` on purpose: a
#: floor that moves when someone retunes ``linear_decel`` is not a floor. The
#: arithmetic above is pinned by ``tests/test_p1e_social_zone_is_config.py``,
#: which reddens if the derivation and the literal ever part company.
PERSON_SOCIAL_ZONE_FLOOR_M: Final[float] = 0.68

#: **The hard floor under the commissioned OBSTACLE stop ring** (card DOOR-1,
#: 2026-08-22). Same shape as :data:`PERSON_SOCIAL_ZONE_FLOOR_M` one paragraph
#: up, and for the same reason: the ring itself is a COMMISSIONING value that
#: config may move (``safety.obstacle_stop_m``), and what may not move is the
#: floor under it.
#:
#: Why this card needed one. The shipped ring is 0.65 m, and the final gate is
#: DIRECTIONAL, so it refuses to translate down any corridor narrower than
#: ``2 * 0.65 * sin(1.15) = 1.19 m`` — a standard 0.8-0.9 m interior doorway
#: included. An indoor companion that cannot walk through a door is the thing
#: card P1-E's own status doc named as the next blocker
#: (``scrum/20260822/task_12/P1E_STATUS.md`` §7/§8). But before the ring can be
#: commissioned DOWN there has to be something it cannot be commissioned below,
#: or "indoor profile" becomes a way to switch the obstacle gate off.
#:
#: Why 0.41 m. It is the body's own ISO/TS-15066 stopping distance at the
#: APPROACH regime — the fastest regime the controller uses while it is working
#: near an obstacle::
#:
#:     stop_distance(0.35) = 0.32 + 0.35*0.12 + 0.35^2/(2*1.4) = 0.405750 m
#:                           ^footprint  ^v*tau   ^braking
#:
#: (``SpeedRegime.approach.vx_mps`` = 0.35 m/s, which the authority already
#: transcribes from ``FollowConfig.max_vx``.) Three properties, each a test:
#:
#: 1. It is strictly above the HULL, ``stop_distance(0.0)`` = 0.32 m
#:    (footprint + Zs + Zr), so no commissioning can put the stop ring inside
#:    the robot's own body.
#: 2. It stays strictly below :data:`PERSON_SOCIAL_ZONE_FLOOR_M` (0.68), which
#:    preserves P1-E's property 1 — a person can never be commissioned LESS
#:    clearance than a wall.
#: 3. It is not the number that decides doorways, and that matters. At the
#:    floor the gate would drive a 0.75 m corridor, but the grid planner models
#:    the body as a DISC (0.32 m) plus ``map_safety_margin_m`` (0.10 m) and so
#:    refuses anything under 0.84 m regardless. The binding constraint indoors
#:    is the planner's footprint model, not this floor.
#:
#: **UNCOMMISSIONED.** No robot hardware exists (owner, 2026-08-22: only the
#: reSpeaker XVF3800 mic array). ``decel_max_mps2`` and ``reaction_latency_s``
#: are config values, not instrumented ones, so this floor is simulator policy
#: derived from in-tree constants — never a physical stopping proof.
#:
#: Written as a literal for the same reason the person floor is: a floor that
#: moves when someone retunes ``linear_decel`` is not a floor.
#:
#: **Name collision, flagged so nobody reads one for the other:**
#: ``evals/nav_instruct/route_memory_cells.OBSTACLE_STOP_FLOOR_M`` is a
#: DIFFERENT quantity with the same spelling — it is
#: ``DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m`` (0.6 m), the envelope FIELD
#: used to place eval geometry, not this commissioning floor (0.41 m). Neither
#: imports the other and this card changed neither value; the collision is a
#: readability hazard, recorded rather than renamed (that file is an eval, not
#: this card's OWNS).
OBSTACLE_STOP_FLOOR_M: Final[float] = 0.41

#: Half-angle of the directional "toward" test the FINAL proximity gate uses
#: (``navigation.reactive_safety._toward``, its ``half_angle`` default). Named
#: here, in the authority, so the planner can derive the lateral clearance the
#: gate will demand without importing the gate and without copying the number
#: (card P1-E; the pin is a test that reads the gate function's own signature).
GATE_TOWARD_HALF_ANGLE_RAD: Final[float] = 1.15


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
            "a personal-space zone. COMMISSIONING VALUE as of card P1-E "
            "(2026-08-22): config (safety.person_stop_m) may move it — the "
            "prototype indoor profile sets 0.7 — but never below "
            "PERSON_SOCIAL_ZONE_FLOOR_M (0.68 m), which is a refusal to boot.",
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
        # Card P1-E: the social zone is a COMMISSIONING value and may be moved
        # by config; this floor may not. Refusal, not a clamp, and the floor is
        # named in the message so the operator reads the number they have to
        # clear. Every construction path lands here — ``from_mapping``,
        # ``from_profile``, ``replace``, ``with_person_social_zone`` — so there
        # is no way into the stack with an under-floor person clearance.
        if self.person_social_zone_m + 1e-12 < PERSON_SOCIAL_ZONE_FLOOR_M:
            raise ValueError(
                f"person_social_zone_m {self.person_social_zone_m} m is below the "
                f"commissioning floor PERSON_SOCIAL_ZONE_FLOOR_M "
                f"({PERSON_SOCIAL_ZONE_FLOOR_M} m) — the Go2's ISO/TS-15066 "
                "stopping distance at cruise. Refusing to build a safety envelope."
            )
        _non_negative(self.person_latency_s, "person_latency_s")
        _positive(self.obstacle_comfort_band_m, "obstacle_comfort_band_m")
        _positive(self.person_comfort_band_m, "person_comfort_band_m")
        _positive(self.obstacle_stop_floor_m, "obstacle_stop_floor_m")
        # Card DOOR-1: symmetric with the person floor above. ``obstacle_stop_floor_m``
        # became a COMMISSIONING value the moment ``with_obstacle_stop_ring`` gave
        # config a way to move it, so it needs the same thing the social zone got —
        # a named floor that no construction path can get under. Every path lands
        # here (``from_mapping``, ``from_profile``, ``replace``,
        # ``with_obstacle_stop_ring``), and the refusal names the constant.
        if self.obstacle_stop_floor_m + 1e-12 < OBSTACLE_STOP_FLOOR_M:
            raise ValueError(
                f"obstacle_stop_floor_m {self.obstacle_stop_floor_m} m is below the "
                f"commissioning floor OBSTACLE_STOP_FLOOR_M "
                f"({OBSTACLE_STOP_FLOOR_M} m) — the Go2's ISO/TS-15066 stopping "
                "distance at the APPROACH regime. Refusing to build a safety envelope."
            )

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

    def with_person_social_zone(self, metres: float) -> SafetyEnvelope:
        """This envelope with its social zone COMMISSIONED from config.

        Card P1-E. The one constructor the reactive gate uses to turn
        ``configs/robot*.yaml`` ``safety.person_stop_m`` into an envelope, so
        the number the gate enforces and the number the authority states are
        the same object rather than two literals that can drift (audit §6, and
        the 1.25-vs-1.2 drift this class was created to end).

        Nothing is clamped: an under-floor value raises out of
        :meth:`__post_init__` naming :data:`PERSON_SOCIAL_ZONE_FLOOR_M`, which
        is how a bad overlay becomes a refusal to boot instead of a quietly
        weakened robot.
        """

        return replace(self, person_social_zone_m=_finite(metres, "person_social_zone_m"))

    def with_obstacle_stop_ring(self, metres: float) -> SafetyEnvelope:
        """This envelope with its OBSTACLE ring COMMISSIONED from config.

        Card DOOR-1, and the exact mirror of :meth:`with_person_social_zone`.
        The one constructor the reactive gate uses to turn
        ``configs/robot*.yaml`` ``safety.obstacle_stop_m`` into an envelope, so
        the ring the gate enforces and the ring the planner inflates against
        are the same object rather than two literals that can drift (audit §6,
        "the planner and the gate disagree on the envelope").

        Nothing is clamped: an under-floor value raises out of
        :meth:`__post_init__` naming :data:`OBSTACLE_STOP_FLOOR_M`, which is how
        an over-eager indoor profile becomes a refusal to boot instead of a
        quietly switched-off obstacle gate.
        """

        return replace(self, obstacle_stop_floor_m=_finite(metres, "obstacle_stop_floor_m"))

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


def gate_lateral_clearance_m(
    stop_ring_m: float,
    *,
    half_angle_rad: float = GATE_TOWARD_HALF_ANGLE_RAD,
) -> float:
    """LATERAL clearance a planner must inflate by to agree with a stop ring.

    Card P1-E, audit §6 ("the planner and the gate disagree on the envelope").
    The final gate is DIRECTIONAL: it stops translation only for obstacles
    inside a ``+/- half_angle`` cone about the travel direction. So a wall the
    robot passes broadside never trips it, while the same wall ahead does. For
    a straight corridor of half-width ``h`` travelled along its centreline the
    nearest obstacle INSIDE the cone is at ``h / sin(half_angle)``, so the gate
    refuses to translate whenever::

        h / sin(half_angle) <= stop_ring   <=>   h <= stop_ring * sin(half_angle)

    which makes ``stop_ring * sin(half_angle)`` exactly the inflation radius a
    grid planner needs for "the planner does not choose corridors the gate
    refuses". At the shipped obstacle ring (0.65 m) that is 0.5933 m — i.e. the
    gate already refuses every corridor narrower than 1.19 m, while the legacy
    footprint-only inflation (0.32 + 0.10 = 0.42 m) plans through anything
    wider than 0.84 m. That gap is the disagreement, in metres.

    One number, two consumers: pass the SAME quantity the gate enforces —
    ``ReactiveSafetyPolicy.obstacle_stop_m`` for a lidar occupancy map,
    ``person_stop_m`` for a map whose cells are people.
    """

    ring = _non_negative(stop_ring_m, "stop_ring_m")
    angle = _finite(half_angle_rad, "half_angle_rad")
    if not 0.0 < angle <= math.pi:
        raise ValueError("half_angle_rad must be in (0, pi]")
    return ring * math.sin(min(angle, math.pi / 2.0))


#: The planner's legacy HARD margin: ``GridPlannerConfig.safety_margin_m`` and
#: ``configs/navigation/models/grid.yaml`` ``map_safety_margin_m``, which have
#: both been 0.10 m since the grid planner shipped. Named here so
#: :class:`ClearanceProfile` can state the planner's inflation without importing
#: the planner; the planner still owns the value and a profile that moves it
#: passes its own.
PLANNER_HARD_MARGIN_M: Final[float] = 0.10

#: The largest obstacle ring whose lateral clearance the LEGACY footprint
#: inflation already covers: ``(footprint + hard_margin) / sin(half_angle)``.
#:
#: This is a COMPATIBILITY constant, not a commissioning claim, and the
#: distinction is the whole reason it is spelled out here. Coupling the planner
#: to a ring at or below it changes no planned route anywhere, because
#: ``inflation_radius_m`` takes a ``max`` and the footprint term still wins;
#: coupling it to a ring ABOVE it tightens the planner and moves every frozen
#: navigation baseline at once (at the shipped 0.65 m ring the narrowest
#: routable corridor goes 0.84 m -> 1.19 m continuous, and 1.00 m -> 1.20 m on
#: the product's 0.10 m grid). Card DOOR-1 uses it as the default for
#: un-commissioned callers precisely so that wiring the coupling is not also,
#: silently, a re-freeze of the navigation evidence.
#:
#: **This constant is the cap for the DEFAULT 0.10 m hard margin only.** Card
#: DOOR-1's correction pass: the margin is per-profile
#: (``configs/navigation/models/grid_clearance.yaml`` runs 0.03 m, so its own
#: legacy-equivalent ring is 0.383 m), and capping that profile at this flat
#: constant would have moved its inflation 0.35 -> 0.42 m. Call sites must use
#: :attr:`ClearanceProfile.legacy_equivalent_ring_m` /
#: :attr:`ClearanceProfile.planner_coupling_ring_m`, which compute it from the
#: profile in hand. This constant remains the value for the default margin and
#: is what ``DEFAULT_CLEARANCE_PROFILE`` carries.
LEGACY_GATE_CLEARANCE_M: Final[float] = (
    DEFAULT_ROBOT_PROFILE.footprint_radius_m + PLANNER_HARD_MARGIN_M
) / math.sin(GATE_TOWARD_HALF_ANGLE_RAD)


@dataclass(frozen=True)
class ClearanceProfile:
    """ONE immutable commissioned obstacle envelope; planner and gate both derive.

    Card DOOR-1 / design DW-4. Audit §6's finding was that the planner and the
    final gate hold two independent opinions about how much room the body needs:
    the planner inflates obstacles by ``footprint + margin`` (0.42 m) while the
    gate refuses to translate toward anything inside a ring (0.65 m) that, run
    through the gate's own directional cone, is a 0.593 m lateral demand. Two
    numbers, no relationship, and the planner was the LOOSER of the two — it
    routed through corridors the gate would then stand in and refuse.

    This type is the fix's shape: the commissioned ring is stated ONCE, and
    both consumers are derived from it.

    * :attr:`planner_inflation_m` — what the planner must inflate by. It is a
      ``max`` against the footprint term, so it can only ever be TIGHTER than
      the legacy planner, never looser.
    * :meth:`final_gate_ring_m` — what the final gate will enforce, recomputed
      from this profile ALONE. It takes no planner input by construction: the
      point of an independent recomputation is that a mistake in the planner
      cannot propagate into the thing that stops the robot.

    Both are monotone non-decreasing in :attr:`obstacle_ring_m`, which is the
    property that makes "commissioning a smaller ring can only relax the
    planner, never the gate's relationship to it" checkable rather than
    asserted.

    **UNCOMMISSIONED.** No robot hardware exists (owner, 2026-08-22). Every
    number this type produces is arithmetic over in-tree body constants and is
    simulator policy, not a measured physical clearance.
    """

    #: The commissioned obstacle stop ring, base-centre to obstacle surface.
    #: This is ``configs/robot*.yaml`` ``safety.obstacle_stop_m`` wearing the
    #: authority's type; it is also exactly ``ReactiveSafetyPolicy.obstacle_stop_m``.
    obstacle_ring_m: float = LEGACY_GATE_CLEARANCE_M
    #: The body the ring belongs to. Injectable so a scaled robot brings its own
    #: footprint / latency / braking terms.
    envelope: SafetyEnvelope = DEFAULT_SAFETY_ENVELOPE
    #: The planner's own hard margin (``GridPlannerConfig.effective_hard_margin_m``).
    planner_hard_margin_m: float = PLANNER_HARD_MARGIN_M
    #: The final gate's directional cone half-angle.
    gate_half_angle_rad: float = GATE_TOWARD_HALF_ANGLE_RAD

    def __post_init__(self) -> None:
        _positive(self.obstacle_ring_m, "obstacle_ring_m")
        _non_negative(self.planner_hard_margin_m, "planner_hard_margin_m")
        if not isinstance(self.envelope, SafetyEnvelope):
            raise TypeError("ClearanceProfile.envelope must be a SafetyEnvelope")
        if not 0.0 < _finite(self.gate_half_angle_rad, "gate_half_angle_rad") <= math.pi:
            raise ValueError("gate_half_angle_rad must be in (0, pi]")
        # The hull check, not the commissioning floor. ``OBSTACLE_STOP_FLOOR_M``
        # is enforced where the ring is COMMISSIONED (``with_obstacle_stop_ring``
        # -> ``SafetyEnvelope.__post_init__``); what this type refuses is the
        # physically meaningless case of a ring inside the robot's own body,
        # which is reachable for an injected wider envelope even when the
        # Go2-scale floor is not.
        hull = self.envelope.stop_distance(0.0)
        if self.obstacle_ring_m + 1e-12 < hull:
            raise ValueError(
                f"obstacle_ring_m {self.obstacle_ring_m} m is inside the body hull "
                f"stop_distance(0.0) = {hull} m — refusing to build a clearance profile."
            )

    @property
    def gate_lateral_clearance_m(self) -> float:
        """Lateral radius this ring implies through the gate's directional cone."""

        return gate_lateral_clearance_m(
            self.obstacle_ring_m, half_angle_rad=self.gate_half_angle_rad
        )

    @property
    def legacy_footprint_term_m(self) -> float:
        """The inflation this profile's planner used BEFORE any coupling."""

        return self.envelope.footprint_radius_m + self.planner_hard_margin_m

    @property
    def legacy_equivalent_ring_m(self) -> float:
        """The largest ring whose lateral demand THIS profile already covers.

        ``LEGACY_GATE_CLEARANCE_M`` is this quantity for the DEFAULT 0.10 m hard
        margin. It is a property here because the margin is per-profile:
        ``configs/navigation/models/grid_clearance.yaml`` runs a 0.03 m hard
        margin, so its legacy term is 0.35 m and its legacy-equivalent ring is
        0.383 m, not 0.460 m. Card DOOR-1's correction pass — the flat
        module-level constant was the wrong cap for that profile and would have
        moved its inflation 0.35 -> 0.42 m.
        """

        return self.legacy_footprint_term_m / math.sin(
            min(self.gate_half_angle_rad, math.pi / 2.0)
        )

    @property
    def planner_coupling_ring_m(self) -> float:
        """The ring a planner may couple to WITHOUT moving a frozen route.

        **Card DOOR-1 correction pass, and the whole scope of the coupling as
        shipped.** The coupling is TIGHTER-ONLY: it is allowed to make a planner
        agree with a gate that demands LESS room than the planner already
        leaves, and it is NOT allowed to raise any inflation, because raising an
        inflation moves planned routes and therefore the frozen navigation
        evidence (BARN bundles, nav_instruct minival, FOLLOW_BENCH_V1). That
        re-cut is a deliberate, owner-and-verifier-gated decision, not a side
        effect of wiring a seam.

        So the ring handed to ``GridPlannerConfig.gate_clearance_m`` is the
        commissioned ring capped at :attr:`legacy_equivalent_ring_m`. Read the
        consequence plainly: **for any profile whose gate demands MORE than its
        planner already leaves, the coupling is inert and the planner and the
        gate still disagree.** :attr:`planner_coupling_is_deferred` says which
        case a profile is in, and it is True on the shipped ``configs/robot.yaml``
        (0.65 m ring) and False on ``configs/robot.prototype.yaml`` (0.45 m).
        """

        return min(self.obstacle_ring_m, self.legacy_equivalent_ring_m)

    @property
    def planner_coupling_is_deferred(self) -> bool:
        """True when the cap binds — i.e. the planner/gate disagreement stands.

        Not a failure and not a silent one: it is the honest state of every
        un-commissioned profile in the tree, it is asserted by
        ``tests/test_door1_doorway.py``, and closing it is the HALTED item H-2
        in ``scrum/20260822/task_19/DOOR1_STATUS.md``.
        """

        return self.planner_coupling_ring_m + 1e-12 < self.obstacle_ring_m

    @property
    def planner_inflation_m(self) -> float:
        """Hard inflation radius the planner uses under the SCOPED coupling.

        ``max(legacy footprint term, lateral demand of the COUPLING ring)``.
        Because the coupling ring is capped at the legacy-equivalent ring, this
        is identically the legacy term for every profile in the tree today —
        which is the point: wiring the seam moved no route. It stops being the
        legacy term the moment H-2 is closed and the cap is lifted.
        """

        return max(
            self.legacy_footprint_term_m,
            gate_lateral_clearance_m(
                self.planner_coupling_ring_m, half_angle_rad=self.gate_half_angle_rad
            ),
        )

    @property
    def uncapped_planner_inflation_m(self) -> float:
        """What the planner WOULD inflate by with the cap lifted (H-2's cost)."""

        return max(self.legacy_footprint_term_m, self.gate_lateral_clearance_m)

    @property
    def gate_range_ring_m(self) -> float:
        """The stop ring in the frame an occupancy grid inflates in.

        Card A2 (NAV-GLUE), and the correction that makes "one number, two
        consumers" true rather than nearly true. :attr:`obstacle_ring_m` is
        compared by the gate against ``SimObservation.nearest_obstacle_m`` /
        ``LidarObstacle.distance_m``, and those fields are **body-surface** to
        obstacle-surface: ``simulation/mujoco_lidar.py`` subtracts the footprint
        (``signed_clearance = signed_center_distance - robot_radius_m``) before
        the gate ever sees a number, and the Go2 range bridge carries the same
        convention. A planner, by contrast, inflates occupied cells around the
        body **centre** — ``legacy_footprint_term_m`` is ``footprint + margin``,
        centre-to-surface — so handing it :attr:`obstacle_ring_m` compares two
        different measurements and understates the gate's demand by exactly one
        footprint radius.

        NAV-CORE measured that understatement as a stall class: with the planner
        at 0.42 m the reactive gate parked 31/60 arm-B episodes at ~0.74 m of
        body-surface clearance with the route still ``status=planned``, and a
        0.45 m hard margin (0.77 m inflation, still short of the 0.885 m this
        property implies at the shipped ring) recovered 1 of 8 sampled stalls.

        This is a RESTATEMENT of the commissioned ring, not a new commissioning
        number and not a floor: nothing here can move what
        ``apply_reactive_safety`` enforces.
        """

        return self.obstacle_ring_m + self.envelope.footprint_radius_m

    @property
    def commissioned_planner_inflation_m(self) -> float:
        """Inflation that makes a planner agree with this gate, cap lifted.

        ``max(legacy footprint term, lateral demand of``
        :attr:`gate_range_ring_m` ``)`` — the uncapped, unit-corrected sibling
        of :attr:`planner_inflation_m`. This is what the two PRODUCTION planner
        construction sites are built from once DOOR-1's item H-2 is closed
        (card A2); :attr:`planner_inflation_m` remains what an un-commissioned
        call site gets, and stays exactly the legacy term.
        """

        return max(
            self.legacy_footprint_term_m,
            gate_lateral_clearance_m(
                self.gate_range_ring_m, half_angle_rad=self.gate_half_angle_rad
            ),
        )

    def final_gate_ring_m(self, speed_mps: float = 0.0) -> float:
        """What the FINAL gate stops at, recomputed from this profile alone.

        ``apply_reactive_safety`` stops translation when a directional obstacle
        is inside ``obstacle_stop_m + |v| * reaction_time_s``. This restates
        that arithmetic from the profile — deliberately WITHOUT consulting the
        planner, the planner's config, or any inflated radius — so the two can
        be compared rather than assumed equal.
        """

        speed = max(0.0, _finite(speed_mps, "speed_mps"))
        return self.obstacle_ring_m + speed * self.envelope.reaction_latency_s

    def narrowest_gate_passable_corridor_m(self, speed_mps: float = 0.0) -> float:
        """Narrowest straight corridor the FINAL gate will drive down, metres."""

        return 2.0 * gate_lateral_clearance_m(
            self.final_gate_ring_m(speed_mps), half_angle_rad=self.gate_half_angle_rad
        )

    def narrowest_planner_routable_corridor_m(self) -> float:
        """Narrowest straight corridor the PLANNER will route through, metres."""

        return 2.0 * self.planner_inflation_m

    def planner_agrees_with_gate(self, planner_inflation_m: float) -> bool:
        """True when a planner at this inflation never routes where the gate refuses.

        The comparison is one-directional on purpose. A planner INSIDE the
        gate's lateral demand proposes corridors the gate will stand in and
        refuse; a planner outside it is merely conservative, which is the safe
        direction and is what the shipped footprint term already does.
        """

        return (
            _non_negative(planner_inflation_m, "planner_inflation_m") + 1e-12
            >= self.gate_lateral_clearance_m
        )

    def with_ring(self, metres: float) -> ClearanceProfile:
        """This profile at a different commissioned ring (still immutable)."""

        return replace(self, obstacle_ring_m=_finite(metres, "obstacle_ring_m"))

    def as_dict(self) -> dict[str, float | bool]:
        return {
            "obstacle_ring_m": float(self.obstacle_ring_m),
            "planner_hard_margin_m": float(self.planner_hard_margin_m),
            "gate_half_angle_rad": float(self.gate_half_angle_rad),
            "gate_lateral_clearance_m": float(self.gate_lateral_clearance_m),
            "legacy_equivalent_ring_m": float(self.legacy_equivalent_ring_m),
            "planner_coupling_ring_m": float(self.planner_coupling_ring_m),
            "planner_coupling_is_deferred": bool(self.planner_coupling_is_deferred),
            "planner_inflation_m": float(self.planner_inflation_m),
            "uncapped_planner_inflation_m": float(self.uncapped_planner_inflation_m),
            "gate_range_ring_m": float(self.gate_range_ring_m),
            "commissioned_planner_inflation_m": float(self.commissioned_planner_inflation_m),
            "final_gate_ring_m": float(self.final_gate_ring_m(0.0)),
        }


#: The profile an un-commissioned planner call site resolves against. Its ring
#: is :data:`LEGACY_GATE_CLEARANCE_M`, so its ``planner_inflation_m`` is exactly
#: the legacy 0.42 m and wiring the coupling changes no shipped route. A
#: commissioned runtime passes its OWN ring (``ReactiveSafetyPolicy.clearance_profile``).
DEFAULT_CLEARANCE_PROFILE: ClearanceProfile = ClearanceProfile()


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
    "DEFAULT_CLEARANCE_PROFILE",
    "DEFAULT_SAFETY_ENVELOPE",
    "DEFAULT_SPEED_REGIME",
    "DEFAULT_STAND_OFF_ENVELOPE",
    "GATE_TOWARD_HALF_ANGLE_RAD",
    "GRAVITY_MPS2",
    "HUMAN_BUCKET",
    "LEGACY_GATE_CLEARANCE_M",
    "OBSTACLE_STOP_FLOOR_M",
    "PERSON_SOCIAL_ZONE_FLOOR_M",
    "PERSON_SOCIAL_ZONE_M",
    "PLANNER_HARD_MARGIN_M",
    "REGIME_NAMES",
    "SCALING_BUCKETS",
    "ClearanceProfile",
    "FieldMeta",
    "RegimeLimits",
    "SafetyEnvelope",
    "SpeedRegime",
    "StandOffEnvelope",
    "arbitrate_limits",
    "gate_lateral_clearance_m",
]
