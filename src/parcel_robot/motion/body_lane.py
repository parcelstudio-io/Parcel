"""The 50 Hz body-intent lane: the composer, wired to the product.

CARD A9, productizing research H4 (``research/20260823/continuous-body-intent/``,
CONFIRMED: 49.5-49.95 Hz over 119,552 ticks, 0 gaps > 100 ms, e-stop to HOLD in
17.66 ms = 0.88 tick, locomotion byte-identical over 3,402 messages). H4's own
verdict recorded the gap this module closes: *"nothing in ``runtime.py``
constructs the composer — by design; wiring is card M1-3 BODY."*

WHERE IT SITS, AND WHY THAT IS THE WHOLE SAFETY ARGUMENT
--------------------------------------------------------
The lane is composed **beneath** the dispatch chain, never beside it. The
velocity it publishes is the one the chain already finalized:

    smoother -> input-health join -> A3 latch -> apply_reactive_safety
             -> TTC gate -> S-curve shaper -> finalize_command
             -> control_manager.set_target  ==>  runtime._last_sent
                                                      |
                                                      v
                                            BodyIntentLane.tick(...)

``_last_sent`` is assigned inside ``_dispatch_active`` immediately after
``finalize_command`` returned and the actuator accepted the value, so the lane
reads the OUTPUT of every gate and can only copy it. The composer has no
arithmetic that could produce a velocity (H4 row B7 proves that separately),
this lane never calls ``submit_motion``, ``set_target`` or the backend's
``move``, and the intent it publishes drives no actuator today: the two body
adapters (simulation, Go2 Sport) exist and neither is installed. So the worst
a defect in this file can do is publish a wrong *description* of what the
already-safe chain decided.

HOLD IS A COMMAND
-----------------
Every tick emits a :class:`~parcel_robot.contracts.body_intent.BodyIntentV1`.
When there is no authorized velocity the locomotion field is the ``HOLD``
singleton, not a zero velocity and not a missing message: "be still" is
something the dog is doing, and a body that infers stillness from silence
cannot tell a held stance from a dead publisher. H3's D7 note is the same point
from the other side — today's idle dog emits 36,000 exact zeros.

E-STOP
------
``emergency`` is forwarded to the composer, which snaps both axis limiters to
zero, forces HOLD, bumps its epoch once on the rising edge and publishes at
priority 100 — all inside the tick that saw the flag. The measured reference is
H4's 0.88 tick (17.66 ms at 50 Hz): the mechanism is same-tick, so the only
latency is when in the tick the flag arrived, which is why the bound is one
tick and not zero. The same flag terminates any running initiated behavior.

The lane holds no lock. It runs on the expression thread (50 Hz) and reads two
plain attributes owned by the control thread (10 Hz); both are immutable
values, and a torn read is impossible because neither is mutated in place.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..attention.drives import InitiativePolicy, InitiativeProposal
from ..attention.initiative import (
    NEUTRAL_OFFER,
    Admission,
    BodyOffer,
    InitiativeLimits,
    Terminal,
    ZeroTranslationLease,
)
from ..contracts.body_intent import HOLD, BodyIntentV1
from .body_composer import DEFAULT_LIMITS, BodyComposer, ComposerLimits
from .expression import ExpressiveOffsets

#: The lane's own cadence contract, from H4's B1 row: 20 Hz floor, no gap over
#: 100 ms. The runtime ticks it from the 50 Hz expression channel.
NOMINAL_TICK_HZ = 50.0
MAX_TICK_GAP_S = 0.100


@dataclass(frozen=True)
class BodyLaneConfig:
    """Knobs, all with shipped defaults. No new configuration file key.

    Deliberately constructed from its own defaults rather than from a config
    section: ``config.py`` is at its DEC-0 ceiling and every existing section
    validator refuses unknown keys by name, so a new knob costs a new
    whitelist entry somewhere. The lane is inert (it publishes a description,
    drives nothing), and initiative ships OFF in
    :class:`~parcel_robot.attention.initiative.InitiativeLimits`, so the
    shipped behaviour needs no switch. The card that turns initiative on owns
    introducing the key.
    """

    enabled: bool = True
    ttl_ms: int = 150
    style: str = "calm"
    breathing_hz: float = 0.25
    limits: ComposerLimits = DEFAULT_LIMITS


@dataclass(frozen=True, slots=True)
class LaneTick:
    """One published tick: the intent, plus what the lane did to produce it."""

    intent: BodyIntentV1
    offer: BodyOffer
    terminal: Terminal | None = None
    gap_s: float = 0.0
    yielded: bool = False


class BodyIntentLane:
    """Compose one body intent per tick, forever, and publish the latest."""

    def __init__(
        self,
        *,
        config: BodyLaneConfig | None = None,
        composer: BodyComposer | None = None,
        lease: ZeroTranslationLease | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or BodyLaneConfig()
        self.composer = composer or BodyComposer(
            limits=self.config.limits,
            ttl_ms=self.config.ttl_ms,
            breathing_hz=self.config.breathing_hz,
            style=self.config.style,
        )
        self.lease = lease if lease is not None else ZeroTranslationLease()
        self._monotonic = monotonic
        self._latest: BodyIntentV1 | None = None
        self._last_tick_s: float | None = None
        self.ticks = 0
        self.hold_ticks = 0
        self.emergency_ticks = 0
        self.yields = 0
        self.gaps_over_bound = 0
        self.max_gap_s = 0.0
        self.last_gap_s = 0.0

    # -- reads ---------------------------------------------------------------
    @property
    def latest(self) -> BodyIntentV1 | None:
        """The most recently composed intent, or ``None`` before the first tick."""

        return self._latest

    def snapshot(self) -> dict[str, object]:
        intent = self._latest
        return {
            "ticks": self.ticks,
            "hold_ticks": self.hold_ticks,
            "emergency_ticks": self.emergency_ticks,
            "yields": self.yields,
            "max_gap_s": round(self.max_gap_s, 4),
            "gaps_over_bound": self.gaps_over_bound,
            "bound_s": MAX_TICK_GAP_S,
            "seq": self.composer.seq,
            "epoch": self.composer.epoch,
            "intent": None if intent is None else intent.as_dict(),
            "initiative": self.lease.snapshot(self._last_tick_s or 0.0),
        }

    # -- initiative ----------------------------------------------------------
    def begin(
        self,
        proposal: InitiativeProposal,
        now_s: float,
        *,
        owner_active: bool = False,
        emergency: bool = False,
        gaze: tuple[float, float] | None = None,
        line: str = "",
    ) -> Admission:
        """Offer one drive proposal to the lease. Raises on a travelling one."""

        return self.lease.admit(
            proposal,
            now_s,
            owner_active=owner_active,
            emergency=emergency,
            gaze=gaze,
            line=line,
        )

    # -- the tick ------------------------------------------------------------
    def tick(
        self,
        *,
        offsets: ExpressiveOffsets,
        finalized_velocity: object | None,
        emergency: bool = False,
        owner_active: bool = False,
        now_s: float | None = None,
    ) -> LaneTick:
        """One 50 Hz tick. Never raises on a stale clock; always publishes.

        ``finalized_velocity`` is whatever the dispatch chain last handed the
        actuator — see the module docstring. ``None`` composes to HOLD, which
        is the honest answer when no producer owns motion.
        """

        now = float(self._monotonic() if now_s is None else now_s)
        if not math.isfinite(now):  # pragma: no cover - a clock that lies
            now = 0.0
        gap = 0.0 if self._last_tick_s is None else max(0.0, now - self._last_tick_s)
        self._last_tick_s = now

        lease_tick = self.lease.tick(now, owner_active=owner_active, emergency=emergency)
        offer = lease_tick.offer if lease_tick.running else NEUTRAL_OFFER
        yielded = bool(
            lease_tick.terminal is not None and (owner_active or emergency)
        )

        merged = offsets
        if offer.posture != (0.0, 0.0):
            merged = ExpressiveOffsets(
                body_height_m=offsets.body_height_m + offer.posture[0],
                body_pitch_rad=offsets.body_pitch_rad + offer.posture[1],
                head_yaw_rad=offsets.head_yaw_rad,
                head_pitch_rad=offsets.head_pitch_rad,
            )
        intent = self.composer.compose(
            now_s=now,
            finalized_velocity=finalized_velocity,
            offsets=merged,
            gaze_target=offer.gaze,
            style=offer.style if lease_tick.running else None,
            emergency=bool(emergency),
        )

        self.ticks += 1
        self.last_gap_s = gap
        self.max_gap_s = max(self.max_gap_s, gap)
        if self.ticks > 1 and gap > MAX_TICK_GAP_S:
            self.gaps_over_bound += 1
        if intent.locomotion is HOLD:
            self.hold_ticks += 1
        if emergency:
            self.emergency_ticks += 1
        if yielded:
            self.yields += 1
        self._latest = intent
        return LaneTick(
            intent=intent,
            offer=offer,
            terminal=lease_tick.terminal,
            gap_s=gap,
            yielded=yielded,
        )


def install_body_lane(
    *,
    enabled: bool = True,
    initiative: InitiativeLimits | None = None,
    policy: InitiativePolicy | None = None,
    quiet: Callable[[float], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> BodyIntentLane | None:
    """Build the lane a runtime installs, or ``None`` when it is switched off.

    Never raises for a configuration reason: a body that cannot describe itself
    must not stop a robot from booting, and the caller treats ``None`` as
    "no lane", exactly as A7's ear and A8's tracker do.
    """

    if not enabled:
        return None
    lease = ZeroTranslationLease(
        policy=policy or InitiativePolicy(),
        limits=initiative or InitiativeLimits(),
        quiet=quiet,
    )
    return BodyIntentLane(lease=lease, monotonic=monotonic)


__all__: Sequence[str] = (
    "MAX_TICK_GAP_S",
    "NOMINAL_TICK_HZ",
    "BodyIntentLane",
    "BodyLaneConfig",
    "LaneTick",
    "install_body_lane",
)
