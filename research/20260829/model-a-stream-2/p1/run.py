"""Stage entry point for the frozen MA-2-P1 experiment."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = Path.home() / ".cache/parcel-0e/venv/bin/python"


def call(script: str, *arguments: str) -> None:
    environment = dict(os.environ)
    environment.pop("TMPDIR", None)
    environment["PYTHONHASHSEED"] = "0"
    environment["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    subprocess.run(
        [str(PYTHON), str(HERE / script), *arguments],
        cwd=HERE.parents[3],
        env=environment,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "train", "evaluate", "verify", "post-prepare"))
    args = parser.parse_args()
    if args.stage in {"prepare", "post-prepare"}:
        call("prepare.py", "--output", str(HERE / "preconditions.json"))
        if args.stage == "prepare":
            return 0
    if args.stage in {"train", "post-prepare"}:
        call(
            "train.py",
            "--manifest",
            str(HERE / "manifest.prerun.json"),
            "--train-shard",
            str(HERE / "shards/train.npz"),
            "--dev-shard",
            str(HERE / "shards/dev.npz"),
            "--output",
            str(HERE / "training.json"),
        )
        if args.stage == "train":
            return 0
    if args.stage in {"evaluate", "post-prepare"}:
        call(
            "evaluate.py",
            "--manifest",
            str(HERE / "manifest.prerun.json"),
            "--training",
            str(HERE / "training.json"),
            "--output",
            str(HERE / "results.json"),
        )
        if args.stage == "evaluate":
            return 0
    if args.stage in {"verify", "post-prepare"}:
        call(
            "verify.py",
            "--manifest",
            str(HERE / "manifest.prerun.json"),
            "--training",
            str(HERE / "training.json"),
            "--results",
            str(HERE / "results.json"),
            "--output",
            str(HERE / "verification.json"),
            "--tamper-output",
            str(HERE / "tamper-test.json"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
