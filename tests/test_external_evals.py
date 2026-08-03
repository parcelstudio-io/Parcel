from __future__ import annotations

import math

import pytest

from evals.external.agents import GoalSeekingAgent
from evals.external.compatibility import COMPATIBILITY, get_fit
from evals.external.episodes import (
    Episode,
    build_suite,
    make_barn_episode,
    make_pointnav_episode,
)
from evals.external.metrics import (
    aggregate,
    barn_score,
    optimal_time_s,
    path_length,
    personal_space_compliance,
    soft_spl,
    success_weighted_path_length,
)
from evals.external.runner import run_episode, run_suite


def test_spl_perfect_and_failure() -> None:
    assert success_weighted_path_length(success=True, shortest_path_m=5.0, agent_path_m=5.0) == pytest.approx(1.0)
    assert success_weighted_path_length(success=True, shortest_path_m=5.0, agent_path_m=10.0) == pytest.approx(0.5)
    assert success_weighted_path_length(success=False, shortest_path_m=5.0, agent_path_m=5.0) == 0.0


def test_soft_spl_scales_with_progress() -> None:
    full = soft_spl(progress=1.0, shortest_path_m=4.0, agent_path_m=4.0)
    half = soft_spl(progress=0.5, shortest_path_m=4.0, agent_path_m=4.0)
    assert full == pytest.approx(1.0)
    assert half == pytest.approx(0.5)


def test_barn_score_clipping() -> None:
    ot = optimal_time_s(6.0, 0.6)  # 10 s
    # Exact OT after success → clipped up to 2*OT, score 0.5
    assert barn_score(success=True, actual_time_s=ot, optimal_time_s=ot) == pytest.approx(0.5)
    assert barn_score(success=False, actual_time_s=ot, optimal_time_s=ot) == 0.0
    # Very slow → clip at 8*OT → score 0.125
    assert barn_score(success=True, actual_time_s=1000.0, optimal_time_s=ot) == pytest.approx(0.125)


def test_psc_and_path_length() -> None:
    assert personal_space_compliance([1.2, 0.5, None], threshold_m=1.0) == pytest.approx(2 / 3)
    assert path_length([(0.0, 0.0), (3.0, 4.0)]) == pytest.approx(5.0)


def test_compatibility_records() -> None:
    assert len(COMPATIBILITY) >= 5
    pointnav = get_fit("habitat2020_pointnav")
    assert pointnav.official_possible_today is False
    assert pointnav.offline_proxy_available is True
    barn = get_fit("barn")
    assert "barn_score" in barn.primary_metrics


def test_pointnav_episode_has_relative_goal() -> None:
    ep = make_pointnav_episode(0, seed=1)
    assert ep.task == "pointnav"
    assert ep.goal_xy is not None
    assert ep.shortest_path_m > 0.0


def test_barn_episode_has_clutter() -> None:
    ep = make_barn_episode(0, seed=2)
    assert ep.task == "barn_clutter"
    assert len(ep.obstacles) > 4


def test_run_episode_smoke() -> None:
    near = Episode(
        episode_id="near",
        task="pointnav",
        benchmark_id="habitat2020_pointnav",
        seed=0,
        start_xy=(0.0, 0.0),
        start_heading_rad=math.pi / 2,
        goal_xy=(0.0, 1.0),
        success_radius_m=0.8,
        max_steps=200,
        dt_s=0.1,
        agent_radius_m=0.3,
        max_speed_mps=0.6,
    )
    metrics, detail = run_episode(near, GoalSeekingAgent())
    assert detail["episode_id"] == "near"
    assert metrics.agent_path_m >= 0.0
    assert 0.0 <= metrics.spl <= 1.0
    assert metrics.success is True


def test_run_suite_offline_no_external_assets() -> None:
    report = run_suite(
        tasks=["pointnav", "barn_clutter", "socialnav"],
        episodes_per_task=3,
        seed=11,
    )
    assert report["aggregate"]["episodes"] == 9.0
    assert set(report["by_task"]) == {"pointnav", "barn_clutter", "socialnav"}
    assert all(row["id"] for row in report["compatibility"])
    # Aggregate keys used in README / CLI summary.
    for key in ("success_rate", "spl", "barn_score", "psc"):
        assert key in report["aggregate"]


def test_build_suite_rejects_unknown_task() -> None:
    with pytest.raises(KeyError):
        build_suite(["not_a_task"], episodes_per_task=1)


def test_aggregate_empty() -> None:
    summary = aggregate([])
    assert summary["episodes"] == 0.0
    assert summary["success_rate"] == 0.0
