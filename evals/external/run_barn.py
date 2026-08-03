"""Run and ledger Parcel's sensor-only baseline on public BARN assets."""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import uuid
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from .barn_native import (
    BARN_EVALUATOR_COMMIT,
    BARN_NATIVE_EVALUATION_KIND,
    BARN_PUBLIC_WORLD_INDICES,
    DEFAULT_LIDAR_RAY_COUNT,
    JACKAL_MELODIC_REFERENCE_COMMIT,
    JACKAL_SIMULATOR_MELODIC_REFERENCE_COMMIT,
    BarnNativeConfig,
    BarnNativeRunner,
    BarnPolicy,
    BarnWorld,
    load_barn_world,
    load_generated_barn_world,
)
from .barn_policy_specs import (
    BarnPolicySpec,
    ProcessPolicyDescriptor,
    parcel_baseline_policy_spec,
    parcel_experimental_config_spec,
)
from .barn_targets import evaluate_barn_top_decile_target
from .ledger import record_evaluation_run

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASSETS_ROOT = (
    REPO_ROOT
    / ".cache"
    / "external-evals"
    / "repos"
    / "barn_challenge"
    / "jackal_helper"
    / "worlds"
    / "BARN"
)
DEFAULT_RESULTS_ROOT = Path(__file__).resolve().parent / "results"
BARN_SOURCE = "https://github.com/Daffan/the-barn-challenge"


def select_worlds(value: str) -> tuple[int, ...]:
    normalized = value.strip().lower()
    if normalized == "public":
        return BARN_PUBLIC_WORLD_INDICES
    if normalized == "pr":
        return BARN_PUBLIC_WORLD_INDICES[:10]
    try:
        worlds = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("worlds must be 'pr', 'public', or comma-separated integers") from exc
    if not worlds or len(set(worlds)) != len(worlds):
        raise ValueError("world selection must be non-empty and contain no duplicates")
    if any(index < 0 or index >= 300 for index in worlds):
        raise ValueError("static BARN world indices must be in [0, 299]")
    return worlds


def _percentile(samples: list[float], quantile: float) -> float:
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _latency_summary(samples: dict[str, list[float]]) -> dict[str, float]:
    summary: dict[str, float] = {}
    for prefix, values in samples.items():
        if not values:
            continue
        summary[f"{prefix}_count"] = float(len(values))
        summary[f"{prefix}_mean_ms"] = fmean(values)
        summary[f"{prefix}_p50_ms"] = _percentile(values, 0.50)
        summary[f"{prefix}_p95_ms"] = _percentile(values, 0.95)
        summary[f"{prefix}_p99_ms"] = _percentile(values, 0.99)
        summary[f"{prefix}_max_ms"] = max(values)
    return summary


@dataclass(frozen=True, slots=True)
class _EpisodeRequest:
    """Pickle-safe inputs for one isolated benchmark episode."""

    world: BarnWorld
    config: BarnNativeConfig
    trial: int
    episode_seed: int
    process_policy: ProcessPolicyDescriptor


@dataclass(frozen=True, slots=True)
class _EpisodeExecution:
    """Episode result plus policy-owned telemetry returned to the parent."""

    detail: dict[str, Any]
    latency_samples_ms: dict[str, tuple[float, ...]]
    controller_phase_counts: dict[str, int]
    safety_phase_counts: dict[str, int]


def _execute_episode(
    *,
    world: BarnWorld,
    config: BarnNativeConfig,
    policy: BarnPolicy,
    trial: int,
    episode_seed: int,
) -> _EpisodeExecution:
    """Run and close one fresh policy without performing any durable writes."""

    try:
        result = BarnNativeRunner(world, config).run(policy)
        latency_fn = getattr(policy, "latency_metrics", None)
        samples_fn = getattr(policy, "latency_samples_ms", None)
        diagnostics_fn = getattr(policy, "policy_diagnostics", None)
        latency = latency_fn() if callable(latency_fn) else {}
        raw_samples = samples_fn() if callable(samples_fn) else {}
        latency_samples = {
            str(name): tuple(float(value) for value in samples)
            for name, samples in raw_samples.items()
        }
        policy_diagnostics = diagnostics_fn() if callable(diagnostics_fn) else {}
        if not isinstance(policy_diagnostics, dict):
            policy_diagnostics = {}
        detail = asdict(result)
        detail["trial"] = trial
        detail["episode_seed"] = episode_seed
        detail["final_distance_to_goal_m"] = math.dist(
            result.final_position_xy,
            (-2.25, 13.0),
        )
        detail["latency"] = latency
        detail["policy_diagnostics"] = policy_diagnostics
        return _EpisodeExecution(
            detail=detail,
            latency_samples_ms=latency_samples,
            controller_phase_counts={
                str(name): int(count)
                for name, count in policy_diagnostics.get(
                    "controller_phase_counts",
                    {},
                ).items()
            },
            safety_phase_counts={
                str(name): int(count)
                for name, count in policy_diagnostics.get("safety_phase_counts", {}).items()
            },
        )
    finally:
        close_fn = getattr(policy, "close", None)
        if callable(close_fn):
            close_fn()


def _run_process_episode(request: _EpisodeRequest) -> _EpisodeExecution:
    """Top-level spawn worker; intentionally accepts no arbitrary factory."""

    policy = request.process_policy.create(episode_seed=request.episode_seed)
    if not isinstance(policy, BarnPolicy):
        raise TypeError("process policy descriptor must create a BarnPolicy")
    return _execute_episode(
        world=request.world,
        config=request.config,
        policy=policy,
        trial=request.trial,
        episode_seed=request.episode_seed,
    )


def run_barn_suite(
    *,
    assets_root: str | Path,
    world_indices: Sequence[int],
    trials: int = 1,
    lidar_ray_count: int = DEFAULT_LIDAR_RAY_COUNT,
    policy_spec: BarnPolicySpec | None = None,
    allow_experimental: bool = False,
    suite_seed: int = 20260803,
    workers: int = 1,
    generated_corpus: bool = False,
    asset_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    if not world_indices:
        raise ValueError("world_indices must not be empty")
    if not 1 <= trials <= 100:
        raise ValueError("trials must be in [1, 100]")
    if not 0 <= suite_seed < 2**63:
        raise ValueError("suite_seed must be in [0, 2**63)")
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 128:
        raise ValueError("workers must be an integer in [1, 128]")
    config = BarnNativeConfig(lidar_ray_count=lidar_ray_count)
    spec = policy_spec or parcel_baseline_policy_spec()
    spec.ensure_enabled(allow_experimental=allow_experimental)
    if workers > 1 and spec.execution_device.strip().lower() != "cpu":
        raise ValueError(
            "workers > 1 is a CPU-policy throughput feature; use workers=1 for a GPU policy "
            "to avoid duplicated model memory and device contention"
        )
    process_policy = spec.require_process_descriptor() if workers > 1 else None
    if generated_corpus:
        if (
            asset_manifest_sha256 is None
            or len(asset_manifest_sha256) != 64
            or any(character not in "0123456789abcdef" for character in asset_manifest_sha256)
        ):
            raise ValueError("generated corpus requires its lowercase SHA-256 manifest hash")
        world_loader = load_generated_barn_world
    else:
        if asset_manifest_sha256 is not None:
            raise ValueError("asset_manifest_sha256 is valid only for a generated corpus")
        world_loader = load_barn_world
    worlds = [world_loader(assets_root, int(world_index)) for world_index in world_indices]
    episode_inputs = [
        (world, trial, suite_seed + int(world.world_index) * 1_009 + trial)
        for world in worlds
        for trial in range(trials)
    ]
    effective_workers = min(workers, len(episode_inputs))

    if effective_workers > 1:
        assert process_policy is not None
        requests = [
            _EpisodeRequest(
                world=world,
                config=config,
                trial=trial,
                episode_seed=episode_seed,
                process_policy=process_policy,
            )
            for world, trial, episode_seed in episode_inputs
        ]
        # ``spawn`` avoids inheriting policy/model state and is safe for future
        # CUDA-backed built-ins.  Executor.map preserves the requested episode
        # order even when workers finish out of order.
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=effective_workers,
            mp_context=context,
        ) as executor:
            executions = list(executor.map(_run_process_episode, requests, chunksize=1))
    else:
        executions = []
        for world, trial, episode_seed in episode_inputs:
            policy = spec.create(
                episode_seed=episode_seed,
                allow_experimental=allow_experimental,
            )
            executions.append(
                _execute_episode(
                    world=world,
                    config=config,
                    policy=policy,
                    trial=trial,
                    episode_seed=episode_seed,
                )
            )

    episodes: list[dict[str, Any]] = []
    latency_samples: dict[str, list[float]] = {
        "adapter_act": [],
        "controller_step": [],
    }
    policy_phase_counts: Counter[str] = Counter()
    safety_phase_counts: Counter[str] = Counter()
    for execution in executions:
        episodes.append(execution.detail)
        for name, samples in execution.latency_samples_ms.items():
            latency_samples.setdefault(name, []).extend(samples)
        policy_phase_counts.update(execution.controller_phase_counts)
        safety_phase_counts.update(execution.safety_phase_counts)

    count = len(episodes)
    succeeded = [episode for episode in episodes if episode["success"]]
    outcome_counts = Counter(str(episode["status"]) for episode in episodes)
    terminal_note_counts = Counter(
        str(episode["last_action_note"] or "<none>") for episode in episodes
    )
    evaluator_diagnostics = [episode["evaluator_diagnostics"] for episode in episodes]
    clearances = [
        float(item["minimum_signed_obstacle_clearance_m"])
        for item in evaluator_diagnostics
        if item["minimum_signed_obstacle_clearance_m"] is not None
    ]
    successful_route_efficiencies = [
        float(item["successful_reference_route_efficiency"])
        for item in evaluator_diagnostics
        if item["successful_reference_route_efficiency"] is not None
    ]
    aggregate: dict[str, Any] = {
        "episodes": float(count),
        "worlds": float(len(world_indices)),
        "trials_per_world": float(trials),
        "success_rate": sum(bool(episode["success"]) for episode in episodes) / count,
        "navigation_metric": fmean(float(episode["navigation_metric"]) for episode in episodes),
        "collision_rate": sum(bool(episode["collided"]) for episode in episodes) / count,
        "timeout_rate": sum(bool(episode["timed_out"]) for episode in episodes) / count,
        "stopped_outside_goal_rate": sum(
            episode["status"] == "stopped_outside_goal" for episode in episodes
        )
        / count,
        "mean_elapsed_time_s": fmean(float(episode["elapsed_time_s"]) for episode in episodes),
        "mean_success_time_s": (
            fmean(float(episode["elapsed_time_s"]) for episode in succeeded) if succeeded else 0.0
        ),
        "mean_final_distance_to_goal_m": fmean(
            float(episode["final_distance_to_goal_m"]) for episode in episodes
        ),
        "mean_traveled_distance_m": fmean(
            float(episode["traveled_distance_m"]) for episode in episodes
        ),
        **_latency_summary(latency_samples),
        "evaluator_diagnostics": {
            "private_state_not_exposed_to_policy": True,
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "failure_counts": {
                key: value for key, value in sorted(outcome_counts.items()) if key != "succeeded"
            },
            "mean_net_goal_progress_m": fmean(
                float(item["net_goal_progress_m"]) for item in evaluator_diagnostics
            ),
            "mean_maximum_goal_progress_m": fmean(
                float(item["maximum_goal_progress_m"]) for item in evaluator_diagnostics
            ),
            "mean_maximum_goal_progress_fraction": fmean(
                float(item["maximum_goal_progress_fraction"]) for item in evaluator_diagnostics
            ),
            "mean_goal_progress_efficiency": fmean(
                float(item["goal_progress_efficiency"]) for item in evaluator_diagnostics
            ),
            "mean_closest_goal_distance_m": fmean(
                float(item["closest_goal_distance_m"]) for item in evaluator_diagnostics
            ),
            "minimum_signed_obstacle_clearance_m": min(clearances) if clearances else None,
            "mean_episode_minimum_signed_obstacle_clearance_m": (
                fmean(clearances) if clearances else None
            ),
            "mean_traveled_to_reference_path_ratio": fmean(
                float(item["traveled_to_reference_path_ratio"]) for item in evaluator_diagnostics
            ),
            "mean_successful_reference_route_efficiency": (
                fmean(successful_route_efficiencies) if successful_route_efficiencies else None
            ),
            "mean_translational_speed_mps": fmean(
                float(item["mean_translational_speed_mps"]) for item in evaluator_diagnostics
            ),
        },
        "policy_diagnostics": {
            "terminal_action_note_counts": dict(sorted(terminal_note_counts.items())),
            "controller_phase_counts": dict(sorted(policy_phase_counts.items())),
            "safety_phase_counts": dict(sorted(safety_phase_counts.items())),
            "note": "Policy-provided notes are not evaluator failure labels.",
        },
    }
    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": {
            "id": BARN_NATIVE_EVALUATION_KIND,
            "source": BARN_SOURCE,
            "source_commit": BARN_EVALUATOR_COMMIT,
            "public_world_indices": list(world_indices),
            "official_gazebo_score": False,
            "asset_scope": (
                "generated-public-style-development" if generated_corpus else "public-barn-static"
            ),
            "asset_manifest_sha256": asset_manifest_sha256,
            "native_reference_source_commits": {
                "jackal_melodic": JACKAL_MELODIC_REFERENCE_COMMIT,
                "jackal_simulator_melodic": JACKAL_SIMULATOR_MELODIC_REFERENCE_COMMIT,
            },
        },
        "policy": spec.report_metadata(),
        "execution": {
            "evaluator_device": "cpu",
            "lidar_raycast_device": "cpu",
            "kinematics_device": "cpu",
            "policy_declared_device": spec.execution_device,
            "episode_workers_requested": workers,
            "episode_workers_effective": effective_workers,
            "process_start_method": "spawn" if effective_workers > 1 else None,
            "durable_report_writer": "parent_process_only",
            "note": "Native ray casting and kinematics are classical CPU evaluation code by design; policy execution is reported separately.",
        },
        "suite_seed": suite_seed,
        "native_config": asdict(config),
        "aggregate": aggregate,
        "top_decile_target": evaluate_barn_top_decile_target(
            float(aggregate["navigation_metric"]),
            official_protocol=False,
        ),
        "episodes": episodes,
        "notes": [
            "Non-official deterministic native approximation; not a Gazebo or leaderboard score.",
            (
                "Generated public-style development assets only; these IDs are namespaced "
                "outside the 300 public worlds and are not official BARN episodes."
                if generated_corpus
                else "Public BARN assets only; hidden challenge worlds are unavailable."
            ),
            "The policy never receives SDF geometry, the reference path, or optimal path length.",
            "The unchanged Parcel pipeline is adapted at the sensor/action boundary; vy is clamped by the differential-drive adapter.",
            "The native LiDAR follows the referenced Jackal Gazebo ray count/FOV/range but intentionally omits sensor noise.",
            "Evaluator diagnostics are computed after actions from private geometry and never enter policy observations.",
            "The frozen 2026 top-decile score is reference-only for this native proxy and cannot be passed officially here.",
            "Native ray casting and kinematics execute on CPU by design; model policy metadata declares its own device explicitly.",
            "Optional episode workers are independent spawned processes; only the parent writes reports and ledger records.",
        ],
    }


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"barn-native-{stamp}-{uuid.uuid4().hex[:8]}"


def write_report(report: dict[str, Any], *, path: Path) -> Path:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    payload = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    return target


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
        help="spawned CPU episode workers (default: 1; built-in Parcel policies only)",
    )
    parser.add_argument(
        "--policy-config",
        type=Path,
        help="Eval-only navigation config; requires --policy-id and --enable-experimental",
    )
    parser.add_argument("--policy-id", help="Stable experiment identifier for --policy-config")
    parser.add_argument("--enable-experimental", action="store_true")
    parser.add_argument("--description", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--ledger-dir", type=Path)
    args = parser.parse_args(argv)

    try:
        worlds = select_worlds(args.worlds)
    except ValueError as exc:
        parser.error(str(exc))
    if args.policy_config is not None:
        if not args.policy_id:
            parser.error("--policy-config requires --policy-id")
        if not args.enable_experimental:
            parser.error("--policy-config requires --enable-experimental")
        policy_spec = parcel_experimental_config_spec(
            args.policy_config,
            experiment_id=args.policy_id,
            description=args.description,
        )
    else:
        if args.policy_id or args.enable_experimental:
            parser.error("--policy-id/--enable-experimental require --policy-config")
        policy_spec = parcel_baseline_policy_spec()
    report = run_barn_suite(
        assets_root=args.assets_root,
        world_indices=worlds,
        trials=args.trials,
        lidar_ray_count=args.lidar_rays,
        policy_spec=policy_spec,
        allow_experimental=args.enable_experimental,
        suite_seed=args.suite_seed,
        workers=args.workers,
    )
    run_id = args.run_id or _new_run_id()
    report["run_id"] = run_id
    report["change_description"] = args.description
    report_path = write_report(
        report,
        path=args.results_root / "runs" / f"{run_id}.json",
    )
    ledger_dir = args.ledger_dir or args.results_root / "ledger"
    ledger = record_evaluation_run(
        benchmark_id=BARN_NATIVE_EVALUATION_KIND,
        benchmark_source=BARN_SOURCE,
        benchmark_source_commit=BARN_EVALUATOR_COMMIT,
        change_description=args.description,
        aggregate_metrics=report["aggregate"],
        report_path=report_path,
        ledger_dir=ledger_dir,
        run_id=run_id,
        agent_id=policy_spec.agent_id,
        adapter_id=policy_spec.adapter_id,
        adapter_hash=policy_spec.implementation_sha256,
        config_id=policy_spec.config_id,
        config_hash=policy_spec.config_sha256,
        model_id=policy_spec.model_id,
        model_hash=policy_spec.model_artifact_sha256,
    )
    print(
        json.dumps(
            {
                "run_id": run_id,
                "report_path": str(report_path),
                "ledger_record_path": str(ledger.record_path),
                "aggregate": report["aggregate"],
                "top_decile_target": report["top_decile_target"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
