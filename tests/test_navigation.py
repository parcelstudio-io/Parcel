from __future__ import annotations

import math
from pathlib import Path

import pytest

from parcel_robot.navigation.base import (
    GoalPose,
    MidLevelCommand,
    Mission,
    ModelSpec,
    NavObservation,
)
from parcel_robot.navigation.collision import CollisionPolicy, apply_collision_brake
from parcel_robot.navigation.envs.metaurban_env import MetaUrbanNavEnv
from parcel_robot.navigation.goals import (
    SemanticGoal,
    navigation_directive_from_text,
    semantic_goal_from_directive,
)
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.models import StubNavigator, build_navigator
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.skills.api import Dog

REPO = Path(__file__).resolve().parents[1]
NAV_CFG = REPO / "configs" / "navigation" / "default.yaml"
POIS = REPO / "configs" / "navigation" / "cities" / "demo_pois.yaml"
MODELS = REPO / "configs" / "navigation" / "models"


@pytest.mark.parametrize(
    ("transcript", "directive", "query", "kind", "relation"),
    [
        (
            "walk to the sidewalk",
            "walk to the sidewalk",
            "sidewalk",
            "region",
            "inside",
        ),
        (
            "Can you go to the sidewalk so that you are not on the road. It's dangerous",
            "go to the sidewalk",
            "sidewalk",
            "region",
            "inside",
        ),
        (
            "Can you wait by the lamppost?",
            "wait by the lamppost",
            "lamppost",
            "object",
            "near",
        ),
        (
            "Parcel, could you please stand next to the street light?",
            "stand next to the street light",
            "street light",
            "object",
            "near",
        ),
    ],
)
def test_explicit_semantic_navigation_commands_are_deterministic(
    transcript: str,
    directive: str,
    query: str,
    kind: str,
    relation: str,
):
    parsed = navigation_directive_from_text(transcript)

    assert parsed == directive
    goal = semantic_goal_from_directive(parsed)
    assert (goal.query, goal.kind, goal.terminal_relation) == (query, kind, relation)


@pytest.mark.parametrize(
    "transcript",
    [
        "wait here",
        "Don't walk to the sidewalk.",
        "What if you walked to the sidewalk?",
        "Suppose you wait by the lamppost.",
    ],
)
def test_non_navigation_text_is_not_forced_into_a_semantic_mission(transcript: str):
    assert navigation_directive_from_text(transcript) is None


def test_registry_lists_supported_model_types():
    reg = ModelRegistry.load(MODELS)
    ids = set(reg.ids())
    assert "stub_v0" in ids
    assert "grid_v1" in ids


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


def test_stub_latches_obstacle_identity_and_world_tangent_until_corridor_is_clear():
    # This test exercises the point-goal stub specifically; the production
    # default is now grid_v1, so select the stub explicitly.
    nav = DirectiveNavigator.from_config(NAV_CFG, model_id="stub_v0")
    nav.start("go to the crosswalk")
    first = nav.step(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_obstacle_m=0.6,
            extras={
                "obstacle_id": "crate",
                "obstacle_bearing_rad": 0.1,
                "lidar_obstacles": [{"id": "crate", "distance_m": 0.6, "bearing_rad": 0.1}],
            },
        )
    )
    controller = nav._navigator
    assert isinstance(controller, StubNavigator)
    fixed_heading = controller._avoid_heading_deg
    assert controller._avoid_obstacle_id == "crate"
    assert "align_avoid" in first.note

    # A different object becomes the nearest return. The active identity and
    # world-frame tangent must not flip to the new object's opposite side.
    second = nav.step(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_obstacle_m=0.4,
            extras={
                "obstacle_id": "bollard",
                "obstacle_bearing_rad": -0.15,
                "lidar_obstacles": [
                    {"id": "bollard", "distance_m": 0.4, "bearing_rad": -0.15},
                    {"id": "crate", "distance_m": 0.8, "bearing_rad": 0.25},
                ],
            },
        )
    )
    assert controller._avoid_obstacle_id == "crate"
    assert controller._avoid_heading_deg == pytest.approx(fixed_heading)
    assert math.copysign(1.0, second.vyaw) == math.copysign(1.0, first.vyaw)

    # Even after the active obstacle gains clearance, another object in the
    # direct goal corridor keeps the original tangent latched.
    nav.step(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_obstacle_m=0.5,
            extras={
                "obstacle_id": "bollard",
                "obstacle_bearing_rad": 0.0,
                "lidar_obstacles": [
                    {"id": "bollard", "distance_m": 0.5, "bearing_rad": 0.0},
                    {"id": "crate", "distance_m": 1.5, "bearing_rad": math.pi},
                ],
            },
        )
    )
    assert controller._avoid_obstacle_id == "crate"
    assert controller._avoid_heading_deg == pytest.approx(fixed_heading)

    resumed = nav.step(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_obstacle_m=1.6,
            extras={
                "obstacle_id": "crate",
                "obstacle_bearing_rad": math.pi,
                "lidar_obstacles": [
                    {"id": "crate", "distance_m": 1.6, "bearing_rad": math.pi},
                    {"id": "bollard", "distance_m": 1.7, "bearing_rad": math.pi},
                ],
            },
        )
    )
    assert controller._avoid_obstacle_id is None
    assert "align_goal" in resumed.note
    nav.close()


def test_stub_uses_full_lidar_to_make_bounded_progress_around_static_obstacle():
    nav = DirectiveNavigator.from_config(NAV_CFG)
    mission = nav.start("go to the crosswalk")
    x = y = yaw = 0.0
    obstacle_x, obstacle_y = 1.8, -0.31
    combined_radius = 0.67
    minimum_clearance = math.inf
    path: list[tuple[float, float]] = []
    avoid_steps = 0
    time_step = 0.1

    for _ in range(500):
        obstacle_dx = obstacle_x - x
        obstacle_dy = obstacle_y - y
        center_distance = math.hypot(obstacle_dx, obstacle_dy)
        clearance = max(0.0, center_distance - combined_radius)
        minimum_clearance = min(minimum_clearance, clearance)
        bearing = (math.atan2(obstacle_dy, obstacle_dx) - yaw + math.pi) % (2.0 * math.pi) - math.pi
        item = {"id": "crate", "distance_m": clearance, "bearing_rad": bearing}
        command = nav.step(
            NavObservation(
                position=(x, y, 0.0),
                heading_deg=math.degrees(yaw),
                nearest_obstacle_m=clearance,
                extras={
                    "obstacle_id": "crate",
                    "obstacle_bearing_rad": bearing,
                    "lidar_obstacles": [item],
                },
            )
        )
        if "avoid" in command.note:
            avoid_steps += 1
        path.append((x, y))
        if command.stop:
            break

        proposed_x = x + math.cos(yaw) * command.vx * time_step
        proposed_y = y + math.sin(yaw) * command.vx * time_step
        assert math.hypot(proposed_x - obstacle_x, proposed_y - obstacle_y) > combined_radius
        x, y = proposed_x, proposed_y
        yaw = (yaw + command.vyaw * time_step + math.pi) % (2.0 * math.pi) - math.pi

    assert mission.status == "arrived"
    assert command.stop
    assert avoid_steps > 0
    assert minimum_clearance > 0.8
    assert max(point[1] for point in path) > 1.0
    assert x > obstacle_x
    nav.close()


def test_near_target_is_excluded_only_from_avoidance_selection():
    controller = StubNavigator(
        ModelSpec("stub-test", "stub", "1"),
        arrive_radius_m=0.1,
        max_linear_accel=100.0,
    )
    mission = Mission(
        "wait by the lamppost",
        GoalPose(3.0, 0.0, arrival_radius_m=0.1),
        semantic_goal=SemanticGoal("lamppost", terminal_relation="near"),
        metadata={"candidate_id": "lamp_post_1"},
    )
    controller.reset(mission)

    target_only = controller.act(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_obstacle_m=0.7,
            extras={
                "obstacle_id": "lamp_post_1",
                "obstacle_bearing_rad": 0.0,
                "lidar_obstacles": [{"id": "lamp_post_1", "distance_m": 0.7, "bearing_rad": 0.0}],
            },
        ),
        mission,
    )
    assert not controller._avoiding
    # Excluding the semantic target from tangent selection does not erase its
    # raw proximity: the existing conservative obstacle slowdown still applies.
    assert target_only.vx == pytest.approx(controller.cruise_vx * 0.25)

    controller.act(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=0.0,
            nearest_obstacle_m=0.6,
            extras={
                "obstacle_id": "crate",
                "obstacle_bearing_rad": 0.2,
                "lidar_obstacles": [
                    {"id": "lamp_post_1", "distance_m": 0.7, "bearing_rad": 0.0},
                    {"id": "crate", "distance_m": 0.6, "bearing_rad": 0.2},
                ],
            },
        ),
        mission,
    )
    assert controller._avoid_obstacle_id == "crate"
    controller.close()


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


def test_collision_brake_retains_default_predictive_stop_semantics():
    policy = CollisionPolicy(
        obstacle_stop_m=0.35,
        obstacle_slow_m=0.80,
        slow_scale=1.0,
        reaction_time_s=0.10,
    )

    vx, vy, note = apply_collision_brake(
        0.50,
        0.0,
        nearest_person_m=None,
        nearest_obstacle_m=0.39,
        nearest_obstacle_bearing_rad=0.0,
        policy=policy,
    )

    assert (vx, vy, note) == (0.0, 0.0, "obstacle_stop")


def test_collision_brake_speed_cap_never_crosses_hard_boundary():
    policy = CollisionPolicy(
        obstacle_stop_m=0.35,
        obstacle_slow_m=0.80,
        slow_scale=1.0,
        reaction_time_s=0.10,
        predictive_mode="speed_cap",
    )

    vx, vy, note = apply_collision_brake(
        0.60,
        0.80,
        nearest_person_m=None,
        nearest_obstacle_m=0.39,
        # Outside the legacy 1.15-radian cone but still with a positive
        # closing component; speed-cap mode must not ignore it.
        nearest_obstacle_bearing_rad=2.20,
        policy=policy,
    )

    assert note == "obstacle_speed_cap"
    assert math.hypot(vx, vy) == pytest.approx(0.40)
    assert (
        math.hypot(vx, vy) * policy.reaction_time_s
        <= 0.39 - policy.obstacle_stop_m + 1e-12
    )
    stopped = apply_collision_brake(
        0.10,
        0.0,
        nearest_person_m=None,
        nearest_obstacle_m=policy.obstacle_stop_m,
        nearest_obstacle_bearing_rad=0.0,
        policy=policy,
    )
    assert stopped == (0.0, 0.0, "obstacle_stop")


def test_projected_speed_cap_preserves_closing_distance_and_tangential_progress():
    policy = CollisionPolicy(
        obstacle_stop_m=0.35,
        obstacle_slow_m=0.80,
        slow_scale=1.0,
        reaction_time_s=0.10,
        predictive_mode="projected_speed_cap",
    )
    obstacle_bearing = math.radians(60.0)

    vx, vy, note = apply_collision_brake(
        1.0,
        0.0,
        nearest_person_m=None,
        nearest_obstacle_m=0.39,
        nearest_obstacle_bearing_rad=obstacle_bearing,
        policy=policy,
    )

    closing_speed = math.hypot(vx, vy) * math.cos(obstacle_bearing)
    assert note == "obstacle_projected_speed_cap"
    assert math.hypot(vx, vy) == pytest.approx(0.80)
    assert closing_speed * policy.reaction_time_s <= (
        0.39 - policy.obstacle_stop_m + 1e-12
    )
    # A total-speed cap would limit this command to 0.40 m/s. Projection keeps
    # safe tangential motion available without changing the hard boundary.
    assert math.hypot(vx, vy) > 0.40


def test_projected_speed_cap_ignores_comfort_slowdown_outside_legacy_cone():
    policy = CollisionPolicy(
        obstacle_stop_m=0.35,
        obstacle_slow_m=0.80,
        slow_scale=0.25,
        reaction_time_s=0.10,
        predictive_mode="projected_speed_cap",
    )

    vx, vy, note = apply_collision_brake(
        0.50,
        0.0,
        nearest_person_m=None,
        nearest_obstacle_m=0.70,
        nearest_obstacle_bearing_rad=math.radians(70.0),
        policy=policy,
    )

    assert (vx, vy, note) == (0.50, 0.0, "clear")


def test_collision_policy_rejects_unknown_predictive_mode():
    with pytest.raises(ValueError, match="predictive_mode"):
        CollisionPolicy(predictive_mode="crawl")


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


def test_navigation_config_applies_complete_collision_profile(tmp_path):
    config = tmp_path / "navigation.yaml"
    config.write_text(
        "\n".join(
            (
                "active_model: stub_v0",
                f"models_root: {MODELS}",
                f"pois_path: {POIS}",
                "safety:",
                "  stop_distance_m: 0.40",
                "  obstacle_slow_m: 0.80",
                "  person_stop_m: 0.90",
                "  person_slow_m: 1.80",
                "  slow_scale: 0.45",
                "  reaction_time_s: 0.10",
                "  predictive_mode: speed_cap",
            )
        ),
        encoding="utf-8",
    )

    nav = DirectiveNavigator.from_config(config)

    assert nav.collision.obstacle_stop_m == pytest.approx(0.40)
    assert nav.collision.obstacle_slow_m == pytest.approx(0.80)
    assert nav.collision.person_stop_m == pytest.approx(0.90)
    assert nav.collision.person_slow_m == pytest.approx(1.80)
    assert nav.collision.slow_scale == pytest.approx(0.45)
    assert nav.collision.reaction_time_s == pytest.approx(0.10)
    assert nav.collision.predictive_mode == "speed_cap"
    nav.close()


def test_unsupported_navigator_type_fails_closed():
    spec = ModelSpec(id="fake_v1", type="not_a_real_type", version="1")
    with pytest.raises(ValueError, match="unsupported navigator type"):
        build_navigator(spec)


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


def test_stub_aligns_terminal_heading_before_declaring_arrival():
    controller = StubNavigator(
        ModelSpec("terminal-heading", "stub", "1"),
        arrive_radius_m=0.1,
    )
    mission = Mission(
        "face the observed target",
        GoalPose(0.0, 0.0, heading_deg=90.0, arrival_radius_m=0.1),
    )
    controller.reset(mission)

    aligning = controller.act(NavObservation(heading_deg=0.0), mission)
    arrived = controller.act(NavObservation(heading_deg=90.0), mission)

    assert not aligning.stop
    assert aligning.vx == aligning.vy == 0.0
    assert aligning.vyaw > 0.0
    assert aligning.note.startswith("align_terminal")
    assert arrived.stop
    assert mission.status == "arrived"


def _semantic_nav() -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=0.25,
    )


def _settled_motion_feedback(*, linear_speed_mps: float = 0.0) -> dict[str, object]:
    return {
        "fresh": True,
        "stop_confirmed": True,
        "linear_speed_mps": linear_speed_mps,
        "yaw_speed_rad_s": 0.0,
        "settled_linear_speed_mps": 0.08,
        "settled_yaw_speed_rad_s": 0.12,
    }


def _sidewalk_observation(position=(0.0, 0.0, 0.0)) -> NavObservation:
    return NavObservation(
        position=position,
        heading_deg=0.0,
        extras={
            "collision": False,
            "perception_fresh": True,
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
            ],
            "motion_feedback": _settled_motion_feedback(),
        },
    )


#: How many ticks a lone-visible region goal now takes to commit.
#: Region ("stuff class") goals are *interchangeable*: the 2026-08-07
#: region-instance arbitration forbids committing to the first instance that
#: confirms, because with only one instance in view "which sidewalk is nearest"
#: is not answerable until the robot has looked around. `ActiveSemanticSearch.
#: observe` therefore withholds the commit until the sweep completes, bounded by
#: `scan_budget_steps` (80). These cases used to commit on the second sighting,
#: which was exactly the first-confirmed-wins rule the arbitration outlawed; the
#: geometry each of them exists to check is untouched.
REGION_SWEEP_BUDGET_STEPS = 80


def _resolve_region_goal(nav, observation, *, budget: int = REGION_SWEEP_BUDGET_STEPS):
    """Drive the interchangeable-goal sweep to its commit; return the commands."""

    commands = []
    for _ in range(budget):
        commands.append(nav.step(observation))
        if nav.mission is not None and nav.mission.goal is not None:
            return commands
    raise AssertionError(
        f"region goal never committed inside the {budget}-step sweep budget"
    )


def test_unknown_sidewalk_uses_bounded_multiview_semantic_search():
    nav = _semantic_nav()
    mission = nav.start("go to the sidewalk")

    commands = _resolve_region_goal(nav, _sidewalk_observation())

    assert mission.goal is not None
    # Bounded is the claim in the name: the sweep terminates on its own budget,
    # it does not run until something else stops it.
    assert len(commands) == REGION_SWEEP_BUDGET_STEPS
    first = commands[0]
    assert first.vx == first.vy == 0.0
    assert first.vyaw > 0.0
    assert first.note == "semantic_search_scan"
    assert commands[-1] == MidLevelCommand(note="semantic_target_resolved")
    assert mission.status == "running"
    assert mission.metadata["candidate_source"] == "test_semantic_camera"
    assert mission.goal.poi_id == "observed-sidewalk-1"
    nav.close()


def test_semantic_region_arrival_requires_robot_inside_region():
    nav = _semantic_nav()
    mission = nav.start("move to the sidewalk")
    _resolve_region_goal(nav, _sidewalk_observation())
    assert mission.goal is not None

    arrived = nav.step(_sidewalk_observation((mission.goal.x, mission.goal.y, 0.0)))

    assert arrived.stop
    assert mission.status == "arrived"
    assert mission.metadata["resolution_state"] == "verified"
    nav.close()


def test_semantic_region_uses_tight_tolerance_and_rejects_an_outside_arrival():
    # The configured 1.5 m POI tolerance used to stop the robot while its body
    # was still on the road. A perception-grounded region supplies its own
    # terminal tolerance and the pipeline independently verifies containment.
    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=1.5,
    )
    mission = nav.start("walk to the sidewalk")
    _resolve_region_goal(nav, _sidewalk_observation())
    assert mission.goal is not None
    assert mission.goal.arrival_radius_m == pytest.approx(0.12)

    # This point is outside the sidewalk and less than the old 1.5 m arrival
    # radius from the selected interior goal.
    road_position = (0.95, 0.0, 0.0)
    distance_to_goal = (
        (mission.goal.x - road_position[0]) ** 2 + (mission.goal.y - road_position[1]) ** 2
    ) ** 0.5
    assert distance_to_goal < 1.5

    command = nav.step(_sidewalk_observation(road_position))

    assert not command.stop
    assert mission.status == "running"
    assert not nav._semantic_arrival_verified(_sidewalk_observation(road_position))
    nav.close()


def _lamppost_observation(position=(0.0, 3.0, 0.0)) -> NavObservation:
    return NavObservation(
        position=position,
        heading_deg=0.0,
        extras={
            "collision": False,
            "perception_fresh": True,
            "semantic_candidates": [
                {
                    "id": "lamp-post-1",
                    "label": "lamppost",
                    "kind": "object",
                    "position": [2.0, 3.0, 0.0],
                    "confidence": 0.98,
                    "source": "test_semantic_camera",
                    "reachable": True,
                    "metadata": {
                        "aliases": ["street light", "lamp post"],
                        "stand_off_m": 1.2,
                        "arrival_radius_m": 0.1,
                        "vicinity_radius_m": 1.35,
                        "support_polygon": [
                            [0.0, 2.0],
                            [4.0, 2.0],
                            [4.0, 4.0],
                            [0.0, 4.0],
                        ],
                    },
                }
            ],
            "lidar_obstacles": [
                {
                    "id": "lamp-post-1",
                    "distance_m": 0.8,
                    "bearing_rad": 0.0,
                }
            ],
            # The arrival policy for an object-facing wait ends by facing the
            # owner. Keep that evidence explicit rather than letting this
            # geometry test depend on an absent owner channel.
            "owner_track": (
                {"id": "owner-1", "x": 10.0, "y": 3.0, "vx": 0.0, "vy": 0.0},
            ),
            "motion_feedback": _settled_motion_feedback(),
        },
    )


def test_near_object_arrival_requires_vicinity_and_safe_support_region():
    nav = _semantic_nav()
    mission = nav.start("wait by the lamppost")
    nav.step(_lamppost_observation())
    nav.step(_lamppost_observation())
    assert mission.goal is not None
    # Stratum-2 (Lane D, card D-3): arrival now also requires M-of-N confirming
    # frames on the target track, so the two ticks that resolve the goal are no
    # longer enough to *claim* it. One more sighting confirms the track; the
    # geometry this case is about is unchanged.
    nav.step(_lamppost_observation())

    at_approach = _lamppost_observation((mission.goal.x, mission.goal.y, 0.0))
    too_far_on_sidewalk = _lamppost_observation((0.5, 3.0, 0.0))
    near_lamp_but_on_road = _lamppost_observation((2.0, 1.75, 0.0))

    assert nav._semantic_arrival_verified(at_approach)
    assert not nav._semantic_arrival_verified(too_far_on_sidewalk)
    assert not nav._semantic_arrival_verified(near_lamp_but_on_road)

    collision_at_approach = _lamppost_observation(
        (mission.goal.x, mission.goal.y, 0.0)
    )
    collision_at_approach.extras["collision"] = True
    assert not nav._semantic_arrival_verified(collision_at_approach)

    phase_b = nav.step(at_approach)
    arrived = nav.step(at_approach)

    assert phase_b.note == "owner_face_turn_started"
    assert phase_b.stop is False
    assert arrived.stop
    assert arrived.note == "arrived_verified"
    assert mission.status == "arrived"
    assert mission.metadata["owner_face_phase"] == "complete"
    assert mission.metadata["terminal_behavior"] == "hold"
    nav.close()


def test_semantic_arrival_waits_for_fresh_measured_stop_feedback():
    nav = _semantic_nav()
    mission = nav.start("move to the sidewalk")
    _resolve_region_goal(nav, _sidewalk_observation())
    assert mission.goal is not None
    moving = _sidewalk_observation((mission.goal.x, mission.goal.y, 0.0))
    moving.extras["motion_feedback"] = {
        **_settled_motion_feedback(linear_speed_mps=0.2),
        "stop_confirmed": False,
    }

    requested = nav.step(moving)
    waiting = nav.step(moving)
    settled = nav.step(_sidewalk_observation((mission.goal.x, mission.goal.y, 0.0)))

    assert requested.stop and requested.note == "semantic_stop_requested"
    assert waiting.stop and waiting.note == "semantic_waiting_for_stop_confirmation"
    assert settled.stop and settled.note == "arrived_verified"
    assert mission.status == "arrived"
    nav.close()


def test_near_arrival_rejects_unsafe_current_target_lidar_range():
    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=0.25,
        max_semantic_replans=0,
    )
    mission = nav.start("wait by the lamppost")
    nav.step(_lamppost_observation())
    nav.step(_lamppost_observation())
    assert mission.goal is not None
    # See above: M-of-N confirmation (card D-3) needs a third sighting.
    nav.step(_lamppost_observation())
    unsafe = _lamppost_observation((mission.goal.x, mission.goal.y, 0.0))
    unsafe.extras["lidar_obstacles"][0]["distance_m"] = 0.0

    result = nav.step(unsafe)

    assert result.stop
    assert result.note == "semantic_arrival_verification_failed"
    assert mission.status == "failed"
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
