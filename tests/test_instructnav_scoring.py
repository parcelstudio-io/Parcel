"""N-S1: GoalRegion predicates, SPL/SR scoring, failure attribution."""

from __future__ import annotations

import math

import pytest

from parcel_robot.instructnav.scoring import (
    AttributionLayer,
    FailureClass,
    GoalRegion,
    score_episode,
    score_episode_with_oracle,
)


def test_disc_and_polygon_contains_and_distance():
    disc = GoalRegion(kind="disc", center=(0.0, 0.0), radius_m=1.0)
    assert disc.contains(0.5, 0.0)
    assert not disc.contains(2.0, 0.0)
    assert disc.distance_to(2.0, 0.0) == pytest.approx(1.0)

    poly = GoalRegion(
        kind="polygon",
        polygon=((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
    )
    assert poly.contains(1.0, 1.0)
    assert not poly.contains(3.0, 1.0)
    assert poly.distance_to(3.0, 1.0) == pytest.approx(1.0)


def test_relative_band_excludes_anchor_footprint():
    band = GoalRegion(
        kind="relative_band",
        center=(0.0, 0.0),
        band_m=(0.4, 0.9),
        anchor_entity="bench_1",
        anchor_footprint_m=0.35,
    )
    assert not band.contains(0.2, 0.0)  # inside footprint
    assert band.contains(0.6, 0.0)
    assert not band.contains(1.2, 0.0)


def test_success_requires_hold_and_agent_stop():
    goal = GoalRegion(kind="disc", center=(2.0, 0.0), radius_m=0.5)
    # Pass through without stopping — fail.
    moving = [
        {"t_s": 0.0, "x": 0.0, "y": 0.0, "stopped": False},
        {"t_s": 1.0, "x": 2.0, "y": 0.0, "stopped": False, "speed_mps": 0.4},
    ]
    failed = score_episode(moving, goal, shortest_path_m=2.0, max_time_s=30.0)
    assert not failed.success
    assert failed.failure == FailureClass.CONTROL_ERROR

    holding = [
        {"t_s": 0.0, "x": 0.0, "y": 0.0, "stopped": False},
        {"t_s": 1.0, "x": 2.0, "y": 0.0, "stopped": True, "speed_mps": 0.0},
        {"t_s": 2.0, "x": 2.0, "y": 0.0, "stopped": True, "speed_mps": 0.0},
    ]
    ok = score_episode(
        holding, goal, shortest_path_m=2.0, max_time_s=30.0, arrival_hold_s=1.0
    )
    assert ok.success
    assert ok.failure == FailureClass.NONE
    assert ok.spl == pytest.approx(1.0)
    assert ok.time_to_goal_s == pytest.approx(2.0)


def test_spl_penalizes_detour():
    goal = GoalRegion(kind="disc", center=(4.0, 0.0), radius_m=0.3)
    detour = [
        {"t_s": 0.0, "x": 0.0, "y": 0.0, "stopped": False},
        {"t_s": 1.0, "x": 0.0, "y": 4.0, "stopped": False},
        {"t_s": 2.0, "x": 4.0, "y": 0.0, "stopped": True},
        {"t_s": 3.5, "x": 4.0, "y": 0.0, "stopped": True},
    ]
    score = score_episode(
        detour, goal, shortest_path_m=4.0, max_time_s=30.0, arrival_hold_s=1.0
    )
    assert score.success
    assert score.spl < 1.0
    assert score.spl == pytest.approx(4.0 / (4.0 + 4.0 * math.sqrt(2)), rel=1e-3)


def test_refusal_precedes_other_failure_classes():
    trace = [
        {
            "t_s": 0.0,
            "x": 0.0,
            "y": 0.0,
            "stopped": True,
            "reply": "I couldn't form a safe, grounded plan yet.",
            "collision": True,
        }
    ]
    score = score_episode(
        trace,
        GoalRegion(kind="disc", center=(5.0, 0.0), radius_m=0.5),
        shortest_path_m=5.0,
        max_time_s=30.0,
    )
    assert score.failure == FailureClass.REFUSAL


def test_oracle_counterfactual_names_grounding_then_exploration():
    goal = GoalRegion(kind="disc", center=(5.0, 0.0), radius_m=0.5)
    trace = [
        {
            "t_s": 0.0,
            "x": 0.0,
            "y": 0.0,
            "stopped": True,
            "resolution_state": "unseen",
            "grounding_error": True,
        }
    ]
    score, attr = score_episode_with_oracle(
        trace,
        goal,
        shortest_path_m=5.0,
        max_time_s=30.0,
        oracle_grounding_flips=True,
        oracle_grounding_and_explore_flips=True,
    )
    assert not score.success
    assert score.oracle_success
    assert score.oracle_sr_gap == pytest.approx(1.0)
    assert attr.grounding_gap
    assert attr.layer == AttributionLayer.L2B_VISIBILITY

    score2, attr2 = score_episode_with_oracle(
        trace,
        goal,
        shortest_path_m=5.0,
        max_time_s=30.0,
        oracle_grounding_flips=False,
        oracle_grounding_and_explore_flips=True,
    )
    assert attr2.exploration_gap
    assert attr2.layer == AttributionLayer.L3_EXPLORATION
    assert score2.attribution_layer == AttributionLayer.L3_EXPLORATION


def test_unseen_without_search_is_grounding_error():
    goal = GoalRegion(kind="disc", center=(5.0, 0.0), radius_m=0.5)
    score = score_episode(
        [{"t_s": 0.0, "x": 0.0, "y": 0.0, "stopped": True, "grounding_outcome": "UNSEEN"}],
        goal,
        shortest_path_m=5.0,
        max_time_s=30.0,
    )
    assert score.failure == FailureClass.GROUNDING_ERROR


def test_oracle_sr_derives_from_ever_inside_when_omitted():
    goal = GoalRegion(kind="disc", center=(2.0, 0.0), radius_m=0.5)
    moving = [
        {"t_s": 0.0, "x": 0.0, "y": 0.0, "stopped": False},
        {"t_s": 1.0, "x": 2.0, "y": 0.0, "stopped": False, "speed_mps": 0.4},
    ]
    score = score_episode(moving, goal, shortest_path_m=2.0, max_time_s=30.0)
    assert not score.success
    assert score.oracle_success
    assert score.oracle_sr_gap == pytest.approx(1.0)


def test_oracle_no_flip_maps_grounding_and_search_layers():
    goal = GoalRegion(kind="disc", center=(5.0, 0.0), radius_m=0.5)
    g_score, g_attr = score_episode_with_oracle(
        [{"t_s": 0.0, "x": 0.0, "y": 0.0, "stopped": True, "grounding_error": True}],
        goal,
        shortest_path_m=5.0,
        max_time_s=30.0,
        oracle_grounding_flips=False,
        oracle_grounding_and_explore_flips=False,
    )
    assert g_score.failure == FailureClass.GROUNDING_ERROR
    assert g_attr.layer == AttributionLayer.L2B_VISIBILITY

    s_score, s_attr = score_episode_with_oracle(
        [{"t_s": 0.0, "x": 0.0, "y": 0.0, "stopped": True, "search_error": True}],
        goal,
        shortest_path_m=5.0,
        max_time_s=30.0,
        oracle_grounding_flips=False,
        oracle_grounding_and_explore_flips=False,
    )
    assert s_score.failure == FailureClass.SEARCH_ERROR
    assert s_attr.layer == AttributionLayer.L3_EXPLORATION
