"""Card R10 item 4: the arrival table's LOCAL half, enforced by the planner.

The table can say ``do_not_cross`` and ``face=owner`` all it likes; these pin
that the PLANNER acts on it. Two behaviours, both owner policy and neither ever
reachable from a hosted tool argument:

* a portal terminal is never a pose inside the portal's own footprint — the
  robot stops AT the door, not IN it;
* an owner-facing semantic terminal first verifies the target-facing arrival,
  then turns in place and verifies owner heading without weakening that claim.

They are exercised through ``_apply_arrival_etiquette``, which is the single
seam ``_commit_semantic_candidate`` routes every committed pose through, so a
pose that reaches a mission has been through exactly this code.
"""

from __future__ import annotations

import math
import pathlib

import pytest

from parcel_robot.navigation import pipeline as pipeline_module
from parcel_robot.navigation.arrival_semantics import (
    CLASS_OBJECT,
    CLASS_PORTAL,
    FACE_OWNER,
    FACE_TRAVEL,
)
from parcel_robot.navigation.base import GoalPose, MidLevelCommand, NavObservation
from parcel_robot.navigation.goals import SemanticGoal
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.navigation.semantic_map import SemanticCandidate
from parcel_robot.skills.api import Dog

MODELS = pathlib.Path(__file__).resolve().parents[1] / "configs" / "navigation" / "models"
ROBOT_CONFIG = pathlib.Path(__file__).resolve().parents[1] / "configs" / "robot.yaml"

#: The owner, standing behind and to the left of the robot.
OWNER_XY = (-2.0, -1.0)

DOOR_POLYGON = ((0.8, 3.8), (1.2, 3.8), (1.2, 4.2), (0.8, 4.2))


def _navigator() -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
    )


def _observation(
    *,
    owner: bool = True,
    position: tuple[float, float] = (0.0, 0.0),
    heading_deg: float = 90.0,
    feedback_fresh: bool = True,
    settled: bool = True,
    nearest_person_m: float | None = None,
) -> NavObservation:
    extras: dict[str, object] = {
        "collision": False,
        "lidar_obstacles": [],
        "perception_fresh": True,
        "semantic_candidates": [],
        "motion_feedback": {
            "fresh": feedback_fresh,
            "stop_confirmed": settled,
            "linear_speed_mps": 0.0,
            "yaw_speed_rad_s": 0.0 if settled else 0.2,
            "settled_linear_speed_mps": 0.02,
            "settled_yaw_speed_rad_s": 0.03,
        },
    }
    if owner:
        extras["owner_track"] = (
            {"x": OWNER_XY[0], "y": OWNER_XY[1], "vx": 0.0, "vy": 0.0, "radius_m": 0.35},
        )
    return NavObservation(
        position=(position[0], position[1], 0.0),
        heading_deg=heading_deg,
        nearest_person_m=nearest_person_m,
        extras=extras,
    )


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


def _arm_owner_facing_arrival(navigator: DirectiveNavigator) -> SemanticGoal:
    semantic_goal = SemanticGoal(
        query="lamppost",
        kind="object",
        terminal_relation="near",
        place_class=CLASS_OBJECT,
        face=FACE_OWNER,
    )
    candidate = SemanticCandidate(
        candidate_id="lamp-1",
        label="lamppost",
        x=0.0,
        y=1.2,
        confidence=0.9,
        kind="object",
        metadata={
            "radius_m": 0.0,
            "minimum_vicinity_radius_m": 1.0,
            "vicinity_radius_m": 1.4,
        },
    )
    navigator.start("go to the lamppost")
    assert navigator.mission is not None
    approach = navigator._apply_arrival_etiquette(
        semantic_goal,
        candidate,
        _observation(),
        GoalPose(x=0.0, y=0.0, heading_deg=90.0, arrival_radius_m=0.1),
    )
    assert approach is not None
    navigator.mission.semantic_goal = semantic_goal
    navigator.mission.goal = approach
    navigator.mission.status = "verifying"
    navigator.mission.metadata.update(
        {
            "arrival_goal_region": navigator._build_arrival_goal_region(
                "near", candidate
            ),
            "support_polygon": (),
            "terminal_support_clearance_m": 0.32,
        }
    )
    return semantic_goal


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
def test_an_owner_facing_terminal_defers_the_turn_until_after_verification() -> None:
    navigator = _navigator()
    navigator.start("go to the door")
    beside = GoalPose(x=1.0, y=2.8, heading_deg=0.0)

    result = navigator._apply_arrival_etiquette(
        _door_goal(), _door_candidate(), _observation(), beside
    )

    assert result is not None
    assert result == beside
    assert navigator.mission is not None
    assert navigator.mission.metadata["arrival_face_applied"] == "deferred"
    assert navigator.mission.metadata["owner_face_phase"] == "approach_target"


def test_phase_a_uses_the_live_verifier_before_phase_b_and_phase_b_never_translates(
    monkeypatch,
) -> None:
    navigator = _navigator()
    _arm_owner_facing_arrival(navigator)
    verifier_calls: list[NavObservation] = []

    def verified(observation: NavObservation) -> bool:
        verifier_calls.append(observation)
        return True

    monkeypatch.setattr(navigator, "_semantic_arrival_verified", verified)
    started = navigator._step_terminal_verification(_observation())

    assert started.note == "owner_face_turn_started"
    assert verifier_calls == [_observation()]
    assert navigator.mission is not None
    assert navigator.mission.status == "running"
    assert navigator.mission.metadata["owner_face_phase_a_verified"] is True

    turning = navigator._step_owner_face_turn(_observation())

    assert turning.stop is False
    assert turning.vx == 0.0 and turning.vy == 0.0
    assert turning.vyaw != 0.0
    # Phase B deliberately has no live target in the frame. Its authority is
    # the exact Phase-A verifier above plus unchanged K0 geometry and no motion.
    assert verifier_calls == [_observation()]


def test_phase_b_rejects_any_controller_translation(
    monkeypatch,
) -> None:
    navigator = _navigator()
    _arm_owner_facing_arrival(navigator)
    monkeypatch.setattr(navigator, "_semantic_arrival_verified", lambda _: True)
    navigator._step_terminal_verification(_observation())
    monkeypatch.setattr(
        navigator._navigator,
        "act",
        lambda *_: MidLevelCommand(vx=0.01, vyaw=0.2, note="bad_translation"),
    )

    refused = navigator._step_owner_face_turn(_observation())

    assert navigator.mission is not None
    assert refused.stop is True
    assert refused.note == "owner_face_translation_proposed"
    assert navigator.mission.status == "failed"
    assert navigator.mission.metadata["owner_face_phase_a_verified"] is False
    assert (
        navigator.mission.metadata["owner_face_phase_a_invalidated_reason"]
        == "owner_face_translation_proposed"
    )


def test_phase_b_invalidates_the_latch_when_the_stop_ring_is_occupied(
    monkeypatch,
) -> None:
    navigator = _navigator()
    _arm_owner_facing_arrival(navigator)
    monkeypatch.setattr(navigator, "_semantic_arrival_verified", lambda _: True)
    navigator._step_terminal_verification(_observation())
    monkeypatch.setattr(
        navigator._navigator,
        "act",
        lambda *_: pytest.fail("unsafe environment must refuse before control"),
    )

    refused = navigator._step_owner_face_turn(
        _observation(nearest_person_m=0.1)
    )

    assert refused.stop is True
    assert refused.note == "owner_face_environment_invalidated"
    assert navigator.mission is not None
    assert navigator.mission.status == "failed"
    assert navigator.mission.metadata["owner_face_phase_a_verified"] is False
    assert navigator.mission.metadata["terminal_relation_verified"] is False
    assert (
        navigator.mission.metadata["owner_face_phase_a_invalidated_reason"]
        == "owner_face_environment_invalidated"
    )


@pytest.mark.parametrize(
    "invalid_vyaw",
    (float("nan"), float("inf"), float("-inf")),
    ids=("nan", "positive_inf", "negative_inf"),
)
def test_public_dog_never_publishes_non_finite_phase_b_yaw(
    monkeypatch,
    invalid_vyaw: float,
) -> None:
    navigator = _navigator()
    _arm_owner_facing_arrival(navigator)
    monkeypatch.setattr(navigator, "_semantic_arrival_verified", lambda _: True)
    navigator._step_terminal_verification(_observation())
    monkeypatch.setattr(
        navigator._navigator,
        "act",
        lambda *_: MidLevelCommand(vyaw=invalid_vyaw, note="invalid_yaw"),
    )
    published = []
    dog = Dog.from_config(ROBOT_CONFIG, on_velocity=published.append)
    dog._navigator = navigator
    dog.set_nav_pose((0.0, 0.0, 0.0), heading_deg=90.0)
    assert navigator.mission is not None

    mission, command = dog.navigate(
        navigator.mission.directive,
        extras=_observation().extras,
        publish=True,
    )

    assert command.stop is True
    assert command.note == "owner_face_yaw_non_finite"
    assert published == []
    assert mission.status == "failed"
    assert mission.metadata["owner_face_phase_a_verified"] is False
    assert mission.metadata["terminal_relation_verified"] is False


def test_public_dog_clamps_over_limit_phase_b_yaw_before_publish(monkeypatch) -> None:
    navigator = _navigator()
    navigator.safety["max_vyaw"] = 0.25
    _arm_owner_facing_arrival(navigator)
    monkeypatch.setattr(navigator, "_semantic_arrival_verified", lambda _: True)
    navigator._step_terminal_verification(_observation())
    monkeypatch.setattr(
        navigator._navigator,
        "act",
        lambda *_: MidLevelCommand(vyaw=4.0, note="over_limit_yaw"),
    )
    published = []
    dog = Dog.from_config(ROBOT_CONFIG, on_velocity=published.append)
    dog._navigator = navigator
    dog.set_nav_pose((0.0, 0.0, 0.0), heading_deg=90.0)
    assert navigator.mission is not None

    mission, command = dog.navigate(
        navigator.mission.directive,
        extras=_observation().extras,
        publish=True,
    )

    assert command.stop is False
    assert command.vx == 0.0 and command.vy == 0.0
    assert command.vyaw == 0.25
    assert len(published) == 1 and published[0].vyaw == 0.25
    assert mission.status == "running"
    assert mission.metadata["owner_face_phase_a_verified"] is True
    assert mission.metadata["owner_face_yaw_clamped"] is True
    assert mission.metadata["owner_face_proposed_vyaw"] == 4.0
    assert mission.metadata["owner_face_max_vyaw"] == 0.25


def test_phase_b_finishes_only_after_current_owner_heading_and_settle(monkeypatch) -> None:
    navigator = _navigator()
    _arm_owner_facing_arrival(navigator)
    monkeypatch.setattr(navigator, "_semantic_arrival_verified", lambda _: True)
    navigator._step_terminal_verification(_observation())
    owner_heading = math.degrees(math.atan2(OWNER_XY[1], OWNER_XY[0]))

    finished = navigator._step_owner_face_turn(
        _observation(heading_deg=owner_heading)
    )

    assert finished.stop is True and finished.note == "arrived_verified"
    assert navigator.mission is not None
    assert navigator.mission.status == "arrived"
    assert navigator.mission.metadata["owner_face_phase"] == "complete"
    assert navigator.mission.metadata["arrival_face_applied"] == FACE_OWNER


def test_failed_phase_a_never_latches_an_owner_facing_arrival(monkeypatch) -> None:
    navigator = _navigator()
    _arm_owner_facing_arrival(navigator)
    navigator.max_semantic_replans = 0
    monkeypatch.setattr(navigator, "_semantic_arrival_verified", lambda _: False)

    refused = navigator._step_terminal_verification(_observation())

    assert refused.note == "semantic_arrival_verification_failed"
    assert navigator.mission is not None
    assert navigator.mission.status == "failed"
    assert navigator.mission.metadata["owner_face_phase"] == "approach_target"
    assert "owner_face_phase_a_verified" not in navigator.mission.metadata


def test_recommit_clears_stale_pose_authority_metadata(monkeypatch) -> None:
    navigator = _navigator()
    navigator.start("go to the lamppost")
    assert navigator.mission is not None
    navigator.mission.metadata.update(
        {
            "approach_pose_source": "stale_source",
            "approach_preference_source": "stale_preference",
            "approach_refused_reason": "stale_refusal",
        }
    )
    goal = SemanticGoal(
        query="lamppost",
        kind="object",
        terminal_relation="near",
        place_class=CLASS_OBJECT,
        face=FACE_OWNER,
    )
    candidate = SemanticCandidate(
        candidate_id="lamp-1",
        label="lamppost",
        x=1.0,
        y=4.0,
        confidence=0.9,
        kind="object",
    )
    primary = GoalPose(x=0.3, y=2.8, heading_deg=60.0)
    monkeypatch.setattr(pipeline_module, "safe_approach_pose", lambda *_, **__: primary)

    navigator._commit_semantic_candidate(
        goal,
        candidate,
        _observation(),
        grounding_outcome="MEMORY_HIT",
    )

    assert navigator.mission.goal == primary
    assert navigator.mission.metadata["approach_pose_source"] == "support_gated"
    assert "approach_preference_source" not in navigator.mission.metadata
    assert "approach_refused_reason" not in navigator.mission.metadata


def test_an_untracked_owner_is_not_guessed_during_the_deferred_commit() -> None:
    navigator = _navigator()
    navigator.start("go to the door")
    beside = GoalPose(x=1.0, y=2.8, heading_deg=42.0)

    result = navigator._apply_arrival_etiquette(
        _door_goal(), _door_candidate(), _observation(owner=False), beside
    )

    assert result is not None
    assert result.heading_deg == 42.0
    assert navigator.mission is not None
    assert navigator.mission.metadata["arrival_face_applied"] == "deferred"


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


def test_an_object_terminal_also_defers_its_owner_turn() -> None:

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
    assert result.heading_deg == 0.0
    assert navigator.mission is not None
    assert navigator.mission.metadata["arrival_face_applied"] == "deferred"
