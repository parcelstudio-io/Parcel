"""Fit the frozen P1 snapshot and causal challengers on train/dev shards only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from common import (
    CHECKPOINT_DIR,
    LEARNED_SEEDS,
    LOG_DIR,
    P1_DIR,
    REPO,
    atomic_json,
    canonical_bytes,
    file_sha256,
    load_json,
)
from features import BASE_DIM
from model import build_model, parameter_count, save_checkpoint
from torch.nn import functional


def install_access_audit() -> list[str]:
    opened: list[str] = []

    def hook(event: str, args: tuple[object, ...]) -> None:
        if event == "open" and args and isinstance(args[0], (str, bytes)):
            raw = os.fsdecode(args[0])
            try:
                opened.append(str(Path(raw).resolve()))
            except OSError:
                opened.append(raw)

    sys.addaudithook(hook)
    return opened


def verify_frozen_sources(manifest: dict[str, Any]) -> None:
    for relative, expected in manifest["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or file_sha256(path) != expected:
            raise SystemExit(f"frozen P1 source mismatch: {relative}")


def load_shard(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as values:
        return {name: values[name].copy() for name in ("current", "sequence", "label")}


def normalize(
    train: dict[str, np.ndarray], dev: dict[str, np.ndarray]
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], np.ndarray, np.ndarray]:
    mean = train["current"].mean(axis=0, dtype=np.float64).astype(np.float32)
    std = train["current"].std(axis=0, dtype=np.float64).astype(np.float32)
    std = np.maximum(std, 1.0e-4)

    def transform(shard: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        current = ((shard["current"] - mean) / std).astype(np.float32)
        sequence = shard["sequence"].copy().astype(np.float32)
        valid = sequence[:, :, BASE_DIM : BASE_DIM + 1]
        sequence[:, :, :BASE_DIM] = ((sequence[:, :, :BASE_DIM] - mean) / std) * valid
        return {"current": current, "sequence": sequence, "label": shard["label"]}

    return transform(train), transform(dev), mean, std


def metrics(
    command: torch.Tensor, stop_logit: torch.Tensor, label: torch.Tensor
) -> dict[str, float]:
    stopped = torch.linalg.vector_norm(label[:, :2], dim=1) <= 0.03
    prediction = command.clone()
    prediction[torch.sigmoid(stop_logit) >= 0.5] = 0.0
    error = prediction - label
    predicted_stop = torch.linalg.vector_norm(prediction[:, :2], dim=1) <= 0.03
    tp = int(torch.logical_and(predicted_stop, stopped).sum())
    fp = int(torch.logical_and(predicted_stop, ~stopped).sum())
    fn = int(torch.logical_and(~predicted_stop, stopped).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    stop_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    moving = torch.linalg.vector_norm(label[:, :2], dim=1) > 0.03
    direction_hits = torch.sum(torch.sum(prediction[:, :2] * label[:, :2], dim=1)[moving] > 0)
    return {
        "mse": float(torch.mean(error * error)),
        "mae": float(torch.mean(torch.abs(error))),
        "stop_precision": precision,
        "stop_recall": recall,
        "stop_f1": stop_f1,
        "direction_agreement": float(direction_hits / moving.sum()) if moving.any() else 0.0,
    }


def train_one(
    *,
    arm: str,
    seed: int,
    repeat: bool,
    train: dict[str, np.ndarray],
    dev: dict[str, np.ndarray],
    mean: np.ndarray,
    std: np.ndarray,
    manifest_sha256: str,
    config: dict[str, Any],
    device: torch.device,
) -> dict[str, Any]:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    model = build_model(arm).to(device)
    count = parameter_count(model)
    if count >= (100_000 if arm == "S" else 250_000):
        raise RuntimeError(f"{arm} parameter budget exceeded: {count}")
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config["learning_rate"]),
        weight_decay=float(config["weight_decay"]),
    )
    train_x = torch.from_numpy(train["current"] if arm == "S" else train["sequence"]).to(device)
    train_y = torch.from_numpy(train["label"]).to(device)
    dev_x = torch.from_numpy(dev["current"] if arm == "S" else dev["sequence"]).to(device)
    dev_y = torch.from_numpy(dev["label"]).to(device)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    best_mse = float("inf")
    best_step = 0
    best_state: dict[str, torch.Tensor] | None = None
    log_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    for step in range(1, int(config["max_steps"]) + 1):
        indices = torch.randint(
            0,
            len(train_y),
            (int(config["batch_size"]),),
            generator=generator,
        ).to(device)
        command, stop_logit = model(train_x[indices])
        labels = train_y[indices]
        stop_target = (torch.linalg.vector_norm(labels[:, :2], dim=1) <= 0.03).float()
        loss = functional.smooth_l1_loss(command, labels) + float(
            config["stop_bce_weight"]
        ) * functional.binary_cross_entropy_with_logits(stop_logit, stop_target)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), float(config["gradient_norm"]))
        optimizer.step()
        if step % int(config["eval_every"]) == 0:
            model.eval()
            with torch.inference_mode():
                dev_command, dev_stop = model(dev_x)
                dev_metrics = metrics(dev_command, dev_stop, dev_y)
            model.train()
            row = {"step": step, "train_loss": float(loss.detach()), "dev": dev_metrics}
            log_rows.append(row)
            if dev_metrics["mse"] < best_mse - 1.0e-12:
                best_mse = dev_metrics["mse"]
                best_step = step
                best_state = {
                    name: value.detach().cpu().clone() for name, value in model.state_dict().items()
                }
            elif step - best_step >= int(config["patience_steps"]):
                break
    if best_state is None:
        raise RuntimeError("no P1 checkpoint selected")
    model.load_state_dict(best_state)
    model.eval()
    with torch.inference_mode():
        dev_command, dev_stop = model(dev_x)
        final_dev = metrics(dev_command, dev_stop, dev_y)
    suffix = "-repeat" if repeat else ""
    path = CHECKPOINT_DIR / f"{arm}-seed-{seed}{suffix}.p1ckpt"
    checkpoint_sha = save_checkpoint(
        path,
        model=model,
        metadata={
            "schema_version": 1,
            "experiment": "MA-2-P1",
            "arm": arm,
            "seed": seed,
            "best_step": best_step,
            "manifest_sha256": manifest_sha256,
            "parameter_count": count,
            "normalization": "train-current-only-v1",
        },
        mean=mean,
        std=std,
    )
    peak_vram = int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
    return {
        "arm": arm,
        "seed": seed,
        "repeat": repeat,
        "checkpoint": str(path.relative_to(P1_DIR)),
        "checkpoint_sha256": checkpoint_sha,
        "parameter_count": count,
        "best_step": best_step,
        "dev": final_dev,
        "steps_run": log_rows[-1]["step"],
        "training_seconds": round(time.perf_counter() - started, 6),
        "peak_vram_bytes": peak_vram,
        "log_sha256": hashlib.sha256(canonical_bytes(log_rows)).hexdigest(),
        "log": log_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--train-shard", type=Path, required=True)
    parser.add_argument("--dev-shard", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    opened = install_access_audit()
    manifest = load_json(args.manifest)
    manifest_sha = file_sha256(args.manifest)
    verify_frozen_sources(manifest)
    if file_sha256(args.train_shard) != manifest["shards"]["train"]["sha256"]:
        raise SystemExit("train shard mismatch")
    if file_sha256(args.dev_shard) != manifest["shards"]["dev"]["sha256"]:
        raise SystemExit("dev shard mismatch")
    if not torch.cuda.is_available():
        raise SystemExit("P1 frozen training requires the designated CUDA device")
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")
    torch.set_num_threads(1)
    device = torch.device("cuda:0")
    train_raw = load_shard(args.train_shard)
    dev_raw = load_shard(args.dev_shard)
    train, dev, mean, std = normalize(train_raw, dev_raw)
    config = manifest["training"]
    runs: list[dict[str, Any]] = []
    for arm in ("S", "C16"):
        for seed in LEARNED_SEEDS:
            runs.append(
                train_one(
                    arm=arm,
                    seed=seed,
                    repeat=False,
                    train=train,
                    dev=dev,
                    mean=mean,
                    std=std,
                    manifest_sha256=manifest_sha,
                    config=config,
                    device=device,
                )
            )
        runs.append(
            train_one(
                arm=arm,
                seed=LEARNED_SEEDS[0],
                repeat=True,
                train=train,
                dev=dev,
                mean=mean,
                std=std,
                manifest_sha256=manifest_sha,
                config=config,
                device=device,
            )
        )
    deterministic: dict[str, Any] = {}
    for arm in ("S", "C16"):
        original = next(
            row
            for row in runs
            if row["arm"] == arm and row["seed"] == 20260829 and not row["repeat"]
        )
        repeat = next(row for row in runs if row["arm"] == arm and row["repeat"])
        deterministic[arm] = {
            "checkpoint_byte_identical": original["checkpoint_sha256"]
            == repeat["checkpoint_sha256"],
            "checkpoint_sha256": original["checkpoint_sha256"],
            "repeat_sha256": repeat["checkpoint_sha256"],
            "normalized_log_identical": original["log_sha256"] == repeat["log_sha256"],
        }
    held_markers = ("/shards/test-", "/shards/audit-only")
    held_reads = sorted({path for path in opened if any(marker in path for marker in held_markers)})
    access = {
        "opened_paths_sha256": hashlib.sha256(canonical_bytes(sorted(set(opened)))).hexdigest(),
        "opened_path_count": len(set(opened)),
        "held_shard_reads": held_reads,
        "pass": not held_reads,
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json(LOG_DIR / "training-access.json", access)
    result = {
        "schema_version": 1,
        "experiment": "MA-2-P1",
        "manifest_sha256": manifest_sha,
        "device": str(torch.cuda.get_device_name(device)),
        "runs": runs,
        "deterministic_repeats": deterministic,
        "access_audit": access,
        "all_pre_eval_gates": access["pass"]
        and all(
            row["checkpoint_byte_identical"] and row["normalized_log_identical"]
            for row in deterministic.values()
        )
        and max(row["peak_vram_bytes"] for row in runs) < 4 * 1024**3,
    }
    atomic_json(args.output, result)
    print(
        json.dumps(
            {
                "all_pre_eval_gates": result["all_pre_eval_gates"],
                "device": result["device"],
                "deterministic_repeats": deterministic,
                "runs": [
                    {
                        key: row[key]
                        for key in (
                            "arm",
                            "seed",
                            "repeat",
                            "checkpoint_sha256",
                            "best_step",
                            "dev",
                            "steps_run",
                            "training_seconds",
                            "peak_vram_bytes",
                        )
                    }
                    for row in runs
                ],
            },
            indent=2,
        )
    )
    return 0 if result["all_pre_eval_gates"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
