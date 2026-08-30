"""Trainable local proposal heads for DMC-1.

The models in this file never authorize motion.  They classify a semantic
proposal that the experiment's deterministic admission gate may accept or
reject.  Training data are procedural state histories; no Parcel runtime,
gateway, or owner data are read.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


ACTIONS = (
    "north",
    "south",
    "east",
    "west",
    "hold",
    "replan",
    "orient",
    "idle_expression",
)
ACTION_TO_ID = {name: index for index, name in enumerate(ACTIONS)}
DIRECTIONS = ACTIONS[:4]

FEATURES = (
    "has_task",
    "stop_latched",
    "sensors_fresh",
    "edge_state",  # -1 occupied, 0 unknown, +1 observed clear
    "route_invalid",
    "sound_active",
    "sound_allowed",
    "at_goal",
    "plan_north",
    "plan_south",
    "plan_east",
    "plan_west",
    "critical_zone",
    "command_changed",
    "blocked_reported",
)
FEATURE_TO_ID = {name: index for index, name in enumerate(FEATURES)}
WINDOW = 16


def _blank_sequence() -> np.ndarray:
    seq = np.zeros((WINDOW, len(FEATURES)), dtype=np.float32)
    seq[:, FEATURE_TO_ID["has_task"]] = 1.0
    seq[:, FEATURE_TO_ID["sensors_fresh"]] = 1.0
    seq[:, FEATURE_TO_ID["edge_state"]] = 1.0
    seq[:, FEATURE_TO_ID["sound_allowed"]] = 1.0
    return seq


def _set_plan(seq: np.ndarray, direction: str) -> None:
    seq[:, FEATURE_TO_ID["plan_north"] : FEATURE_TO_ID["plan_west"] + 1] = 0.0
    seq[:, FEATURE_TO_ID[f"plan_{direction}"]] = 1.0


def _jitter_prefix(
    seq: np.ndarray,
    rng: random.Random,
    *,
    held_out: bool,
    final_direction: str,
) -> None:
    """Add irrelevant but causal-safe history variation.

    Held-out sequences use longer alternating prefixes and transition locations
    not used by training.  The final label still depends only on information at
    or before the last frame.
    """

    limit = WINDOW - (3 if held_out else 5)
    for index in range(rng.randint(0, max(0, limit))):
        if rng.random() < (0.32 if held_out else 0.18):
            seq[index, FEATURE_TO_ID["edge_state"]] = rng.choice((-1.0, 0.0, 1.0))
        if rng.random() < 0.08:
            seq[index, FEATURE_TO_ID["sound_active"]] = 1.0
            seq[index, FEATURE_TO_ID["sound_allowed"]] = float(rng.random() > 0.35)
        if rng.random() < 0.05:
            seq[index, FEATURE_TO_ID["blocked_reported"]] = 1.0
    if rng.random() < (0.72 if held_out else 0.48):
        transition = rng.randint(1, WINDOW - 2)
        seq[:transition, FEATURE_TO_ID["has_task"]] = 0.0
        seq[:transition, FEATURE_TO_ID["edge_state"]] = 0.0
        seq[:transition, FEATURE_TO_ID["plan_north"] : FEATURE_TO_ID["plan_west"] + 1] = 0.0
        seq[transition, FEATURE_TO_ID["command_changed"]] = 1.0
    if rng.random() < 0.35:
        end = rng.randint(1, WINDOW - 2)
        start = max(0, end - rng.randint(1, 6))
        seq[start:end, FEATURE_TO_ID["sensors_fresh"]] = 0.0
        seq[start:end, FEATURE_TO_ID["edge_state"]] = 0.0
    if rng.random() < 0.30:
        end = rng.randint(1, WINDOW - 2)
        start = max(0, end - rng.randint(1, 6))
        seq[start:end, FEATURE_TO_ID["stop_latched"]] = 1.0
        seq[start:end, FEATURE_TO_ID["sound_allowed"]] = 0.0
    # Grid routes turn inside a 1.6 s window.  Earlier plan directions are
    # therefore nuisance history, while the final short suffix is the current
    # global planner output.  The held-out arm uses more and later changes.
    stable_suffix = rng.randint(2, 5 if held_out else 7)
    for index in range(WINDOW - stable_suffix):
        if rng.random() < (0.42 if held_out else 0.24):
            earlier = rng.choice(DIRECTIONS)
            seq[index, FEATURE_TO_ID["plan_north"] : FEATURE_TO_ID["plan_west"] + 1] = 0.0
            seq[index, FEATURE_TO_ID[f"plan_{earlier}"]] = 1.0
    seq[-stable_suffix:, FEATURE_TO_ID["plan_north"] : FEATURE_TO_ID["plan_west"] + 1] = 0.0
    seq[-stable_suffix:, FEATURE_TO_ID[f"plan_{final_direction}"]] = 1.0


def make_example(rng: random.Random, label: str, *, held_out: bool) -> np.ndarray:
    if label not in ACTION_TO_ID:
        raise ValueError(label)
    seq = _blank_sequence()
    direction = label if label in DIRECTIONS else rng.choice(DIRECTIONS)
    _set_plan(seq, direction)
    _jitter_prefix(seq, rng, held_out=held_out, final_direction=direction)

    if label in DIRECTIONS:
        # The move is legal only after two consecutive observed-clear frames.
        clear_run = rng.randint(2, 7 if held_out else 5)
        seq[-clear_run:, FEATURE_TO_ID["edge_state"]] = 1.0
        if clear_run < WINDOW:
            seq[-clear_run - 1, FEATURE_TO_ID["edge_state"]] = rng.choice((-1.0, 0.0))
        if held_out and rng.random() < 0.5:
            # Clear after a flickering person track: snapshot-only cannot tell
            # this from an unsafe one-frame clearance.
            seq[-clear_run - 3 : -clear_run, FEATURE_TO_ID["edge_state"]] = (-1.0, 1.0, -1.0)
        if rng.random() < 0.35:
            seq[-rng.randint(1, 5) :, FEATURE_TO_ID["critical_zone"]] = 1.0
            seq[-rng.randint(1, 5) :, FEATURE_TO_ID["sound_allowed"]] = 0.0
    elif label == "hold":
        kind = rng.choice(
            (
                "stop",
                "stale",
                "unknown",
                "occupied_wait",
                "just_cleared",
                "goal",
                "critical_sound",
            )
        )
        if kind == "stop":
            seq[-rng.randint(1, 5) :, FEATURE_TO_ID["stop_latched"]] = 1.0
            seq[-rng.randint(1, 5) :, FEATURE_TO_ID["sound_allowed"]] = 0.0
        elif kind == "stale":
            seq[-rng.randint(1, 4) :, FEATURE_TO_ID["sensors_fresh"]] = 0.0
        elif kind == "unknown":
            seq[-1, FEATURE_TO_ID["edge_state"]] = 0.0
        elif kind == "occupied_wait":
            seq[-rng.randint(1, 4) :, FEATURE_TO_ID["edge_state"]] = -1.0
        elif kind == "just_cleared":
            seq[-2:, FEATURE_TO_ID["edge_state"]] = (-1.0, 1.0)
        elif kind == "goal":
            seq[-1, FEATURE_TO_ID["at_goal"]] = 1.0
        else:
            seq[-1, FEATURE_TO_ID["sound_active"]] = 1.0
            seq[-1, FEATURE_TO_ID["sound_allowed"]] = 0.0
            seq[-1, FEATURE_TO_ID["critical_zone"]] = 1.0
    elif label == "replan":
        if rng.random() < 0.5:
            seq[-1, FEATURE_TO_ID["route_invalid"]] = 1.0
        else:
            run = rng.randint(5, 10 if held_out else 8)
            seq[-run:, FEATURE_TO_ID["edge_state"]] = -1.0
            seq[-1, FEATURE_TO_ID["blocked_reported"]] = 1.0
        if rng.random() < 0.35:
            seq[-1, FEATURE_TO_ID["critical_zone"]] = 1.0
            seq[-1, FEATURE_TO_ID["sound_allowed"]] = 0.0
    elif label == "orient":
        seq[-1, FEATURE_TO_ID["sound_active"]] = 1.0
        seq[-1, FEATURE_TO_ID["sound_allowed"]] = 1.0
        seq[-1, FEATURE_TO_ID["critical_zone"]] = 0.0
        seq[-1, FEATURE_TO_ID["edge_state"]] = rng.choice((-1.0, 0.0, 1.0))
    elif label == "idle_expression":
        seq[:, FEATURE_TO_ID["has_task"]] = 0.0
        seq[:, FEATURE_TO_ID["edge_state"]] = 0.0
        seq[:, FEATURE_TO_ID["plan_north"] : FEATURE_TO_ID["plan_west"] + 1] = 0.0

    # Low-amplitude continuous noise prevents learning exact fixture values.
    noise = np.asarray(
        [[rng.uniform(-0.015, 0.015) for _ in FEATURES] for _ in range(WINDOW)],
        dtype=np.float32,
    )
    protected = {
        FEATURE_TO_ID["edge_state"],
        FEATURE_TO_ID["plan_north"],
        FEATURE_TO_ID["plan_south"],
        FEATURE_TO_ID["plan_east"],
        FEATURE_TO_ID["plan_west"],
    }
    for column in range(len(FEATURES)):
        if column not in protected:
            seq[:, column] += noise[:, column]
    return seq


def make_dataset(*, seed: int, count: int, held_out: bool) -> tuple[np.ndarray, np.ndarray]:
    if count < len(ACTIONS):
        raise ValueError("dataset count must cover every action")
    rng = random.Random(seed)
    xs = np.empty((count, WINDOW, len(FEATURES)), dtype=np.float32)
    ys = np.empty((count,), dtype=np.int64)
    order = [ACTIONS[index % len(ACTIONS)] for index in range(count)]
    rng.shuffle(order)
    for index, label in enumerate(order):
        xs[index] = make_example(rng, label, held_out=held_out)
        ys[index] = ACTION_TO_ID[label]
    return xs, ys


class SnapshotMLP(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(len(FEATURES), 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, len(ACTIONS)),
        )

    def forward(self, sequence: torch.Tensor) -> torch.Tensor:
        return self.net(sequence[:, -1, :])


class HistoryGRU(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.gru = nn.GRU(len(FEATURES), 64, num_layers=1, batch_first=True)
        self.head = nn.Sequential(nn.Linear(64, 64), nn.ReLU(), nn.Linear(64, len(ACTIONS)))

    def forward(self, sequence: torch.Tensor) -> torch.Tensor:
        encoded, _ = self.gru(sequence)
        return self.head(encoded[:, -1, :])


@dataclass(frozen=True)
class TrainedPolicies:
    snapshot: SnapshotMLP
    history: HistoryGRU
    metrics: dict[str, Any]


def _confusion(pred: torch.Tensor, truth: torch.Tensor) -> list[list[int]]:
    matrix = [[0 for _ in ACTIONS] for _ in ACTIONS]
    for target, guess in zip(truth.tolist(), pred.tolist(), strict=True):
        matrix[target][guess] += 1
    return matrix


def _classification(matrix: list[list[int]]) -> dict[str, Any]:
    per_class: dict[str, dict[str, float]] = {}
    f1s: list[float] = []
    total = sum(sum(row) for row in matrix)
    correct = sum(matrix[index][index] for index in range(len(ACTIONS)))
    for index, action in enumerate(ACTIONS):
        tp = matrix[index][index]
        fp = sum(matrix[row][index] for row in range(len(ACTIONS)) if row != index)
        fn = sum(matrix[index][column] for column in range(len(ACTIONS)) if column != index)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1s.append(f1)
        per_class[action] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": sum(matrix[index]),
        }
    return {
        "accuracy": correct / total if total else 0.0,
        "macro_f1": sum(f1s) / len(f1s),
        "per_class": per_class,
        "confusion": matrix,
    }


def _fit(
    model: nn.Module,
    train_x: torch.Tensor,
    train_y: torch.Tensor,
    dev_x: torch.Tensor,
    dev_y: torch.Tensor,
    *,
    seed: int,
    epochs: int,
) -> tuple[nn.Module, dict[str, Any]]:
    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.set_num_threads(1)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2.5e-3, weight_decay=1e-4)
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(
        TensorDataset(train_x, train_y),
        batch_size=512,
        shuffle=True,
        num_workers=0,
        generator=generator,
    )
    losses: list[float] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_f1 = -1.0
    for _epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        examples = 0
        for x_batch, y_batch in loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(x_batch)
            loss = nn.functional.cross_entropy(logits, y_batch)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            epoch_loss += float(loss.detach()) * len(x_batch)
            examples += len(x_batch)
        losses.append(epoch_loss / max(1, examples))
        model.eval()
        with torch.inference_mode():
            predictions = model(dev_x).argmax(dim=-1)
        score = _classification(_confusion(predictions, dev_y))["macro_f1"]
        if score > best_f1:
            best_f1 = float(score)
            best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
    if best_state is None:
        raise AssertionError("training produced no checkpoint")
    model.load_state_dict(best_state)
    return model, {"loss_by_epoch": losses, "best_dev_macro_f1": best_f1}


def _latency(model: nn.Module, sample: torch.Tensor, *, repetitions: int = 2_000) -> dict[str, float]:
    torch.set_num_threads(1)
    model.eval()
    values: list[float] = []
    with torch.inference_mode():
        for _ in range(100):
            model(sample)
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            model(sample)
            values.append((time.perf_counter_ns() - started) / 1_000_000.0)
    array = np.asarray(values, dtype=np.float64)
    return {
        "p50_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "p99_ms": float(np.percentile(array, 99)),
        "max_ms": float(array.max()),
        "samples": repetitions,
    }


def train_policies(
    *,
    seed: int = 8292026,
    train_count: int = 80_000,
    dev_count: int = 8_000,
    test_count: int = 20_000,
    epochs: int = 6,
) -> TrainedPolicies:
    train_x_np, train_y_np = make_dataset(seed=seed, count=train_count, held_out=False)
    dev_x_np, dev_y_np = make_dataset(seed=seed + 10_000, count=dev_count, held_out=False)
    test_x_np, test_y_np = make_dataset(seed=seed + 20_000, count=test_count, held_out=True)
    train_x = torch.from_numpy(train_x_np)
    train_y = torch.from_numpy(train_y_np)
    dev_x = torch.from_numpy(dev_x_np)
    dev_y = torch.from_numpy(dev_y_np)
    test_x = torch.from_numpy(test_x_np)
    test_y = torch.from_numpy(test_y_np)

    snapshot, snapshot_fit = _fit(
        SnapshotMLP(), train_x, train_y, dev_x, dev_y, seed=seed + 1, epochs=epochs
    )
    history, history_fit = _fit(
        HistoryGRU(), train_x, train_y, dev_x, dev_y, seed=seed + 2, epochs=epochs
    )
    snapshot.eval()
    history.eval()
    with torch.inference_mode():
        snapshot_predictions = snapshot(test_x).argmax(dim=-1)
        history_predictions = history(test_x).argmax(dim=-1)
    sample = test_x[:1]
    metrics = {
        "schema": "parcel.dmc1.local-policy-training.v1",
        "seed": seed,
        "counts": {"train": train_count, "dev": dev_count, "test": test_count},
        "window_frames": WINDOW,
        "features": list(FEATURES),
        "actions": list(ACTIONS),
        "snapshot_mlp": {
            "parameters": sum(parameter.numel() for parameter in snapshot.parameters()),
            "fit": snapshot_fit,
            "held_out": _classification(_confusion(snapshot_predictions, test_y)),
            "latency_cpu_single_thread": _latency(snapshot, sample),
        },
        "history_gru": {
            "parameters": sum(parameter.numel() for parameter in history.parameters()),
            "fit": history_fit,
            "held_out": _classification(_confusion(history_predictions, test_y)),
            "latency_cpu_single_thread": _latency(history, sample),
        },
    }
    metrics["macro_f1_delta_history_minus_snapshot"] = (
        metrics["history_gru"]["held_out"]["macro_f1"]
        - metrics["snapshot_mlp"]["held_out"]["macro_f1"]
    )
    return TrainedPolicies(snapshot=snapshot, history=history, metrics=metrics)


def save_policies(policies: TrainedPolicies, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    torch.save(policies.snapshot.state_dict(), directory / "snapshot_mlp.pt")
    torch.save(policies.history.state_dict(), directory / "history_gru.pt")
    (directory / "training_metrics.json").write_text(
        json.dumps(policies.metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_policies(directory: Path) -> TrainedPolicies:
    snapshot = SnapshotMLP()
    history = HistoryGRU()
    snapshot.load_state_dict(torch.load(directory / "snapshot_mlp.pt", map_location="cpu"))
    history.load_state_dict(torch.load(directory / "history_gru.pt", map_location="cpu"))
    metrics = json.loads((directory / "training_metrics.json").read_text(encoding="utf-8"))
    snapshot.eval()
    history.eval()
    return TrainedPolicies(snapshot=snapshot, history=history, metrics=metrics)


def predict(model: nn.Module, history: list[list[float]]) -> str:
    if not history:
        raise ValueError("history cannot be empty")
    padded = [history[0]] * max(0, WINDOW - len(history)) + history[-WINDOW:]
    tensor = torch.tensor([padded], dtype=torch.float32)
    with torch.inference_mode():
        action_id = int(model(tensor).argmax(dim=-1).item())
    return ACTIONS[action_id]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=8292026)
    parser.add_argument("--train-count", type=int, default=80_000)
    parser.add_argument("--dev-count", type=int, default=8_000)
    parser.add_argument("--test-count", type=int, default=20_000)
    parser.add_argument("--epochs", type=int, default=6)
    args = parser.parse_args()
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    policies = train_policies(
        seed=args.seed,
        train_count=args.train_count,
        dev_count=args.dev_count,
        test_count=args.test_count,
        epochs=args.epochs,
    )
    save_policies(policies, args.out_dir)
    print(json.dumps(policies.metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
