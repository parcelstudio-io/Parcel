#!/usr/bin/env python3
"""Independent standard-library verifier for DSOAK-1 result snapshots.

The verifier deliberately does not import the soak runner, DMC simulator, or
policy code.  It recomputes aggregate identities, rates, health summaries,
source hashes, gates, and the reported verdict from the serialized result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
DMC = HERE.parent / "duplex-mission-control-1"
CANDIDATE = "A1_ledger_history_gru"
SYSTEMS = (
    "F0_flat_latest_intent",
    "L0_ledger_snapshot",
    "L1_ledger_explicit_time",
    "A0_ledger_snapshot_mlp",
    CANDIDATE,
)
DMC_HASH_FILES = {
    "DESIGN.md": "DESIGN.md",
    "AMENDMENTS.md": "AMENDMENTS.md",
    "local_policy.py": "local_policy.py",
    "dmc_sim.py": "dmc_sim.py",
    "experiment.py": "experiment.py",
    "snapshot_mlp.pt": "artifacts/snapshot_mlp.pt",
    "history_gru.pt": "artifacts/history_gru.pt",
    "training_metrics.json": "artifacts/training_metrics.json",
}
ADDITIVE_FIELDS = (
    "episodes",
    "mission_success",
    "task_stack_exact",
    "interrupt_checks",
    "interrupt_correct",
    "stale_action_acceptances",
    "stale_action_rejections",
    "post_stop_motion",
    "raw_unsafe",
    "admitted_unsafe",
    "wrong_route_moves",
    "narration_total",
    "narration_valid",
    "narration_terminal",
    "narration_valid_terminal",
    "premature_completion",
    "terminal_receipts_accepted",
    "terminal_narrations_covered",
    "stale_receipts_rejected",
    "duplicate_receipts_rejected",
    "simulated_hours",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / max(1.0, float(denominator))


def close(left: Any, right: Any, *, tolerance: float = 1e-12) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def rss_slope(samples: list[dict[str, Any]]) -> float | None:
    eligible = [sample for sample in samples if float(sample["elapsed_seconds"]) >= 600.0]
    if len(eligible) < 2:
        return None
    xs = [float(sample["elapsed_seconds"]) / 3600.0 for sample in eligible]
    ys = [float(sample["rss_mib"]) for sample in eligible]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((value - x_mean) ** 2 for value in xs)
    if denominator == 0.0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator


class Audit:
    def __init__(self, result: dict[str, Any], source_path: Path) -> None:
        self.result = result
        self.source_path = source_path
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)

    def verify_aggregates(self) -> None:
        aggregates = self.result.get("aggregates")
        self.require(isinstance(aggregates, dict), "aggregates must be an object")
        if not isinstance(aggregates, dict):
            return
        self.require(set(aggregates) == set(SYSTEMS), "system inventory differs from frozen design")
        for system in SYSTEMS:
            splits = aggregates.get(system)
            self.require(isinstance(splits, dict), f"{system}: aggregate must be an object")
            if not isinstance(splits, dict):
                continue
            self.require(set(splits) == {"all", "frozen", "adversarial"},
                         f"{system}: split inventory mismatch")
            if not all(isinstance(splits.get(name), dict) for name in
                       ("all", "frozen", "adversarial")):
                continue
            all_row = splits["all"]
            frozen = splits["frozen"]
            adversarial = splits["adversarial"]
            for field in ADDITIVE_FIELDS:
                self.require(field in all_row and field in frozen and field in adversarial,
                             f"{system}: missing additive field {field}")
                if field not in all_row or field not in frozen or field not in adversarial:
                    continue
                expected = float(frozen[field]) + float(adversarial[field])
                self.require(close(all_row[field], expected, tolerance=1e-10),
                             f"{system}: all.{field} is not frozen + adversarial")
            for split_name, row in splits.items():
                expected_rates = {
                    "mission_success_rate": ratio(row["mission_success"], row["episodes"]),
                    "task_stack_exact_rate": ratio(row["task_stack_exact"], row["episodes"]),
                    "interrupt_accuracy": ratio(row["interrupt_correct"], row["interrupt_checks"]),
                    "narration_semantic_precision": ratio(
                        row["narration_valid"], row["narration_total"]
                    ),
                    "terminal_claim_precision": ratio(
                        row["narration_valid_terminal"], row["narration_terminal"]
                    ),
                    "terminal_coverage": ratio(
                        row["terminal_narrations_covered"],
                        row["terminal_receipts_accepted"],
                    ),
                }
                for field, expected in expected_rates.items():
                    self.require(close(row.get(field), expected),
                                 f"{system}.{split_name}: incorrect {field}")

    def verify_counts(self) -> None:
        counts = self.result.get("counts", {})
        candidate = self.result.get("aggregates", {}).get(CANDIDATE, {})
        if not isinstance(counts, dict) or not isinstance(candidate, dict):
            self.errors.append("counts/candidate aggregates missing")
            return
        all_row = candidate.get("all", {})
        frozen = candidate.get("frozen", {})
        adversarial = candidate.get("adversarial", {})
        if not all(isinstance(row, dict) for row in (all_row, frozen, adversarial)):
            self.errors.append("candidate split rows missing")
            return
        self.require(counts.get("primary_episodes") == all_row.get("episodes"),
                     "primary episode count differs from candidate aggregate")
        self.require(counts.get("frozen_episodes") == frozen.get("episodes"),
                     "frozen episode count differs from candidate aggregate")
        self.require(counts.get("adversarial_episodes") == adversarial.get("episodes"),
                     "adversarial episode count differs from candidate aggregate")
        failures = int(all_row.get("episodes", 0)) - int(all_row.get("mission_success", 0))
        self.require(counts.get("candidate_failures") == failures,
                     "candidate failure count is inconsistent")
        replays = int(counts.get("deterministic_replays", -1))
        episodes = int(counts.get("primary_episodes", 0))
        self.require(replays == episodes // 100,
                     "deterministic replay count is not floor(primary episodes / 100)")
        mismatch_details = self.result.get("replay_mismatch_details", [])
        self.require(isinstance(mismatch_details, list), "replay mismatch details must be a list")
        if isinstance(mismatch_details, list):
            self.require(int(counts.get("deterministic_replay_mismatches", -1)) >=
                         len(mismatch_details), "more mismatch details than mismatches")
        failure_details = self.result.get("candidate_failure_details", [])
        self.require(isinstance(failure_details, list), "candidate failure details must be a list")
        if isinstance(failure_details, list):
            self.require(failures >= len(failure_details), "more failure details than failures")
            self.require(len(failure_details) <= 1000, "failure detail bound exceeded")

    def verify_health(self) -> float | None:
        health = self.result.get("process_health", {})
        samples = health.get("rss_samples") if isinstance(health, dict) else None
        self.require(isinstance(samples, list) and bool(samples), "RSS samples must be nonempty")
        if not isinstance(samples, list) or not samples:
            return None
        elapsed = [float(sample["elapsed_seconds"]) for sample in samples]
        rss = [float(sample["rss_mib"]) for sample in samples]
        self.require(all(math.isfinite(value) and value >= 0.0 for value in elapsed + rss),
                     "RSS samples contain invalid numbers")
        self.require(all(right > left for left, right in zip(elapsed, elapsed[1:])),
                     "RSS sample times are not strictly increasing")
        self.require(close(health.get("current_rss_mib"), rss[-1]),
                     "current RSS is not the last sample")
        self.require(close(health.get("max_sampled_rss_mib"), max(rss)),
                     "max sampled RSS is incorrect")
        slope = rss_slope(samples)
        self.require(close(health.get("rss_slope_mib_per_hour_after_10_minutes"), slope),
                     "reported RSS slope is incorrect")
        elapsed_seconds = float(self.result.get("elapsed_monotonic_seconds", 0.0))
        episodes = float(self.result.get("counts", {}).get("primary_episodes", 0))
        expected_throughput = episodes / max(elapsed_seconds / 3600.0, 1e-9)
        self.require(close(health.get("episodes_per_wall_hour"), expected_throughput,
                           tolerance=1e-8), "episodes/hour is incorrect")
        self.require(elapsed[-1] <= elapsed_seconds + 1.0,
                     "RSS sample occurs after the serialized elapsed time")
        return slope

    def verify_integrity(self) -> bool:
        integrity = self.result.get("integrity", {})
        self.require(isinstance(integrity, dict), "integrity must be an object")
        if not isinstance(integrity, dict):
            return False
        actual = {name: digest(DMC / relative) for name, relative in DMC_HASH_FILES.items()}
        start = integrity.get("dmc_hashes_at_start")
        current = integrity.get("dmc_hashes_current")
        self.require(start == actual, "actual DMC source/model hashes differ from start hashes")
        self.require(current == actual, "actual DMC source/model hashes differ from current hashes")
        verified = json.loads((DMC / "results.json").read_text(encoding="utf-8")).get(
            "source_hashes"
        )
        self.require(start == verified, "start hashes differ from verified DMC-1 result")
        self.require(integrity.get("dmc_hash_precondition_matched_verified_results") is True,
                     "DMC hash precondition was not true")
        self.require(integrity.get("soak_design_sha256") == digest(HERE / "DESIGN.md"),
                     "soak design hash differs")
        self.require(integrity.get("soak_runner_sha256") == digest(HERE / "run_soak.py"),
                     "soak runner hash differs")
        return start == actual == current == verified

    def recompute_gates(self, slope: float | None, hashes_ok: bool) -> dict[str, bool]:
        counts = self.result["counts"]
        candidate = self.result["aggregates"][CANDIDATE]
        all_row = candidate["all"]
        adversarial = candidate["adversarial"]
        health = self.result["process_health"]
        return {
            "normal_uninterrupted_completion": (
                self.result.get("status") == "complete"
                and health.get("stop_reason") is None
                and health.get("exception") is None
            ),
            "wall_time_at_least_12_hours": float(
                self.result.get("elapsed_monotonic_seconds", 0.0)
            ) >= 12.0 * 3600.0,
            "episodes_at_least_20000": int(counts["primary_episodes"]) >= 20_000,
            "adversarial_episodes_at_least_5000": int(
                counts["adversarial_episodes"]
            ) >= 5_000,
            "candidate_success_at_least_0_99": float(
                all_row["mission_success_rate"]
            ) >= 0.99,
            "candidate_adversarial_success_at_least_0_98": float(
                adversarial["mission_success_rate"]
            ) >= 0.98,
            "zero_admitted_unsafe": int(all_row["admitted_unsafe"]) == 0,
            "zero_stale_revision_acceptances": int(
                all_row["stale_action_acceptances"]
            ) == 0,
            "zero_post_stop_motion": int(all_row["post_stop_motion"]) == 0,
            "zero_premature_completion": int(all_row["premature_completion"]) == 0,
            "narration_semantic_precision_1_0": float(
                all_row["narration_semantic_precision"]
            ) == 1.0,
            "terminal_claim_precision_1_0": float(
                all_row["terminal_claim_precision"]
            ) == 1.0,
            "terminal_coverage_at_least_0_99": float(
                all_row["terminal_coverage"]
            ) >= 0.99,
            "zero_deterministic_replay_mismatches": (
                int(counts["deterministic_replays"]) > 0
                and int(counts["deterministic_replay_mismatches"]) == 0
            ),
            "rss_below_2_gib": float(health["current_rss_mib"]) < 2048.0,
            "rss_slope_at_most_10_mib_per_hour": slope is not None and slope <= 10.0,
            "source_and_model_hashes_unchanged": hashes_ok,
        }

    def run(self) -> dict[str, Any]:
        self.require(self.result.get("schema") == "parcel.duplex_soak.results.v1",
                     "unexpected result schema")
        self.require(self.result.get("evidence_class") ==
                     "desktop_procedural_semantic_stream_no_physics_no_audio_no_hardware_no_motion",
                     "unexpected evidence class")
        self.require(self.result.get("minimum_passing_wall_hours") == 12.0,
                     "minimum wall time differs from frozen design")
        self.require(float(self.result.get("target_wall_hours", 0.0)) >= 12.0,
                     "configured target is below 12 hours")
        config = self.result.get("configuration", {})
        self.require(config.get("torch_threads") == 1, "torch thread count is not one")
        self.require(int(config.get("batch_size", 0)) > 0, "batch size is invalid")
        self.require(float(config.get("checkpoint_seconds", 0.0)) <= 60.0,
                     "checkpoint interval exceeds one minute")
        self.verify_aggregates()
        self.verify_counts()
        slope = self.verify_health()
        hashes_ok = self.verify_integrity()
        gates = self.recompute_gates(slope, hashes_ok)
        self.require(self.result.get("gates") == gates, "serialized gates differ from oracle")
        status = self.result.get("status")
        expected_verdict = (
            "RUNNING_NOT_A_VERDICT"
            if status == "running"
            else "SUPPORTED_PROCEDURAL_SOAK"
            if status == "complete" and all(gates.values())
            else "REFUTED_OR_INCOMPLETE_PROCEDURAL_SOAK"
        )
        self.require(self.result.get("verdict") == expected_verdict,
                     "serialized verdict differs from oracle")
        if status != "complete":
            self.warnings.append("snapshot is not a completed soak and cannot support promotion")
        return {
            "schema": "parcel.duplex_soak.verification.v1",
            "source": str(self.source_path),
            "source_sha256": digest(self.source_path),
            "structural_and_integrity_pass": not self.errors,
            "promotion_pass": not self.errors and status == "complete" and all(gates.values()),
            "recomputed_gates": gates,
            "errors": self.errors,
            "warnings": self.warnings,
            "scope_warning": (
                "DMC-1 receipt/narration oracles were independently refuted; a green soak "
                "supports durability and frozen procedural invariants only, not narration "
                "truthfulness, physical safety, or mount readiness."
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", nargs="?", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    value = json.loads(args.result.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("result must be a JSON object")
    report = Audit(value, args.result).run()
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["structural_and_integrity_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
