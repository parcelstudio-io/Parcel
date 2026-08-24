"""The final safety governor, co-located with the gateway (FABLE_VERDICT X12).

HLD §8.8 gives the disposition lattice::

    PASS < CLAMP < HOLD < STOP < LATCHED_STOP

and the composition rule: intersect the motion constraints, and *separately*
select the most restrictive lifecycle precedence — a zero-valued ``CLAMP`` is
not lifecycle-equivalent to ``HOLD`` or ``STOP``.

X12 gives the authority split for the prototype: one clamp owner (this
governor), and a writer module that is **veto-only** — it may reject or zero,
never originate or increase.  That sentence is not a comment here; it is
:meth:`FinalGovernorV1.evaluate`'s last act.  Whatever the clamp arithmetic
above it does, ``_veto_only`` re-reads the candidate and the output and, if any
axis came out larger in magnitude or with a flipped sign, throws the result
away, emits exact zero and returns ``STOP`` with the cause
``governor_would_increase_motion``.  A future shaper bug therefore stops the
robot instead of accelerating it, and the property is testable directly
(``tests/test_m1_0_gateway.py`` drives it over an exhaustive sign/scale sweep
of the three axes and over a deliberately broken shaper subclass).

The clamp's numbers come from :mod:`gateway.catalog`, not from the regime
directly: the governor admits the named action first and then clamps to *that
action's* declared parameter bounds.  An action the catalog does not list is an
exact-zero stop, and an axis an admitted action does not declare is zeroed
rather than passed through — so the allowlist is on the control path instead of
being a document beside it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from .catalog import ActionCatalogV1, ActionNotAdmittedError, ActionSpecV1
from .limits import GovernorLimitsV1


class DispositionV1(Enum):
    """The HLD lattice. Ordered: a larger value is more restrictive."""

    PASS = 0
    CLAMP = 1
    HOLD = 2
    STOP = 3
    LATCHED_STOP = 4

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, DispositionV1):
            return NotImplemented
        return self.value < other.value

    def __le__(self, other: object) -> bool:
        if not isinstance(other, DispositionV1):
            return NotImplemented
        return self.value <= other.value

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, DispositionV1):
            return NotImplemented
        return self.value > other.value

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, DispositionV1):
            return NotImplemented
        return self.value >= other.value

    @property
    def permits_motion(self) -> bool:
        return self in (DispositionV1.PASS, DispositionV1.CLAMP)


@dataclass(frozen=True)
class MotionCandidateV1:
    """A proposed body-frame velocity. The governor never invents one."""

    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float

    def __post_init__(self) -> None:
        for name in ("vx_mps", "vy_mps", "vyaw_rad_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"motion candidate {name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"motion candidate {name} must be finite")

    @property
    def axes(self) -> tuple[float, float, float]:
        return (self.vx_mps, self.vy_mps, self.vyaw_rad_s)


#: The exact-zero candidate. Used wherever a stop is composed.
ZERO_CANDIDATE = MotionCandidateV1(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class AuthorityEvidenceV1:
    """Everything the governor is allowed to treat as evidence of authority.

    Every field is a *positive* statement that must be true for motion to be
    permitted.  There is no field whose default makes motion legal: the core
    builds this from what it actually observed this cycle, and a missing
    observation is a false, not an absent, field.
    """

    armed: bool
    latched: bool
    lease_active: bool
    state_fresh: bool
    state_sequence_ok: bool
    ttl_remaining_s: float
    vendor_writer_healthy: bool


@dataclass(frozen=True)
class GovernorVerdictV1:
    disposition: DispositionV1
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    causes: tuple[str, ...] = field(default=())

    @property
    def axes(self) -> tuple[float, float, float]:
        return (self.vx_mps, self.vy_mps, self.vyaw_rad_s)

    @property
    def is_exact_zero(self) -> bool:
        return all(value == 0.0 for value in self.axes)

    @property
    def primary_cause(self) -> str:
        return self.causes[0] if self.causes else ""


def _stop_verdict(causes: tuple[str, ...], *, latched: bool) -> GovernorVerdictV1:
    return GovernorVerdictV1(
        disposition=DispositionV1.LATCHED_STOP if latched else DispositionV1.STOP,
        vx_mps=0.0,
        vy_mps=0.0,
        vyaw_rad_s=0.0,
        causes=causes,
    )


class FinalGovernorV1:
    """Stateless per-cycle verdict. It recomputes; it never remembers."""

    def __init__(self, limits: GovernorLimitsV1, catalog: ActionCatalogV1) -> None:
        self._limits = limits
        self._catalog = catalog

    @property
    def limits(self) -> GovernorLimitsV1:
        return self._limits

    @property
    def catalog(self) -> ActionCatalogV1:
        return self._catalog

    def evaluate(
        self,
        action: str,
        candidate: MotionCandidateV1,
        evidence: AuthorityEvidenceV1,
    ) -> GovernorVerdictV1:
        if evidence.latched:
            return _stop_verdict(("latched",), latched=True)
        causes = self._stop_causes(evidence)
        if causes:
            return _stop_verdict(causes, latched=False)
        try:
            spec = self._catalog.admit(action)
        except ActionNotAdmittedError:
            return _stop_verdict(("action_not_in_catalog",), latched=False)
        shaped, clamped_axes = self._clamp(spec, candidate)
        shaped = self._veto_only(candidate, shaped)
        if shaped is None:
            return _stop_verdict(("governor_would_increase_motion",), latched=True)
        if clamped_axes:
            return GovernorVerdictV1(
                disposition=DispositionV1.CLAMP,
                vx_mps=shaped.vx_mps,
                vy_mps=shaped.vy_mps,
                vyaw_rad_s=shaped.vyaw_rad_s,
                causes=tuple(clamped_axes),
            )
        return GovernorVerdictV1(
            disposition=DispositionV1.PASS,
            vx_mps=shaped.vx_mps,
            vy_mps=shaped.vy_mps,
            vyaw_rad_s=shaped.vyaw_rad_s,
        )

    @staticmethod
    def _stop_causes(evidence: AuthorityEvidenceV1) -> tuple[str, ...]:
        """Every failed positive statement, most authority-specific first."""

        causes: list[str] = []
        if not evidence.armed:
            causes.append("gateway_disarmed")
        if not evidence.lease_active:
            causes.append("sport_lease_lost")
        if not evidence.state_sequence_ok:
            causes.append("state_sequence_not_advancing")
        if not evidence.state_fresh:
            causes.append("state_stale")
        if evidence.ttl_remaining_s <= 0.0:
            causes.append("local_ttl_expired")
        if not evidence.vendor_writer_healthy:
            causes.append("vendor_write_stalled")
        return tuple(causes)

    @staticmethod
    def _clamp(
        spec: ActionSpecV1,
        candidate: MotionCandidateV1,
    ) -> tuple[MotionCandidateV1, list[str]]:
        """Clamp to the *catalog's* bounds for the admitted action.

        The catalog is therefore on the control path rather than beside it: an
        axis the admitted action does not declare has no bound to be inside,
        and is zeroed rather than passed through.
        """

        bounds = {bound.name: bound for bound in spec.parameters}
        shaped: dict[str, float] = {}
        clamped: list[str] = []
        for name in ("vx_mps", "vy_mps", "vyaw_rad_s"):
            value = float(getattr(candidate, name))
            bound = bounds.get(name)
            limited = 0.0 if bound is None else bound.clamp(value)
            if limited != value:
                clamped.append(f"clamped:{name}")
            shaped[name] = limited
        return MotionCandidateV1(**shaped), clamped

    @staticmethod
    def _veto_only(
        candidate: MotionCandidateV1,
        shaped: MotionCandidateV1,
    ) -> MotionCandidateV1 | None:
        """X12's writer rule, enforced rather than documented.

        Returns ``None`` — meaning "throw this away and stop" — if the shaped
        result is larger in magnitude than the candidate on any axis, or has
        flipped its sign.  The tolerance is exactly zero: this is a comparison
        between two floats the same function produced.
        """

        for proposed, result in zip(candidate.axes, shaped.axes):
            if abs(result) > abs(proposed):
                return None
            if result * proposed < 0.0:
                return None
        return shaped
