from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import evals.external.barn_policy_specs as policy_specs
from evals.external.barn_native import BarnAction, BarnObservation
from evals.external.barn_policy_specs import (
    DEFAULT_NAVIGATION_CONFIG,
    BarnPolicySpec,
    ExperimentalPolicyDisabledError,
    parcel_experimental_config_spec,
)
from evals.external.compare_barn import run_barn_comparison
from evals.external.run_barn import run_barn_suite


def _assets(root: Path) -> None:
    (root / "path_files").mkdir(parents=True)
    (root / "world_0.world").write_text(
        '<sdf version="1.6"><world name="default"/></sdf>\n',
        encoding="utf-8",
    )
    np.save(root / "path_files" / "path_0.npy", np.asarray([[15, 0], [15, 29]]))


class _StraightPolicy:
    def __init__(self, speed: float, seed_sink: list[int], seed: int) -> None:
        self.speed = speed
        seed_sink.append(seed)

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        del start_xy, heading_rad, goal_xy

    def act(self, observation: BarnObservation) -> BarnAction:
        assert not hasattr(observation, "cylinders")
        assert not hasattr(observation, "reference_path_world")
        return BarnAction(self.speed, 0.0, note="straight")


def _spec(
    policy_id: str,
    speed: float,
    seeds: list[int],
    *,
    experimental: bool,
) -> BarnPolicySpec:
    return BarnPolicySpec(
        policy_id=policy_id,
        description=f"straight {speed}",
        agent_id="test-straight",
        adapter_id="sensor-only-test",
        model_id="none",
        factory=lambda seed: _StraightPolicy(speed, seeds, seed),
        experimental=experimental,
    )


def test_experimental_policy_requires_explicit_feature_gate(tmp_path: Path) -> None:
    seeds: list[int] = []
    candidate = _spec("candidate", 2.0, seeds, experimental=True)

    with pytest.raises(ExperimentalPolicyDisabledError, match="explicit opt-in"):
        run_barn_suite(
            assets_root=tmp_path / "not-loaded",
            world_indices=(0,),
            policy_spec=candidate,
        )

    assert seeds == []


def test_process_workers_reject_arbitrary_policy_factories_before_loading_assets(
    tmp_path: Path,
) -> None:
    seeds: list[int] = []
    candidate = _spec("candidate", 2.0, seeds, experimental=True)

    with pytest.raises(ValueError, match="arbitrary in-process factory"):
        run_barn_suite(
            assets_root=tmp_path / "not-loaded",
            world_indices=(0,),
            policy_spec=candidate,
            allow_experimental=True,
            workers=2,
        )

    assert seeds == []


def test_config_spec_hashes_model_by_declared_id_not_filename(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    model_path = models / "descriptive_filename.yaml"
    model_path.write_text("id: grid_v1\ntype: grid\n", encoding="utf-8")
    inactive_path = models / "inactive.yaml"
    inactive_path.write_text("id: spare_v1\ntype: stub\n", encoding="utf-8")
    pois_path = tmp_path / "pois.yaml"
    pois_path.write_text("pois: []\n", encoding="utf-8")
    config_path = tmp_path / "candidate.yaml"
    config_path.write_text(
        f"active_model: grid_v1\nmodels_root: {models}\npois_path: {pois_path}\n",
        encoding="utf-8",
    )

    spec = parcel_experimental_config_spec(
        config_path,
        experiment_id="grid-v1-test",
        description="model provenance test",
    )

    assert spec.model_id == "grid_v1"
    assert spec.model_artifact_id == str(model_path)
    assert spec.model_artifact_sha256 is not None
    assert spec.process_descriptor is not None
    source_provenance = spec.report_metadata()["provenance"]["policy_source_tree"]
    assert source_provenance["id"] == "src/parcel_robot"
    assert len(source_provenance["sha256"]) == 64
    dependencies = spec.report_metadata()["provenance"]["runtime_dependencies"]
    registry = dependencies["navigation_model_registry"]
    assert registry["membership"] == "exact_direct_*.yaml"
    assert registry["file_count"] == 2
    assert [record["id"] for record in registry["files"]] == [
        str(model_path),
        str(inactive_path),
    ]
    assert [record["size_bytes"] for record in registry["files"]] == [
        model_path.stat().st_size,
        inactive_path.stat().st_size,
    ]
    assert dependencies["places_of_interest"]["id"] == str(pois_path)
    assert dependencies["places_of_interest"]["size_bytes"] == pois_path.stat().st_size
    assert len(dependencies["dependency_set_sha256"]) == 64
    assert dependencies["active_model_checkpoint"] is None


def test_process_policy_descriptor_rejects_non_active_registry_changes(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "active.yaml").write_text("id: grid_v1\ntype: grid\n", encoding="utf-8")
    inactive_path = models / "inactive.yaml"
    inactive_path.write_text("id: spare_v1\ntype: stub\n", encoding="utf-8")
    config_path = tmp_path / "candidate.yaml"
    config_path.write_text(
        f"active_model: grid_v1\nmodels_root: {models}\n",
        encoding="utf-8",
    )
    spec = parcel_experimental_config_spec(
        config_path,
        experiment_id="registry-transitive-hash-guard",
        description="all model registry inputs are frozen",
    )
    assert spec.process_descriptor is not None

    # Preserve file size so the content digest, rather than size alone, must catch it.
    inactive_path.write_text("id: spare_v2\ntype: stub\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after parent validation"):
        spec.process_descriptor.create(episode_seed=1)


def test_process_policy_descriptor_rejects_registry_membership_and_poi_changes(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "active.yaml").write_text("id: grid_v1\ntype: grid\n", encoding="utf-8")
    pois_path = tmp_path / "pois.yaml"
    pois_path.write_text("pois: []\n", encoding="utf-8")
    config_path = tmp_path / "candidate.yaml"
    config_path.write_text(
        f"active_model: grid_v1\nmodels_root: {models}\npois_path: {pois_path}\n",
        encoding="utf-8",
    )
    spec = parcel_experimental_config_spec(
        config_path,
        experiment_id="registry-membership-guard",
        description="model registry membership is frozen",
    )
    assert spec.process_descriptor is not None
    (models / "added.yaml").write_text("id: added_v1\ntype: stub\n", encoding="utf-8")
    with pytest.raises(ValueError, match="registry membership changed"):
        spec.process_descriptor.create(episode_seed=1)

    (models / "added.yaml").unlink()
    pois_spec = parcel_experimental_config_spec(
        config_path,
        experiment_id="poi-content-guard",
        description="POI bytes and size are frozen",
    )
    assert pois_spec.process_descriptor is not None
    pois_path.write_text("pois: []\n# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after parent validation"):
        pois_spec.process_descriptor.create(episode_seed=1)


@pytest.mark.parametrize("checkpoint_kind", ["file", "directory"])
def test_process_policy_descriptor_freezes_active_checkpoint_closure(
    tmp_path: Path,
    checkpoint_kind: str,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    checkpoint = tmp_path / "checkpoint"
    if checkpoint_kind == "file":
        checkpoint.write_bytes(b"weight-v1")
    else:
        checkpoint.mkdir()
        (checkpoint / "config.json").write_text('{"version": 1}\n', encoding="utf-8")
        (checkpoint / "weights.bin").write_bytes(b"weight-v1")
    (models / "active.yaml").write_text(
        f"id: external_v1\ntype: citywalker\ncheckpoint: {checkpoint}\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "candidate.yaml"
    config_path.write_text(
        f"active_model: external_v1\nmodels_root: {models}\n",
        encoding="utf-8",
    )
    spec = parcel_experimental_config_spec(
        config_path,
        experiment_id=f"active-checkpoint-{checkpoint_kind}",
        description="active checkpoint closure is frozen",
    )
    assert spec.process_descriptor is not None
    checkpoint_metadata = spec.report_metadata()["provenance"]["runtime_dependencies"][
        "active_model_checkpoint"
    ]
    assert checkpoint_metadata["kind"] == checkpoint_kind
    assert checkpoint_metadata["file_count"] == (1 if checkpoint_kind == "file" else 2)
    assert all(record["size_bytes"] > 0 for record in checkpoint_metadata["files"])

    if checkpoint_kind == "file":
        checkpoint.write_bytes(b"weight-v2")
    else:
        (checkpoint / "added.bin").write_bytes(b"new")
    with pytest.raises(ValueError, match="changed after parent validation"):
        spec.process_descriptor.create(episode_seed=1)


def test_process_policy_descriptor_rejects_changed_inputs(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    model_path = models / "grid.yaml"
    model_path.write_text("id: grid_v1\ntype: grid\n", encoding="utf-8")
    config_path = tmp_path / "candidate.yaml"
    config_path.write_text(
        f"active_model: grid_v1\nmodels_root: {models}\n",
        encoding="utf-8",
    )
    spec = parcel_experimental_config_spec(
        config_path,
        experiment_id="grid-v1-hash-guard",
        description="worker input hash guard",
    )
    assert spec.process_descriptor is not None
    model_path.write_text("id: grid_v1\ntype: grid\ndevice: cuda\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after parent validation"):
        spec.process_descriptor.create(episode_seed=1)


def test_process_policy_descriptor_rejects_changed_policy_source_tree(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "stub.yaml").write_text("id: stub_v0\ntype: stub\n", encoding="utf-8")
    config_path = tmp_path / "candidate.yaml"
    config_path.write_text(
        f"active_model: stub_v0\nmodels_root: {models}\n",
        encoding="utf-8",
    )
    source_root = tmp_path / "policy-source"
    source_root.mkdir()
    source_path = source_root / "controller.py"
    source_path.write_text("VALUE = 1\n", encoding="utf-8")
    spec = parcel_experimental_config_spec(
        config_path,
        experiment_id="source-tree-hash-guard",
        description="worker policy source hash guard",
    )
    assert spec.process_descriptor is not None
    descriptor = replace(
        spec.process_descriptor,
        policy_source_root=str(source_root),
        policy_source_sha256=policy_specs._source_tree_sha256(source_root),
    )
    source_path.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="policy source tree changed"):
        descriptor.create(episode_seed=1)


def test_config_spec_fails_on_missing_or_duplicate_declared_model_id(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    config_path = tmp_path / "candidate.yaml"
    config_path.write_text(
        f"active_model: grid_v1\nmodels_root: {models}\n",
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="grid_v1"):
        parcel_experimental_config_spec(
            config_path,
            experiment_id="missing-model",
            description="missing model must fail closed",
        )

    (models / "first.yaml").write_text("id: grid_v1\ntype: grid\n", encoding="utf-8")
    (models / "second.yaml").write_text("id: grid_v1\ntype: grid\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate navigation model id"):
        parcel_experimental_config_spec(
            config_path,
            experiment_id="duplicate-model",
            description="duplicate model must fail closed",
        )


def test_paired_harness_uses_same_world_trial_seed_and_reports_deltas(tmp_path: Path) -> None:
    _assets(tmp_path)
    baseline_seeds: list[int] = []
    candidate_seeds: list[int] = []
    baseline = _spec("baseline", 0.5, baseline_seeds, experimental=False)
    candidate = _spec("candidate", 2.0, candidate_seeds, experimental=True)

    report = run_barn_comparison(
        assets_root=tmp_path,
        world_indices=(0,),
        baseline_spec=baseline,
        candidate_spec=candidate,
        trials=2,
        lidar_ray_count=9,
        suite_seed=41,
        allow_experimental=True,
    )

    assert baseline_seeds == candidate_seeds == [41, 42]
    assert report["official_gazebo_score"] is False
    assert report["comparison"]["same_worlds_trials_config_and_seeds"] is True
    assert report["comparison"]["paired_episode_count"] == 2
    assert report["comparison"]["candidate_minus_baseline"]["navigation_metric"] > 0.0
    assert report["comparison"]["candidate_minus_baseline"]["success_rate"] == 0.0
    assert report["comparison"]["safety_regression"] is False
    assert report["target_status"]["official_gate_pass"] is False
    assert report["candidate"]["policy"]["experimental"] is True
    assert report["candidate"]["policy"]["production_behavior_modified"] is True
    assert report["candidate"]["policy"]["production_default_behavior_modified"] is False
    assert report["candidate"]["policy"]["deployment_enabled"] is False


def test_paired_harness_propagates_spawn_workers_to_builtin_arms(tmp_path: Path) -> None:
    _assets(tmp_path)
    candidate_config = tmp_path / "candidate.yaml"
    candidate_config.write_text(
        DEFAULT_NAVIGATION_CONFIG.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    candidate = parcel_experimental_config_spec(
        candidate_config,
        experiment_id="spawned-candidate",
        description="same policy through spawned comparison workers",
    )

    report = run_barn_comparison(
        assets_root=tmp_path,
        world_indices=(0,),
        candidate_spec=candidate,
        trials=2,
        lidar_ray_count=31,
        suite_seed=83,
        allow_experimental=True,
        workers=2,
    )

    assert report["comparison"]["same_worlds_trials_config_and_seeds"] is True
    assert report["comparison"]["candidate_minus_baseline"]["navigation_metric"] == 0.0
    assert report["baseline"]["execution"]["episode_workers_effective"] == 2
    assert report["candidate"]["execution"]["episode_workers_effective"] == 2


def test_evaluator_diagnostics_are_nested_and_failure_notes_are_separate(
    tmp_path: Path,
) -> None:
    _assets(tmp_path)

    class StopPolicy(_StraightPolicy):
        def act(self, observation: BarnObservation) -> BarnAction:
            del observation
            return BarnAction(0.0, 0.0, stop=True, note="policy_chose_stop")

    seeds: list[int] = []
    spec = BarnPolicySpec(
        policy_id="stop-baseline",
        description="stop outside goal",
        agent_id="test-stop",
        adapter_id="sensor-only-test",
        model_id="none",
        factory=lambda seed: StopPolicy(0.0, seeds, seed),
    )
    report = run_barn_suite(
        assets_root=tmp_path,
        world_indices=(0,),
        lidar_ray_count=9,
        policy_spec=spec,
    )

    diagnostics = report["aggregate"]["evaluator_diagnostics"]
    policy_diagnostics = report["aggregate"]["policy_diagnostics"]
    assert diagnostics["private_state_not_exposed_to_policy"] is True
    assert diagnostics["failure_counts"] == {"stopped_outside_goal": 1}
    assert diagnostics["mean_maximum_goal_progress_m"] == 0.0
    assert policy_diagnostics["terminal_action_note_counts"] == {"policy_chose_stop": 1}
    assert "policy_chose_stop" not in diagnostics["failure_counts"]
    assert report["episodes"][0]["evaluator_diagnostics"]["evaluator_private_state"] is True
