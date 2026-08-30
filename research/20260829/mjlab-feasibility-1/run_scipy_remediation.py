#!/usr/bin/env python3
"""Record the second narrow remediation for MJLAB-1's undeclared SciPy import."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes())
    return digest.hexdigest()


def invoke(argv: list[str], cwd: Path | None = None) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.monotonic()
    proc = subprocess.run(argv, cwd=cwd, check=False, capture_output=True, text=True)
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

    command = [str(python), "-m", "pip", "install", "--only-binary=:all:", "scipy==1.17.1"]
    install, install_seconds = invoke(command)
    (out / "scipy-remediation-final-pip.stdout.txt").write_text(
        install.stdout, encoding="utf-8"
    )
    (out / "scipy-remediation-final-pip.stderr.txt").write_text(
        install.stderr, encoding="utf-8"
    )

    list_envs, list_seconds = invoke(
        [str(python), "scripts/list_envs.py", "--keyword", "Go2"], cwd=source
    )
    stdout_path = out / "scipy-remediated-list-envs-final.stdout.txt"
    stderr_path = out / "scipy-remediated-list-envs-final.stderr.txt"
    stdout_path.write_text(list_envs.stdout, encoding="utf-8")
    stderr_path.write_text(list_envs.stderr, encoding="utf-8")
    source_status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=source, text=True
    )
    flat = "Unitree-Go2-Flat" in list_envs.stdout
    rough = "Unitree-Go2-Rough" in list_envs.stdout
    success = install.returncode == 0 and list_envs.returncode == 0 and flat and rough
    record = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "MJLAB-1",
        "phase": "undeclared_scipy_runtime_remediation",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip(),
        "source_status_porcelain": source_status,
        "source_patched": False,
        "trigger": {
            "prior_artifact": "remediation.json",
            "error": "ModuleNotFoundError: No module named 'scipy'",
            "evidence": "mjlab/terrains/heightfield_terrains.py imports scipy at module scope",
            "declared_by_mjlab_1_2_0": False,
        },
        "install": {
            "argv": command,
            "returncode": install.returncode,
            "wall_seconds": install_seconds,
            "stdout_file": "scipy-remediation-final-pip.stdout.txt",
            "stderr_file": "scipy-remediation-final-pip.stderr.txt",
            "installed_version": (
                importlib.metadata.version("scipy") if install.returncode == 0 else None
            ),
        },
        "registration": {
            "returncode": list_envs.returncode,
            "wall_seconds": list_seconds,
            "stdout_file": stdout_path.name,
            "stdout_sha256": sha256(stdout_path),
            "stderr_file": stderr_path.name,
            "stderr_sha256": sha256(stderr_path),
            "contains_flat": flat,
            "contains_rough": rough,
        },
        "remediated_registration_supported": success,
        "interpretation": (
            "This second environment-only repair demonstrates a workable compatibility "
            "recipe; it does not repair upstream dependency metadata or the clean-install gate."
        ),
    }
    path = out / "scipy-remediation-final.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
