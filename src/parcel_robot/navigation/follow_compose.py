"""Follow, composed onto the observation spine — card A8, HLD Gate 6.

Card A4 left Follow with a V2 entry point that re-projects a
:class:`~parcel_robot.contracts.navigation_snapshot_v2.NavigationSnapshotV2`
onto the simulator-shaped carrier and said so out loud: *"``OwnerBeliefV1``
already carries the ambiguity/loss evidence Gate 6 needs
(``snapshot.owner.ambiguous`` / ``.lost``).  This path does not consume it
yet."*  This module consumes it, and it adds the one check the assembler
cannot make on Follow's behalf.

WHAT THIS MODULE IS FOR
-----------------------
Follow is the only behavior that steers the body at a **person** using
evidence from two different channels at once: WHERE he is (range/bearing, the
traversability and owner channels) and WHO he is (pixels, the owner channel's
identity fields).  HLD §4.2 names mixing a fresh image with an old pose as the
failure the stamped header exists to catch, and Gate 6 asks for the
synchronization explicitly.  So:

* :func:`owner_range_sync_reasons` refuses a target assembled from two
  epochs, or from two captures further apart than the tighter of the two
  producers' own TTLs.  **It adds no new number**: the bound is
  ``min(owner.max_age_ns, scan.max_age_ns)``, a derivation from what the two
  producers already declare, and the assembler's own reasons are carried
  through ahead of it rather than replaced.
* Ambiguity and loss are read from ``OwnerBeliefV1``'s own derived state, not
  re-derived from a confidence float — card OT-2 measured what thresholding
  the float costs (a ground-truth 1.0 and an uncalibrated cosine 0.97 meaning
  the same thing).

WHAT IT DOES NOT DO
-------------------
It moves **no floor**.  It owns no clearance number, it does not call
``apply_reactive_safety``, and it cannot make a command that the reactive gate
would have stopped survive: every command it returns still travels the
runtime's ordinary dispatch chain (smoother → input-health join → A3's latch →
``apply_reactive_safety`` → TTC → shaper).  Everything here is subtractive —
it can only turn a follow command into a HOLD.

HOLD, NOT STOP
--------------
A HOLD here is a zero-translation command with the yaw the controller would
have used suppressed as well, and the behaviour stays ENABLED.  It is the
wave-2 ratified shape (``IMPLEMENTATION_PLAN.md`` A9: "a safe-hold invariant
… NOT a scripted stop-and-return", which measured worse — contacts 319→323,
contact time 89→245 s).  Reacquisition is allowed and is bounded by a window
the CALLER supplies from the owner-search configuration it already owns, so
this module invents no timeout either.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from parcel_robot.contracts.navigation_snapshot_v2 import NavigationSnapshotV2
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.follow import (
    FollowDecision,
    FollowOwnerController,
    step_from_snapshot,
)
from parcel_robot.navigation.owner_prediction import PredictedPath

# ---------------------------------------------------------------------------
# The canned lines.  One sentence each, honest about what the robot knows.
# ---------------------------------------------------------------------------
#: The owner's OFFLINE FLOOR, in the owner's own words (2026-08-24 directive).
#: Said when the hosted lane is unreachable AND Follow has passed its enable
#: gate.
OFFLINE_FOLLOW_LINE = (
    "Sorry but I am currently offline so all I can do is follow you "
    "until we are connected to the internet."
)
#: The same floor before the box-day identity gate has passed — F5's "ship
#: floor until the gate passes = local STOP + HOLD + the canned line".
OFFLINE_HOLD_LINE = (
    "Sorry but I am currently offline, so all I can do is hold still "
    "until we are connected to the internet."
)
#: Two plausible owners.  Says the ambiguity, does not name a winner.
AMBIGUOUS_OWNER_LINE = "I can see two people who might be you, so I am holding still."
#: Track loss.  Says it is looking, does not claim it knows where you went.
LOST_OWNER_LINE = "I have lost track of you, so I am holding still and looking."
#: Evidence the spine refused.  Says WHICH evidence, without a number.
UNSYNCHRONIZED_EVIDENCE_LINE = (
    "I cannot line up what I see with what I range, so I am holding still."
)
#: A3's latch.  Follow inherits it; it never argues with it.
LATCHED_LINE = "I am not sure where I am any more, so I am holding still."

# ---------------------------------------------------------------------------
# HOLD reasons.  A typed vocabulary, so a HOLD can say what went wrong.
# ---------------------------------------------------------------------------
HOLD_NONE = ""
HOLD_NO_SNAPSHOT = "no_snapshot"
HOLD_UNSYNCHRONIZED = "unsynchronized_owner_evidence"
HOLD_LATCHED = "localization_latched"
HOLD_AMBIGUOUS = "owner_ambiguous"
HOLD_LOST = "owner_lost"

#: The holds that VETO the controller — the ones where asking the controller
#: for a command would mean guessing.  ``HOLD_LOST`` is deliberately NOT here:
#: the controller already answers a lost owner with a zero command and the
#: state string the runtime's reacquisition route keys on, so vetoing it would
#: replace a working route with a second one.
FOLLOW_HOLD_VETOES: frozenset[str] = frozenset(
    {"unsynchronized_owner_evidence", "localization_latched", "owner_ambiguous"}
)

HOLD_LINES: dict[str, str] = {
    HOLD_NO_SNAPSHOT: UNSYNCHRONIZED_EVIDENCE_LINE,
    HOLD_UNSYNCHRONIZED: UNSYNCHRONIZED_EVIDENCE_LINE,
    HOLD_LATCHED: LATCHED_LINE,
    HOLD_AMBIGUOUS: AMBIGUOUS_OWNER_LINE,
    HOLD_LOST: LOST_OWNER_LINE,
}

#: Named sync refusals, so a caller can key on them instead of on a substring.
REASON_MIXED_EPOCH = "owner_range:mixed_epoch"
REASON_CAPTURE_SKEW = "owner_range:capture_skew"
REASON_OWNER_STALE = "owner:stale"
REASON_SCAN_STALE = "scan:stale"


def owner_range_sync_reasons(snapshot: NavigationSnapshotV2) -> tuple[str, ...]:
    """Every reason this snapshot's owner target may not authorize a follow step.

    Order is deliberate and is the order a reader needs: the assembler's own
    verdict first (it saw every channel, this function sees two), then the
    Follow-specific pair check.  A non-empty tuple is a refusal; it is never
    advisory, and no caller in this module may pick a subset of it.
    """

    reasons: list[str] = list(snapshot.health_reasons)
    owner = snapshot.owner.header
    scan = snapshot.traversability.header
    if owner.process_epoch != scan.process_epoch:
        reasons.append(REASON_MIXED_EPOCH)
    # DERIVED, not chosen: the tighter of the two producers' OWN declared TTLs.
    # A pair whose captures are further apart than the shorter-lived of them
    # cannot be one look at one world, whatever either sample says about
    # itself.
    bound_ns = min(owner.max_age_ns, scan.max_age_ns)
    if abs(owner.capture_monotonic_ns - scan.capture_monotonic_ns) > bound_ns:
        reasons.append(REASON_CAPTURE_SKEW)
    if owner.transport_age_ns > owner.max_age_ns:
        reasons.append(REASON_OWNER_STALE)
    if scan.transport_age_ns > scan.max_age_ns:
        reasons.append(REASON_SCAN_STALE)
    seen: dict[str, None] = {}
    for reason in reasons:
        seen.setdefault(reason, None)
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class OfflineFloor:
    """What the dog can still do, and the one sentence it says about it.

    ``stop_available`` is a constant True and is carried anyway, because the
    loss-class policy's own wording is "every rung: independent local STOP" and
    a floor record that did not state it would invite the question.
    """

    line: str
    follow_available: bool
    stop_available: bool = True
    hold_available: bool = True


def offline_floor(*, connected: bool, follow_commissioned: bool) -> OfflineFloor:
    """The offline floor's SHAPE, from the two facts that decide it.

    ``follow_commissioned`` is the box-day identity gate's verdict (F5: "the
    owner's floor is the target; the enable is gated").  It is False on every
    host that has not run that study — which is every host today — and this
    function is where that False turns into the honest sentence instead of
    into a silently missing capability.
    """

    if connected:
        return OfflineFloor(line="", follow_available=follow_commissioned)
    if follow_commissioned:
        return OfflineFloor(line=OFFLINE_FOLLOW_LINE, follow_available=True)
    return OfflineFloor(line=OFFLINE_HOLD_LINE, follow_available=False)


@dataclass(frozen=True, slots=True)
class FollowComposeDecision:
    """One composed follow tick: the controller's decision plus the HOLD verdict."""

    decision: FollowDecision
    hold: str = HOLD_NONE
    line: str = ""
    reasons: tuple[str, ...] = ()
    #: Seconds left in the reacquisition window, or ``None`` when not holding
    #: for loss.  Zero means the window has closed and the caller's own
    #: owner-search route owns what happens next.
    reacquire_remaining_s: float | None = None

    @property
    def holding(self) -> bool:
        return self.hold != HOLD_NONE

    @property
    def command(self) -> VelocityCommand:
        return self.decision.command


def _hold_decision(follower: FollowOwnerController, hold: str, owner_id: str) -> FollowDecision:
    """A zero command wearing the controller's own decision shape.

    Built by hand rather than by asking the controller for one, because the
    point of a HOLD is that the controller was NOT consulted: an ambiguous or
    unsynchronized frame must not reach its motion history, or the next
    confident frame inherits a heading estimated from a person who may not be
    the owner.
    """

    return FollowDecision(
        state="holding",
        command=VelocityCommand(),
        reason=hold,
        owner_id=owner_id or None,
        mode=follower.mode,
    )


class FollowComposer:
    """Drives :class:`FollowOwnerController` from stamped snapshots.

    Stateful in exactly one respect — when the owner was last confirmed — and
    that state exists so the reacquisition window can be reported rather than
    guessed.  Everything else is a pure function of the snapshot in hand.

    Thread-safety is the caller's, deliberately: the runtime already drives
    Follow from one control-loop thread and holds its own lock around the
    decision it publishes.  Adding a lock here would be a second answer to a
    question the loop has already answered, and the DEC program's rule is that
    a new lock needs an r24 port with anti-vacuity floors — this needs neither
    because it takes none.
    """

    def __init__(self, follower: FollowOwnerController, *, reacquire_window_s: float) -> None:
        window = float(reacquire_window_s)
        if not math.isfinite(window) or window <= 0.0:
            raise ValueError("reacquire_window_s must be positive and finite")
        self.follower = follower
        self.reacquire_window_s = window
        self._last_confirmed_s: float | None = None

    @property
    def last_confirmed_s(self) -> float | None:
        return self._last_confirmed_s

    def reset(self) -> None:
        """Forget the reacquisition clock; the follower's own state is its own."""

        self._last_confirmed_s = None

    def step(
        self,
        snapshot: NavigationSnapshotV2 | None,
        now: float,
        *,
        prediction: PredictedPath | None = None,
    ) -> FollowComposeDecision:
        """One composed follow tick.  Strictest verdict first, and it wins."""

        if snapshot is None:
            return self._hold(HOLD_NO_SNAPSHOT, "", ())
        owner_id = snapshot.owner.owner_id
        reasons = owner_range_sync_reasons(snapshot)
        if reasons:
            return self._hold(HOLD_UNSYNCHRONIZED, owner_id, reasons)
        # A3's latch, inherited and never argued with.  It is checked AFTER the
        # evidence join and BEFORE anything about the owner, because a body
        # that does not know where it is may not translate toward anybody —
        # NAV-CORE refuter 4b measured 824/840 HEALTHY ticks after a kidnap.
        if snapshot.localization.motion_latched:
            return self._hold(HOLD_LATCHED, owner_id, ("localization:motion_latched",))
        owner = snapshot.owner
        if owner.ambiguous:
            detail = f"owner:ambiguous:{owner.ambiguity_reason}"
            return self._hold(
                HOLD_AMBIGUOUS,
                owner_id,
                (detail if owner.ambiguity_reason else "owner:ambiguous",),
            )
        if owner.lost:
            # The reacquisition clock is NOT restarted here: the window runs
            # from the last CONFIRMED sighting, so a loss that persists across
            # ticks keeps counting down instead of resetting itself forever.
            return self._hold(HOLD_LOST, owner_id, ("owner:lost",), now=now)
        self._last_confirmed_s = now
        decision = step_from_snapshot(self.follower, snapshot, now, prediction=prediction)
        return FollowComposeDecision(decision=decision)

    def _hold(
        self,
        hold: str,
        owner_id: str,
        reasons: tuple[str, ...],
        *,
        now: float | None = None,
    ) -> FollowComposeDecision:
        remaining: float | None = None
        if hold == HOLD_LOST and now is not None:
            if self._last_confirmed_s is None:
                remaining = self.reacquire_window_s
            else:
                remaining = max(0.0, self.reacquire_window_s - (now - self._last_confirmed_s))
        return FollowComposeDecision(
            decision=_hold_decision(self.follower, hold, owner_id),
            hold=hold,
            line=HOLD_LINES.get(hold, ""),
            reasons=reasons,
            reacquire_remaining_s=remaining,
        )


def hold_command(decision: FollowDecision) -> FollowDecision:
    """Force one decision to a zero command, keeping its reason readable.

    Exposed for a caller that already has a :class:`FollowDecision` in hand
    (the runtime's telemetry path) and needs the HOLD shape without re-running
    the controller.
    """

    return replace(decision, command=VelocityCommand(), state="holding")


__all__ = [
    "AMBIGUOUS_OWNER_LINE",
    "FOLLOW_HOLD_VETOES",
    "HOLD_AMBIGUOUS",
    "HOLD_LATCHED",
    "HOLD_LINES",
    "HOLD_LOST",
    "HOLD_NONE",
    "HOLD_NO_SNAPSHOT",
    "HOLD_UNSYNCHRONIZED",
    "LATCHED_LINE",
    "LOST_OWNER_LINE",
    "OFFLINE_FOLLOW_LINE",
    "OFFLINE_HOLD_LINE",
    "REASON_CAPTURE_SKEW",
    "REASON_MIXED_EPOCH",
    "REASON_OWNER_STALE",
    "REASON_SCAN_STALE",
    "UNSYNCHRONIZED_EVIDENCE_LINE",
    "FollowComposeDecision",
    "FollowComposer",
    "OfflineFloor",
    "hold_command",
    "offline_floor",
    "owner_range_sync_reasons",
]
