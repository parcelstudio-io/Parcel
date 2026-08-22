from __future__ import annotations

from pathlib import Path

import mujoco
import pytest

from parcel_robot.dynamic_city import (
    DynamicCity,
    circle_contact_ttc,
    default_dynamic_agent_specs,
    select_social_collision_candidate,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.sim import (
    is_logical_obstacle_name,
    lidar_obstacle_payload,
    select_relevant_obstacle,
)

REPO = Path(__file__).resolve().parents[1]
CITY_SCENE = REPO / "src" / "parcel_robot" / "scenes" / "city_block.xml"
FLAT_SCENE = REPO / "third_party" / "unitree_mujoco" / "unitree_robots" / "go2" / "scene.xml"


def test_seeded_city_routes_are_replayable_and_bounded():
    first = DynamicCity.default(seed=19)
    second = DynamicCity.default(seed=19)

    for _ in range(400):
        first.step(0.05)
        second.step(0.05)

    assert first.snapshots() == second.snapshots()
    for actor in first.snapshots():
        assert -8.0 <= float(actor["x"]) <= 8.0
        assert -5.0 <= float(actor["y"]) <= 5.0


def test_nearest_social_actor_reports_clearance():
    city = DynamicCity.default(seed=3)
    pedestrian = next(actor for actor in city.agents if actor.spec.kind == "pedestrian")

    nearest = city.nearest_person(pedestrian.x, pedestrian.y)

    assert nearest is not None
    assert nearest["kind"] == "pedestrian"
    assert nearest["distance_m"] == 0.0
    assert "bearing_rad" in nearest


def test_snapshots_can_be_limited_to_scene_mapped_actors():
    city = DynamicCity.default(seed=3)

    tracks = city.snapshots({"ped-2", "cyclist-1", "not-in-this-scene"})

    assert {track["id"] for track in tracks} == {"ped-2", "cyclist-1"}


# Card GATE-0: the `skipif(not FLAT_SCENE.exists())` guard is gone — the flat
# Go2 scene is a tracked, manifest-pinned asset now, not a developer clone.
def test_flat_scene_does_not_publish_phantom_city_tracks():
    model = mujoco.MjModel.from_xml_path(str(FLAT_SCENE))
    city = DynamicCity.default(seed=3)
    mapped_ids = {
        actor.spec.agent_id
        for actor in city.agents
        if (
            (body_id := mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, actor.spec.body_name))
            >= 0
            and int(model.body_mocapid[body_id]) >= 0
        )
    }

    assert mapped_ids == set()
    assert city.snapshots(mapped_ids) == []


def test_circle_contact_ttc_reports_first_contact_not_closest_approach():
    # Centers would coincide at t=2.0, but the two 0.25 m circles touch at 1.5 s.
    assert circle_contact_ttc(2.0, 0.0, -1.0, 0.0, 0.5) == pytest.approx(1.5)
    assert circle_contact_ttc(2.0, 0.0, 1.0, 0.0, 0.5) is None


def test_social_candidate_prefers_crossing_cyclist_over_closer_actor_behind():
    candidate = select_social_collision_candidate(
        [
            {
                "id": "owner-1",
                "kind": "owner",
                "x": -0.8,
                "y": 0.0,
                "vx": 0.0,
                "vy": 0.0,
                "radius_m": 0.22,
            },
            {
                "id": "cyclist-1",
                "kind": "cyclist",
                "x": 3.0,
                "y": 0.0,
                "vx": -1.0,
                "vy": 0.0,
                "radius_m": 0.38,
            },
        ],
        robot_x=0.0,
        robot_y=0.0,
        robot_heading_rad=0.0,
        robot_vx=0.0,
        robot_vy=0.0,
    )

    assert candidate is not None
    assert candidate["id"] == "cyclist-1"
    assert candidate["selection"] == "earliest_collision"
    assert candidate["time_to_collision_s"] == pytest.approx(2.3)


def test_disabled_city_has_no_tracks():
    city = DynamicCity.default(enabled=False)
    before = [(actor.x, actor.y) for actor in city.agents]
    city.step(2.0)

    assert city.snapshots() == []
    assert [(actor.x, actor.y) for actor in city.agents] == before


def test_default_routes_clear_sidewalk_fixtures():
    circular_fixtures = (
        (-5.0, 3.15, 0.45),
        (5.0, 3.1, 0.45),
        (0.2, 3.15, 0.06),
        (-6.7, -2.9, 0.06),
        (3.85, 2.1, 0.055),
    )
    bench = (-3.2, -1.8, 2.78, 3.23)

    for spec in default_dynamic_agent_specs():
        points = [(point.x, point.y) for point in spec.route]
        segments = zip(points, points[1:] + points[:1], strict=True)
        for start, end in segments:
            for fixture_x, fixture_y, fixture_radius in circular_fixtures:
                assert _point_segment_distance((fixture_x, fixture_y), start, end) > (
                    fixture_radius + spec.radius_m + 0.01
                ), f"{spec.agent_id} intersects a circular sidewalk fixture"
            assert not _segment_intersects_box(
                start,
                end,
                bench[0] - spec.radius_m,
                bench[1] + spec.radius_m,
                bench[2] - spec.radius_m,
                bench[3] + spec.radius_m,
            ), f"{spec.agent_id} intersects the sidewalk bench"


def test_new_city_furniture_is_logical_obstacle_telemetry():
    for name in ("planter_1", "tree_1", "lamp_post_1", "signal_post"):
        assert is_logical_obstacle_name(name)


def test_obstacle_ahead_is_not_masked_by_closer_obstacle_behind():
    selected = select_relevant_obstacle(
        [
            {"id": "behind", "distance_m": 0.2, "bearing_rad": 3.12},
            {"id": "ahead", "distance_m": 0.7, "bearing_rad": 0.1},
        ],
        VelocityCommand(vx=0.3),
    )

    assert selected is not None
    assert selected["id"] == "ahead"


def test_lidar_payload_strips_simulator_world_coordinates():
    payload = lidar_obstacle_payload(
        {
            "id": "bench",
            "distance_m": 0.7,
            "bearing_rad": 0.1,
            "x": 12.0,
            "y": -4.0,
        }
    )

    assert payload == {"id": "bench", "distance_m": 0.7, "bearing_rad": 0.1}


@pytest.mark.skipif(not CITY_SCENE.exists(), reason="city scene is unavailable")
def test_city_scene_contains_mocap_crowd():
    model = mujoco.MjModel.from_xml_path(str(CITY_SCENE))

    assert model.nmocap == 9  # owner + seven pedestrians + one cyclist
    for name in ("pedestrian_1", "pedestrian_7", "cyclist_1"):
        assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name) >= 0


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return ((point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2) ** 0.5
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    projection = max(0.0, min(1.0, projection))
    nearest = (start[0] + projection * dx, start[1] + projection * dy)
    return ((point[0] - nearest[0]) ** 2 + (point[1] - nearest[1]) ** 2) ** 0.5


def _segment_intersects_box(
    start: tuple[float, float],
    end: tuple[float, float],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> bool:
    lower, upper = 0.0, 1.0
    for origin, delta, minimum, maximum in (
        (start[0], end[0] - start[0], min_x, max_x),
        (start[1], end[1] - start[1], min_y, max_y),
    ):
        if abs(delta) <= 1e-12:
            if origin < minimum or origin > maximum:
                return False
            continue
        first, second = (minimum - origin) / delta, (maximum - origin) / delta
        entry, exit_ = sorted((first, second))
        lower, upper = max(lower, entry), min(upper, exit_)
        if lower > upper:
            return False
    return True
