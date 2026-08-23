# ---- CARD AWARE-1 (scrum/20260823/task_4) ---------------------------------
"""Periodic gentle yaw sweep, so an idle robot keeps looking around.

The owner's directive: *the robot should periodically turn its head to stay
aware of its surroundings — there may be people around.*

WHY THIS IS A BODY YAW AND NOT A HEAD GESTURE
---------------------------------------------
``expression.py`` already has a ``look_around`` idle gesture, and it is not
this. It produces an ``ExpressiveOffsets.head_yaw_rad``, and that field
reaches exactly two places: the telemetry dict and the panel
(``expression.py:78-126``). No actuator consumes it, and a Go2 has no head
that yaws independently of its body anyway. A gesture that moves no sensor
cannot make the robot aware of anything. Staying aware means turning the
BODY, which means a velocity proposal, which means the ordinary
proposal/arbitration/safety path — and nothing else.

WHAT THIS MODULE IS ALLOWED TO BE
---------------------------------
A **proposer**, in ``patrol/mission.py``'s sense and with its lesson: a
behaviour that spends the body's time commanding things the safety gate will
refuse has not bought motion, it has bought refusals (E2-D2, MOVE-1). So the
bounds here are thresholds a proposal is *withheld* at, never authority it is
granted. The reactive gate, the TTC brake and the input-health join are
untouched and remain the only things that refuse.

:class:`AwarenessProposal` carries **no translation field at all**. That is
deliberate and structural: this behaviour cannot propose ``vx``/``vy`` by any
bug, typo or future edit, because there is nowhere to put them.

THE R28 TABLE IS IN HERE
------------------------
:func:`awareness_yaw_permitted` is the executable half of
``scrum/20260823/task_4/R28_AXIS_TABLE.md``. It is an ALLOW-LIST: an input
class nobody has classified yet suppresses the sweep. It is strictly narrower
than what the gate permits — the gate preserves yaw through EVERY ``HOLD``
(``runtime.py:14050``), and this says yes to three named ``(input, class)``
pairs and nothing else.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from parcel_robot.core.input_health import (
    HealthAction,
    InputHealthVerdict,
    RequiredInput,
)

#: The base-config section this behaviour reads.
#:
#: NOT PRESENT IN ``configs/robot.yaml`` TODAY, and that is a blocked card
#: deliverable rather than an oversight: the base config is SHA-locked
#: (``evals/companion/embodied_plan_v1/manifest.json`` ``robot_config``,
#: ``tests/test_hw5_physical_profile.py:69``), and moving it needs an owner
#: authorised re-pin. Card PROX-1 hit the same wall this wave and shipped its
#: table as code constants for the same reason. :func:`awareness_limits_from_config`
#: reads this section the moment it exists and needs no code change then.
AWARENESS_CONFIG_KEY: Final[str] = "awareness"

#: THE R28 ALLOW-LIST: the exact ``(input, class)`` pairs a discretionary
#: sensing yaw may be proposed under. Anything absent from this set forbids the
#: sweep, which is rule E and is why this is a set of pairs rather than a set
#: of exclusions. Each entry earns its place:
#:
#: * ``scan``/``missing`` and ``scan``/``stale`` — rule B. Turning is what
#:   re-acquires a camera cone, and the body stays measurable while it does.
#: * ``controller_feedback``/``missing`` — rule D's careful half, and it is
#:   MEASURED rather than reasoned. A stationary runtime publishes no motion
#:   state at all: the feedback buffer is filled from the observation inside
#:   ``_dispatch_active``/``_collision_safe``, both of which need a command to
#:   run. So feedback appears one tick AFTER the first command, and a rule that
#:   demanded it beforehand would deadlock the behaviour permanently — the
#:   sweep would need motion to be allowed to propose motion. An absent
#:   feedback on a robot at rest is the expected state, not a fault.
#:
#: ``controller_feedback``/``stale`` is deliberately NOT here, and that is the
#: other half of rule D: stale means the controller ANSWERED and then stopped,
#: which on a robot mid-sweep is exactly the open-loop turn worth refusing.
#: Every ``pose`` class is absent too — rule C, an arc you cannot measure
#: cannot be bounded.
PERMITTED_HOLD_FAULTS: Final[frozenset[tuple[RequiredInput, str]]] = frozenset(
    {
        (RequiredInput.SCAN, "missing"),
        (RequiredInput.SCAN, "stale"),
        (RequiredInput.CONTROLLER_FEEDBACK, "missing"),
    }
)


@dataclass(frozen=True)
class AwarenessProposal:
    """One tick's worth of sensing yaw. Yaw only, by construction."""

    vyaw: float
    reason: str = "awareness_sweep"

    def __post_init__(self) -> None:
        if isinstance(self.vyaw, bool) or not isinstance(self.vyaw, (int, float)):
            raise TypeError("AwarenessProposal.vyaw must be a number")
        if not math.isfinite(float(self.vyaw)):
            raise ValueError("AwarenessProposal.vyaw must be finite")


@dataclass(frozen=True)
class AwarenessLimits:
    """Bounds. Every one is a threshold a proposal is withheld at.

    None of these is a safety device and none may ever be read as one.
    """

    #: DEFAULT OFF. The shipped ``configs/robot.yaml`` is an input to the
    #: digest-pinned ``embodied_plan_v1`` eval (997 simulator steps, minimum
    #: clearance 0.883147 m), and that eval has idle stretches. A robot that
    #: turned itself during them would move a pinned row silently, which is
    #: exactly the class of baseline drift this repo's re-pin protocol exists
    #: to prevent. Flipping this default is a one-line change plus a
    #: re-measured eval row; the STATUS names it.
    enabled: bool = False
    #: How long the robot must have been continuously idle and permitted
    #: before a sweep starts, and the minimum gap between sweeps.
    idle_period_s: float = 25.0
    #: TOTAL swept angle for one sweep, out and back. The peak excursion from
    #: the starting heading is therefore half of this. 1.4 rad total = about
    #: 40 degrees each way, which points a ~87 degree D455 cone at roughly
    #: 170 degrees of the room without the robot ever losing its heading.
    sweep_arc_rad: float = 1.4
    #: Yaw rate while sweeping. Well under the patrol's own ``turn_vyaw``
    #: (0.8, ``patrol/mission.py:157``) because a sensing turn is a look, not
    #: an avoidance manoeuvre — and a detector needs the scene to hold still
    #: long enough to fire.
    sweep_vyaw: float = 0.35

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("AwarenessLimits.enabled must be a bool")
        for name in ("idle_period_s", "sweep_arc_rad", "sweep_vyaw"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"AwarenessLimits.{name} must be a number")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"AwarenessLimits.{name} must be positive and finite")
        # A sweep wider than a half turn is not a look, it is a spin, and the
        # swept-volume argument the R28 table's rule B rests on gets weaker the
        # further the body travels from the heading it was commissioned at.
        if float(self.sweep_arc_rad) > math.pi:
            raise ValueError(
                "AwarenessLimits.sweep_arc_rad must not exceed pi radians "
                f"(got {self.sweep_arc_rad}) — a sensing sweep is a look, not a spin"
            )
        # The patrol's avoidance turn is the fastest rotation any proposer in
        # this repo asks for. A "gentle" sweep that outran it would be a
        # contradiction in terms.
        if float(self.sweep_vyaw) > 0.8:
            raise ValueError(
                "AwarenessLimits.sweep_vyaw must not exceed the patrol's "
                f"turn_vyaw of 0.8 rad/s (got {self.sweep_vyaw})"
            )

    @property
    def sweep_duration_s(self) -> float:
        """How long one complete out-and-back sweep takes."""

        return float(self.sweep_arc_rad) / float(self.sweep_vyaw)


def awareness_limits_from_config(
    section: Mapping[str, Any] | None,
) -> AwarenessLimits:
    """Read the ``awareness`` config section; absent keys keep the default.

    Every value goes through :class:`AwarenessLimits`' validator, so a typo'd
    number refuses at boot rather than reading as "no bound".
    """

    if not section:
        return AwarenessLimits()
    if not isinstance(section, Mapping):
        raise TypeError(
            f"{AWARENESS_CONFIG_KEY!r} configuration must be a mapping "
            f"(got {type(section).__name__})"
        )
    defaults = AwarenessLimits()
    unknown = set(section) - {
        "enabled",
        "idle_period_s",
        "sweep_arc_rad",
        "sweep_vyaw",
    }
    if unknown:
        # Fail closed on spelling. A key nothing reads is indistinguishable
        # from a key nobody wrote, which is how `minimum_confidenc` booted at
        # the wrong value (config.py's own lesson).
        raise ValueError(
            f"unknown {AWARENESS_CONFIG_KEY!r} configuration keys: "
            f"{sorted(unknown)!r}"
        )

    def _number(name: str, fallback: float) -> float:
        if name not in section:
            return fallback
        value = section[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(
                f"{AWARENESS_CONFIG_KEY}.{name} must be a number (got {value!r})"
            )
        return float(value)

    enabled = section.get("enabled", defaults.enabled)
    if not isinstance(enabled, bool):
        raise TypeError(
            f"{AWARENESS_CONFIG_KEY}.enabled must be a bool (got {enabled!r})"
        )
    return AwarenessLimits(
        enabled=enabled,
        idle_period_s=_number("idle_period_s", defaults.idle_period_s),
        sweep_arc_rad=_number("sweep_arc_rad", defaults.sweep_arc_rad),
        sweep_vyaw=_number("sweep_vyaw", defaults.sweep_vyaw),
    )


def awareness_yaw_permitted(
    verdict: InputHealthVerdict | None,
    *,
    latched: bool = False,
) -> bool:
    """THE R28 TABLE, executable. May a *discretionary* sensing yaw be proposed?

    See ``scrum/20260823/task_4/R28_AXIS_TABLE.md`` §2. Strictly narrower than
    what the gate permits, and an allow-list so an unclassified input class
    defaults to "no".

    * rule A — any ``LATCHED_STOP`` (or an already-set runtime latch) → no.
    * rules B–D — every fault must be in :data:`PERMITTED_HOLD_FAULTS`, which
      carries the reason each pair is or is not there.
    * rule E — anything else, including an absent verdict → no.
    """

    if latched:
        return False
    if not isinstance(verdict, InputHealthVerdict):
        return False
    if verdict.action is HealthAction.ALLOW:
        # ALLOW is `max(faults, default=ALLOW)`, so it carries no faults at
        # all. Asserting it rather than assuming it costs nothing.
        return not verdict.faults
    if verdict.action is not HealthAction.HOLD:
        return False
    for fault in verdict.faults:
        if fault.action is not HealthAction.HOLD:
            return False
        if (fault.required_input, fault.reason) not in PERMITTED_HOLD_FAULTS:
            return False
    return True


class AwarenessSweep:
    """The cadence and the bounded arc. Pure: no clock, no I/O, no lock.

    Driven by ``step(now, idle=..., yaw_permitted=...)``; the caller owns the
    clock and both predicates, which is what makes the whole behaviour
    decidable in a unit test with no runtime and no simulator.

    One sweep is OUT AND BACK — half the arc one way, half the other — so the
    robot ends a sweep pointing where it started. A sweep that only ever went
    one way would leave an idle robot slowly rotating away from its heading
    forever, which is a different behaviour and not the one that was asked
    for.
    """

    def __init__(self, limits: AwarenessLimits | None = None) -> None:
        self.limits = AwarenessLimits() if limits is None else limits
        self._ready_at: float | None = None
        self._swept_rad: float = 0.0
        self._last_step_at: float | None = None
        self._sweeping: bool = False
        #: Which way the NEXT sweep starts; flips after each completed sweep.
        self._sign_seed: float = 1.0
        self.sweeps_started: int = 0
        self.sweeps_completed: int = 0

    @property
    def sweeping(self) -> bool:
        return self._sweeping

    @property
    def swept_rad(self) -> float:
        """Angle swept so far in the sweep in progress (0.0 when idle)."""

        return self._swept_rad

    def reset(self) -> None:
        """Abandon any sweep in progress and restart the cadence clock."""

        self._ready_at = None
        self._swept_rad = 0.0
        self._last_step_at = None
        self._sweeping = False

    def step(
        self,
        now: float,
        *,
        idle: bool,
        yaw_permitted: bool,
    ) -> AwarenessProposal | None:
        """One tick. ``None`` means "propose nothing", which is most ticks."""

        if isinstance(now, bool) or not isinstance(now, (int, float)):
            raise TypeError("AwarenessSweep.step now must be a number")
        if not math.isfinite(float(now)):
            raise ValueError("AwarenessSweep.step now must be finite")
        now = float(now)
        limits = self.limits

        if not limits.enabled or not idle or not yaw_permitted:
            # THE SUPPRESSION, and it abandons rather than pauses. A sweep that
            # resumed mid-arc after the reason it stopped went away would be a
            # robot finishing a gesture it started under different evidence.
            self.reset()
            return None

        if self._sweeping:
            elapsed = max(0.0, now - (self._last_step_at or now))
            self._last_step_at = now
            self._swept_rad += abs(limits.sweep_vyaw) * elapsed
            # THE BOUND, and it is a bound on the angle actually COMMANDED, not
            # on the angle already swept. A proposal issued now is held until
            # the next tick, so stopping at `swept >= arc` would command one
            # tick's worth PAST the arc every single sweep. This asks whether
            # issuing another tick would cross it, using the tick just observed
            # as the estimate of the next one — so the total commanded angle is
            # <= sweep_arc_rad, and no branch in this class can extend it.
            if self._swept_rad + abs(limits.sweep_vyaw) * elapsed >= limits.sweep_arc_rad:
                self.sweeps_completed += 1
                self._sweeping = False
                self._swept_rad = 0.0
                self._last_step_at = None
                self._ready_at = now + limits.idle_period_s
                # ROAM-1's alternation trick, and here for a measured reason:
                # a discrete tick cannot flip at exactly half the arc, so every
                # out-and-back leaves a residual of up to one tick's yaw in the
                # SAME direction. Unalternated, an idle robot would creep round
                # a few degrees per sweep and be facing somewhere else by
                # morning. Flipping the start direction makes consecutive
                # residuals cancel instead of accumulate.
                self._sign_seed = -self._sign_seed
                return None
            half = limits.sweep_arc_rad / 2.0
            sign = self._sign_seed if self._swept_rad < half else -self._sign_seed
            return AwarenessProposal(vyaw=limits.sweep_vyaw * sign)

        if self._ready_at is None:
            # First permitted tick of an idle stretch: start the clock. The
            # cadence is measured from when the robot BECAME idle, so a robot
            # that has just stopped doing something does not immediately turn.
            self._ready_at = now + limits.idle_period_s
            return None
        if now < self._ready_at:
            return None

        self._sweeping = True
        self._swept_rad = 0.0
        self._last_step_at = now
        self.sweeps_started += 1
        return AwarenessProposal(vyaw=limits.sweep_vyaw * self._sign_seed)


__all__ = [
    "AWARENESS_CONFIG_KEY",
    "PERMITTED_HOLD_FAULTS",
    "AwarenessLimits",
    "AwarenessProposal",
    "AwarenessSweep",
    "awareness_limits_from_config",
    "awareness_yaw_permitted",
]

# ---- END CARD AWARE-1 ------------------------------------------------------
