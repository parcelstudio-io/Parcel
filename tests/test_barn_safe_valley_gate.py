from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from evals.external.barn_native import load_barn_world, load_generated_barn_world
from evals.external.generate_safe_valley_v5_corpus import (
    DEVELOPMENT_WORLD_IDS,
    PROMOTION_GATE,
    SEALED_CONFIRMATION_WORLD_IDS,
    _seed,
)
from evals.external.run_safe_valley_v5 import evaluate_gate

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_ROOT = REPO_ROOT / "evals" / "external" / "development" / "barn_safe_valley_v5"


def _passing_report() -> dict[str, object]:
    baseline_aggregate = {
        "collision_rate": 0.0,
        "timeout_rate": 0.10,
        "controller_step_p99_ms": 20.0,
        "evaluator_diagnostics": {"minimum_signed_obstacle_clearance_m": 0.10},
        "policy_diagnostics": {"controller_phase_counts": {}},
    }
    candidate_aggregate = {
        "collision_rate": 0.0,
        "timeout_rate": 0.05,
        "controller_step_p99_ms": 22.0,
        "evaluator_diagnostics": {"minimum_signed_obstacle_clearance_m": 0.099},
        "policy_diagnostics": {"controller_phase_counts": {"grid_safe_valley_advance": 8}},
    }
    return {
        "baseline": {
            "benchmark": {"asset_manifest_sha256": "a" * 64},
            "aggregate": baseline_aggregate,
        },
        "candidate": {
            "benchmark": {"asset_manifest_sha256": "a" * 64},
            "aggregate": candidate_aggregate,
        },
        "comparison": {
            "same_worlds_trials_config_and_seeds": True,
            "paired_outcomes": {"success_gains": 2, "success_regressions": 0},
            "candidate_minus_baseline": {"navigation_metric": 0.01},
        },
    }


def test_frozen_gate_requires_every_safety_quality_and_latency_condition() -> None:
    gates, diagnostics = evaluate_gate(_passing_report())

    assert all(gates.values())
    assert diagnostics["all_conditions_passed"] is True
    assert diagnostics["safe_valley_advance_steps"] == 8
    assert PROMOTION_GATE["minimum_paired_success_gains"] == 2
    assert PROMOTION_GATE["maximum_controller_p99_latency_ms"] == 100.0

    failed = copy.deepcopy(_passing_report())
    failed["candidate"]["aggregate"]["policy_diagnostics"][  # type: ignore[index]
        "controller_phase_counts"
    ] = {}
    failed["comparison"]["paired_outcomes"]["success_gains"] = 1  # type: ignore[index]
    failed_gates, failed_diagnostics = evaluate_gate(failed)
    assert failed_gates["safe_valley_advance_phase_exercised"] is False
    assert failed_gates["minimum_paired_success_gains"] is False
    assert failed_diagnostics["all_conditions_passed"] is False


def test_generated_id_and_seed_recipe_is_disjoint_and_deterministic() -> None:
    assert min(DEVELOPMENT_WORLD_IDS) >= 1000
    assert set(DEVELOPMENT_WORLD_IDS).isdisjoint(range(300))
    assert set(DEVELOPMENT_WORLD_IDS).isdisjoint(SEALED_CONFIRMATION_WORLD_IDS)
    assert _seed(1000, 1) == _seed(1000, 1)
    assert _seed(1000, 1) != _seed(1000, 2)
    assert _seed(1000, 1) != _seed(1001, 1)


def test_generated_loader_cannot_alias_a_public_world_id(tmp_path: Path) -> None:
    (tmp_path / "world_files").mkdir()
    (tmp_path / "path_files").mkdir()
    (tmp_path / "world_files" / "world_300.world").write_text(
        '<sdf version="1.6"><world name="default"/></sdf>\n',
        encoding="utf-8",
    )
    np.save(tmp_path / "path_files" / "path_300.npy", np.asarray([[15, 0], [15, 29]]))

    generated = load_generated_barn_world(tmp_path, 300)
    assert generated.world_index == 300
    with pytest.raises(ValueError, match="at least 300"):
        load_generated_barn_world(tmp_path, 0)
    with pytest.raises(ValueError, match=r"\[0, 299\]"):
        load_barn_world(tmp_path, 300)


def test_frozen_development_evidence_rejects_v5_and_keeps_confirmation_unopened() -> None:
    manifest = json.loads((DEVELOPMENT_ROOT / "split.json").read_text(encoding="utf-8"))
    summary = json.loads(
        (
            DEVELOPMENT_ROOT / "results" / "barn-safe-valley-v5-dev-20260803-run01-summary.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest["development_corpus"]["world_count"] == 30
    assert manifest["status_at_freeze"]["deployment_enabled"] is False
    assert manifest["sealed_confirmation_recipe"]["generated"] is False
    assert manifest["sealed_confirmation_recipe"]["opened"] is False
    assert summary["paired"]["outcomes"]["success_gains"] == 1
    assert summary["paired"]["outcomes"]["success_regressions"] == 0
    assert summary["candidate"]["safe_valley_advance_steps"] > 0
    assert summary["promotion_gate"]["minimum_paired_success_gains"] is False
    assert summary["promotion_gate"]["minimum_signed_clearance_floor"] is False
    assert summary["promotion_gate"]["no_timeout_rate_increase"] is False
    assert summary["decision"]["selected_for_single_sealed_confirmation"] is False
    assert summary["decision"]["confirmation_command_authorized"] is False
    assert summary["decision"]["deployment_enabled"] is False
    assert summary["sealed_confirmation_generated"] is False
    assert summary["sealed_confirmation_opened"] is False
    assert summary["sealed_confirmation_evaluated"] is False
