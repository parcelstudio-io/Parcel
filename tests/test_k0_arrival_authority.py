"""K0: one GoalRegion arrival authority + step-limit termination attribution."""

from __future__ import annotations

import pytest

from evals.nav_instruct.generator import (
    _LANDMARKS,
    EPISODE_SET_V1,
    EPISODE_SET_V3,
    _object_goal,
    _region_goal,
    _relative_goal,
    episode_set_spec,
)
from parcel_robot.city_semantics import extract_city_semantics
from parcel_robot.instructnav.scoring import (
    NEXT_TO_BAND_M,
    AttributionLayer,
    FailureClass,
    GoalRegion,
    arrival_goal_region_for_relation,
    next_to_band_from_centre,
    object_near_envelope_m,
    object_near_goal_region,
    object_towards_goal_region,
    score_episode,
)


def test_semantics_and_eval_object_goal_regions_agree():
    """city_semantics goal_region ≡ NAV_INSTRUCT generator for the same lamp."""

    from pathlib import Path

    import mujoco

    scene = Path(__file__).resolve().parents[1] / "src/parcel_robot/scenes/city_block.xml"
    model = mujoco.MjModel.from_xml_path(str(scene))
    _, objects = extract_city_semantics(model)
    lamp = next(item for item in objects if item["id"] == "lamp_post_1")
    semantic = GoalRegion.from_mapping(lamp["metadata"]["goal_region"])

    _, eval_goal = _object_goal("go to the lamp post", tier="A", absent=False)
    assert eval_goal.kind == semantic.kind == "relative_band"
    assert eval_goal.center == pytest.approx(tuple(semantic.center))
    assert eval_goal.band_m == pytest.approx(tuple(semantic.band_m))

    # Pipeline relation builder reproduces the same authority.
    pipeline = arrival_goal_region_for_relation(
        "near",
        center=(lamp["position"][0], lamp["position"][1]),
        object_radius_m=float(lamp["metadata"]["radius_m"]),
        label="lamppost",
        entity_id="lamp_post_1",
        metadata=lamp["metadata"],
    )
    assert pipeline.band_m == pytest.approx(tuple(semantic.band_m))


def test_towards_and_region_builders_are_shared():
    landmark = _LANDMARKS["lamp_post_1"]
    _, towards = _object_goal("walk towards the lamppost", tier="A", absent=False)
    assert towards.kind == "relative_band"
    assert towards.band_m == object_towards_goal_region(landmark["position"]).band_m

    _, sidewalk = _region_goal("go to the sidewalk", tier="A", absent=False)
    assert sidewalk.kind == "polygon"
    assert len(sidewalk.polygon or ()) >= 3


@pytest.mark.parametrize(
    ("instruction", "entity_id"),
    (
        ("stand next to the bench", "bench_1"),
        ("go next to the planter", "planter_1"),
    ),
)
def test_next_to_eval_pipeline_approach_footprint_agree(instruction: str, entity_id: str):
    """B1: one next_to footprint across generator, arrival builder, and approach.

    The comparison is against the **live** episode-set version (v3), because
    the live K0 band is the surface-anchored one. v1/v2 are frozen artifacts
    carrying the superseded centre-anchored encoding on purpose, and the second
    half of this test pins that they do *not* agree with today's builder — a
    frozen set that silently tracked a K0 change would not be frozen.
    """

    landmark = _LANDMARKS[entity_id]
    radius_m = float(landmark["radius_m"])
    center = (float(landmark["position"][0]), float(landmark["position"][1]))

    _, eval_goal = _relative_goal(
        instruction, tier="A", absent=False, spec=episode_set_spec(EPISODE_SET_V3)
    )
    pipeline = arrival_goal_region_for_relation(
        "next_to",
        center=center,
        object_radius_m=radius_m,
        entity_id=entity_id,
        metadata={"radius_m": radius_m},
    )

    assert eval_goal.kind == pipeline.kind == "relative_band"
    assert eval_goal.center == pytest.approx(pipeline.center)
    assert eval_goal.band_m == pytest.approx(pipeline.band_m)
    assert eval_goal.band_m == pytest.approx(next_to_band_from_centre(radius_m))
    assert eval_goal.anchor_footprint_m == pytest.approx(pipeline.anchor_footprint_m)
    assert eval_goal.anchor_footprint_m == pytest.approx(radius_m)
    # Approach next_to footprint is metadata["radius_m"] (same full radius).
    assert float(landmark["radius_m"]) == pytest.approx(eval_goal.anchor_footprint_m)

    # The frozen sets carry the superseded band and must keep carrying it.
    _, frozen_goal = _relative_goal(
        instruction, tier="A", absent=False, spec=episode_set_spec(EPISODE_SET_V1)
    )
    assert frozen_goal.band_m == pytest.approx(NEXT_TO_BAND_M)
    assert frozen_goal.band_m != pytest.approx(eval_goal.band_m)

    # Concrete disagreement case is gone: 0.50 m was inside half-radius bench
    # (0.35) but outside full footprint (0.7). Both authorities now exclude it.
    if entity_id == "bench_1":
        assert radius_m == pytest.approx(0.7)
        outside_xy = (center[0] + 0.50, center[1])
        inside_xy = (center[0] + radius_m + 1.0, center[1])
        assert not eval_goal.contains(*outside_xy)
        assert not pipeline.contains(*outside_xy)
        assert eval_goal.contains(*inside_xy)
        assert pipeline.contains(*inside_xy)


def test_near_envelope_rejects_legacy_radius_plus_1_4():
    """The old eval disc (radius+1.4 ≈ 1.46) must not be the authority."""

    _, minimum, vicinity = object_near_envelope_m(0.06, label="lamppost")
    assert vicinity == pytest.approx(0.06 + 0.32 + 1.0)
    assert vicinity < 1.46
    assert minimum < vicinity
    region = object_near_goal_region((0.2, 3.15), 0.06, label="lamppost")
    # Inside the band.
    assert region.contains(0.2, 3.15 + 1.30)
    # Outside the old-vs-new gap that produced near-miss planning_errors.
    assert not region.contains(0.2, 3.15 + 1.46)


def test_step_limit_inside_goal_is_termination_not_planning():
    goal = GoalRegion(kind="disc", center=(2.0, 0.0), radius_m=0.5)
    trace = [
        {"t_s": 0.0, "x": 0.0, "y": 0.0, "stopped": False, "attempted": True},
        {
            "t_s": 4.0,
            "x": 2.05,
            "y": 0.0,
            "stopped": True,
            "attempted": True,
            "step_limit": True,
            "note": "navigation_step_limit_inside_goal",
            "termination_error": True,
        },
    ]
    score = score_episode(
        trace,
        goal,
        shortest_path_m=2.0,
        max_time_s=5.0,
        arrival_hold_s=1.0,
    )
    assert not score.success
    assert score.failure == FailureClass.TERMINATION
    assert score.attribution_layer == AttributionLayer.L6_TERMINATION
    assert score.failure != FailureClass.PLANNING_ERROR


def test_ever_inside_with_step_limit_note_is_termination():
    goal = GoalRegion(kind="disc", center=(2.0, 0.0), radius_m=0.5)
    trace = [
        {"t_s": 0.0, "x": 0.0, "y": 0.0, "stopped": False, "attempted": True},
        {"t_s": 1.0, "x": 2.0, "y": 0.0, "stopped": False, "attempted": True},
        {
            "t_s": 4.0,
            "x": 3.5,
            "y": 0.0,
            "stopped": True,
            "attempted": True,
            "note": "navigation_step_limit",
            "step_limit": True,
        },
    ]
    score = score_episode(trace, goal, shortest_path_m=2.0, max_time_s=5.0)
    assert score.failure == FailureClass.TERMINATION
    assert score.attribution_layer == AttributionLayer.L6_TERMINATION


def test_terminal_step_limit_inside_goal_beats_earlier_planning_error():
    """S1: stale planning_error must not outrank terminal L6 inside-goal expiry."""

    goal = GoalRegion(kind="disc", center=(2.0, 0.0), radius_m=0.5)
    trace = [
        {
            "t_s": 0.0,
            "x": 0.0,
            "y": 0.0,
            "stopped": False,
            "attempted": True,
            "planning_error": True,
            "unreachable": True,
            "note": "no_route",
        },
        {
            "t_s": 4.0,
            "x": 2.05,
            "y": 0.0,
            "stopped": True,
            "attempted": True,
            "step_limit": True,
            "note": "navigation_step_limit_inside_goal",
            "termination_error": True,
        },
    ]
    score = score_episode(
        trace,
        goal,
        shortest_path_m=2.0,
        max_time_s=5.0,
        arrival_hold_s=1.0,
    )
    assert not score.success
    assert score.failure == FailureClass.TERMINATION
    assert score.attribution_layer == AttributionLayer.L6_TERMINATION
    assert score.failure != FailureClass.PLANNING_ERROR
