from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from evals.external.barn_policy_specs import parcel_baseline_policy_spec
from evals.external.run_barn import run_barn_suite, select_worlds


def _assets(root: Path) -> None:
    (root / "path_files").mkdir(parents=True)
    (root / "world_0.world").write_text(
        '<sdf version="1.6"><world name="default"/></sdf>\n',
        encoding="utf-8",
    )
    np.save(root / "path_files" / "path_0.npy", np.asarray([[15, 0], [15, 29]]))


def test_world_selector_has_stable_pr_and_public_gates() -> None:
    assert select_worlds("pr") == tuple(range(0, 60, 6))
    assert select_worlds("public") == tuple(range(0, 300, 6))
    assert select_worlds("0, 6,12") == (0, 6, 12)
    with pytest.raises(ValueError, match="duplicates"):
        select_worlds("0,0")


def test_parallel_workers_fail_closed_for_gpu_policy_before_loading_assets(
    tmp_path: Path,
) -> None:
    gpu_spec = replace(parcel_baseline_policy_spec(), execution_device="cuda")

    with pytest.raises(ValueError, match="duplicated model memory"):
        run_barn_suite(
            assets_root=tmp_path / "not-loaded",
            world_indices=(0,),
            policy_spec=gpu_spec,
            workers=2,
        )


def test_suite_runs_unchanged_parcel_policy_and_reports_latency(tmp_path: Path) -> None:
    _assets(tmp_path)

    report = run_barn_suite(
        assets_root=tmp_path,
        world_indices=(0,),
        trials=1,
        lidar_ray_count=31,
    )

    assert report["policy"]["production_behavior_modified"] is False
    assert report["policy"]["execution_device"] == "cpu"
    assert report["execution"]["evaluator_device"] == "cpu"
    assert report["execution"]["lidar_raycast_device"] == "cpu"
    assert report["benchmark"]["official_gazebo_score"] is False
    assert report["aggregate"]["episodes"] == 1.0
    assert report["aggregate"]["success_rate"] == 1.0
    assert report["aggregate"]["navigation_metric"] > 0.0
    assert report["aggregate"]["controller_step_p95_ms"] >= 0.0


def test_spawn_workers_preserve_episode_order_seeds_and_deterministic_results(
    tmp_path: Path,
) -> None:
    _assets(tmp_path)

    serial = run_barn_suite(
        assets_root=tmp_path,
        world_indices=(0,),
        trials=2,
        lidar_ray_count=31,
        suite_seed=71,
        workers=1,
    )
    parallel = run_barn_suite(
        assets_root=tmp_path,
        world_indices=(0,),
        trials=2,
        lidar_ray_count=31,
        suite_seed=71,
        workers=2,
    )

    assert [episode["episode_seed"] for episode in parallel["episodes"]] == [71, 72]
    assert [episode["trial"] for episode in parallel["episodes"]] == [0, 1]
    for serial_episode, parallel_episode in zip(
        serial["episodes"],
        parallel["episodes"],
        strict=True,
    ):
        serial_semantics = dict(serial_episode)
        parallel_semantics = dict(parallel_episode)
        serial_semantics.pop("latency")
        parallel_semantics.pop("latency")
        assert parallel_semantics == serial_semantics

    assert parallel["aggregate"]["success_rate"] == serial["aggregate"]["success_rate"]
    assert parallel["aggregate"]["navigation_metric"] == serial["aggregate"][
        "navigation_metric"
    ]
    assert parallel["aggregate"]["collision_rate"] == serial["aggregate"]["collision_rate"]
    assert parallel["aggregate"]["controller_step_count"] == serial["aggregate"][
        "controller_step_count"
    ]
    assert parallel["execution"]["episode_workers_requested"] == 2
    assert parallel["execution"]["episode_workers_effective"] == 2
    assert parallel["execution"]["process_start_method"] == "spawn"
    assert parallel["execution"]["durable_report_writer"] == "parent_process_only"
