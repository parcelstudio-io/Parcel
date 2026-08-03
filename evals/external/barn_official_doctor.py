"""Read-only readiness doctor for the official-compatible BARN 2026 ROS 2 path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .barn_runtime_package import (
    DEFAULT_PACKAGE_PATH,
    DEFAULT_ROOTFS_PATH,
    inspect_runtime_package,
    inspect_runtime_rootfs,
)
from .fetch_sources import DEFAULT_DESTINATION, load_lock

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_MANIFEST = Path(__file__).resolve().parent / "targets" / "barn_ros2_2026_runtime.json"
SOURCE_ID = "barn_challenge_ros2_2026"
PUBLIC_EVALUATION_KIND = "barn-ros2-gazebo-public-compatibility-non-official"
ROOTLESS_SMOKE_EVALUATION_KIND = "barn-ros2-upstream-mppi-single-world-rootless-smoke"
DEFAULT_ROOTLESS_PROOT_PATH = REPO_ROOT / ".cache/external-evals/runtime/proot"
DEFAULT_ROOTLESS_BUILD_ROOTFS = REPO_ROOT / ".cache/external-evals/runtime/barn-current-rootfs"
DEFAULT_ROOTLESS_SMOKE_EVIDENCE = (
    Path(__file__).resolve().parent / "results/barn_ros2/upstream-mppi-world0-20260803.json"
)


def load_runtime_manifest(path: str | Path = RUNTIME_MANIFEST) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load BARN ROS2 runtime manifest {manifest_path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("BARN ROS2 runtime manifest must be a schema-version-1 object")
    required = (
        "official_sources",
        "container",
        "protocol",
        "eligibility",
        "gpu",
        "rootless_diagnostic",
    )
    if any(not isinstance(document.get(key), dict) for key in required):
        raise ValueError("BARN ROS2 runtime manifest is missing required objects")
    source_hashes = document["official_sources"].get("critical_files_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ValueError("BARN ROS2 runtime manifest must pin critical evaluator files")
    if any(
        not isinstance(relative, str)
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for relative, digest in source_hashes.items()
    ):
        raise ValueError("BARN ROS2 critical evaluator hashes must be lowercase SHA-256 values")
    indices = document["protocol"].get("public_world_indices")
    if indices != list(range(0, 300, 6)):
        raise ValueError("BARN ROS2 public compatibility indices must be 0,6,...,294")
    if document["eligibility"].get("public_container_run_is_official_score") is not False:
        raise ValueError("public compatibility runs must never be marked official")
    if document["rootless_diagnostic"].get("official_compatibility_gate") is not False:
        raise ValueError("rootless diagnostics must never satisfy the official compatibility gate")
    if document["gpu"].get("required") is not False:
        raise ValueError("GPU availability must not be a BARN readiness gate")
    if document["gpu"].get("cpu_compatibility_required") is not True:
        raise ValueError("the BARN submission profile must remain CPU-compatible")
    return document


def parse_os_release(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value.strip().strip('"')
    return result


def parse_singularity_version(output: str) -> str | None:
    """Extract a semantic SingularityCE version from common CLI output."""

    match = re.search(r"(?:version\s+|singularity-ce\s+)(\d+\.\d+\.\d+)", output.lower())
    return match.group(1) if match else None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _command_version(executable: str, arguments: Sequence[str]) -> dict[str, Any]:
    path = shutil.which(executable)
    if path is None:
        return {"detected": False, "path": None, "output": None, "error": "not found"}
    try:
        result = subprocess.run(
            [path, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"detected": True, "path": path, "output": None, "error": str(exc)}
    output = (result.stdout or result.stderr).strip()
    return {
        "detected": result.returncode == 0,
        "path": path,
        "output": output,
        "error": None if result.returncode == 0 else f"exit {result.returncode}",
    }


def _normalized_git_url(url: str) -> str:
    return url.rstrip("/").removesuffix(".git")


def _git_checkout_status(
    path: Path,
    expected_commit: str,
    expected_origin: str | None = None,
) -> dict[str, Any]:
    if not (path / ".git").is_dir():
        return {
            "path": str(path),
            "detected": False,
            "actual_commit": None,
            "expected_commit": expected_commit,
            "commit_matches": False,
            "origin_url": None,
            "expected_origin": expected_origin,
            "origin_matches": False,
            "worktree_clean": False,
            "provenance_verified": False,
            "error": "pinned checkout not fetched",
        }
    try:

        def run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(path), *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )

        revision = run_git("rev-parse", "HEAD")
        origin_result = run_git("remote", "get-url", "origin")
        status_result = run_git("status", "--porcelain", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "path": str(path),
            "detected": True,
            "actual_commit": None,
            "expected_commit": expected_commit,
            "commit_matches": False,
            "origin_url": None,
            "expected_origin": expected_origin,
            "origin_matches": False,
            "worktree_clean": False,
            "provenance_verified": False,
            "error": str(exc),
        }
    actual = revision.stdout.strip() if revision.returncode == 0 else None
    origin = origin_result.stdout.strip() if origin_result.returncode == 0 else None
    origin_matches = bool(
        origin
        and expected_origin
        and _normalized_git_url(origin) == _normalized_git_url(expected_origin)
    )
    worktree_clean = status_result.returncode == 0 and not status_result.stdout.strip()
    errors = [
        result.stderr.strip()
        for result in (revision, origin_result, status_result)
        if result.returncode != 0 and result.stderr.strip()
    ]
    return {
        "path": str(path),
        "detected": revision.returncode == 0,
        "actual_commit": actual,
        "expected_commit": expected_commit,
        "commit_matches": actual == expected_commit,
        "origin_url": origin,
        "expected_origin": expected_origin,
        "origin_matches": origin_matches,
        "worktree_clean": worktree_clean,
        "provenance_verified": bool(
            actual == expected_commit and origin_matches and worktree_clean
        ),
        "error": "; ".join(errors) if errors else None,
    }


def _user_namespace_probe(executable: str, arguments: Sequence[str]) -> dict[str, Any]:
    path = shutil.which(executable)
    if path is None:
        return {"attempted": False, "ready": False, "error": f"{executable} not found"}
    try:
        result = subprocess.run(
            [path, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"attempted": True, "ready": False, "error": str(exc)}
    detail = (result.stderr or result.stdout).strip()
    return {
        "attempted": True,
        "ready": result.returncode == 0,
        "error": None if result.returncode == 0 else detail or f"exit {result.returncode}",
    }


def _mapping_present(path: Path, username: str) -> bool:
    text = _read_text(path)
    if text is None:
        return False
    return any(line.split(":", 1)[0] == username for line in text.splitlines() if ":" in line)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pinned_file_status(path: Path, *, expected_sha256: str, expected_size: int) -> dict[str, Any]:
    """Inspect one staged diagnostic artifact without executing it."""

    if path.is_symlink():
        return {
            "path": str(path),
            "detected": True,
            "verified": False,
            "sha256": None,
            "size_bytes": None,
            "errors": ["symlink is not accepted"],
        }
    if not path.is_file():
        return {
            "path": str(path),
            "detected": False,
            "verified": False,
            "sha256": None,
            "size_bytes": None,
            "errors": ["missing"],
        }
    size = path.stat().st_size
    digest = _sha256(path)
    errors: list[str] = []
    if size != expected_size:
        errors.append("size mismatch")
    if digest != expected_sha256:
        errors.append("sha256 mismatch")
    return {
        "path": str(path),
        "detected": True,
        "verified": not errors,
        "sha256": digest,
        "size_bytes": size,
        "errors": errors,
    }


def _rootless_build_rootfs_status(
    path: Path,
    *,
    critical_source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Inspect the cache-only ROS rootfs; never treat it as a SIF proof."""

    if not path.is_dir():
        return {
            "path": str(path),
            "detected": False,
            "build_outputs_verified": False,
            "evaluator_critical_files_verified": False,
            "errors": ["missing"],
        }
    errors: list[str] = []
    source_root = path / "jackal_ws/src/The-Barn-Challenge-Ros2"
    source_files: dict[str, dict[str, Any]] = {}
    for relative, expected_digest in sorted(critical_source_hashes.items()):
        candidate = source_root / relative
        actual_digest = _sha256(candidate) if candidate.is_file() else None
        matches = actual_digest == expected_digest
        source_files[relative] = {
            "detected": candidate.is_file(),
            "expected_sha256": expected_digest,
            "sha256": actual_digest,
            "matches": matches,
        }
        if not matches:
            errors.append(f"critical evaluator file mismatch: {relative}")

    build_outputs = (
        path / "opt/ros/jazzy/setup.bash",
        path / "jackal_ws/install/local_setup.bash",
        path / "jackal_ws/install/jackal_helper/share/jackal_helper/package.xml",
    )
    missing_outputs = [
        str(candidate.relative_to(path)) for candidate in build_outputs if not candidate.is_file()
    ]
    errors.extend(f"missing build output: {relative}" for relative in missing_outputs)

    dpkg_status_path = path / "var/lib/dpkg/status"
    dpkg_status = _read_text(dpkg_status_path) or ""
    required_packages = ("ros-jazzy-ros-gz", "ros-jazzy-clearpath-simulator")
    installed_packages = {
        package: bool(
            re.search(
                rf"(?ms)^Package: {re.escape(package)}\n.*?^Status: install ok installed$",
                dpkg_status,
            )
        )
        for package in required_packages
    }
    for package, installed in installed_packages.items():
        if not installed:
            errors.append(f"required package is not configured: {package}")

    source_verified = all(entry["matches"] for entry in source_files.values())
    build_verified = not missing_outputs and all(installed_packages.values())
    return {
        "path": str(path),
        "detected": True,
        "build_outputs_verified": build_verified,
        "evaluator_critical_files_verified": source_verified,
        "source_files": source_files,
        "required_packages": installed_packages,
        "errors": errors,
        "ready_for_diagnostic_replay": build_verified and source_verified,
        "satisfies_singularity_or_sif_gate": False,
    }


def _rootless_smoke_evidence_status(
    path: Path,
    *,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the durable one-world result and its raw evaluator row."""

    if not path.is_file():
        return {"path": str(path), "detected": False, "valid": False, "errors": ["missing"]}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "path": str(path),
            "detected": True,
            "valid": False,
            "errors": [f"invalid JSON: {exc}"],
        }

    errors: list[str] = []
    expected_source = manifest["official_sources"]
    expected_container = manifest["container"]
    expected_top_level = {
        "schema_version": 1,
        "evaluation_kind": ROOTLESS_SMOKE_EVALUATION_KIND,
    }
    if not isinstance(document, dict):
        errors.append("evidence must be an object")
        document = {}
    for key, expected in expected_top_level.items():
        if document.get(key) != expected:
            errors.append(f"{key} mismatch")

    source = document.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        if source.get("repository") != expected_source["repository"]:
            errors.append("source repository mismatch")
        if source.get("commit") != expected_source["repository_commit"]:
            errors.append("source commit mismatch")
        if source.get("checkout_clean") is not True:
            errors.append("source checkout was not recorded clean")
    if document.get("source_file_sha256") != expected_source["critical_files_sha256"]:
        errors.append("critical source hashes mismatch")

    runtime = document.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("runtime must be an object")
    else:
        runtime_expected = {
            "build_driver": "bubblewrap-plus-proot-cache-only-diagnostic",
            "upstream_tested_runtime": "singularity-ce-4.3.0",
            "used_upstream_tested_runtime_for_launch": False,
            "base_image": expected_container["local_base_image"],
            "base_image_index_digest": expected_container["local_base_image_manifest_digest"],
            "base_image_linux_amd64_manifest_digest": expected_container[
                "local_base_image_linux_amd64_manifest_digest"
            ],
            "software_rendering_forced": True,
            "gpu_used": False,
            "host_system_packages_installed": False,
        }
        for key, expected in runtime_expected.items():
            if runtime.get(key) != expected:
                errors.append(f"runtime.{key} mismatch")

    navigation = document.get("navigation")
    navigation_expected = {
        "stack": "upstream-default-nav2-mppi",
        "parcel_adapter_exercised": False,
        "official_evaluator_modified": False,
    }
    if not isinstance(navigation, dict):
        errors.append("navigation must be an object")
    else:
        for key, expected in navigation_expected.items():
            if navigation.get(key) != expected:
                errors.append(f"navigation.{key} mismatch")

    scope = document.get("scope")
    if scope != {"world_indices": [0], "trials_per_world": 1, "episode_count": 1}:
        errors.append("scope must be exactly one trial on public world 0")
    claims = document.get("claims")
    expected_claims = {
        "official_protocol": False,
        "organizer_attested": False,
        "parcel_navigation_score": False,
        "top_decile_evidence": False,
    }
    if claims != expected_claims:
        errors.append("non-official claim boundary mismatch")

    raw = document.get("raw_result")
    raw_path: Path | None = None
    raw_text: str | None = None
    if not isinstance(raw, dict):
        errors.append("raw_result must be an object")
    else:
        raw_name = raw.get("path")
        if not isinstance(raw_name, str) or not raw_name:
            errors.append("raw_result.path must be relative text")
        else:
            relative = Path(raw_name)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append("raw_result.path escapes the evidence directory")
            else:
                raw_path = path.parent / relative
                if raw_path.is_symlink() or not raw_path.is_file():
                    errors.append("raw result is missing or is a symlink")
                else:
                    raw_text = _read_text(raw_path)
                    if _sha256(raw_path) != raw.get("sha256"):
                        errors.append("raw result sha256 mismatch")
                    if raw_path.stat().st_size != raw.get("size_bytes"):
                        errors.append("raw result size mismatch")

    episode = document.get("episode")
    parsed_episode: dict[str, int | float] | None = None
    if raw_text is not None:
        rows = [line for line in raw_text.splitlines() if line.strip()]
        try:
            if len(rows) != 1:
                raise ValueError("expected exactly one evaluator row")
            fields = rows[0].split()
            if len(fields) != 6:
                raise ValueError("expected six evaluator columns")
            parsed_episode = {
                "world_idx": int(fields[0]),
                "success": int(fields[1]),
                "collision": int(fields[2]),
                "timeout": int(fields[3]),
                "elapsed_time_s": float(fields[4]),
                "navigation_metric": float(fields[5]),
            }
        except ValueError as exc:
            errors.append(f"invalid raw evaluator row: {exc}")
    if parsed_episode is not None and episode != parsed_episode:
        errors.append("episode metrics do not match the raw evaluator row")

    return {
        "path": str(path),
        "detected": True,
        "valid": not errors,
        "errors": errors,
        "run_id": document.get("run_id"),
        "raw_result_path": str(raw_path) if raw_path is not None else None,
        "episode": parsed_episode,
        "official_protocol": False,
        "parcel_adapter_exercised": False,
        "top_decile_evidence": False,
    }


def _public_report_status(
    path: Path,
    *,
    image_sha256: str | None,
    expected_commit: str,
    public_indices: list[int],
    trials_per_world: int,
) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "detected": False, "valid": False, "errors": ["missing"]}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "path": str(path),
            "detected": True,
            "valid": False,
            "errors": [f"invalid JSON: {exc}"],
        }
    errors: list[str] = []
    expected = {
        "schema_version": 1,
        "evaluation_kind": PUBLIC_EVALUATION_KIND,
        "source_commit": expected_commit,
        "world_indices": public_indices,
        "trials_per_world": trials_per_world,
        "episode_count": len(public_indices) * trials_per_world,
        "official_protocol": False,
        "organizer_attested": False,
        "image_sha256": image_sha256,
    }
    if not isinstance(report, dict):
        errors.append("report must be an object")
    else:
        for key, value in expected.items():
            if report.get(key) != value:
                errors.append(f"{key} mismatch")
        raw_digest = report.get("raw_output_sha256")
        if not isinstance(raw_digest, str) or re.fullmatch(r"[0-9a-f]{64}", raw_digest) is None:
            errors.append("raw_output_sha256 must be a lowercase SHA-256")
        if not isinstance(report.get("metrics"), dict):
            errors.append("metrics must be an object")
    return {
        "path": str(path),
        "detected": True,
        "valid": not errors,
        "errors": errors,
    }


def audit_barn_ros2_readiness(
    *,
    repo_root: str | Path = REPO_ROOT,
    checkout_root: str | Path | None = None,
    runtime_package_path: str | Path | None = None,
    runtime_rootfs_path: str | Path | None = None,
    image_path: str | Path | None = None,
    public_report_path: str | Path | None = None,
    rootless_proot_path: str | Path | None = None,
    rootless_build_rootfs_path: str | Path | None = None,
    rootless_smoke_evidence_path: str | Path | None = None,
    os_release_path: str | Path = "/etc/os-release",
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return host, source, protocol, and official-eligibility readiness.

    This function is strictly read-only.  In particular, it does not run
    ``rosdep``, build an image, initialize ROS, or contact the organizer.
    """

    manifest = load_runtime_manifest()
    locked = load_lock()
    source = locked.get(SOURCE_ID)
    expected_commit = str(manifest["official_sources"]["repository_commit"])
    expected_origin = str(manifest["official_sources"]["repository"])
    lock_matches = bool(
        source
        and source.get("commit") == expected_commit
        and _normalized_git_url(str(source.get("url", ""))) == _normalized_git_url(expected_origin)
    )

    root = Path(repo_root).expanduser().resolve()
    checkout_base = (
        Path(checkout_root).expanduser().resolve()
        if checkout_root is not None
        else (root / DEFAULT_DESTINATION.relative_to(REPO_ROOT)).resolve()
    )
    checkout = _git_checkout_status(
        checkout_base / SOURCE_ID,
        expected_commit,
        expected_origin,
    )

    os_text = _read_text(Path(os_release_path)) or ""
    os_release = parse_os_release(os_text)
    architecture = platform.machine()
    native_ros_supported = (
        os_release.get("ID") == "ubuntu"
        and os_release.get("VERSION_ID") == "24.04"
        and architecture == "x86_64"
    )

    singularity = _command_version("singularity", ("version",))
    parsed_runtime_version = (
        parse_singularity_version(str(singularity["output"])) if singularity["detected"] else None
    )
    tested_runtime_version = str(manifest["container"]["tested_version"])
    singularity["version"] = parsed_runtime_version
    singularity["matches_tested_version"] = parsed_runtime_version == tested_runtime_version
    apptainer = _command_version("apptainer", ("version",))

    resolved_runtime_package = (
        Path(runtime_package_path).expanduser().resolve()
        if runtime_package_path is not None
        else (root / DEFAULT_PACKAGE_PATH.relative_to(REPO_ROOT)).resolve()
    )
    resolved_runtime_rootfs = (
        Path(runtime_rootfs_path).expanduser().resolve()
        if runtime_rootfs_path is not None
        else (root / DEFAULT_ROOTFS_PATH.relative_to(REPO_ROOT)).resolve()
    )
    runtime_package = inspect_runtime_package(resolved_runtime_package, manifest)
    extracted_runtime = inspect_runtime_rootfs(resolved_runtime_rootfs, manifest)

    rootless_manifest = manifest["rootless_diagnostic"]
    resolved_proot = (
        Path(rootless_proot_path).expanduser().resolve()
        if rootless_proot_path is not None
        else (root / DEFAULT_ROOTLESS_PROOT_PATH.relative_to(REPO_ROOT)).resolve()
    )
    proot_artifact = _pinned_file_status(
        resolved_proot,
        expected_sha256=str(rootless_manifest["proot_sha256"]),
        expected_size=int(rootless_manifest["proot_size_bytes"]),
    )
    resolved_build_rootfs = (
        Path(rootless_build_rootfs_path).expanduser().resolve()
        if rootless_build_rootfs_path is not None
        else (root / DEFAULT_ROOTLESS_BUILD_ROOTFS.relative_to(REPO_ROOT)).resolve()
    )
    rootless_build_rootfs = _rootless_build_rootfs_status(
        resolved_build_rootfs,
        critical_source_hashes=manifest["official_sources"]["critical_files_sha256"],
    )
    resolved_smoke_evidence = (
        Path(rootless_smoke_evidence_path).expanduser().resolve()
        if rootless_smoke_evidence_path is not None
        else (root / DEFAULT_ROOTLESS_SMOKE_EVIDENCE.relative_to(REPO_ROOT)).resolve()
    )
    rootless_smoke_evidence = _rootless_smoke_evidence_status(
        resolved_smoke_evidence,
        manifest=manifest,
    )

    env = dict(os.environ if environment is None else environment)
    username = env.get("USER") or env.get("LOGNAME") or ""
    userns_text = _read_text(Path("/proc/sys/kernel/unprivileged_userns_clone"))
    userns_enabled = userns_text is None or userns_text.strip() == "1"
    userns_creation_probe = _user_namespace_probe("unshare", ("--user", "true"))
    root_mapping_probe = _user_namespace_probe("unshare", ("--user", "--map-root-user", "true"))
    bubblewrap = _command_version("bwrap", ("--version",))
    bubblewrap_root_mapping_probe = _user_namespace_probe(
        "bwrap",
        (
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--uid",
            "0",
            "--gid",
            "0",
            "--unshare-pid",
            "--die-with-parent",
            "/bin/true",
        ),
    )
    apparmor_restriction_text = _read_text(
        Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    )
    apparmor_restricts_userns = (
        apparmor_restriction_text is not None and apparmor_restriction_text.strip() == "1"
    )
    fakeroot_prerequisites = {
        "unprivileged_user_namespaces_sysctl": userns_enabled,
        "user_namespace_creation_probe": userns_creation_probe["ready"],
        "root_uid_mapping_probe": root_mapping_probe["ready"],
        "apparmor_restrict_unprivileged_userns": apparmor_restricts_userns,
        "subuid_mapping": bool(username and _mapping_present(Path("/etc/subuid"), username)),
        "subgid_mapping": bool(username and _mapping_present(Path("/etc/subgid"), username)),
        "newuidmap": shutil.which("newuidmap") is not None,
        "newgidmap": shutil.which("newgidmap") is not None,
    }
    fakeroot_ready = all(
        fakeroot_prerequisites[key]
        for key in (
            "unprivileged_user_namespaces_sysctl",
            "user_namespace_creation_probe",
            "root_uid_mapping_probe",
            "subuid_mapping",
            "subgid_mapping",
            "newuidmap",
            "newgidmap",
        )
    )

    gpu_probe = _command_version(
        "nvidia-smi",
        ("--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"),
    )
    adapter_files = (
        root / "evals/external/barn_ros2_adapter.py",
        root / "evals/external/barn_ros2_node.py",
    )
    adapter_ready = all(path.is_file() for path in adapter_files)
    source_provenance_ready = bool(lock_matches and checkout["provenance_verified"])
    build_prerequisites_ready = bool(
        source_provenance_ready and singularity["matches_tested_version"] and adapter_ready
    )
    resolved_image_path = (
        Path(image_path).expanduser().resolve()
        if image_path is not None
        else root / ".cache/external-evals/images/barn_ros2_public_compat.sif"
    )
    image_detected = resolved_image_path.is_file()
    image_sha256 = _sha256(resolved_image_path) if image_detected else None
    image = {
        "path": str(resolved_image_path),
        "detected": image_detected,
        "sha256": image_sha256,
    }
    resolved_report_path = (
        Path(public_report_path).expanduser().resolve()
        if public_report_path is not None
        else root / ".cache/external-evals/results/barn_ros2_public_compatibility.json"
    )
    public_report = _public_report_status(
        resolved_report_path,
        image_sha256=image_sha256,
        expected_commit=expected_commit,
        public_indices=list(manifest["protocol"]["public_world_indices"]),
        trials_per_world=int(manifest["protocol"]["public_trials_per_world"]),
    )
    public_compatibility_ready = bool(
        build_prerequisites_ready and image_detected and public_report["valid"]
    )

    blockers: list[dict[str, str]] = []
    if not lock_matches:
        blockers.append(
            {
                "id": "source_lock_mismatch",
                "scope": "public_compatibility",
                "detail": f"expected {expected_origin}@{expected_commit}",
            }
        )
    if not checkout["commit_matches"]:
        blockers.append(
            {
                "id": "pinned_ros2_checkout_missing_or_wrong",
                "scope": "public_compatibility",
                "detail": f"fetch {SOURCE_ID} at {expected_commit}",
            }
        )
    elif not checkout["origin_matches"]:
        blockers.append(
            {
                "id": "pinned_ros2_checkout_origin_mismatch",
                "scope": "public_compatibility",
                "detail": f"expected origin {expected_origin}",
            }
        )
    elif not checkout["worktree_clean"]:
        blockers.append(
            {
                "id": "pinned_ros2_checkout_dirty",
                "scope": "public_compatibility",
                "detail": "official evaluator checkout must remain byte-for-byte at the pinned commit",
            }
        )
    if not singularity["matches_tested_version"]:
        staged = bool(runtime_package["verified"] and extracted_runtime["verified"])
        blockers.append(
            {
                "id": (
                    "tested_singularity_runtime_not_installed"
                    if staged
                    else "tested_singularity_runtime_unavailable"
                ),
                "scope": "public_compatibility",
                "detail": (
                    f"SingularityCE {tested_runtime_version} is provenance-verified and staged, "
                    "but extraction/version output does not prove container execution"
                    if staged
                    else f"SingularityCE {tested_runtime_version} is required for the proven path"
                ),
            }
        )
        if staged and not root_mapping_probe["ready"]:
            blockers.append(
                {
                    "id": "rootless_namespace_mapping_blocked",
                    "scope": "rootless_runtime_alternative",
                    "detail": root_mapping_probe["error"]
                    or "unprivileged root UID mapping probe failed",
                }
            )
        if staged and (
            not fakeroot_prerequisites["newuidmap"] or not fakeroot_prerequisites["newgidmap"]
        ):
            blockers.append(
                {
                    "id": "rootless_uidmap_helpers_missing",
                    "scope": "rootless_runtime_alternative",
                    "detail": "newuidmap/newgidmap are required by an unprivileged Singularity fakeroot build",
                }
            )
    if not adapter_ready:
        blockers.append(
            {
                "id": "parcel_ros2_adapter_missing",
                "scope": "public_compatibility",
                "detail": "evaluator-only adapter files are incomplete",
            }
        )
    if not image_detected:
        blockers.append(
            {
                "id": "compatibility_sif_missing",
                "scope": "public_compatibility",
                "detail": str(resolved_image_path),
            }
        )
    if not public_report["valid"]:
        blockers.append(
            {
                "id": "public_500_episode_report_missing_or_invalid",
                "scope": "public_compatibility",
                "detail": str(resolved_report_path),
            }
        )
    blockers.append(
        {
            "id": "organizer_hidden_evaluation_required",
            "scope": "official_score",
            "detail": "Only an organizer-attested 50-hidden-world x 10-trial run is official.",
        }
    )
    if not manifest["eligibility"]["post_event_evaluation_confirmed"]:
        blockers.append(
            {
                "id": "post_event_submission_not_confirmed",
                "scope": "official_score",
                "detail": "The 2026 hard deadline has passed; organizer acceptance must be confirmed.",
            }
        )

    install = manifest["container"]
    commands = {
        "fetch_source": [
            ".parcel/bin/python",
            "evals/external/fetch_sources.py",
            SOURCE_ID,
        ],
        "inspect_staged_runtime": [
            ".parcel/bin/python",
            "-m",
            "evals.external.barn_runtime_package",
        ],
        "prepare_runtime_without_installing": [
            ".parcel/bin/python",
            "-m",
            "evals.external.barn_runtime_package",
            "--prepare",
        ],
        "verify_rootless_smoke_evidence": [
            ".parcel/bin/python",
            "-m",
            "evals.external.barn_official_doctor",
        ],
    }

    host_tools = {
        executable: shutil.which(executable)
        for executable in (
            "bwrap",
            "unshare",
            "newuidmap",
            "newgidmap",
            "dpkg-deb",
            "unsquashfs",
            "mksquashfs",
            "crun",
            "runc",
            "docker",
            "podman",
            "gcc",
            "make",
            "go",
        )
    }

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_id": manifest["runtime_id"],
        "classification": {
            "build_prerequisites_ready": build_prerequisites_ready,
            "public_container_compatibility_ready": public_compatibility_ready,
            "rootless_upstream_smoke_evidence_valid": rootless_smoke_evidence["valid"],
            "official_hidden_protocol_ready": False,
            "official_score_available": False,
            "leaderboard_claim_allowed": False,
            "reason": "Local public-world compatibility and organizer-attested hidden evaluation are separate gates.",
        },
        "host": {
            "os_release": os_release,
            "architecture": architecture,
            "native_ros2_jazzy_supported": native_ros_supported,
            "container_required": not native_ros_supported,
            "python_version": platform.python_version(),
            "singularity": singularity,
            "apptainer_alternative_detected": apptainer,
            "tools": host_tools,
            "fakeroot_prerequisites": fakeroot_prerequisites,
            "fakeroot_ready": fakeroot_ready,
            "user_namespace_probes": {
                "creation": userns_creation_probe,
                "root_uid_mapping": root_mapping_probe,
            },
            "gpu": {
                "detected": gpu_probe["detected"],
                "probe": gpu_probe,
                "required": manifest["gpu"]["required"],
                "local_passthrough_supported_by_upstream_wrapper": manifest["gpu"][
                    "local_passthrough_supported_by_wrapper"
                ],
                "official_simulation_gpu_promised": manifest["gpu"][
                    "organizer_simulation_gpu_promised"
                ],
                "official_physical_final_gpu_available": manifest["gpu"][
                    "official_physical_final_gpu_available"
                ],
                "cpu_compatibility_required": manifest["gpu"]["cpu_compatibility_required"],
            },
        },
        "source": {
            "lock_matches_manifest": lock_matches,
            "provenance_ready": source_provenance_ready,
            "lock": source,
            "checkout": checkout,
        },
        "runtime_artifacts": {
            "package": runtime_package,
            "extracted_rootfs": extracted_runtime,
            "system_packages_installed_by_helper": False,
            "maintainer_scripts_executed_by_helper": False,
            "extraction_is_runtime_exec_proof": False,
        },
        "rootless_diagnostic": {
            "bubblewrap": bubblewrap,
            "bubblewrap_root_mapping_probe": bubblewrap_root_mapping_probe,
            "proot": proot_artifact,
            "build_rootfs": rootless_build_rootfs,
            "smoke_evidence": rootless_smoke_evidence,
            "current_cache_replay_ready": bool(
                bubblewrap_root_mapping_probe["ready"]
                and proot_artifact["verified"]
                and rootless_build_rootfs.get("ready_for_diagnostic_replay")
            ),
            "official_compatibility_gate": False,
            "public_500_episode_gate_satisfied": False,
            "parcel_navigation_score": False,
            "top_decile_evidence": False,
            "note": rootless_manifest["note"],
        },
        "adapter": {
            "ready": adapter_ready,
            "files": [str(path) for path in adapter_files],
            "production_package_modified": False,
            "official_evaluator_modified": False,
            "documented_hook_only": True,
        },
        "container_image": image,
        "public_compatibility_report": public_report,
        "protocol": manifest["protocol"],
        "known_upstream_findings": manifest["known_upstream_findings"],
        "eligibility": manifest["eligibility"],
        "blockers": blockers,
        "safe_next_commands": commands,
        "runtime_installer_sha256": install["installer_sha256"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require",
        choices=("none", "public", "official"),
        default="none",
        help="return nonzero unless the selected gate is ready",
    )
    parser.add_argument("--checkout-root", type=Path)
    parser.add_argument("--runtime-package", type=Path)
    parser.add_argument("--runtime-rootfs", type=Path)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--public-report", type=Path)
    parser.add_argument("--rootless-proot", type=Path)
    parser.add_argument("--rootless-build-rootfs", type=Path)
    parser.add_argument("--rootless-smoke-evidence", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_barn_ros2_readiness(
        checkout_root=args.checkout_root,
        runtime_package_path=args.runtime_package,
        runtime_rootfs_path=args.runtime_rootfs,
        image_path=args.image,
        public_report_path=args.public_report,
        rootless_proot_path=args.rootless_proot,
        rootless_build_rootfs_path=args.rootless_build_rootfs,
        rootless_smoke_evidence_path=args.rootless_smoke_evidence,
    )
    print(json.dumps(report, indent=2, sort_keys=False))
    classification = report["classification"]
    if args.require == "public" and not classification["public_container_compatibility_ready"]:
        return 2
    if args.require == "official" and not classification["official_score_available"]:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI wrapper
    raise SystemExit(main())


__all__ = [
    "ROOTLESS_SMOKE_EVALUATION_KIND",
    "RUNTIME_MANIFEST",
    "SOURCE_ID",
    "audit_barn_ros2_readiness",
    "load_runtime_manifest",
    "main",
    "parse_os_release",
    "parse_singularity_version",
]
