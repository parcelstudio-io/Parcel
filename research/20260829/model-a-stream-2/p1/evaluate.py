"""Run P1 open-loop, closed-loop, and CPU/GPU latency evaluation."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import torch
from common import (
    LEARNED_SEEDS,
    MA2_DIR,
    P1_DIR,
    REPO,
    TEST_SPLITS,
    TRACE_DIR,
    ZERO_HASH,
    atomic_json,
    digest,
    episode_specs,
    file_sha256,
    load_json,
    write_zstd_rows,
    zstd_rows,
)
from features import BASE_DIM, CausalWindow, extract_frame
from model import load_checkpoint

sys.path.insert(0, str(MA2_DIR))
sys.path.insert(0, str(REPO / "src"))
import run_p0


def quantized(value: float) -> float:
    return float(f"{value:.6f}")


def target_relative(payload: dict[str, Any]) -> tuple[float, float]:
    target_ref = payload["mission"]["target_ref"]
    target = next(
        row for row in payload["semantic_map"]["candidates"] if row["entity_uuid"] == target_ref
    )
    return float(target["relative_x_m"]), float(target["relative_y_m"])


class RecordedPolicy:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.records.clear()


class TeacherPolicy(RecordedPolicy):
    def __init__(self, teacher: Callable[[dict[str, Any]], dict[str, float]]):
        super().__init__()
        self.teacher = teacher

    def __call__(self, payload: dict[str, Any]) -> dict[str, float]:
        command = self.teacher(payload)
        self.records.append({"raw_command": command, "stop_probability": None})
        return command


class ReflexPolicy(RecordedPolicy):
    def __call__(self, payload: dict[str, Any]) -> dict[str, float]:
        dx, dy = target_relative(payload)
        distance = math.hypot(dx, dy)
        if distance <= 0.18:
            speed = 0.0
            angle = 0.0
        else:
            speed = 0.30 if distance <= 1.0 else 0.70
            angle = round(math.atan2(dy, dx) / (math.pi / 4.0)) * (math.pi / 4.0)
        command = {
            "vx": quantized(speed * math.cos(angle)),
            "vy": quantized(speed * math.sin(angle)),
            "vyaw": 0.0,
        }
        self.records.append({"raw_command": command, "stop_probability": float(speed == 0.0)})
        return command


class DirectPolicy(RecordedPolicy):
    def __call__(self, payload: dict[str, Any]) -> dict[str, float]:
        dx, dy = target_relative(payload)
        distance = math.hypot(dx, dy)
        speed = 0.0 if distance <= 0.18 else 0.70
        scale = speed / distance if distance > 0 else 0.0
        command = {"vx": quantized(dx * scale), "vy": quantized(dy * scale), "vyaw": 0.0}
        self.records.append({"raw_command": command, "stop_probability": float(speed == 0.0)})
        return command


class IdlePolicy(RecordedPolicy):
    def __call__(self, payload: dict[str, Any]) -> dict[str, float]:
        del payload
        command = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}
        self.records.append({"raw_command": command, "stop_probability": 1.0})
        return command


class LearnedPolicy(RecordedPolicy):
    def __init__(self, checkpoint: Path, device: torch.device):
        super().__init__()
        self.model, self.header, self.mean, self.std = load_checkpoint(checkpoint, device)
        self.device = device
        self.window = CausalWindow()

    def reset(self) -> None:
        super().reset()
        self.window = CausalWindow()

    def __call__(self, payload: dict[str, Any]) -> dict[str, float]:
        raw = extract_frame(payload)
        normalized = (raw - self.mean) / self.std
        if self.header["arm"] == "S":
            value = torch.from_numpy(normalized).unsqueeze(0).to(self.device)
        else:
            sequence = self.window.push(raw)
            valid = sequence[:, BASE_DIM : BASE_DIM + 1]
            sequence[:, :BASE_DIM] = ((sequence[:, :BASE_DIM] - self.mean) / self.std) * valid
            value = torch.from_numpy(sequence).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            model_command, stop_logit = self.model(value)
        command_values = model_command[0].detach().cpu().numpy()
        stop_probability = float(torch.sigmoid(stop_logit[0]).detach().cpu())
        if stop_probability >= 0.5:
            command_values[:] = 0.0
        command = {
            "vx": quantized(float(command_values[0])),
            "vy": quantized(float(command_values[1])),
            "vyaw": quantized(float(command_values[2])),
        }
        self.records.append(
            {
                "raw_command": command,
                "stop_probability": stop_probability,
                "checkpoint_sha256": self.header.get("checkpoint_sha256"),
            }
        )
        return command


def trace_metrics(rows: list[dict[str, Any]], outcome: dict[str, Any]) -> dict[str, Any]:
    positions = [
        (
            float(row["scorer_only"]["actual_pose"]["x_m"]),
            float(row["scorer_only"]["actual_pose"]["y_m"]),
        )
        for row in rows
    ]
    path_length = sum(
        math.hypot(right[0] - left[0], right[1] - left[1]) for left, right in pairwise(positions)
    )
    velocities = [
        (
            float(row["actions"]["actuator_applied"]["vx"]),
            float(row["actions"]["actuator_applied"]["vy"]),
        )
        for row in rows
    ]
    accelerations = [
        ((right[0] - left[0]) / 0.1, (right[1] - left[1]) / 0.1)
        for left, right in pairwise(velocities)
    ]
    jerks = [
        math.hypot(right[0] - left[0], right[1] - left[1]) / 0.1
        for left, right in pairwise(accelerations)
    ]
    receipts = [row["narrative_receipt"] for row in rows if row["narrative_receipt"] is not None]
    backed = 0
    for row in rows:
        receipt = row["narrative_receipt"]
        if receipt is None:
            continue
        mission = row["policy_input"]["mission"]
        score = row["scorer_only"]
        backed += int(
            score["exact_success_rising_edge"]
            and receipt["task_id"] == mission["task_id"]
            and receipt["plan_revision"] == mission["revision"]
            and receipt["step_id"] == mission["step_id"]
            and receipt["attempt"] == mission["attempt"]
            and receipt["target_entity_uuid"] == mission["target_ref"]
            and receipt["target_entity_uuid"] == score["exact_target_entity_uuid"]
        )
    stale = sum(
        row["p1"]["binding"]["task_id"] != row["policy_input"]["mission"]["task_id"]
        or row["p1"]["binding"]["revision"] != row["policy_input"]["mission"]["revision"]
        for row in rows
    )
    return {
        "success": bool(outcome["success"]),
        "frames": len(rows),
        "path_length_m": round(path_length, 6),
        "mean_jerk_mps3": round(statistics.fmean(jerks), 6) if jerks else 0.0,
        "contacts": int(outcome["contacts"]),
        "unsafe_after_gate": int(outcome["unsafe_after_gate"]),
        "gate_interventions": int(outcome["gate_interventions"]),
        "transaction_exact": bool(outcome["transaction_exact"]),
        "terminal_receipts": len(receipts),
        "backed_terminal_receipts": backed,
        "wrong_or_unbacked_terminal_receipts": len(receipts) - backed,
        "stale_binding_commands": stale,
        "resume_admitted": bool(outcome["resume_admitted"]),
        "resume_eligible": bool(
            outcome["child_terminal_receipt"] and outcome["owner_resume_accepted"]
        ),
    }


def persist_episode(
    *,
    rows: list[dict[str, Any]],
    policy: RecordedPolicy,
    arm: str,
    seed: int | None,
    checkpoint_sha256: str | None,
    split: str,
    path: Path,
    success: bool,
) -> tuple[str, str]:
    if len(rows) != len(policy.records):
        raise RuntimeError("policy output/trace row count mismatch")
    previous = ZERO_HASH
    for index, (row, record) in enumerate(zip(rows, policy.records, strict=True)):
        row.pop("row_hash", None)
        row["run"] = "MA-2-P1"
        row["split"] = split
        mission = row["policy_input"]["mission"]
        row["p1"] = {
            "arm": arm,
            "seed": seed,
            "checkpoint_sha256": checkpoint_sha256,
            "raw_policy": record,
            "binding": {"task_id": mission["task_id"], "revision": mission["revision"]},
        }
        row["p1_episode_complete"] = index == len(rows) - 1
        row["p1_termination"] = (
            "success"
            if index == len(rows) - 1 and success
            else "frame_cap"
            if index == len(rows) - 1
            else None
        )
        row["previous_row_hash"] = previous
        row["row_hash"] = digest(row)
        previous = row["row_hash"]
    write_zstd_rows(path, iter(rows))
    return previous, file_sha256(path)


def open_loop_metrics(
    checkpoint: Path,
    shard_path: Path,
    device: torch.device,
    trace_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model, header, mean, std = load_checkpoint(checkpoint, device)
    with np.load(shard_path, allow_pickle=False) as values:
        current = values["current"].copy()
        sequence = values["sequence"].copy()
        label = values["label"].copy()
    if header["arm"] == "S":
        value = (current - mean) / std
    else:
        valid = sequence[:, :, BASE_DIM : BASE_DIM + 1]
        sequence[:, :, :BASE_DIM] = ((sequence[:, :, :BASE_DIM] - mean) / std) * valid
        value = sequence
    predictions: list[np.ndarray] = []
    stops: list[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(label), 2048):
            tensor = torch.from_numpy(value[start : start + 2048]).to(device)
            command, stop_logit = model(tensor)
            predictions.append(command.cpu().numpy())
            stops.append(torch.sigmoid(stop_logit).cpu().numpy())
    prediction = np.concatenate(predictions)
    stop_probability = np.concatenate(stops)
    prediction[stop_probability >= 0.5] = 0.0
    error = prediction - label
    stopped = np.linalg.norm(label[:, :2], axis=1) <= 0.03
    predicted_stop = np.linalg.norm(prediction[:, :2], axis=1) <= 0.03
    tp = int(np.logical_and(stopped, predicted_stop).sum())
    fp = int(np.logical_and(~stopped, predicted_stop).sum())
    fn = int(np.logical_and(stopped, ~predicted_stop).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    moving = np.linalg.norm(label[:, :2], axis=1) > 0.03
    direction = np.sum(prediction[moving, :2] * label[moving, :2], axis=1) > 0
    variance = np.sum((label - label.mean(axis=0)) ** 2)
    metrics = {
        "rows": len(label),
        "mse": float(np.mean(error * error)),
        "mae": float(np.mean(np.abs(error))),
        "variance_weighted_r2": float(1.0 - np.sum(error * error) / max(variance, 1.0e-12)),
        "direction_agreement": float(direction.mean()) if len(direction) else 0.0,
        "direction_denominator": len(direction),
        "stop_precision": precision,
        "stop_recall": recall,
        "stop_f1": f1,
    }
    previous = ZERO_HASH
    trace_rows: list[dict[str, Any]] = []
    for index in range(len(label)):
        row = {
            "schema_version": 1,
            "index": index,
            "label": [float(value) for value in label[index]],
            "prediction": [float(value) for value in prediction[index]],
            "stop_probability": float(stop_probability[index]),
            "previous_row_hash": previous,
        }
        row["row_hash"] = digest(row)
        previous = row["row_hash"]
        trace_rows.append(row)
    write_zstd_rows(trace_path, iter(trace_rows))
    inventory = {
        "path": str(trace_path.relative_to(P1_DIR)),
        "sha256": file_sha256(trace_path),
        "rows": len(trace_rows),
        "root": previous,
    }
    return metrics, inventory


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def latency_metrics(
    checkpoint: Path, payloads: list[dict[str, Any]], device: torch.device
) -> dict[str, Any]:
    policy = LearnedPolicy(checkpoint, device)
    for index in range(500):
        policy(payloads[index % len(payloads)])
    policy.reset()
    values: list[float] = []
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    for index in range(10_000):
        started = time.perf_counter_ns()
        policy(payloads[index % len(payloads)])
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        values.append((time.perf_counter_ns() - started) / 1_000_000.0)
    rounded = [round(value, 9) for value in values]
    return {
        "device": str(torch.cuda.get_device_name(device))
        if device.type == "cuda"
        else "host-one-thread",
        "samples": len(values),
        "warmups": 500,
        "p50_ms": percentile(rounded, 50),
        "p95_ms": percentile(rounded, 95),
        "p99_ms": percentile(rounded, 99),
        "max_ms": max(rounded),
        "samples_ms": rounded,
        "samples_sha256": digest(rounded),
    }


def aggregate_closed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: defaultdict[tuple[str, str, int | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["arm"], row["split"], row["seed"])].append(row)
    output: dict[str, Any] = {}
    for (arm, split, seed), episodes in grouped.items():
        successes = [row for row in episodes if row["success"]]
        claims = sum(row["terminal_receipts"] for row in episodes)
        backed = sum(row["backed_terminal_receipts"] for row in episodes)
        key = f"{arm}|{seed if seed is not None else 'na'}|{split}"
        output[key] = {
            "arm": arm,
            "seed": seed,
            "split": split,
            "successes": len(successes),
            "episodes": len(episodes),
            "success_rate": len(successes) / len(episodes),
            "success_wilson95": wilson(len(successes), len(episodes)),
            "terminal_precision": backed / claims if claims else 1.0,
            "terminal_claims": claims,
            "wrong_or_unbacked_terminal_receipts": claims - backed,
            "contacts": sum(row["contacts"] for row in episodes),
            "unsafe_after_gate": sum(row["unsafe_after_gate"] for row in episodes),
            "stale_binding_commands": sum(row["stale_binding_commands"] for row in episodes),
            "ineligible_resumes": sum(
                row["resume_admitted"] and not row["resume_eligible"] for row in episodes
            ),
            "transaction_exact": sum(row["transaction_exact"] for row in episodes),
            "median_frames_success": statistics.median(row["frames"] for row in successes)
            if successes
            else None,
            "median_path_m_success": statistics.median(row["path_length_m"] for row in successes)
            if successes
            else None,
            "mean_jerk_mps3": statistics.fmean(row["mean_jerk_mps3"] for row in episodes),
        }
    teacher_by_episode = {
        (row["split"], row["episode_id"]): row for row in rows if row["arm"] == "T*"
    }
    for key, aggregate in output.items():
        arm, seed_text, split = key.split("|")
        seed = None if seed_text == "na" else int(seed_text)
        paired = [
            row
            for row in rows
            if row["arm"] == arm
            and row["seed"] == seed
            and row["split"] == split
            and row["success"]
            and teacher_by_episode[(split, row["episode_id"])]["success"]
        ]
        if paired:
            learned_frames = statistics.median(row["frames"] for row in paired)
            teacher_frames = statistics.median(
                teacher_by_episode[(split, row["episode_id"])]["frames"] for row in paired
            )
            learned_path = statistics.median(row["path_length_m"] for row in paired)
            teacher_path = statistics.median(
                teacher_by_episode[(split, row["episode_id"])]["path_length_m"] for row in paired
            )
            aggregate["joint_success_episodes"] = len(paired)
            aggregate["paired_completion_frame_ratio"] = learned_frames / teacher_frames
            aggregate["paired_path_ratio"] = learned_path / teacher_path
        else:
            aggregate["joint_success_episodes"] = 0
            aggregate["paired_completion_frame_ratio"] = None
            aggregate["paired_path_ratio"] = None
    return output


def wilson(successes: int, total: int) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, centre - radius), min(1.0, centre + radius)]


def gates(
    aggregates: dict[str, Any], open_loop: dict[str, Any], latency: dict[str, Any]
) -> dict[str, Any]:
    h_a: dict[str, bool] = {}
    required = {
        "test-S": 0.90,
        "test-T": 0.90,
        "test-F": 0.90,
        "test-TF": 0.80,
        "test-ST": 0.80,
        "test-SF": 0.80,
        "test-STF": 0.75,
    }
    for seed in LEARNED_SEEDS:
        checks = []
        for split, threshold in required.items():
            row = aggregates[f"C16|{seed}|{split}"]
            checks.append(row["success_rate"] >= threshold)
            checks.extend(
                [
                    row["terminal_precision"] == 1.0,
                    row["contacts"] == 0,
                    row["unsafe_after_gate"] == 0,
                    row["stale_binding_commands"] == 0,
                    row["ineligible_resumes"] == 0,
                    row["wrong_or_unbacked_terminal_receipts"] == 0,
                ]
            )
        diagnostic = open_loop[f"C16|{seed}|test-STF"]
        checks.extend(
            [
                diagnostic["mse"] <= 0.01,
                diagnostic["direction_agreement"] >= 0.95,
                diagnostic["stop_f1"] >= 0.90,
            ]
        )
        learned = aggregates[f"C16|{seed}|test-STF"]
        checks.extend(
            [
                learned["paired_completion_frame_ratio"] is not None
                and learned["paired_completion_frame_ratio"] <= 1.25,
                learned["paired_path_ratio"] is not None and learned["paired_path_ratio"] <= 1.25,
            ]
        )
        h_a[str(seed)] = all(checks)
    held_family = ("test-F", "test-TF", "test-SF", "test-STF")
    h_b: dict[str, bool] = {}
    for seed in LEARNED_SEEDS:
        c_success = sum(aggregates[f"C16|{seed}|{split}"]["successes"] for split in held_family)
        s_success = sum(aggregates[f"S|{seed}|{split}"]["successes"] for split in held_family)
        denominator = sum(aggregates[f"C16|{seed}|{split}"]["episodes"] for split in held_family)
        h_b[str(seed)] = (c_success - s_success) / denominator >= 0.05
    h_c = all(
        latency[f"{arm}|{seed}|gpu"]["p99_ms"] <= 10.0
        and latency[f"{arm}|{seed}|cpu"]["p99_ms"] <= 50.0
        for arm in ("S", "C16")
        for seed in LEARNED_SEEDS
    )
    integrity = all(
        row["contacts"] == 0
        and row["unsafe_after_gate"] == 0
        and row["stale_binding_commands"] == 0
        and row["ineligible_resumes"] == 0
        and row["wrong_or_unbacked_terminal_receipts"] == 0
        for row in aggregates.values()
    )
    return {
        "integrity": integrity,
        "H-P1a_by_seed": h_a,
        "H-P1a": all(h_a.values()),
        "H-P1b_by_seed": h_b,
        "H-P1b": all(h_b.values()),
        "H-P1c": h_c,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=P1_DIR / "results.json")
    args = parser.parse_args()
    manifest = load_json(args.manifest)
    training = load_json(args.training)
    if not training["all_pre_eval_gates"]:
        raise SystemExit("training pre-evaluation gate failed")
    if training["manifest_sha256"] != file_sha256(args.manifest):
        raise SystemExit("training/manifest binding mismatch")
    checkpoint_rows = [row for row in training["runs"] if not row["repeat"]]
    checkpoint_index = {
        (row["arm"], int(row["seed"])): (P1_DIR / row["checkpoint"], row["checkpoint_sha256"])
        for row in checkpoint_rows
    }
    for path, expected in checkpoint_index.values():
        if file_sha256(path) != expected:
            raise SystemExit(f"checkpoint mismatch: {path}")
    torch.set_num_threads(1)
    device = torch.device("cuda:0")
    original_teacher = run_p0.propose
    specs = [spec for spec in episode_specs() if spec["split"] in TEST_SPLITS]
    closed_rows: list[dict[str, Any]] = []
    trace_inventory: list[dict[str, Any]] = []
    arms: list[tuple[str, int | None, RecordedPolicy, str | None]] = [
        ("T*", None, TeacherPolicy(original_teacher), None),
        ("R", None, ReflexPolicy(), None),
        ("DIRECT", None, DirectPolicy(), None),
        ("IDLE", None, IdlePolicy(), None),
    ]
    for arm in ("S", "C16"):
        for seed in LEARNED_SEEDS:
            checkpoint, checkpoint_sha = checkpoint_index[(arm, seed)]
            policy = LearnedPolicy(checkpoint, device)
            policy.header["checkpoint_sha256"] = checkpoint_sha
            arms.append((arm, seed, policy, checkpoint_sha))
    try:
        for arm, seed, policy, checkpoint_sha in arms:
            arm_name = "Tstar" if arm == "T*" else arm
            for index, spec in enumerate(specs):
                policy.reset()
                run_p0.propose = policy
                outcome = run_p0.run_episode(spec, trace_path=None, collect_rows=True)
                rows = outcome.pop("rows")
                trace_path = (
                    TRACE_DIR
                    / arm_name
                    / (str(seed) if seed is not None else "deterministic")
                    / f"{spec['episode_id']}.jsonl.zst"
                )
                episode_root, trace_sha = persist_episode(
                    rows=rows,
                    policy=policy,
                    arm=arm,
                    seed=seed,
                    checkpoint_sha256=checkpoint_sha,
                    split=spec["split"],
                    path=trace_path,
                    success=bool(outcome["success"]),
                )
                metrics = trace_metrics(rows, outcome)
                closed_rows.append({**spec, "arm": arm, "seed": seed, **metrics})
                trace_inventory.append(
                    {
                        "episode_id": spec["episode_id"],
                        "arm": arm,
                        "seed": seed,
                        "checkpoint_sha256": checkpoint_sha,
                        "split": spec["split"],
                        "path": str(trace_path.relative_to(P1_DIR)),
                        "sha256": trace_sha,
                        "episode_root": episode_root,
                        "frames": len(rows),
                    }
                )
                if (index + 1) % 50 == 0:
                    print(f"closed-loop {arm}/{seed}: {index + 1}/{len(specs)}", flush=True)
    finally:
        run_p0.propose = original_teacher
    open_loop: dict[str, Any] = {}
    open_loop_trace_inventory: list[dict[str, Any]] = []
    for arm in ("S", "C16"):
        for seed in LEARNED_SEEDS:
            checkpoint, _sha = checkpoint_index[(arm, seed)]
            for split in TEST_SPLITS:
                key = f"{arm}|{seed}|{split}"
                metrics, trace_meta = open_loop_metrics(
                    checkpoint,
                    P1_DIR / manifest["shards"][split]["path"],
                    device,
                    P1_DIR / "open-loop" / arm / str(seed) / f"{split}.jsonl.zst",
                )
                open_loop[key] = metrics
                open_loop_trace_inventory.append(
                    {
                        "key": key,
                        "checkpoint_sha256": checkpoint_index[(arm, seed)][1],
                        **trace_meta,
                    }
                )
    sample_specs = [spec for spec in episode_specs() if spec["split"] == "test-STF"]
    p0_index = {
        row["episode_id"]: row for row in load_json(MA2_DIR / "manifest.json")["episode_traces"]
    }
    payloads: list[dict[str, Any]] = []
    for spec in sample_specs[:4]:
        for row in zstd_rows(MA2_DIR / p0_index[spec["episode_id"]]["path"]):
            payloads.append(row["policy_input"])
            if len(payloads) >= 128:
                break
        if len(payloads) >= 128:
            break
    latency: dict[str, Any] = {}
    for arm in ("S", "C16"):
        for seed in LEARNED_SEEDS:
            checkpoint, _sha = checkpoint_index[(arm, seed)]
            latency[f"{arm}|{seed}|gpu"] = latency_metrics(checkpoint, payloads, device)
            latency[f"{arm}|{seed}|cpu"] = latency_metrics(
                checkpoint, payloads, torch.device("cpu")
            )
    closed_aggregates = aggregate_closed(closed_rows)
    hypothesis = gates(closed_aggregates, open_loop, latency)
    if not hypothesis["integrity"]:
        verdict = "INVALID_PRECONDITION"
    elif hypothesis["H-P1a"] and hypothesis["H-P1c"]:
        verdict = "P1_RESEARCH_CHALLENGER" if hypothesis["H-P1b"] else "P1_SNAPSHOT_SUFFICIENT"
    else:
        verdict = "P1_REFUTED"
    results = {
        "schema_version": 1,
        "experiment": "MA-2-P1",
        "verdict": verdict,
        "claim": "bounded Head-1 desktop challenger only; no Model-A or hardware promotion",
        "manifest_sha256": file_sha256(args.manifest),
        "training_sha256": file_sha256(args.training),
        "checkpoint_inventory": [
            {
                "arm": arm,
                "seed": seed,
                "path": str(path.relative_to(P1_DIR)),
                "sha256": sha,
            }
            for (arm, seed), (path, sha) in checkpoint_index.items()
        ],
        "closed_loop": closed_rows,
        "closed_loop_aggregates": closed_aggregates,
        "open_loop": open_loop,
        "open_loop_trace_inventory": open_loop_trace_inventory,
        "open_loop_trace_inventory_root": digest(open_loop_trace_inventory),
        "latency": latency,
        "hypotheses": hypothesis,
        "trace_inventory": trace_inventory,
        "trace_inventory_root": digest(trace_inventory),
    }
    atomic_json(args.output, results)
    print(
        json.dumps(
            {
                "verdict": verdict,
                "hypotheses": hypothesis,
                "closed_loop": closed_aggregates,
                "latency": latency,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
