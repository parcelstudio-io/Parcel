"""Shared deterministic plumbing for MA-2-P1."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

P1_DIR = Path(__file__).resolve().parent
MA2_DIR = P1_DIR.parent
REPO = MA2_DIR.parents[2]
P0_MANIFEST = MA2_DIR / "manifest.json"
P0_RESULTS = MA2_DIR / "results.json"
SHARD_DIR = P1_DIR / "shards"
CHECKPOINT_DIR = P1_DIR / "checkpoints"
TRACE_DIR = P1_DIR / "traces"
LOG_DIR = P1_DIR / "logs"
ROOT_SEED = 20260829
TRAIN_ROLES = frozenset({"door", "sofa", "bench"})
TRAIN_FAMILIES = frozenset({"plain", "interrupt_now"})
TEST_SPLITS = (
    "test-S",
    "test-T",
    "test-F",
    "test-TF",
    "test-ST",
    "test-SF",
    "test-STF",
)
ARMS = ("T*", "R", "DIRECT", "IDLE", "S", "C16")
LEARNED_SEEDS = (20260829, 20260830, 20260831)
EXPECTED_SPLITS = {
    "train": (72, 7272),
    "dev": (12, 1443),
    "test-S": (36, 3822),
    "test-T": (48, 5333),
    "test-F": (36, 5215),
    "test-TF": (24, 3957),
    "test-ST": (24, 2578),
    "test-SF": (18, 2741),
    "test-STF": (12, 1968),
    "audit-only": (18, 2425),
}
ZERO_HASH = "0" * 64


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(value) + b"\n")
    temporary.replace(path)


def split_for(*, scene_index: int, target_role: str, task_family: str) -> str:
    train_role = target_role in TRAIN_ROLES
    train_family = task_family in TRAIN_FAMILIES
    if scene_index <= 5:
        if train_role and train_family:
            return "train"
        if not train_role and train_family:
            return "test-T"
        if train_role and not train_family:
            return "test-F"
        return "test-TF"
    if scene_index == 6:
        return "dev" if train_role and train_family else "audit-only"
    if train_role and train_family:
        return "test-S"
    if not train_role and train_family:
        return "test-ST"
    if train_role and not train_family:
        return "test-SF"
    return "test-STF"


def zstd_rows(path: Path) -> Iterator[dict[str, Any]]:
    result = subprocess.run(
        ["zstd", "-q", "-dc", str(path)],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"zstd failed for {path}: {result.stderr.decode('utf-8')}")
    for line in result.stdout.splitlines():
        yield json.loads(line)


def write_zstd_rows(path: Path, rows: Iterator[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.with_suffix("")
    with raw.open("wb") as handle:
        for row in rows:
            handle.write(canonical_bytes(row) + b"\n")
    subprocess.run(
        ["zstd", "-q", "-f", "-10", str(raw), "-o", str(path)],
        timeout=120,
        check=True,
    )
    raw.unlink()


def episode_specs() -> list[dict[str, Any]]:
    results = load_json(P0_RESULTS)
    outcomes = {row["episode_id"]: row for row in results["episodes"]}
    qualification = load_json(MA2_DIR / "manifests/qualify.json")
    return [
        {
            "episode_id": row["episode_id"],
            "scene_id": row["scene_id"],
            "scene_index": row["scene_index"],
            "target_role": row["target_role"],
            "task_family": row["task_family"],
            "repeat": row["repeat"],
            "seeds": row["seeds"],
            "p0_frames": outcomes[row["episode_id"]]["frames"],
            "split": split_for(
                scene_index=int(row["scene_index"]),
                target_role=str(row["target_role"]),
                task_family=str(row["task_family"]),
            ),
        }
        for row in qualification
    ]
