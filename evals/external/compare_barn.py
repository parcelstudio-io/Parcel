"""Run a paired, deterministic BARN-native baseline/candidate experiment."""

from __future__ import annotations

import argparse
import json
import math
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from .barn_native import BARN_EVALUATOR_COMMIT, DEFAULT_LIDAR_RAY_COUNT
from .barn_policy_specs import (
    BarnPolicySpec,
    parcel_baseline_policy_spec,
    parcel_experimental_config_spec,
)
from .ledger import record_evaluation_run
from .run_barn import (
    BARN_SOURCE,
    DEFAULT_ASSETS_ROOT,
    DEFAULT_RESULTS_ROOT,
    run_barn_suite,
    select_worlds,
    write_report,
)

COMPARISON_KIND = "barn-native-paired-comparison-headless-non-official"


def _episode_key(episode: Mapping[str, Any]) -> tuple[int, int]:
    return (int(episode["world_index"]), int(episode["trial"]))


def _diagnostic(episode: Mapping[str, Any], name: str) -> float | None:
    diagnostics = episode.get("evaluator_diagnostics")
    if not isinstance(diagnostics, Mapping):
        raise TypeError("episode is missing evaluator-private diagnostics")
    value = diagnostics.get(name)
    return None if value is None else float(value)


def _paired_delta(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_clearance = _diagnostic(baseline, "minimum_signed_obstacle_clearance_m")
    candidate_clearance = _diagnostic(candidate, "minimum_signed_obstacle_clearance_m")
    return {
        "world_index": int(baseline["world_index"]),
        "trial": int(baseline["trial"]),
        "episode_seed": int(baseline["episode_seed"]),
        "baseline_status": str(baseline["status"]),
        "candidate_status": str(candidate["status"]),
        "success_delta": int(bool(candidate["success"])) - int(bool(baseline["success"])),
        "collision_delta": int(bool(candidate["collided"])) - int(bool(baseline["collided"])),
        "navigation_metric_delta": float(candidate["navigation_metric"])
        - float(baseline["navigation_metric"]),
        "final_goal_distance_delta_m": float(candidate["final_distance_to_goal_m"])
        - float(baseline["final_distance_to_goal_m"]),
        "maximum_goal_progress_delta_m": (
            _diagnostic(candidate, "maximum_goal_progress_m")
            - _diagnostic(baseline, "maximum_goal_progress_m")
        ),
        "minimum_signed_clearance_delta_m": (
            None
            if baseline_clearance is None or candidate_clearance is None
            else candidate_clearance - baseline_clearance
        ),
    }


def compare_barn_reports(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Pair two same-protocol reports and calculate candidate-minus-baseline deltas."""

    if baseline["native_config"] != candidate["native_config"]:
        raise ValueError("paired BARN reports must use the same native configuration")
    if baseline["suite_seed"] != candidate["suite_seed"]:
        raise ValueError("paired BARN reports must use the same suite seed")
    baseline_by_key = {_episode_key(item): item for item in baseline["episodes"]}
    candidate_by_key = {_episode_key(item): item for item in candidate["episodes"]}
    if baseline_by_key.keys() != candidate_by_key.keys():
        raise ValueError("paired BARN reports must contain identical world/trial keys")
    pairs: list[dict[str, Any]] = []
    for key in sorted(baseline_by_key):
        baseline_episode = baseline_by_key[key]
        candidate_episode = candidate_by_key[key]
        if baseline_episode["episode_seed"] != candidate_episode["episode_seed"]:
            raise ValueError(f"episode seed mismatch for pair {key}")
        pairs.append(_paired_delta(baseline_episode, candidate_episode))

    baseline_aggregate = baseline["aggregate"]
    candidate_aggregate = candidate["aggregate"]
    baseline_diagnostics = baseline_aggregate["evaluator_diagnostics"]
    candidate_diagnostics = candidate_aggregate["evaluator_diagnostics"]
    clearance_deltas = [
        float(pair["minimum_signed_clearance_delta_m"])
        for pair in pairs
        if pair["minimum_signed_clearance_delta_m"] is not None
    ]
    metric_deltas = [float(pair["navigation_metric_delta"]) for pair in pairs]
    return {
        "paired_episode_count": len(pairs),
        "same_worlds_trials_config_and_seeds": True,
        "candidate_minus_baseline": {
            "success_rate": float(candidate_aggregate["success_rate"])
            - float(baseline_aggregate["success_rate"]),
            "navigation_metric": float(candidate_aggregate["navigation_metric"])
            - float(baseline_aggregate["navigation_metric"]),
            "collision_rate": float(candidate_aggregate["collision_rate"])
            - float(baseline_aggregate["collision_rate"]),
            "timeout_rate": float(candidate_aggregate["timeout_rate"])
            - float(baseline_aggregate["timeout_rate"]),
            "stopped_outside_goal_rate": float(candidate_aggregate["stopped_outside_goal_rate"])
            - float(baseline_aggregate["stopped_outside_goal_rate"]),
            "mean_final_distance_to_goal_m": float(
                candidate_aggregate["mean_final_distance_to_goal_m"]
            )
            - float(baseline_aggregate["mean_final_distance_to_goal_m"]),
            "mean_maximum_goal_progress_m": float(
                candidate_diagnostics["mean_maximum_goal_progress_m"]
            )
            - float(baseline_diagnostics["mean_maximum_goal_progress_m"]),
            "mean_goal_progress_efficiency": float(
                candidate_diagnostics["mean_goal_progress_efficiency"]
            )
            - float(baseline_diagnostics["mean_goal_progress_efficiency"]),
            "mean_episode_minimum_signed_obstacle_clearance_m": (
                fmean(clearance_deltas) if clearance_deltas else None
            ),
        },
        "paired_outcomes": {
            "success_gains": sum(pair["success_delta"] > 0 for pair in pairs),
            "success_regressions": sum(pair["success_delta"] < 0 for pair in pairs),
            "collision_gains": sum(pair["collision_delta"] < 0 for pair in pairs),
            "collision_regressions": sum(pair["collision_delta"] > 0 for pair in pairs),
            "metric_improvements": sum(delta > 1e-12 for delta in metric_deltas),
            "metric_regressions": sum(delta < -1e-12 for delta in metric_deltas),
            "metric_ties": sum(math.isclose(delta, 0.0, abs_tol=1e-12) for delta in metric_deltas),
        },
        "safety_regression": (
            float(candidate_aggregate["collision_rate"])
            > float(baseline_aggregate["collision_rate"])
        ),
        "paired_episodes": pairs,
    }


def run_barn_comparison(
    *,
    assets_root: str | Path,
    world_indices: Sequence[int],
    candidate_spec: BarnPolicySpec,
    baseline_spec: BarnPolicySpec | None = None,
    trials: int = 1,
    lidar_ray_count: int = DEFAULT_LIDAR_RAY_COUNT,
    suite_seed: int = 20260803,
    allow_experimental: bool = False,
    workers: int = 1,
    generated_corpus: bool = False,
    asset_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Run isolated policy arms over exactly the same deterministic episodes."""

    if not candidate_spec.experimental:
        raise ValueError("candidate_spec must be explicitly marked experimental")
    baseline_policy = baseline_spec or parcel_baseline_policy_spec()
    if baseline_policy.experimental:
        raise ValueError("baseline_spec must not be experimental")
    baseline = run_barn_suite(
        assets_root=assets_root,
        world_indices=world_indices,
        trials=trials,
        lidar_ray_count=lidar_ray_count,
        policy_spec=baseline_policy,
        suite_seed=suite_seed,
        workers=workers,
        generated_corpus=generated_corpus,
        asset_manifest_sha256=asset_manifest_sha256,
    )
    candidate = run_barn_suite(
        assets_root=assets_root,
        world_indices=world_indices,
        trials=trials,
        lidar_ray_count=lidar_ray_count,
        policy_spec=candidate_spec,
        allow_experimental=allow_experimental,
        suite_seed=suite_seed,
        workers=workers,
        generated_corpus=generated_corpus,
        asset_manifest_sha256=asset_manifest_sha256,
    )
    comparison = compare_barn_reports(baseline, candidate)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_kind": COMPARISON_KIND,
        "official_gazebo_score": False,
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison,
        "target_status": {
            "baseline": baseline["top_decile_target"],
            "candidate": candidate["top_decile_target"],
            "official_gate_pass": False,
            "note": "A paired native proxy comparison cannot pass the official target gate.",
        },
    }


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"barn-ab-{stamp}-{uuid.uuid4().hex[:8]}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-root", type=Path, default=DEFAULT_ASSETS_ROOT)
    parser.add_argument(
        "--worlds",
        default="pr",
        help="pr, public (fixed 50-world proxy subset), or comma-separated ids",
    )
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--lidar-rays", type=int, default=DEFAULT_LIDAR_RAY_COUNT)
    parser.add_argument("--suite-seed", type=int, default=20260803)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="spawned CPU episode workers per arm (default: 1)",
    )
    parser.add_argument("--candidate-config", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--enable-experimental", action="store_true")
    parser.add_argument("--description", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--ledger-dir", type=Path)
    args = parser.parse_args(argv)
    if not args.enable_experimental:
        parser.error("paired candidate execution requires --enable-experimental")
    try:
        worlds = select_worlds(args.worlds)
        candidate_spec = parcel_experimental_config_spec(
            args.candidate_config,
            experiment_id=args.candidate_id,
            description=args.description,
        )
        report = run_barn_comparison(
            assets_root=args.assets_root,
            world_indices=worlds,
            candidate_spec=candidate_spec,
            trials=args.trials,
            lidar_ray_count=args.lidar_rays,
            suite_seed=args.suite_seed,
            allow_experimental=True,
            workers=args.workers,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))

    run_id = args.run_id or _new_run_id()
    report["run_id"] = run_id
    report["change_description"] = args.description
    report_path = write_report(
        report,
        path=args.results_root / "runs" / f"{run_id}.json",
    )
    baseline_aggregate = report["baseline"]["aggregate"]
    candidate_aggregate = report["candidate"]["aggregate"]
    comparison_summary = {
        key: value for key, value in report["comparison"].items() if key != "paired_episodes"
    }
    ledger_metrics = {
        "baseline": baseline_aggregate,
        "candidate": candidate_aggregate,
        "comparison": comparison_summary,
        "target_status": report["target_status"],
    }
    ledger = record_evaluation_run(
        benchmark_id=COMPARISON_KIND,
        benchmark_source=BARN_SOURCE,
        benchmark_source_commit=BARN_EVALUATOR_COMMIT,
        change_description=args.description,
        aggregate_metrics=ledger_metrics,
        report_path=report_path,
        ledger_dir=args.ledger_dir or args.results_root / "ledger",
        run_id=run_id,
        agent_id=candidate_spec.agent_id,
        adapter_id=candidate_spec.adapter_id,
        adapter_hash=candidate_spec.implementation_sha256,
        config_id=candidate_spec.config_id,
        config_hash=candidate_spec.config_sha256,
        model_id=candidate_spec.model_id,
        model_hash=candidate_spec.model_artifact_sha256,
    )
    print(
        json.dumps(
            {
                "run_id": run_id,
                "report_path": str(report_path),
                "ledger_record_path": str(ledger.record_path),
                "baseline": {
                    "success_rate": baseline_aggregate["success_rate"],
                    "navigation_metric": baseline_aggregate["navigation_metric"],
                    "collision_rate": baseline_aggregate["collision_rate"],
                },
                "candidate": {
                    "success_rate": candidate_aggregate["success_rate"],
                    "navigation_metric": candidate_aggregate["navigation_metric"],
                    "collision_rate": candidate_aggregate["collision_rate"],
                },
                "candidate_minus_baseline": report["comparison"]["candidate_minus_baseline"],
                "target_status": report["target_status"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["COMPARISON_KIND", "compare_barn_reports", "run_barn_comparison"]
