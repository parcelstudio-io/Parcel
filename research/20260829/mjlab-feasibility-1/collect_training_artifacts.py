#!/usr/bin/env python3
"""Verify and retain the bounded MJLAB-1 PPO smoke-run artifacts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import torch


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, object]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def find_scalar(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}:\s*(.+?)\s*$", text)
    if not match:
        raise ValueError(f"missing scalar {key}")
    return match.group(1)


def parse_gnu_time(text: str) -> dict[str, object]:
    fields: dict[str, object] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if ": " not in stripped:
            continue
        key, value = stripped.rsplit(": ", 1)
        fields[key] = value
    elapsed = str(fields.get("Elapsed (wall clock) time (h:mm:ss or m:ss)", ""))
    parts = [float(part) for part in elapsed.split(":") if part]
    if len(parts) == 2:
        elapsed_seconds = parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        elapsed_seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
    else:
        elapsed_seconds = None
    rss_kib = int(str(fields["Maximum resident set size (kbytes)"]))
    return {
        "elapsed_wall_seconds": elapsed_seconds,
        "maximum_resident_set_kib": rss_kib,
        "maximum_resident_set_gib": rss_kib / (1024 * 1024),
        "exit_status": int(str(fields["Exit status"])),
        "raw_fields": fields,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--training-log", type=Path, required=True)
    parser.add_argument("--time-log", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    run_dir = args.run_dir.resolve()
    training_log = args.training_log.resolve()
    time_log = args.time_log.resolve()
    out_dir = args.out_dir.resolve()
    retained_dir = out_dir / "artifacts"
    retained_dir.mkdir(parents=True, exist_ok=True)

    agent_yaml = run_dir / "params" / "agent.yaml"
    env_yaml = run_dir / "params" / "env.yaml"
    checkpoints = sorted(run_dir.glob("model_*.pt"))
    if not checkpoints:
        raise FileNotFoundError("no native checkpoints")
    final_checkpoint = checkpoints[-1]
    policy = run_dir / "policy.onnx"
    required = [agent_yaml, env_yaml, final_checkpoint, policy, training_log, time_log]
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"missing or empty artifact: {path}")

    retained_sources = {
        "model_2.pt": final_checkpoint,
        "policy.onnx": policy,
        "agent.yaml": agent_yaml,
        "env.yaml": env_yaml,
    }
    retained = {}
    for name, original in retained_sources.items():
        destination = retained_dir / name
        shutil.copy2(original, destination)
        retained[name] = {
            "original": file_record(original),
            "retained": file_record(destination),
            "hash_match": sha256(original) == sha256(destination),
        }

    checkpoint = torch.load(final_checkpoint, map_location="cpu", weights_only=False)
    if not isinstance(checkpoint, dict):
        raise TypeError("checkpoint is not a dict")
    agent_text = agent_yaml.read_text(encoding="utf-8")
    env_text = env_yaml.read_text(encoding="utf-8")
    log_text = training_log.read_text(encoding="utf-8")
    requested = {
        "num_envs": int(find_scalar(env_text, "num_envs")),
        "seed": int(find_scalar(agent_text, "seed")),
        "num_steps_per_env": int(find_scalar(agent_text, "num_steps_per_env")),
        "max_iterations": int(find_scalar(agent_text, "max_iterations")),
        "save_interval": int(find_scalar(agent_text, "save_interval")),
    }
    expected_samples = (
        requested["num_envs"]
        * requested["num_steps_per_env"]
        * requested["max_iterations"]
    )
    observed_total_steps = [int(value) for value in re.findall(r"Total steps:\s+(\d+)", log_text)]
    iterations = [int(value) for value in re.findall(r"Learning iteration (\d+)/3", log_text)]
    time_record = parse_gnu_time(time_log.read_text(encoding="utf-8"))
    tracked_diff = subprocess.run(
        ["git", "diff", "--quiet"], cwd=source, check=False
    ).returncode
    gates = {
        "upstream_command_exit_pass": time_record["exit_status"] == 0,
        "num_envs_pass": requested["num_envs"] == 64,
        "seed_pass": requested["seed"] == 42,
        "iterations_pass": requested["max_iterations"] == 3 and iterations == [0, 1, 2],
        "rollout_steps_pass": requested["num_steps_per_env"] == 24,
        "checkpoint_interval_pass": requested["save_interval"] == 1,
        "total_steps_pass": observed_total_steps and observed_total_steps[-1] == expected_samples,
        "native_checkpoint_pass": (
            final_checkpoint.stat().st_size > 0
            and int(checkpoint.get("iter", -1)) == 2
            and "actor_state_dict" in checkpoint
            and "critic_state_dict" in checkpoint
            and "optimizer_state_dict" in checkpoint
        ),
        "configuration_files_pass": agent_yaml.stat().st_size > 0 and env_yaml.stat().st_size > 0,
        "retained_hashes_pass": all(item["hash_match"] for item in retained.values()),
        "upstream_tracked_source_unchanged": tracked_diff == 0,
    }
    record = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "MJLAB-1",
        "hypothesis": "MJF-H3",
        "source": {
            "path": str(source),
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source, text=True
            ).strip(),
            "tracked_diff_empty": tracked_diff == 0,
            "status_porcelain": subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=source, text=True
            ),
            "collector_sha256": sha256(Path(__file__).resolve()),
        },
        "command": [
            "scripts/train.py",
            "Unitree-Go2-Flat",
            "--env.scene.num-envs=64",
            "--agent.max-iterations=3",
            "--agent.save-interval=1",
            "--agent.seed=42",
            "--agent.run-name=mjlab1-h3-pinned",
        ],
        "operational_environment": {
            "CUDA_VISIBLE_DEVICES": "0",
            "MUJOCO_GL": "egl",
            "WANDB_MODE": "offline",
        },
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "unitree_rl_mjlab",
                "mjlab",
                "mujoco-warp",
                "mujoco",
                "warp-lang",
                "scipy",
                "wandb",
                "torch",
                "rsl-rl-lib",
            )
        },
        "configuration": requested,
        "expected_environment_steps": expected_samples,
        "observed_total_steps_by_iteration": observed_total_steps,
        "observed_iteration_indices": iterations,
        "checkpoint": {
            "original": file_record(final_checkpoint),
            "checkpoint_iteration_index": checkpoint.get("iter"),
            "top_level_keys": sorted(checkpoint),
        },
        "all_native_checkpoints": [file_record(path) for path in checkpoints],
        "retained_artifacts": retained,
        "training_log": file_record(training_log),
        "time_log": file_record(time_log),
        "resource_usage": time_record,
        "gates": gates,
        "h3_supported": all(gates.values()),
        "interpretation": (
            "Three iterations demonstrate only that rollout, optimization, logging, native "
            "checkpointing, and ONNX export execute. They do not demonstrate reward improvement "
            "or a usable locomotion policy."
        ),
    }
    result = out_dir / "training-result.json"
    result.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(result), "h3_supported": record["h3_supported"]}))
    return 0 if record["h3_supported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
