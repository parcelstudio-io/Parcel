#!/usr/bin/env python3
"""Build Parcel's pinned llama.cpp CUDA server without installing system packages.

This script requires an existing exact source checkout and an already available
user/system toolchain.  It writes only to the isolated profile build directory;
it never invokes a package manager, fetches source, or replaces the CPU binary.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from parcel_robot.reasoner_gpu import (
    DEFAULT_PROFILE,
    load_reasoner_gpu_profile,
    parse_llama_devices,
)


class BuildPreflightError(RuntimeError):
    """Raised before CMake if the pinned, isolated build cannot be guaranteed."""


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _require_tool(candidates: list[str], label: str) -> str:
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    raise BuildPreflightError(f"missing {label}; tried {', '.join(candidates)}")


def _tool_version(path: str) -> str:
    completed = subprocess.run(
        [path, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = "\n".join(
        item.strip() for item in (completed.stdout, completed.stderr) if item.strip()
    )
    if completed.returncode != 0 or not output:
        raise BuildPreflightError(f"cannot record tool version for {path}")
    return output[:2000]


def _git_head(source_dir: Path, git: str) -> str:
    completed = subprocess.run(
        [git, "-C", str(source_dir), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise BuildPreflightError(
            f"cannot inspect source checkout {source_dir}: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _require_clean_tracked_source(source_dir: Path, git: str) -> None:
    completed = subprocess.run(
        [git, "-C", str(source_dir), "status", "--porcelain", "--untracked-files=no"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise BuildPreflightError(
            f"cannot inspect source cleanliness {source_dir}: {completed.stderr.strip()}"
        )
    if completed.stdout.strip():
        raise BuildPreflightError("pinned llama.cpp source has tracked modifications")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--jobs", type=int, default=max(1, min(16, os.cpu_count() or 1)))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")
    profile = load_reasoner_gpu_profile(args.profile)
    build = profile["build"]
    source = profile["source"]
    source_dir = _resolve(REPO_ROOT, args.source_dir or build["source_dir"])
    build_dir = _resolve(REPO_ROOT, args.build_dir or build["build_dir"])

    allowed_build_root = (REPO_ROOT / "third_party/llama.cpp-build").resolve()
    if not build_dir.is_relative_to(allowed_build_root) or build_dir == allowed_build_root:
        raise BuildPreflightError(
            f"build directory must be a child of {allowed_build_root}, got {build_dir}"
        )
    if not (source_dir / ".git").exists():
        raise BuildPreflightError(f"pinned llama.cpp checkout is missing: {source_dir}")

    required = build["required_tools"]
    tools = {
        label: _require_tool([str(item) for item in candidates], label)
        for label, candidates in required.items()
    }
    tool_versions = {label: _tool_version(path) for label, path in tools.items()}
    actual_commit = _git_head(source_dir, tools["git"])
    expected_commit = str(source["commit"])
    if actual_commit != expected_commit:
        raise BuildPreflightError(
            f"source commit mismatch: expected {expected_commit}, found {actual_commit}"
        )
    _require_clean_tracked_source(source_dir, tools["git"])

    build_dir.mkdir(parents=True, exist_ok=True)
    definitions = dict(build["cmake_defines"])
    definitions["CMAKE_C_COMPILER"] = tools["c_compiler"]
    definitions["CMAKE_CXX_COMPILER"] = tools["cxx_compiler"]
    definitions["CMAKE_CUDA_COMPILER"] = tools["cuda_compiler"]
    definitions["CMAKE_MAKE_PROGRAM"] = tools["ninja"]
    configure_command = [
        tools["cmake"],
        "-S",
        str(source_dir),
        "-B",
        str(build_dir),
        "-G",
        str(build["generator"]),
        *(f"-D{key}={value}" for key, value in sorted(definitions.items())),
    ]
    subprocess.run(configure_command, check=True)
    subprocess.run(
        [
            tools["cmake"],
            "--build",
            str(build_dir),
            "--target",
            str(build["target"]),
            "--parallel",
            str(args.jobs),
        ],
        check=True,
    )

    binary = build_dir / "bin/llama-server"
    backend_modules = sorted((build_dir / "bin").glob("libggml-cuda.so*"))
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise BuildPreflightError(f"build completed without executable {binary}")
    if not backend_modules:
        raise BuildPreflightError("build completed without libggml-cuda.so")
    environment = dict(os.environ)
    environment["LD_LIBRARY_PATH"] = os.pathsep.join(
        [str(build_dir / "bin"), environment.get("LD_LIBRARY_PATH", "")]
    ).rstrip(os.pathsep)
    version = subprocess.run(
        [str(binary), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )
    devices = subprocess.run(
        [str(binary), "--list-devices"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )
    device_output = "\n".join(item for item in (devices.stdout, devices.stderr) if item)
    reported_devices = parse_llama_devices(device_output)
    if not reported_devices:
        raise BuildPreflightError(
            "CUDA build exists but llama-server --list-devices reports no device"
        )
    print(
        json.dumps(
            {
                "profile_id": profile["profile_id"],
                "source_commit": actual_commit,
                "binary": str(binary),
                "backend_modules": [str(path) for path in backend_modules],
                "cmake_defines": definitions,
                "tool_versions": tool_versions,
                "version": "\n".join(
                    item.strip() for item in (version.stdout, version.stderr) if item.strip()
                ),
                "reported_devices": reported_devices,
                "next_step": (
                    "python -m parcel_robot.reasoner_gpu --use-cuda-build-output "
                    "--require-inference-ready"
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildPreflightError as error:
        raise SystemExit(f"build_reasoner_cuda: {error}") from error
