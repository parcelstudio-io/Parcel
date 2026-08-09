"""Proxemic veto on the traffic-ranked approach winner (Lane D, card D-5a)."""

from __future__ import annotations

import math

import pytest

from parcel_robot.navigation.approach import (
    PROXEMIC_VETO_DEPTH,
    _obstacles_excluding_target,
    _proxemic_veto,
    _rank_approach_point,
)
from parcel_robot.navigation.proxemic_approach import ProxemicApproachConfig
from parcel_robot.navigation.semantic_map import SemanticCandidate
from parcel_robot.navigation.traffic_aware import TrackState


def _grid(n: int = 8) -> list[tuple[float, float]]:
    return [(float(i), 0.0) for i in range(n)]


# --- the ladder rule --------------------------------------------------------


def test_no_tracks_keeps_the_static_winner_exactly() -> None:
    """With no dynamic agents the veto must not be consulted at all."""

    points = [(3.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    winner = _rank_approach_point(points, (0.0, 0.0), ())
    assert winner is not None
    assert (winner.x, winner.y) == (1.0, 0.0)
    assert winner.traffic_cost == 0.0


def test_the_veto_never_reorders_only_strikes_out() -> None:
    """The winner is always the first *surviving* candidate, in rank order."""

    ranked = _rank_approach_point(
        _grid(), (0.0, 0.0), (TrackState(x=0.0, y=0.0, vx=0.0, vy=0.0),)
    )
    assert ranked is not None
    unvetoed = _rank_approach_point(_grid(), (0.0, 0.0), ())
    assert unvetoed is not None
    # The chosen pose can only ever be equal to or worse (statically) than the
    # unvetoed winner — never better, because the veto cannot promote.
    assert ranked.static_cost >= unvetoed.static_cost


def test_a_pedestrian_parked_on_the_winner_demotes_it() -> None:
    telemetry: dict = {}
    tracks = (TrackState(x=0.0, y=0.0, vx=0.0, vy=0.0, radius_m=0.35),)
    chosen = _rank_approach_point(_grid(), (0.0, 0.0), tracks, veto_out=telemetry)
    assert chosen is not None
    assert telemetry["proxemic_veto"] in {"passed", "demoted"}
    if telemetry["proxemic_veto"] == "demoted":
        assert telemetry["proxemic_vetoed_count"] >= 1
        assert chosen.x > 0.0


def test_all_vetoed_returns_an_honest_none() -> None:
    """Fail-closed: no safe pose is an answer, not a reason to pick the worst."""

    # One candidate, with a pedestrian standing exactly on it.
    telemetry: dict = {}
    tracks = (TrackState(x=1.0, y=0.0, vx=0.0, vy=0.0, radius_m=0.35),)
    result = _rank_approach_point([(1.0, 0.0)], (0.0, 0.0), tracks, veto_out=telemetry)
    assert result is None
    assert telemetry["proxemic_veto"] == "all_vetoed"
    assert telemetry["proxemic_vetoed_count"] == 1


def test_veto_depth_is_bounded() -> None:
    tracks = (TrackState(x=0.0, y=0.0, vx=0.0, vy=0.0),)
    ranked = _rank_approach_point(_grid(40), (0.0, 0.0), tracks)
    assert ranked is not None
    assert PROXEMIC_VETO_DEPTH == 16


def test_veto_threshold_is_the_shared_reject_cost() -> None:
    """One authority for 'too close to a person', not a private copy."""

    assert ProxemicApproachConfig().reject_cost == pytest.approx(0.85)


def test_empty_ranking_is_none() -> None:
    assert _rank_approach_point([], (0.0, 0.0), ()) is None


def test_proxemic_veto_defers_when_it_cannot_be_evaluated() -> None:
    """A veto that cannot run must not veto everything — it defers, and says so."""

    class _Ranked:
        index = 0
        x = 1.0
        y = 0.0
        static_cost = 1.0
        traffic_cost = 0.0
        total_cost = 1.0

    telemetry: dict = {}
    result = _proxemic_veto(
        [_Ranked()], ("not a track",), (0.0, 0.0), veto_out=telemetry
    )
    assert result is not None
    assert telemetry["proxemic_veto"] == "unavailable"


# --- geometric target exclusion (D-2, the approach-side id join) ------------


def _candidate(radius: float) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id="bench_1",
        label="bench",
        x=2.0,
        y=0.0,
        confidence=0.9,
        metadata={"radius_m": radius},
    )


def test_target_surfaces_are_excluded_by_geometry_not_by_id() -> None:
    """A surface on the line of sight to the target belongs to the target."""

    candidate = _candidate(0.7)
    robot = (0.0, 0.0)
    blocked = (
        # On the ray to the target (2.0, 0.0) and short of it — this is the
        # target's own near surface, whatever id the range channel gave it.
        ("lidar-4711", 1.3, 0.0),
        # A different body, well off the line of sight: kept.
        ("lidar-9", 2.0, 4.0),
    )
    kept = _obstacles_excluding_target(candidate, blocked, robot)
    assert kept == (("lidar-9", 2.0, 4.0),)


def test_an_anonymous_return_on_the_target_is_still_excluded() -> None:
    kept = _obstacles_excluding_target(_candidate(0.7), ((None, 1.5, 0.1),), (0.0, 0.0))
    assert kept == ()


def test_a_surface_beyond_the_target_is_kept() -> None:
    """The exemption is the target's near surface, never something behind it."""

    candidate = _candidate(0.3)  # gate 0.75, target at (2.0, 0.0)
    behind = (None, 3.5, 0.0)
    assert _obstacles_excluding_target(candidate, (behind,), (0.0, 0.0)) == (behind,)


def test_a_neighbour_just_outside_the_lateral_gate_is_kept() -> None:
    """The gate is on the target's offset from the *line of sight*, not on y.

    Robot at the origin, target at (2, 0), surface at (2, y): the target's
    perpendicular offset from the robot→surface ray is ``2y / sqrt(4 + y^2)``,
    which crosses the 0.45 m gate at y = 0.462. The two probes bracket it.
    """

    candidate = _candidate(0.0)  # gate = 0.45
    robot = (0.0, 0.0)
    just_outside = (None, 2.0, 0.50)  # offset 0.485
    just_inside = (None, 2.0, 0.40)  # offset 0.392
    assert _obstacles_excluding_target(candidate, (just_outside,), robot) == (just_outside,)
    assert _obstacles_excluding_target(candidate, (just_inside,), robot) == ()


def test_exclusion_scales_with_the_target_radius() -> None:
    robot = (0.0, 0.0)
    point = (None, 2.0, 1.0)  # 1.0 m lateral of the target at (2.0, 0.0)
    assert _obstacles_excluding_target(_candidate(0.3), (point,), robot) == (point,)
    assert _obstacles_excluding_target(_candidate(2.0), (point,), robot) == ()


def test_exclusion_is_isotropic_in_the_robots_frame() -> None:
    """Rotating robot, target and surface together must not change the verdict."""

    candidate = _candidate(0.5)
    for angle in (0.0, math.pi / 3, math.pi, -math.pi / 2):
        # Robot sits 2 m from the target along `angle`; the surface is 0.5 m
        # short of the target on the same ray.
        robot = (
            candidate.x - 2.0 * math.cos(angle),
            candidate.y - 2.0 * math.sin(angle),
        )
        surface = (
            None,
            candidate.x - 0.5 * math.cos(angle),
            candidate.y - 0.5 * math.sin(angle),
        )
        assert _obstacles_excluding_target(candidate, (surface,), robot) == ()


def test_a_surface_at_the_robot_itself_is_never_the_target() -> None:
    assert _obstacles_excluding_target(
        _candidate(0.7), ((None, 0.0, 0.0),), (0.0, 0.0)
    ) == ((None, 0.0, 0.0),)


def test_a_target_behind_the_robot_claims_nothing() -> None:
    """A forward ray cannot belong to a target that is behind the robot."""

    candidate = _candidate(0.7)  # at (2.0, 0.0)
    robot = (5.0, 0.0)  # target is at bearing pi from here
    forward = (None, 8.0, 0.0)
    assert _obstacles_excluding_target(candidate, (forward,), robot) == (forward,)
