from __future__ import annotations

from pathlib import Path

import pytest

from parcel_robot.navigation import (
    DirectiveNavigator,
    GoalPose,
    Mission,
    ModelRegistry,
    NavObservation,
    PlaceGrounder,
    SemanticGoal,
    navigation_directive_from_text,
    semantic_goal_from_directive,
)

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "configs" / "navigation" / "models"
POIS = REPO / "configs" / "navigation" / "cities" / "demo_pois.yaml"


def _sidewalk_observation() -> NavObservation:
    return NavObservation(
        extras={
            "collision": False,
            "perception_fresh": True,
            "semantic_candidates": [
                {
                    "id": "sidewalk-test",
                    "label": "sidewalk",
                    "kind": "region",
                    "polygon": [[2.0, -1.0], [5.0, -1.0], [5.0, 1.0], [2.0, 1.0]],
                    "confidence": 0.99,
                    "reachable": True,
                }
            ]
        }
    )


#: Region ("stuff class") goals are *interchangeable*, and the 2026-08-07
#: region-instance arbitration forbids committing to the first instance that
#: confirms: with one instance in view, "which sidewalk is nearest" is not
#: answerable until the robot has looked around. `ActiveSemanticSearch.observe`
#: therefore withholds the commit until the sweep completes, bounded by
#: `scan_budget_steps` (80), where these cases used to commit on the second
#: sighting. Every case below re-checks its own subject — the watchdog and the
#: three terminal-verification behaviours — unchanged, after the sweep; only the
#: number of ticks it takes to *get* a goal moved.
REGION_SWEEP_BUDGET_STEPS = 80


def _resolve_region_goal(navigator, observation, *, budget: int = REGION_SWEEP_BUDGET_STEPS):
    """Drive the interchangeable-goal sweep to its commit."""

    for _ in range(budget):
        navigator.step(observation)
        if navigator.mission is not None and navigator.mission.goal is not None:
            return
    raise AssertionError(
        f"region goal never committed inside the {budget}-step sweep budget"
    )


def test_progress_watchdog_replans_then_fails_closed_instead_of_running_forever():
    navigator = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        progress_timeout_steps=10,
        max_semantic_replans=1,
    )
    mission = navigator.start("walk to the sidewalk")
    observation = _sidewalk_observation()
    _resolve_region_goal(navigator, observation)

    first_attempt = [navigator.step(observation) for _ in range(10)]

    assert first_attempt[-1].note == "semantic_replan_after_no_progress"
    assert mission.status == "searching"
    assert mission.goal is None
    assert mission.metadata["replan_count"] == 1

    # The replan resets the search, so the second attempt pays the sweep again.
    _resolve_region_goal(navigator, observation)
    second_attempt = [navigator.step(observation) for _ in range(10)]

    assert second_attempt[-1].stop
    assert second_attempt[-1].note == "navigation_no_progress"
    assert mission.status == "failed"


def test_terminal_verification_fails_closed_without_measured_stop_feedback():
    navigator = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        terminal_stop_timeout_steps=2,
        max_semantic_replans=0,
    )
    mission = navigator.start("walk to the sidewalk")
    observation = _sidewalk_observation()
    _resolve_region_goal(navigator, observation)
    assert mission.goal is not None
    at_goal = NavObservation(
        position=(mission.goal.x, mission.goal.y, 0.0),
        heading_deg=mission.goal.heading_deg,
        extras=observation.extras,
    )

    requested = navigator.step(at_goal)
    failed = navigator.step(at_goal)

    assert requested.stop and requested.note == "semantic_stop_requested"
    assert failed.stop and failed.note == "terminal_stop_not_confirmed"
    assert mission.status == "failed"


def test_terminal_verification_rejects_stale_semantic_perception():
    navigator = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        max_semantic_replans=0,
    )
    mission = navigator.start("walk to the sidewalk")
    observation = _sidewalk_observation()
    _resolve_region_goal(navigator, observation)
    assert mission.goal is not None
    stale_extras = {
        **observation.extras,
        "perception_fresh": False,
        "motion_feedback": {
            "fresh": True,
            "stop_confirmed": True,
            "linear_speed_mps": 0.0,
            "yaw_speed_rad_s": 0.0,
            "settled_linear_speed_mps": 0.08,
            "settled_yaw_speed_rad_s": 0.12,
        },
    }

    result = navigator.step(
        NavObservation(
            position=(mission.goal.x, mission.goal.y, 0.0),
            heading_deg=mission.goal.heading_deg,
            extras=stale_extras,
        )
    )

    assert result.stop
    assert result.note == "semantic_arrival_verification_failed"
    assert mission.status == "failed"
    assert mission.metadata["terminal_relation_verified"] is False


def test_terminal_verification_checks_nearest_obstacle_when_lidar_list_is_empty():
    navigator = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        max_semantic_replans=0,
    )
    mission = navigator.start("walk to the sidewalk")
    observation = _sidewalk_observation()
    _resolve_region_goal(navigator, observation)
    assert mission.goal is not None
    blocked_extras = {
        **observation.extras,
        "lidar_obstacles": [],
        "obstacle_id": None,
        "motion_feedback": {
            "fresh": True,
            "stop_confirmed": True,
            "linear_speed_mps": 0.0,
            "yaw_speed_rad_s": 0.0,
            "settled_linear_speed_mps": 0.08,
            "settled_yaw_speed_rad_s": 0.12,
        },
    }

    result = navigator.step(
        NavObservation(
            position=(mission.goal.x, mission.goal.y, 0.0),
            heading_deg=mission.goal.heading_deg,
            nearest_obstacle_m=0.1,
            extras=blocked_extras,
        )
    )

    assert result.stop
    assert result.note == "semantic_arrival_verification_failed"
    assert mission.status == "failed"
    assert mission.metadata["terminal_relation_verified"] is False


@pytest.mark.parametrize(
    "directive",
    [
        "don't go to the coffee shop at 42nd street",
        "Don’t go to the coffee shop at 42nd street",
        "suppose you go to the coffee shop at 42nd street",
    ],
)
def test_direct_navigator_api_rejects_non_authoritative_known_poi_language(directive: str):
    navigator = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder.from_yaml(POIS),
    )

    with pytest.raises(ValueError, match="negated or hypothetical"):
        navigator.start(directive)


def test_sentence_boundary_rationale_preserves_sidewalk_region_goal():
    directive = navigation_directive_from_text(
        "Can you go to the sidewalk? It's dangerous on the road."
    )

    assert directive == "go to the sidewalk"
    goal = semantic_goal_from_directive(directive)
    assert (goal.query, goal.kind, goal.terminal_relation) == (
        "sidewalk",
        "region",
        "inside",
    )


def test_near_target_excludes_camera_associated_lidar_identity_from_avoidance():
    registry = ModelRegistry.load(MODELS)
    controller = registry.create("stub_v0", arrive_radius_m=0.1)
    mission = Mission(
        directive="wait by the lamp",
        goal=GoalPose(2.0, 0.0, arrival_radius_m=0.1),
        semantic_goal=SemanticGoal("lamp", kind="object", terminal_relation="near"),
        metadata={
            "candidate_id": "camera-lamp-track-7",
            "associated_lidar_ids": ["lidar-post-12"],
        },
    )
    controller.reset(mission)

    command = controller.act(
        NavObservation(
            extras={
                "lidar_obstacles": [
                    {
                        "id": "lidar-post-12",
                        "distance_m": 0.4,
                        "bearing_rad": 0.0,
                    }
                ]
            }
        ),
        mission,
    )

    assert "avoid" not in command.note
    assert "goal" in command.note
