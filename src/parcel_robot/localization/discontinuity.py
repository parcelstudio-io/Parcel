"""The discontinuity latch: motion stays disarmed until the place is re-earned.

CLAUDE_RESPONSE addendum **A4** is the rule and addendum **A10** is the list.
A4: "after pickup, restart, power-cycle, or any suspected discontinuity, motion
**latches disarmed**; re-arm requires either (a) globally discriminative
geometric evidence — a relocalization match whose second-best candidate is
worse by a pre-registered margin across the whole map, not a local residual
gate — or (b) an explicit operator pose-reset-and-validation transaction
(operator states the pose, the system verifies scan agreement, both are
journaled).  **HEALTHY + covariance never re-arms anything.**"  A10 enumerates
the six sources this module implements, each journalled with its trigger value.

**Why this is a latch and not a health level.**  NAV-CORE refuter 4b measured
both shipped arms translating after a kidnap on 824–840 of 840 HEALTHY ticks
(``research/20260824/nav-core/RESULTS.md``), and H7 measured a 6.3 m teleport
that never left HEALTHY while the covariance moved 1.00 -> 3.10 mm.  A level
that a good tick can lower is not a refusal.  So this object never lowers
itself: the only two exits are the two A4 paths, and both write a journal row.

**Why it lives in ``localization/`` and not in ``core/input_health.py``.**
Every A10 source is a statement about the localization estimate's continuity —
the estimator's own boot epoch, the machine that holds the map power-cycling,
a carried/airborne signature that voids the odometry prior, whole-map match
ambiguity, and the ``T_map_odom`` jump itself.  ``core/input_health.py`` is a
*pure freshness/provenance join over three declared inputs*; a fourth
``RequiredInput`` there would change ``DEFAULT_REQUIRED_INPUTS`` for every
consumer and every test that pins its fault set, and would still have nowhere
to put a margin or a jump magnitude.  The two COMPOSE instead: this latch
reports the same :class:`~parcel_robot.core.input_health.HealthAction`
vocabulary, so a caller holding both takes ``max(verdict.action, latch.action)``
and gets the stricter of them without either owning the other.

**The IMU / foot-contact seam is named, not faked.**  No robot hardware is on
hand (CLAUDE.md, owner), so :class:`CarriedSignature` defines exactly what a
body must publish for the carried check to be real, and
:class:`StubCarriedSignatureSource` is the honest stand-in: it says "standing"
and says out loud that it measured nothing.  A stub that guessed "carried"
would be a fake refusal; a stub that silently claimed authority would be the
W0-A defect in another costume.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from parcel_robot.core.input_health import HealthAction
from parcel_robot.localization.contract import LocalizationUpdate, RelocalizationMatch
from parcel_robot.localization.global_match import (
    GLOBAL_MATCH_MARGIN_MIN,
    OPERATOR_AGREEMENT_RMS_M,
)

__all__ = [
    "LOCALIZATION_JUMP_BOUND_M",
    "ArmingLatch",
    "ArmingRecord",
    "BodySignals",
    "CarriedSignature",
    "CarriedSignatureSource",
    "DiscontinuityTrigger",
    "LatchBounds",
    "OperatorPoseReset",
    "OperatorResetState",
    "StubCarriedSignatureSource",
]

#: PRE-REGISTERED.  ``bridge/timing.py``'s ``localization_jump_m`` is UNMEASURED
#: on every host record, so the latch's bound is stated here rather than read
#: from one: 0.35 m sits below the 0.5 m arrival band, so a jump large enough to
#: move the body across that band cannot pass unlatched.  NAV-CORE's own
#: measurement brackets it from both sides — room-scale nominal corrections
#: peaked at 0.029 m over 120 episodes, and the delegation bench measured
#: 7.15 m on a kidnap and 10.47 m on the relocalization that followed.
LOCALIZATION_JUMP_BOUND_M = 0.35


class DiscontinuityTrigger(str, Enum):
    """Addendum A10's list, and nothing else.  The value is the journal key."""

    BOOT_EPOCH_CHANGE = "boot_epoch_change"
    POWER_CYCLE = "power_cycle"
    CARRIED_SIGNATURE = "carried_signature"
    GLOBAL_MATCH_AMBIGUITY = "global_match_ambiguity"
    LOCALIZATION_JUMP = "localization_jump_m"
    OPERATOR_PICKUP = "operator_pickup"


class RearmPath(str, Enum):
    """A4's two exits.  There is no third, and no automatic one."""

    GLOBAL_MATCH_MARGIN = "global_match_margin"
    OPERATOR_POSE_RESET = "operator_pose_reset"


class OperatorResetState(str, Enum):
    """One statement's life.  ``PENDING`` is the only state that can re-arm."""

    PENDING = "pending"
    COMMITTED = "committed"
    REFUSED = "refused"


@dataclass(frozen=True)
class CarriedSignature:
    """What a body must publish for "is it being carried" to be answerable.

    ``feet_in_contact`` is the count of stance feet the contact estimator
    believes; ``vertical_accel_mps2`` is the IMU's body-z specific force with
    gravity removed.  ``measured`` is the honesty bit: a source that did not
    actually observe the body says ``False`` and can never trigger the latch,
    because a refusal minted from an unmeasured channel is not a refusal.
    """

    feet_in_contact: int
    vertical_accel_mps2: float
    stamp_ns: int
    source: str
    measured: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "feet_in_contact", int(self.feet_in_contact))
        object.__setattr__(self, "vertical_accel_mps2", float(self.vertical_accel_mps2))
        object.__setattr__(self, "stamp_ns", int(self.stamp_ns))
        object.__setattr__(self, "source", str(self.source))
        object.__setattr__(self, "measured", bool(self.measured))
        if self.feet_in_contact < 0:
            raise ValueError("feet_in_contact is a count and must be non-negative")
        if not math.isfinite(self.vertical_accel_mps2):
            raise ValueError("vertical_accel_mps2 must be finite")

    def is_carried(self, *, minimum_feet: int, free_fall_mps2: float) -> bool:
        """Carried/airborne while the commanded state says "standing"."""

        if not self.measured:
            return False
        return (
            self.feet_in_contact < int(minimum_feet)
            or abs(self.vertical_accel_mps2) >= float(free_fall_mps2)
        )


@runtime_checkable
class CarriedSignatureSource(Protocol):
    """The seam a real IMU / foot-contact estimator fills."""

    def carried_signature(self, *, stamp_ns: int) -> CarriedSignature: ...


class StubCarriedSignatureSource:
    """No IMU on this host, and it says so.  Never triggers the latch.

    Named rather than omitted so the A10 row is wired end to end and the thing
    that is missing is a *driver*, not a design.  ``measured=False`` is what
    keeps it from minting a refusal it did not observe.
    """

    name = "stub_no_imu"

    def carried_signature(self, *, stamp_ns: int) -> CarriedSignature:
        return CarriedSignature(
            feet_in_contact=4,
            vertical_accel_mps2=0.0,
            stamp_ns=int(stamp_ns),
            source=self.name,
            measured=False,
        )


@dataclass(frozen=True)
class BodySignals:
    """One tick of the A10 evidence that does not come from the localizer.

    ``boot_epoch`` identifies the process/machine generation that owns the map;
    any change is a restart, whether or not anything else noticed.
    ``power_cycled`` and ``operator_pickup`` are edges reported by the panel /
    physical control.  ``carried`` is the IMU/foot-contact signature.
    """

    boot_epoch: int | None = None
    power_cycled: bool = False
    operator_pickup: bool = False
    carried: CarriedSignature | None = None


@dataclass(frozen=True)
class LatchBounds:
    """Every threshold the latch reads, in one place, all pre-registered."""

    jump_bound_m: float = LOCALIZATION_JUMP_BOUND_M
    margin_min: float = GLOBAL_MATCH_MARGIN_MIN
    operator_agreement_rms_m: float = OPERATOR_AGREEMENT_RMS_M
    #: Fewer stance feet than this while nominally standing is "carried".
    minimum_feet_in_contact: int = 2
    #: |body-z specific force| at or above this is airborne/handled.
    free_fall_mps2: float = 6.0

    def __post_init__(self) -> None:
        for name in ("jump_bound_m", "operator_agreement_rms_m", "free_fall_mps2"):
            if float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if int(self.minimum_feet_in_contact) < 1:
            raise ValueError("minimum_feet_in_contact must be at least 1")


@dataclass(frozen=True)
class ArmingRecord:
    """One journalled latch, refusal or re-arm.  A4 requires the journal."""

    t_s: float
    event: str
    trigger: str
    value: float
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_s": float(self.t_s),
            "event": str(self.event),
            "trigger": str(self.trigger),
            "value": float(self.value),
            "detail": str(self.detail),
        }


@dataclass
class OperatorPoseReset:
    """ONE operator statement, usable ONCE.  A4 path (b), as re-measured.

    NAV-CORE's first refuter-4b operator arm passed the live body pose on every
    tick and re-armed **79 times in one episode** — functionally auto-resume
    under ambiguity (``REFUTER_4B_REMEASURE.md``).  The fix there was a harness
    discipline; here it is the type.  A statement is an object, its pose is
    captured at construction, and :class:`ArmingLatch` marks it COMMITTED or
    REFUSED the first time it is settled.  Handing the same object back on
    every tick therefore cannot re-arm twice, and a standing feed of *new*
    statements is a standing feed of operator statements, which is a different
    (operator-continuous) mode M1 does not ship.
    """

    stated_pose: tuple[float, float, float]
    stated_at_s: float
    operator: str = "operator"
    state: OperatorResetState = OperatorResetState.PENDING
    agreement_rms_m: float = math.nan

    def __post_init__(self) -> None:
        raw = tuple(self.stated_pose)
        if len(raw) != 3:
            raise ValueError("stated_pose must be (x, y, yaw)")
        pose = tuple(float(value) for value in raw)
        if not all(math.isfinite(value) for value in pose):
            raise ValueError("stated_pose must be finite")
        self.stated_pose = pose
        self.stated_at_s = float(self.stated_at_s)
        self.operator = str(self.operator)

    @property
    def spent(self) -> bool:
        return self.state is not OperatorResetState.PENDING


class ArmingLatch:
    """Latch on any A10 signal; re-arm only by an A4 path; journal everything.

    ``reanchor`` is how a successful re-arm reaches the estimator: the latch
    decides, the localizer moves.  Leaving the poke to the caller was the
    harness's shape and it meant a re-arm could be journalled without the map
    frame ever moving; passing the callback here makes the two atomic.
    """

    def __init__(
        self,
        *,
        bounds: LatchBounds | None = None,
        reanchor: Callable[[tuple[float, float, float]], None] | None = None,
        enabled: bool = True,
    ) -> None:
        self.bounds = bounds or LatchBounds()
        self.enabled = bool(enabled)
        self._reanchor = reanchor
        self._latched = False
        self._journal: list[ArmingRecord] = []
        self._standing: set[str] = set()
        self._boot_epoch: int | None = None
        self._last_margin: float = math.inf
        self._rearms = 0

    # -- state -------------------------------------------------------------

    @property
    def latched(self) -> bool:
        return self._latched

    @property
    def action(self) -> HealthAction:
        """The composable verdict.  A latch is a LATCHED_STOP, by definition."""

        return HealthAction.LATCHED_STOP if self._latched else HealthAction.ALLOW

    @property
    def translation_allowed(self) -> bool:
        return not self._latched

    @property
    def journal(self) -> tuple[ArmingRecord, ...]:
        return tuple(self._journal)

    @property
    def triggers(self) -> tuple[str, ...]:
        """Every discontinuity this latch has recorded, in order."""

        return tuple(
            row.trigger for row in self._journal if row.event in _LATCH_EVENTS
        )

    @property
    def rearms(self) -> int:
        return self._rearms

    @property
    def last_margin(self) -> float:
        return self._last_margin

    def journal_rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(row.as_dict() for row in self._journal)

    # -- latching ----------------------------------------------------------

    def observe(
        self,
        *,
        t_s: float,
        update: LocalizationUpdate | None = None,
        match: RelocalizationMatch | None = None,
        signals: BodySignals | None = None,
    ) -> bool:
        """One tick of evidence.  Latches; never re-arms.  True if it latched.

        Order is deliberate: the body signals first, because a restart or a
        pickup makes every geometric answer on the same tick suspect.
        """

        if not self.enabled:
            return False
        latched = False
        if signals is not None:
            latched = self.observe_signals(signals, t_s=t_s) or latched
        if update is not None:
            latched = self.observe_update(update, t_s=t_s) or latched
        candidate = match if match is not None else getattr(update, "match", None)
        if candidate is not None:
            latched = self.observe_match(candidate, t_s=t_s) or latched
        return latched

    def observe_signals(self, signals: BodySignals, *, t_s: float) -> bool:
        """A10 rows 1-3 and 6: boot epoch, power cycle, carried, pickup.

        Every row is evaluated in BOTH directions.  A flag that is still raised
        on the next tick is the same discontinuity and writes nothing; a flag
        that drops and is raised again is a NEW one and writes a row.  The boot
        epoch needs no clearing — an epoch that has not changed did not fire.
        """

        if not self.enabled:
            return False
        latched = False
        epoch = signals.boot_epoch
        if epoch is not None:
            epoch = int(epoch)
            if self._boot_epoch is None:
                self._boot_epoch = epoch
            elif epoch != self._boot_epoch:
                previous, self._boot_epoch = self._boot_epoch, epoch
                self._standing.discard(DiscontinuityTrigger.BOOT_EPOCH_CHANGE.value)
                latched = self._latch(
                    t_s,
                    DiscontinuityTrigger.BOOT_EPOCH_CHANGE,
                    float(epoch),
                    detail=f"was {previous}",
                ) or latched
        latched = self._signal(
            t_s,
            DiscontinuityTrigger.POWER_CYCLE,
            active=bool(signals.power_cycled),
            value=1.0,
            detail="power-cycle flag",
        ) or latched
        carried = signals.carried
        if carried is not None:
            latched = self._signal(
                t_s,
                DiscontinuityTrigger.CARRIED_SIGNATURE,
                active=carried.is_carried(
                    minimum_feet=self.bounds.minimum_feet_in_contact,
                    free_fall_mps2=self.bounds.free_fall_mps2,
                ),
                value=float(carried.feet_in_contact),
                detail=(
                    f"vertical_accel_mps2={carried.vertical_accel_mps2:.3f} "
                    f"source={carried.source}"
                ),
            ) or latched
        latched = self._signal(
            t_s,
            DiscontinuityTrigger.OPERATOR_PICKUP,
            active=bool(signals.operator_pickup),
            value=1.0,
            detail="panel/physical",
        ) or latched
        return latched

    def observe_update(self, update: LocalizationUpdate, *, t_s: float) -> bool:
        """A10 row 5: the ``localization_jump_m`` bound, on the body's own jump."""

        if not self.enabled:
            return False
        jump = float(update.jump_m)
        return self._signal(
            t_s,
            DiscontinuityTrigger.LOCALIZATION_JUMP,
            active=jump > self.bounds.jump_bound_m,
            value=jump,
            detail=f"bound {self.bounds.jump_bound_m:.3f} m health {update.health.value}",
        )

    def observe_match(self, match: RelocalizationMatch, *, t_s: float) -> bool:
        """A10 row 4: whole-map ambiguity, from the second-best margin."""

        if not self.enabled:
            return False
        self._last_margin = match.margin
        return self._signal(
            t_s,
            DiscontinuityTrigger.GLOBAL_MATCH_AMBIGUITY,
            active=not match.is_discriminative(self.bounds.margin_min),
            value=match.margin,
            detail=(
                f"threshold {self.bounds.margin_min} over {match.hypotheses} "
                f"hypotheses ({match.source})"
            ),
        )

    # -- re-arming ---------------------------------------------------------

    def try_rearm_by_margin(self, match: RelocalizationMatch, *, t_s: float) -> bool:
        """A4 path (a): globally discriminative geometry, over the whole map."""

        if not self._latched:
            return False
        self._last_margin = match.margin
        if not match.is_discriminative(self.bounds.margin_min):
            return False
        self._rearm(t_s, RearmPath.GLOBAL_MATCH_MARGIN, match.margin, match.pose)
        return True

    def try_rearm_by_operator(
        self,
        transaction: OperatorPoseReset,
        observed: Any,
        matcher: Any,
        *,
        t_s: float,
    ) -> bool:
        """A4 path (b): one statement, verified against the scan, journalled.

        The transaction is settled either way — a statement the scan refuses is
        SPENT, not retried silently, which is what keeps a repeated feed from
        becoming a standing authorization.
        """

        if not isinstance(transaction, OperatorPoseReset):
            raise TypeError("an operator re-arm needs an OperatorPoseReset statement")
        if transaction.spent or not self._latched:
            return False
        rms = float(matcher.agreement_rms_m(observed, transaction.stated_pose))
        transaction.agreement_rms_m = rms
        if not (rms <= self.bounds.operator_agreement_rms_m):
            transaction.state = OperatorResetState.REFUSED
            self._journal.append(
                ArmingRecord(
                    t_s=float(t_s),
                    event="operator_refused",
                    trigger="scan_agreement_rms_m",
                    value=rms,
                    detail=(
                        f"stated {_pose_text(transaction.stated_pose)} by "
                        f"{transaction.operator}; bound "
                        f"{self.bounds.operator_agreement_rms_m:.3f} m"
                    ),
                )
            )
            return False
        transaction.state = OperatorResetState.COMMITTED
        self._rearm(
            t_s,
            RearmPath.OPERATOR_POSE_RESET,
            rms,
            transaction.stated_pose,
            detail=f"stated by {transaction.operator} at t={transaction.stated_at_s:.2f}s",
        )
        return True

    # -- machinery ---------------------------------------------------------

    def _signal(
        self,
        t_s: float,
        trigger: DiscontinuityTrigger,
        *,
        active: bool,
        value: float,
        detail: str = "",
    ) -> bool:
        """One level-triggered A10 row: latch on the rising edge, clear on the fall."""

        if not active:
            self._standing.discard(trigger.value)
            return False
        return self._latch(t_s, trigger, value, detail=detail)

    def _latch(
        self,
        t_s: float,
        trigger: DiscontinuityTrigger,
        value: float,
        *,
        detail: str = "",
    ) -> bool:
        """Record a discontinuity; set the latch if it was not already set.

        A trigger that is ALREADY standing writes nothing — the aliased-world
        ambiguity check re-asks its question every few ticks and a row per ask
        would bury the journal.  A DIFFERENT trigger arriving while the latch
        holds is written as ``retriggered``, because "it was also picked up"
        is evidence an operator reading the journal needs and losing it to a
        deduplication would be the wrong kind of tidy.
        """

        if trigger.value in self._standing:
            return False
        self._standing.add(trigger.value)
        already = self._latched
        self._latched = True
        self._journal.append(
            ArmingRecord(
                t_s=float(t_s),
                event="retriggered" if already else "latched",
                trigger=trigger.value,
                value=float(value),
                detail=detail,
            )
        )
        return not already

    def _rearm(
        self,
        t_s: float,
        path: RearmPath,
        value: float,
        pose: tuple[float, float, float],
        *,
        detail: str = "",
    ) -> None:
        if self._reanchor is not None:
            self._reanchor(pose)
        self._latched = False
        self._standing.clear()
        self._rearms += 1
        self._journal.append(
            ArmingRecord(
                t_s=float(t_s),
                event="rearmed",
                trigger=path.value,
                value=float(value),
                detail=detail or _pose_text(pose),
            )
        )


#: Journal events that record a discontinuity (as opposed to a re-arm).
_LATCH_EVENTS = frozenset({"latched", "retriggered"})


def _pose_text(pose: tuple[float, float, float]) -> str:
    return f"({pose[0]:.3f}, {pose[1]:.3f}, {pose[2]:.3f})"
