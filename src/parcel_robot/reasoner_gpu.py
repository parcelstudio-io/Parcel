"""Fail-closed CUDA readiness audit for Parcel's pinned llama.cpp reasoner.

The doctor is deliberately read-only.  It distinguishes a healthy NVIDIA
driver from a llama.cpp binary that can actually enumerate a CUDA backend, and
it keeps build readiness separate from inference readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = REPO_ROOT / "configs/reasoner/llama_cpp_cuda12_oci_b10236.json"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class ReasonerGpuProfileError(ValueError):
    """Raised when the pinned CUDA profile is malformed."""


def _merge_profile_objects(
    base: Mapping[str, object], overlay: Mapping[str, object]
) -> dict[str, Any]:
    """Recursively merge a small model overlay onto a pinned runtime profile."""

    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_profile_objects(existing, value)
        else:
            merged[key] = value
    return merged


def _load_profile_document(path: Path, *, seen: frozenset[Path]) -> dict[str, Any]:
    if path in seen:
        raise ReasonerGpuProfileError("reasoner GPU profile inheritance contains a cycle")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReasonerGpuProfileError(f"cannot load reasoner GPU profile: {error}") from error
    if not isinstance(document, dict):
        raise ReasonerGpuProfileError("reasoner GPU profile must be a JSON object")
    parent_name = document.get("extends")
    if parent_name is None:
        return document
    relative = Path(str(parent_name))
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ReasonerGpuProfileError("profile extends must name a sibling JSON profile")
    parent = (path.parent / relative).resolve()
    if parent.parent != path.parent or parent.suffix != ".json":
        raise ReasonerGpuProfileError("profile extends escaped the profile directory")
    base = _load_profile_document(parent, seen=seen | {path})
    overlay = dict(document)
    overlay.pop("extends", None)
    merged = _merge_profile_objects(base, overlay)
    merged["extends"] = relative.name
    return merged


def load_reasoner_gpu_profile(path: str | Path = DEFAULT_PROFILE) -> dict[str, Any]:
    """Load and validate the small, pinned CUDA build/runtime profile."""

    profile_path = Path(path).expanduser().resolve()
    document = _load_profile_document(profile_path, seen=frozenset())
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ReasonerGpuProfileError("reasoner GPU profile must be a schema-version-1 object")
    for key in ("source", "build", "runtime", "admission"):
        if not isinstance(document.get(key), dict):
            raise ReasonerGpuProfileError(f"reasoner GPU profile is missing object {key!r}")

    source = document["source"]
    if _COMMIT_PATTERN.fullmatch(str(source.get("commit", ""))) is None:
        raise ReasonerGpuProfileError("source.commit must be a lowercase full Git commit")
    if not isinstance(source.get("release_build"), int) or source["release_build"] <= 0:
        raise ReasonerGpuProfileError("source.release_build must be a positive integer")

    build = document["build"]
    if not isinstance(build.get("required_tools"), dict) or not build["required_tools"]:
        raise ReasonerGpuProfileError("build.required_tools must be a non-empty object")
    for label, candidates in build["required_tools"].items():
        if not isinstance(label, str) or not isinstance(candidates, list) or not candidates:
            raise ReasonerGpuProfileError(
                "every required tool must have candidate executable names"
            )
        if any(not isinstance(candidate, str) or not candidate for candidate in candidates):
            raise ReasonerGpuProfileError("tool candidate names must be non-empty strings")
    defines = build.get("cmake_defines")
    if not isinstance(defines, dict) or defines.get("GGML_CUDA") != "ON":
        raise ReasonerGpuProfileError("build.cmake_defines must enable GGML_CUDA")
    if str(defines.get("CMAKE_CUDA_ARCHITECTURES")) != "89":
        raise ReasonerGpuProfileError("the RTX 5000 Ada profile must target CUDA architecture 89")

    runtime = document["runtime"]
    model = runtime.get("model")
    if not isinstance(model, dict):
        raise ReasonerGpuProfileError("runtime.model must be an object")
    if not isinstance(model.get("size_bytes"), int) or model["size_bytes"] <= 0:
        raise ReasonerGpuProfileError("runtime.model.size_bytes must be positive")
    if _SHA256_PATTERN.fullmatch(str(model.get("sha256", ""))) is None:
        raise ReasonerGpuProfileError("runtime.model.sha256 must be a lowercase SHA-256")
    for key in ("current_binary", "cuda_binary"):
        if not isinstance(runtime.get(key), str) or not runtime[key]:
            raise ReasonerGpuProfileError(f"runtime.{key} must be a non-empty path")
    for key in ("library_dirs", "preload_libraries"):
        values = runtime.get(key, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise ReasonerGpuProfileError(f"runtime.{key} must be a list of non-empty paths")

    distribution = document.get("distribution")
    if distribution is not None:
        if not isinstance(distribution, dict) or distribution.get("kind") != "oci_image":
            raise ReasonerGpuProfileError("distribution must describe an OCI image")
        for key in (
            "rootfs_dir",
            "entrypoint",
            "index_digest",
            "manifest_digest",
        ):
            if not isinstance(distribution.get(key), str) or not distribution[key]:
                raise ReasonerGpuProfileError(f"distribution.{key} must be non-empty text")
        for key in ("index_digest", "manifest_digest"):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", distribution[key]) is None:
                raise ReasonerGpuProfileError(f"distribution.{key} must be an OCI SHA-256")
        config = distribution.get("config")
        if (
            not isinstance(config, dict)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(config.get("digest", ""))) is None
        ):
            raise ReasonerGpuProfileError("distribution.config must pin a SHA-256 digest")
        layers = distribution.get("layers")
        if not isinstance(layers, list) or not layers:
            raise ReasonerGpuProfileError("distribution.layers must be a non-empty list")
        if any(
            not isinstance(item, dict)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get("digest", ""))) is None
            for item in layers
        ):
            raise ReasonerGpuProfileError("every OCI layer must pin a SHA-256 digest")
        critical_files = distribution.get("critical_files")
        if not isinstance(critical_files, list) or not critical_files:
            raise ReasonerGpuProfileError("distribution.critical_files must be non-empty")
        for index, item in enumerate(critical_files):
            if not isinstance(item, dict):
                raise ReasonerGpuProfileError(f"critical file {index} must be an object")
            relative = Path(str(item.get("path", "")))
            if not str(relative) or relative.is_absolute() or ".." in relative.parts:
                raise ReasonerGpuProfileError(f"critical file {index} path is unsafe")
            if not isinstance(item.get("size"), int) or item["size"] <= 0:
                raise ReasonerGpuProfileError(f"critical file {index} size must be positive")
            if _SHA256_PATTERN.fullmatch(str(item.get("sha256", ""))) is None:
                raise ReasonerGpuProfileError(f"critical file {index} SHA-256 is invalid")

    admission = document["admission"]
    for key in ("minimum_total_vram_mib", "minimum_free_vram_mib"):
        if not isinstance(admission.get(key), int) or admission[key] <= 0:
            raise ReasonerGpuProfileError(f"admission.{key} must be a positive integer")
    return document


def parse_llama_devices(output: str) -> list[str]:
    """Parse the stable ``--list-devices`` section without trusting init logs."""

    devices: list[str] = []
    in_section = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.lower() == "available devices:":
            in_section = True
            continue
        if not in_section or not line:
            continue
        if line.lower() == "(none)":
            return []
        candidate = line.lstrip("-* ")
        if re.fullmatch(r"[A-Za-z0-9_.-]+:\s+.+", candidate):
            devices.append(candidate)
    return devices


def parse_nvidia_smi_csv(output: str) -> list[dict[str, Any]]:
    """Parse the exact no-units query emitted by :func:`audit_reasoner_gpu_readiness`."""

    result: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        fields = [field.strip() for field in raw_line.split(",")]
        if len(fields) != 7:
            continue
        try:
            total_mib, used_mib, free_mib = (int(value) for value in fields[4:7])
        except ValueError:
            continue
        result.append(
            {
                "name": fields[0],
                "uuid": fields[1],
                "driver_version": fields[2],
                "compute_capability": fields[3],
                "memory_total_mib": total_mib,
                "memory_used_mib": used_mib,
                "memory_free_mib": free_mib,
            }
        )
    return result


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _command_status(
    executable: str | Path,
    arguments: Sequence[str],
    *,
    library_dirs: Sequence[Path] = (),
    preload_libraries: Sequence[Path] = (),
    timeout: float = 10.0,
) -> dict[str, Any]:
    raw_executable = str(executable)
    if Path(raw_executable).is_absolute() or "/" in raw_executable:
        path = Path(raw_executable)
        resolved = str(path) if path.is_file() and os.access(path, os.X_OK) else None
    else:
        resolved = shutil.which(raw_executable)
    if resolved is None:
        return {
            "detected": False,
            "path": raw_executable,
            "returncode": None,
            "output": None,
            "error": "not found or not executable",
        }
    environment = dict(os.environ)
    library_path = [str(path) for path in library_dirs if path.is_dir()]
    if environment.get("LD_LIBRARY_PATH"):
        library_path.append(environment["LD_LIBRARY_PATH"])
    if library_path:
        environment["LD_LIBRARY_PATH"] = os.pathsep.join(library_path)
    preloads = [str(path) for path in preload_libraries if path.is_file()]
    if environment.get("LD_PRELOAD"):
        preloads.append(environment["LD_PRELOAD"])
    if preloads:
        environment["LD_PRELOAD"] = os.pathsep.join(preloads)
    try:
        completed = subprocess.run(
            [resolved, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "detected": True,
            "path": resolved,
            "returncode": None,
            "output": None,
            "error": str(error),
        }
    output = "\n".join(
        item.strip() for item in (completed.stdout, completed.stderr) if item.strip()
    )
    return {
        "detected": True,
        "path": resolved,
        "returncode": completed.returncode,
        "output": output,
        "error": None if completed.returncode == 0 else f"exit {completed.returncode}",
    }


def _library_dirs(binary: Path, extra: Sequence[Path] = ()) -> list[Path]:
    candidates = [
        *extra,
        binary.parent,
        binary.parent / "lib",
        binary.parent / "lib64",
        binary.parent.parent / "lib",
        binary.parent.parent / "lib64",
    ]
    result: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in result:
            result.append(resolved)
    return result


def _cuda_backend_artifacts(binary: Path, library_dirs: Sequence[Path] = ()) -> list[str]:
    patterns = ("libggml-cuda.so*", "libggml-cuda.dylib", "ggml-cuda*.dll")
    result: set[str] = set()
    for directory in _library_dirs(binary, library_dirs):
        if not directory.is_dir():
            continue
        for pattern in patterns:
            result.update(str(path.resolve()) for path in directory.glob(pattern) if path.is_file())
    return sorted(result)


def _toolchain_status(required: Mapping[str, object]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for label, raw_candidates in required.items():
        candidates = [str(candidate) for candidate in raw_candidates]  # validated on load
        found = None
        for candidate in candidates:
            found = shutil.which(candidate)
            if found is not None:
                break
        result[label] = {
            "detected": found is not None,
            "path": found,
            "candidates": candidates,
        }
    return result


def _git_source_status(source_dir: Path, expected_commit: str) -> dict[str, Any]:
    if not (source_dir / ".git").exists():
        return {
            "path": str(source_dir),
            "detected": False,
            "expected_commit": expected_commit,
            "actual_commit": None,
            "commit_matches": False,
            "error": "pinned source checkout is missing",
        }
    probe = _command_status("git", ("-C", str(source_dir), "rev-parse", "HEAD"))
    actual = str(probe["output"]).strip() if probe["returncode"] == 0 else None
    return {
        "path": str(source_dir),
        "detected": probe["returncode"] == 0,
        "expected_commit": expected_commit,
        "actual_commit": actual,
        "commit_matches": actual == expected_commit,
        "error": probe["error"],
    }


def _model_status(
    path: Path, expected_size: int, expected_sha256: str, verify_hash: bool
) -> dict[str, Any]:
    detected = path.is_file()
    actual_size = path.stat().st_size if detected else None
    magic: str | None = None
    error: str | None = None
    if detected:
        try:
            with path.open("rb") as stream:
                magic = stream.read(4).decode("ascii", errors="replace")
        except OSError as read_error:
            error = str(read_error)
    actual_sha256: str | None = None
    if detected and verify_hash and error is None:
        try:
            actual_sha256 = _sha256(path)
        except OSError as hash_error:
            error = str(hash_error)
    size_matches = actual_size == expected_size
    hash_matches = actual_sha256 == expected_sha256 if verify_hash else None
    return {
        "path": str(path),
        "detected": detected,
        "magic": magic,
        "actual_size_bytes": actual_size,
        "expected_size_bytes": expected_size,
        "size_matches": size_matches,
        "actual_sha256": actual_sha256,
        "expected_sha256": expected_sha256,
        "hash_verified": verify_hash,
        "hash_matches": hash_matches,
        "ready": detected and magic == "GGUF" and size_matches and hash_matches is True,
        "error": error,
    }


def _critical_file_status(
    rootfs: Path,
    descriptor: Mapping[str, object],
) -> dict[str, Any]:
    relative = Path(str(descriptor["path"]))
    path = rootfs / relative
    try:
        resolved = path.resolve(strict=False)
        confined = resolved.is_relative_to(rootfs)
    except OSError as error:
        return {
            "path": str(path),
            "relative_path": relative.as_posix(),
            "ready": False,
            "error": str(error),
        }
    detected = confined and path.is_file()
    size = path.stat().st_size if detected else None
    actual_hash: str | None = None
    error: str | None = None
    if detected and size == descriptor["size"]:
        try:
            actual_hash = _sha256(path)
        except OSError as hash_error:
            error = str(hash_error)
    ready = bool(
        detected
        and size == descriptor["size"]
        and actual_hash == descriptor["sha256"]
        and error is None
    )
    return {
        "path": str(path),
        "relative_path": relative.as_posix(),
        "confined_to_rootfs": confined,
        "detected": detected,
        "size_bytes": size,
        "expected_size_bytes": descriptor["size"],
        "sha256": actual_hash,
        "expected_sha256": descriptor["sha256"],
        "ready": ready,
        "error": error,
    }


def _oci_distribution_status(
    root: Path,
    distribution: Mapping[str, object],
    selected_binary: Path,
) -> dict[str, Any]:
    managed_root = (root / "third_party/llama.cpp-oci").resolve()
    rootfs = _resolve(root, str(distribution["rootfs_dir"]))
    rootfs_confined = rootfs.is_relative_to(managed_root) and rootfs != managed_root
    marker_path = rootfs / ".parcel-oci-provenance.json"
    marker: dict[str, Any] | None = None
    marker_error: str | None = None
    if rootfs_confined and marker_path.is_file():
        try:
            value = json.loads(marker_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                marker = value
            else:
                marker_error = "provenance marker is not a JSON object"
        except (OSError, json.JSONDecodeError) as error:
            marker_error = str(error)
    else:
        marker_error = "managed rootfs or provenance marker is missing"

    entrypoint = rootfs / str(distribution["entrypoint"])
    binary_matches_entrypoint = selected_binary.resolve(strict=False) == entrypoint.resolve(
        strict=False
    )
    critical_descriptors = distribution["critical_files"]  # type: ignore[assignment]
    critical_files = (
        [_critical_file_status(rootfs, descriptor) for descriptor in critical_descriptors]
        if rootfs_confined
        else [
            {
                "relative_path": str(descriptor["path"]),
                "ready": False,
                "error": "rootfs is outside the managed OCI cache",
            }
            for descriptor in critical_descriptors
        ]
    )
    expected_layers = [
        item["digest"]
        for item in distribution["layers"]  # type: ignore[index]
    ]
    config = distribution["config"]
    entrypoint_descriptor = next(
        (
            descriptor
            for descriptor in critical_descriptors
            if descriptor["path"] == distribution["entrypoint"]
        ),
        None,
    )
    marker_matches = bool(
        marker
        and marker.get("schema_version") == 1
        and marker.get("index_digest") == distribution["index_digest"]
        and marker.get("manifest_digest") == distribution["manifest_digest"]
        and marker.get("config_digest") == config["digest"]  # type: ignore[index]
        and marker.get("layer_digests") == expected_layers
        and marker.get("entrypoint") == distribution["entrypoint"]
        and entrypoint_descriptor is not None
        and marker.get("entrypoint_sha256") == entrypoint_descriptor["sha256"]
    )
    ready = bool(
        rootfs_confined
        and marker_matches
        and binary_matches_entrypoint
        and all(item["ready"] for item in critical_files)
    )
    return {
        "kind": "oci_image",
        "rootfs": str(rootfs),
        "rootfs_confined": rootfs_confined,
        "marker_path": str(marker_path),
        "marker_error": marker_error,
        "marker_matches_profile": marker_matches,
        "index_digest": distribution["index_digest"],
        "manifest_digest": distribution["manifest_digest"],
        "entrypoint": str(entrypoint),
        "binary_matches_entrypoint": binary_matches_entrypoint,
        "critical_file_count": len(critical_files),
        "verified_critical_file_count": sum(item["ready"] for item in critical_files),
        "critical_files": critical_files,
        "ready": ready,
    }


def _blocker(identifier: str, component: str, detail: str, resolution: str) -> dict[str, str]:
    return {
        "id": identifier,
        "component": component,
        "detail": detail,
        "resolution": resolution,
    }


def audit_reasoner_gpu_readiness(
    *,
    profile_path: str | Path = DEFAULT_PROFILE,
    repo_root: str | Path = REPO_ROOT,
    binary_path: str | Path | None = None,
    model_path: str | Path | None = None,
    use_cuda_build_output: bool = False,
    verify_model_hash: bool = True,
    recorded_at_utc: str | None = None,
) -> dict[str, Any]:
    """Audit one llama.cpp binary without loading the model or changing GPU state."""

    profile = load_reasoner_gpu_profile(profile_path)
    root = Path(repo_root).expanduser().resolve()
    source = profile["source"]
    build = profile["build"]
    runtime = profile["runtime"]
    admission = profile["admission"]

    default_binary_key = "cuda_binary" if use_cuda_build_output else "current_binary"
    binary = _resolve(root, binary_path or runtime[default_binary_key])
    model_config = runtime["model"]
    model = _resolve(root, model_path or model_config["path"])
    source_dir = _resolve(root, build["source_dir"])
    build_dir = _resolve(root, build["build_dir"])
    configured_library_dirs = [_resolve(root, value) for value in runtime.get("library_dirs", [])]
    preload_libraries = [_resolve(root, value) for value in runtime.get("preload_libraries", [])]

    binary_size = binary.stat().st_size if binary.is_file() else None
    try:
        binary_sha256 = _sha256(binary) if binary.is_file() else None
        binary_hash_error = None
    except OSError as error:
        binary_sha256 = None
        binary_hash_error = str(error)
    library_dirs = _library_dirs(binary, configured_library_dirs)
    version_probe = _command_status(
        binary,
        ("--version",),
        library_dirs=library_dirs,
        preload_libraries=preload_libraries,
    )
    devices_probe = _command_status(
        binary,
        ("--list-devices",),
        library_dirs=library_dirs,
        preload_libraries=preload_libraries,
    )
    ldd_probe = _command_status(
        "ldd",
        (str(binary),),
        library_dirs=library_dirs,
        preload_libraries=preload_libraries,
    )
    llama_devices = (
        parse_llama_devices(str(devices_probe["output"]))
        if devices_probe["returncode"] == 0
        else []
    )
    backend_artifacts = _cuda_backend_artifacts(binary, configured_library_dirs)
    linkage_output = str(ldd_probe.get("output") or "").lower()
    cuda_linkage = any(
        marker in linkage_output for marker in ("libggml-cuda", "libcudart", "libcuda.so")
    )

    gpu_probe = _command_status(
        "nvidia-smi",
        (
            "--query-gpu=name,uuid,driver_version,compute_cap,memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ),
    )
    gpus = parse_nvidia_smi_csv(str(gpu_probe["output"])) if gpu_probe["returncode"] == 0 else []
    selected_gpu = max(gpus, key=lambda item: int(item["memory_free_mib"])) if gpus else None

    distribution = profile.get("distribution")
    distribution_status = (
        _oci_distribution_status(root, distribution, binary)
        if isinstance(distribution, Mapping)
        else None
    )
    distribution_ready = distribution_status is None or bool(distribution_status["ready"])

    model_status = _model_status(
        model,
        int(model_config["size_bytes"]),
        str(model_config["sha256"]),
        verify_model_hash,
    )
    model_mib = int(model_config["size_bytes"]) / 2**20
    weights_only_headroom_mib = (
        round(float(selected_gpu["memory_free_mib"]) - model_mib, 3) if selected_gpu else None
    )
    total_memory_ready = bool(
        selected_gpu
        and int(selected_gpu["memory_total_mib"]) >= int(admission["minimum_total_vram_mib"])
    )
    free_memory_ready = bool(
        selected_gpu
        and int(selected_gpu["memory_free_mib"]) >= int(admission["minimum_free_vram_mib"])
    )
    required_reserve_mib = int(admission["minimum_runtime_reserve_over_weight_file_mib"])
    runtime_reserve_ready = bool(
        weights_only_headroom_mib is not None and weights_only_headroom_mib >= required_reserve_mib
    )
    compute_capability_ready = bool(
        selected_gpu
        and str(selected_gpu["compute_capability"]) == str(admission["target_compute_capability"])
    )

    version_output = str(version_probe.get("output") or "")
    expected_short_commit = str(source["commit"])[:9]
    expected_build = str(source["release_build"])
    version_matches = (
        version_probe["returncode"] == 0
        and expected_short_commit in version_output
        and re.search(rf"\b{re.escape(expected_build)}\b", version_output) is not None
    )
    binary_cuda_capable = bool(
        devices_probe["returncode"] == 0 and llama_devices and (backend_artifacts or cuda_linkage)
    )

    toolchain = _toolchain_status(build["required_tools"])
    source_status = _git_source_status(source_dir, str(source["commit"]))
    build_ready = source_status["commit_matches"] and all(
        bool(status["detected"]) for status in toolchain.values()
    )
    driver_ready = bool(gpu_probe["returncode"] == 0 and gpus)
    inference_ready = bool(
        driver_ready
        and binary_cuda_capable
        and version_matches
        and distribution_ready
        and model_status["ready"]
        and total_memory_ready
        and free_memory_ready
        and runtime_reserve_ready
        and compute_capability_ready
    )

    blockers: list[dict[str, str]] = []
    if not driver_ready:
        blockers.append(
            _blocker(
                "nvidia_driver_or_device_unavailable",
                "driver",
                "nvidia-smi did not return a parseable CUDA device",
                "restore NVIDIA driver/device visibility before attempting model inference",
            )
        )
    if devices_probe["returncode"] != 0 or not llama_devices:
        blockers.append(
            _blocker(
                "llama_cpp_reports_no_cuda_device",
                "inference_binary",
                "llama-server --list-devices returned no usable backend device",
                "use the pinned GGML_CUDA=ON build output; do not pass --n-gpu-layers to this binary",
            )
        )
    if not backend_artifacts and not cuda_linkage:
        blockers.append(
            _blocker(
                "llama_cpp_cuda_backend_missing",
                "inference_binary",
                "no libggml-cuda artifact or CUDA linkage was found beside the selected server",
                "build the pinned source with scripts/build_reasoner_cuda.py",
            )
        )
    if not version_matches:
        blockers.append(
            _blocker(
                "llama_cpp_version_not_pinned",
                "inference_binary",
                f"selected server does not identify as build {expected_build} ({expected_short_commit})",
                "select a server built from the exact profile commit",
            )
        )
    if distribution_status is not None and not distribution_status["ready"]:
        blockers.append(
            _blocker(
                "llama_cpp_oci_distribution_not_verified",
                "inference_binary",
                "selected server, staged OCI provenance marker, or critical runtime file hashes do not match the pinned profile",
                "run scripts/fetch_reasoner_cuda_oci.py --prepare, then select the profile's CUDA entrypoint",
            )
        )
    if not model_status["ready"]:
        detail = (
            "model hash was deliberately skipped"
            if model_status["detected"] and not verify_model_hash
            else "GGUF magic, size, or SHA-256 did not match the pinned Gemma artifact"
        )
        blockers.append(
            _blocker(
                "gemma_artifact_not_verified",
                "model",
                detail,
                "provide the complete pinned GGUF and run the doctor with hashing enabled",
            )
        )
    if selected_gpu and not total_memory_ready:
        blockers.append(
            _blocker(
                "gpu_total_vram_below_profile_floor",
                "memory",
                f"GPU has {selected_gpu['memory_total_mib']} MiB total; profile requires {admission['minimum_total_vram_mib']} MiB",
                "select a larger GPU or define and separately evaluate a partial-offload profile",
            )
        )
    if selected_gpu and not free_memory_ready:
        blockers.append(
            _blocker(
                "gpu_free_vram_below_profile_floor",
                "memory",
                f"GPU has {selected_gpu['memory_free_mib']} MiB free; profile requires {admission['minimum_free_vram_mib']} MiB",
                "stop competing GPU workloads before loading Gemma",
            )
        )
    if selected_gpu and not runtime_reserve_ready:
        blockers.append(
            _blocker(
                "gpu_runtime_reserve_below_profile_floor",
                "memory",
                f"weights-only free headroom is {weights_only_headroom_mib} MiB; profile requires {required_reserve_mib} MiB",
                "stop competing GPU workloads or use a separately evaluated lower-memory profile",
            )
        )
    if selected_gpu and not compute_capability_ready:
        blockers.append(
            _blocker(
                "gpu_compute_capability_mismatch",
                "device",
                f"GPU compute capability is {selected_gpu['compute_capability']}; profile targets {admission['target_compute_capability']}",
                "select the matching GPU or define and separately validate a profile for this architecture",
            )
        )
    if not source_status["commit_matches"]:
        blockers.append(
            _blocker(
                "pinned_llama_cpp_source_missing",
                "build",
                f"source checkout is absent or not at {source['commit']}",
                "fetch the exact commit into the profile source_dir; never build an unpinned branch",
            )
        )
    for label, status in toolchain.items():
        if not status["detected"]:
            blockers.append(
                _blocker(
                    f"build_tool_{label}_missing",
                    "build",
                    f"none of {status['candidates']} is available on PATH",
                    "provide the tool in an isolated/user-space toolchain; this doctor never installs it",
                )
            )

    timestamp = recorded_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "audit_kind": "parcel-llama-cpp-cuda-readiness",
        "recorded_at_utc": timestamp,
        "profile": {
            "id": profile["profile_id"],
            "path": str(Path(profile_path).expanduser().resolve()),
            "source_repository": source["repository"],
            "source_commit": source["commit"],
            "release_build": source["release_build"],
            "cmake_defines": build["cmake_defines"],
            "requested_gpu_layers": runtime["requested_gpu_layers"],
        },
        "host": {
            "nvidia_smi": gpu_probe,
            "gpus": gpus,
            "selected_gpu": selected_gpu,
        },
        "inference_binary": {
            "path": str(binary),
            "size_bytes": binary_size,
            "sha256": binary_sha256,
            "hash_error": binary_hash_error,
            "version_probe": version_probe,
            "version_matches_profile": version_matches,
            "device_probe": devices_probe,
            "reported_devices": llama_devices,
            "cuda_backend_artifacts": backend_artifacts,
            "cuda_linkage_detected": cuda_linkage,
            "cuda_capable": binary_cuda_capable,
            "library_dirs": [str(path) for path in library_dirs],
            "preload_libraries": [str(path) for path in preload_libraries],
        },
        "distribution": distribution_status,
        "model": model_status,
        "memory_admission": {
            "weight_file_mib": round(model_mib, 3),
            "minimum_total_vram_mib": admission["minimum_total_vram_mib"],
            "minimum_free_vram_mib": admission["minimum_free_vram_mib"],
            "minimum_runtime_reserve_over_weight_file_mib": admission[
                "minimum_runtime_reserve_over_weight_file_mib"
            ],
            "weights_only_free_headroom_mib": weights_only_headroom_mib,
            "total_memory_ready": total_memory_ready,
            "free_memory_ready": free_memory_ready,
            "runtime_reserve_ready": runtime_reserve_ready,
            "target_compute_capability": admission["target_compute_capability"],
            "compute_capability_ready": compute_capability_ready,
            "note": "The floor is an admission estimate, not measured peak model/KV/runtime VRAM.",
        },
        "build": {
            "source": source_status,
            "build_dir": str(build_dir),
            "toolchain": toolchain,
        },
        "classification": {
            "nvidia_driver_ready": driver_ready,
            "binary_cuda_ready": binary_cuda_capable and version_matches and distribution_ready,
            "model_ready": model_status["ready"],
            "memory_admission_ready": (
                total_memory_ready
                and free_memory_ready
                and runtime_reserve_ready
                and compute_capability_ready
            ),
            "ready_for_gpu_inference": inference_ready,
            "ready_to_build_pinned_cuda_binary": build_ready,
            "gpu_planner_run_authorized": inference_ready,
        },
        "blockers": blockers,
        "claims": {
            "model_loaded": False,
            "planner_run_performed": False,
            "measured_peak_vram_mib": None,
            "measured_gpu_layers_offloaded": None,
            "navigation_or_planning_behavior_changed": False,
        },
    }


def write_audit_report(report: Mapping[str, object], path: str | Path) -> Path:
    """Persist one immutable readiness record without replacing prior evidence."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except FileExistsError as error:
        raise FileExistsError(f"refusing to overwrite readiness result: {target}") from error
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument(
        "--use-cuda-build-output",
        action="store_true",
        help="audit the profile's isolated CUDA build path instead of the installed CPU binary",
    )
    parser.add_argument(
        "--no-model-hash",
        action="store_true",
        help="skip the expensive artifact hash; fail-closed inference admission remains false",
    )
    parser.add_argument("--require-inference-ready", action="store_true")
    parser.add_argument("--require-build-ready", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.binary is not None and args.use_cuda_build_output:
        raise SystemExit("--binary and --use-cuda-build-output are mutually exclusive")
    report = audit_reasoner_gpu_readiness(
        profile_path=args.profile,
        repo_root=args.repo_root,
        binary_path=args.binary,
        model_path=args.model,
        use_cuda_build_output=args.use_cuda_build_output,
        verify_model_hash=not args.no_model_hash,
    )
    if args.output is not None:
        try:
            write_audit_report(report, args.output)
        except FileExistsError as error:
            raise SystemExit(str(error)) from error
    print(json.dumps(report, indent=None if args.compact else 2, sort_keys=True))
    classification = report["classification"]
    if args.require_inference_ready and not classification["ready_for_gpu_inference"]:
        return 2
    if args.require_build_ready and not classification["ready_to_build_pinned_cuda_binary"]:
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
