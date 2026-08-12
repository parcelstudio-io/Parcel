"""Card J-A: the frozen contract of ``core.stop_ramp``.

The module reproduces the pre-6bd945d emergency decay. These tests are the
contract, not a smoke check: every clause of the card's gate is a test here, and
the bit-equality clause reconstructs the 60ecea2 semantics from an INDEPENDENT
copy of that hunk rather than importing the live symbol, so a future edit of the
shaper cannot make the equality vacuous.
"""

from __future__ import annotations

import math
import random

import pytest

from parcel_robot.core.stop_ramp import (
    ZERO_STEP,
    enforce_monotone_stop,
    nominal_stop_step,
)
from parcel_robot.navigation.velocity_shaping import ShaperLimits

LIMITS = (
    ShaperLimits(1.2, 3.0),
    ShaperLimits(1.2, 3.0),
    ShaperLimits(2.4, 6.0),
)


# --- the reconstructed 60ecea2 emergency hunk (verbatim, independent copy) ---
#
#   git show 60ecea2:src/parcel_robot/navigation/velocity_shaping.py
#   lines 20-24 (_move_toward) and 97-120 (step(..., emergency=True))
#
# Retyped here on purpose. Importing the live ``_move_toward`` would make the
# bit-equality test tautological the moment somebody edits it.


def _move_toward_60ecea2(current: float, target: float, distance: float) -> float:
    if current < target:
        return min(current + distance, target)
    return max(current - distance, target)


def _emergency_60ecea2(
    velocity: tuple[float, float, float],
    limits: tuple[ShaperLimits, ShaperLimits, ShaperLimits],
    dt_s: float,
) -> tuple[float, float, float]:
    """The pre-P0-A emergency branch: per-axis ``_move_toward(v, 0, a*dt)``."""

    out = []
    for index, limit in enumerate(limits):
        out.append(_move_toward_60ecea2(velocity[index], 0.0, limit.max_accel * dt_s))
    return (out[0], out[1], out[2])


def _seeded_grid() -> list[tuple[tuple[float, float, float], float, float]]:
    """(velocity, max_accel, dt) triples: a deterministic sweep, not a sample."""

    rng = random.Random(20260811)
    grid: list[tuple[tuple[float, float, float], float, float]] = []
    for velocity in (
        (0.0, 0.0, 0.0),
        (0.141, 0.0, 0.0),
        (-0.141, 0.02, -0.4),
        (1.5, -1.5, 3.0),
        (1e-18, -1e-18, 0.0),
        (0.85, 0.12, -2.4),
    ):
        for accel in (0.05, 1.2, 2.4, 12.0):
            for dt in (1e-3, 0.05, 0.1, 0.25, 10.0):
                grid.append((velocity, accel, dt))
    for _ in range(400):
        velocity = (
            rng.uniform(-3.0, 3.0),
            rng.uniform(-3.0, 3.0),
            rng.uniform(-6.0, 6.0),
        )
        grid.append((velocity, rng.uniform(1e-3, 5.0), rng.uniform(1e-3, 0.3)))
    return grid


def test_nominal_stop_step_is_bit_equal_to_the_60ecea2_emergency_semantics() -> None:
    """The whole point of the module: the OLD ramp, bit for bit."""

    for velocity, accel, dt in _seeded_grid():
        limits = (
            ShaperLimits(accel, accel * 2.5),
            ShaperLimits(accel, accel * 2.5),
            ShaperLimits(accel * 2.0, accel * 5.0),
        )
        expected = _emergency_60ecea2(velocity, limits, dt)
        actual = nominal_stop_step(velocity, limits, dt)
        assert actual == expected, f"{velocity} @ accel={accel} dt={dt}"
        # Bit-equality, not just ``==``: -0.0 == 0.0 would hide a sign flip.
        for got, want in zip(actual, expected):
            assert math.copysign(1.0, got) == math.copysign(1.0, want)


def test_every_step_is_non_increasing_in_magnitude_and_sign_preserving() -> None:
    for velocity, accel, dt in _seeded_grid():
        limits = (
            ShaperLimits(accel, accel * 2.5),
            ShaperLimits(accel, accel * 2.5),
            ShaperLimits(accel * 2.0, accel * 5.0),
        )
        stepped = nominal_stop_step(velocity, limits, dt)
        for was, now in zip(velocity, stepped):
            assert abs(now) <= abs(was)
            assert was * now >= 0.0


def test_zero_is_reached_in_the_ceiling_number_of_steps() -> None:
    """``ceil(|v| / (max_accel * dt))`` steps — plus at most one float-residue tick.

    Measured, and deliberately NOT "fixed": iterated ``_move_toward`` subtraction
    can leave a residue of order 1e-16 on the tick the exact-arithmetic bound
    predicts as zero (e.g. ``-3.0`` at ``a=1.2, dt=0.25`` lands on
    ``-3.33e-16``), which the next tick clears. The module reproduces the
    60ecea2 semantics bit for bit, so it inherits that residue; snapping it to
    zero here would BREAK the bit-equality contract. The runtime consequence is
    bounded and benign: one extra ramp tick below ``_is_zero_command``'s 1e-9.
    """

    for velocity in ((0.9, -0.4, 2.0), (0.141, 0.0, 0.0), (-3.0, 3.0, -6.0)):
        for dt in (0.05, 0.1, 0.25):
            bound = max(
                math.ceil(abs(value) / (limit.max_accel * dt))
                for value, limit in zip(velocity, LIMITS)
            )
            state = velocity
            for _ in range(bound):
                assert state != ZERO_STEP, "reached zero earlier than the ceiling bound"
                state = nominal_stop_step(state, LIMITS, dt)
            # At the exact-arithmetic bound: zero, or a residue under 1e-9.
            assert all(abs(value) < 1e-9 for value in state)
            assert nominal_stop_step(state, LIMITS, dt) == ZERO_STEP


def test_the_ramp_fails_closed_on_bad_dt_velocity_or_limits() -> None:
    for dt in (0.0, -0.1, math.inf, math.nan, -math.inf, "0.1", None, True):
        assert nominal_stop_step((0.5, 0.5, 0.5), LIMITS, dt) == ZERO_STEP
    for velocity in (
        (math.inf, 0.0, 0.0),
        (0.0, math.nan, 0.0),
        (0.0, 0.0, -math.inf),
        (0.1, 0.2),
        (0.1, 0.2, 0.3, 0.4),
        "abc",
        None,
        42,
    ):
        assert nominal_stop_step(velocity, LIMITS, 0.1) == ZERO_STEP
    for limits in ((), (LIMITS[0], LIMITS[1]), None, "xyz", (1.2, 1.2, 2.4)):
        assert nominal_stop_step((0.5, 0.5, 0.5), limits, 0.1) == ZERO_STEP


def test_a_zero_velocity_stays_exactly_zero() -> None:
    assert nominal_stop_step(ZERO_STEP, LIMITS, 0.1) == ZERO_STEP


def test_enforce_monotone_stop_accepts_only_legal_continuations() -> None:
    previous = (0.4, -0.2, 1.0)
    assert enforce_monotone_stop(previous, (0.3, -0.1, 0.5)) == (0.3, -0.1, 0.5)
    assert enforce_monotone_stop(previous, previous) == previous
    assert enforce_monotone_stop(previous, ZERO_STEP) == ZERO_STEP


def test_enforce_monotone_stop_rejects_every_magnitude_increase() -> None:
    previous = (0.4, -0.2, 1.0)
    for candidate in (
        (0.4000000000000001, -0.2, 1.0),
        (0.4, -0.20000000000000004, 1.0),
        (0.4, -0.2, 1.0000000000000002),
        (0.9, -0.2, 1.0),
    ):
        assert enforce_monotone_stop(previous, candidate) is None
    # From an exact zero, ANY motion is an increase.
    for candidate in ((1e-18, 0.0, 0.0), (0.0, -1e-18, 0.0), (0.0, 0.0, 1e-18)):
        assert enforce_monotone_stop(ZERO_STEP, candidate) is None


def test_enforce_monotone_stop_rejects_sign_flips_even_when_smaller() -> None:
    previous = (0.4, -0.2, 1.0)
    for candidate in ((-0.1, -0.1, 0.5), (0.1, 0.1, 0.5), (0.1, -0.1, -0.5)):
        assert enforce_monotone_stop(previous, candidate) is None


def test_enforce_monotone_stop_rejects_non_finite_and_malformed_shapes() -> None:
    previous = (0.4, -0.2, 1.0)
    for candidate in (
        (math.nan, 0.0, 0.0),
        (0.0, math.inf, 0.0),
        (0.0, 0.0, -math.inf),
        (0.1, 0.2),
        (0.1, 0.2, 0.3, 0.4),
        None,
        "abc",
        42,
    ):
        assert enforce_monotone_stop(previous, candidate) is None
    for prior in ((math.nan, 0.0, 0.0), (0.1, 0.2), None, "abc"):
        assert enforce_monotone_stop(prior, (0.0, 0.0, 0.0)) is None


def test_iterated_ramp_is_always_accepted_by_the_boundary_check() -> None:
    """The two halves of the contract agree: the ramp never trips its own guard."""

    rng = random.Random(4711)
    for _ in range(200):
        state = (
            rng.uniform(-2.0, 2.0),
            rng.uniform(-2.0, 2.0),
            rng.uniform(-4.0, 4.0),
        )
        dt = rng.uniform(0.01, 0.25)
        for _ in range(1000):
            candidate = nominal_stop_step(state, LIMITS, dt)
            assert enforce_monotone_stop(state, candidate) == candidate
            state = candidate
            if state == ZERO_STEP:
                break
        assert state == ZERO_STEP


def test_the_module_exposes_only_its_frozen_contract() -> None:
    import parcel_robot.core.stop_ramp as module

    assert sorted(module.__all__) == [
        "ZERO_STEP",
        "enforce_monotone_stop",
        "nominal_stop_step",
    ]


def test_the_ramp_never_raises_on_hostile_input() -> None:
    class Hostile:
        def __len__(self) -> int:
            raise RuntimeError("hostile")

    with pytest.raises(RuntimeError):
        len(Hostile())
    assert nominal_stop_step(Hostile(), LIMITS, 0.1) == ZERO_STEP
    assert enforce_monotone_stop(Hostile(), (0.0, 0.0, 0.0)) is None
