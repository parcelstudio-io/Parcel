"""Pure nominal-stop decay: the pre-6bd945d emergency semantics, isolated.

Card J-A. This module owns no wiring and no policy. It reproduces exactly one
thing: the accel-limited stop that ``SCurveVelocityShaper.step(emergency=True)``
performed before commit ``6bd945d`` (card P0-A replaced it with an instant exact
zero for hard stops, which is the correct and shipped hard-stop contract and is
NOT changed by this module).

The severity split that consumes this lives in ``core.hard_stop`` /
``runtime``: EMERGENCY stops keep P0-A's instant zero; a NOMINAL zero intent may
decay along this ramp instead, but only behind a default-OFF flag and only after
the untouched reactive gate has disposed of every candidate this module
produces (see ``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §3.2).

Two functions, both total and non-raising:

* :func:`nominal_stop_step` — one per-axis accel-limited step toward zero.
  The decay RATE is derived from the shaper's own limits triple
  (``MotionShapingConfig.limits()``); nothing here restates an acceleration.
* :func:`enforce_monotone_stop` — the boundary check. Any magnitude increase,
  sign flip, malformed shape, or non-finite value returns ``None``, which
  obliges the caller to fall back to the untouched HARD_STOP path.

Fail-closed convention: :func:`nominal_stop_step` never signals failure by
raising and never returns a value larger in magnitude than its input — a
malformed input collapses to the exact all-axis zero, which is the terminal
value of the ramp it implements and therefore always the safe answer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from parcel_robot.navigation.velocity_shaping import ShaperLimits, _move_toward

#: The all-axis zero triple: the ramp's terminal value and its fail-closed answer.
ZERO_STEP: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _finite_triple(values: object) -> tuple[float, float, float] | None:
    """Return ``values`` as a 3-tuple of floats, or ``None`` if malformed."""

    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        return None
    if len(values) != 3:
        return None
    out: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        out.append(number)
    return (out[0], out[1], out[2])


def nominal_stop_step(
    velocity: Sequence[float],
    accel_limits: Sequence[ShaperLimits],
    dt_s: float,
) -> tuple[float, float, float]:
    """Advance ``velocity`` one tick toward zero at each axis' accel limit.

    Exactly ``_move_toward(v, 0.0, limits.max_accel * dt_s)`` per axis — the
    symbol is imported from the shaper rather than re-implemented so the two
    can never drift apart.

    Malformed velocity, malformed limits, or ``dt_s`` non-finite/non-positive
    fail closed to :data:`ZERO_STEP`.
    """

    current = _finite_triple(velocity)
    if current is None:
        return ZERO_STEP
    if isinstance(accel_limits, (str, bytes)) or not isinstance(accel_limits, Sequence):
        return ZERO_STEP
    if len(accel_limits) != 3:
        return ZERO_STEP
    if not isinstance(dt_s, (int, float)) or isinstance(dt_s, bool):
        return ZERO_STEP
    dt = float(dt_s)
    if not math.isfinite(dt) or dt <= 0.0:
        return ZERO_STEP

    stepped: list[float] = []
    for value, limits in zip(current, accel_limits):
        if not isinstance(limits, ShaperLimits):
            return ZERO_STEP
        distance = limits.max_accel * dt
        if not math.isfinite(distance) or distance <= 0.0:
            return ZERO_STEP
        stepped.append(_move_toward(value, 0.0, distance))
    return (stepped[0], stepped[1], stepped[2])


def enforce_monotone_stop(
    previous: Sequence[float],
    candidate: Sequence[float],
) -> tuple[float, float, float] | None:
    """Return ``candidate`` when it is a legal continuation of a stop.

    Legal means, per axis: finite, magnitude not greater than ``previous``, and
    the sign preserved or collapsed to zero. Anything else — including a
    malformed shape on either side — returns ``None``; the caller must then
    take the untouched HARD_STOP path (exact zero plus its reset obligations).
    """

    prior = _finite_triple(previous)
    proposed = _finite_triple(candidate)
    if prior is None or proposed is None:
        return None
    for was, now in zip(prior, proposed):
        if abs(now) > abs(was):
            return None
        if was * now < 0.0:
            return None
    return proposed


__all__ = ["ZERO_STEP", "enforce_monotone_stop", "nominal_stop_step"]
