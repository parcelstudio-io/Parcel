from pathlib import Path

import mujoco
import pytest

from parcel_robot.perception.city_semantics import extract_city_semantics, visible_city_semantics

REPO = Path(__file__).resolve().parents[1]
SCENE = REPO / "src" / "parcel_robot" / "scenes" / "city_block.xml"


@pytest.fixture(scope="module")
def city_semantics():
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    return extract_city_semantics(model)


def test_city_scene_exposes_sidewalk_regions_with_terminal_contract(city_semantics):
    regions, _ = city_semantics
    by_id = {region["id"]: region for region in regions}

    assert {"sidewalk", "sidewalk_south"} <= set(by_id)
    for region_id in ("sidewalk", "sidewalk_south"):
        region = by_id[region_id]
        assert region["label"] == "sidewalk"
        assert len(region["polygon"]) == 4
        assert region["metadata"]["arrival_radius_m"] < 0.2
        assert region["metadata"]["terminal_clearance_m"] >= 0.32


def test_city_lampposts_have_aliases_standoff_and_sidewalk_support(city_semantics):
    _, objects = city_semantics
    lamps = {
        item["id"]: item for item in objects if item["label"] == "lamppost"
    }

    assert {"lamp_post_1", "lamp_post_2"} <= set(lamps)
    for lamp in lamps.values():
        metadata = lamp["metadata"]
        assert lamp["label"] == "lamppost"
        assert "street light" in metadata["aliases"]
        assert lamp["id"] in metadata["associated_lidar_ids"]
        assert metadata["support_label"] == "sidewalk"
        assert len(metadata["support_polygon"]) == 4
        minimum_center_distance = lamp["metadata"]["radius_m"] + 0.32 + 0.8
        assert (
            metadata["stand_off_m"] - metadata["arrival_radius_m"]
            > minimum_center_distance
        )
        maximum_surface_gap = (
            metadata["vicinity_radius_m"] - lamp["metadata"]["radius_m"] - 0.32
        )
        assert maximum_surface_gap == pytest.approx(1.0)
        assert metadata["vicinity_radius_m"] >= metadata["stand_off_m"]


def test_city_semantic_camera_only_returns_tracks_inside_its_view(city_semantics):
    regions, objects = city_semantics

    visible_regions, visible_objects = visible_city_semantics(
        regions,
        objects,
        robot_x=0.0,
        robot_y=0.0,
        robot_heading=0.0,
        max_range_m=4.0,
    )

    assert all(item["source"] == "simulator_semantic_camera" for item in visible_regions)
    assert all(item["source"] == "simulator_semantic_camera" for item in visible_objects)
    assert all(item["confidence"] == pytest.approx(0.98) for item in visible_regions)
    assert all(item["reachable"] is True for item in (*visible_regions, *visible_objects))
    assert any(item["label"] == "crosswalk" for item in visible_regions)
    assert all(item["id"] != "lamp_post_1" for item in visible_objects)


def test_vocabulary_includes_bench_tree_planter_building_crosswalk(city_semantics):
    regions, objects = city_semantics
    labels = {item["label"] for item in objects}
    region_labels = {item["label"] for item in regions}
    assert {"bench", "tree", "planter", "building", "lamppost"} <= labels
    assert {"sidewalk", "crosswalk"} <= region_labels

    by_id = {item["id"]: item for item in objects}
    assert "bench_1" in by_id
    bench = by_id["bench_1"]
    assert "seat" in bench["metadata"]["aliases"]
    assert any(name.startswith("bench_") for name in bench["metadata"]["associated_lidar_ids"])
    assert bench["metadata"]["goal_region"]["kind"] == "relative_band"
    assert bench["metadata"]["goal_region"]["center"][0] == pytest.approx(-2.5)
    assert bench["metadata"]["goal_region"]["band_m"][1] == pytest.approx(
        bench["metadata"]["vicinity_radius_m"]
    )

    crosswalk = next(item for item in regions if item["label"] == "crosswalk")
    assert crosswalk["id"] == "crosswalk"
    assert crosswalk["metadata"]["goal_region"]["kind"] == "polygon"
    assert "crossing" in crosswalk["metadata"]["aliases"]

    tree = next(item for item in objects if item["label"] == "tree")
    assert any(name.startswith("tree_") for name in tree["metadata"]["associated_lidar_ids"])
