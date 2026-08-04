from __future__ import annotations

import copy
import hashlib
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from evals.external.barn_native import BARN_EVALUATOR_COMMIT, BarnAction, BarnObservation
from evals.external.barn_policy_specs import BarnPolicySpec
from evals.external.barn_sensor_faithful import (
    BARN_SENSOR_FAITHFUL_EVALUATION_KIND,
    BARN_SOURCE,
    CalibratedBarnConfig,
    run_sensor_faithful_paired_comparison,
)
from evals.external.barn_v8_action_evidence import (
    V8_ACTION_EVIDENCE_FORMAT_ID,
    V8ActionEvidenceBuilder,
    read_v8_action_evidence,
)
from evals.external.barn_v8_promotion_gate import (
    V8DevelopmentGateContract,
    V8PromotionGateError,
    build_v8_evidence_index_from_report,
    canonical_json_sha256,
    evaluate_v8_promotion_gate,
    extract_v8_harness_evidence_entries,
    v8_evidence_relative_path,
)
from evals.external.generate_all_ray_shield_v8_corpus import (
    CORPUS_ID,
    DEVELOPMENT_WORLD_IDS,
    FROZEN_CALIBRATED_CONFIG,
    PAIRED_ARM_ORDER_SCHEDULE,
    PAIRED_ARM_ORDER_SCHEDULE_SHA256,
    SUITE_SEED,
)

RAY_COUNT = 720
ANGLE_MIN = -math.pi
ANGLE_INCREMENT = 2.0 * math.pi / (RAY_COUNT - 1)


class _ImmediateStopPolicy:
    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        del start_xy, heading_rad, goal_xy

    def act(self, observation: BarnObservation) -> BarnAction:
        del observation
        return BarnAction(0.0, 0.0, stop=True, note="synthetic_schema_stop")

    def latency_samples_ms(self) -> dict[str, tuple[float, ...]]:
        return {"controller_step": (1.0,)}

    def close(self) -> None:
        return None


def _stop_spec(*, experimental: bool) -> BarnPolicySpec:
    role = "candidate" if experimental else "reference"
    return BarnPolicySpec(
        policy_id=f"v8-schema-{role}",
        description=f"V8 live schema {role}",
        agent_id="schema-test-agent",
        adapter_id="schema-test-adapter",
        model_id="none",
        factory=lambda _seed: _ImmediateStopPolicy(),
        experimental=experimental,
    )


def _evidence_metadata(write_result: Any, path: Path) -> dict[str, Any]:
    verified = read_v8_action_evidence(
        path,
        expected_artifact_sha256=write_result.identity.artifact_sha256,
    )
    violating = sum(
        not record.certificate.observed_return_boundary_satisfied for record in verified.records
    )
    return {
        "identity": write_result.identity.as_dict(),
        "write_overhead": write_result.overhead.as_dict(),
        "read_verification_overhead": verified.overhead.as_dict(),
        "action_count_matches_published_trace": True,
        "policy_observation_hashes_match_published_trace": True,
        "all_records_format_read_and_recertified": True,
        "observed_return_boundary_satisfied_action_count": len(verified.records) - violating,
        "observed_return_boundary_violating_action_count": violating,
        "perception_incomplete_action_count": sum(
            not record.certificate.perception_complete for record in verified.records
        ),
        "evaluator_evidence_overhead_included_in_controller_latency": False,
    }


def _episode(
    *,
    world_id: int,
    success: bool,
    navigation_metric: float,
    vx: float,
    stop: bool,
    observation_sha256: str,
    controller_latency_ms: float,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    status = "succeeded" if success else "timeout"
    return {
        "world_index": world_id,
        "trial": 0,
        "episode_seed": SUITE_SEED + world_id * 1_009,
        "success": success,
        "collided": False,
        "timed_out": not success,
        "startup_timed_out": False,
        "status": status,
        "steps": 1,
        "navigation_metric": navigation_metric,
        "evaluator_diagnostics": {"minimum_signed_obstacle_clearance_m": 0.5},
        "sensor_diagnostics": {
            "frame_count": 1,
            "policy_observation_steps": [0],
            "policy_observation_sha256": [observation_sha256],
            "published_action_steps": [0],
            "published_action_values": [[0, vx, 0.0, stop]],
        },
        "shield_stall_diagnostics": {"issued_policy_command_steps": 1},
        "evaluator_controller_step_latency_samples_ms": [controller_latency_ms],
        "action_evidence": evidence,
    }


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(episodes)
    samples = sorted(
        float(sample)
        for episode in episodes
        for sample in episode["evaluator_controller_step_latency_samples_ms"]
    )

    def nearest_rank(quantile: float) -> float:
        return samples[math.ceil(quantile * len(samples)) - 1]

    return {
        "success_rate": sum(bool(item["success"]) for item in episodes) / count,
        "collision_rate": sum(bool(item["collided"]) for item in episodes) / count,
        "timeout_rate": sum(item["status"] == "timeout" for item in episodes) / count,
        "navigation_metric": sum(float(item["navigation_metric"]) for item in episodes) / count,
        "controller_step_count": float(len(samples)),
        "controller_step_mean_ms": math.fsum(samples) / len(samples),
        "controller_step_p50_ms": nearest_rank(0.50),
        "controller_step_p95_ms": nearest_rank(0.95),
        "controller_step_p99_ms": nearest_rank(0.99),
        "controller_step_max_ms": max(samples),
        "evaluator_diagnostics": {
            "minimum_signed_obstacle_clearance_m": min(
                item["evaluator_diagnostics"]["minimum_signed_obstacle_clearance_m"]
                for item in episodes
            )
        },
    }


def _refresh_arm(report: dict[str, Any], key: str) -> None:
    report[key]["aggregate"] = _aggregate(report[key]["episodes"])


def _passing_fixture(
    tmp_path: Path,
    *,
    mode_affected: bool = True,
    global_nearest_case: bool = True,
    unavailable_translation: bool = False,
    candidate_violation: bool = False,
    divergent_observation_mismatch: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], V8DevelopmentGateContract, Path]:
    root = tmp_path / "evidence"
    root.mkdir(parents=True)
    reference_policy = {
        "policy_id": "historical-reference",
        "execution_device": "cpu",
        "execution_isolation": {"package_sha256": "1" * 64, "worker_sha256": "2" * 64},
    }
    candidate_policy = {
        "policy_id": "v8-candidate",
        "execution_device": "cpu",
        "execution_isolation": {"package_sha256": "3" * 64, "worker_sha256": "2" * 64},
    }
    contract = V8DevelopmentGateContract(
        run_id="barn-v8-synthetic-pass",
        corpus_id=CORPUS_ID,
        corpus_sha256="a" * 64,
        manifest_sha256="b" * 64,
        native_config_sha256=canonical_json_sha256(FROZEN_CALIBRATED_CONFIG),
        reference_policy_metadata_sha256=canonical_json_sha256(reference_policy),
        candidate_policy_metadata_sha256=canonical_json_sha256(candidate_policy),
        one_factor_delta_sha256="c" * 64,
        isolated_runtime_pair_sha256="d" * 64,
        arm_order_schedule_sha256=PAIRED_ARM_ORDER_SCHEDULE_SHA256,
    )
    reference_episodes: list[dict[str, Any]] = []
    candidate_episodes: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for offset, (world_id, order) in enumerate(
        zip(DEVELOPMENT_WORLD_IDS, PAIRED_ARM_ORDER_SCHEDULE, strict=True)
    ):
        reference_success = offset >= 10
        candidate_success = offset >= 7
        reference_vx = 0.3 if offset == 1 and candidate_violation else 0.2
        candidate_vx = 0.3 if offset == 0 and mode_affected else reference_vx
        candidate_stop = False
        if offset == 0 and unavailable_translation:
            common_scan = (math.nan,) * RAY_COUNT
            candidate_vx = 0.1
        elif offset == 0 and global_nearest_case:
            scan = [math.inf] * RAY_COUNT
            scan[0] = 0.85
            scan[360] = 1.0
            common_scan = tuple(scan)
        elif offset == 1 and candidate_violation:
            scan = [math.inf] * RAY_COUNT
            scan[360] = 0.81
            common_scan = tuple(scan)
            candidate_vx = 0.3
        else:
            common_scan = (math.inf,) * RAY_COUNT
        episode_by_arm: dict[str, dict[str, Any]] = {}
        for arm, vx, success, metric in (
            ("reference", reference_vx, reference_success, 0.5 if reference_success else 0.0),
            ("candidate", candidate_vx, candidate_success, 0.5 if candidate_success else 0.0),
        ):
            execution_order = int(
                (order == "reference_then_candidate" and arm == "candidate")
                or (order == "candidate_then_reference" and arm == "reference")
            )
            builder = V8ActionEvidenceBuilder()
            arm_scan = common_scan
            observation_sha256 = hashlib.sha256(
                f"v8-synthetic-policy-observation-{world_id}".encode()
            ).hexdigest()
            if offset == 0 and arm == "candidate" and divergent_observation_mismatch:
                observation_sha256 = hashlib.sha256(
                    f"v8-synthetic-policy-observation-{world_id}-changed-pose".encode()
                ).hexdigest()
            builder.append(
                step_index=0,
                execution_order=execution_order,
                arm=arm,
                world_id=world_id,
                trial_id=0,
                seed=SUITE_SEED + world_id * 1_009,
                issued_by_policy=True,
                observation_reused=False,
                normalized_scan_m=arm_scan,
                angle_min_rad=ANGLE_MIN,
                angle_increment_rad=ANGLE_INCREMENT,
                published_vx_mps=vx,
                published_vy_mps=0.0,
                published_yaw_rate_rps=0.0,
                published_stop=candidate_stop if arm == "candidate" else False,
                note=f"{arm}-action",
                policy_observation_sha256=observation_sha256,
            )
            path = root / v8_evidence_relative_path(arm, world_id, 0)
            written = builder.write_exclusive(path)
            metadata = _evidence_metadata(written, path)
            episode_by_arm[arm] = _episode(
                world_id=world_id,
                success=success,
                navigation_metric=metric,
                vx=vx,
                stop=candidate_stop if arm == "candidate" else False,
                observation_sha256=observation_sha256,
                controller_latency_ms=50.0 if arm == "reference" else 55.0,
                evidence=metadata,
            )
            artifacts.append(metadata["identity"])
        reference_episodes.append(episode_by_arm["reference"])
        candidate_episodes.append(episode_by_arm["candidate"])

    schedule = [
        {
            "world_index": world_id,
            "trial": 0,
            "episode_seed": SUITE_SEED + world_id * 1_009,
            "arm_order": order,
        }
        for world_id, order in zip(DEVELOPMENT_WORLD_IDS, PAIRED_ARM_ORDER_SCHEDULE, strict=True)
    ]
    paired = []
    for index, world_id in enumerate(DEVELOPMENT_WORLD_IDS):
        left = reference_episodes[index]
        right = candidate_episodes[index]
        is_affected = index == 0 and mode_affected and not divergent_observation_mismatch
        paired.append(
            {
                "world_index": world_id,
                "trial": 0,
                "baseline_status": left["status"],
                "candidate_status": right["status"],
                "success_delta": int(right["success"]) - int(left["success"]),
                "mode_affected": is_affected,
                "first_published_action_divergence_step": 0 if is_affected else None,
                "first_divergence_on_identical_policy_observation": is_affected,
            }
        )
    report = {
        "schema_version": 1,
        "evaluation_kind": (
            f"{BARN_SENSOR_FAITHFUL_EVALUATION_KIND}-counterbalanced-paired-comparison"
        ),
        "official_gazebo_score": False,
        "target_status": {
            "official_gate_pass": False,
            "note": "synthetic non-official gate fixture",
        },
        "v8_preflight": {
            "corpus_sha256": contract.corpus_sha256,
            "exact_one_factor_policy_delta": True,
            "isolated_runtime_parity": True,
            "isolated_runtime_pair_sha256": contract.isolated_runtime_pair_sha256,
            "manifest_sha256": contract.manifest_sha256,
            "one_factor_delta_sha256": contract.one_factor_delta_sha256,
        },
        "baseline": {
            "schema_version": 1,
            "evaluation_kind": BARN_SENSOR_FAITHFUL_EVALUATION_KIND,
            "official_gazebo_score": False,
            "suite_seed": SUITE_SEED,
            "native_config": copy.deepcopy(FROZEN_CALIBRATED_CONFIG),
            "benchmark": {
                "id": BARN_SENSOR_FAITHFUL_EVALUATION_KIND,
                "source": BARN_SOURCE,
                "source_commit": BARN_EVALUATOR_COMMIT,
                "official_gazebo_score": False,
                "asset_scope": "generated-public-style-development",
                "asset_manifest_sha256": contract.manifest_sha256,
                "public_world_indices": list(DEVELOPMENT_WORLD_IDS),
            },
            "execution": {
                "evaluator_device": "cpu",
                "lidar_raycast_device": "cpu",
                "kinematics_device": "cpu",
                "policy_declared_device": "cpu",
                "episode_workers_requested": 4,
                "episode_workers_effective": 4,
                "process_start_method": "spawn",
                "durable_report_writer": "caller_or_parent_process_only",
                "paired_episode_execution": True,
                "arms_concurrent_within_pair": False,
                "action_evidence": {
                    "enabled": True,
                    "immutable_artifact_count": 30,
                    "evaluator_overhead_included_in_controller_latency": False,
                },
            },
            "policy": reference_policy,
            "episodes": reference_episodes,
            "aggregate": _aggregate(reference_episodes),
            "top_decile_target": {"official_protocol": False, "pass": False},
        },
        "candidate": {
            "schema_version": 1,
            "evaluation_kind": BARN_SENSOR_FAITHFUL_EVALUATION_KIND,
            "official_gazebo_score": False,
            "suite_seed": SUITE_SEED,
            "native_config": copy.deepcopy(FROZEN_CALIBRATED_CONFIG),
            "benchmark": {
                "id": BARN_SENSOR_FAITHFUL_EVALUATION_KIND,
                "source": BARN_SOURCE,
                "source_commit": BARN_EVALUATOR_COMMIT,
                "official_gazebo_score": False,
                "asset_scope": "generated-public-style-development",
                "asset_manifest_sha256": contract.manifest_sha256,
                "public_world_indices": list(DEVELOPMENT_WORLD_IDS),
            },
            "execution": {
                "evaluator_device": "cpu",
                "lidar_raycast_device": "cpu",
                "kinematics_device": "cpu",
                "policy_declared_device": "cpu",
                "episode_workers_requested": 4,
                "episode_workers_effective": 4,
                "process_start_method": "spawn",
                "durable_report_writer": "caller_or_parent_process_only",
                "paired_episode_execution": True,
                "arms_concurrent_within_pair": False,
                "action_evidence": {
                    "enabled": True,
                    "immutable_artifact_count": 30,
                    "evaluator_overhead_included_in_controller_latency": False,
                },
            },
            "policy": candidate_policy,
            "episodes": candidate_episodes,
            "aggregate": _aggregate(candidate_episodes),
            "top_decile_target": {"official_protocol": False, "pass": False},
        },
        "comparison": {
            "same_worlds_trials_config_and_seeds": True,
            "paired_episode_count": 30,
            "mode_affected_episode_count": int(
                mode_affected and not divergent_observation_mismatch
            ),
            "paired_episodes": paired,
            "paired_execution": {
                "pair_count": 30,
                "arms_never_concurrent_within_pair": True,
                "same_world_config_trial_and_seed_within_pair": True,
                "order_counts": {
                    "reference_then_candidate": 15,
                    "candidate_then_reference": 15,
                },
                "schedule": schedule,
            },
            "action_evidence": {
                "enabled": True,
                "format_id": V8_ACTION_EVIDENCE_FORMAT_ID,
                "immutable_artifact_count": 60,
                "expected_immutable_artifact_count": 60,
                "all_action_counts_match_published_traces": True,
                "all_policy_observation_hashes_match_published_traces": True,
                "all_records_format_read_and_recertified": True,
                "evaluator_overhead_included_in_controller_latency": False,
                "artifacts": artifacts,
            },
        },
    }
    index = build_v8_evidence_index_from_report(report, contract=contract, evidence_root=root)
    return report, index, contract, root


def test_passing_synthetic_run_satisfies_every_predeclared_gate(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)

    gates, diagnostics = evaluate_v8_promotion_gate(
        report,
        evidence_index=index,
        evidence_root=root,
        contract=contract,
    )

    assert all(gates.values())
    assert diagnostics["all_conditions_passed"] is True
    assert diagnostics["verified_artifact_count"] == 60
    assert diagnostics["verified_action_count"] == 60
    assert diagnostics["success_gains"] == 3
    assert diagnostics["success_regressions"] == 0
    assert diagnostics["global_nearest_not_limiting_action_count"] >= 1
    assert diagnostics["mode_affected_identical_observation_pair_count"] == 1
    assert diagnostics["evidence_overhead_included_in_controller_latency"] is False
    assert diagnostics["official_score"] is False
    assert diagnostics["leaderboard_claim"] is False


@pytest.mark.parametrize("failure", ["missing", "mutable", "extra", "duplicate_index"])
def test_evidence_inventory_fails_closed(tmp_path: Path, failure: str) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    target = root / v8_evidence_relative_path("candidate", DEVELOPMENT_WORLD_IDS[0], 0)
    if failure == "missing":
        target.rename(tmp_path / "removed.v8e")
    elif failure == "mutable":
        target.chmod(0o644)
    elif failure == "extra":
        (root / "unindexed.v8e").write_bytes(b"not evidence")
    else:
        index["entries"][1] = copy.deepcopy(index["entries"][0])

    with pytest.raises(V8PromotionGateError):
        evaluate_v8_promotion_gate(
            report,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )


def test_evidence_root_rejects_a_lexical_symlink_ancestor(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    alias_parent = tmp_path / "evidence-parent-alias"
    alias_parent.symlink_to(root.parent, target_is_directory=True)

    with pytest.raises(V8PromotionGateError, match="symbolic-link component"):
        evaluate_v8_promotion_gate(
            report,
            evidence_index=index,
            evidence_root=alias_parent / root.name,
            contract=contract,
        )


def test_evidence_file_with_a_foreign_hardlink_is_rejected(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    target = root / v8_evidence_relative_path("candidate", DEVELOPMENT_WORLD_IDS[0], 0)
    os.link(target, tmp_path / "foreign-hardlink.v8e")

    with pytest.raises(V8PromotionGateError, match="single-link"):
        evaluate_v8_promotion_gate(
            report,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )


def test_tampered_evidence_and_action_count_mismatch_fail_closed(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    target = root / v8_evidence_relative_path("candidate", DEVELOPMENT_WORLD_IDS[0], 0)
    target.chmod(0o600)
    payload = bytearray(target.read_bytes())
    payload[-1] ^= 1
    target.write_bytes(payload)
    target.chmod(0o444)

    with pytest.raises(V8PromotionGateError, match="failed verification"):
        evaluate_v8_promotion_gate(
            report,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )

    report, index, contract, root = _passing_fixture(tmp_path / "second")
    report["candidate"]["episodes"][0]["steps"] = 2
    with pytest.raises(V8PromotionGateError, match="action count"):
        evaluate_v8_promotion_gate(
            report,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )


def test_identity_runtime_and_schedule_mismatches_fail_before_scoring(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    report["candidate"]["policy"]["execution_isolation"]["worker_sha256"] = "9" * 64
    with pytest.raises(V8PromotionGateError, match="policy/runtime identity"):
        evaluate_v8_promotion_gate(
            report,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )

    report, index, contract, root = _passing_fixture(tmp_path / "schedule")
    report["comparison"]["paired_execution"]["schedule"][0]["arm_order"] = (
        "candidate_then_reference"
    )
    with pytest.raises(V8PromotionGateError, match="schedule"):
        evaluate_v8_promotion_gate(
            report,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )


def test_all_promotion_critical_report_identities_are_strict(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    mutations = (
        ("top schema", lambda value: value.__setitem__("schema_version", True)),
        ("top kind", lambda value: value.__setitem__("evaluation_kind", "other")),
        (
            "arm schema",
            lambda value: value["baseline"].__setitem__("schema_version", 2),
        ),
        (
            "arm kind",
            lambda value: value["candidate"].__setitem__("evaluation_kind", "other"),
        ),
        (
            "benchmark source",
            lambda value: value["candidate"]["benchmark"].__setitem__("source_commit", "0" * 40),
        ),
        (
            "benchmark scope",
            lambda value: value["baseline"]["benchmark"].__setitem__(
                "asset_scope", "public-barn-static"
            ),
        ),
        (
            "execution device",
            lambda value: value["candidate"]["execution"].__setitem__(
                "lidar_raycast_device", "cuda"
            ),
        ),
        (
            "arm official target",
            lambda value: value["candidate"]["top_decile_target"].__setitem__("pass", True),
        ),
        (
            "top official target",
            lambda value: value["target_status"].__setitem__("official_gate_pass", True),
        ),
        (
            "comparison artifact identity",
            lambda value: value["comparison"]["action_evidence"]["artifacts"][0].__setitem__(
                "artifact_sha256", "0" * 64
            ),
        ),
    )
    for _label, mutate in mutations:
        changed = copy.deepcopy(report)
        mutate(changed)
        with pytest.raises(V8PromotionGateError):
            evaluate_v8_promotion_gate(
                changed,
                evidence_index=index,
                evidence_root=root,
                contract=contract,
            )


def test_certificate_and_no_perception_failures_are_gate_failures(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(
        tmp_path / "violation", candidate_violation=True
    )
    gates, diagnostics = evaluate_v8_promotion_gate(
        report, evidence_index=index, evidence_root=root, contract=contract
    )
    assert gates["zero_candidate_observed_return_certificate_violations"] is False
    assert diagnostics["candidate_observed_return_violation_count"] > 0
    assert diagnostics["all_conditions_passed"] is False

    report, index, contract, root = _passing_fixture(
        tmp_path / "unavailable", unavailable_translation=True
    )
    gates, diagnostics = evaluate_v8_promotion_gate(
        report, evidence_index=index, evidence_root=root, contract=contract
    )
    assert gates["zero_candidate_translation_when_perception_unavailable"] is False
    assert diagnostics["candidate_perception_unavailable_translation_count"] == 1


def test_efficacy_safety_and_latency_thresholds_are_independently_enforced(
    tmp_path: Path,
) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    episode = report["candidate"]["episodes"][0]
    episode["success"] = False
    episode["collided"] = True
    episode["timed_out"] = False
    episode["status"] = "collided"
    report["comparison"]["paired_episodes"][0]["candidate_status"] = "collided"
    report["comparison"]["paired_episodes"][0]["success_delta"] = 0
    episode["evaluator_controller_step_latency_samples_ms"] = [101.0]
    episode["evaluator_diagnostics"]["minimum_signed_obstacle_clearance_m"] = 0.474
    _refresh_arm(report, "candidate")

    gates, diagnostics = evaluate_v8_promotion_gate(
        report, evidence_index=index, evidence_root=root, contract=contract
    )
    assert gates["zero_candidate_collisions"] is False
    assert gates["candidate_minimum_signed_body_clearance"] is False
    assert gates["candidate_controller_p99_latency"] is False
    assert gates["candidate_to_reference_controller_p99_ratio"] is False
    assert diagnostics["all_conditions_passed"] is False


def test_timeout_increase_and_paired_success_regression_are_rejected(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    for index_value, episode in enumerate(report["candidate"]["episodes"]):
        episode["success"] = False
        episode["status"] = "timeout"
        episode["timed_out"] = True
        episode["startup_timed_out"] = False
        episode["navigation_metric"] = 0.0
        reference_success = bool(report["baseline"]["episodes"][index_value]["success"])
        report["comparison"]["paired_episodes"][index_value]["success_delta"] = -int(
            reference_success
        )
        report["comparison"]["paired_episodes"][index_value]["candidate_status"] = "timeout"
    _refresh_arm(report, "candidate")

    gates, diagnostics = evaluate_v8_promotion_gate(
        report,
        evidence_index=index,
        evidence_root=root,
        contract=contract,
    )

    assert gates["candidate_timeout_rate_not_above_reference"] is False
    assert gates["zero_paired_success_regressions"] is False
    assert diagnostics["success_regressions"] == 20
    assert diagnostics["all_conditions_passed"] is False


def test_episode_success_collision_and_status_are_never_truthiness_coerced(
    tmp_path: Path,
) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    mutations = (
        lambda episode: episode.__setitem__("success", 1),
        lambda episode: episode.__setitem__("collided", 0),
        lambda episode: episode.__setitem__("status", "unknown"),
        lambda episode: episode.__setitem__("status", "collided"),
    )
    for mutate in mutations:
        changed = copy.deepcopy(report)
        mutate(changed["candidate"]["episodes"][0])
        with pytest.raises(V8PromotionGateError):
            evaluate_v8_promotion_gate(
                changed,
                evidence_index=index,
                evidence_root=root,
                contract=contract,
            )


def test_raw_controller_latency_samples_and_recomputed_aggregates_are_mandatory(
    tmp_path: Path,
) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)

    aggregate_tamper = copy.deepcopy(report)
    aggregate_tamper["candidate"]["aggregate"]["controller_step_mean_ms"] += 0.25
    with pytest.raises(V8PromotionGateError, match="raw controller samples"):
        evaluate_v8_promotion_gate(
            aggregate_tamper,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )

    sample_tamper = copy.deepcopy(report)
    sample_tamper["candidate"]["episodes"][0]["evaluator_controller_step_latency_samples_ms"] = [
        56.0
    ]
    with pytest.raises(V8PromotionGateError, match="raw controller samples"):
        evaluate_v8_promotion_gate(
            sample_tamper,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )

    negative_sample = copy.deepcopy(report)
    negative_sample["candidate"]["episodes"][0]["evaluator_controller_step_latency_samples_ms"] = [
        -1.0
    ]
    with pytest.raises(V8PromotionGateError, match="non-negative"):
        evaluate_v8_promotion_gate(
            negative_sample,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )

    count_tamper = copy.deepcopy(report)
    count_tamper["candidate"]["episodes"][0]["evaluator_controller_step_latency_samples_ms"] = [
        55.0,
        55.0,
    ]
    with pytest.raises(V8PromotionGateError, match="sample count"):
        evaluate_v8_promotion_gate(
            count_tamper,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )


def test_meaningful_gain_and_causal_exercise_are_required(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(
        tmp_path, mode_affected=False, global_nearest_case=False
    )
    for index_value in (7, 8):
        report["candidate"]["episodes"][index_value]["success"] = False
        report["candidate"]["episodes"][index_value]["status"] = "timeout"
        report["candidate"]["episodes"][index_value]["timed_out"] = True
        report["candidate"]["episodes"][index_value]["navigation_metric"] = 0.0
        report["comparison"]["paired_episodes"][index_value]["success_delta"] = 0
        report["comparison"]["paired_episodes"][index_value]["candidate_status"] = "timeout"
    _refresh_arm(report, "candidate")

    gates, diagnostics = evaluate_v8_promotion_gate(
        report, evidence_index=index, evidence_root=root, contract=contract
    )
    assert gates["minimum_success_gains"] is False
    assert gates["minimum_success_rate_delta"] is False
    assert gates["mode_affected_identical_first_divergence_observation"] is False
    assert gates["global_nearest_not_limiting_case_exercised"] is False
    assert diagnostics["all_conditions_passed"] is False


def test_every_first_divergence_must_share_the_exact_observation(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(
        tmp_path,
        divergent_observation_mismatch=True,
    )
    world_id = DEVELOPMENT_WORLD_IDS[0]
    reference_record = read_v8_action_evidence(
        root / v8_evidence_relative_path("reference", world_id, 0)
    ).records[0]
    candidate_record = read_v8_action_evidence(
        root / v8_evidence_relative_path("candidate", world_id, 0)
    ).records[0]
    assert (
        reference_record.normalized_scan_float64_le == candidate_record.normalized_scan_float64_le
    )
    assert reference_record.angle_min_rad == candidate_record.angle_min_rad
    assert reference_record.angle_increment_rad == candidate_record.angle_increment_rad
    assert reference_record.policy_observation_sha256 != candidate_record.policy_observation_sha256

    gates, diagnostics = evaluate_v8_promotion_gate(
        report,
        evidence_index=index,
        evidence_root=root,
        contract=contract,
    )

    assert gates["mode_affected_identical_first_divergence_observation"] is False
    assert gates["all_first_divergences_share_identical_exact_observation"] is False
    assert diagnostics["divergent_pair_count"] == 1
    assert diagnostics["invalid_first_divergence_observation_pair_count"] == 1
    assert diagnostics["all_conditions_passed"] is False


def test_reported_full_observation_hash_must_match_evaluator_evidence(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    report["candidate"]["episodes"][0]["sensor_diagnostics"]["policy_observation_sha256"][0] = (
        "f" * 64
    )

    with pytest.raises(V8PromotionGateError, match="full-observation hashes"):
        evaluate_v8_promotion_gate(
            report,
            evidence_index=index,
            evidence_root=root,
            contract=contract,
        )


def test_evidence_overhead_cannot_be_relabelled_as_controller_latency(tmp_path: Path) -> None:
    report, index, contract, root = _passing_fixture(tmp_path)
    index["entries"][0]["write_overhead"]["included_in_controller_latency"] = True
    with pytest.raises(V8PromotionGateError, match="overhead leaked"):
        evaluate_v8_promotion_gate(
            report, evidence_index=index, evidence_root=root, contract=contract
        )

    report, index, contract, root = _passing_fixture(tmp_path / "aggregate")
    report["candidate"]["aggregate"]["evidence_write_p99_ms"] = 1.0
    gates, diagnostics = evaluate_v8_promotion_gate(
        report, evidence_index=index, evidence_root=root, contract=contract
    )
    assert gates["evidence_overhead_separate_from_controller_latency"] is False
    assert diagnostics["all_conditions_passed"] is False


def test_contract_rejects_any_noncanonical_development_protocol() -> None:
    common = {
        "run_id": "bad-contract",
        "corpus_id": CORPUS_ID,
        "corpus_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "native_config_sha256": "c" * 64,
        "reference_policy_metadata_sha256": "d" * 64,
        "candidate_policy_metadata_sha256": "e" * 64,
        "one_factor_delta_sha256": "f" * 64,
        "isolated_runtime_pair_sha256": "1" * 64,
        "arm_order_schedule_sha256": PAIRED_ARM_ORDER_SCHEDULE_SHA256,
    }
    with pytest.raises(V8PromotionGateError, match="exactly four"):
        V8DevelopmentGateContract(**common, workers=3)
    with pytest.raises(V8PromotionGateError, match="one trial"):
        V8DevelopmentGateContract(**common, trials_per_world=2)
    with pytest.raises(V8PromotionGateError, match="world identities"):
        V8DevelopmentGateContract(**common, world_ids=tuple(range(4001, 4031)))


def test_live_paired_harness_tuple_schema_adapts_to_evidence_index(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    (assets / "path_files").mkdir(parents=True)
    (assets / "world_0.world").write_text(
        '<sdf version="1.6"><world name="default"/></sdf>\n',
        encoding="utf-8",
    )
    np.save(assets / "path_files" / "path_0.npy", np.asarray([[15, 0], [15, 29]]))
    evidence_root = tmp_path / "evidence"
    paths = {
        (0, 0, arm): evidence_root / v8_evidence_relative_path(arm, 0, 0)
        for arm in ("reference", "candidate")
    }

    report = run_sensor_faithful_paired_comparison(
        assets_root=assets,
        world_indices=(0,),
        reference_spec=_stop_spec(experimental=False),
        candidate_spec=_stop_spec(experimental=True),
        trials=1,
        suite_seed=SUITE_SEED,
        workers=1,
        allow_experimental=True,
        config=CalibratedBarnConfig(startup_timeout_s=0.1, timeout_s=0.1),
        arm_order_schedule=("reference_then_candidate",),
        action_evidence_paths=paths,
    )

    assert isinstance(
        report["baseline"]["episodes"][0]["sensor_diagnostics"]["published_action_steps"],
        tuple,
    )
    entries, identities = extract_v8_harness_evidence_entries(
        report,
        evidence_root=evidence_root,
    )
    assert identities == {("reference", 0, 0), ("candidate", 0, 0)}
    assert len(entries) == 2
    assert all(entry["identity"]["record_count"] == 1 for entry in entries)
    assert all(
        entry["initial_read_verification_overhead"]["included_in_controller_latency"] is False
        for entry in entries
    )
    for arm in ("baseline", "candidate"):
        episode = report[arm]["episodes"][0]
        assert episode["evaluator_controller_step_latency_samples_ms"] == (1.0,)
        assert report[arm]["aggregate"]["controller_step_count"] == 1.0
        assert report[arm]["aggregate"]["controller_step_mean_ms"] == 1.0
        assert report[arm]["aggregate"]["controller_step_p50_ms"] == 1.0
        assert report[arm]["aggregate"]["controller_step_p95_ms"] == 1.0
        assert report[arm]["aggregate"]["controller_step_p99_ms"] == 1.0
        assert report[arm]["aggregate"]["controller_step_max_ms"] == 1.0
