#!/usr/bin/env python3
"""Apply and record the narrow MJLAB-1 MuJoCo compatibility remediation."""

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
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
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

    source = args.source.resolve()
    venv = args.venv.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    python = venv / "bin" / "python"

    before = {
        name: importlib.metadata.version(name)
        for name in ("mjlab", "mujoco-warp", "mujoco")
    }
    install_argv = [str(python), "-m", "pip", "install", "--only-binary=:all:", "mujoco==3.5.0"]
    install, install_seconds = invoke(install_argv)
    (out / "remediation-final-pip.stdout.txt").write_text(install.stdout, encoding="utf-8")
    (out / "remediation-final-pip.stderr.txt").write_text(install.stderr, encoding="utf-8")

    checks: dict[str, object] = {}
    if install.returncode == 0:
        enum_check, enum_seconds = invoke(
            [
                str(python),
                "-c",
                (
                    "import mujoco; import mujoco_warp; "
                    "assert hasattr(mujoco.mjtEnableBit, 'mjENBL_MULTICCD'); "
                    "print(mujoco.__version__); print(mujoco_warp.__version__)"
                ),
            ]
        )
        checks["enum_and_import"] = {
            "returncode": enum_check.returncode,
            "wall_seconds": enum_seconds,
            "stdout": enum_check.stdout,
            "stderr": enum_check.stderr,
        }
        list_envs, list_seconds = invoke(
            [str(python), "scripts/list_envs.py", "--keyword", "Go2"], cwd=source
        )
        (out / "remediated-list-envs-final.stdout.txt").write_text(
            list_envs.stdout, encoding="utf-8"
        )
        (out / "remediated-list-envs-final.stderr.txt").write_text(
            list_envs.stderr, encoding="utf-8"
        )
        checks["list_envs"] = {
            "returncode": list_envs.returncode,
            "wall_seconds": list_seconds,
            "stdout_file": "remediated-list-envs-final.stdout.txt",
            "stdout_sha256": sha256(out / "remediated-list-envs-final.stdout.txt"),
            "stderr_file": "remediated-list-envs-final.stderr.txt",
            "stderr_sha256": sha256(out / "remediated-list-envs-final.stderr.txt"),
            "contains_flat": "Unitree-Go2-Flat" in list_envs.stdout,
            "contains_rough": "Unitree-Go2-Rough" in list_envs.stdout,
        }

    after = {}
    for name in ("mjlab", "mujoco-warp", "mujoco"):
        try:
            after[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            after[name] = None

    enum_ok = bool(
        isinstance(checks.get("enum_and_import"), dict)
        and checks["enum_and_import"]["returncode"] == 0
    )
    list_ok = bool(
        isinstance(checks.get("list_envs"), dict)
        and checks["list_envs"]["returncode"] == 0
        and checks["list_envs"]["contains_flat"]
        and checks["list_envs"]["contains_rough"]
    )
    record = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "MJLAB-1",
        "phase": "narrow_compatibility_remediation",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip(),
        "source_status_porcelain": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=source, text=True
        ),
        "source_patched": False,
        "before": before,
        "remediation": {
            "rationale": (
                "Pair the upstream-pinned mujoco-warp 3.5.0 with the same MuJoCo "
                "minor release, satisfying mjlab>=3.5.0 and mujoco-warp>=3.4.0 "
                "without editing upstream source."
            ),
            "argv": install_argv,
            "returncode": install.returncode,
            "wall_seconds": install_seconds,
            "stdout_file": "remediation-final-pip.stdout.txt",
            "stderr_file": "remediation-final-pip.stderr.txt",
        },
        "after": after,
        "checks": checks,
        "remediated_registration_supported": (
            install.returncode == 0 and enum_ok and list_ok and after.get("mujoco") == "3.5.0"
        ),
        "interpretation": (
            "A pass is remediated workstation feasibility only. It does not retroactively "
            "make the upstream clean install reproducible."
        ),
    }
    path = out / "remediation-final.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)
    return 0 if record["remediated_registration_supported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
