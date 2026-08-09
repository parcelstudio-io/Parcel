"""Pure proxemic approach-pose scoring (task_2 Sol lane)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from parcel_robot.navigation.dynamic_costs import AgentTrack
from parcel_robot.navigation.proxemic_approach import (
    ProxemicApproachConfig,
    proxemic_costs,
    select_proxemic_approach,
)


def test_empty_tracks_zero_social_cost() -> None:
    poses = ((0.0, 0.0), (2.0, 1.0))
    costs = proxemic_costs(poses, [])
    assert costs.shape == (2,)
    assert np.allclose(costs, 0.0)


def test_stream_corridor_costs_more_than_quiet_side() -> None:
    # Pedestrians walk +x along y=0; quiet candidate sits off the stream.
    tracks = (
        AgentTrack(0.0, 0.0, 1.2, 0.0, radius_m=0.35),
        AgentTrack(-1.0, 0.0, 1.2, 0.0, radius_m=0.35),
    )
    in_stream = (1.5, 0.0)
    quiet = (1.5, 2.5)
    costs = proxemic_costs((in_stream, quiet), tracks)
    assert costs[0] > costs[1]
    assert costs[0] > 0.3


def test_select_prefers_pose_away_from_stream() -> None:
    tracks = (AgentTrack(0.0, 0.0, 1.0, 0.0, radius_m=0.3),)
    # Closest-to-robot would prefer (1.0, 0.0) on the stream; proxemic must
    # prefer the quieter offset even though it is farther from the robot.
    poses = ((1.0, 0.0), (1.0, 2.0), (0.5, 2.0))
    chosen = select_proxemic_approach(poses, tracks, robot_xy=(-1.0, 0.0))
    assert chosen is not None
    assert abs(chosen[1]) >= 1.5


def test_ttc_urgency_raises_cost_for_imminent_contact() -> None:
    walker = AgentTrack(2.0, 0.0, -1.0, 0.0, radius_m=0.25)
    near = (0.0, 0.0)  # contact ~1.5 s for stationary robot + radii
    far = (0.0, 4.0)
    costs = proxemic_costs(
        (near, far),
        [walker],
        config=ProxemicApproachConfig(occupancy_weight=0.0, ttc_weight=1.0),
    )
    assert costs[0] > costs[1]
    assert costs[0] == pytest.approx(1.0 - 1.5 / 2.0, abs=0.05)


def test_reject_threshold_fail_closed() -> None:
    track = AgentTrack(0.0, 0.0, 0.0, 0.0, radius_m=0.35)
    # Only candidate sits on the agent — must refuse rather than yield it.
    assert (
        select_proxemic_approach(
            ((0.0, 0.0),),
            [track],
            config=ProxemicApproachConfig(reject_cost=0.2),
        )
        is None
    )


def test_empty_candidates_return_none() -> None:
    assert select_proxemic_approach([], []) is None
    assert proxemic_costs([], []).shape == (0,)


def test_overlap_pose_has_max_ttc_urgency() -> None:
    overlap = AgentTrack(0.1, 0.0, 0.0, 0.0, radius_m=0.3)
    costs = proxemic_costs(
        ((0.0, 0.0),),
        [overlap],
        config=ProxemicApproachConfig(occupancy_weight=0.0, ttc_weight=1.0),
    )
    assert costs[0] == pytest.approx(1.0)


def test_malformed_inputs_raise() -> None:
    with pytest.raises(ValueError):
        proxemic_costs(np.array([1.0, 2.0, 3.0]), [])
    with pytest.raises(ValueError):
        proxemic_costs(((math.nan, 0.0),), [])
    with pytest.raises(ValueError):
        ProxemicApproachConfig(horizon_s=0.0)
    with pytest.raises(ValueError):
        ProxemicApproachConfig(step_s=3.0, horizon_s=1.0)
    bad = AgentTrack(0.0, 0.0, math.nan, 0.0)
    with pytest.raises(ValueError):
        proxemic_costs(((0.0, 0.0),), [bad])
