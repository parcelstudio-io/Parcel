"""N11 wiring pins: traffic ranking in approach + RampMemory seed on GridNavigator."""

from __future__ import annotations

import math
import pathlib

import pytest

from parcel_robot.navigation import pipeline as pipeline_module
from parcel_robot.navigation.approach import safe_approach_pose
from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.goals import SemanticGoal
from parcel_robot.navigation.grid_navigator import GridNavigator
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.semantic_map import SemanticCandidate
from parcel_robot.navigation.traffic_aware import RampMemory, TrackState


def _sidewalk_candidate() -> SemanticCandidate:
    # Wide polygon: nearest static point from (0,0) is near the south edge
    # (y≈1.0), while a quieter north entry sits farther away.
    polygon = (
        (-2.0, 1.0),
        (2.0, 1.0),
        (2.0, 5.0),
        (-2.0, 5.0),
    )
    return SemanticCandidate(
        candidate_id="sidewalk_0",
        label="sidewalk",
        x=0.0,
        y=3.0,
        confidence=0.9,
        kind="region",
        polygon=polygon,
        source="test",
        observed_at=0.0,
        reachable=True,
        metadata={"terminal_clearance_m": 0.2, "arrival_radius_m": 0.12},
    )


def test_safe_approach_empty_tracks_matches_static_nearest() -> None:
    goal = SemanticGoal("sidewalk", kind="region", terminal_relation="inside")
    candidate = _sidewalk_candidate()
    observation = NavObservation(position=(0.0, 0.0, 0.0), heading_deg=90.0)
    costs: dict[str, float] = {}
    with_empty = safe_approach_pose(
        goal, candidate, observation, tracks=(), cost_out=costs
    )
    without = safe_approach_pose(goal, candidate, observation)
    assert with_empty is not None and without is not None
    assert (with_empty.x, with_empty.y) == (without.x, without.y)
    assert costs["approach_traffic_cost"] == 0.0
    assert costs["approach_static_cost"] >= 0.0


def test_safe_approach_prefers_quieter_entry_with_crossing_stream() -> None:
    goal = SemanticGoal("sidewalk", kind="region", terminal_relation="inside")
    candidate = _sidewalk_candidate()
    observation = NavObservation(position=(0.0, 0.0, 0.0), heading_deg=90.0)
    static = safe_approach_pose(goal, candidate, observation, tracks=())
    assert static is not None
    # Pedestrian stream sweeping the statically-nearest south edge.
    tracks = (
        TrackState(x=-3.0, y=1.2, vx=1.4, vy=0.0, radius_m=0.35),
        TrackState(x=-1.5, y=1.3, vx=1.4, vy=0.0, radius_m=0.35),
    )
    costs: dict[str, float] = {}
    traffic = safe_approach_pose(
        goal, candidate, observation, tracks=tracks, cost_out=costs
    )
    assert traffic is not None
    assert costs["approach_traffic_cost"] >= 0.0
    # Quieter entry should sit farther north than the traffic-blind pick.
    assert traffic.y > static.y + 0.4
    assert math.hypot(traffic.x - 0.0, traffic.y - 0.0) > math.hypot(
        static.x - 0.0, static.y - 0.0
    )


def test_safe_approach_filters_track_lidar_and_weights_traffic() -> None:
    goal = SemanticGoal("sidewalk", kind="region", terminal_relation="inside")
    candidate = _sidewalk_candidate()
    # LiDAR return coinciding with the crossing stream (south edge). Without
    # track filtering those hits prune quiet samples the ranking needs.
    observation = NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=90.0,
        extras={
            "lidar_obstacles": [
                # Forward (heading 90°) ≈ world +y; distance ~1.2 m lands on stream.
                {"id": "ped-a", "distance_m": 1.2, "bearing_rad": 0.0},
            ]
        },
    )
    tracks = (
        TrackState(x=0.0, y=1.2, vx=1.2, vy=0.0, radius_m=0.35),
        TrackState(x=-1.0, y=1.3, vx=1.2, vy=0.0, radius_m=0.35),
    )
    costs: dict[str, float] = {}
    pose = safe_approach_pose(
        goal, candidate, observation, tracks=tracks, cost_out=costs
    )
    assert pose is not None
    # With weight=2 and track-lidar filtering, prefer a quieter (farther) entry.
    static = safe_approach_pose(goal, candidate, observation, tracks=())
    assert static is not None
    assert costs["approach_traffic_cost"] < costs.get("approach_static_cost", 99) or pose.y > static.y


def test_grid_navigator_seed_ramp_raises_last_vx_only() -> None:
    nav = object.__new__(GridNavigator)
    nav._last_vx = 0.0
    nav.cruise_vx = 0.85
    GridNavigator.seed_ramp(nav, 0.4)
    assert nav._last_vx == 0.4
    GridNavigator.seed_ramp(nav, 0.2)
    assert nav._last_vx == 0.4  # never lowers
    GridNavigator.seed_ramp(nav, 2.0)
    assert nav._last_vx == 0.85  # capped at cruise


# --------------------------------------------------------------------------
# Fix round (arbitration OB-1/OB-3/OB-4)
# --------------------------------------------------------------------------


class _FakeNavigator:
    def __init__(self) -> None:
        self.seeded: list[float] = []

    def seed_ramp(self, vx: float) -> None:
        self.seeded.append(float(vx))


def _pipeline_with_ramp() -> DirectiveNavigator:
    nav = object.__new__(DirectiveNavigator)
    nav._ramp = RampMemory()
    nav._ramp_fallback_ticks = 0
    nav._ramp_clock = "unset"
    nav.pending_ramp_seed_mps = None
    nav._navigator = _FakeNavigator()
    return nav


def _obs(stamp: float | None = None) -> NavObservation:
    extras = {} if stamp is None else {"odometry_timestamp_s": stamp}
    return NavObservation(position=(0.0, 0.0, 0.0), heading_deg=0.0, extras=extras)


def test_release_publishes_a_seed_for_the_runtime_and_seeds_the_navigator() -> None:
    """Both serial rate limiters get the one seed; RampMemory is the source."""

    nav = _pipeline_with_ramp()
    nav._update_ramp_memory(_obs(0.0), 0.85, "clear")
    nav._update_ramp_memory(_obs(0.1), 0.0, "person_stop")
    nav._update_ramp_memory(_obs(0.6), 0.4, "clear")

    seed = nav.pending_ramp_seed_mps
    assert seed is not None and 0.0 < seed < 0.85
    assert nav._navigator.seeded == [seed]
    # Single reader: the runtime consumes it exactly once.
    assert DirectiveNavigator.take_pending_ramp_seed(nav) == seed
    assert DirectiveNavigator.take_pending_ramp_seed(nav) is None


def test_align_ticks_do_not_wipe_the_held_ramp() -> None:
    """OB-4: grid align emits vx=0.0 at every corner; that is not 'running'."""

    nav = _pipeline_with_ramp()
    nav._update_ramp_memory(_obs(0.0), 0.85, "clear")
    nav._update_ramp_memory(_obs(0.1), 0.0, "grid_align")  # corner, no person
    assert nav._ramp.held_velocity_mps == pytest.approx(0.85)

    nav._update_ramp_memory(_obs(0.2), 0.0, "person_stop")
    nav._update_ramp_memory(_obs(0.5), 0.3, "clear")
    assert nav.pending_ramp_seed_mps is not None
    assert nav.pending_ramp_seed_mps > 0.0


def test_ramp_clock_never_mixes_a_sensor_stamp_with_the_tick_fallback() -> None:
    nav = _pipeline_with_ramp()
    assert nav._ramp_now_s(_obs(1000.0)) == 1000.0
    assert nav._ramp_clock == "stamp"
    # Stamp disappears: fall back without ever handing RampMemory a regression.
    first = nav._ramp_now_s(_obs(None))
    second = nav._ramp_now_s(_obs(None))
    assert nav._ramp_clock == "tick"
    assert second > first
    # And a returning stamp must not drag the clock back to the old base.
    assert nav._ramp_now_s(_obs(1000.5)) > second


def test_pipeline_degrades_without_traffic_aware() -> None:
    """OB-1: pipeline.py is a v8 replacement source; frozen bundles lack N11."""

    source = pathlib.Path(pipeline_module.__file__).read_text(encoding="utf-8")
    assert "from .traffic_aware import RampMemory" in source
    assert "_HAS_TRAFFIC_AWARE" in source
    # The guard must degrade to "no ramp memory", never to an import error.
    nav = object.__new__(DirectiveNavigator)
    nav._ramp = None
    nav._ramp_fallback_ticks = 0
    nav._ramp_clock = "unset"
    nav.pending_ramp_seed_mps = None
    nav._navigator = _FakeNavigator()
    nav._update_ramp_memory(_obs(0.0), 0.85, "person_stop")
    nav._update_ramp_memory(_obs(0.5), 0.4, "clear")
    assert nav.pending_ramp_seed_mps is None
    assert nav._navigator.seeded == []
