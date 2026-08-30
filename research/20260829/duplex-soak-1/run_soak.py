#!/usr/bin/env python3
"""Long-duration, isolated stability soak for the DMC-1 research simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch


HERE = Path(__file__).resolve().parent
DMC = HERE.parent / "duplex-mission-control-1"
sys.path.insert(0, str(DMC))

from dmc_sim import generate_spec, run_episode  # noqa: E402
from local_policy import load_policies  # noqa: E402


SCHEMA = "parcel.duplex_soak.results.v1"
CANDIDATE = "A1_ledger_history_gru"
SYSTEMS = (
    "F0_flat_latest_intent",
    "L0_ledger_snapshot",
    "L1_ledger_explicit_time",
    "A0_ledger_snapshot_mlp",
    CANDIDATE,
)
MIN_WALL_HOURS = 12.0
MIN_EPISODES = 20_000
MIN_ADVERSARIAL = 5_000
MAX_FAILURE_DETAILS = 1_000
MAX_REPLAY_MISMATCH_DETAILS = 100
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dmc_hashes() -> dict[str, str]:
    return {name: sha256_file(DMC / relative) for name, relative in DMC_HASH_FILES.items()}


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def semantic_projection(value: object) -> object:
    """Remove only measured wall-time fields before deterministic replay."""
    if isinstance(value, dict):
        return {
            key: semantic_projection(item)
            for key, item in value.items()
            if key != "encode_p99_ms"
        }
    if isinstance(value, list):
        return [semantic_projection(item) for item in value]
    return value


def current_rss_mib() -> float:
    status = Path("/proc/self/status").read_text(encoding="utf-8")
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    raise RuntimeError("VmRSS not found in /proc/self/status")


def counter() -> dict[str, int | float]:
    return {
        "episodes": 0,
        "mission_success": 0,
        "task_stack_exact": 0,
        "interrupt_checks": 0,
        "interrupt_correct": 0,
        "stale_action_acceptances": 0,
        "stale_action_rejections": 0,
        "post_stop_motion": 0,
        "raw_unsafe": 0,
        "admitted_unsafe": 0,
        "wrong_route_moves": 0,
        "narration_total": 0,
        "narration_valid": 0,
        "narration_terminal": 0,
        "narration_valid_terminal": 0,
        "premature_completion": 0,
        "terminal_receipts_accepted": 0,
        "terminal_narrations_covered": 0,
        "stale_receipts_rejected": 0,
        "duplicate_receipts_rejected": 0,
        "simulated_hours": 0.0,
    }


COUNT_FIELDS = tuple(counter())


def update_counter(target: dict[str, int | float], outcome: dict[str, Any]) -> None:
    target["episodes"] += 1
    target["mission_success"] += int(bool(outcome["mission_success"]))
    target["task_stack_exact"] += int(bool(outcome["task_stack_exact"]))
    for name in COUNT_FIELDS:
        if name in {"episodes", "mission_success", "task_stack_exact"}:
            continue
        target[name] += outcome[name]


def rate(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / max(1.0, float(denominator))


def render_counter(raw: dict[str, int | float]) -> dict[str, Any]:
    result = dict(raw)
    result.update(
        {
            "mission_success_rate": rate(raw["mission_success"], raw["episodes"]),
            "task_stack_exact_rate": rate(raw["task_stack_exact"], raw["episodes"]),
            "interrupt_accuracy": rate(raw["interrupt_correct"], raw["interrupt_checks"]),
            "narration_semantic_precision": rate(raw["narration_valid"], raw["narration_total"]),
            "terminal_claim_precision": rate(
                raw["narration_valid_terminal"], raw["narration_terminal"]
            ),
            "terminal_coverage": rate(
                raw["terminal_narrations_covered"], raw["terminal_receipts_accepted"]
            ),
        }
    )
    return result


def rss_slope_mib_per_hour(samples: list[dict[str, float]]) -> float | None:
    eligible = [sample for sample in samples if sample["elapsed_seconds"] >= 600.0]
    if len(eligible) < 2:
        return None
    xs = [sample["elapsed_seconds"] / 3600.0 for sample in eligible]
    ys = [sample["rss_mib"] for sample in eligible]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((value - x_mean) ** 2 for value in xs)
    if denominator == 0.0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class Soak:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.started_utc = utc_now()
        self.started_monotonic = time.monotonic()
        self.hashes_start = dmc_hashes()
        self.expected_hashes = json.loads((DMC / "results.json").read_text(encoding="utf-8"))[
            "source_hashes"
        ]
        self.hash_precondition = self.hashes_start == self.expected_hashes
        if not self.hash_precondition:
            raise RuntimeError("DMC-1 source/model hashes differ from verified results.json")
        torch.set_num_threads(1)
        self.policies = load_policies(DMC / "artifacts")
        self.counts = {
            system: {
                "all": counter(),
                "frozen": counter(),
                "adversarial": counter(),
            }
            for system in SYSTEMS
        }
        self.seeds_used = {"frozen": 0, "adversarial": 0}
        self.failures_total = 0
        self.failure_details: list[dict[str, Any]] = []
        self.replays_run = 0
        self.replay_mismatches = 0
        self.replay_mismatch_details: list[dict[str, Any]] = []
        self.rss_samples: list[dict[str, float]] = []
        self.stop_reason: str | None = None
        self.exception: str | None = None
        self.last_checkpoint = self.started_monotonic
        self.last_progress = self.started_monotonic
        self.completed_normally = False

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_monotonic

    @property
    def total_episodes(self) -> int:
        return self.seeds_used["frozen"] + self.seeds_used["adversarial"]

    def next_item(self) -> tuple[int, str]:
        batch_index = self.total_episodes // self.args.batch_size
        split = "frozen" if batch_index % 2 == 0 else "adversarial"
        base = 1_000_000 if split == "frozen" else 2_000_000
        return base + self.seeds_used[split], split

    def consume(self, row: dict[str, Any]) -> None:
        split = str(row["split"])
        for system in SYSTEMS:
            outcome = row["systems"][system]
            update_counter(self.counts[system]["all"], outcome)
            update_counter(self.counts[system][split], outcome)
        candidate = row["systems"][CANDIDATE]
        if not candidate["mission_success"]:
            self.failures_total += 1
            if len(self.failure_details) < MAX_FAILURE_DETAILS:
                self.failure_details.append(
                    {
                        "seed": row["seed"],
                        "split": split,
                        "spec_digest": row["spec_digest"],
                        "task_status": candidate["task_status"],
                        "position": candidate["position"],
                        "wrong_route_moves": candidate["wrong_route_moves"],
                        "raw_unsafe": candidate["raw_unsafe"],
                    }
                )

    def replay(self, row: dict[str, Any]) -> None:
        repeated = run_episode(generate_spec(int(row["seed"]), str(row["split"])), self.policies)
        first_digest = canonical_digest(semantic_projection(row))
        repeated_digest = canonical_digest(semantic_projection(repeated))
        self.replays_run += 1
        if first_digest != repeated_digest:
            self.replay_mismatches += 1
            if len(self.replay_mismatch_details) < MAX_REPLAY_MISMATCH_DETAILS:
                self.replay_mismatch_details.append(
                    {
                        "seed": row["seed"],
                        "split": row["split"],
                        "first": first_digest,
                        "repeated": repeated_digest,
                    }
                )

    def sample_rss(self) -> None:
        sample = {"elapsed_seconds": self.elapsed, "rss_mib": current_rss_mib()}
        if not self.rss_samples or sample["elapsed_seconds"] - self.rss_samples[-1]["elapsed_seconds"] >= 30.0:
            self.rss_samples.append(sample)

    def gates(self, *, final: bool) -> dict[str, bool]:
        candidate_all = render_counter(self.counts[CANDIDATE]["all"])
        candidate_adversarial = render_counter(self.counts[CANDIDATE]["adversarial"])
        slope = rss_slope_mib_per_hour(self.rss_samples)
        hashes_unchanged = dmc_hashes() == self.hashes_start
        rss = self.rss_samples[-1]["rss_mib"] if self.rss_samples else current_rss_mib()
        return {
            "normal_uninterrupted_completion": final and self.completed_normally,
            "wall_time_at_least_12_hours": self.elapsed >= MIN_WALL_HOURS * 3600.0,
            "episodes_at_least_20000": self.total_episodes >= MIN_EPISODES,
            "adversarial_episodes_at_least_5000": self.seeds_used["adversarial"] >= MIN_ADVERSARIAL,
            "candidate_success_at_least_0_99": candidate_all["mission_success_rate"] >= 0.99,
            "candidate_adversarial_success_at_least_0_98": candidate_adversarial[
                "mission_success_rate"
            ]
            >= 0.98,
            "zero_admitted_unsafe": candidate_all["admitted_unsafe"] == 0,
            "zero_stale_revision_acceptances": candidate_all["stale_action_acceptances"] == 0,
            "zero_post_stop_motion": candidate_all["post_stop_motion"] == 0,
            "zero_premature_completion": candidate_all["premature_completion"] == 0,
            "narration_semantic_precision_1_0": candidate_all[
                "narration_semantic_precision"
            ]
            == 1.0,
            "terminal_claim_precision_1_0": candidate_all["terminal_claim_precision"] == 1.0,
            "terminal_coverage_at_least_0_99": candidate_all["terminal_coverage"] >= 0.99,
            "zero_deterministic_replay_mismatches": self.replays_run > 0
            and self.replay_mismatches == 0,
            "rss_below_2_gib": rss < 2048.0,
            "rss_slope_at_most_10_mib_per_hour": slope is not None and slope <= 10.0,
            "source_and_model_hashes_unchanged": hashes_unchanged,
        }

    def payload(self, *, status: str, final: bool) -> dict[str, Any]:
        self.sample_rss()
        slope = rss_slope_mib_per_hour(self.rss_samples)
        gates = self.gates(final=final)
        if not final:
            verdict = "RUNNING_NOT_A_VERDICT"
        elif all(gates.values()):
            verdict = "SUPPORTED_PROCEDURAL_SOAK"
        else:
            verdict = "REFUTED_OR_INCOMPLETE_PROCEDURAL_SOAK"
        rendered = {
            system: {split: render_counter(values) for split, values in splits.items()}
            for system, splits in self.counts.items()
        }
        return {
            "schema": SCHEMA,
            "evidence_class": "desktop_procedural_semantic_stream_no_physics_no_audio_no_hardware_no_motion",
            "status": status,
            "verdict": verdict,
            "started_utc": self.started_utc,
            "updated_utc": utc_now(),
            "elapsed_monotonic_seconds": self.elapsed,
            "target_wall_hours": self.args.hours,
            "minimum_passing_wall_hours": MIN_WALL_HOURS,
            "configuration": {
                "batch_size": self.args.batch_size,
                "checkpoint_seconds": self.args.checkpoint_seconds,
                "torch_threads": torch.get_num_threads(),
                "process_id": os.getpid(),
            },
            "counts": {
                "primary_episodes": self.total_episodes,
                "frozen_episodes": self.seeds_used["frozen"],
                "adversarial_episodes": self.seeds_used["adversarial"],
                "deterministic_replays": self.replays_run,
                "deterministic_replay_mismatches": self.replay_mismatches,
                "candidate_failures": self.failures_total,
            },
            "aggregates": rendered,
            "candidate_failure_details": self.failure_details,
            "candidate_failure_details_truncated": self.failures_total > len(self.failure_details),
            "replay_mismatch_details": self.replay_mismatch_details,
            "process_health": {
                "current_rss_mib": self.rss_samples[-1]["rss_mib"],
                "max_sampled_rss_mib": max(sample["rss_mib"] for sample in self.rss_samples),
                "rss_slope_mib_per_hour_after_10_minutes": slope,
                "rss_samples": self.rss_samples,
                "episodes_per_wall_hour": self.total_episodes / max(self.elapsed / 3600.0, 1e-9),
                "stop_reason": self.stop_reason,
                "exception": self.exception,
            },
            "integrity": {
                "dmc_hash_precondition_matched_verified_results": self.hash_precondition,
                "dmc_hashes_at_start": self.hashes_start,
                "dmc_hashes_current": dmc_hashes(),
                "soak_design_sha256": sha256_file(HERE / "DESIGN.md"),
                "soak_runner_sha256": sha256_file(HERE / "run_soak.py"),
            },
            "gates": gates,
        }

    def checkpoint(self, *, status: str = "running", final: bool = False) -> None:
        atomic_write(self.args.out, self.payload(status=status, final=final))
        self.last_checkpoint = time.monotonic()
        candidate = self.counts[CANDIDATE]["all"]
        print(
            json.dumps(
                {
                    "status": status,
                    "elapsed_hours": round(self.elapsed / 3600.0, 4),
                    "episodes": self.total_episodes,
                    "adversarial": self.seeds_used["adversarial"],
                    "candidate_success": rate(candidate["mission_success"], candidate["episodes"]),
                    "admitted_unsafe": candidate["admitted_unsafe"],
                    "premature_completion": candidate["premature_completion"],
                    "replay_mismatches": self.replay_mismatches,
                    "rss_mib": round(self.rss_samples[-1]["rss_mib"], 1),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    def run(self) -> int:
        target_seconds = self.args.hours * 3600.0
        self.sample_rss()
        self.checkpoint()
        while self.elapsed < target_seconds and self.stop_reason is None:
            seed, split = self.next_item()
            row = run_episode(generate_spec(seed, split), self.policies)
            self.consume(row)
            self.seeds_used[split] += 1
            if self.total_episodes % 100 == 0:
                self.replay(row)
            if time.monotonic() - self.last_checkpoint >= self.args.checkpoint_seconds:
                self.checkpoint()
        self.completed_normally = self.stop_reason is None and self.elapsed >= target_seconds
        status = "complete" if self.completed_normally else "interrupted"
        self.checkpoint(status=status, final=True)
        return 0 if self.completed_normally else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--hours", type=float, default=12.05)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--checkpoint-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if args.hours <= 0.0 or args.batch_size <= 0 or args.checkpoint_seconds <= 0.0:
        raise SystemExit("hours, batch size, and checkpoint interval must be positive")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    soak: Soak | None = None

    def request_stop(signum: int, _frame: object) -> None:
        if soak is not None:
            soak.stop_reason = f"signal_{signum}"

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        soak = Soak(args)
        return soak.run()
    except BaseException as exc:
        if soak is not None:
            soak.exception = f"{type(exc).__name__}: {exc}"
            soak.stop_reason = soak.stop_reason or "exception"
            try:
                soak.checkpoint(status="error", final=True)
            except BaseException:
                pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
