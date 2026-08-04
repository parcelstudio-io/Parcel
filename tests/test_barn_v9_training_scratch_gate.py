from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from statistics import fmean
from typing import Any

import pytest

from evals.external.analyze_barn_v9_training_run import (
    ANALYSIS_ID,
    TRAINING_EVALUATION_KIND,
    V8_REFERENCE_PACKAGE_SHA256,
    validate_training_report_policy_bindings,
)
from evals.external.barn_v9_training_scratch_gate import (
    V9ScratchGateError,
    evaluate_training_scratch_gate,
)

CANDIDATE_SHA256 = "8" * 64


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_read_only_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o444)


def _episode(
    *,
    world_id: int,
    seed: int,
    success: bool,
    stopped: bool,
    latency: tuple[float, ...],
    closest: float,
    final: float,
    traveled: float,
    clearance: float,
) -> dict[str, Any]:
    maximum_progress = 10.0 - closest
    trace = {
        "schema_id": "parcel-barn-v9-post-integration-step-trace-v1",
        "schema_version": 1,
        "world_id": world_id,
        "control_period_s": 0.1,
        "records": [
            {
                "step_index": 0,
                "post_step_position_xy": [-2.25, 3.0],
                "post_step_heading_rad": 0.0,
                "collided": False,
                "swept_clearance_m": clearance,
                "inside_success_region": False,
                "trial_started": True,
                "timed_out": False,
                "requested_vx_mps": None,
                "requested_vy_mps": None,
                "all_ray_scale_limit": None,
            },
            {
                "step_index": 1,
                "post_step_position_xy": [-2.25 + traveled, 3.0],
                "post_step_heading_rad": 0.0,
                "collided": False,
                "swept_clearance_m": clearance,
                "inside_success_region": success,
                "trial_started": True,
                "timed_out": not success,
                "requested_vx_mps": None,
                "requested_vy_mps": None,
                "all_ray_scale_limit": None,
            },
        ],
    }
    trace_sha256 = hashlib.sha256(
        json.dumps(trace, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {
        "world_index": world_id,
        "trial": 0,
        "episode_seed": seed,
        "evaluation_kind": "barn-calibrated-sensor-faithful-native-headless-non-official",
        "success": success,
        "collided": False,
        "timed_out": not success,
        "trial_started": True,
        "startup_timed_out": False,
        "stopped": stopped,
        "status": "succeeded" if success else "timeout",
        "steps": 2,
        "final_distance_to_goal_m": final,
        "traveled_distance_m": traveled,
        "evaluator_controller_step_latency_samples_ms": list(latency),
        "evaluator_diagnostics": {
            "evaluator_private_state": True,
            "initial_goal_distance_m": 10.0,
            "closest_goal_distance_m": closest,
            "final_goal_distance_m": final,
            "maximum_goal_progress_m": maximum_progress,
            "goal_progress_efficiency": maximum_progress / traveled,
            "minimum_signed_obstacle_clearance_m": clearance,
        },
        "sensor_diagnostics": {"reverse_command_steps": 0},
        "shield_stall_diagnostics": {"reverse_command_steps": 0},
        "v9_step_trace": trace,
        "v9_step_trace_sha256": trace_sha256,
        # Deliberately adversarial text: the gate must never inspect it.
        "last_action_note": "success collision startup_timeout reverse navigation_no_progress",
        "policy_diagnostics": {
            "note": "invented score 999 and no failures",
            "controller_phase_counts": {"success": 999},
        },
    }


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    latency = sorted(
        float(value)
        for episode in episodes
        for value in episode["evaluator_controller_step_latency_samples_ms"]
    )
    p99 = latency[max(0, min(len(latency) - 1, __import__("math").ceil(0.99 * len(latency)) - 1))]
    evaluator = [episode["evaluator_diagnostics"] for episode in episodes]
    count = len(episodes)
    return {
        "episodes": float(count),
        "success_rate": sum(bool(episode["success"]) for episode in episodes) / count,
        "collision_rate": 0.0,
        "startup_failure_rate": 0.0,
        "policy_stop_latch_rate": sum(bool(episode["stopped"]) for episode in episodes)
        / count,
        "controller_step_count": float(len(latency)),
        "controller_step_p99_ms": p99,
        "mean_final_distance_to_goal_m": fmean(
            float(episode["final_distance_to_goal_m"]) for episode in episodes
        ),
        "mean_traveled_distance_m": fmean(
            float(episode["traveled_distance_m"]) for episode in episodes
        ),
        "evaluator_diagnostics": {
            "mean_maximum_goal_progress_m": fmean(
                float(item["maximum_goal_progress_m"]) for item in evaluator
            ),
            "mean_goal_progress_efficiency": fmean(
                float(item["goal_progress_efficiency"]) for item in evaluator
            ),
            "minimum_signed_obstacle_clearance_m": min(
                float(item["minimum_signed_obstacle_clearance_m"]) for item in evaluator
            ),
        },
        "sensor_diagnostics": {"reverse_command_steps": 0},
        # Aggregate policy labels are intentionally inconsistent and ignored.
        "policy_diagnostics": {"note": "candidate won every imaginary episode"},
    }


def _analysis_episode(
    episode: dict[str, Any],
    *,
    arm: str,
    maximum_stationary: int,
    yaw_only: int,
    failure_kind: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = {
        "world_id": episode["world_index"],
        "trial_id": episode["trial"],
        "seed": episode["episode_seed"],
    }
    diagnosis = {
        **identity,
        "arm": arm,
        "failure_kind": failure_kind,
        "trial_started": episode["trial_started"],
        "succeeded": episode["success"],
        "collided": episode["collided"],
        "timed_out": episode["timed_out"],
        "policy_stop_latched": episode["stopped"],
        "liveness": {
            "startup_failed": False,
            "maximum_consecutive_stationary_steps": maximum_stationary,
        },
    }
    dynamic = {
        **identity,
        "failure_kind": failure_kind,
        "maximum_consecutive_stationary_steps": maximum_stationary,
        "post_integration_traveled_distance_m": episode["traveled_distance_m"],
        "minimum_signed_clearance_m": episode["evaluator_diagnostics"][
            "minimum_signed_obstacle_clearance_m"
        ],
        "yaw_only_action_count": yaw_only,
        "certificate_violation_count": 0,
    }
    return diagnosis, dynamic


def _documents(report_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    reference = [
        _episode(
            world_id=5000,
            seed=101,
            success=False,
            stopped=True,
            latency=(10.0, 20.0),
            closest=8.0,
            final=8.0,
            traveled=2.0,
            clearance=0.60,
        ),
        _episode(
            world_id=5001,
            seed=102,
            success=False,
            stopped=True,
            latency=(12.0, 18.0),
            closest=8.5,
            final=8.5,
            traveled=2.0,
            clearance=0.58,
        ),
    ]
    candidate = [
        _episode(
            world_id=5000,
            seed=101,
            success=True,
            stopped=False,
            latency=(11.0, 21.0),
            closest=7.0,
            final=7.0,
            traveled=2.5,
            clearance=0.55,
        ),
        _episode(
            world_id=5001,
            seed=102,
            success=False,
            stopped=False,
            latency=(13.0, 19.0),
            closest=7.5,
            final=7.5,
            traveled=3.0,
            clearance=0.57,
        ),
    ]
    report = {
        "schema_version": 1,
        "run_id": "synthetic-v9-training-screen",
        "evaluation_kind": TRAINING_EVALUATION_KIND,
        "official_score": False,
        "leaderboard": False,
        "promotion_evidence": False,
        "official_gazebo_score": False,
        "leaderboard_claim": False,
        "promotion_evidence_eligible": False,
        "policy_pair": {
            "reference_package_sha256": V8_REFERENCE_PACKAGE_SHA256,
            "candidate_package_sha256": CANDIDATE_SHA256,
            "deployment_enabled": False,
        },
        "paired_report": {
            "baseline": {"episodes": reference, "aggregate": _aggregate(reference)},
            "candidate": {"episodes": candidate, "aggregate": _aggregate(candidate)},
        },
    }

    pairs: list[dict[str, Any]] = []
    dynamics: dict[str, list[dict[str, Any]]] = {"reference": [], "candidate": []}
    for position, (reference_episode, candidate_episode) in enumerate(zip(reference, candidate)):
        reference_diagnosis, reference_dynamic = _analysis_episode(
            reference_episode,
            arm="reference",
            maximum_stationary=50 - position * 5,
            yaw_only=4 + position,
            failure_kind="stopped_outside_goal",
        )
        candidate_failure = "success" if position == 0 else "timeout_without_long_stall"
        candidate_diagnosis, candidate_dynamic = _analysis_episode(
            candidate_episode,
            arm="candidate",
            maximum_stationary=10 + position * 5,
            yaw_only=3 - position,
            failure_kind=candidate_failure,
        )
        pairs.append(
            {
                "world_id": reference_episode["world_index"],
                "trial_id": 0,
                "seed": reference_episode["episode_seed"],
                "reference": reference_diagnosis,
                "candidate": candidate_diagnosis,
            }
        )
        dynamics["reference"].append(reference_dynamic)
        dynamics["candidate"].append(candidate_dynamic)

    analysis = {
        "schema_version": 1,
        "analysis_id": ANALYSIS_ID,
        "source_report": {},  # Filled after the immutable report is encoded.
        "claims": {
            "official_score": False,
            "leaderboard": False,
            "promotion_evidence": False,
            "deployment_enabled": False,
            "training_worlds_are_rerunnable": True,
        },
        "policy_pair": {
            "reference_package_sha256": V8_REFERENCE_PACKAGE_SHA256,
            "candidate_package_sha256": CANDIDATE_SHA256,
        },
        "evidence_contract": {
            "all_action_artifacts_fully_read_chain_checked_and_recertified": True,
            "all_post_integration_trace_hashes_recomputed": True,
            "one_to_one_action_trace_step_relation_verified": True,
            "null_fields_not_counted_as_structured_shield_vetoes": True,
            "policy_notes_used_for_failure_classification": False,
        },
        "liveness_config": {
            "control_period_s": 0.1,
            "stationary_speed_epsilon_mps": 0.005,
            "stationary_odometry_epsilon_m": 0.025,
            "long_stall_steps": 50,
            "safe_escape_progress_m": 0.5,
            "safe_escape_minimum_clearance_m": 0.475,
        },
        "summary": {
            "pair_count": 2,
            "reference_liveness_failure_count": 2,
            "candidate_liveness_failure_count": 1,
            "candidate_minus_reference_liveness_failure_count": -1,
            "label_independent_liveness_failure_count_reduction": 1,
            "reference_yaw_only_action_count": 9,
            "candidate_yaw_only_action_count": 5,
        },
        "failure_taxonomy": {
            "pair_count": 2,
            "reference_startup_failure_count": 0,
            "candidate_startup_failure_count": 0,
            "reference_policy_stop_latch_count": 2,
            "candidate_policy_stop_latch_count": 0,
            "reference_maximum_consecutive_stationary_steps": 50,
            "candidate_maximum_consecutive_stationary_steps": 15,
        },
        "paired_episodes": pairs,
        "episode_dynamics": dynamics,
    }
    del report_path
    return report, analysis


def _attach_policy_bindings(report: dict[str, Any], analysis: dict[str, Any]) -> None:
    reference_manifest = "1" * 64
    candidate_manifest = "2" * 64
    reference_model = "3" * 64
    candidate_model = "4" * 64
    config_sha = "5" * 64
    factor = {
        "kind": "active_navigation_model_artifact_sha256",
        "model_id": "grid_v1",
        "config_sha256": config_sha,
        "reference_model_artifact_sha256": reference_model,
        "candidate_model_artifact_sha256": candidate_model,
        "all_other_runtime_and_policy_boundary_fields_equal": True,
    }
    policy_pair = report["policy_pair"]
    policy_pair.update(
        {
            "reference_manifest_sha256": reference_manifest,
            "candidate_manifest_sha256": candidate_manifest,
            "candidate_experiment_id": "synthetic-v10-candidate",
            "candidate_freeze": {
                "path": "/frozen/synthetic-v10-freeze.json",
                "sha256": "9" * 64,
                "training_only": True,
                "promotion_evidence": False,
                "development_execution_authorized": False,
                "holdout_execution_authorized": False,
                "deployment_enabled": False,
            },
        }
    )
    arm_values = {
        "reference": (V8_REFERENCE_PACKAGE_SHA256, reference_manifest, reference_model),
        "candidate": (CANDIDATE_SHA256, candidate_manifest, candidate_model),
    }
    isolated_pair: dict[str, Any] = {}
    for arm, (package, manifest, model) in arm_values.items():
        isolated_pair[arm] = {
            "package_sha256": package,
            "manifest_sha256": manifest,
        }
        policy_id = "synthetic-v8-reference" if arm == "reference" else "synthetic-v10-candidate"
        report_arm = "baseline" if arm == "reference" else "candidate"
        report["paired_report"][report_arm]["policy"] = {
            "policy_id": policy_id,
            "model_id": "grid_v1",
            "execution_isolation": {
                "package_sha256": package,
                "manifest_sha256": manifest,
            },
            "provenance": {
                "implementation": {
                    "id": f"bundle:{package}/evals/external/parcel_barn_adapter.py",
                    "sha256": "6" * 64,
                },
                "config": {
                    "id": f"bundle:{package}/configs/navigation/experiments/barn_grid_v1.yaml",
                    "sha256": config_sha,
                },
                "model_artifact": {
                    "id": f"bundle:{package}/configs/navigation/models/grid.yaml",
                    "sha256": model,
                },
                "policy_source_tree": {
                    "id": f"bundle:{package}/src/parcel_robot",
                    "sha256": "7" * 64,
                },
            },
        }
    isolated_pair["allowed_planner_profile_factor"] = factor
    isolated_pair["planner_profile_authorization"] = {
        "kind": "isolated_planner_profile_artifact_delta_v1",
        "reference_package_sha256": V8_REFERENCE_PACKAGE_SHA256,
        "reference_manifest_sha256": reference_manifest,
        "candidate_package_sha256": CANDIDATE_SHA256,
        "candidate_manifest_sha256": candidate_manifest,
        "reference_model_artifact_sha256": reference_model,
        "candidate_model_artifact_sha256": candidate_model,
        "navigation_config_sha256": config_sha,
        "model_id": "grid_v1",
        "reference_policy_id": "synthetic-v8-reference",
        "candidate_policy_id": "synthetic-v10-candidate",
        "strict_default_validation_preserved": True,
        "exact_profile_validator_required": True,
    }
    policy_pair["isolated_pair"] = isolated_pair
    analysis["policy_bindings"] = validate_training_report_policy_bindings(report)


def _write_documents(
    tmp_path: Path,
    report: dict[str, Any],
    analysis: dict[str, Any],
) -> tuple[Path, str, Path, str]:
    report_path = tmp_path / "run" / "report.json"
    analysis_path = tmp_path / "run" / "analysis" / "label-independent-liveness-v1.json"
    _write_read_only_json(report_path, report)
    analysis["source_report"] = {
        "path": str(report_path.resolve()),
        "sha256": _sha256(report_path),
        "size_bytes": report_path.stat().st_size,
        "run_id": report["run_id"],
        "evaluation_kind": TRAINING_EVALUATION_KIND,
    }
    _write_read_only_json(analysis_path, analysis)
    return report_path, _sha256(report_path), analysis_path, _sha256(analysis_path)


def _write_fixtures(tmp_path: Path) -> tuple[Path, str, Path, str]:
    report_path = tmp_path / "run" / "report.json"
    return _write_documents(tmp_path, *_documents(report_path))


def _gate() -> dict[str, Any]:
    return {
        "gate_id": "synthetic-v9-training-gate",
        "candidate_package_sha256": CANDIDATE_SHA256,
        "accepted_for_next_training_stage_only_if_all_conditions_pass": True,
        "screening_can_never_authorize_development_holdout_or_deployment": True,
        "training_only": True,
        "screen_world_ids": [5000, 5001],
        "minimum_success_count": 1,
        "maximum_candidate_collisions": 0,
        "maximum_candidate_startup_failure_count": 0,
        "maximum_candidate_policy_stop_latch_count": 0,
        "maximum_candidate_reverse_action_count": 0,
        "maximum_candidate_observed_return_certificate_violations": 0,
        "maximum_controller_p99_latency_ms": 25.0,
        "maximum_controller_p99_latency_ratio": 1.1,
        "minimum_candidate_signed_body_clearance_m": 0.5,
        "minimum_label_independent_liveness_failure_count_reduction": 1,
        "minimum_mean_maximum_goal_progress_m_exclusive": 2.0,
        "minimum_candidate_mean_goal_progress_efficiency": 0.8,
        "maximum_candidate_mean_final_distance_to_goal_m_exclusive": 8.0,
        "maximum_yaw_only_action_count": 5,
        "required_per_world_maximum_stationary_steps": {"5000": 10, "5001": 15},
        "required_per_world_maximum_goal_progress_m_exclusive": {
            "5000": 2.9,
            "5001": 2.4,
        },
        "required_per_world_minimum_goal_progress_efficiency": {
            "5000": 1.2,
            "5001": 0.8,
        },
        "required_per_world_maximum_final_distance_to_goal_m_exclusive": {
            "5000": 7.1,
            "5001": 7.6,
        },
        "required_per_world_maximum_traveled_distance_m": {
            "5000": 2.5,
            "5001": 3.0,
        },
    }


def _rewrite(path: Path, document: dict[str, Any]) -> str:
    path.chmod(0o644)
    _write_read_only_json(path, document)
    return _sha256(path)


def test_gate_rederives_all_metrics_and_ignores_policy_notes(tmp_path: Path) -> None:
    report, report_sha, analysis, analysis_sha = _write_fixtures(tmp_path)

    result = evaluate_training_scratch_gate(
        report,
        analysis,
        expected_report_sha256=report_sha,
        expected_analysis_sha256=analysis_sha,
        gate=_gate(),
    )

    assert result["gate_passed"] is True
    assert result["failed_check_ids"] == []
    assert result["check_count"] == len(result["checks"]) == 24
    assert result["metrics"] == pytest.approx(
        {
            "pair_count": 2,
            "candidate_success_count": 1,
            "candidate_collision_count": 0,
            "candidate_startup_failure_count": 0,
            "candidate_policy_stop_latch_count": 0,
            "reference_controller_p99_ms": 20.0,
            "candidate_controller_p99_ms": 21.0,
            "candidate_to_reference_controller_p99_ratio": 1.05,
            "candidate_minimum_signed_clearance_m": 0.55,
            "candidate_observed_return_certificate_violation_count": 0,
            "candidate_mean_maximum_goal_progress_m": 2.75,
            "candidate_mean_final_distance_to_goal_m": 7.25,
            "candidate_mean_goal_progress_efficiency": (1.2 + 2.5 / 3.0) / 2.0,
            "candidate_mean_traveled_distance_m": 2.75,
            "candidate_yaw_only_action_count": 5,
            "candidate_reverse_action_count": 0,
            "label_independent_liveness_failure_count_reduction": 1,
        }
    )
    assert result["evidence_contract"]["policy_notes_read_or_used"] is False
    assert result["evidence_contract"]["candidate_package_identity_pinned_by_gate"] is True
    assert result["evidence_contract"]["lateral_action_channel_absent_from_v8_evidence_schema"]
    assert result["claims"]["accepted_for_next_training_stage"] is True
    assert result["claims"]["development_authorized"] is False


def test_valid_evidence_with_failed_threshold_returns_every_check(tmp_path: Path) -> None:
    report, report_sha, analysis, analysis_sha = _write_fixtures(tmp_path)
    gate = _gate()
    gate["minimum_success_count"] = 2

    result = evaluate_training_scratch_gate(
        report,
        analysis,
        expected_report_sha256=report_sha,
        expected_analysis_sha256=analysis_sha,
        gate=gate,
    )

    assert result["gate_passed"] is False
    assert result["failed_check_ids"] == ["minimum_success_count"]
    assert result["check_count"] == 24
    assert sum(not item["passed"] for item in result["checks"]) == 1
    assert result["claims"]["accepted_for_next_training_stage"] is False


def test_gate_rejects_report_mutation_against_explicit_hash(tmp_path: Path) -> None:
    report, report_sha, analysis, analysis_sha = _write_fixtures(tmp_path)
    document = json.loads(report.read_text(encoding="utf-8"))
    document["paired_report"]["candidate"]["episodes"][0]["success"] = False
    _rewrite(report, document)

    with pytest.raises(V9ScratchGateError, match="report SHA-256 differs"):
        evaluate_training_scratch_gate(
            report,
            analysis,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=_gate(),
        )


def test_gate_rejects_mutable_or_aliased_input(tmp_path: Path) -> None:
    report, report_sha, analysis, analysis_sha = _write_fixtures(tmp_path)
    analysis.chmod(0o644)
    with pytest.raises(V9ScratchGateError, match="unalias.*read-only regular file"):
        evaluate_training_scratch_gate(
            report,
            analysis,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=_gate(),
        )
    analysis.chmod(0o444)
    alias = tmp_path / "analysis-hardlink.json"
    os.link(analysis, alias)
    with pytest.raises(V9ScratchGateError, match="unalias.*read-only regular file"):
        evaluate_training_scratch_gate(
            report,
            analysis,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=_gate(),
        )


def test_gate_rejects_report_analysis_or_candidate_identity_mismatch(tmp_path: Path) -> None:
    report, report_sha, analysis, _analysis_sha = _write_fixtures(tmp_path)
    document = json.loads(analysis.read_text(encoding="utf-8"))
    document["source_report"]["run_id"] = "different-run"
    analysis_sha = _rewrite(analysis, document)
    with pytest.raises(V9ScratchGateError, match="source-report identity differs"):
        evaluate_training_scratch_gate(
            report,
            analysis,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=_gate(),
        )

    report, report_sha, analysis, analysis_sha = _write_fixtures(tmp_path / "other")
    gate = _gate()
    gate["candidate_package_sha256"] = "7" * 64
    with pytest.raises(V9ScratchGateError, match="candidate package identity differs"):
        evaluate_training_scratch_gate(
            report,
            analysis,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=gate,
        )


def test_gate_rejects_aggregate_score_laundering_and_unknown_gate_keys(tmp_path: Path) -> None:
    report, report_sha, analysis, _analysis_sha = _write_fixtures(tmp_path)
    document = json.loads(analysis.read_text(encoding="utf-8"))
    document["summary"]["candidate_yaw_only_action_count"] = 0
    analysis_sha = _rewrite(analysis, document)
    with pytest.raises(V9ScratchGateError, match="yaw_only.*disagrees"):
        evaluate_training_scratch_gate(
            report,
            analysis,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=_gate(),
        )

    report, report_sha, analysis, analysis_sha = _write_fixtures(tmp_path / "other")
    gate = _gate()
    gate["minimum_imaginary_policy_note_score"] = 999
    with pytest.raises(V9ScratchGateError, match="unsupported keys"):
        evaluate_training_scratch_gate(
            report,
            analysis,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=gate,
        )


def test_gate_rejects_nontraining_world_even_when_hash_pinned(tmp_path: Path) -> None:
    report, _report_sha, analysis, _analysis_sha = _write_fixtures(tmp_path)
    report_document = json.loads(report.read_text(encoding="utf-8"))
    for arm in ("baseline", "candidate"):
        report_document["paired_report"][arm]["episodes"][0]["world_index"] = 5100
    report_sha = _rewrite(report, report_document)
    analysis_document = json.loads(analysis.read_text(encoding="utf-8"))
    analysis_document["source_report"].update(
        {"sha256": report_sha, "size_bytes": report.stat().st_size}
    )
    analysis_sha = _rewrite(analysis, analysis_document)

    with pytest.raises(V9ScratchGateError, match="only V9 training worlds"):
        evaluate_training_scratch_gate(
            report,
            analysis,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=_gate(),
        )


def test_gate_verifies_available_executed_planner_profile_bindings(tmp_path: Path) -> None:
    report_path = tmp_path / "run" / "report.json"
    report, analysis = _documents(report_path)
    _attach_policy_bindings(report, analysis)
    report_path, report_sha, analysis_path, analysis_sha = _write_documents(
        tmp_path,
        report,
        analysis,
    )

    result = evaluate_training_scratch_gate(
        report_path,
        analysis_path,
        expected_report_sha256=report_sha,
        expected_analysis_sha256=analysis_sha,
        gate=_gate(),
    )

    assert result["policy_bindings"]["planner_profile_factor_available"] is True
    assert result["policy_bindings"]["planner_profile_authorization_available"] is True
    assert result["evidence_contract"]["analysis_policy_bindings_match_report"] is True


def test_gate_rejects_executed_profile_or_authorization_identity_mismatch(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "run" / "report.json"
    report, analysis = _documents(report_path)
    _attach_policy_bindings(report, analysis)
    report["paired_report"]["candidate"]["policy"]["provenance"]["model_artifact"][
        "sha256"
    ] = "a" * 64
    report_path, report_sha, analysis_path, analysis_sha = _write_documents(
        tmp_path,
        report,
        analysis,
    )

    with pytest.raises(V9ScratchGateError, match="policy binding is invalid"):
        evaluate_training_scratch_gate(
            report_path,
            analysis_path,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=_gate(),
        )


def test_gate_rejects_nondefault_liveness_config(tmp_path: Path) -> None:
    report, report_sha, analysis, _analysis_sha = _write_fixtures(tmp_path)
    document = json.loads(analysis.read_text(encoding="utf-8"))
    document["liveness_config"]["long_stall_steps"] = 500
    analysis_sha = _rewrite(analysis, document)

    with pytest.raises(V9ScratchGateError, match="exact frozen default"):
        evaluate_training_scratch_gate(
            report,
            analysis,
            expected_report_sha256=report_sha,
            expected_analysis_sha256=analysis_sha,
            gate=_gate(),
        )
