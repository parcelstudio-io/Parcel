#!/usr/bin/env python3
"""Record the MJLAB-1 W&B/RSL logger API compatibility remediation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def invoke(argv: list[str]) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.monotonic()
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    return proc, time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source, venv, out = args.source.resolve(), args.venv.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    python = venv / "bin" / "python"
    before = importlib.metadata.version("wandb")
    command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--only-binary=:all:",
        "wandb==0.22.3",
    ]
    install, install_seconds = invoke(command)
    stdout = out / "wandb-remediation-pip.stdout.txt"
    stderr = out / "wandb-remediation-pip.stderr.txt"
    stdout.write_text(install.stdout, encoding="utf-8")
    stderr.write_text(install.stderr, encoding="utf-8")
    check, check_seconds = invoke(
        [
            str(python),
            "-c",
            (
                "import wandb; s=wandb.Settings(start_method='thread'); "
                "assert s is not None; print(wandb.__version__)"
            ),
        ]
    )
    check_stdout = out / "wandb-remediation-check.stdout.txt"
    check_stderr = out / "wandb-remediation-check.stderr.txt"
    check_stdout.write_text(check.stdout, encoding="utf-8")
    check_stderr.write_text(check.stderr, encoding="utf-8")
    after = importlib.metadata.version("wandb") if install.returncode == 0 else None
    success = install.returncode == 0 and check.returncode == 0 and after == "0.22.3"
    record = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "MJLAB-1",
        "phase": "wandb_rsl_logger_compatibility_remediation",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip(),
        "source_patched": False,
        "source_status_porcelain": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=source, text=True
        ),
        "trigger": {
            "prior_log": "training-wandb-api-failure.log",
            "prior_log_sha256": hashlib.sha256(
                (out / "training-wandb-api-failure.log").read_bytes()
            ).hexdigest(),
            "resolver_selected_wandb": before,
            "error": "wandb.Settings(start_method='thread') rejected start_method",
            "mjlab_requirement": "wandb>=0.22.3",
            "rsl_rl_version": importlib.metadata.version("rsl-rl-lib"),
        },
        "remediation": {
            "rationale": (
                "Use mjlab 1.2.0's exact W&B lower bound because RSL-RL 5.0.1 "
                "constructs Settings with the legacy start_method field."
            ),
            "argv": command,
            "returncode": install.returncode,
            "wall_seconds": install_seconds,
            "installed_version": after,
            "stdout_file": stdout.name,
            "stderr_file": stderr.name,
        },
        "check": {
            "returncode": check.returncode,
            "wall_seconds": check_seconds,
            "stdout_file": check_stdout.name,
            "stderr_file": check_stderr.name,
        },
        "remediated_logger_api_supported": success,
        "interpretation": (
            "This is an environment-only compatibility pin. The training smoke uses "
            "WANDB_MODE=offline so no external account or network is part of the gate."
        ),
    }
    result = out / "wandb-remediation.json"
    result.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
