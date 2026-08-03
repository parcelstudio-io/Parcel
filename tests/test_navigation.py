from __future__ import annotations

from pathlib import Path

import pytest

from parcel_robot.navigation import (
    DirectiveNavigator,
    MetaUrbanNavEnv,
    MidLevelCommand,
    ModelRegistry,
    NavObservation,
    PlaceGrounder,
)
from parcel_robot.navigation.collision import apply_collision_brake
from parcel_robot.skills import Dog

REPO = Path(__file__).resolve().parents[1]
NAV_CFG = REPO / "configs" / "navigation" / "default.yaml"
POIS = REPO / "configs" / "navigation" / "cities" / "demo_pois.yaml"
MODELS = REPO / "configs" / "navigation" / "models"


def test_registry_lists_multiple_model_types():
    reg = ModelRegistry.load(MODELS)
    ids = set(reg.ids())
    assert "stub_v0" in ids
    assert "citywalker_v1" in ids
    assert "navila_v1" in ids
    assert "nomad_v1" in ids
    assert "vint_v1" in ids
    assert any(s.type == "navila" for s in reg.list())


def test_ground_coffee_42nd():
    g = PlaceGrounder.from_yaml(POIS)
    goal = g.ground("I want you to go to the coffee shop at 42nd street")
    assert goal.poi_id == "coffee_42nd"
    assert goal.x == pytest.approx(42.0)


def test_directive_navigator_stub_aligns_then_moves_toward_goal():
    nav = DirectiveNavigator.from_config(NAV_CFG)
    mission = nav.start("go to the coffee shop at 42nd street")
    assert mission.goal.poi_id == "coffee_42nd"
    cmd = nav.step(NavObservation(position=(0.0, 0.0, 0.0), heading_deg=0.0))
    assert not cmd.stop
    assert cmd.vx == 0.0
    assert cmd.vy == 0.0
    assert cmd.vyaw > 0.0
    assert "align_goal" in cmd.note
    aligned = nav.step(NavObservation(position=(0.0, 0.0, 0.0), heading_deg=11.4))
    assert aligned.vx > 0.0
    assert aligned.vy == 0.0
    assert "track_goal" in aligned.note
    nav.close()


def test_directive_navigator_turns_away_from_close_obstacle():
    nav = DirectiveNavigator.from_config(NAV_CFG)
    nav.start("go to the crosswalk")
    command = nav.step(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_obstacle_m=0.5,
            extras={"obstacle_bearing_rad": 0.2},
        )
    )

    assert command.vx == 0.0
    assert command.vyaw < 0.0
    assert "obstacle_stop" in command.note
    nav.close()


@pytest.mark.parametrize("clearance", [None, 1.5])
def test_stub_exits_avoidance_without_a_bearing_when_obstacle_clears(clearance):
    nav = DirectiveNavigator.from_config(NAV_CFG)
    nav.start("go to the crosswalk")
    avoiding = nav.step(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_obstacle_m=0.5,
            extras={"obstacle_bearing_rad": 0.2},
        )
    )
    assert "align_avoid" in avoiding.note

    resumed = nav.step(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_obstacle_m=clearance,
            extras={},
        )
    )

    assert "align_goal" in resumed.note
    assert "avoid" not in resumed.note
    nav.close()


def test_collision_brake_stops_for_nearby_person():
    vx, vy, note = apply_collision_brake(0.5, 0.0, nearest_person_m=0.5, nearest_obstacle_m=None)
    assert vx == 0.0 and vy == 0.0
    assert note == "person_stop"


def test_collision_brake_allows_motion_away_from_obstacle():
    vx, vy, note = apply_collision_brake(
        0.3,
        0.0,
        nearest_person_m=None,
        nearest_obstacle_m=0.4,
        nearest_obstacle_bearing_rad=2.0,
    )

    assert (vx, vy, note) == (0.3, 0.0, "clear")


def test_navigation_pipeline_preserves_intentional_lateral_motion():
    class LateralNavigator:
        def reset(self, mission):
            mission.status = "running"

        def act(self, observation, mission):
            return MidLevelCommand(vx=0.1, vy=0.2, note="close_reposition")

        def close(self):
            pass

    nav = DirectiveNavigator.from_config(NAV_CFG)
    nav._navigator.close()
    nav._navigator = LateralNavigator()
    nav.start("go to the crosswalk")

    command = nav.step(NavObservation(position=(0.0, 0.0, 0.0), heading_deg=0.0))

    assert command.vx == pytest.approx(0.1)
    assert command.vy == pytest.approx(0.2)
    assert command.note == "close_reposition|clear"
    nav.close()


def test_checkpoint_model_missing_weights():
    nav = DirectiveNavigator.from_config(NAV_CFG, model_id="citywalker_v1")
    with pytest.raises((FileNotFoundError, NotImplementedError)):
        nav.start("go to the park")
    nav.close()


def test_metaurban_env_stub_episode():
    env = MetaUrbanNavEnv(density_ped=0.5, density_obj=0.2, seed=1, max_episode_steps=50)
    obs, info = env.reset(options={"directive": "go to the coffee shop at 42nd street"})
    assert obs.shape == (8,)
    assert info["goal"].poi_id == "coffee_42nd"
    done = False
    for _ in range(50):
        obs, reward, terminated, truncated, info = env.step([0.0, 0.0, 0.0])
        assert isinstance(reward, float)
        if terminated or truncated:
            done = True
            break
    assert done
    env.close()


def test_dog_navigate_api():
    dog = Dog.from_config(REPO / "configs" / "robot.yaml")
    models = dog.list_nav_models()
    assert any(m.id == "stub_v0" for m in models)
    dog.set_nav_pose((0.0, 0.0, 0.0), heading_deg=0.0)
    mission, cmd = dog.navigate("go to the coffee shop on 42nd")
    assert mission.goal.poi_id == "coffee_42nd"
    assert cmd.vx == 0.0
    assert cmd.vyaw > 0.0
    assert "align_goal" in cmd.note


def test_stub_turns_in_place_for_goal_behind_robot():
    nav = DirectiveNavigator.from_config(NAV_CFG)
    nav.start("go to the crosswalk")
    command = nav.step(NavObservation(position=(8.0, 1.0, 0.0), heading_deg=0.0))

    assert command.vx == 0.0
    assert command.vy == 0.0
    assert command.vyaw != 0.0
    assert "align_goal" in command.note
    nav.close()


def _semantic_nav() -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=0.25,
    )


def _sidewalk_observation(position=(0.0, 0.0, 0.0)) -> NavObservation:
    return NavObservation(
        position=position,
        heading_deg=0.0,
        extras={
            "semantic_candidates": [
                {
                    "id": "observed-sidewalk-1",
                    "label": "sidewalk",
                    "kind": "region",
                    "polygon": [[1.0, -1.0], [4.0, -1.0], [4.0, 1.0], [1.0, 1.0]],
                    "confidence": 0.92,
                    "source": "test_semantic_camera",
                    "reachable": True,
                }
            ]
        },
    )


def test_unknown_sidewalk_uses_bounded_multiview_semantic_search():
    nav = _semantic_nav()
    mission = nav.start("go to the sidewalk")

    first = nav.step(_sidewalk_observation())
    second = nav.step(_sidewalk_observation())

    assert mission.goal is not None
    assert first.vx == first.vy == 0.0
    assert first.vyaw > 0.0
    assert first.note == "semantic_search_scan"
    assert second == MidLevelCommand(note="semantic_target_resolved")
    assert mission.status == "running"
    assert mission.metadata["candidate_source"] == "test_semantic_camera"
    assert mission.goal.poi_id == "observed-sidewalk-1"
    nav.close()


def test_semantic_region_arrival_requires_robot_inside_region():
    nav = _semantic_nav()
    mission = nav.start("move to the sidewalk")
    nav.step(_sidewalk_observation())
    nav.step(_sidewalk_observation())
    assert mission.goal is not None

    arrived = nav.step(_sidewalk_observation((mission.goal.x, mission.goal.y, 0.0)))

    assert arrived.stop
    assert mission.status == "arrived"
    assert mission.metadata["resolution_state"] == "verified"
    nav.close()


def test_unreachable_semantic_candidate_never_authorizes_translation():
    nav = _semantic_nav()
    nav.start("go to the sidewalk")
    observation = _sidewalk_observation()
    raw = dict(observation.extras["semantic_candidates"][0])
    raw["reachable"] = False
    blocked = NavObservation(extras={"semantic_candidates": [raw]})

    commands = [nav.step(blocked) for _ in range(3)]

    assert all(command.vx == command.vy == 0.0 for command in commands)
    assert all(command.note == "semantic_search_scan" for command in commands)
    nav.close()
