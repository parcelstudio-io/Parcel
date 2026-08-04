import math
import time
from itertools import pairwise

import pytest

from parcel_robot.navigation.velocity_shaping import SCurveVelocityShaper, ShaperLimits


def _shaper(accel: float = 2.0, jerk: float = 8.0) -> SCurveVelocityShaper:
    limits = ShaperLimits(max_accel=accel, max_jerk=jerk)
    return SCurveVelocityShaper(limits, limits, limits)


def test_target_step_has_bounded_acceleration_and_jerk_without_overshoot() -> None:
    shaper = _shaper()
    velocities = [0.0]
    for _ in range(100):
        velocities.append(shaper.step((1.0, 0.0, 0.0), dt_s=0.02)[0])
    accelerations = [
        (current - previous) / 0.02
        for previous, current in pairwise(velocities)
    ]
    assert max(velocities) <= 1.0 + 1e-12
    assert max(abs(value) for value in accelerations) <= 2.0 + 1e-10
    assert max(
        abs(current - previous)
        for previous, current in pairwise([0.0, *accelerations])
    ) <= 8.0 * 0.02 + 1e-10
    assert velocities[-1] == pytest.approx(1.0, abs=0.01)


def test_variable_dt_tracks_without_overshoot() -> None:
    shaper = _shaper()
    values = []
    for index in range(80):
        dt_s = (0.007, 0.013, 0.021)[index % 3]
        values.append(shaper.step((0.6, -0.4, 0.2), dt_s=dt_s))
    assert all(value[0] <= 0.6 + 1e-12 for value in values)
    assert all(value[1] >= -0.4 - 1e-12 for value in values)
    assert all(value[2] <= 0.2 + 1e-12 for value in values)


def test_emergency_ignores_target_and_bypasses_jerk() -> None:
    shaper = _shaper(accel=1.5, jerk=0.01)
    shaper.reset((1.0, -0.4, 0.1))
    result = shaper.step((10.0, 10.0, 10.0), dt_s=0.2, emergency=True)
    assert result == pytest.approx((0.7, -0.1, 0.0))


def test_scaled_halves_limits_and_preserves_velocity() -> None:
    original = _shaper(accel=2.0, jerk=4.0)
    original.reset((0.2, 0.0, 0.0))
    calm = original.scaled(0.5)
    first = calm.step((2.0, 0.0, 0.0), dt_s=0.1)[0]
    second = calm.step((2.0, 0.0, 0.0), dt_s=0.1)[0]
    assert first == pytest.approx(0.22)
    assert second - first == pytest.approx(0.04)
    # Scaling returns an independent profile and leaves the source state alone.
    assert original.step((0.2, 0.0, 0.0), dt_s=0.1)[0] == pytest.approx(0.2)


def test_reset_zero_cost_and_validation() -> None:
    shaper = _shaper()
    shaper.reset((0.3, -0.2, 0.1))
    assert shaper.step((0.3, -0.2, 0.1), dt_s=0.1) == (0.3, -0.2, 0.1)
    with pytest.raises(ValueError):
        shaper.step((math.nan, 0.0, 0.0), dt_s=0.1)
    with pytest.raises(ValueError):
        shaper.step((0.0, 0.0, 0.0), dt_s=0.0)
    with pytest.raises(ValueError):
        ShaperLimits(max_accel=1.0, max_jerk=math.inf)
    with pytest.raises(ValueError):
        shaper.scaled(0.0)


def test_step_performance() -> None:
    shaper = _shaper()
    count = 20_000
    started = time.perf_counter()
    for _ in range(count):
        shaper.step((1.0, -0.2, 0.5), dt_s=0.01)
    elapsed_per_step = (time.perf_counter() - started) / count
    assert elapsed_per_step < 0.00005
