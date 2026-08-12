"""Person keepout geometry DERIVED from the reactive safety gate (card D15-A).

Why this module exists
----------------------
D-15 (``nav-object_goal-D-15-109547e2``) deadlocked after the owner-authorized
``person_stop_m`` 1.0 -> 1.2 retune: an undeclared stationary bystander sits
1.2632 m of clearance from the planned route, the gate's *predictive* person
stop at the cruise speed is 1.3020 m, and
:func:`~parcel_robot.navigation.reactive_safety.apply_reactive_safety`
therefore hard-stopped translation on every tick — invisibly to the planner,
which kept re-planning the same straight route until the step budget expired
(``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §1).

The retune is correct and is not touched here. What this module supplies is the
missing *proposer-side* geometry: where a compliant route may not go, and how
fast a proposal may ask to move so the UNMODIFIED gate approves it.

Derivation, not restatement
---------------------------
Every number below is read off a live
:class:`~parcel_robot.navigation.reactive_safety.ReactiveSafetyPolicy`
instance. This module contains **no** safety literal of its own: a threshold
written here would be a second copy of the gate's authority and would silently
fork the first time the policy is retuned again — which is exactly the failure
class D-15 is. :func:`gate_vetoes` evaluates the gate's own inequality
verbatim, so "would the gate stop this?" is answered by the gate's expression
rather than by an approximation of it.

Nothing in this module gates, stops, or clamps anything by itself. It PROPOSES;
``apply_reactive_safety`` remains the single disposer, unchanged and running
after every consumer of this module.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy

__all__ = [
    "compliant_speed",
    "gate_vetoes",
    "keepout_cost_field",
    "keepout_radius_m",
    "predictive_person_stop_m",
]


def _speed_magnitude(speed_mps: float | tuple[float, float]) -> float:
    """The speed the gate compares against: ``math.hypot(command.vx, command.vy)``.

    Accepts either a scalar magnitude or the ``(vx, vy)`` pair, because the two
    call sites that matter differ: the gate holds a command, a route-planning
    consumer holds a scalar cruise speed.
    """

    if isinstance(speed_mps, tuple):
        vx, vy = speed_mps
        value = math.hypot(float(vx), float(vy))
    else:
        value = abs(float(speed_mps))
    if not math.isfinite(value):
        raise ValueError("speed must be finite")
    return value


def predictive_person_stop_m(
    policy: ReactiveSafetyPolicy,
    speed_mps: float | tuple[float, float],
) -> float:
    """The gate's predictive person-stop threshold at ``speed_mps`` (metres).

    Mirrors ``apply_reactive_safety``'s expression exactly::

        policy.person_stop_m + math.hypot(command.vx, command.vy) * policy.reaction_time_s

    Clearance convention is the gate's:
    :data:`~parcel_robot.authority.CLEARANCE_CONVENTION`, base-center to person
    surface. Callers must not re-add a footprint.
    """

    return policy.person_stop_m + _speed_magnitude(speed_mps) * policy.reaction_time_s


def gate_vetoes(
    clearance_m: float,
    speed_mps: float | tuple[float, float],
    *,
    policy: ReactiveSafetyPolicy,
) -> bool:
    """Evaluate the gate's veto inequality verbatim (``<=``; adjudication #5).

    ``True`` means: were a person at ``clearance_m`` in the direction of travel,
    ``apply_reactive_safety`` would ``_stop_translation`` this command. The
    boundary belongs to the gate — equality vetoes — which is why
    :func:`compliant_speed` returns a supremum that is *strictly* below it.
    """

    clearance = float(clearance_m)
    if not math.isfinite(clearance):
        raise ValueError("clearance_m must be finite")
    return clearance <= predictive_person_stop_m(policy, speed_mps)


def keepout_radius_m(
    policy: ReactiveSafetyPolicy,
    speed_mps: float | tuple[float, float],
) -> float:
    """Radius of the veto ring around a person's CENTRE, at ``speed_mps``.

    ``person_stop_m + v·reaction_time_s`` is a *clearance* (surface-referenced);
    a planner works in centres, so the person's own envelope
    (``owner_collision_envelope_m`` — the same envelope the gate subtracts when
    it converts the owner's centre distance into a clearance) is added back.
    A route waypoint inside this ring is a waypoint the gate will veto on
    arrival, which is what makes the ring the right thing to paint.
    """

    return predictive_person_stop_m(policy, speed_mps) + policy.owner_collision_envelope_m


def compliant_speed(
    clearance_m: float,
    *,
    policy: ReactiveSafetyPolicy,
) -> float:
    """Largest speed the gate will NOT veto at ``clearance_m`` (float lattice).

    The gate vetoes at ``clearance <= person_stop_m + v·reaction_time_s``, so
    the admissible set is ``{v >= 0 : gate_vetoes(clearance, v) is False}`` — an
    interval that is *open* at the top in exact arithmetic. On the float lattice
    it has a largest element, and that element is what a proposer wants: any
    faster and the gate stops the robot dead; slower is needlessly timid.

    Returned value is the SUPREMUM ON THE FLOAT LATTICE: the largest float ``v``
    for which the gate's own inequality evaluates ``False``, found by bisecting
    the lattice between an admissible ``lo`` and a vetoing ``hi`` until they are
    adjacent. Exact by construction and free of new constants — the analytic
    expression ``(clearance - person_stop_m) / reaction_time_s`` is used only as
    a starting bracket, never as the answer, because rounding can place it on
    either side of the boundary.

    Returns ``0.0`` when the admissible set is EMPTY (``clearance <=
    person_stop_m``: the gate vetoes even a standing start). Callers must treat
    ``0.0`` as "no translation is compliant here"; it is not a promise that
    ``0.0`` passes. :func:`gate_vetoes` answers that question directly.
    """

    clearance = float(clearance_m)
    if not math.isfinite(clearance):
        raise ValueError("clearance_m must be finite")
    if gate_vetoes(clearance, 0.0, policy=policy):
        return 0.0

    # Bracket: ``lo`` is known admissible (the standing start checked above),
    # ``hi`` is known to veto. The analytic root seeds one side or the other
    # depending on which way it rounded; the lattice walk settles it.
    estimate = (clearance - policy.person_stop_m) / policy.reaction_time_s
    if not math.isfinite(estimate) or estimate <= 0.0:
        estimate = math.ulp(0.0)
    lo = 0.0
    hi = estimate
    if not gate_vetoes(clearance, hi, policy=policy):
        lo = hi
        while not gate_vetoes(clearance, hi, policy=policy):
            hi = math.nextafter(hi, math.inf)

    while math.nextafter(lo, hi) != hi:
        mid = lo + (hi - lo) / 2.0
        if mid <= lo or mid >= hi:
            break
        if gate_vetoes(clearance, mid, policy=policy):
            hi = mid
        else:
            lo = mid
    return lo


def keepout_cost_field(
    cell_centers_xy: np.ndarray,
    people_xy: Sequence[tuple[float, float]],
    *,
    policy: ReactiveSafetyPolicy,
    speed_mps: float | tuple[float, float],
    cost: float,
) -> np.ndarray:
    """Additive per-cell planner penalty for the keepout rings of ``people_xy``.

    Shape and contract match the planner's dynamic-cost layer
    (``GridPlanner.set_dynamic_cost_layer``): finite, non-negative, additive —
    a COST and never a mask, so it can only make a cell more expensive and can
    never open a route that hard inflation closed. Cells whose centre lies
    inside a person's :func:`keepout_radius_m` ring get ``cost``; everything
    else gets zero; overlapping rings sum.

    ``cell_centers_xy`` is the ``(N, 2)`` world-frame cell-centre array the
    rolling grid already publishes.
    """

    query = np.asarray(cell_centers_xy, dtype=float)
    if query.ndim != 2 or query.shape[1] != 2:
        raise ValueError("cell_centers_xy must have shape (N, 2)")
    if not np.all(np.isfinite(query)):
        raise ValueError("cell_centers_xy must be finite")
    weight = float(cost)
    if not math.isfinite(weight) or weight < 0.0:
        raise ValueError("cost must be finite and non-negative")

    field = np.zeros(query.shape[0], dtype=float)
    radius = keepout_radius_m(policy, speed_mps)
    for person in people_xy:
        px, py = (float(person[0]), float(person[1]))
        if not (math.isfinite(px) and math.isfinite(py)):
            raise ValueError("people_xy entries must be finite")
        dx = query[:, 0] - px
        dy = query[:, 1] - py
        field += np.where(dx * dx + dy * dy <= radius * radius, weight, 0.0)
    return field
