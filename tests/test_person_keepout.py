"""Card D15-A — derived person keepout, strict compliant speed, D-15 pin.

Four things are pinned here, and only these four are claimed:

* the MEASURED D-15 geometry (``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md``
  §1.1) reproduces from the shipped policy — clearance 1.2632 m against a
  predictive person stop of 1.3020 m at the v3/v4 cruise speed, i.e. a veto on
  every tick;
* :func:`compliant_speed` is the float-lattice SUPREMUM of the admissible set,
  verified against the gate's own inequality at ``v`` and at
  ``nextafter(v, +inf)`` (adjudication #5: the gate's comparison is ``<=``, so
  the analytic root is itself vetoed);
* the property that makes it safe to cap a proposal with it, over randomized
  clearances and randomized policies;
* no-literal drift: the module states no safety constant of its own, so a
  future ``person_stop_m`` retune moves every derived quantity (adjudication
  #20 puts these assertions HERE, not in
  ``tests/test_authority_no_literal_drift.py``).

What these tests do NOT prove: that any consumer is safe. ``person_keepout``
proposes; ``apply_reactive_safety`` — untouched by card D15-A — disposes.
"""

from __future__ import annotations

import ast
import math
import pathlib
import random

import numpy as np
import pytest

from parcel_robot.navigation import person_keepout
from parcel_robot.navigation.person_keepout import (
    compliant_speed,
    gate_vetoes,
    keepout_cost_field,
    keepout_radius_m,
    predictive_person_stop_m,
)
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy

#: The D-15 bisect numbers, from the design record §1.1 (all measured):
#: owner at (2.00, -0.50), robot at (0.29, 0.11) heading for tree_2.
D15_OWNER_CENTER_DISTANCE_M = 1.8132
#: Cruise speed of the grid_v1 controller the frozen rows were measured with.
D15_COMMANDED_SPEED_MPS = 0.85


def _shipped_policy() -> ReactiveSafetyPolicy:
    """The policy the D-15 rows were measured under (defaults = the authority)."""

    return ReactiveSafetyPolicy()


def test_d15_geometry_pin_reproduces_the_measured_veto() -> None:
    policy = _shipped_policy()
    clearance = D15_OWNER_CENTER_DISTANCE_M - policy.owner_collision_envelope_m
    threshold = predictive_person_stop_m(policy, D15_COMMANDED_SPEED_MPS)

    assert round(clearance, 4) == 1.2632
    assert round(threshold, 4) == 1.3020
    assert gate_vetoes(clearance, D15_COMMANDED_SPEED_MPS, policy=policy) is True
    # The ring the planner has to route around, centre-referenced.
    assert round(keepout_radius_m(policy, D15_COMMANDED_SPEED_MPS), 4) == 1.8520


def test_d15_pin_is_a_veto_only_under_the_retune() -> None:
    """The counterfactual, computed (not run): at the OLD 1.0 the tick passes.

    ``ReactiveSafetyPolicy`` refuses ``person_stop_m`` below the envelope floor
    (E5's guard, adjudication #12), so the old arm cannot be constructed as a
    policy at all — the arithmetic is done directly on the gate's expression.

    Card P1-E (2026-08-22) lowered that floor from the shipped social zone
    (1.2 m) to the named ``PERSON_SOCIAL_ZONE_FLOOR_M`` (0.68 m), so the retired
    1.0 IS now constructible. The counterfactual arithmetic below is unchanged
    and is still done on the gate's expression; the refusal is re-probed at a
    value under the new floor, which is what the guard now guards.
    """

    policy = _shipped_policy()
    clearance = D15_OWNER_CENTER_DISTANCE_M - policy.owner_collision_envelope_m
    old_person_stop_m = 1.0
    old_threshold = old_person_stop_m + D15_COMMANDED_SPEED_MPS * policy.reaction_time_s

    assert round(old_threshold, 4) == 1.1020
    assert clearance > old_threshold
    with pytest.raises(ValueError, match="person_stop_m must not undercut"):
        ReactiveSafetyPolicy(person_stop_m=0.6)


def test_compliant_speed_is_the_float_lattice_supremum_at_the_d15_pin() -> None:
    policy = _shipped_policy()
    clearance = D15_OWNER_CENTER_DISTANCE_M - policy.owner_collision_envelope_m

    speed = compliant_speed(clearance, policy=policy)

    assert speed == pytest.approx(0.5266, abs=1e-4)
    # The gate's own inequality: False here, True one float step up. That pair
    # IS the definition of the supremum, evaluated by the gate's expression.
    assert gate_vetoes(clearance, speed, policy=policy) is False
    assert gate_vetoes(clearance, math.nextafter(speed, math.inf), policy=policy) is True
    # Strictly below the analytic root, which the ``<=`` boundary vetoes.
    assert speed < (clearance - policy.person_stop_m) / policy.reaction_time_s
    # And strictly below the speed that deadlocked D-15.
    assert speed < D15_COMMANDED_SPEED_MPS


def test_compliant_speed_is_empty_below_the_stop_distance() -> None:
    """No speed — not even zero — is admissible inside ``person_stop_m``."""

    policy = _shipped_policy()

    assert compliant_speed(policy.person_stop_m, policy=policy) == 0.0
    assert gate_vetoes(policy.person_stop_m, 0.0, policy=policy) is True
    # Just outside, a standing start is admissible and the supremum is > 0.
    outside = math.nextafter(policy.person_stop_m, math.inf)
    assert gate_vetoes(outside, 0.0, policy=policy) is False
    assert compliant_speed(outside, policy=policy) >= 0.0


def _random_policy(rng: random.Random) -> ReactiveSafetyPolicy:
    person_stop_m = rng.uniform(1.2, 2.0)
    return ReactiveSafetyPolicy(
        person_stop_m=person_stop_m,
        person_slow_m=person_stop_m + rng.uniform(0.3, 1.5),
        owner_collision_envelope_m=rng.uniform(0.2, 0.8),
        reaction_time_s=rng.uniform(0.05, 0.5),
    )


def test_compliant_speed_property_over_randomized_clearances_and_policies() -> None:
    """For all v > compliant_speed the gate vetoes; at compliant_speed it does not."""

    rng = random.Random(20260811)
    for _ in range(400):
        policy = _random_policy(rng)
        clearance = policy.person_stop_m + rng.uniform(-0.2, 2.0)
        speed = compliant_speed(clearance, policy=policy)

        if speed == 0.0 and gate_vetoes(clearance, 0.0, policy=policy):
            # Admissible set genuinely empty: inside the stop distance.
            assert clearance <= policy.person_stop_m
            continue

        assert gate_vetoes(clearance, speed, policy=policy) is False
        assert gate_vetoes(clearance, math.nextafter(speed, math.inf), policy=policy) is True
        for faster in (
            math.nextafter(speed, math.inf),
            speed * 1.000001 + 1e-9,
            speed + 0.01,
            speed + 1.0,
        ):
            assert gate_vetoes(clearance, faster, policy=policy) is True


def test_speed_pair_form_matches_the_gates_hypot() -> None:
    policy = _shipped_policy()
    vx, vy = 0.6, 0.25

    assert predictive_person_stop_m(policy, (vx, vy)) == predictive_person_stop_m(
        policy, math.hypot(vx, vy)
    )


def test_derived_quantities_track_a_retuned_policy() -> None:
    """A retune moves every derived number — the anti-fork property."""

    shipped = _shipped_policy()
    retuned = ReactiveSafetyPolicy(
        person_stop_m=shipped.person_stop_m + 0.3,
        person_slow_m=shipped.person_slow_m,
        reaction_time_s=shipped.reaction_time_s * 2.0,
    )
    clearance = 1.9

    assert predictive_person_stop_m(retuned, 0.85) > predictive_person_stop_m(shipped, 0.85)
    assert keepout_radius_m(retuned, 0.85) > keepout_radius_m(shipped, 0.85)
    assert compliant_speed(clearance, policy=retuned) < compliant_speed(
        clearance, policy=shipped
    )
    # Every threshold is the policy's own arithmetic, not a copy of it.
    assert predictive_person_stop_m(retuned, 0.0) == retuned.person_stop_m
    assert keepout_radius_m(retuned, 0.0) == (
        retuned.person_stop_m + retuned.owner_collision_envelope_m
    )


#: Values that would be a SECOND COPY of a safety authority if written into
#: ``person_keepout.py``: the shipped person clearances, the reaction horizon,
#: the owner envelope, and the cruise speed the D-15 rows were measured at.
FORBIDDEN_LITERALS: frozenset[float] = frozenset(
    {1.0, 1.2, 2.5, 0.12, 0.55, 0.85, 1.3020, 1.2632, 1.8532, 0.5266}
)

#: The only float literals the module may contain: ``0.0`` (origin/comparison)
#: and ``2.0`` (the bisection midpoint divisor). Neither is a safety quantity.
STRUCTURAL_FLOAT_LITERALS: frozenset[float] = frozenset({0.0, 2.0})


def test_module_states_no_safety_literal_of_its_own() -> None:
    """No-literal-drift tripwire (adjudication #20; §1.4 risk 3).

    The named risk is that ``compliant_speed`` — or any threshold it reads —
    drifts INTO a hardcoded copy, at which point a retune of the gate would
    stop moving the proposer and the two would fork silently. Scanning the
    module's own AST is the cheapest way to keep that impossible.
    """

    source = pathlib.Path(person_keepout.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    floats = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is float
    }

    offenders = sorted(floats & FORBIDDEN_LITERALS)
    assert offenders == [], f"safety constants restated in person_keepout.py: {offenders}"
    assert floats <= STRUCTURAL_FLOAT_LITERALS


def test_thresholds_are_read_from_the_policy_instance() -> None:
    """Every returned number is a function of the PASSED policy, nothing else."""

    policy = _shipped_policy()
    assert predictive_person_stop_m(policy, 0.0) == policy.person_stop_m
    assert predictive_person_stop_m(policy, 1.0) == (
        policy.person_stop_m + policy.reaction_time_s
    )
    assert keepout_radius_m(policy, 0.0) == (
        policy.person_stop_m + policy.owner_collision_envelope_m
    )


def _cell_centers(extent_m: float, step_m: float) -> np.ndarray:
    axis = np.arange(-extent_m, extent_m + step_m * 0.5, step_m)
    grid_x, grid_y = np.meshgrid(axis, axis, indexing="xy")
    return np.column_stack((grid_x.ravel(), grid_y.ravel()))


def test_keepout_cost_field_paints_exactly_the_derived_ring() -> None:
    policy = _shipped_policy()
    centers = _cell_centers(4.0, 0.1)
    person = (1.0, 0.5)
    radius = keepout_radius_m(policy, D15_COMMANDED_SPEED_MPS)

    field = keepout_cost_field(
        centers,
        [person],
        policy=policy,
        speed_mps=D15_COMMANDED_SPEED_MPS,
        cost=1.0,
    )

    inside = np.hypot(centers[:, 0] - person[0], centers[:, 1] - person[1]) <= radius
    assert np.array_equal(field > 0.0, inside)
    assert float(field.min()) >= 0.0
    assert np.all(np.isfinite(field))
    # Contract of ``GridPlanner.set_dynamic_cost_layer``: additive, non-negative.
    assert field.shape == (centers.shape[0],)


def test_keepout_cost_field_rings_are_additive_and_shrink_with_speed() -> None:
    policy = _shipped_policy()
    centers = _cell_centers(3.0, 0.1)
    people = [(0.0, 0.0), (0.4, 0.0)]

    fast = keepout_cost_field(centers, people, policy=policy, speed_mps=0.85, cost=1.0)
    slow = keepout_cost_field(centers, people, policy=policy, speed_mps=0.0, cost=1.0)

    assert float(fast.max()) == 2.0  # overlapping rings sum
    assert float((fast > 0.0).sum()) > float((slow > 0.0).sum())
    # Slowing down is what shrinks the ring — the whole point of the speed cap.
    assert keepout_radius_m(policy, 0.0) < keepout_radius_m(policy, 0.85)


def test_keepout_cost_field_rejects_malformed_inputs() -> None:
    policy = _shipped_policy()
    centers = _cell_centers(1.0, 0.5)

    with pytest.raises(ValueError, match="shape"):
        keepout_cost_field(
            np.zeros((4, 3)), [(0.0, 0.0)], policy=policy, speed_mps=0.0, cost=1.0
        )
    with pytest.raises(ValueError, match="non-negative"):
        keepout_cost_field(centers, [(0.0, 0.0)], policy=policy, speed_mps=0.0, cost=-1.0)
    with pytest.raises(ValueError, match="finite"):
        keepout_cost_field(
            centers, [(math.nan, 0.0)], policy=policy, speed_mps=0.0, cost=1.0
        )
    with pytest.raises(ValueError, match="finite"):
        compliant_speed(math.inf, policy=policy)
