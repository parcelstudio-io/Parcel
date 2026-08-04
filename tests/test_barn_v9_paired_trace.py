from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from evals.external import barn_sensor_faithful as evaluator_module
from evals.external.barn_policy_specs import IsolatedPlannerProfileAuthorization
from evals.external.barn_sensor_faithful import (
    CalibratedBarnConfig,
    calibrated_experimental_config_spec,
    calibrated_reference_config_spec,
    run_sensor_faithful_paired_comparison,
)
from evals.external.barn_v9_paired_trace import (
    run_sensor_faithful_paired_comparison_with_v9_traces,
    run_v9_paired_process_episode,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BARN_GRID_CONFIG = REPO_ROOT / "configs/navigation/experiments/barn_grid_v1.yaml"
SYNTHETIC_WORLD_IDS = (91, 92)


def _profile_authorization() -> IsolatedPlannerProfileAuthorization:
    return IsolatedPlannerProfileAuthorization(
        reference_package_sha256="1" * 64,
        reference_manifest_sha256="2" * 64,
        candidate_package_sha256="3" * 64,
        candidate_manifest_sha256="4" * 64,
        reference_model_artifact_sha256="5" * 64,
        candidate_model_artifact_sha256="6" * 64,
        navigation_config_sha256="7" * 64,
        model_id="grid_v1",
        reference_policy_id="trace-reference",
        candidate_policy_id="trace-candidate",
    )


def _assets(root: Path, world_ids: tuple[int, ...] = SYNTHETIC_WORLD_IDS) -> None:
    (root / "path_files").mkdir(parents=True)
    for world_id in world_ids:
        (root / f"world_{world_id}.world").write_text(
            '<sdf version="1.6"><world name="synthetic-v9"/></sdf>\n',
            encoding="utf-8",
        )
        np.save(
            root / "path_files" / f"path_{world_id}.npy",
            np.asarray([[15.0, 0.0], [15.0, 29.0]]),
        )


def _specs():
    reference = calibrated_reference_config_spec(
        BARN_GRID_CONFIG,
        reference_id="v9-paired-trace-reference",
        description="synthetic V9 paired trace reference",
    )
    candidate = calibrated_experimental_config_spec(
        BARN_GRID_CONFIG,
        experiment_id="v9-paired-trace-candidate",
        description="synthetic V9 paired trace candidate",
    )
    return reference, candidate


def _episode_result_projection(episode: dict[str, object]) -> dict[str, object]:
    """Remove additive evidence and nondeterministic wall-clock timing only."""

    result = copy.deepcopy(episode)
    for key in (
        "action_evidence",
        "evaluator_controller_step_latency_samples_ms",
        "latency",
        "v9_step_trace",
        "v9_step_trace_sha256",
    ):
        result.pop(key, None)
    sensor = result["sensor_diagnostics"]
    assert isinstance(sensor, dict)
    sensor.pop("latency", None)
    return result


def _assert_episode_parity(
    ordinary: dict[str, object],
    traced: dict[str, object],
) -> None:
    for arm in ("baseline", "candidate"):
        ordinary_episodes = ordinary[arm]["episodes"]  # type: ignore[index]
        traced_episodes = traced[arm]["episodes"]  # type: ignore[index]
        assert len(ordinary_episodes) == len(traced_episodes)
        for expected, actual in zip(ordinary_episodes, traced_episodes, strict=True):
            assert _episode_result_projection(actual) == _episode_result_projection(expected)


def _assert_full_traces(report: dict[str, object], expected_world_ids: set[int]) -> None:
    observed_world_ids: set[int] = set()
    for arm in ("baseline", "candidate"):
        for episode in report[arm]["episodes"]:  # type: ignore[index]
            observed_world_ids.add(int(episode["world_index"]))
            trace = episode["v9_step_trace"]
            assert isinstance(trace, dict)
            records = trace["records"]
            assert isinstance(records, list)
            assert len(records) == int(episode["steps"])
            assert [record["step_index"] for record in records] == list(range(len(records)))
            assert all(record["requested_vx_mps"] is None for record in records)
            assert all(record["requested_vy_mps"] is None for record in records)
            assert all(record["all_ray_scale_limit"] is None for record in records)
            if records:
                assert records[-1]["post_step_position_xy"] == list(episode["final_position_xy"])
                assert records[-1]["collided"] is episode["collided"]
            encoded = json.dumps(
                trace,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            assert episode["v9_step_trace_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert observed_world_ids == expected_world_ids


def test_workers_one_preserves_results_traces_both_arms_and_action_evidence(
    tmp_path: Path,
) -> None:
    assets = tmp_path / "assets"
    _assets(assets, (SYNTHETIC_WORLD_IDS[0],))
    reference, candidate = _specs()
    common = {
        "assets_root": assets,
        "world_indices": (SYNTHETIC_WORLD_IDS[0],),
        "candidate_spec": candidate,
        "reference_spec": reference,
        "trials": 1,
        "suite_seed": 7101,
        "workers": 1,
        "allow_experimental": True,
        "config": CalibratedBarnConfig(timeout_s=0.1, startup_timeout_s=0.2),
    }
    ordinary = run_sensor_faithful_paired_comparison(**common)
    evidence_root = tmp_path / "evidence"
    evidence_paths = {
        (SYNTHETIC_WORLD_IDS[0], 0, "reference"): evidence_root / "reference.v8e",
        (SYNTHETIC_WORLD_IDS[0], 0, "candidate"): evidence_root / "candidate.v8e",
    }
    traced = run_sensor_faithful_paired_comparison_with_v9_traces(
        **common,
        action_evidence_paths=evidence_paths,
    )

    _assert_episode_parity(ordinary, traced)
    _assert_full_traces(traced, {SYNTHETIC_WORLD_IDS[0]})
    assert traced["comparison"]["action_evidence"]["immutable_artifact_count"] == 2
    assert all(path.is_file() for path in evidence_paths.values())
    assert traced["baseline"]["execution"]["process_start_method"] is None


def test_spawn_workers_two_preserves_results_and_returns_both_arm_traces(
    tmp_path: Path,
) -> None:
    assets = tmp_path / "assets"
    _assets(assets)
    reference, candidate = _specs()
    common = {
        "assets_root": assets,
        "world_indices": SYNTHETIC_WORLD_IDS,
        "candidate_spec": candidate,
        "reference_spec": reference,
        "trials": 1,
        "suite_seed": 7201,
        "workers": 2,
        "allow_experimental": True,
        "config": CalibratedBarnConfig(timeout_s=0.1, startup_timeout_s=0.2),
    }

    ordinary = run_sensor_faithful_paired_comparison(**common)
    traced = run_sensor_faithful_paired_comparison_with_v9_traces(**common)

    _assert_episode_parity(ordinary, traced)
    _assert_full_traces(traced, set(SYNTHETIC_WORLD_IDS))
    assert traced["baseline"]["execution"]["process_start_method"] == "spawn"
    assert traced["candidate"]["execution"]["episode_workers_effective"] == 2
    assert traced["comparison"]["paired_episode_count"] == 2
    assert run_v9_paired_process_episode.__module__ == ("evals.external.barn_v9_paired_trace")


def test_parent_module_substitutions_restore_in_finally(tmp_path: Path) -> None:
    reference, candidate = _specs()
    original_executor = evaluator_module._execute_episode
    original_worker = evaluator_module._run_paired_process_episode

    with pytest.raises(ValueError, match="world_indices"):
        run_sensor_faithful_paired_comparison_with_v9_traces(
            assets_root=tmp_path,
            world_indices=(),
            candidate_spec=candidate,
            reference_spec=reference,
            workers=2,
            allow_experimental=True,
        )

    assert evaluator_module._execute_episode is original_executor
    assert evaluator_module._run_paired_process_episode is original_worker


def test_traced_wrapper_propagates_typed_profile_authorization_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference, candidate = _specs()
    authorization = _profile_authorization()
    captured: dict[str, object] = {}

    def fake_evaluator(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"propagated": True}

    monkeypatch.setattr(
        evaluator_module,
        "run_sensor_faithful_paired_comparison",
        fake_evaluator,
    )
    result = run_sensor_faithful_paired_comparison_with_v9_traces(
        assets_root=tmp_path,
        world_indices=(91,),
        candidate_spec=candidate,
        reference_spec=reference,
        allow_experimental=True,
        isolated_planner_profile_authorization=authorization,
    )

    assert result == {"propagated": True}
    assert captured["isolated_planner_profile_authorization"] is authorization


def test_evaluator_rejects_untyped_or_nonisolated_profile_authorization(
    tmp_path: Path,
) -> None:
    reference, candidate = _specs()
    common = {
        "assets_root": tmp_path,
        "world_indices": (91,),
        "candidate_spec": candidate,
        "reference_spec": reference,
        "allow_experimental": True,
    }
    with pytest.raises(TypeError, match="IsolatedPlannerProfileAuthorization"):
        run_sensor_faithful_paired_comparison(
            **common,
            isolated_planner_profile_authorization="untyped",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="requires two isolated policy arms"):
        run_sensor_faithful_paired_comparison(
            **common,
            isolated_planner_profile_authorization=_profile_authorization(),
        )
