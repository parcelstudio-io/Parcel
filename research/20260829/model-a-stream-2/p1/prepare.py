"""Freeze P1 sources/splits and build leakage-free feature shards; no fitting."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from common import (
    EXPECTED_SPLITS,
    MA2_DIR,
    P0_MANIFEST,
    P1_DIR,
    REPO,
    SHARD_DIR,
    ZERO_HASH,
    atomic_json,
    canonical_bytes,
    digest,
    episode_specs,
    file_sha256,
    load_json,
    zstd_rows,
)
from features import (
    BASE_DIM,
    FEATURE_NAMES,
    HISTORY_FRAMES,
    build_episode_arrays,
    exact_label,
    extract_frame,
)


def verify_row_chain(rows: list[dict[str, Any]], expected_root: str) -> None:
    previous = ZERO_HASH
    for frame, row in enumerate(rows):
        if row["frame"] != frame or row["previous_row_hash"] != previous:
            raise ValueError("P0 trace order/hash predecessor mismatch")
        claimed = row["row_hash"]
        unsigned = dict(row)
        unsigned.pop("row_hash")
        if digest(unsigned) != claimed:
            raise ValueError("P0 trace row hash mismatch")
        applied = row["actions"]["actuator_applied"]
        if (
            hashlib.sha256(canonical_bytes(applied)).hexdigest()
            != row["actions"]["world_apply_argument_sha256"]
        ):
            raise ValueError("P0 world-application binding mismatch")
        exact_label(row)
        previous = claimed
    if previous != expected_root:
        raise ValueError("P0 episode root mismatch")


def save_shard(path: Path, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    current_values: list[np.ndarray] = []
    sequence_values: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    episode_ids: list[str] = []
    frames: list[int] = []
    for episode in episodes:
        current_values.append(episode["current"])
        sequence_values.append(episode["sequence"])
        labels.append(episode["labels"])
        episode_ids.extend([episode["episode_id"]] * len(episode["labels"]))
        frames.extend(range(len(episode["labels"])))
    current = np.concatenate(current_values).astype("<f4", copy=False)
    sequence = np.concatenate(sequence_values).astype("<f4", copy=False)
    label = np.concatenate(labels).astype("<f4", copy=False)
    max_id = max(len(value) for value in episode_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        current=current,
        sequence=sequence,
        label=label,
        episode_id=np.asarray(episode_ids, dtype=f"<U{max_id}"),
        frame=np.asarray(frames, dtype="<i4"),
    )
    return {
        "path": str(path.relative_to(P1_DIR)),
        "sha256": file_sha256(path),
        "episodes": len(episodes),
        "frames": len(label),
        "current_shape": list(current.shape),
        "sequence_shape": list(sequence.shape),
        "label_shape": list(label.shape),
        "episode_ids_sha256": digest(sorted({str(value) for value in episode_ids})),
    }


def leakage_fixtures(sample_rows: list[dict[str, Any]]) -> dict[str, Any]:
    scorer_identical = 0
    uuid_identical = 0
    full_row_rejected = 0
    future_rejected = 0
    bad_label_rejected = 0
    for index, row in enumerate(sample_rows):
        original = extract_frame(row["policy_input"])
        scorer_mutated = copy.deepcopy(row)
        scorer_mutated["scorer_only"] = {
            "actual_pose": {"x_m": 1.0e12, "y_m": -1.0e12},
            "exact_success_rising_edge": not row["scorer_only"]["exact_success_rising_edge"],
            "distance_to_exact_target_m": -999.0,
        }
        scorer_identical += int(
            np.array_equal(original, extract_frame(scorer_mutated["policy_input"]))
        )

        permuted = copy.deepcopy(row["policy_input"])
        old_uuid = permuted["mission"]["target_ref"]
        new_uuid = f"permuted-uuid-{index:04d}"
        permuted["mission"]["target_ref"] = new_uuid
        for candidate in permuted["semantic_map"]["candidates"]:
            if candidate["entity_uuid"] == old_uuid:
                candidate["entity_uuid"] = new_uuid
        permuted["semantic_map"]["candidates"].reverse()
        uuid_identical += int(np.array_equal(original, extract_frame(permuted)))
        try:
            extract_frame(row)
        except ValueError:
            full_row_rejected += 1
        future = copy.deepcopy(row["policy_input"])
        future["freshness"]["observed_at_ns"] = future["header"]["monotonic_ns"] + 1
        try:
            extract_frame(future)
        except ValueError:
            future_rejected += 1
        bad_label = copy.deepcopy(row)
        bad_label["actions"]["label_apply_equal"] = False
        try:
            exact_label(bad_label)
        except ValueError:
            bad_label_rejected += 1
    total = len(sample_rows)
    return {
        "samples": total,
        "scorer_mutation_tensor_identical": scorer_identical,
        "uuid_and_order_mutation_tensor_identical": uuid_identical,
        "full_trace_row_rejected_as_feature_input": full_row_rejected,
        "future_observation_rejected": future_rejected,
        "misaligned_label_rejected": bad_label_rejected,
        "pass": all(
            value == total
            for value in (
                scorer_identical,
                uuid_identical,
                full_row_rejected,
                future_rejected,
                bad_label_rejected,
            )
        ),
    }


def source_manifest(shards: dict[str, Any], split_manifest: dict[str, Any]) -> dict[str, Any]:
    source_paths = [
        MA2_DIR / "P1_DESIGN.md",
        MA2_DIR / "P1_AMENDMENTS.md",
        MA2_DIR / "P1_EXECUTION_AMENDMENT_20260829.md",
        MA2_DIR / "P1_EXECUTION_AMENDMENT_20260829_2.md",
        P1_DIR / "common.py",
        P1_DIR / "features.py",
        P1_DIR / "model.py",
        P1_DIR / "prepare.py",
        P1_DIR / "train.py",
        P1_DIR / "evaluate.py",
        P1_DIR / "verify.py",
        P1_DIR / "run.py",
    ]
    source_hashes = {str(path.relative_to(REPO)): file_sha256(path) for path in source_paths}
    command = [
        str(Path.home() / ".cache/parcel-0e/venv/bin/python"),
        str((P1_DIR / "train.py").relative_to(REPO)),
        "--manifest",
        str((P1_DIR / "manifest.prerun.json").relative_to(REPO)),
        "--train-shard",
        str((P1_DIR / "shards/train.npz").relative_to(REPO)),
        "--dev-shard",
        str((P1_DIR / "shards/dev.npz").relative_to(REPO)),
        "--output",
        str((P1_DIR / "training.json").relative_to(REPO)),
    ]
    return {
        "schema_version": 1,
        "experiment": "MA-2-P1",
        "status": "PRERUN_FROZEN_NO_OPTIMIZER_STEP",
        "created_at_unix_s": time.time(),
        "p0_manifest_sha256": file_sha256(P0_MANIFEST),
        "p0_trace_inventory_root": load_json(P0_MANIFEST)["trace_inventory_root"],
        "design_sha256": source_hashes[str((MA2_DIR / "P1_DESIGN.md").relative_to(REPO))],
        "amendments_sha256": source_hashes[str((MA2_DIR / "P1_AMENDMENTS.md").relative_to(REPO))],
        "source_hashes": source_hashes,
        "split_manifest_sha256": digest(split_manifest),
        "shards": shards,
        "features": {
            "current_dim": BASE_DIM,
            "feature_names": list(FEATURE_NAMES),
            "history_frames": HISTORY_FRAMES,
            "sequence_dim": BASE_DIM + 1,
        },
        "training": {
            "arms": ["S", "C16"],
            "seeds": [20260829, 20260830, 20260831],
            "repeat_seed": 20260829,
            "optimizer": "AdamW",
            "learning_rate": 0.0003,
            "weight_decay": 0.0001,
            "batch_size": 128,
            "max_steps": 5000,
            "eval_every": 100,
            "patience_steps": 800,
            "gradient_norm": 1.0,
            "smooth_l1_weight": 1.0,
            "stop_bce_weight": 0.2,
        },
        "exact_training_command": "env -u TMPDIR PYTHONHASHSEED=0 CUBLAS_WORKSPACE_CONFIG=:4096:8 "
        + " ".join(command),
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "numpy": np.__version__,
            "nvidia_smi": subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version,memory.total,memory.free,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            ).stdout.strip(),
            "pythonhashseed": os.environ.get("PYTHONHASHSEED", "not-set"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=P1_DIR / "preconditions.json")
    args = parser.parse_args()
    p0_manifest = load_json(P0_MANIFEST)
    p0_trace_index = {row["episode_id"]: row for row in p0_manifest["episode_traces"]}
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    sample_rows: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for spec in episode_specs():
        metadata = p0_trace_index[spec["episode_id"]]
        trace_path = MA2_DIR / metadata["path"]
        if file_sha256(trace_path) != metadata["sha256"]:
            raise SystemExit(f"P0 trace hash mismatch: {spec['episode_id']}")
        rows = list(zstd_rows(trace_path))
        verify_row_chain(rows, metadata["episode_root"])
        current, sequence, labels = build_episode_arrays(rows)
        grouped[spec["split"]].append(
            {
                **spec,
                "current": current,
                "sequence": sequence,
                "labels": labels,
            }
        )
        inventory.append(
            {
                **spec,
                "frames": len(rows),
                "p0_trace_sha256": metadata["sha256"],
                "p0_episode_root": metadata["episode_root"],
            }
        )
        if len(sample_rows) < 40:
            sample_rows.append(rows[min(len(rows) - 1, len(sample_rows) % len(rows))])
    observed = {
        split: (len(episodes), sum(len(row["labels"]) for row in episodes))
        for split, episodes in grouped.items()
    }
    if observed != EXPECTED_SPLITS:
        raise SystemExit(f"frozen split count mismatch: {observed}")
    if len({row["episode_id"] for row in inventory}) != 300:
        raise SystemExit("episode split overlap")
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    shards = {
        split: save_shard(SHARD_DIR / f"{split}.npz", grouped[split]) for split in EXPECTED_SPLITS
    }
    split_manifest = {
        "schema_version": 1,
        "experiment": "MA-2-P1",
        "episodes": inventory,
        "counts": {
            split: {"episodes": observed[split][0], "frames": observed[split][1]}
            for split in sorted(observed)
        },
    }
    atomic_json(P1_DIR / "split-manifest.json", split_manifest)
    leakage = leakage_fixtures(sample_rows)
    manifest = source_manifest(shards, split_manifest)
    atomic_json(P1_DIR / "manifest.prerun.json", manifest)
    manifest_hash = file_sha256(P1_DIR / "manifest.prerun.json")
    train_only_paths = {
        str((P1_DIR / "shards/train.npz").relative_to(REPO)),
        str((P1_DIR / "shards/dev.npz").relative_to(REPO)),
    }
    no_held_in_command = all(
        value not in manifest["exact_training_command"]
        for value in ("test-S.npz", "test-T.npz", "test-F.npz", "audit-only.npz")
    )
    preconditions = {
        "status": "PASS" if leakage["pass"] and no_held_in_command else "FAIL",
        "optimizer_steps_run": 0,
        "manifest_sha256": manifest_hash,
        "source_hashes": manifest["source_hashes"],
        "split_counts": split_manifest["counts"],
        "leakage_fixtures": leakage,
        "training_visible_shards": sorted(train_only_paths),
        "held_shards_absent_from_command": no_held_in_command,
        "exact_training_command": manifest["exact_training_command"],
    }
    atomic_json(args.output, preconditions)
    print(json.dumps(preconditions, indent=2))
    return 0 if preconditions["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
