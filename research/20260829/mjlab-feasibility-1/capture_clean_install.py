#!/usr/bin/env python3
"""Capture the preregistered MJLAB-1 clean-install failure before remediation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PACKAGES = (
    "unitree_rl_mjlab",
    "mjlab",
    "mujoco-warp",
    "mujoco",
    "warp-lang",
    "torch",
    "rsl-rl-lib",
)


def run(*args: str, cwd: Path | None = None) -> dict[str, object]:
    proc = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "argv": list(args),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_bytes(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except FileNotFoundError:
            pass
    return total


def package_record(name: str) -> dict[str, object]:
    metadata = importlib.metadata.metadata(name)
    return {
        "name": name,
        "version": metadata["Version"],
        "requires_python": metadata.get("Requires-Python"),
        "requires_dist": importlib.metadata.requires(name) or [],
    }


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
    list_result = run(str(python), "scripts/list_envs.py", "Go2", cwd=source)
    (out / "clean-list-envs.stdout.txt").write_text(
        str(list_result["stdout"]), encoding="utf-8"
    )
    (out / "clean-list-envs.stderr.txt").write_text(
        str(list_result["stderr"]), encoding="utf-8"
    )

    source_files = [
        source / "setup.py",
        source / "scripts" / "list_envs.py",
        source / "scripts" / "train.py",
    ]
    record = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "MJLAB-1",
        "phase": "clean_install_before_remediation",
        "source": {
            "path": str(source),
            "commit": run("git", "rev-parse", "HEAD", cwd=source)["stdout"].strip(),
            "status_porcelain": run("git", "status", "--porcelain", cwd=source)[
                "stdout"
            ],
            "files_sha256": {str(path.relative_to(source)): sha256(path) for path in source_files},
            "tree_bytes": tree_bytes(source),
        },
        "environment": {
            "venv": str(venv),
            "python_executable": str(python),
            "python_version": sys.version,
            "platform": platform.platform(),
            "os_release": Path("/etc/os-release").read_text(encoding="utf-8"),
            "venv_tree_bytes": tree_bytes(venv),
            "packages": [package_record(name) for name in PACKAGES],
            "pip_check": run(str(python), "-m", "pip", "check"),
            "gpu": run(
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ),
        },
        "install": {
            "upstream_command": "python -m pip install -e .",
            "wall_seconds": None,
            "wall_seconds_note": (
                "The invoking shell did not retain an install timer; this is recorded as "
                "unknown rather than reconstructed from filesystem timestamps."
            ),
        },
        "list_envs": {
            "argv": list_result["argv"],
            "returncode": list_result["returncode"],
            "stdout_file": "clean-list-envs.stdout.txt",
            "stderr_file": "clean-list-envs.stderr.txt",
            "stderr_sha256": sha256(out / "clean-list-envs.stderr.txt"),
            "expected_failure_signature": "mjtEnableBit has no attribute mjENBL_MULTICCD",
            "observed_expected_failure": (
                list_result["returncode"] != 0
                and "mjENBL_MULTICCD" in str(list_result["stderr"])
            ),
        },
        "clean_install_h1_supported": False,
        "causal_diagnosis": {
            "mujoco_warp_requirement": "mujoco>=3.4.0",
            "mjlab_requirement": "mujoco>=3.5.0",
            "resolver_selected_mujoco": importlib.metadata.version("mujoco"),
            "paired_mujoco_warp": importlib.metadata.version("mujoco-warp"),
            "note": (
                "Both dependency lower bounds are unbounded above. The resolver-selected "
                "MuJoCo 3.12.0 no longer exposes mjENBL_MULTICCD, while the pinned "
                "mujoco-warp 3.5.0 imports it at module load."
            ),
        },
    }
    output_path = out / "clean-install.json"
    output_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)
    return 0 if record["list_envs"]["observed_expected_failure"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
