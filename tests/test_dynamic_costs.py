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


def test_cost_field_vectorization_performance() -> None:
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
