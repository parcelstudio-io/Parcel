"""Card R10 item 1: in-region goal resampling, and the defect it removes.

THE DEFECT, REPRODUCED
----------------------
A region (``inside``) goal had no second-chance pose solver. ``safe_approach_pose``
tries a coarse inset grid and then one nearest-inset point, and BOTH require the
straight ROBOT→POINT segment to be clear of observed surfaces. One pedestrian
standing between the robot and the sidewalk disqualifies every interior sample
at the same instant — and ``_fallback_near_arrival_pose`` is gated to
``near``/``next_to``, so nothing else ever ran. The mission released the only
instance it had and reported ``semantic_target_unreachable`` while standing two
metres from a perfectly walkable sidewalk.

``test_a_person_between_the_robot_and_the_region_used_to_make_it_unreachable``
is that live failure in miniature: it asserts the OLD path finds nothing and the
resampler finds something, in the same call.

WHAT MUST NOT MOVE
------------------
The resampler relaxes the straight-line heuristic and NOTHING else. Every test
below that begins ``test_the_resampler_never_`` is a safety direction, and each
is written so that weakening the corresponding filter reddens it.
"""

from __future__ import annotations

import math

from parcel_robot.authority import DEFAULT_STAND_OFF_ENVELOPE
from parcel_robot.navigation.approach import (
    _safe_polygon_point,
    resample_inside_region,
    safe_approach_pose,
)
from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.goals import SemanticGoal
from parcel_robot.navigation.semantic_map import SemanticCandidate
from parcel_robot.navigation.traffic_aware import TrackState

FOOTPRINT = DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m

#: A 2.4 m-wide sidewalk corridor running away from the robot — the live shape
#: (a strip flanked by furniture), not a plaza with lateral escapes.
SIDEWALK = ((-1.2, 2.0), (1.2, 2.0), (1.2, 8.0), (-1.2, 8.0))
ROBOT = (0.0, 0.0)

#: A parked van broadside across the sightline at y = 1.3 m. Static: it is a
#: SURFACE, so it is not pruned as a dynamic track, and it disqualifies every
#: interior sample at once through the straight-segment test.
VAN = tuple(
    {
        "distance_m": math.hypot(x, 1.3) - FOOTPRINT,
        "bearing_rad": math.atan2(x, 1.3),
        "obstacle_id": "van",
    }
    for x in (-1.0, -0.6, -0.2, 0.2, 0.6, 1.0)
)


def _observation(lidar: tuple[dict[str, float], ...] = ()) -> NavObservation:
    return NavObservation(
        position=(ROBOT[0], ROBOT[1], 0.0),
        heading_deg=90.0,
        extras={"lidar_obstacles": list(lidar)},
    )


def _region_goal() -> SemanticGoal:
    return SemanticGoal(query="sidewalk", kind="region", terminal_relation="inside")


def _candidate() -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id="sidewalk-1",
        label="sidewalk",
        x=0.0,
        y=4.0,
        confidence=0.9,
        kind="region",
        polygon=SIDEWALK,
    )


# ============================================================ the defect itself
def test_an_occluded_sightline_alone_defeats_the_coarse_interior_sampler() -> None:
    """Tier 1's straight-segment test loses the WHOLE region to one van."""

    surfaces = tuple(("van", x, 1.3) for x in (-1.0, -0.6, -0.2, 0.2, 0.6, 1.0))
    assert (
        _safe_polygon_point(
            SIDEWALK,
            ROBOT,
            FOOTPRINT + 0.12,
            blocked_points=surfaces,
            obstacle_clearance=1.14,
        )
        is None
    ), "if this stops being None the defect is no longer reproduced"


def test_the_live_failure_shape_now_ends_inside_the_region() -> None:
    """The 2026-08-18 mission, in miniature.

    A static occlusion defeats the coarse sampler (tier 1) and a pedestrian
    standing on the nearest inset point defeats the single tier-2 retry through
    the proxemic veto. Before R10 that combination WAS
    ``semantic_target_unreachable``, because ``_fallback_near_arrival_pose`` is
    gated to near/next_to and nothing else ran for a region goal.
    """

    person = (TrackState(x=0.0, y=2.45, vx=0.0, vy=0.0, radius_m=0.45),)
    costs: dict[str, object] = {}
    pose = safe_approach_pose(
        _region_goal(),
        _candidate(),
        _observation(VAN),
        footprint_clearance_m=FOOTPRINT,
        obstacle_stop_m=0.65,
        tracks=person,
        cost_out=costs,
    )
    assert pose is not None, "the sidewalk is walkable; the mission must not give up"
    # It was the RESAMPLER that supplied it — tiers 1 and 2 both failed.
    assert int(costs["inside_resample_candidates"]) > 0
    # And the robot ends with its whole body inside the region…
    assert 2.0 + FOOTPRINT <= pose.y <= 8.0 - FOOTPRINT
    assert -1.2 + FOOTPRINT <= pose.x <= 1.2 - FOOTPRINT
    # …and clear of the person who caused the veto.
    assert math.hypot(pose.x - 0.0, pose.y - 2.45) >= 0.45


def test_without_the_person_the_shipped_tiers_still_answer_unchanged() -> None:
    """The resampler is a FALLBACK. It must not take work off the old path."""

    costs: dict[str, object] = {}
    pose = safe_approach_pose(
        _region_goal(),
        _candidate(),
        _observation(VAN),
        footprint_clearance_m=FOOTPRINT,
        obstacle_stop_m=0.65,
        cost_out=costs,
    )
    assert pose is not None
    assert "inside_resample_candidates" not in costs


# ==================================================== safety directions (hard)
def test_the_resampler_never_returns_a_point_inside_a_person_keepout() -> None:
    """People veto absolutely, at any clearance. The old path never checked."""

    keepout = (("someone", 0.0, 4.0, 2.5),)
    points = resample_inside_region(
        SIDEWALK,
        ROBOT,
        approach_clearance=FOOTPRINT,
        obstacle_clearance=0.4,
        keepouts=keepout,
    )
    assert points
    for x, y in points:
        assert math.hypot(x - 0.0, y - 4.0) >= 2.5


def test_the_resampler_never_returns_a_point_inside_the_obstacle_clearance() -> None:
    surfaces = (("bollard", 0.0, 4.0), ("bollard", 1.0, 3.0))
    clearance = 1.1
    points = resample_inside_region(
        SIDEWALK,
        ROBOT,
        approach_clearance=FOOTPRINT,
        obstacle_clearance=clearance,
        blocked_points=surfaces,
    )
    assert points
    for x, y in points:
        for _label, sx, sy in surfaces:
            assert math.hypot(x - sx, y - sy) >= clearance


def test_the_resampler_never_puts_the_body_outside_the_region() -> None:
    """An ``inside`` terminal means the FOOTPRINT is contained, not the centre."""

    points = resample_inside_region(
        SIDEWALK, ROBOT, approach_clearance=FOOTPRINT, obstacle_clearance=0.4
    )
    assert points
    for x, y in points:
        assert 2.0 + FOOTPRINT - 1e-9 <= y <= 8.0 - FOOTPRINT + 1e-9
        assert -1.2 + FOOTPRINT - 1e-9 <= x <= 1.2 - FOOTPRINT + 1e-9


def test_the_inset_ladder_never_descends_below_the_footprint_radius() -> None:
    attempts: list[dict[str, object]] = []
    resample_inside_region(
        SIDEWALK,
        ROBOT,
        approach_clearance=FOOTPRINT * 3.0,
        obstacle_clearance=0.4,
        footprint_clearance_m=FOOTPRINT,
        # Nothing is admissible, so every rung of the ladder is walked.
        keepouts=(("wall", 0.0, 4.0, 50.0),),
        attempts_out=attempts,
    )
    assert attempts
    for row in attempts:
        assert float(row["inset_m"]) >= FOOTPRINT - 1e-9


def test_a_genuinely_boxed_in_region_still_returns_nothing() -> None:
    """The fallback must not become a way to say yes to an impossible goal."""

    points = resample_inside_region(
        SIDEWALK,
        ROBOT,
        approach_clearance=FOOTPRINT,
        obstacle_clearance=0.4,
        keepouts=(("crowd", 0.0, 4.0, 50.0),),
    )
    assert points == ()


# ============================================================= the give-up says why
def test_the_give_up_names_every_candidate_it_tried() -> None:
    """Card: *the give-up names the candidates tried*."""

    attempts: list[dict[str, object]] = []
    points = resample_inside_region(
        SIDEWALK,
        ROBOT,
        approach_clearance=FOOTPRINT,
        obstacle_clearance=0.4,
        keepouts=(("crowd", 0.0, 4.0, 50.0),),
        attempts_out=attempts,
    )
    assert points == ()
    assert attempts, "an unexplained give-up is the thing this replaces"
    for row in attempts:
        # Enough to answer "what did you try, and what rejected it?"
        assert {
            "inset_m",
            "obstacle_clearance_m",
            "considered",
            "blocked_by_person_keepout",
            "admitted",
        } <= set(row)
        assert int(row["considered"]) > 0
        assert int(row["blocked_by_person_keepout"]) > 0
        assert int(row["admitted"]) == 0


def test_the_attempts_reach_the_solvers_cost_channel() -> None:
    """So the pipeline can put them on the mission for the refusal to read."""

    person = (TrackState(x=0.0, y=2.45, vx=0.0, vy=0.0, radius_m=0.45),)
    costs: dict[str, object] = {}
    safe_approach_pose(
        _region_goal(),
        _candidate(),
        _observation(VAN),
        footprint_clearance_m=FOOTPRINT,
        obstacle_stop_m=0.65,
        tracks=person,
        cost_out=costs,
    )
    attempts = costs.get("inside_resample_attempts")
    assert attempts, "the pipeline reads this to name what it tried"
    assert int(costs["inside_resample_candidates"]) > 0


def test_a_degenerate_polygon_is_reported_and_not_a_crash() -> None:
    attempts: list[dict[str, object]] = []
    assert (
        resample_inside_region(
            ((0.0, 0.0), (1.0, 0.0)),
            ROBOT,
            approach_clearance=FOOTPRINT,
            obstacle_clearance=0.4,
            attempts_out=attempts,
        )
        == ()
    )
    assert attempts and attempts[0]["rejected"] == "polygon_degenerate"
