"""The zero-translation lease: what a drive is allowed to do to the body.

CARD A9 (``scrum/20260824/task_2/IMPLEMENTATION_PLAN.md`` row A9), built on
research H3 (``research/20260823/drives-and-initiative/``) and the ratified
wave-2 terminal amendment (``research/20260824/FABLE_WAVE2_RATIFICATION.md``).

WHY THIS MODULE EXISTS
----------------------
``attention/drives.py`` decides *whether the dog wants to do something*. It is
deliberately not an authority and it has no idea what a body is. This module is
the authority between that want and the body: it admits a proposal, hands back
an offer the body can execute, governs how often that may happen, yields
instantly when the owner speaks, and terminates every initiated leg.

THE LEASE IS STRUCTURAL, NOT A POLICY TABLE
-------------------------------------------
H3 measured 1,222 contact episodes when an initiated errand was allowed to
translate the body — 1,213 of them with the dog STANDING STILL inside a
pedestrian route, because an initiated leg had no terminal. The verdict and
Codex's cross-review both concluded: **M1 keeps proactive travel radius at
zero.** That is enforced here three ways, none of which is a rule a caller
could forget to consult:

1. :class:`BodyOffer` — the only thing this module can hand out — has no
   velocity field and no way to express one. A drive cannot ask for translation
   because the vocabulary it is answered in does not contain it.
2. :class:`ZeroTranslationLease` refuses at CONSTRUCTION if handed a policy
   whose ``travel_radius_m`` is not zero, and refuses at ADMISSION any proposal
   whose ``travels`` is true. Both raise :class:`TranslationRefused`.
3. Even a rogue caller that fabricated a velocity could not deliver it: the
   command arbiter (``core/commands.py``) validates ``MotionIntent.source``
   against ``SOURCE_PRIORITIES`` by name, and no drive source exists in it.

THE TERMINAL IS A SAFE-HOLD INVARIANT, NOT A SCRIPTED RETURN
------------------------------------------------------------
The wave-2 study measured the obvious fix and refuted it: adding a scripted
stop-and-return to each initiated leg made the nuisance WORSE (contacts
319→323, contact time 89.1→244.6 s), because a return leg is a second
uninvited traversal of the same live people-flow. The ratified rule is a
safe-hold invariant plus a receding horizon against predicted occupancy, and a
typed terminal from :data:`TERMINAL_KINDS`.

At travel radius zero that rule collapses to something this module can prove
rather than plan: **the safe-hold region is where the body already is.** The
dog never left it, so admission does not have to search for one, no return
trajectory can exist, and the only reachable terminals are
:data:`TERMINAL_HOLD` and :data:`TERMINAL_RELEASE_AUTHORITY`
(:data:`M1_REACHABLE_TERMINALS`). The other three names are carried, unused, so
that the card that eventually earns a positive radius extends a vocabulary
instead of inventing one — and so a test can assert that M1 never emits them.

RATE, AND WHY 6/h
-----------------
H3's D1 pre-registered band was 3-8 initiations/hour and measured 5, 5 and 6
over three seeds (~5.3/h). :attr:`InitiativeLimits.max_per_hour` therefore
ships at ``6.0`` — the measured ceiling of the three seeds, inside the
pre-registered band — over a sliding one-hour window, on top of the
proposer's own ``refractory_s`` floor between any two proposals. The envelope
is a governor and not a scheduler: it can only say no.

PURITY
------
No clock, no I/O, no model, no import of the runtime. ``now_s`` is supplied by
the caller, exactly as :class:`~parcel_robot.motion.body_composer.BodyComposer`
requires, so a harness and a runtime tick this identically.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .drives import InitiativeKind, InitiativePolicy, InitiativeProposal

# --------------------------------------------------------------------------
# Terminals — the ratified vocabulary.
# --------------------------------------------------------------------------

TERMINAL_HOLD = "hold"
TERMINAL_RETURN = "return"
TERMINAL_YIELD_ASIDE = "yield_aside"
TERMINAL_FOLLOW_OWNER = "follow_owner"
TERMINAL_RELEASE_AUTHORITY = "release_authority"

#: Every terminal the amendment names. Carried whole so the successor card
#: extends a vocabulary rather than inventing one.
TERMINAL_KINDS: frozenset[str] = frozenset(
    {
        TERMINAL_HOLD,
        TERMINAL_RETURN,
        TERMINAL_YIELD_ASIDE,
        TERMINAL_FOLLOW_OWNER,
        TERMINAL_RELEASE_AUTHORITY,
    }
)

#: The two a zero-radius leg can reach. ``RETURN``/``YIELD_ASIDE``/
#: ``FOLLOW_OWNER`` all describe going somewhere, and a leg that never left
#: cannot go back, step aside, or catch up.
M1_REACHABLE_TERMINALS: frozenset[str] = frozenset(
    {TERMINAL_HOLD, TERMINAL_RELEASE_AUTHORITY}
)

# Why a leg ended. Reported, never inferred: "the owner spoke" and "it ran out
# of budget" are the same terminal and completely different facts.
END_COMPLETED = "completed"
END_OWNER_COMMAND = "owner_command"
END_EMERGENCY_STOP = "emergency_stop"
END_WITHDRAWN = "withdrawn"

#: Behaviors a zero-radius lease can execute: H3's non-travelling ones, plus
#: the name for "nothing initiated", which is also the safe-hold body.
#: ``LOOK`` has somewhere to look; ``ORIENT`` is the same behavior when the
#: digest could not say where (the dog lifts its head rather than snapping it
#: to a bearing nobody measured).
BEHAVIOR_NONE = "none"
BEHAVIOR_LOOK = "look"
BEHAVIOR_ORIENT = "orient"
BEHAVIOR_STRETCH = "stretch"
BEHAVIOR_REMARK = "remark"
BEHAVIOR_KINDS: frozenset[str] = frozenset(
    {BEHAVIOR_NONE, BEHAVIOR_LOOK, BEHAVIOR_ORIENT, BEHAVIOR_STRETCH, BEHAVIOR_REMARK}
)

#: Which drive proposal becomes which body behavior. ``REST`` becomes a
#: stretch — the one comfort behavior a stationary body has.
_KIND_TO_BEHAVIOR: dict[str, str] = {
    InitiativeKind.LOOK.value: BEHAVIOR_LOOK,
    InitiativeKind.REMARK.value: BEHAVIOR_REMARK,
    InitiativeKind.REST.value: BEHAVIOR_STRETCH,
}

#: Bounds on what an offer may ask the body for. Well inside the composer's own
#: envelope (``motion/body_composer.ComposerLimits``), which clamps anyway —
#: this is the lease refusing to ASK for something the composer would have to
#: shave, so an out-of-band offer is a bug here and not a clamp there.
MAX_OFFER_GAZE_YAW_RAD = 1.2
MAX_OFFER_GAZE_PITCH_RAD = 0.5
MAX_OFFER_POSTURE_DZ_M = 0.04
MAX_OFFER_POSTURE_PITCH_RAD = 0.20

#: What the dog says when it opens a conversation and no hosted phrasing is
#: available (or was refused). H2 measured the local 8B at 66-71 ms TTFT as a
#: *phrasing* model; these are the floor beneath even that — no model, no
#: socket, no budget. Spoken through the product's own canned-line path
#: (``RobotRuntime._brain_vocalize``), like every other line the dog owns.
LOCAL_OPENERS: tuple[str, ...] = (
    "I noticed something over here.",
    "Something changed since I last looked.",
    "I've been keeping an eye on this corner.",
    "I saw something I hadn't seen before.",
)

#: Governor purpose string for a hosted phrasing call a drive would open.
OPENER_PURPOSE = "drive_opener"

OPENER_LOCAL_NO_GOVERNOR = "local_no_governor"
OPENER_LOCAL_REFUSED = "local_budget_refused"
OPENER_HOSTED_ADMITTED = "hosted_admitted"


class TranslationRefused(RuntimeError):
    """A drive asked for, or was configured for, self-initiated translation."""


class LeaseBusy(RuntimeError):
    """A second behavior was admitted while one was still running."""


# --------------------------------------------------------------------------
# The offer — the only thing a drive can put on the body.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BodyOffer:
    """What an initiated behavior asks the body for. NO velocity, by type.

    ``gaze`` is a (yaw, pitch) target in radians or ``None`` for "no opinion";
    ``posture`` is an additive (dz, pitch) offset. Both are additive requests
    handed to the composer, which owns the rate/accel/jerk limiting. ``line``
    is a sentence to say, or empty.

    There is no ``velocity``, no ``goal``, no ``waypoint`` and no ``budget_m``.
    That absence is the lease: see the module docstring.
    """

    behavior: str
    gaze: tuple[float, float] | None = None
    posture: tuple[float, float] = (0.0, 0.0)
    style: str = "calm"
    line: str = ""

    def __post_init__(self) -> None:
        if self.behavior not in BEHAVIOR_KINDS:
            raise ValueError(f"unsupported initiative behavior: {self.behavior!r}")
        if self.gaze is not None:
            yaw, pitch = self.gaze
            if not (math.isfinite(yaw) and math.isfinite(pitch)):
                raise ValueError("offer gaze must be finite")
            if abs(yaw) > MAX_OFFER_GAZE_YAW_RAD or abs(pitch) > MAX_OFFER_GAZE_PITCH_RAD:
                raise ValueError("offer gaze exceeds the lease's own bound")
        dz, pitch = self.posture
        if not (math.isfinite(dz) and math.isfinite(pitch)):
            raise ValueError("offer posture must be finite")
        if abs(dz) > MAX_OFFER_POSTURE_DZ_M or abs(pitch) > MAX_OFFER_POSTURE_PITCH_RAD:
            raise ValueError("offer posture exceeds the lease's own bound")

    @property
    def is_neutral(self) -> bool:
        return self.gaze is None and self.posture == (0.0, 0.0) and not self.line

    def as_dict(self) -> dict[str, object]:
        return {
            "behavior": self.behavior,
            "gaze": None if self.gaze is None else [round(v, 4) for v in self.gaze],
            "posture": [round(v, 4) for v in self.posture],
            "style": self.style,
            "line": self.line,
        }


#: The offer a body makes when nothing is initiated. Also the safe-hold body:
#: neutral is not "no command", it is the command to be still.
NEUTRAL_OFFER = BodyOffer(behavior=BEHAVIOR_NONE)


@dataclass(frozen=True, slots=True)
class Terminal:
    """How one initiated leg ended. Every leg gets one; none is implicit."""

    kind: str
    reason: str
    at_s: float
    behavior: str = ""
    returned: bool = False

    def __post_init__(self) -> None:
        if self.kind not in TERMINAL_KINDS:
            raise ValueError(f"unsupported terminal: {self.kind!r}")
        if self.returned:  # pragma: no cover - defended, never constructed
            raise ValueError(
                "a zero-radius leg cannot return; stop-and-return was refuted "
                "(contacts 319->323, contact time 89.1->244.6 s)"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "at_s": round(self.at_s, 4),
            "behavior": self.behavior,
            "returned": self.returned,
        }


@dataclass(frozen=True, slots=True)
class Admission:
    """Why the governor said yes or no. A refusal is an answer with a name."""

    admitted: bool
    code: str
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"admitted": self.admitted, "code": self.code, "detail": self.detail}


ADMIT_OK = "admitted"
REFUSE_DISABLED = "initiative_disabled"
REFUSE_EMERGENCY = "emergency_stopped"
REFUSE_OWNER_ACTIVE = "owner_owns_motion"
REFUSE_QUIET = "quiet_window"
REFUSE_REFRACTORY = "refractory"
REFUSE_RATE = "rate_envelope_reached"
REFUSE_BUSY = "behavior_running"
REFUSE_TRAVEL = "travel_refused"


@dataclass(frozen=True)
class InitiativeLimits:
    """The initiation-rate envelope. See the module docstring for the numbers."""

    enabled: bool = False
    max_per_hour: float = 6.0
    window_s: float = 3600.0
    refractory_s: float = 120.0
    #: Longest any one non-travelling behavior may hold the body.
    max_behavior_s: float = 8.0

    def __post_init__(self) -> None:
        if not 0.0 < self.max_per_hour <= 60.0:
            raise ValueError("max_per_hour must be in (0, 60]")
        if self.window_s <= 0.0:
            raise ValueError("window_s must be positive")
        if self.refractory_s < 0.0:
            raise ValueError("refractory_s cannot be negative")
        if not 0.0 < self.max_behavior_s <= 60.0:
            raise ValueError("max_behavior_s must be in (0, 60]")

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "max_per_hour": self.max_per_hour,
            "window_s": self.window_s,
            "refractory_s": self.refractory_s,
            "max_behavior_s": self.max_behavior_s,
        }


@dataclass(frozen=True, slots=True)
class OpenerDecision:
    """Whether a drive's opening line may be phrased by a hosted model."""

    hosted: bool
    code: str
    line: str
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "hosted": self.hosted,
            "code": self.code,
            "line": self.line,
            "reason": self.reason,
        }


def choose_opener(seed: int) -> str:
    """A deterministic local opener. Seeded, so a soak replays exactly."""

    return LOCAL_OPENERS[int(seed) % len(LOCAL_OPENERS)]


def open_line(
    governor: object | None,
    *,
    seed: int = 0,
    purpose: str = OPENER_PURPOSE,
) -> OpenerDecision:
    """Ask A7's governor whether a drive may spend money on phrasing.

    Three outcomes and all three speak:

    * no governor wired  -> local phrase (a build without a budget is not a
      build with an unlimited one);
    * governor refuses   -> local phrase, carrying the governor's own reason
      so "the envelope said no" stays distinguishable from "the socket died";
    * governor admits    -> the caller may open a hosted phrasing call.

    ``call_class`` is left at the governor's default (routine) on purpose: a
    dog's opening remark is the most preemptable thing in the system, and
    nothing self-initiated may ever be billed as critical.
    """

    fallback = choose_opener(seed)
    admit = getattr(governor, "admit", None)
    if governor is None or not callable(admit):
        return OpenerDecision(
            hosted=False,
            code=OPENER_LOCAL_NO_GOVERNOR,
            line=fallback,
            reason="no hosted-call governor is wired",
        )
    decision = admit(purpose)
    if bool(getattr(decision, "admitted", False)):
        return OpenerDecision(
            hosted=True,
            code=OPENER_HOSTED_ADMITTED,
            line=fallback,
            reason=str(getattr(decision, "reason", "")),
        )
    return OpenerDecision(
        hosted=False,
        code=OPENER_LOCAL_REFUSED,
        line=fallback,
        reason=str(getattr(decision, "reason", "")) or str(getattr(decision, "code", "")),
    )


@dataclass(frozen=True, slots=True)
class LeaseTick:
    """One tick of the lease: what the body should do, and what just ended."""

    offer: BodyOffer
    running: bool
    terminal: Terminal | None = None
    behavior: str = ""
    remaining_s: float = 0.0


@dataclass
class ZeroTranslationLease:
    """Admit, run and terminate ONE non-translating initiated behavior.

    Stateful in the way a lease is: at most one behavior at a time, a sliding
    window of when the previous ones started, and the terminal of the last one.
    """

    policy: InitiativePolicy = field(default_factory=InitiativePolicy)
    limits: InitiativeLimits = field(default_factory=InitiativeLimits)
    #: Optional door for "may the dog speak right now" — the product's real
    #: quiet-window/night-band authority (``realtime.whisperer.ChatterScheduler``)
    #: injected as a predicate rather than re-implemented here.
    quiet: Callable[[float], bool] | None = None

    def __post_init__(self) -> None:
        if float(self.policy.travel_radius_m) != 0.0:
            raise TranslationRefused(
                "the M1 lease is zero-translation; a policy with "
                f"travel_radius_m={self.policy.travel_radius_m!r} cannot hold it "
                "(H3 D4: 1,222 contact episodes refuted self-initiated travel)"
            )
        self._starts: list[float] = []
        self._behavior: str = ""
        self._started_s: float = 0.0
        self._offer: BodyOffer = NEUTRAL_OFFER
        self._terminal: Terminal | None = None
        self.admitted = 0
        self.refused = 0
        self.yields = 0
        self.terminals: list[Terminal] = []

    # -- reads ---------------------------------------------------------------
    @property
    def running(self) -> bool:
        return bool(self._behavior)

    @property
    def behavior(self) -> str:
        return self._behavior

    @property
    def last_terminal(self) -> Terminal | None:
        return self._terminal

    def initiations_in_window(self, now_s: float) -> int:
        cutoff = float(now_s) - self.limits.window_s
        return sum(1 for start in self._starts if start > cutoff)

    # -- admission -----------------------------------------------------------
    def may_admit(
        self,
        now_s: float,
        *,
        owner_active: bool = False,
        emergency: bool = False,
    ) -> Admission:
        """The rate envelope, in order, before any proposal is even looked at."""

        if not self.limits.enabled:
            return Admission(False, REFUSE_DISABLED)
        if emergency:
            return Admission(False, REFUSE_EMERGENCY)
        if owner_active:
            return Admission(False, REFUSE_OWNER_ACTIVE)
        if self.running:
            return Admission(False, REFUSE_BUSY, self._behavior)
        if self.quiet is not None and not self.quiet(float(now_s)):
            return Admission(False, REFUSE_QUIET)
        if self._starts:
            since = float(now_s) - self._starts[-1]
            if since < self.limits.refractory_s:
                return Admission(False, REFUSE_REFRACTORY, f"{since:.1f}s")
        count = self.initiations_in_window(now_s)
        if count >= self.limits.max_per_hour:
            return Admission(
                False,
                REFUSE_RATE,
                f"{count} in the last {self.limits.window_s:.0f}s",
            )
        return Admission(True, ADMIT_OK)

    def admit(
        self,
        proposal: InitiativeProposal,
        now_s: float,
        *,
        owner_active: bool = False,
        emergency: bool = False,
        gaze: tuple[float, float] | None = None,
        line: str = "",
    ) -> Admission:
        """Turn a drive proposal into a running body behavior, or refuse it.

        A travelling proposal is refused BY TYPE before the envelope is even
        consulted, and the refusal is an exception rather than a code: a caller
        that handed this a ``GO_CHECK`` has a bug the return value would let it
        ignore.
        """

        if proposal.travels or float(proposal.budget_m) != 0.0:
            self.refused += 1
            raise TranslationRefused(
                f"{proposal.kind!r} would translate the body "
                f"(budget_m={proposal.budget_m!r}); the M1 lease is zero-translation"
            )
        behavior = _KIND_TO_BEHAVIOR.get(str(proposal.kind))
        if behavior is None:
            self.refused += 1
            raise TranslationRefused(
                f"{proposal.kind!r} has no non-translating body behavior"
            )
        verdict = self.may_admit(now_s, owner_active=owner_active, emergency=emergency)
        if not verdict.admitted:
            self.refused += 1
            return verdict
        offer = _offer_for(behavior, proposal, gaze=gaze, line=line)
        self._behavior = behavior
        self._started_s = float(now_s)
        self._offer = offer
        self._terminal = None
        self._starts.append(float(now_s))
        self.admitted += 1
        return verdict

    # -- the tick ------------------------------------------------------------
    def tick(
        self,
        now_s: float,
        *,
        owner_active: bool = False,
        emergency: bool = False,
    ) -> LeaseTick:
        """Advance the running behavior. Yields in the SAME tick, never the next.

        Order is the point. The two preemptions are read before the budget,
        and the terminal they produce is applied before the offer is returned,
        so the offer this call hands back is already the safe-hold one. There
        is no tick in which the owner has spoken and the dog is still doing its
        own thing.
        """

        if not self._behavior:
            return LeaseTick(offer=NEUTRAL_OFFER, running=False, terminal=self._terminal)
        if emergency:
            return self._end(now_s, END_EMERGENCY_STOP, TERMINAL_RELEASE_AUTHORITY)
        if owner_active:
            self.yields += 1
            return self._end(now_s, END_OWNER_COMMAND, TERMINAL_RELEASE_AUTHORITY)
        elapsed = float(now_s) - self._started_s
        if elapsed >= self.limits.max_behavior_s:
            return self._end(now_s, END_COMPLETED, TERMINAL_HOLD)
        return LeaseTick(
            offer=self._offer,
            running=True,
            behavior=self._behavior,
            remaining_s=max(0.0, self.limits.max_behavior_s - elapsed),
        )

    def withdraw(self, now_s: float, reason: str = END_WITHDRAWN) -> LeaseTick:
        """End the leg from outside (the caller changed its mind)."""

        if not self._behavior:
            return LeaseTick(offer=NEUTRAL_OFFER, running=False, terminal=self._terminal)
        return self._end(now_s, reason, TERMINAL_HOLD)

    def _end(self, now_s: float, reason: str, kind: str) -> LeaseTick:
        """Every exit goes through here, and every exit is a safe hold.

        ``returned=False`` is not a default, it is the invariant: the body did
        not travel, so the safe-hold region is the one it is standing in and no
        return trajectory exists to emit. :class:`Terminal` refuses ``True``.
        """

        terminal = Terminal(
            kind=kind,
            reason=reason,
            at_s=float(now_s),
            behavior=self._behavior,
            returned=False,
        )
        self._behavior = ""
        self._offer = NEUTRAL_OFFER
        self._terminal = terminal
        self.terminals.append(terminal)
        return LeaseTick(offer=NEUTRAL_OFFER, running=False, terminal=terminal)

    def snapshot(self, now_s: float) -> dict[str, object]:
        return {
            "running": self.running,
            "behavior": self._behavior,
            "admitted": self.admitted,
            "refused": self.refused,
            "yields": self.yields,
            "initiations_in_window": self.initiations_in_window(now_s),
            "travel_radius_m": float(self.policy.travel_radius_m),
            "limits": self.limits.as_dict(),
            "last_terminal": None if self._terminal is None else self._terminal.as_dict(),
        }


def _offer_for(
    behavior: str,
    proposal: InitiativeProposal,
    *,
    gaze: tuple[float, float] | None,
    line: str,
) -> BodyOffer:
    """The body shape of one admitted behavior. Bounded by construction."""

    if gaze is None and proposal.bearing_rad is not None:
        gaze = (
            _clamp(float(proposal.bearing_rad), MAX_OFFER_GAZE_YAW_RAD),
            0.0,
        )
    if behavior == BEHAVIOR_STRETCH:
        return BodyOffer(
            behavior=BEHAVIOR_STRETCH,
            posture=(MAX_OFFER_POSTURE_DZ_M, MAX_OFFER_POSTURE_PITCH_RAD * 0.5),
            style="calm",
        )
    if behavior == BEHAVIOR_REMARK:
        return BodyOffer(
            behavior=BEHAVIOR_REMARK,
            gaze=gaze,
            style="alert" if gaze is not None else "calm",
            line=line,
        )
    if gaze is None:
        # Nothing measured a bearing, so there is nothing to look AT. The dog
        # lifts its head instead of snapping it to a number nobody supplied.
        return BodyOffer(behavior=BEHAVIOR_ORIENT, posture=(0.0, -0.05), style="calm")
    return BodyOffer(behavior=behavior, gaze=gaze, style="alert")


def _clamp(value: float, bound: float) -> float:
    return max(-bound, min(bound, value))


def reachable_terminals(policy: InitiativePolicy) -> frozenset[str]:
    """Which terminals this policy can actually produce. Radius 0 -> two."""

    if float(policy.travel_radius_m) > 0.0:  # pragma: no cover - refused above
        return TERMINAL_KINDS
    return M1_REACHABLE_TERMINALS


__all__: Sequence[str] = (
    "ADMIT_OK",
    "BEHAVIOR_KINDS",
    "BEHAVIOR_LOOK",
    "BEHAVIOR_NONE",
    "BEHAVIOR_ORIENT",
    "BEHAVIOR_REMARK",
    "BEHAVIOR_STRETCH",
    "END_COMPLETED",
    "END_EMERGENCY_STOP",
    "END_OWNER_COMMAND",
    "END_WITHDRAWN",
    "LOCAL_OPENERS",
    "M1_REACHABLE_TERMINALS",
    "NEUTRAL_OFFER",
    "OPENER_HOSTED_ADMITTED",
    "OPENER_LOCAL_NO_GOVERNOR",
    "OPENER_LOCAL_REFUSED",
    "OPENER_PURPOSE",
    "REFUSE_BUSY",
    "REFUSE_DISABLED",
    "REFUSE_EMERGENCY",
    "REFUSE_OWNER_ACTIVE",
    "REFUSE_QUIET",
    "REFUSE_RATE",
    "REFUSE_REFRACTORY",
    "TERMINAL_FOLLOW_OWNER",
    "TERMINAL_HOLD",
    "TERMINAL_KINDS",
    "TERMINAL_RELEASE_AUTHORITY",
    "TERMINAL_RETURN",
    "TERMINAL_YIELD_ASIDE",
    "Admission",
    "BodyOffer",
    "InitiativeLimits",
    "LeaseBusy",
    "LeaseTick",
    "OpenerDecision",
    "Terminal",
    "TranslationRefused",
    "ZeroTranslationLease",
    "choose_opener",
    "open_line",
    "reachable_terminals",
)
