from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from evals.external.barn_native import BarnAction, BarnObservation, BarnWorld
from evals.external.barn_policy_specs import BarnPolicySpec
from evals.external.barn_sensor_faithful import (
    CANDIDATE_THEN_REFERENCE,
    CalibratedBarnConfig,
    SensorFaithfulBarnRunner,
    V8EpisodeEvidenceCaptureSpec,
    calibrated_experimental_config_spec,
    calibrated_reference_config_spec,
    run_sensor_faithful_paired_comparison,
)
from evals.external.barn_v8_action_evidence import read_v8_action_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
BARN_GRID_CONFIG = REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_v1.yaml"


class _FixedPolicy:
    def __init__(self, action: BarnAction) -> None:
        self.action = action
        self.observations: list[BarnObservation] = []

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        del start_xy, heading_rad, goal_xy

    def act(self, observation: BarnObservation) -> BarnAction:
        self.observations.append(observation)
        return self.action

    def close(self) -> None:
        return None


def _world(world_id: int = 4000) -> BarnWorld:
    return BarnWorld(
        world_index=world_id,
        cylinders=(),
        reference_path_grid=((15.0, 0.0), (15.0, 29.0)),
        reference_path_world=((-2.25, 5.075), (-2.25, 9.425)),
        optimal_path_length_m=10.0,
    )


def _assets(root: Path) -> None:
    (root / "path_files").mkdir(parents=True)
    (root / "world_0.world").write_text(
        '<sdf version="1.6"><world name="default"/></sdf>\n',
        encoding="utf-8",
    )
    np.save(root / "path_files" / "path_0.npy", np.asarray([[15, 0], [15, 29]]))


def _spec(name: str, action: BarnAction, *, experimental: bool) -> BarnPolicySpec:
    return BarnPolicySpec(
        policy_id=f"v8-evidence-{name}",
        description=f"v8 evidence {name}",
        agent_id="v8-evidence-test",
        adapter_id="v8-evidence-test",
        model_id="none",
        factory=lambda _seed: _FixedPolicy(action),
        experimental=experimental,
    )


def _paths(
    root: Path,
    *,
    worlds: tuple[int, ...],
    trials: int,
) -> dict[tuple[int, int, str], Path]:
    return {
        (world, trial, arm): root / f"world-{world}-trial-{trial}-{arm}.v8e"
        for world in worlds
        for trial in range(trials)
        for arm in ("reference", "candidate")
    }


def test_direct_runner_binds_exact_normalized_observation_and_stop_latch() -> None:
    policy = _FixedPolicy(BarnAction(0.4, 0.2, stop=True, note="policy-secret"))
    runner = SensorFaithfulBarnRunner(
        _world(),
        CalibratedBarnConfig(timeout_s=0.3, startup_timeout_s=0.3),
    )

    captured = runner.run_with_action_evidence(
        policy,
        V8EpisodeEvidenceCaptureSpec(
            arm="candidate",
            execution_order=1,
            world_id=4000,
            trial_id=2,
            seed=701,
        ),
    )
    records = captured.action_evidence.records

    assert captured.result.steps == 3
    assert len(policy.observations) == 1
    assert len(records) == 3
    first = records[0]
    assert first.step_index == 0
    assert first.issued_by_policy is True
    assert first.observation_reused is False
    assert first.published_stop is True
    assert first.published_vx_mps == 0.0
    assert first.published_vy_mps == 0.0
    assert first.published_yaw_rate_rps == 0.0
    assert first.normalized_scan_float64_le == struct.pack(
        "<720d", *policy.observations[0].lidar_ranges_m
    )
    assert first.angle_min_rad == policy.observations[0].lidar_angle_min_rad
    assert first.angle_increment_rad == policy.observations[0].lidar_angle_increment_rad
    assert (
        first.policy_observation_sha256
        == captured.result.sensor_diagnostics.policy_observation_sha256[0]
    )
    assert first.certificate.unavailable_ray_count == 201
    for step, latched in enumerate(records[1:], start=1):
        assert latched.step_index == step
        assert latched.issued_by_policy is False
        assert latched.observation_reused is True
        assert latched.published_stop is True
        assert latched.published_vx_mps == 0.0
        assert latched.published_yaw_rate_rps == 0.0
        assert latched.normalized_scan_float64_le == first.normalized_scan_float64_le
        assert latched.policy_observation_sha256 == first.policy_observation_sha256
    assert "action_evidence" not in captured.result.sensor_diagnostics.latency
    assert "certificate" not in captured.result.sensor_diagnostics.latency


def test_local_paired_parent_writes_and_recetrifies_predeclared_artifacts(
    tmp_path: Path,
) -> None:
    assets = tmp_path / "assets"
    _assets(assets)
    paths = _paths(tmp_path / "evidence", worlds=(0,), trials=1)

    report = run_sensor_faithful_paired_comparison(
        assets_root=assets,
        world_indices=(0,),
        trials=1,
        suite_seed=811,
        workers=1,
        reference_spec=_spec(
            "reference",
            BarnAction(0.2, 0.0, note="reference-note"),
            experimental=False,
        ),
        candidate_spec=_spec(
            "candidate",
            BarnAction(0.3, 0.0, note="candidate-note"),
            experimental=True,
        ),
        allow_experimental=True,
        config=CalibratedBarnConfig(timeout_s=0.1),
        arm_order_schedule=(CANDIDATE_THEN_REFERENCE,),
        action_evidence_paths=paths,
    )

    summary = report["comparison"]["action_evidence"]
    assert summary["enabled"] is True
    assert summary["immutable_artifact_count"] == 2
    assert summary["expected_immutable_artifact_count"] == 2
    assert summary["all_action_counts_match_published_traces"] is True
    assert summary["all_policy_observation_hashes_match_published_traces"] is True
    assert summary["all_records_format_read_and_recertified"] is True
    assert summary["evaluator_overhead_included_in_controller_latency"] is False
    for arm, expected_order in (("candidate", 0), ("reference", 1)):
        episode_key = "candidate" if arm == "candidate" else "baseline"
        episode = report[episode_key]["episodes"][0]
        metadata = episode["action_evidence"]
        artifact = read_v8_action_evidence(
            paths[(0, 0, arm)],
            expected_artifact_sha256=metadata["identity"]["artifact_sha256"],
        )
        assert metadata["identity"]["execution_order"] == expected_order
        assert metadata["identity"]["arm"] == arm
        assert metadata["identity"]["world_id"] == 0
        assert metadata["identity"]["trial_id"] == 0
        assert metadata["identity"]["seed"] == 811
        assert metadata["evaluator_evidence_overhead_included_in_controller_latency"] is False
        assert metadata["policy_observation_hashes_match_published_trace"] is True
        assert artifact.identity.record_count == len(
            episode["sensor_diagnostics"]["published_action_steps"]
        )
        assert tuple(record.step_index for record in artifact.records) == tuple(
            episode["sensor_diagnostics"]["published_action_steps"]
        )
        assert tuple(
            (record.step_index, record.policy_observation_sha256)
            for record in artifact.records
            if record.issued_by_policy
        ) == tuple(
            zip(
                episode["sensor_diagnostics"]["policy_observation_steps"],
                episode["sensor_diagnostics"]["policy_observation_sha256"],
                strict=True,
            )
        )


def test_spawned_paired_builders_return_to_parent_for_exclusive_evidence_write(
    tmp_path: Path,
) -> None:
    assets = tmp_path / "assets"
    _assets(assets)
    paths = _paths(tmp_path / "spawn-evidence", worlds=(0,), trials=2)
    reference = calibrated_reference_config_spec(
        BARN_GRID_CONFIG,
        reference_id="v8-evidence-spawn-reference",
        description="spawned evidence reference",
    )
    candidate = calibrated_experimental_config_spec(
        BARN_GRID_CONFIG,
        experiment_id="v8-evidence-spawn-candidate",
        description="spawned evidence candidate",
    )

    report = run_sensor_faithful_paired_comparison(
        assets_root=assets,
        world_indices=(0,),
        trials=2,
        suite_seed=907,
        workers=2,
        reference_spec=reference,
        candidate_spec=candidate,
        allow_experimental=True,
        config=CalibratedBarnConfig(timeout_s=0.1),
        action_evidence_paths=paths,
    )

    assert report["baseline"]["execution"]["process_start_method"] == "spawn"
    assert report["candidate"]["execution"]["process_start_method"] == "spawn"
    assert report["comparison"]["action_evidence"]["immutable_artifact_count"] == 4
    assert len(report["comparison"]["action_evidence"]["artifacts"]) == 4
    for key, path in paths.items():
        arm = key[2]
        episode_key = "candidate" if arm == "candidate" else "baseline"
        episode = report[episode_key]["episodes"][key[1]]
        artifact = read_v8_action_evidence(
            path,
            expected_artifact_sha256=episode["action_evidence"]["identity"]["artifact_sha256"],
        )
        assert artifact.identity.arm == arm
        assert artifact.identity.trial_id == key[1]
        assert artifact.identity.record_count == len(
            episode["sensor_diagnostics"]["published_action_steps"]
        )
