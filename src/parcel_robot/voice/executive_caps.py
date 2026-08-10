"""Map closed intents to executive / CommandArbiter caps (K6).

Caps never author raw velocity. ``stop`` is a hard cancel; ``faster``/``slower``
adjust a bounded pace scale applied by the arbiter gate; ``come`` yields a
PlanSketch for admission; ``goal-amend`` only signals revision (no motion).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from parcel_robot.brain.plan_sketch import PlanSketch

from .closed_intents import ClosedIntent
from .local_plans import sketch_come

# Pace scale bounds applied at the CommandArbiter / submit_motion seam.
PACE_MIN = 0.35
PACE_MAX = 1.25
PACE_STEP = 0.15
PACE_DEFAULT = 1.0


@dataclass(frozen=True, slots=True)
class CapDirective:
    intent: ClosedIntent
    kind: str
    reply: str
    pace_scale: float | None = None
    sketch: PlanSketch | None = None
    suspend: bool = False
    resume: bool = False
    emergency_stop: bool = False
    goal_amend: bool = False


def resolve_cap(intent: ClosedIntent, *, current_pace: float = PACE_DEFAULT) -> CapDirective:
    if not isinstance(intent, ClosedIntent):
        raise TypeError("intent must be ClosedIntent")
    pace = _clamp_pace(current_pace)

    if intent is ClosedIntent.STOP:
        return CapDirective(
            intent=intent,
            kind="stop",
            reply="Stopping.",
            emergency_stop=True,
        )
    if intent is ClosedIntent.PAUSE:
        return CapDirective(
            intent=intent,
            kind="pause",
            reply="Okay—I'll pause the current task.",
            suspend=True,
        )
    if intent is ClosedIntent.RESUME:
        return CapDirective(
            intent=intent,
            kind="resume",
            reply="Okay—resuming with a fresh observation.",
            resume=True,
        )
    if intent is ClosedIntent.FASTER:
        return CapDirective(
            intent=intent,
            kind="pace",
            reply="Okay—I'll pick up the pace a little within safe limits.",
            pace_scale=_clamp_pace(pace + PACE_STEP),
        )
    if intent is ClosedIntent.SLOWER:
        return CapDirective(
            intent=intent,
            kind="pace",
            reply="Okay—I'll slow down.",
            pace_scale=_clamp_pace(pace - PACE_STEP),
        )
    if intent is ClosedIntent.COME:
        return CapDirective(
            intent=intent,
            kind="admit_plan",
            reply="Okay—I'll come to you safely.",
            sketch=sketch_come(),
        )
    if intent is ClosedIntent.GOAL_AMEND:
        return CapDirective(
            intent=intent,
            kind="goal_amend",
            reply="Okay—I'll revise the current goal.",
            goal_amend=True,
        )
    raise ValueError(f"unhandled closed intent: {intent}")


class PaceCap:
    """Bounded speed-scale owner for CommandArbiter-facing caps."""

    def __init__(self, scale: float = PACE_DEFAULT) -> None:
        self._scale = _clamp_pace(scale)

    @property
    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float) -> float:
        self._scale = _clamp_pace(scale)
        return self._scale

    def scale_command(self, vx: float, vy: float, vyaw: float) -> tuple[float, float, float]:
        s = self._scale
        return (float(vx) * s, float(vy) * s, float(vyaw) * s)


def _clamp_pace(value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError("pace scale must be numeric")
    number = float(value)
    if math.isnan(number):
        raise ValueError("pace scale must be finite")
    return max(PACE_MIN, min(PACE_MAX, number))


__all__ = [
    "PACE_DEFAULT",
    "PACE_MAX",
    "PACE_MIN",
    "PACE_STEP",
    "CapDirective",
    "PaceCap",
    "resolve_cap",
]
