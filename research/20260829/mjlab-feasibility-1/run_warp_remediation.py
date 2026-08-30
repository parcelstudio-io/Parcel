#!/usr/bin/env python3
"""Record the MJLAB-1 Warp API compatibility remediation."""

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

    command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--only-binary=:all:",
        "warp-lang==1.12.0",
    ]
    install, install_seconds = invoke(command)
    stdout = out / "warp-remediation-final-pip.stdout.txt"
    stderr = out / "warp-remediation-final-pip.stderr.txt"
    stdout.write_text(install.stdout, encoding="utf-8")
    stderr.write_text(install.stderr, encoding="utf-8")

    check, check_seconds = invoke(
        [
            str(python),
            "-c",
            (
                "import importlib.metadata as md; import warp as wp; import mujoco_warp; "
                "import mjlab; wp.init(); "
                "assert hasattr(wp, 'context'); "
                "assert wp.context.runtime is not None; "
                "print(wp.__version__); print(mujoco_warp.__version__); "
                "print(md.version('mjlab'))"
            ),
        ]
    )
    check_stdout = out / "warp-remediation-final-check.stdout.txt"
    check_stderr = out / "warp-remediation-final-check.stderr.txt"
    check_stdout.write_text(check.stdout, encoding="utf-8")
    check_stderr.write_text(check.stderr, encoding="utf-8")
    source_status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=source, text=True
    )
    installed = importlib.metadata.version("warp-lang") if install.returncode == 0 else None
    success = install.returncode == 0 and check.returncode == 0 and installed == "1.12.0"
    record = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "MJLAB-1",
        "phase": "warp_api_compatibility_remediation",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip(),
        "source_status_porcelain": source_status,
        "source_patched": False,
        "trigger": {
            "prior_log": "physics-run-1.log",
            "prior_log_sha256": hashlib.sha256(
                (out / "physics-run-1.log").read_bytes()
            ).hexdigest(),
            "resolver_selected_warp": "1.16.0",
            "error": "AttributeError: module 'warp' has no attribute 'context'",
            "mjlab_requirement": "warp-lang>=1.12.0",
            "mujoco_warp_requirement": "warp-lang>=1.11.0",
        },
        "remediation": {
            "rationale": (
                "Use mjlab 1.2.0's exact supported lower bound, warp-lang 1.12.0, "
                "because its Simulation implementation directly accesses wp.context."
            ),
            "argv": command,
            "returncode": install.returncode,
            "wall_seconds": install_seconds,
            "installed_version": installed,
            "stdout_file": stdout.name,
            "stderr_file": stderr.name,
        },
        "check": {
            "returncode": check.returncode,
            "wall_seconds": check_seconds,
            "stdout_file": check_stdout.name,
            "stderr_file": check_stderr.name,
        },
        "remediated_import_supported": success,
        "interpretation": (
            "This third environment-only pin records another open-ended dependency drift. "
            "It does not retroactively support the clean-install gate."
        ),
    }
    result = out / "warp-remediation-final.json"
    result.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
