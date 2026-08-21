import math
import time

import numpy as np
import pytest

from parcel_robot.navigation.dynamic_costs import (
    AgentTrack,
    agent_cost_at,
    time_to_collision_s,
)


def test_zero_tracks() -> None:
    query = np.array(((0.0, 0.0), (1.0, 2.0)))
    assert np.array_equal(agent_cost_at([], query), np.zeros(2))
    assert math.isinf(
        time_to_collision_s(
            [], robot_xy=(0.0, 0.0), robot_v=(1.0, 0.0), robot_radius_m=0.3
        )
    )


def test_stationary_agent_produces_static_gaussian() -> None:
    track = AgentTrack(0.0, 0.0, 0.0, 0.0, radius_m=0.0)
    costs = agent_cost_at(
        [track],
        np.array(((0.0, 0.0), (1.0, 0.0), (3.0, 0.0))),
        horizon_s=0.2,
        step_s=0.2,
    )
    assert costs[0] == 1.0
    assert costs[0] > costs[1] > costs[2]
    assert np.all((0.0 <= costs) & (costs <= 1.0))


def test_rollout_places_cost_in_future_corridor() -> None:
    track = AgentTrack(0.0, 0.0, 1.0, 0.0, radius_m=0.1)
    query = np.array(((1.0, 0.0), (1.0, 2.0)))
    costs = agent_cost_at([track], query)
    assert costs[0] > 0.5
    assert costs[0] > costs[1]


def test_ttc_approaching_receding_and_stationary_robot() -> None:
    approaching = AgentTrack(2.0, 0.0, 0.0, 0.0, radius_m=0.25)
    ttc = time_to_collision_s(
        [approaching],
        robot_xy=(0.0, 0.0),
        robot_v=(1.0, 0.0),
        robot_radius_m=0.25,
    )
    assert ttc == pytest.approx(1.5)
    receding = AgentTrack(2.0, 0.0, 2.0, 0.0, radius_m=0.25)
    assert math.isinf(
        time_to_collision_s(
            [receding],
            robot_xy=(0.0, 0.0),
            robot_v=(1.0, 0.0),
            robot_radius_m=0.25,
        )
    )
    walker = AgentTrack(2.0, 0.0, -1.0, 0.0, radius_m=0.25)
    assert time_to_collision_s(
        [walker],
        robot_xy=(0.0, 0.0),
        robot_v=(0.0, 0.0),
        robot_radius_m=0.25,
    ) == pytest.approx(1.5)


def test_overlap_and_validation() -> None:
    overlap = AgentTrack(0.1, 0.0, 0.0, 0.0, radius_m=0.2)
    assert (
        time_to_collision_s(
            [overlap],
            robot_xy=(0.0, 0.0),
            robot_v=(0.0, 0.0),
            robot_radius_m=0.2,
        )
        == 0.0
    )
    bad = AgentTrack(0.0, 0.0, math.nan, 0.0)
    with pytest.raises(ValueError):
        agent_cost_at([bad], np.zeros((1, 2)))
    with pytest.raises(ValueError):
        time_to_collision_s(
            [bad],
            robot_xy=(0.0, 0.0),
            robot_v=(0.0, 0.0),
            robot_radius_m=0.2,
        )
    with pytest.raises(ValueError):
        agent_cost_at([], np.zeros((3,)))


@pytest.mark.load_sensitive
def test_cost_field_vectorization_performance() -> None:
    """Card R26: the assertion is unchanged; only the marker is new.

    READ THIS BEFORE SPENDING AN HOUR ON IT. ``per_call < 0.002`` measures the
    clock frequency of whichever core this lands on, not the code.

    * It reddened a recorded R13 commit gate at ``0.0031336`` (15-minute load 65
      on this 192-core host) and passed unchanged on the same tree at load 20.
    * R26 measured it again on an **idle** host, 2026-08-21: 25/25 timed trials
      over budget, min ``0.002430``; 15/15 pytest failures in isolation — while
      the identical test passed inside R25's full 7,442-test gate 22 minutes
      earlier, on a tree where this module is byte-identical to HEAD.
    * The host runs the ``powersave`` governor: cores idle at 2.21 GHz against a
      5.39 GHz ceiling, and 3.6/2.2 ~ 1.6x covers the whole gap. A burst on a
      cold core is slow; a core the preceding thousands of tests have heated is
      not. ``os.getloadavg()`` cannot see that, and neither can the load guard.

    So: **a failure here is very likely your machine, not your change** — check
    ``R26_STATUS.md`` §4.3 before attributing it. The 2 ms budget was NOT
    relaxed by R26; relaxing a number to stop noise is how a performance pin
    becomes decoration. Re-deriving it, or rewriting the assertion as a ratio
    against a same-core reference, is a decision with attribution and is
    R26_STATUS.md §9 open risk 1.
    """

    tracks = [AgentTrack(float(index), 0.0, 0.2, 0.1) for index in range(8)]
    query = np.random.default_rng(7).normal(size=(4_000, 2))
    # Use repeated calls to reduce timer quantization without pinning a noisy
    # single call. The card's 10 projected steps use horizon 1.8 inclusive.
    started = time.perf_counter()
    repeats = 10
    for _ in range(repeats):
        result = agent_cost_at(tracks, query, horizon_s=1.8, step_s=0.2)
    per_call = (time.perf_counter() - started) / repeats
    assert result.shape == (4_000,)
    assert per_call < 0.002


def test_cost_field_is_vectorized_over_the_whole_query_under_any_load() -> None:
    """The non-timing half of the test above — never skipped (card R26).

    The shape contract (one cost per query row, finite, batch-equals-loop) is
    what makes the timing claim meaningful in the first place, and it does not
    need a quiet machine. Guarding the timing assertion must not take this with
    it.
    """

    tracks = [AgentTrack(float(index), 0.0, 0.2, 0.1) for index in range(8)]
    query = np.random.default_rng(7).normal(size=(4_000, 2))
    batch = agent_cost_at(tracks, query, horizon_s=1.8, step_s=0.2)
    assert batch.shape == (4_000,)
    assert np.all(np.isfinite(batch))
    for index in (0, 1234, 3999):
        single = agent_cost_at(tracks, query[index : index + 1], horizon_s=1.8, step_s=0.2)
        assert single.shape == (1,)
        assert float(single[0]) == pytest.approx(float(batch[index]), rel=1e-12, abs=1e-12)


def test_default_field_keeps_a_gradient_instead_of_a_saturated_mesa() -> None:
    track = AgentTrack(0.0, 0.0, 1.2, 0.0, radius_m=0.35)
    xs = np.linspace(-2.0, 4.0, 61)
    costs = agent_cost_at([track], np.column_stack([xs, np.zeros_like(xs)]))
    saturated = int(np.sum(costs >= 1.0 - 1e-12))
    # Pre-arbitration defaults saturated ~36 of 61 samples (~3.6 m). After
    # weight normalization the plateau must be small enough that A* still sees
    # a gradient along the track.
    assert saturated <= 5
    assert float(np.max(np.abs(np.diff(costs)))) > 0.01


def test_behind_costs_no_more_than_front_at_equal_range() -> None:
    track = AgentTrack(0.0, 0.0, 1.2, 0.0, radius_m=0.35)
    query = np.array(((-1.0, 0.0), (-1.5, 0.0), (1.0, 0.0), (1.5, 0.0)))
    costs = agent_cost_at([track], query)
    assert costs[0] <= costs[2] + 1e-9
    assert costs[1] <= costs[3] + 1e-9
    assert costs[1] < costs[0]
