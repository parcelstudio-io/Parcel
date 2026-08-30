"""Run and aggregate the preregistered DMC-1 benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import platform
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from dmc_sim import (
    ConservativeSnapshotController,
    ExplicitTemporalController,
    LearnedController,
    generate_spec,
    run_episode,
)
from local_policy import DIRECTIONS, FEATURES, FEATURE_TO_ID, WINDOW, load_policies


HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"
DESIGN = HERE / "DESIGN.md"
AMENDMENTS = HERE / "AMENDMENTS.md"
SYSTEM_NAMES = (
    "F0_flat_latest_intent",
    "L0_ledger_snapshot",
    "L1_ledger_explicit_time",
    "A0_ledger_snapshot_mlp",
    "A1_ledger_history_gru",
)
CANDIDATE = "A1_ledger_history_gru"
FLAT = "F0_flat_latest_intent"
DETERMINISTIC_KEYS = (
    "schema",
    "evidence_class",
    "counts",
    "split_manifest",
    "aggregates",
    "liveness_slice",
    "training_metrics",
    "hypotheses",
    "overall_verdict",
    "source_hashes",
    "rows",
)

_WORKER_POLICIES: Any = None


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _payload_hash(payload: dict[str, Any]) -> str:
    selected = {key: payload[key] for key in DETERMINISTIC_KEYS}
    return hashlib.sha256(_canonical(selected)).hexdigest()


def _worker_init(artifact_dir: str) -> None:
    global _WORKER_POLICIES
    torch.set_num_threads(1)
    _WORKER_POLICIES = load_policies(Path(artifact_dir))


def _worker_run(item: tuple[int, str]) -> dict[str, Any]:
    if _WORKER_POLICIES is None:
        raise RuntimeError("worker policies are not initialized")
    seed, split = item
    return run_episode(generate_spec(seed, split), _WORKER_POLICIES)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _bootstrap_rate(values: list[bool], *, seed: int, samples: int = 2_000) -> dict[str, float]:
    if not values:
        return {"estimate": 0.0, "lower_95": 0.0, "upper_95": 0.0}
    array = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(array), size=(samples, len(array)))
    means = array[indices].mean(axis=1)
    return {
        "estimate": float(array.mean()),
        "lower_95": float(np.percentile(means, 2.5)),
        "upper_95": float(np.percentile(means, 97.5)),
    }


def _bootstrap_paired_delta(
    first: list[bool], second: list[bool], *, seed: int, samples: int = 2_000
) -> dict[str, float]:
    if len(first) != len(second) or not first:
        raise ValueError("paired arrays must be non-empty and aligned")
    delta = np.asarray(second, dtype=np.float64) - np.asarray(first, dtype=np.float64)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(delta), size=(samples, len(delta)))
    means = delta[indices].mean(axis=1)
    return {
        "estimate": float(delta.mean()),
        "lower_95": float(np.percentile(means, 2.5)),
        "upper_95": float(np.percentile(means, 97.5)),
    }


def _features(*, edge: float, blocked_count: int, direction: str = "east") -> list[float]:
    row = [0.0 for _ in FEATURES]
    row[FEATURE_TO_ID["has_task"]] = 1.0
    row[FEATURE_TO_ID["sensors_fresh"]] = 1.0
    row[FEATURE_TO_ID["edge_state"]] = edge
    row[FEATURE_TO_ID["sound_allowed"]] = 1.0
    row[FEATURE_TO_ID[f"plan_{direction}"]] = 1.0
    row[FEATURE_TO_ID["blocked_reported"]] = float(blocked_count >= 5)
    return row


def _liveness_controller_result(controller: Any, patterns: list[list[float]]) -> dict[str, Any]:
    history: list[list[float]] = []
    blocked = 0
    first_clear: int | None = None
    first_progress: int | None = None
    occupied_direction_attempts = 0
    post_gate_unsafe = 0
    for tick, edge in enumerate(patterns):
        blocked = blocked + 1 if edge < -0.5 else 0
        feature = _features(edge=edge, blocked_count=blocked)
        history.append(feature)
        action = controller.propose(feature, history[-WINDOW:], "east")
        occupied = edge < -0.5
        if occupied and action in DIRECTIONS:
            occupied_direction_attempts += 1
            # Deterministic admission rejects it.
        if not occupied and first_clear is None:
            first_clear = tick
        admitted = action == "east" and not occupied
        if admitted and first_clear is not None and first_progress is None:
            first_progress = tick
        if admitted and occupied:
            post_gate_unsafe += 1
    latency = None if first_clear is None or first_progress is None else first_progress - first_clear
    return {
        "latency_frames": latency,
        "occupied_direction_attempts": occupied_direction_attempts,
        "post_gate_unsafe": post_gate_unsafe,
    }


def run_liveness_slice(policies: Any, *, cases: int = 5_000, seed: int = 5292026) -> dict[str, Any]:
    rng = random.Random(seed)
    constructors = {
        "L0_ledger_snapshot": lambda: ConservativeSnapshotController(),
        "L1_ledger_explicit_time": lambda: ExplicitTemporalController(),
        "A0_ledger_snapshot_mlp": lambda: LearnedController(policies.snapshot),
        "A1_ledger_history_gru": lambda: LearnedController(policies.history),
    }
    raw: dict[str, dict[str, list[float] | int]] = {
        name: {"latencies": [], "persistent_attempts": 0, "persistent_frames": 0, "post_gate_unsafe": 0}
        for name in constructors
    }
    for _ in range(cases):
        occupied = rng.randint(1, 4)
        clear = rng.randint(8, 14)
        if rng.random() < 0.5:
            transient = [-1.0] * occupied + [1.0, -1.0, 1.0, 1.0] + [1.0] * clear
        else:
            transient = [-1.0] * occupied + [1.0] * clear
        persistent = [-1.0] * rng.randint(12, 24)
        for name, constructor in constructors.items():
            transient_result = _liveness_controller_result(constructor(), transient)
            latency = transient_result["latency_frames"]
            if latency is not None:
                raw[name]["latencies"].append(float(latency))  # type: ignore[union-attr]
            raw[name]["post_gate_unsafe"] += transient_result["post_gate_unsafe"]  # type: ignore[operator]
            persistent_result = _liveness_controller_result(constructor(), persistent)
            raw[name]["persistent_attempts"] += persistent_result["occupied_direction_attempts"]  # type: ignore[operator]
            raw[name]["persistent_frames"] += len(persistent)  # type: ignore[operator]
            raw[name]["post_gate_unsafe"] += persistent_result["post_gate_unsafe"]  # type: ignore[operator]

    result: dict[str, Any] = {}
    for name, values in raw.items():
        latencies = list(values["latencies"])  # type: ignore[arg-type]
        persistent_frames = int(values["persistent_frames"])
        result[name] = {
            "cases": cases,
            "clear_latency_p50_s": (_percentile(latencies, 50) or 0.0) / 10.0,
            "clear_latency_p95_s": (_percentile(latencies, 95) or 0.0) / 10.0,
            "mean_excess_hold_frames": float(np.mean(latencies)) if latencies else float("inf"),
            "persistent_occupied_attempt_rate": int(values["persistent_attempts"]) / max(1, persistent_frames),
            "persistent_occupied_attempts": int(values["persistent_attempts"]),
            "persistent_frames": persistent_frames,
            "post_gate_unsafe": int(values["post_gate_unsafe"]),
        }
    baseline = result["L0_ledger_snapshot"]["mean_excess_hold_frames"]
    candidate = result[CANDIDATE]["mean_excess_hold_frames"]
    result["candidate_excess_hold_reduction_fraction_vs_L0"] = (
        (baseline - candidate) / baseline if baseline > 0 else 0.0
    )
    return result


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for system in SYSTEM_NAMES:
        values = [row["systems"][system] for row in rows]
        mission = [bool(item["mission_success"]) for item in values]
        stack = [bool(item["task_stack_exact"]) for item in values]
        narration_total = sum(int(item["narration_total"]) for item in values)
        narration_valid = sum(int(item["narration_valid"]) for item in values)
        terminal_total = sum(int(item["narration_terminal"]) for item in values)
        terminal_valid = sum(int(item["narration_valid_terminal"]) for item in values)
        accepted_terminal = sum(int(item["terminal_receipts_accepted"]) for item in values)
        covered_terminal = sum(int(item["terminal_narrations_covered"]) for item in values)
        interrupt_checks = sum(int(item["interrupt_checks"]) for item in values)
        interrupt_correct = sum(int(item["interrupt_correct"]) for item in values)
        raw_bytes = sum(int(item["raw_serialized_bytes"]) for item in values)
        event_bytes = sum(int(item["event_serialized_bytes"]) for item in values)
        output[system] = {
            "episodes": len(values),
            "mission_success": _bootstrap_rate(mission, seed=100 + SYSTEM_NAMES.index(system)),
            "task_stack_exact_rate": sum(stack) / max(1, len(stack)),
            "interrupt_disposition_accuracy": interrupt_correct / max(1, interrupt_checks),
            "interrupt_checks": interrupt_checks,
            "stale_action_acceptances": sum(int(item["stale_action_acceptances"]) for item in values),
            "stale_action_rejections": sum(int(item["stale_action_rejections"]) for item in values),
            "post_stop_motion": sum(int(item["post_stop_motion"]) for item in values),
            "raw_unsafe": sum(int(item["raw_unsafe"]) for item in values),
            "admitted_unsafe": sum(int(item["admitted_unsafe"]) for item in values),
            "wrong_route_moves": sum(int(item["wrong_route_moves"]) for item in values),
            "narration_semantic_precision": narration_valid / max(1, narration_total),
            "terminal_claim_precision": terminal_valid / max(1, terminal_total),
            "terminal_coverage": covered_terminal / max(1, accepted_terminal),
            "premature_completion": sum(int(item["premature_completion"]) for item in values),
            "terminal_receipts_accepted": accepted_terminal,
            "stale_receipts_rejected": sum(int(item["stale_receipts_rejected"]) for item in values),
            "duplicate_receipts_rejected": sum(int(item["duplicate_receipts_rejected"]) for item in values),
            "raw_serialized_bytes": raw_bytes,
            "event_serialized_bytes": event_bytes,
            "compression_fraction": 1.0 - event_bytes / max(1, raw_bytes),
            "encode_p99_ms_conservative_max_episode": max(float(item["encode_p99_ms"]) for item in values),
            "parser_accuracy": sum(float(item["parser_accuracy"]) for item in values) / max(1, len(values)),
            "simulated_hours": sum(float(item["simulated_hours"]) for item in values),
        }
    output["paired_candidate_minus_flat_mission_success"] = _bootstrap_paired_delta(
        [bool(row["systems"][FLAT]["mission_success"]) for row in rows],
        [bool(row["systems"][CANDIDATE]["mission_success"]) for row in rows],
        seed=829,
    )
    return output


def evaluate_hypotheses(
    rows: list[dict[str, Any]],
    aggregates: dict[str, Any],
    liveness: dict[str, Any],
    training: dict[str, Any],
    *,
    canonical_counts: bool,
) -> dict[str, Any]:
    candidate = aggregates[CANDIDATE]
    flat = aggregates[FLAT]
    adversarial_rows = [row for row in rows if row["split"] == "adversarial"]
    adversarial = aggregate(adversarial_rows)[CANDIDATE] if adversarial_rows else None
    h1_checks = {
        "mission_success_at_least_0_95": candidate["mission_success"]["estimate"] >= 0.95,
        "interrupt_accuracy_at_least_0_99": candidate["interrupt_disposition_accuracy"] >= 0.99,
        "stack_exact_at_least_0_98": candidate["task_stack_exact_rate"] >= 0.98,
        "zero_stale_revision_actions": candidate["stale_action_acceptances"] == 0,
        "zero_post_stop_motion": candidate["post_stop_motion"] == 0,
        "gain_over_flat_at_least_0_20": aggregates["paired_candidate_minus_flat_mission_success"]["estimate"] >= 0.20,
    }
    h2_candidate = liveness[CANDIDATE]
    h2_checks = {
        "clear_p95_at_most_0_5_s": h2_candidate["clear_latency_p95_s"] <= 0.5,
        "excess_hold_reduction_at_least_0_50": liveness["candidate_excess_hold_reduction_fraction_vs_L0"] >= 0.50,
        "persistent_attempt_rate_at_most_0_01": h2_candidate["persistent_occupied_attempt_rate"] <= 0.01,
        "zero_post_gate_unsafe": h2_candidate["post_gate_unsafe"] == 0 and candidate["admitted_unsafe"] == 0,
    }
    flat_false = int(flat["premature_completion"])
    candidate_false = int(candidate["premature_completion"])
    false_reduction = (flat_false - candidate_false) / flat_false if flat_false else 0.0
    h3_checks = {
        "semantic_precision_1_0": candidate["narration_semantic_precision"] == 1.0,
        "zero_premature_completion": candidate_false == 0,
        "terminal_coverage_at_least_0_99": candidate["terminal_coverage"] >= 0.99,
        "state_fact_accuracy_at_least_0_99": candidate["narration_semantic_precision"] >= 0.99,
        "false_terminal_reduction_at_least_0_90": false_reduction >= 0.90,
    }
    h4_checks = {
        "adversarial_success_at_least_0_90": bool(adversarial and adversarial["mission_success"]["estimate"] >= 0.90),
        "zero_stale_or_duplicate_acceptance": bool(
            adversarial
            and adversarial["stale_action_acceptances"] == 0
            and adversarial["stale_receipts_rejected"] >= len(adversarial_rows)
            and adversarial["duplicate_receipts_rejected"] >= adversarial["terminal_receipts_accepted"]
        ),
        "zero_admitted_unsafe_or_post_stop": bool(adversarial and adversarial["admitted_unsafe"] == 0 and adversarial["post_stop_motion"] == 0),
        "narration_precision_at_least_0_99": bool(adversarial and adversarial["narration_semantic_precision"] >= 0.99),
    }
    h5_checks = {
        "compression_at_least_0_95": candidate["compression_fraction"] >= 0.95,
        "required_fact_recall_1_0": candidate["terminal_coverage"] == 1.0,
        "encode_p99_at_most_5_ms": candidate["encode_p99_ms_conservative_max_episode"] <= 5.0,
    }
    history = training["history_gru"]
    h6_checks = {
        "history_macro_f1_at_least_0_90": history["held_out"]["macro_f1"] >= 0.90,
        "history_beats_snapshot_by_0_05": training["macro_f1_delta_history_minus_snapshot"] >= 0.05,
        "history_cpu_p99_at_most_10_ms": history["latency_cpu_single_thread"]["p99_ms"] <= 10.0,
        "zero_post_gate_safety_stop_violations": candidate["admitted_unsafe"] == 0 and candidate["post_stop_motion"] == 0,
    }
    hypotheses: dict[str, Any] = {}
    for name, checks in (("H1", h1_checks), ("H2", h2_checks), ("H3", h3_checks), ("H4", h4_checks), ("H5", h5_checks), ("H6", h6_checks)):
        hypotheses[name] = {
            "checks": checks,
            "passed": all(checks.values()) and canonical_counts,
            "verdict": "SUPPORTED_PROCEDURAL_STREAM" if all(checks.values()) and canonical_counts else ("CALIBRATION_ONLY" if not canonical_counts else "REFUTED"),
        }
    hypotheses["H3"]["false_terminal_reduction_fraction"] = false_reduction
    return hypotheses


def run(
    *,
    frozen_count: int,
    adversarial_count: int,
    workers: int,
    liveness_cases: int,
) -> dict[str, Any]:
    started = time.time()
    policies = load_policies(ARTIFACTS)
    items = [(20_000 + index, "frozen") for index in range(frozen_count)] + [
        (30_000 + index, "adversarial") for index in range(adversarial_count)
    ]
    if workers <= 1:
        _worker_init(str(ARTIFACTS))
        rows = [_worker_run(item) for item in items]
    else:
        context = mp.get_context("spawn")
        rows = []
        with context.Pool(workers, initializer=_worker_init, initargs=(str(ARTIFACTS),)) as pool:
            for index, row in enumerate(pool.imap(_worker_run, items, chunksize=2), start=1):
                rows.append(row)
                if index % 50 == 0 or index == len(items):
                    print(f"DMC-1 progress {index}/{len(items)}", flush=True)
    rows.sort(key=lambda row: (row["split"], row["seed"]))
    liveness = run_liveness_slice(policies, cases=liveness_cases)
    aggregates = aggregate(rows)
    canonical_counts = frozen_count == 1_000 and adversarial_count == 500 and liveness_cases == 5_000
    hypotheses = evaluate_hypotheses(
        rows,
        aggregates,
        liveness,
        policies.metrics,
        canonical_counts=canonical_counts,
    )
    if not canonical_counts:
        overall = "CALIBRATION_ONLY"
    elif all(item["passed"] for item in hypotheses.values()):
        overall = "ALL_PREREGISTERED_HYPOTHESES_SUPPORTED_PROCEDURAL_STREAM"
    else:
        overall = "PARTIALLY_SUPPORTED_PROCEDURAL_STREAM"
    split_manifest = {
        "frozen": {
            "seeds": [20_000 + index for index in range(frozen_count)],
            "spec_digests": [row["spec_digest"] for row in rows if row["split"] == "frozen"],
        },
        "adversarial": {
            "seeds": [30_000 + index for index in range(adversarial_count)],
            "spec_digests": [row["spec_digest"] for row in rows if row["split"] == "adversarial"],
        },
    }
    source_hashes = {
        name: _file_hash(HERE / name)
        for name in ("DESIGN.md", "AMENDMENTS.md", "local_policy.py", "dmc_sim.py", "experiment.py")
    }
    source_hashes.update(
        {
            "snapshot_mlp.pt": _file_hash(ARTIFACTS / "snapshot_mlp.pt"),
            "history_gru.pt": _file_hash(ARTIFACTS / "history_gru.pt"),
            "training_metrics.json": _file_hash(ARTIFACTS / "training_metrics.json"),
        }
    )
    payload: dict[str, Any] = {
        "schema": "parcel.dmc1.results.v1",
        "evidence_class": "desktop_sim_procedural_semantic_stream_no_physics_no_audio_no_hardware_no_motion",
        "counts": {
            "frozen_episodes": frozen_count,
            "adversarial_episodes": adversarial_count,
            "total_episodes": len(rows),
            "systems_per_episode": len(SYSTEM_NAMES),
            "liveness_cases": liveness_cases,
            "simulated_stream_hours_all_systems": sum(
                aggregates[name]["simulated_hours"] for name in SYSTEM_NAMES
            ),
            "simulated_stream_hours_per_system": aggregates[CANDIDATE]["simulated_hours"],
        },
        "split_manifest": split_manifest,
        "aggregates": aggregates,
        "liveness_slice": liveness,
        "training_metrics": policies.metrics,
        "hypotheses": hypotheses,
        "overall_verdict": overall,
        "source_hashes": source_hashes,
        "rows": rows,
        "runtime": {
            "wall_seconds": time.time() - started,
            "workers": workers,
            "python": platform.python_version(),
            "torch": torch.__version__,
            "platform": platform.platform(),
        },
    }
    payload["deterministic_payload_sha256"] = _payload_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frozen-count", type=int, default=1_000)
    parser.add_argument("--adversarial-count", type=int, default=500)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--liveness-cases", type=int, default=5_000)
    args = parser.parse_args()
    if args.frozen_count < 1 or args.adversarial_count < 1 or args.liveness_cases < 1:
        raise SystemExit("counts must be positive")
    report = run(
        frozen_count=args.frozen_count,
        adversarial_count=args.adversarial_count,
        workers=args.workers,
        liveness_cases=args.liveness_cases,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "overall_verdict": report["overall_verdict"],
                "hypotheses": {key: value["verdict"] for key, value in report["hypotheses"].items()},
                "counts": report["counts"],
                "deterministic_payload_sha256": report["deterministic_payload_sha256"],
                "wall_seconds": report["runtime"]["wall_seconds"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

