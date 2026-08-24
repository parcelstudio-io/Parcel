"""Card R10 item 4: the arrival table's LOCAL half, enforced by the planner.

The table can say ``do_not_cross`` and ``face=owner`` all it likes; these pin
that the PLANNER acts on it. Two behaviours, both owner policy and neither ever
reachable from a hosted tool argument:

* a portal terminal is never a pose inside the portal's own footprint — the
  robot stops AT the door, not IN it;
* an object/portal terminal ends with the body turned back toward the owner,
  which the bench measured the model getting wrong 6/6 on both tiers and which
  REALM says no distance criterion will ever induce on its own.

They are exercised through ``_apply_arrival_etiquette``, which is the single
seam ``_commit_semantic_candidate`` routes every committed pose through, so a
pose that reaches a mission has been through exactly this code.
"""

from __future__ import annotations

import math
import pathlib

from parcel_robot.navigation.arrival_semantics import (
    CLASS_OBJECT,
    CLASS_PORTAL,
    FACE_OWNER,
    FACE_TRAVEL,
)
from parcel_robot.navigation.base import GoalPose, NavObservation
from parcel_robot.navigation.goals import SemanticGoal
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.navigation.semantic_map import SemanticCandidate

MODELS = pathlib.Path(__file__).resolve().parents[1] / "configs" / "navigation" / "models"

#: The owner, standing behind and to the left of the robot.
OWNER_XY = (-2.0, -1.0)

DOOR_POLYGON = ((0.8, 3.8), (1.2, 3.8), (1.2, 4.2), (0.8, 4.2))


def _navigator() -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
    )


def _observation(*, owner: bool = True) -> NavObservation:
    extras: dict[str, object] = {"lidar_obstacles": []}
    if owner:
        extras["owner_track"] = (
            {"x": OWNER_XY[0], "y": OWNER_XY[1], "vx": 0.0, "vy": 0.0, "radius_m": 0.35},
        )
    return NavObservation(position=(0.0, 0.0, 0.0), heading_deg=90.0, extras=extras)


def _door_goal() -> SemanticGoal:
    return SemanticGoal(
        query="door",
        kind="object",
        terminal_relation="near",
        place_class=CLASS_PORTAL,
        face=FACE_OWNER,
        do_not_cross=True,
        ask_hint="ask the owner what they would like to do next",
    )


def _door_candidate() -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id="door-1",
        label="door",
        x=1.0,
        y=4.0,
        confidence=0.9,
        kind="object",
        polygon=DOOR_POLYGON,
    )


# ================================================================ do-not-cross
def test_a_terminal_pose_inside_the_doorway_is_refused() -> None:
    navigator = _navigator()
    navigator.start("go to the door")
    inside_the_threshold = GoalPose(x=1.0, y=4.0, heading_deg=0.0)

    result = navigator._apply_arrival_etiquette(
        _door_goal(), _door_candidate(), _observation(), inside_the_threshold
    )

    assert result is None, "the robot must stop AT the door, never in it"
    assert navigator.mission is not None
    assert (
        navigator.mission.metadata["arrival_refused_reason"]
        == "portal_terminal_inside_threshold"
    )


def test_a_pose_beside_the_doorway_is_kept() -> None:
    """The guard refuses the threshold, not the errand."""

    navigator = _navigator()
    navigator.start("go to the door")
    beside = GoalPose(x=1.0, y=2.8, heading_deg=0.0)

    result = navigator._apply_arrival_etiquette(
        _door_goal(), _door_candidate(), _observation(), beside
    )

    assert result is not None
    assert (result.x, result.y) == (1.0, 2.8)


# ============================================================== face the owner
def test_an_owner_facing_terminal_turns_the_body_back_to_the_owner() -> None:
    navigator = _navigator()
    navigator.start("go to the door")
    beside = GoalPose(x=1.0, y=2.8, heading_deg=0.0)

    result = navigator._apply_arrival_etiquette(
        _door_goal(), _door_candidate(), _observation(), beside
    )

    assert result is not None
    expected = math.degrees(math.atan2(OWNER_XY[1] - 2.8, OWNER_XY[0] - 1.0))
    assert result.heading_deg == expected
    assert navigator.mission is not None
    assert navigator.mission.metadata["arrival_face_applied"] == FACE_OWNER


def test_an_untracked_owner_leaves_the_heading_alone_rather_than_guessing() -> None:
    navigator = _navigator()
    navigator.start("go to the door")
    beside = GoalPose(x=1.0, y=2.8, heading_deg=42.0)

    result = navigator._apply_arrival_etiquette(
        _door_goal(), _door_candidate(), _observation(owner=False), beside
    )

    assert result is not None
    assert result.heading_deg == 42.0
    assert navigator.mission is not None
    assert navigator.mission.metadata["arrival_face_applied"] == "unavailable"


def test_a_region_terminal_is_left_facing_its_travel_direction() -> None:
    """face=travel means "do not turn me", not "turn me somewhere else"."""

    navigator = _navigator()
    navigator.start("go to the sidewalk")
    goal = SemanticGoal(
        query="sidewalk",
        kind="region",
        terminal_relation="inside",
        face=FACE_TRAVEL,
    )
    candidate = SemanticCandidate(
        candidate_id="sidewalk-1",
        label="sidewalk",
        x=0.0,
        y=4.0,
        confidence=0.9,
        kind="region",
        polygon=((-2.0, 2.0), (2.0, 2.0), (2.0, 6.0), (-2.0, 6.0)),
    )
    pose = GoalPose(x=0.0, y=3.0, heading_deg=90.0)

    result = navigator._apply_arrival_etiquette(goal, candidate, _observation(), pose)

    assert result is not None
    assert result.heading_deg == 90.0


def test_an_object_terminal_also_turns_back_to_the_owner() -> None:
    """Not just doors: any errand the owner sent the robot on ends facing them."""

    navigator = _navigator()
    navigator.start("go to the bench")
    goal = SemanticGoal(
        query="bench",
        kind="object",
        terminal_relation="near",
        place_class=CLASS_OBJECT,
        face=FACE_OWNER,
    )
    candidate = SemanticCandidate(
        candidate_id="bench-1", label="bench", x=3.0, y=3.0, confidence=0.9
    )
    pose = GoalPose(x=2.0, y=2.0, heading_deg=0.0)

    result = navigator._apply_arrival_etiquette(goal, candidate, _observation(), pose)

    assert result is not None
    assert result.heading_deg == math.degrees(
        math.atan2(OWNER_XY[1] - 2.0, OWNER_XY[0] - 2.0)
    )
