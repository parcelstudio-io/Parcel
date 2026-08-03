"""Run the one-shot paired safe-valley v5 generated development gate.

There is intentionally no confirmation execution mode.  This command verifies
the frozen manifest and every asset/config/source hash, replays the unchanged
cached-frontier v3 reference, then evaluates the deployment-disabled v5 arm on
identical native-proxy episodes.  A sealed confirmation can be designed only
after every predeclared development condition passes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .barn_native import BARN_EVALUATOR_COMMIT
from .barn_policy_specs import (
    PARCEL_POLICY_SOURCE_ROOT,
    REPO_ROOT,
    _source_tree_sha256,
    parcel_experimental_config_spec,
    parcel_reference_config_spec,
)
from .compare_barn import COMPARISON_KIND, run_barn_comparison
from .generate_safe_valley_v5_corpus import (
    CHALLENGER_CONFIG,
    CORPUS_ID,
    DEFAULT_MANIFEST,
    DEVELOPMENT_WORLD_IDS,
    PROMOTION_GATE,
    REFERENCE_CONFIG,
)
from .ledger import record_evaluation_run, sha256_file
from .run_barn import BARN_SOURCE

EVALUATION_KIND = "barn-native-safe-valley-v5-generated-development-non-official"
DEFAULT_RESULTS_ROOT = DEFAULT_MANIFEST.parent / "results"


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    return value


def _verify_file(root: Path, record: Mapping[str, Any], name: str) -> Path:
    raw_path = record.get("path")
    digest = record.get("sha256")
    size = record.get("size_bytes")
    if not isinstance(raw_path, str) or not isinstance(digest, str):
        raise TypeError(f"{name} has invalid path/hash provenance")
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{name} is missing: {path}")
    if sha256_file(path) != digest or path.stat().st_size != int(size):
        raise ValueError(f"{name} changed after the development manifest was frozen")
    return path


def verify_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[dict[str, Any], str, Path]:
    """Verify every frozen input and return manifest, digest, and asset root."""

    path = path.expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported safe-valley corpus manifest")
    if payload.get("corpus_id") != CORPUS_ID:
        raise ValueError("unexpected safe-valley corpus identity")
    status = _require_mapping(payload.get("status_at_freeze"), "status_at_freeze")
    if (
        status.get("development_policy_execution_started") is not False
        or status.get("sealed_confirmation_generated") is not False
        or status.get("sealed_confirmation_opened") is not False
        or status.get("deployment_enabled") is not False
    ):
        raise ValueError("manifest is not in the frozen pre-development state")
    if payload.get("promotion_gate_frozen_before_development") != PROMOTION_GATE:
        raise ValueError("promotion gate changed after predeclaration")

    identity = _require_mapping(payload.get("identity_partition"), "identity_partition")
    development_ids = tuple(int(value) for value in identity["development_world_ids"])
    sealed_ids = tuple(int(value) for value in identity["sealed_confirmation_world_ids"])
    forbidden_ids = {
        int(value) for value in identity["forbidden_static_public_consumed_frozen_sealed_ids"]
    }
    if development_ids != DEVELOPMENT_WORLD_IDS:
        raise ValueError("development ID order changed")
    if set(development_ids) & (forbidden_ids | set(sealed_ids)):
        raise ValueError("development IDs overlap consumed/frozen/sealed identities")

    corpus = _require_mapping(payload.get("development_corpus"), "development_corpus")
    assets_root = Path(str(corpus["assets_root"])).expanduser().resolve()
    episodes = corpus.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != len(DEVELOPMENT_WORLD_IDS):
        raise ValueError("development corpus episode count changed")
    for episode in episodes:
        item = _require_mapping(episode, "development episode")
        world_id = int(item["world_id"])
        if world_id not in DEVELOPMENT_WORLD_IDS:
            raise ValueError(f"unexpected generated development world ID {world_id}")
        files = _require_mapping(item.get("files"), f"world {world_id} files")
        for kind in ("world", "path", "grid", "cspace", "metrics"):
            _verify_file(assets_root, _require_mapping(files.get(kind), kind), f"{world_id}/{kind}")
    if any(
        (assets_root / directory / f"{stem}_{world_id}{suffix}").exists()
        for world_id in sealed_ids
        for directory, stem, suffix in (
            ("world_files", "world", ".world"),
            ("path_files", "path", ".npy"),
            ("grid_files", "grid", ".npy"),
        )
    ):
        raise ValueError("sealed confirmation geometry exists in the development asset root")

    frozen = _require_mapping(
        payload.get("frozen_policy_inputs_before_execution"),
        "frozen_policy_inputs_before_execution",
    )
    for name in ("reference_config", "reference_model", "challenger_config", "challenger_model"):
        _verify_file(REPO_ROOT, _require_mapping(frozen.get(name), name), name)
    source_tree = _require_mapping(frozen.get("policy_source_tree"), "policy_source_tree")
    if _source_tree_sha256(PARCEL_POLICY_SOURCE_ROOT) != source_tree.get("sha256"):
        raise ValueError("Parcel policy source changed after the manifest was frozen")
    harness = _require_mapping(frozen.get("harness_files"), "harness_files")
    for name, record in harness.items():
        _verify_file(REPO_ROOT, _require_mapping(record, str(name)), f"harness/{name}")
    protocol = _require_mapping(
        payload.get("protocol_frozen_before_development"),
        "protocol_frozen_before_development",
    )
    if (
        protocol.get("sealed_confirmation_must_not_be_generated_opened_or_run_during_development")
        is not True
    ):
        raise ValueError("sealed-confirmation guard is absent")
    return payload, sha256_file(path), assets_root


def _finite(mapping: Mapping[str, Any], key: str) -> float:
    value = float(mapping[key])
    if not math.isfinite(value):
        raise ValueError(f"non-finite evaluation metric: {key}")
    return value


def evaluate_gate(report: Mapping[str, Any]) -> tuple[dict[str, bool], dict[str, Any]]:
    """Evaluate only the conditions frozen in the pre-run corpus manifest."""

    baseline = _require_mapping(report.get("baseline"), "baseline")
    candidate = _require_mapping(report.get("candidate"), "candidate")
    baseline_aggregate = _require_mapping(baseline.get("aggregate"), "baseline aggregate")
    candidate_aggregate = _require_mapping(candidate.get("aggregate"), "candidate aggregate")
    comparison = _require_mapping(report.get("comparison"), "comparison")
    paired = _require_mapping(comparison.get("paired_outcomes"), "paired outcomes")
    deltas = _require_mapping(comparison.get("candidate_minus_baseline"), "paired deltas")
    baseline_diagnostics = _require_mapping(
        baseline_aggregate.get("evaluator_diagnostics"),
        "baseline evaluator diagnostics",
    )
    candidate_diagnostics = _require_mapping(
        candidate_aggregate.get("evaluator_diagnostics"),
        "candidate evaluator diagnostics",
    )
    policy_diagnostics = _require_mapping(
        candidate_aggregate.get("policy_diagnostics"),
        "candidate policy diagnostics",
    )
    phases = _require_mapping(policy_diagnostics.get("controller_phase_counts"), "phase counts")

    baseline_clearance = _finite(
        baseline_diagnostics,
        "minimum_signed_obstacle_clearance_m",
    )
    candidate_clearance = _finite(
        candidate_diagnostics,
        "minimum_signed_obstacle_clearance_m",
    )
    baseline_p99 = _finite(baseline_aggregate, "controller_step_p99_ms")
    candidate_p99 = _finite(candidate_aggregate, "controller_step_p99_ms")
    latency_ratio = candidate_p99 / baseline_p99 if baseline_p99 > 0.0 else math.inf
    advance_steps = int(phases.get("grid_safe_valley_advance", 0))
    gates = {
        "same_world_trial_seed_native_config_and_manifest": bool(
            comparison.get("same_worlds_trials_config_and_seeds") is True
            and baseline["benchmark"]["asset_manifest_sha256"]
            == candidate["benchmark"]["asset_manifest_sha256"]
        ),
        "safe_valley_advance_phase_exercised": advance_steps > 0,
        "minimum_paired_success_gains": int(paired["success_gains"])
        >= int(PROMOTION_GATE["minimum_paired_success_gains"]),
        "maximum_paired_success_regressions": int(paired["success_regressions"])
        <= int(PROMOTION_GATE["maximum_paired_success_regressions"]),
        "positive_navigation_metric_delta": _finite(deltas, "navigation_metric") > 0.0,
        "zero_candidate_collision_rate": _finite(candidate_aggregate, "collision_rate") == 0.0,
        "no_timeout_rate_increase": _finite(candidate_aggregate, "timeout_rate")
        <= _finite(baseline_aggregate, "timeout_rate") + 1e-12,
        "minimum_signed_clearance_floor": candidate_clearance
        >= float(PROMOTION_GATE["minimum_signed_clearance_must_be_at_least"]),
        "maximum_clearance_floor_regression": candidate_clearance
        >= baseline_clearance - float(PROMOTION_GATE["maximum_clearance_floor_regression_m"]),
        "controller_p99_latency_absolute": candidate_p99
        <= float(PROMOTION_GATE["maximum_controller_p99_latency_ms"]),
        "controller_p99_latency_ratio": latency_ratio
        <= float(PROMOTION_GATE["maximum_controller_p99_latency_ratio"]),
    }
    diagnostics = {
        "safe_valley_advance_steps": advance_steps,
        "reference_minimum_signed_clearance_m": baseline_clearance,
        "candidate_minimum_signed_clearance_m": candidate_clearance,
        "clearance_floor_delta_m": candidate_clearance - baseline_clearance,
        "reference_controller_p99_ms": baseline_p99,
        "candidate_controller_p99_ms": candidate_p99,
        "controller_p99_latency_ratio": latency_ratio,
        "all_conditions_passed": all(gates.values()),
    }
    return gates, diagnostics


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)


def _run_id() -> str:
    return "barn-safe-valley-v5-dev-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_development(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    run_id: str | None = None,
) -> dict[str, Any]:
    manifest, manifest_sha256, assets_root = verify_manifest(manifest_path)
    protocol = _require_mapping(
        manifest["protocol_frozen_before_development"],
        "protocol",
    )
    identifier = run_id or _run_id()
    full_report_path = results_root / "runs" / f"{identifier}.json"
    summary_path = results_root / f"{identifier}-summary.json"
    if full_report_path.exists() or summary_path.exists():
        raise FileExistsError(f"refusing to replace safe-valley run {identifier}")

    reference_spec = parcel_reference_config_spec(
        REFERENCE_CONFIG,
        reference_id="barn-safe-valley-v5-reference-frontier-cached-v3",
        description="Unchanged selected cached-frontier v3 reference on frozen generated corpus",
    )
    candidate_spec = parcel_experimental_config_spec(
        CHALLENGER_CONFIG,
        experiment_id="barn-safe-valley-v5-challenger",
        description=(
            "Deployment-disabled fresh LiDAR/odometry safe-valley micro-advance challenger"
        ),
    )
    paired = run_barn_comparison(
        assets_root=assets_root,
        world_indices=DEVELOPMENT_WORLD_IDS,
        candidate_spec=candidate_spec,
        baseline_spec=reference_spec,
        trials=int(protocol["trials_per_world"]),
        lidar_ray_count=int(protocol["lidar_rays"]),
        suite_seed=int(protocol["suite_seed"]),
        allow_experimental=True,
        workers=int(protocol["episode_workers"]),
        generated_corpus=True,
        asset_manifest_sha256=manifest_sha256,
    )
    gates, gate_diagnostics = evaluate_gate(paired)
    passed = bool(gate_diagnostics["all_conditions_passed"])
    result: dict[str, Any] = {
        "schema_version": 1,
        "run_id": identifier,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_kind": EVALUATION_KIND,
        "comparison_kind": COMPARISON_KIND,
        "official_gazebo_score": False,
        "leaderboard_claim": False,
        "corpus": {
            "id": CORPUS_ID,
            "manifest_path": str(manifest_path.resolve()),
            "manifest_sha256": manifest_sha256,
            "world_ids": list(DEVELOPMENT_WORLD_IDS),
            "sealed_confirmation_generated": False,
            "sealed_confirmation_opened": False,
            "sealed_confirmation_evaluated": False,
        },
        "frozen_promotion_gate": PROMOTION_GATE,
        "gate_results": gates,
        "gate_diagnostics": gate_diagnostics,
        "decision": {
            "selected_for_single_sealed_confirmation": passed,
            "confirmation_execution_implemented": False,
            "confirmation_command_authorized": False,
            "deployment_enabled": False,
            "reason": (
                "All development gates passed; a separate sealed one-shot command must be "
                "reviewed before confirmation."
                if passed
                else "One or more predeclared development gates failed; sealed confirmation "
                "remains unopened and unauthorized."
            ),
        },
        "paired_report": paired,
    }
    _write_immutable_json(full_report_path, result)
    baseline = paired["baseline"]["aggregate"]
    candidate = paired["candidate"]["aggregate"]
    comparison = paired["comparison"]
    ledger_metrics = {
        "reference": baseline,
        "candidate": candidate,
        "paired_outcomes": comparison["paired_outcomes"],
        "candidate_minus_reference": comparison["candidate_minus_baseline"],
        "promotion_gate": gates,
        "gate_diagnostics": gate_diagnostics,
        "decision": result["decision"],
        "corpus_manifest_sha256": manifest_sha256,
    }
    ledger = record_evaluation_run(
        benchmark_id=EVALUATION_KIND,
        benchmark_source=BARN_SOURCE,
        benchmark_source_commit=BARN_EVALUATOR_COMMIT,
        change_description=(
            "Paired unchanged cached-frontier v3 reference versus deployment-disabled "
            "fresh-sensor safe-valley v5 on a frozen disjoint generated development corpus."
        ),
        aggregate_metrics=ledger_metrics,
        report_path=full_report_path,
        ledger_dir=results_root / "ledger",
        run_id=identifier,
        agent_id=candidate_spec.agent_id,
        adapter_id=candidate_spec.adapter_id,
        adapter_hash=candidate_spec.implementation_sha256,
        config_id=candidate_spec.config_id,
        config_hash=candidate_spec.config_sha256,
        model_id=candidate_spec.model_id,
        model_hash=candidate_spec.model_artifact_sha256,
    )
    summary = {
        "schema_version": 1,
        "run_id": identifier,
        "timestamp_utc": ledger.record["timestamp_utc"],
        "evaluation_kind": EVALUATION_KIND,
        "official_gazebo_score": False,
        "corpus_id": CORPUS_ID,
        "corpus_manifest_sha256": manifest_sha256,
        "development_world_count": len(DEVELOPMENT_WORLD_IDS),
        "sealed_confirmation_generated": False,
        "sealed_confirmation_opened": False,
        "sealed_confirmation_evaluated": False,
        "reference": {
            "policy": "grid_frontier_cached_v3",
            "success_rate": baseline["success_rate"],
            "navigation_metric": baseline["navigation_metric"],
            "collision_rate": baseline["collision_rate"],
            "timeout_rate": baseline["timeout_rate"],
            "minimum_signed_clearance_m": baseline["evaluator_diagnostics"][
                "minimum_signed_obstacle_clearance_m"
            ],
            "controller_step_p99_ms": baseline["controller_step_p99_ms"],
        },
        "candidate": {
            "policy": "grid_safe_valley_v5",
            "success_rate": candidate["success_rate"],
            "navigation_metric": candidate["navigation_metric"],
            "collision_rate": candidate["collision_rate"],
            "timeout_rate": candidate["timeout_rate"],
            "minimum_signed_clearance_m": candidate["evaluator_diagnostics"][
                "minimum_signed_obstacle_clearance_m"
            ],
            "controller_step_p99_ms": candidate["controller_step_p99_ms"],
            "safe_valley_advance_steps": gate_diagnostics["safe_valley_advance_steps"],
        },
        "paired": {
            "outcomes": comparison["paired_outcomes"],
            "candidate_minus_reference": comparison["candidate_minus_baseline"],
        },
        "promotion_gate": gates,
        "gate_diagnostics": gate_diagnostics,
        "decision": result["decision"],
        "full_report": ledger.record["report"],
        "ledger_record_path": str(ledger.record_path),
        "limitations": [
            "Generated native CPU proxy; not official Gazebo BARN or a leaderboard score.",
            "The candidate remains deployment-disabled regardless of this development result.",
            "No v4 sealed world or safe-valley sealed confirmation asset was opened or run.",
        ],
    }
    _write_immutable_json(summary_path, summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute-development",
        action="store_true",
        help="required acknowledgement for the one-shot frozen development run",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if not args.execute_development:
        parser.error("development execution requires --execute-development")
    summary = run_development(
        manifest_path=args.manifest,
        results_root=args.results_root,
        run_id=args.run_id,
    )
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - command-line entry point
    raise SystemExit(main())


__all__ = ["EVALUATION_KIND", "evaluate_gate", "run_development", "verify_manifest"]
