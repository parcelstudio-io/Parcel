# ---- CARD PROX-1 (scrum/20260823/task_2) --------------------------------
"""Preregistered person-proximity profiles, selected by a typed CONTEXT.

Owner direction, 2026-08-23: the person collision distance should be generally
shorter, and shorter still when the robot knows it is indoors or in close
quarters; a reasoning model decides the context later — **start simple**.

The shape this module gives that direction, and the two rules it exists to
make unbreakable:

**Rule 2 — the model may never mint a raw distance.** Everything reachable
from a tool call is an *enum*. :func:`ProximityContext.parse` refuses a float,
an int and a bool by type, so ``set_proximity_context(0.4)`` is a ``TypeError``
naming the rule rather than a robot that now stops 0.4 m from a person. A
context switch can only ever select one of the preregistered pairs; it cannot
invent a fourth.

**Where the preregistration lives, and why it is here today.** The card put the
table in base ``configs/robot.yaml``. That file is SHA-locked by
``evals/companion/embodied_plan_v1/manifest.json``, whose own digest is pinned
in ``scripts/ci_gate.py`` DIGEST_SENTINELS under a re-pin protocol requiring
owner authorisation and re-measured eval rows — so this card cannot move it.
:data:`PREREGISTERED_PROXIMITY_PROFILES` is therefore the shipped ladder, and
:func:`load_proximity_profiles` already reads ``safety.proximity_profiles``
when a config supplies it. The exact block, proven loadable and floor-clearing,
is ``PROPOSED_SAFETY_BLOCK`` in ``tests/test_prox1_proximity_profiles.py``;
landing it after the authorised re-pin needs no code change here.

**The floor stays the authority's.** Nothing here re-implements, restates or
softens the P1-E physics/proxemics floor. A profile is validated by BEING
APPLIED — :meth:`ProximityProfile.apply_to` is a ``dataclasses.replace`` onto
:class:`~parcel_robot.navigation.reactive_safety.ReactiveSafetyPolicy`, whose
existing ``__post_init__`` runs the whole unchanged chain:
``SafetyEnvelope.with_person_social_zone`` (which raises naming
:data:`~parcel_robot.authority.PERSON_SOCIAL_ZONE_FLOOR_M`), the physics floor
under an injected body, ``stop < slow``, and the owner-band separation. So an
under-floor "indoor" profile is a refusal to build, in the authority's own
words, exactly as an under-floor ``safety.person_stop_m`` already is.

Validation happens when the TABLE is built, not when the context switches: a
mistyped preregistration refuses at boot rather than at the moment the dog
walks into a doorway.

**What this module does NOT do.** It does not read a venue file, hold a lock,
touch the 10 Hz tick, or wire itself into ``RobotRuntime`` — that wire-in is
handed to AWARE-1 (see ``scrum/20260823/task_2/PROX1_STATUS.md``). Today it is
a pure selector plus a small owner object a caller can hold.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy

__all__ = [
    "PREREGISTERED_PROXIMITY_PROFILES",
    "PROXIMITY_PROFILES_CONFIG_KEY",
    "VENUE_PROXIMITY_CONTEXT",
    "ProximityContext",
    "ProximityContextOwner",
    "ProximityProfile",
    "load_proximity_profiles",
    "proximity_context_for_venue",
    "resolve_proximity_profile",
]

#: The ``safety:`` sub-key the preregistered table is read from. BASE
#: ``configs/robot.yaml``, deliberately: a base addition needs no
#: overlay-admission change, so no venue overlay can mint a profile table the
#: admission list never saw.
PROXIMITY_PROFILES_CONFIG_KEY: Final[str] = "proximity_profiles"


class ProximityContext(Enum):
    """What kind of space the robot believes it is in. THE ONLY tool input.

    Three values and no more. A reasoning model PROPOSES one of these; the
    distances it selects were preregistered by an operator. Adding a fourth is
    a config + code change under review, which is the point.
    """

    #: Outdoors / open room. The shipped commissioning, unchanged.
    DEFAULT = "default"
    #: Inside a home: furniture, a person on a sofa, a kitchen counter.
    INDOOR = "indoor"
    #: Close quarters — a doorway, a hallway, standing beside a chair.
    NARROW = "narrow"

    @classmethod
    def parse(cls, value: Any) -> ProximityContext:
        """Coerce ``value`` to a context, refusing anything number-shaped.

        This is where architecture rule 2 is enforced. ``bool`` is checked
        before ``int`` because ``bool`` IS an ``int`` in Python, and
        ``ProximityContext.parse(True)`` must not become a lookup on ``1``.
        """

        if isinstance(value, cls):
            return value
        if isinstance(value, (bool, int, float)):
            raise TypeError(
                "proximity context must be a ProximityContext or one of "
                f"{sorted(item.value for item in cls)!r}, not the number "
                f"{value!r} — a reasoning model PROPOSES a preregistered "
                "context and may never mint a raw distance."
            )
        if not isinstance(value, str):
            raise TypeError(
                "proximity context must be a ProximityContext or one of "
                f"{sorted(item.value for item in cls)!r} (got {type(value).__name__})"
            )
        name = value.strip().lower()
        for item in cls:
            if item.value == name:
                return item
        raise ValueError(
            f"unknown proximity context {value!r}; preregistered contexts are "
            f"{sorted(item.value for item in cls)!r}"
        )


@dataclass(frozen=True)
class ProximityProfile:
    """One preregistered ``(person_stop_m, person_slow_m)`` pair."""

    person_stop_m: float
    person_slow_m: float

    def apply_to(self, policy: ReactiveSafetyPolicy) -> ReactiveSafetyPolicy:
        """``policy`` with THIS pair commissioned, through the existing validator.

        A ``dataclasses.replace`` and nothing else: every refusal a caller can
        see out of here — the social-zone floor, the physics floor under an
        injected body, ``stop < slow``, the owner-band separation — is raised
        by ``ReactiveSafetyPolicy.__post_init__``, untouched by this card.
        """

        return replace(
            policy,
            person_stop_m=float(self.person_stop_m),
            person_slow_m=float(self.person_slow_m),
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, where: str) -> ProximityProfile:
        """Build from a config mapping; unknown and missing keys fail closed."""

        allowed = {"person_stop_m", "person_slow_m"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"{where}: unknown proximity profile keys {unknown}")
        missing = sorted(allowed - set(raw))
        if missing:
            raise ValueError(f"{where}: proximity profile is missing {missing}")
        return cls(
            person_stop_m=float(raw["person_stop_m"]),
            person_slow_m=float(raw["person_slow_m"]),
        )


# THE PREREGISTERED LADDER, and where each number comes from. Written as
# literals with the derivation beside them, in the house style P1-E set for
# ``PERSON_SOCIAL_ZONE_FLOOR_M`` — a commissioning value that silently moves
# when someone retunes a term is not a preregistration. The arithmetic below
# is pinned by ``tests/test_prox1_proximity_profiles.py``, which reddens if a
# literal and its derivation ever part company.
#
#   NARROW stop = PERSON_SOCIAL_ZONE_FLOOR_M (0.68 m — the Go2's ISO/TS-15066
#     stopping distance at cruise) rounded UP to the nearest 0.05 m = 0.70 m.
#     The tightest pair the EXISTING validator will admit at Go2 scale. The
#     0.02 m of headroom is deliberate: it is derivation margin, so a future
#     retune that nudges the floor by a rounding cannot land this profile
#     under it and take the whole robot down with it.
#   INDOOR stop = the midpoint of narrow and default, to the nearest 0.05 m:
#     (0.70 + 1.20) / 2 = 0.95 m.
#   DEFAULT stop = the shipped social zone, taken from the authority rather
#     than restated, so this table cannot drift from ``robot.yaml``.
#
#   Every SLOW band keeps the shipped default's band-to-stop ratio (2.5 over
#     1.2, about 2.083), rounded UP to the nearest 0.05 m so a tighter profile
#     is never handed a tighter comfort ramp than that ratio implies:
#     narrow 0.70 -> 1.4583 -> 1.50; indoor 0.95 -> 1.9792 -> 2.00.
_NARROW_PROFILE: Final[ProximityProfile] = ProximityProfile(
    person_stop_m=0.70, person_slow_m=1.50
)
_INDOOR_PROFILE: Final[ProximityProfile] = ProximityProfile(
    person_stop_m=0.95, person_slow_m=2.00
)
_DEFAULT_PROFILE: Final[ProximityProfile] = ProximityProfile(
    person_stop_m=DEFAULT_SAFETY_ENVELOPE.person_stop(0.0),
    person_slow_m=DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m,
)

#: The Go2-scale ladder every un-injected call site resolves against.
PREREGISTERED_PROXIMITY_PROFILES: Mapping[ProximityContext, ProximityProfile] = (
    MappingProxyType(
        {
            ProximityContext.DEFAULT: _DEFAULT_PROFILE,
            ProximityContext.INDOOR: _INDOOR_PROFILE,
            ProximityContext.NARROW: _NARROW_PROFILE,
        }
    )
)

#: Source of truth for the context TODAY: the commissioned venue.
#: ``go2_edu_plus`` is the owner's indoor education rig.
#:
#: A venue this map has never heard of resolves to ``DEFAULT`` — the WIDEST
#: clearance, not the tightest. The fail direction of an unknown space is more
#: room around a person, never less.
VENUE_PROXIMITY_CONTEXT: Mapping[str, ProximityContext] = MappingProxyType(
    {"go2_edu_plus": ProximityContext.INDOOR}
)


def proximity_context_for_venue(venue: str | None) -> ProximityContext:
    """The context a commissioned venue implies; unknown venues get DEFAULT."""

    if not venue:
        return ProximityContext.DEFAULT
    return VENUE_PROXIMITY_CONTEXT.get(str(venue).strip().lower(), ProximityContext.DEFAULT)


def resolve_proximity_profile(
    context: Any,
    profiles: Mapping[ProximityContext, ProximityProfile] | None = None,
) -> ProximityProfile:
    """THE PURE SELECTOR: a context in, a preregistered pair out.

    No I/O, no clock, no state. ``profiles`` defaults to the shipped ladder so
    a caller that has not loaded config still gets a preregistered answer
    rather than a ``None``.
    """

    requested = ProximityContext.parse(context)
    table = PREREGISTERED_PROXIMITY_PROFILES if profiles is None else profiles
    try:
        return table[requested]
    except KeyError:
        raise ValueError(
            f"no proximity profile preregistered for context {requested.value!r}"
        ) from None


def load_proximity_profiles(
    raw_safety_config: Mapping[str, Any] | None,
    *,
    base_policy: ReactiveSafetyPolicy | None = None,
) -> dict[ProximityContext, ProximityProfile]:
    """Read ``safety.proximity_profiles`` and validate EVERY pair at boot.

    ``base_policy`` is the gate this deployment already commissions. Two
    things follow, and both are deliberate:

    * With no ``proximity_profiles`` key at all, ``DEFAULT`` is the base
      policy's OWN pair — not a constant — so a deployment that commissioned
      ``safety.person_stop_m`` itself keeps exactly the distance it configured.
      That is what makes the no-new-keys baseline byte-identical for every
      config, not only for the shipped one.
    * Every profile is validated by being applied to that same policy, so a
      preregistration that undercuts the floor is a refusal HERE, at boot, and
      not a surprise at the moment a context switch fires.
    """

    policy = ReactiveSafetyPolicy() if base_policy is None else base_policy
    profiles: dict[ProximityContext, ProximityProfile] = {
        ProximityContext.DEFAULT: ProximityProfile(
            person_stop_m=policy.person_stop_m, person_slow_m=policy.person_slow_m
        ),
        ProximityContext.INDOOR: _INDOOR_PROFILE,
        ProximityContext.NARROW: _NARROW_PROFILE,
    }
    raw = dict(raw_safety_config or {}).get(PROXIMITY_PROFILES_CONFIG_KEY, {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise TypeError(f"safety.{PROXIMITY_PROFILES_CONFIG_KEY} must be a mapping")
    for name, body in raw.items():
        where = f"safety.{PROXIMITY_PROFILES_CONFIG_KEY}.{name}"
        context = ProximityContext.parse(name)
        if not isinstance(body, Mapping):
            raise TypeError(f"{where} must be a mapping")
        profiles[context] = ProximityProfile.from_mapping(body, where=where)
    for context, profile in profiles.items():
        try:
            profile.apply_to(policy)
        except ValueError as error:
            raise ValueError(
                f"safety.{PROXIMITY_PROFILES_CONFIG_KEY}.{context.value} is not "
                f"commissionable: {error}"
            ) from error
    return profiles


class ProximityContextOwner:
    """Holds the ACTIVE proximity context and the policy that context commissions.

    The seam a reasoning-model tool calls, and the object a runtime holds. Two
    properties a caller on the control tick depends on:

    * :attr:`policy` is one attribute read of an immutable frozen dataclass,
      so a tick thread reading it while a tool thread switches context sees
      either the old policy or the new one — never a half-applied pair. There
      is no lock here on purpose: a rebind of a single attribute is atomic
      under the GIL, and this object must never be able to block the 10 Hz
      path.
    * every policy this object ever hands out came out of the existing
      ``ReactiveSafetyPolicy`` validator, so there is no path through it to an
      under-floor distance.
    """

    def __init__(
        self,
        base_policy: ReactiveSafetyPolicy | None = None,
        profiles: Mapping[ProximityContext, ProximityProfile] | None = None,
        context: Any = ProximityContext.DEFAULT,
    ) -> None:
        self._base_policy = ReactiveSafetyPolicy() if base_policy is None else base_policy
        table = (
            load_proximity_profiles(None, base_policy=self._base_policy)
            if profiles is None
            else dict(profiles)
        )
        for name, profile in table.items():
            try:
                profile.apply_to(self._base_policy)
            except ValueError as error:
                raise ValueError(
                    f"proximity profile {name.value!r} is not commissionable: {error}"
                ) from error
        self._profiles: Mapping[ProximityContext, ProximityProfile] = MappingProxyType(table)
        self._context = ProximityContext.DEFAULT
        self._policy = self._base_policy
        self.set_proximity_context(context)

    @property
    def base_policy(self) -> ReactiveSafetyPolicy:
        """The commissioned gate every profile is applied ON TOP OF."""

        return self._base_policy

    @property
    def profiles(self) -> Mapping[ProximityContext, ProximityProfile]:
        """The preregistered table, read-only."""

        return self._profiles

    @property
    def context(self) -> ProximityContext:
        """The context currently in force."""

        return self._context

    @property
    def policy(self) -> ReactiveSafetyPolicy:
        """The ACTIVE gate. Single atomic read; safe from the control tick."""

        return self._policy

    def set_proximity_context(
        self, context: Any, *, source: str = "config"
    ) -> ReactiveSafetyPolicy:
        """PROPOSE a context switch; returns the policy now in force.

        ``context`` is a :class:`ProximityContext` or its exact name. A number
        is a ``TypeError`` — see :meth:`ProximityContext.parse`. ``source`` is
        provenance for the caller's own logging and changes nothing here.
        """

        requested = ProximityContext.parse(context)
        profile = resolve_proximity_profile(requested, self._profiles)
        # The existing validator, one more time, at the moment of the switch:
        # a table built against one envelope may not be silently applied to a
        # policy it was never checked against.
        policy = profile.apply_to(self._base_policy)
        self._policy = policy
        self._context = requested
        self._last_source = str(source)
        return policy

    @property
    def last_source(self) -> str:
        """Who asked for the context in force (provenance only, never authority)."""

        return getattr(self, "_last_source", "config")


# ---- END CARD PROX-1 ----------------------------------------------------
