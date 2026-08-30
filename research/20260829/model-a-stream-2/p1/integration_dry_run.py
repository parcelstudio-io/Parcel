"""Exercise the frozen P1 evaluator/verifier without running an optimizer.

This is a non-evidentiary orchestration test. It rebinds copied checkpoint
weights to the current manifest and replaces one challenger with an explicit
zero-output dummy so that the expected terminal result is P1_REFUTED.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import torch
from common import (
    CHECKPOINT_DIR,
    LEARNED_SEEDS,
    P1_DIR,
    TEST_SPLITS,
    atomic_json,
    file_sha256,
    load_json,
)
from model import load_checkpoint, parameter_count, save_checkpoint

PYTHON = Path.home() / ".cache/parcel-0e/venv/bin/python"


def call(script: str, *arguments: str) -> None:
    environment = dict(os.environ)
    environment.pop("TMPDIR", None)
    environment["PYTHONHASHSEED"] = "0"
    environment["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    subprocess.run(
        [str(PYTHON), str(P1_DIR / script), *arguments],
        cwd=P1_DIR.parents[3],
        env=environment,
        check=True,
    )


def stage_checkpoints(source: Path, manifest_sha: str) -> list[dict[str, Any]]:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=False)
    runs: list[dict[str, Any]] = []
    for arm in ("S", "C16"):
        for seed in LEARNED_SEEDS:
            old_path = source / f"{arm}-seed-{seed}.p1ckpt"
            model, _header, mean, std = load_checkpoint(old_path, torch.device("cpu"))
            deliberately_zeroed = arm == "C16" and seed == LEARNED_SEEDS[-1]
            if deliberately_zeroed:
                for parameter in model.parameters():
                    parameter.data.zero_()
            new_path = CHECKPOINT_DIR / old_path.name
            checkpoint_sha = save_checkpoint(
                new_path,
                model=model,
                metadata={
                    "schema_version": 1,
                    "experiment": "MA-2-P1-INTEGRATION-DRY-RUN",
                    "arm": arm,
                    "seed": seed,
                    "best_step": 0,
                    "manifest_sha256": manifest_sha,
                    "parameter_count": parameter_count(model),
                    "normalization": "copied-no-optimizer-dry-run",
                    "deliberately_zeroed": deliberately_zeroed,
                },
                mean=mean,
                std=std,
            )
            runs.append(
                {
                    "arm": arm,
                    "seed": seed,
                    "repeat": False,
                    "checkpoint": str(new_path.relative_to(P1_DIR)),
                    "checkpoint_sha256": checkpoint_sha,
                    "parameter_count": parameter_count(model),
                    "best_step": 0,
                    "dev": {},
                    "steps_run": 0,
                    "training_seconds": 0.0,
                    "peak_vram_bytes": 0,
                    "log_sha256": "NO_OPTIMIZER",
                    "log": [],
                    "deliberately_zeroed": deliberately_zeroed,
                }
            )
        primary = next(
            row for row in runs if row["arm"] == arm and row["seed"] == LEARNED_SEEDS[0]
        )
        repeat_path = CHECKPOINT_DIR / f"{arm}-seed-{LEARNED_SEEDS[0]}-repeat.p1ckpt"
        shutil.copyfile(P1_DIR / primary["checkpoint"], repeat_path)
        runs.append(
            {
                **primary,
                "repeat": True,
                "checkpoint": str(repeat_path.relative_to(P1_DIR)),
            }
        )
    return runs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-checkpoints", type=Path, required=True)
    args = parser.parse_args()
    manifest_sha = file_sha256(args.manifest)
    runs = stage_checkpoints(args.source_checkpoints, manifest_sha)
    deterministic = {}
    for arm in ("S", "C16"):
        primary = next(row for row in runs if row["arm"] == arm and not row["repeat"])
        repeat = next(row for row in runs if row["arm"] == arm and row["repeat"])
        deterministic[arm] = {
            "checkpoint_byte_identical": file_sha256(P1_DIR / primary["checkpoint"])
            == file_sha256(P1_DIR / repeat["checkpoint"]),
            "checkpoint_sha256": primary["checkpoint_sha256"],
            "repeat_sha256": repeat["checkpoint_sha256"],
            "normalized_log_identical": True,
        }
    training = {
        "schema_version": 1,
        "experiment": "MA-2-P1-INTEGRATION-DRY-RUN",
        "mode": "NO_OPTIMIZER_INTEGRATION_DRY_RUN",
        "optimizer_steps_run": 0,
        "manifest_sha256": manifest_sha,
        "device": "checkpoint-construction-cpu/evaluation-normal-devices",
        "runs": runs,
        "deterministic_repeats": deterministic,
        "access_audit": {
            "opened_paths_sha256": "NON_TRAINING_DRY_RUN",
            "opened_path_count": 0,
            "held_shard_reads": [],
            "pass": True,
        },
        "all_pre_eval_gates": all(
            row["checkpoint_byte_identical"] and row["normalized_log_identical"]
            for row in deterministic.values()
        ),
    }
    training_path = P1_DIR / "dryrun-training.json"
    results_path = P1_DIR / "dryrun-results.json"
    verification_path = P1_DIR / "dryrun-verification.json"
    tamper_path = P1_DIR / "dryrun-tamper.json"
    atomic_json(training_path, training)
    call(
        "evaluate.py",
        "--manifest",
        str(args.manifest),
        "--training",
        str(training_path),
        "--output",
        str(results_path),
    )
    call(
        "verify.py",
        "--manifest",
        str(args.manifest),
        "--training",
        str(training_path),
        "--results",
        str(results_path),
        "--output",
        str(verification_path),
        "--tamper-output",
        str(tamper_path),
    )
    results = load_json(results_path)
    verification = load_json(verification_path)
    expected_streams = {
        (arm, seed, split)
        for arm, seeds in {
            "T*": (None,),
            "R": (None,),
            "DIRECT": (None,),
            "IDLE": (None,),
            "S": LEARNED_SEEDS,
            "C16": LEARNED_SEEDS,
        }.items()
        for seed in seeds
        for split in TEST_SPLITS
    }
    observed_streams = {
        (row["arm"], row["seed"], row["split"]) for row in results["trace_inventory"]
    }
    checks = {
        "optimizer_steps_zero": training["optimizer_steps_run"] == 0,
        "all_arm_seed_split_paths": observed_streams == expected_streams,
        "closed_loop_traces_1980": len(results["trace_inventory"]) == 1980,
        "open_loop_traces_42": len(results["open_loop_trace_inventory"]) == 42,
        "latency_samples_120000": sum(
            row["samples"] for row in results["latency"].values()
        )
        == 120_000,
        "expected_quality_failure": results["verdict"] == "P1_REFUTED",
        "independent_verifier_pass": verification["status"] == "PASS",
        "tamper_5_of_5": load_json(tamper_path)["rejected"] == 5,
    }
    report = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "mode": "NON_EVIDENTIARY_NO_OPTIMIZER_INTEGRATION_DRY_RUN",
        "harness_sha256": file_sha256(Path(__file__)),
        "manifest_sha256": manifest_sha,
        "checks": checks,
        "observed_verdict": results["verdict"],
        "hypotheses": results["hypotheses"],
    }
    atomic_json(P1_DIR / "dryrun-report.json", report)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
