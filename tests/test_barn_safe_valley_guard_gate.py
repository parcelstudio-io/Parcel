from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from evals.external.generate_safe_valley_guard_v6_corpus import (
    DEVELOPMENT_WORLD_IDS,
    PROMOTION_GATE,
    SEALED_CONFIRMATION_WORLD_IDS,
    _seed,
)
from evals.external.run_safe_valley_guard_v6 import evaluate_gate

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_ROOT = REPO_ROOT / "evals" / "external" / "development" / "barn_safe_valley_guard_v6"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _passing_report() -> dict[str, object]:
    return {
        "baseline": {
            "benchmark": {"asset_manifest_sha256": "a" * 64},
            "aggregate": {
                "collision_rate": 0.0,
                "timeout_rate": 0.05,
                "controller_step_p99_ms": 20.0,
                "evaluator_diagnostics": {
                    "minimum_signed_obstacle_clearance_m": 0.080,
                },
                "policy_diagnostics": {"controller_phase_counts": {}},
            },
        },
        "candidate": {
            "benchmark": {"asset_manifest_sha256": "a" * 64},
            "aggregate": {
                "collision_rate": 0.0,
                "timeout_rate": 0.0,
                "controller_step_p99_ms": 21.0,
                "evaluator_diagnostics": {
                    "minimum_signed_obstacle_clearance_m": 0.090,
                },
                "policy_diagnostics": {
                    "controller_phase_counts": {"grid_safe_valley_advance": 8},
                },
            },
        },
        "comparison": {
            "same_worlds_trials_config_and_seeds": True,
            "paired_outcomes": {"success_gains": 0, "success_regressions": 0},
            "candidate_minus_baseline": {"navigation_metric": 0.0},
            "paired_episodes": [
                {
                    "baseline_status": "stopped_outside_goal",
                    "candidate_status": "stopped_outside_goal",
                    "final_goal_distance_delta_m": -0.1,
                    "maximum_goal_progress_delta_m": 0.1,
                    "minimum_signed_clearance_delta_m": 0.01,
                    "navigation_metric_delta": 0.0,
                }
            ],
        },
    }


def test_v6_gate_requires_all_predeclared_safety_liveness_and_quality_conditions() -> None:
    gates, diagnostics = evaluate_gate(_passing_report())
    assert all(gates.values())
    assert diagnostics["all_conditions_passed"] is True
    assert diagnostics["guarded_safe_valley_advance_steps"] == 8
    assert diagnostics["guard_affected_paired_episodes"] == 1
    assert PROMOTION_GATE["candidate_timeout_rate_must_equal"] == 0.0
    assert PROMOTION_GATE["maximum_clearance_floor_regression_m"] == 0.0

    failed = copy.deepcopy(_passing_report())
    failed["candidate"]["aggregate"]["timeout_rate"] = 0.05  # type: ignore[index]
    failed["candidate"]["aggregate"]["evaluator_diagnostics"][  # type: ignore[index]
        "minimum_signed_obstacle_clearance_m"
    ] = 0.074
    failed["comparison"]["paired_episodes"][0].update(  # type: ignore[index]
        {
            "final_goal_distance_delta_m": 0.0,
            "maximum_goal_progress_delta_m": 0.0,
            "minimum_signed_clearance_delta_m": 0.0,
        }
    )
    failed_gates, failed_diagnostics = evaluate_gate(failed)
    assert failed_gates["zero_candidate_timeout_rate"] is False
    assert failed_gates["minimum_signed_clearance_floor"] is False
    assert failed_gates["minimum_guard_affected_paired_episodes"] is False
    assert failed_diagnostics["all_conditions_passed"] is False


def test_v6_ids_and_seed_recipe_are_disjoint_from_public_and_all_v5_identities() -> None:
    forbidden = set(range(300)) | set(range(1000, 1050))
    assert set(DEVELOPMENT_WORLD_IDS).isdisjoint(forbidden)
    assert set(SEALED_CONFIRMATION_WORLD_IDS).isdisjoint(forbidden)
    assert set(DEVELOPMENT_WORLD_IDS).isdisjoint(SEALED_CONFIRMATION_WORLD_IDS)
    assert _seed(2000, 1) == _seed(2000, 1)
    assert _seed(2000, 1) != _seed(2000, 2)
    assert _seed(2000, 1) != _seed(2001, 1)


def test_frozen_v6_evidence_rejects_guard_and_keeps_confirmation_unopened() -> None:
    predecessor_path = DEVELOPMENT_ROOT / "split.json"
    repaired_path = DEVELOPMENT_ROOT / "split-run02.json"
    preflight_path = (
        DEVELOPMENT_ROOT
        / "results"
        / "preflight"
        / "barn-safe-valley-guard-v6-dev-20260803-run01-failed-before-episodes.json"
    )
    summary_path = (
        DEVELOPMENT_ROOT / "results" / "barn-safe-valley-guard-v6-dev-20260803-run02-summary.json"
    )
    repaired = json.loads(repaired_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert _sha256(predecessor_path) == (
        "47dddf6b54a8cc6b962f6bb4b16912a2d72266187126e13c6559af0f0949cd63"
    )
    assert _sha256(repaired_path) == (
        "821e70935c447007614e1a6b939c9a1d0769443cebdf7f5028e4bdcf348e13a5"
    )
    assert _sha256(summary_path) == (
        "0453abc5e900c5c8f76453a0e30661eb63e0d10ddd4d2ba969db889ce344ebb9"
    )
    assert preflight["episode_policy_executions"] == 0
    assert preflight["episode_outcomes_inspected"] is False
    assert preflight["metrics_generated"] is False
    assert (
        repaired["manifest_revision"][
            "corpus_reused_without_episode_execution_or_outcome_inspection"
        ]
        is True
    )
    assert repaired["development_corpus"]["world_count"] == 30
    assert repaired["development_corpus"]["corpus_sha256"] == (
        "fd587ef042b8fae124c4b0b2779548023d0b374eaf5d4bd9759ea4b0d00ff579"
    )
    assert repaired["sealed_confirmation_recipe"]["generated"] is False
    assert repaired["sealed_confirmation_recipe"]["opened"] is False

    assert summary["reference"]["success_rate"] == 0.5
    assert summary["candidate"]["success_rate"] == 0.5
    assert summary["reference"]["timeout_rate"] == 4 / 30
    assert summary["candidate"]["timeout_rate"] == 4 / 30
    assert summary["candidate"]["collision_rate"] == 0.0
    assert summary["candidate"]["minimum_signed_clearance_m"] >= 0.075
    assert summary["candidate"]["guarded_safe_valley_advance_steps"] == 964
    assert summary["gate_diagnostics"]["guard_affected_paired_episodes"] == 10
    assert summary["promotion_gate"]["zero_candidate_timeout_rate"] is False
    assert sum(not passed for passed in summary["promotion_gate"].values()) == 1
    assert summary["decision"]["selected_for_single_sealed_confirmation"] is False
    assert summary["decision"]["confirmation_command_authorized"] is False
    assert summary["decision"]["deployment_enabled"] is False
    assert summary["sealed_confirmation_generated"] is False
    assert summary["sealed_confirmation_opened"] is False
    assert summary["sealed_confirmation_evaluated"] is False
