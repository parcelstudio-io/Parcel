from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

import evals.external.run_predictive_shield_v7 as v7_runner
from evals.external.barn_native import barn_navigation_metric
from evals.external.compare_barn import compare_barn_reports
from evals.external.generate_predictive_shield_v7_corpus import (
    BARN_RUNTIME_HOKUYO_URDF,
    BARN_RUNTIME_J100_URDF,
    BARN_RUNTIME_ROBOT_URDF,
    DEFAULT_ASSETS_ROOT,
    DEFAULT_MANIFEST,
    DEVELOPMENT_WORLD_IDS,
    EXPECTED_EFFECTIVE_CONFIG_DIFF,
    FORBIDDEN_WORLD_IDS,
    IMMUTABLE_ROS_REFERENCE_CONFIG_SHA256,
    PROMOTION_GATE,
    SEALED_CONFIRMATION_WORLD_IDS,
    _seed,
    effective_config_differences,
    generate_corpus,
    runtime_calibration_preflight,
    verify_one_factor_configs,
)
from evals.external.predictive_shield_v7_retirement import (
    RETIREMENT_RECORD,
    RETIREMENT_RECORD_SHA256,
    RetiredExperimentError,
    v7_retirement_record,
)
from evals.external.run_predictive_shield_v7 import (
    _run_single_use_claimed_execution,
    _validated_run_id,
    _write_immutable_json,
    causal_pair_diagnostics,
    evaluate_gate,
)
from parcel_robot.navigation.collision import CollisionPolicy, apply_collision_brake


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ids_sha256(values: tuple[int, ...]) -> str:
    return _sha256_text(",".join(str(value) for value in values))


def _policy_metadata() -> dict[str, Any]:
    return {
        "agent_id": "DirectiveNavigator",
        "adapter_id": "parcel-barn-calibrated-sensor-adapter-v1",
        "model_id": "grid_v1",
        "execution_device": "cpu",
        "underlying_policy_adapter_id": "parcel-barn-adapter-v1",
        "sensor_transport": {"id": "calibrated-sensor-v1"},
        "policy_inputs": [
            "goal_in_odom_frame",
            "platform_odometry",
            "calibrated_front_360_degree_lidar",
            "simulation_clock",
        ],
        "provenance": {
            "implementation": {"id": "sensor-adapter", "sha256": "a" * 64},
            "policy_source_tree": {"id": "src/parcel_robot", "sha256": "b" * 64},
            "model_artifact": {"id": "grid.yaml", "sha256": "c" * 64},
            "runtime_dependencies": {
                "dependency_set_sha256": "e" * 64,
                "navigation_model_registry": {"file_count": 14},
                "places_of_interest": {"sha256": "f" * 64},
                "active_model_checkpoint": None,
            },
            "calibrated_sensor_transport": {
                "id": "barn_ros2_adapter.py",
                "sha256": "9" * 64,
            },
            # Config provenance is intentionally different between the two
            # arms and is excluded by the runner's policy-equivalence check.
            "config": {"id": "arm.yaml", "sha256": "d" * 64},
        },
    }


def _episode(
    world_index: int,
    *,
    candidate: bool,
    divergence_observation: str | None = None,
) -> dict[str, Any]:
    offset = world_index - DEVELOPMENT_WORLD_IDS[0]
    success = offset < (24 if candidate else 21)
    elapsed = 50.0 if success else 100.0
    optimal_path_length = 20.0
    observation_hashes = [
        _sha256_text(f"world={world_index}:observation={step}") for step in range(51)
    ]
    if divergence_observation is not None:
        observation_hashes[1] = divergence_observation
    action_values = [
        [step, 0.1 if step == 0 else (0.2 if candidate else 0.0), 0.2, False]
        for step in range(51)
    ]
    action_hashes = [
        hashlib.sha256(
            struct.pack("<dd", float(forward), float(yaw_rate))
            + (b"\x01" if stop else b"\x00")
        ).hexdigest()
        for _step, forward, yaw_rate, stop in action_values
    ]
    return {
        "world_index": world_index,
        "trial": 0,
        "episode_seed": 20260803 + world_index * 1_009,
        "success": success,
        "collided": False,
        "timed_out": not success,
        "startup_timed_out": False,
        "trial_started": True,
        "stopped": False,
        "status": "succeeded" if success else "timeout",
        "startup_time_s": 0.1,
        "elapsed_time_s": elapsed,
        "simulation_elapsed_time_s": elapsed + 0.1,
        "steps": 51,
        "final_distance_to_goal_m": 0.5 if success else 5.0,
        "final_position_xy": [-2.25, 12.5 if success else 8.0],
        "optimal_path_length_m": optimal_path_length,
        "optimal_time_s": optimal_path_length / 2.0,
        "navigation_metric": barn_navigation_metric(success, elapsed, optimal_path_length),
        "evaluator_diagnostics": {
            "evaluator_private_state": True,
            "maximum_goal_progress_m": 24.5 if success else 20.0,
            "minimum_signed_obstacle_clearance_m": 0.46 if candidate else 0.48,
        },
        "sensor_diagnostics": {
            "policy_observation_steps": list(range(51)),
            "policy_observation_sha256": observation_hashes,
            "published_action_steps": list(range(51)),
            "published_action_sha256": action_hashes,
            "published_action_values": action_values,
            "normalization_failures": 0,
        },
        "shield_stall_diagnostics": {
            "policy_stop_latched": False,
            "policy_stop_latch_step": None,
            "issued_policy_command_steps": 51,
            "obstacle_stop_steps": 0 if candidate else 50,
            "obstacle_stop_command_steps": [] if candidate else list(range(1, 51)),
            "max_consecutive_obstacle_stop_steps": 0 if candidate else 50,
            "reverse_command_steps": 0,
        },
    }


def _passing_report() -> dict[str, Any]:
    worlds = DEVELOPMENT_WORLD_IDS
    reference_policy = _policy_metadata()
    candidate_policy = copy.deepcopy(reference_policy)
    reference_policy["provenance"]["config"] = {  # type: ignore[index]
        "id": "barn_grid_v1.yaml",
        "sha256": IMMUTABLE_ROS_REFERENCE_CONFIG_SHA256,
    }
    candidate_policy["provenance"]["config"] = {  # type: ignore[index]
        "id": "barn_grid_v1_projected_speed_cap_0p8_v7.yaml",
        "sha256": verify_one_factor_configs()["challenger_config_sha256"],
    }
    native_config = {
        "dt_s": 0.1,
        "robot_radius_m": 0.32,
        "success_radius_m": 1.0,
        "timeout_s": 100.0,
    }
    execution = {
        "evaluator_device": "cpu",
        "lidar_raycast_device": "cpu",
        "kinematics_device": "cpu",
        "policy_declared_device": "cpu",
        "episode_workers_requested": 4,
        "episode_workers_effective": 4,
        "process_start_method": "spawn",
        "durable_report_writer": "caller_or_parent_process_only",
    }
    assets = [
        {
            "world_index": world_index,
            "world": {"sha256": _sha256_text(f"world-{world_index}")},
            "reference_path": {"sha256": _sha256_text(f"path-{world_index}")},
        }
        for world_index in worlds
    ]
    provenance = {
        "config_sha256": "1" * 64,
        "harness": {"sha256": "2" * 64},
        "native_geometry": {"sha256": "3" * 64},
        "calibrated_adapter": {"sha256": "4" * 64},
        "assets": assets,
    }
    benchmark = {
        "id": v7_runner.SENSOR_FAITHFUL_EVALUATION_KIND,
        "source": v7_runner.BARN_SOURCE,
        "source_commit": v7_runner.BARN_SOURCE_COMMIT,
        "asset_manifest_sha256": "f" * 64,
        "public_world_indices": list(worlds),
        "official_gazebo_score": False,
        "asset_scope": "generated-public-style-development",
    }
    reference_episodes = [_episode(world_index, candidate=False) for world_index in worlds]
    candidate_episodes = [_episode(world_index, candidate=True) for world_index in worlds]
    report = {
        "baseline": {
            "benchmark": benchmark,
            "native_config": native_config,
            "suite_seed": 20260803,
            "execution": execution,
            "provenance": provenance,
            "policy": reference_policy,
            "aggregate": {
                "episodes": 30.0,
                "worlds": 30.0,
                "trials_per_world": 1.0,
                "success_rate": 0.70,
                "navigation_metric": 0.14,
                "collision_rate": 0.0,
                "timeout_rate": 0.30,
                "startup_failure_rate": 0.0,
                "stopped_outside_goal_rate": 0.0,
                "policy_stop_latch_rate": 0.0,
                "adapter_act_p99_ms": 20.0,
                "controller_step_p99_ms": 18.0,
                "mean_final_distance_to_goal_m": 1.85,
                "sensor_diagnostics": {
                    "long_shield_stall_threshold_steps": 50,
                    "long_shield_stall_episode_count": 30,
                    "sensor_normalization_failures": 0,
                    "reverse_command_steps": 0,
                    "obstacle_stop_steps": 1_500,
                    "max_consecutive_obstacle_stop_steps": 50,
                },
                "evaluator_diagnostics": {
                    "private_state_not_exposed_to_policy": True,
                    "outcome_counts": {"succeeded": 21, "timeout": 9},
                    "failure_counts": {"timeout": 9},
                    "minimum_signed_obstacle_clearance_m": 0.48,
                    "mean_maximum_goal_progress_m": 23.15,
                    "mean_goal_progress_efficiency": 0.8,
                },
            },
            "episodes": reference_episodes,
        },
        "candidate": {
            "benchmark": copy.deepcopy(benchmark),
            "native_config": native_config,
            "suite_seed": 20260803,
            "execution": copy.deepcopy(execution),
            "provenance": copy.deepcopy(provenance),
            "policy": candidate_policy,
            "aggregate": {
                "episodes": 30.0,
                "worlds": 30.0,
                "trials_per_world": 1.0,
                "success_rate": 0.80,
                "navigation_metric": 0.16,
                "collision_rate": 0.0,
                "timeout_rate": 0.20,
                "startup_failure_rate": 0.0,
                "stopped_outside_goal_rate": 0.0,
                "policy_stop_latch_rate": 0.0,
                "adapter_act_p99_ms": 21.0,
                "controller_step_p99_ms": 19.0,
                "mean_final_distance_to_goal_m": 1.40,
                "sensor_diagnostics": {
                    "long_shield_stall_threshold_steps": 50,
                    "long_shield_stall_episode_count": 0,
                    "sensor_normalization_failures": 0,
                    "reverse_command_steps": 0,
                    "obstacle_stop_steps": 0,
                    "max_consecutive_obstacle_stop_steps": 0,
                },
                "evaluator_diagnostics": {
                    "private_state_not_exposed_to_policy": True,
                    "outcome_counts": {"succeeded": 24, "timeout": 6},
                    "failure_counts": {"timeout": 6},
                    "minimum_signed_obstacle_clearance_m": 0.46,
                    "mean_maximum_goal_progress_m": 23.60,
                    "mean_goal_progress_efficiency": 0.82,
                },
            },
            "episodes": candidate_episodes,
        },
    }
    report["comparison"] = compare_barn_reports(report["baseline"], report["candidate"])
    return report


def _synthetic_gate_contract() -> dict[str, Any]:
    report = _passing_report()
    reference = report["baseline"]
    candidate = report["candidate"]
    return {
        "manifest_sha256": "f" * 64,
        "native_config": copy.deepcopy(reference["native_config"]),
        "calibrated_config_sha256": "1" * 64,
        "suite_seed": 20260803,
        "reference_policy": copy.deepcopy(reference["policy"]),
        "candidate_policy": copy.deepcopy(candidate["policy"]),
        "execution": copy.deepcopy(reference["execution"]),
        "benchmark": copy.deepcopy(reference["benchmark"]),
        "provenance_component_sha256": {
            "sensor_faithful_runner": "2" * 64,
            "barn_native": "3" * 64,
            "barn_ros2_adapter": "4" * 64,
        },
        "asset_sha256": {
            str(item["world_index"]): {
                "world": item["world"]["sha256"],
                "path": item["reference_path"]["sha256"],
            }
            for item in reference["provenance"]["assets"]
        },
        "optimal_path_length_m": {str(world_index): 20.0 for world_index in DEVELOPMENT_WORLD_IDS},
        "historical_reference_preflight": {
            "claims": {"reference_implementation_matches_exercised_package": True}
        },
    }


def _evaluate_synthetic_gate(
    report: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, bool], dict[str, Any]]:
    """Exercise gate math without requiring the external historical-run cache."""

    del monkeypatch
    return evaluate_gate(report, expected_contract=_synthetic_gate_contract())


def _collision_policy(profile: dict[str, Any]) -> CollisionPolicy:
    return CollisionPolicy(
        person_stop_m=float(profile["person_stop_m"]),
        person_slow_m=float(profile["person_slow_m"]),
        obstacle_stop_m=float(profile["obstacle_stop_m"]),
        obstacle_slow_m=float(profile["obstacle_slow_m"]),
        slow_scale=float(profile["slow_scale"]),
        reaction_time_s=float(profile["reaction_time_s"]),
        predictive_mode=str(profile["predictive_mode"]),
    )


def test_v7_configs_are_exact_one_factor_0p8_profiles() -> None:
    preflight = verify_one_factor_configs()

    assert preflight["reference_config_sha256"] == (IMMUTABLE_ROS_REFERENCE_CONFIG_SHA256)
    assert (
        effective_config_differences()
        == EXPECTED_EFFECTIVE_CONFIG_DIFF
        == {"safety.predictive_mode": ("stop", "projected_speed_cap")}
    )
    assert preflight["effective_leaf_differences"] == {
        "safety.predictive_mode": {
            "reference": "stop",
            "challenger": "projected_speed_cap",
        }
    }

    reference = preflight["reference_collision_profile"]
    candidate = preflight["challenger_collision_profile"]
    assert reference["predictive_mode"] == "stop"
    assert candidate["predictive_mode"] == "projected_speed_cap"
    for name, expected in {
        "max_vx": 0.45,
        "max_vy": 0.25,
        "max_vyaw": 0.8,
        "person_stop_m": 1.2,
        "person_slow_m": 2.5,
        "obstacle_stop_m": 0.8,
        "obstacle_slow_m": 1.2,
        "slow_scale": 0.35,
        "reaction_time_s": 0.12,
    }.items():
        assert float(reference[name]) == pytest.approx(expected)
        assert float(candidate[name]) == pytest.approx(expected)

    normalized_candidate = dict(candidate)
    normalized_candidate["predictive_mode"] = "stop"
    assert normalized_candidate == reference


def test_v7_is_immutably_retired_before_any_corpus_or_execution() -> None:
    record = v7_retirement_record()

    assert record["status"] == "invalidated_pre_execution"
    assert record["score"] is None
    assert record["corpus_generated"] is False
    assert record["policy_execution_started"] is False
    assert hashlib.sha256(RETIREMENT_RECORD.read_bytes()).hexdigest() == (
        RETIREMENT_RECORD_SHA256
    )
    assert not DEFAULT_ASSETS_ROOT.exists()
    assert not DEFAULT_MANIFEST.exists()
    with pytest.raises(RetiredExperimentError, match="invalidated before corpus generation"):
        generate_corpus()
    with pytest.raises(RetiredExperimentError, match="invalidated before corpus generation"):
        v7_runner.run_development()
    assert not DEFAULT_ASSETS_ROOT.exists()
    assert not DEFAULT_MANIFEST.exists()


def test_v7_calibration_is_derived_from_the_pinned_barn_runtime() -> None:
    if not all(
        path.is_file()
        for path in (
            BARN_RUNTIME_ROBOT_URDF,
            BARN_RUNTIME_J100_URDF,
            BARN_RUNTIME_HOKUYO_URDF,
        )
    ):
        pytest.skip("content-addressed BARN runtime cache is not installed")
    calibration = runtime_calibration_preflight()

    assert calibration["resolved"] == {
        "angle_min_rad": -math.pi,
        "angle_max_rad": math.pi,
        "ray_count": 720,
        "range_min_m": 0.05,
        "range_max_m": 25.0,
        "base_to_lidar_forward_m": 0.12,
        "self_mask_radius_m": 0.05,
        "range_resolution_m": 0.01,
    }
    assert set(calibration["sources"]) == {
        "generated_robot_urdf",
        "j100_platform_urdf",
        "hokuyo_sensor_urdf",
    }
    assert all(len(record["sha256"]) == 64 for record in calibration["sources"].values())
    assert calibration["content_addressed_source_sha256"] == {
        "generated_robot_urdf": (
            "1838f0aab300aeaa94491100bd51e1b8b07a9d0f5e8c1f25285dc9f64cf46b8c"
        ),
        "j100_platform_urdf": ("79753aba798941180cf86665a43f5496fdff23cef43ed7feab2636f69e158b38"),
        "hokuyo_sensor_urdf": ("5fc4a8176ab642c3d5dc1c97d0ecb9cb83180ba383508ce481997726d8087c51"),
    }
    assert calibration["validated_planar_transform_chain"][0] == "base_link"
    assert calibration["validated_planar_transform_chain"][-1] == "lidar2d_0_laser"


def test_v7_identity_partition_and_promotion_gate_are_predeclared() -> None:
    assert DEVELOPMENT_WORLD_IDS == tuple(range(3000, 3030))
    assert SEALED_CONFIRMATION_WORLD_IDS == tuple(range(3030, 3050))
    assert FORBIDDEN_WORLD_IDS == (
        tuple(range(300)) + tuple(range(1000, 1050)) + tuple(range(2000, 2050))
    )
    assert set(DEVELOPMENT_WORLD_IDS).isdisjoint(FORBIDDEN_WORLD_IDS)
    assert set(DEVELOPMENT_WORLD_IDS).isdisjoint(SEALED_CONFIRMATION_WORLD_IDS)
    assert set(SEALED_CONFIRMATION_WORLD_IDS).isdisjoint(FORBIDDEN_WORLD_IDS)
    assert _ids_sha256(DEVELOPMENT_WORLD_IDS) == (
        "cbfc1082dfb86337baf9ff6a4342ba21eb5a86dada6ece7816f432ffc69007dc"
    )
    assert _ids_sha256(SEALED_CONFIRMATION_WORLD_IDS) == (
        "04c2c536643459747d3600161bf7fbc7e131862566051a1b1594bc711cec6716"
    )
    assert _ids_sha256(FORBIDDEN_WORLD_IDS) == (
        "c7bf3bd22ba645294c09e8be66f68b546f4d505a97b111f643ffefc247d6b85b"
    )
    assert _seed(3000, 1) == _seed(3000, 1)
    assert _seed(3000, 1) != _seed(3000, 2)
    assert _seed(3000, 1) != _seed(3001, 1)

    assert PROMOTION_GATE == {
        "reference_policy": "grid_v1_0p8_predictive_stop",
        "candidate_policy": "grid_v1_0p8_projected_speed_cap_v7",
        "single_effective_config_difference": True,
        "exact_immutable_ros_reference": True,
        "same_worlds_trials_seeds_dynamics_manifest_sources": True,
        "long_shield_stall_steps": 50,
        "minimum_reference_long_shield_stall_episodes": 1,
        "maximum_candidate_long_shield_stall_episodes": 0,
        "minimum_mode_affected_paired_episodes": 1,
        "all_first_divergences_must_share_identical_observation": True,
        "all_action_observation_prefixes_must_match_before_divergence": True,
        "minimum_legacy_stop_replaced_by_safe_forward_pairs": 1,
        "minimum_paired_success_gains": 3,
        "maximum_paired_success_regressions": 0,
        "minimum_success_rate_delta": 0.10,
        "minimum_navigation_metric_delta": 0.01,
        "minimum_timeout_or_stop_rate_reduction": 0.10,
        "candidate_collision_rate_must_equal": 0.0,
        "candidate_timeout_rate_must_not_exceed_reference": True,
        "maximum_startup_failure_rate": 0.0,
        "minimum_signed_body_clearance_m": 0.45,
        "maximum_clearance_floor_regression_m": 0.03,
        "maximum_controller_p99_latency_ms": 100.0,
        "maximum_controller_p99_latency_ratio": 1.20,
        "maximum_sensor_normalization_failures": 0,
        "maximum_reverse_command_steps": 0,
        "all_conditions_required_for_single_sealed_confirmation": True,
    }


def test_v7_projected_mode_resolves_diagnosed_predictive_stop_without_weakening_hard_stop() -> None:
    preflight = verify_one_factor_configs()
    reference = _collision_policy(preflight["reference_collision_profile"])
    candidate = _collision_policy(preflight["challenger_collision_profile"])
    requested_vx = 0.5647
    nearest_range_m = 0.8592
    nearest_bearing_rad = 0.8639
    inputs = {
        "nearest_person_m": None,
        "nearest_obstacle_m": nearest_range_m,
        "nearest_obstacle_bearing_rad": nearest_bearing_rad,
    }

    stopped = apply_collision_brake(
        requested_vx,
        0.0,
        policy=reference,
        **inputs,
    )
    projected = apply_collision_brake(
        requested_vx,
        0.0,
        policy=candidate,
        **inputs,
    )

    assert reference.obstacle_stop_m + requested_vx * reference.reaction_time_s > (nearest_range_m)
    assert stopped == (0.0, 0.0, "obstacle_stop")
    assert projected[0] == pytest.approx(0.197645)
    assert projected[1:] == (0.0, "obstacle_slow")
    projected_closing_speed = projected[0] * math.cos(nearest_bearing_rad)
    assert projected_closing_speed * candidate.reaction_time_s <= (
        nearest_range_m - candidate.obstacle_stop_m + 1e-12
    )

    for policy in (reference, candidate):
        assert apply_collision_brake(
            requested_vx,
            0.0,
            nearest_person_m=None,
            nearest_obstacle_m=0.8,
            nearest_obstacle_bearing_rad=nearest_bearing_rad,
            policy=policy,
        ) == (0.0, 0.0, "obstacle_stop")


def test_v7_causal_diagnostics_locate_divergence_on_identical_observation() -> None:
    report = _passing_report()

    causal = causal_pair_diagnostics(report["baseline"], report["candidate"])

    assert causal["mode_affected_paired_episode_count"] == 30
    assert causal["all_first_divergences_share_identical_observation"] is True
    assert causal["all_action_observation_prefixes_identical"] is True
    assert causal["legacy_stop_replaced_by_safe_forward_pair_count"] == 30
    assert all(pair["affected"] for pair in causal["pairs"])
    assert all(pair["first_action_divergence_step"] == 1 for pair in causal["pairs"])
    assert all(pair["first_divergence_observation_identical"] for pair in causal["pairs"])
    assert all(pair["legacy_stop_replaced_by_safe_forward"] for pair in causal["pairs"])
    assert all(
        pair["reference_max_consecutive_obstacle_stop_steps"] == 50 for pair in causal["pairs"]
    )
    assert all(
        pair["candidate_max_consecutive_obstacle_stop_steps"] == 0 for pair in causal["pairs"]
    )


def test_v7_gate_passes_only_when_every_predeclared_condition_holds(monkeypatch) -> None:
    gates, diagnostics = _evaluate_synthetic_gate(_passing_report(), monkeypatch)

    assert all(gates.values())
    assert diagnostics["all_conditions_passed"] is True
    assert gates["first_divergence_observation_identity"] is True
    assert diagnostics["reference_long_shield_stall_episodes"] == 30
    assert diagnostics["candidate_long_shield_stall_episodes"] == 0
    assert diagnostics["mode_affected_paired_episode_count"] == 30
    assert diagnostics["timeout_or_stop_rate_reduction"] == pytest.approx(0.10)
    assert diagnostics["candidate_minimum_signed_clearance_m"] == pytest.approx(0.46)
    assert diagnostics["controller_p99_latency_ratio"] == pytest.approx(1.05)

    failed = copy.deepcopy(_passing_report())
    failed["candidate"]["episodes"][0]["sensor_diagnostics"]["policy_observation_sha256"][1] = (
        _sha256_text("different-observation-at-first-action-divergence")
    )
    failed_gates, failed_diagnostics = _evaluate_synthetic_gate(failed, monkeypatch)

    assert failed_gates["first_divergence_observation_identity"] is False
    assert failed_diagnostics["all_conditions_passed"] is False


def test_v7_gate_rejects_the_legacy_combined_diagnostic_schema(monkeypatch) -> None:
    report = _passing_report()
    episode = report["candidate"]["episodes"][0]
    episode["sensor_faithful_diagnostics"] = episode.pop("sensor_diagnostics")

    with pytest.raises(TypeError, match="sensor diagnostics"):
        _evaluate_synthetic_gate(report, monkeypatch)


def test_v7_evidence_writer_is_no_clobber_and_run_ids_are_path_safe(tmp_path) -> None:
    target = tmp_path / "evidence" / "claim.json"

    _write_immutable_json(target, {"manifest": "a" * 64})

    assert json.loads(target.read_text(encoding="utf-8")) == {"manifest": "a" * 64}
    assert target.stat().st_mode & 0o222 == 0
    with pytest.raises(FileExistsError, match="refusing to replace"):
        _write_immutable_json(target, {"manifest": "b" * 64})
    assert _validated_run_id("barn-v7.valid_01") == "barn-v7.valid_01"
    for value in ("../escape", "/absolute", "space is unsafe", "x" * 129):
        with pytest.raises(ValueError, match="run_id"):
            _validated_run_id(value)


def _single_use_paths(root: Path, run_id: str = "v7-terminal-test") -> dict[str, Path]:
    return {
        "claim_path": root / "claims" / "corpus.json",
        "outcome_path": root / "terminal-outcomes" / "corpus.json",
        "full_report_path": root / "runs" / f"{run_id}.json",
        "ledger_path": root / "ledger" / "runs" / f"{run_id}.json",
        "summary_path": root / f"{run_id}-summary.json",
    }


def _single_use_claim(
    manifest_sha256: str,
    *,
    run_id: str = "v7-terminal-test",
    ownership_nonce: str = "a" * 32,
) -> dict[str, str]:
    return {
        "run_id": run_id,
        "ownership_nonce": ownership_nonce,
        "manifest_sha256": manifest_sha256,
    }


def test_v7_claimed_execution_records_one_completed_terminal_outcome(tmp_path) -> None:
    root = tmp_path / "results"
    manifest_path = tmp_path / "manifest.json"
    _write_immutable_json(manifest_path, {"corpus": "frozen"})
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    paths = _single_use_paths(root)

    def execute(set_stage: Any, claim_sha256: str) -> dict[str, Any]:
        set_stage("report_write")
        _write_immutable_json(paths["full_report_path"], {"claim_sha256": claim_sha256})
        set_stage("ledger_write")
        _write_immutable_json(paths["ledger_path"], {"report": "installed"})
        set_stage("summary_write")
        summary = {"result": "complete"}
        _write_immutable_json(paths["summary_path"], summary)
        return summary

    summary = _run_single_use_claimed_execution(
        canonical_results_root=root,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        run_id="v7-terminal-test",
        claim=_single_use_claim(manifest_sha256),
        execute=execute,
        **paths,
    )

    assert summary == {"result": "complete"}
    outcome = json.loads(paths["outcome_path"].read_text(encoding="utf-8"))
    assert outcome["status"] == "completed"
    assert outcome["stage"] == "all_required_evidence_written"
    assert outcome["exception"] is None
    assert outcome["manifest"]["sha256"] == manifest_sha256
    assert (
        outcome["single_use_claim"]["sha256"]
        == hashlib.sha256(paths["claim_path"].read_bytes()).hexdigest()
    )
    for name, path_key in (
        ("full_report", "full_report_path"),
        ("ledger_record", "ledger_path"),
        ("summary", "summary_path"),
    ):
        assert (
            outcome["artifacts"][name]["sha256"]
            == hashlib.sha256(paths[path_key].read_bytes()).hexdigest()
        )
    assert len(list((root / "terminal-outcomes").glob("*.json"))) == 1

    with pytest.raises(FileExistsError, match="terminal outcome already exists"):
        _run_single_use_claimed_execution(
            canonical_results_root=root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            run_id="alternate-run-id",
            claim=_single_use_claim(manifest_sha256, run_id="alternate-run-id"),
            execute=execute,
            **paths,
        )


def test_v7_claimed_execution_catches_baseexception_and_burns_the_corpus(tmp_path) -> None:
    root = tmp_path / "results"
    manifest_path = tmp_path / "manifest.json"
    _write_immutable_json(manifest_path, {"corpus": "frozen"})
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    paths = _single_use_paths(root)

    def interrupted(set_stage: Any, claim_sha256: str) -> dict[str, Any]:
        set_stage("report_write")
        _write_immutable_json(paths["full_report_path"], {"claim_sha256": claim_sha256})
        set_stage("ledger_write")
        raise KeyboardInterrupt("simulated operator interrupt")

    with pytest.raises(KeyboardInterrupt, match="simulated operator interrupt"):
        _run_single_use_claimed_execution(
            canonical_results_root=root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            run_id="v7-terminal-test",
            claim=_single_use_claim(manifest_sha256),
            execute=interrupted,
            **paths,
        )

    outcome = json.loads(paths["outcome_path"].read_text(encoding="utf-8"))
    assert outcome["status"] == "aborted"
    assert outcome["stage"] == "ledger_write"
    assert outcome["exception"] == {
        "class": "builtins.KeyboardInterrupt",
        "message": "simulated operator interrupt",
    }
    assert outcome["artifacts"]["full_report"] is not None
    assert outcome["artifacts"]["ledger_record"] is None
    assert outcome["artifacts"]["summary"] is None
    assert len(list((root / "terminal-outcomes").glob("*.json"))) == 1

    with pytest.raises(FileExistsError, match="terminal outcome already exists"):
        _run_single_use_claimed_execution(
            canonical_results_root=root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            run_id="alternate-run-id",
            claim=_single_use_claim(manifest_sha256, run_id="alternate-run-id"),
            execute=interrupted,
            **paths,
        )


def test_v7_concurrent_claim_loser_cannot_terminalize_the_winners_run(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "results"
    manifest_path = tmp_path / "manifest.json"
    _write_immutable_json(manifest_path, {"corpus": "frozen"})
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    paths = _single_use_paths(root, run_id="loser")
    winner_claim = _single_use_claim(
        manifest_sha256,
        run_id="winner",
        ownership_nonce="b" * 32,
    )
    original_write = _write_immutable_json

    def racing_write(path: Path, payload: Any) -> None:
        if path == paths["claim_path"]:
            original_write(path, winner_claim)
            raise FileExistsError("winner installed the claim first")
        original_write(path, payload)

    monkeypatch.setattr(v7_runner, "_write_immutable_json", racing_write)
    executed = False

    def must_not_execute(_set_stage: Any, _claim_sha256: str) -> dict[str, Any]:
        nonlocal executed
        executed = True
        return {}

    with pytest.raises(FileExistsError, match="winner installed"):
        _run_single_use_claimed_execution(
            canonical_results_root=root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            run_id="loser",
            claim=_single_use_claim(
                manifest_sha256,
                run_id="loser",
                ownership_nonce="c" * 32,
            ),
            execute=must_not_execute,
            **paths,
        )

    assert executed is False
    assert json.loads(paths["claim_path"].read_text(encoding="utf-8")) == winner_claim
    assert not paths["outcome_path"].exists()
    assert not paths["full_report_path"].exists()
    assert not paths["ledger_path"].exists()
    assert not paths["summary_path"].exists()


def test_v7_output_preflight_finishes_before_the_corpus_claim(tmp_path) -> None:
    root = tmp_path / "results"
    manifest_path = tmp_path / "manifest.json"
    _write_immutable_json(manifest_path, {"corpus": "frozen"})
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    paths = _single_use_paths(root)
    _write_immutable_json(paths["summary_path"], {"unexpected": "prior evidence"})

    with pytest.raises(FileExistsError, match="summary already exists"):
        _run_single_use_claimed_execution(
            canonical_results_root=root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            run_id="v7-terminal-test",
            claim=_single_use_claim(manifest_sha256),
            execute=lambda _set_stage, _claim_sha256: {},
            **paths,
        )

    assert not paths["claim_path"].exists()
    assert not paths["outcome_path"].exists()


def test_v7_missing_summary_turns_attempted_completion_into_abort(tmp_path) -> None:
    root = tmp_path / "results"
    manifest_path = tmp_path / "manifest.json"
    _write_immutable_json(manifest_path, {"corpus": "frozen"})
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    paths = _single_use_paths(root)

    def incomplete(set_stage: Any, _claim_sha256: str) -> dict[str, Any]:
        set_stage("report_write")
        _write_immutable_json(paths["full_report_path"], {"report": "complete"})
        set_stage("ledger_write")
        _write_immutable_json(paths["ledger_path"], {"ledger": "complete"})
        return {"summary": "not installed"}

    with pytest.raises(RuntimeError, match="requires report, ledger record, and summary"):
        _run_single_use_claimed_execution(
            canonical_results_root=root,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            run_id="v7-terminal-test",
            claim=_single_use_claim(manifest_sha256),
            execute=incomplete,
            **paths,
        )

    outcome = json.loads(paths["outcome_path"].read_text(encoding="utf-8"))
    assert outcome["status"] == "aborted"
    assert outcome["stage"] == "completed_terminal_outcome_write"
    assert outcome["artifacts"]["full_report"] is not None
    assert outcome["artifacts"]["ledger_record"] is not None
    assert outcome["artifacts"]["summary"] is None
