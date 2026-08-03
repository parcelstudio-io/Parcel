"""Provenance-checked, non-system preparation for the pinned BARN runtime.

The helper can download and extract the exact upstream SingularityCE Debian
package into Parcel's ignored cache.  It never invokes ``apt``, ``dpkg -i``,
``sudo``, a package maintainer script, or a container build.  Extraction is a
useful staging step, but it is deliberately *not* reported as a working
container runtime: Singularity still needs an executable namespace / setuid
path before the official-compatible definition can run its ``%post`` section.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_MANIFEST = Path(__file__).resolve().parent / "targets" / "barn_ros2_2026_runtime.json"
DEFAULT_RUNTIME_CACHE = REPO_ROOT / ".cache" / "external-evals" / "runtime"
DEFAULT_PACKAGE_PATH = DEFAULT_RUNTIME_CACHE / "singularity-ce_4.3.0-noble_amd64.deb"
DEFAULT_ROOTFS_PATH = DEFAULT_RUNTIME_CACHE / "singularity-ce-4.3.0-noble-rootfs"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_pin(manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw = manifest.get("container")
    if not isinstance(raw, Mapping):
        raise TypeError("BARN runtime manifest has no container object")
    required_strings = (
        "installer_url",
        "installer_sha256",
        "installer_package_version",
        "installer_architecture",
        "tested_version",
    )
    if any(not isinstance(raw.get(key), str) for key in required_strings):
        raise ValueError("BARN runtime manifest has incomplete installer provenance")
    expected_sha256 = str(raw["installer_sha256"])
    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise ValueError("BARN runtime installer SHA-256 is malformed")
    expected_size = raw.get("installer_size_bytes")
    if not isinstance(expected_size, int) or expected_size <= 0:
        raise ValueError("BARN runtime installer size must be positive")
    critical = raw.get("extracted_critical_files_sha256")
    if not isinstance(critical, Mapping) or not critical:
        raise ValueError("BARN runtime manifest has no extracted-file pins")
    normalized: dict[str, str] = {}
    for relative, digest in critical.items():
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
        ):
            raise ValueError("BARN runtime extracted-file pin is malformed")
        normalized[relative] = digest
    return {
        "url": str(raw["installer_url"]),
        "sha256": expected_sha256,
        "size_bytes": expected_size,
        "package_version": str(raw["installer_package_version"]),
        "architecture": str(raw["installer_architecture"]),
        "tested_version": str(raw["tested_version"]),
        "critical_files_sha256": normalized,
    }


def _deb_fields(path: Path) -> dict[str, Any]:
    executable = shutil.which("dpkg-deb")
    if executable is None:
        return {"available": False, "fields": {}, "error": "dpkg-deb not found"}
    try:
        result = subprocess.run(
            [executable, "--field", str(path), "Package", "Version", "Architecture"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": True, "fields": {}, "error": str(exc)}
    if result.returncode != 0:
        return {
            "available": True,
            "fields": {},
            "error": (result.stderr or f"exit {result.returncode}").strip(),
        }
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().lower()] = value.strip()
    return {"available": True, "fields": fields, "error": None}


def inspect_runtime_package(
    path: str | Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Inspect the pinned installer without running it or a maintainer script."""

    pin = _runtime_pin(manifest)
    package = Path(path).expanduser().resolve()
    if not package.is_file():
        return {
            "path": str(package),
            "detected": False,
            "verified": False,
            "size_bytes": None,
            "sha256": None,
            "errors": ["missing"],
        }
    errors: list[str] = []
    size = package.stat().st_size
    digest = _sha256(package)
    if size != pin["size_bytes"]:
        errors.append("size mismatch")
    if digest != pin["sha256"]:
        errors.append("sha256 mismatch")
    deb = _deb_fields(package)
    fields = deb["fields"]
    if deb["error"] is not None:
        errors.append(f"package metadata unavailable: {deb['error']}")
    else:
        if fields.get("package") != "singularity-ce":
            errors.append("package name mismatch")
        if fields.get("version") != pin["package_version"]:
            errors.append("package version mismatch")
        if fields.get("architecture") != pin["architecture"]:
            errors.append("package architecture mismatch")
    return {
        "path": str(package),
        "detected": True,
        "verified": not errors,
        "size_bytes": size,
        "expected_size_bytes": pin["size_bytes"],
        "sha256": digest,
        "expected_sha256": pin["sha256"],
        "deb_metadata": deb,
        "errors": errors,
    }


def _probe_extracted_version(binary: Path, config: Path) -> dict[str, Any]:
    """Run only ``singularity version`` in a read-only Bubblewrap view."""

    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        return {
            "attempted": False,
            "detected": False,
            "output": None,
            "error": "bwrap not found; extracted package was not executed directly",
        }
    try:
        result = subprocess.run(
            [
                bubblewrap,
                "--ro-bind",
                "/",
                "/",
                "--uid",
                "0",
                "--gid",
                "0",
                str(binary),
                "--config",
                str(config),
                "version",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"attempted": True, "detected": False, "output": None, "error": str(exc)}
    output = (result.stdout or result.stderr).strip()
    return {
        "attempted": True,
        "detected": result.returncode == 0,
        "output": output,
        "error": None if result.returncode == 0 else f"exit {result.returncode}",
    }


def inspect_runtime_rootfs(
    path: str | Path,
    manifest: Mapping[str, Any],
    *,
    probe_version: bool = True,
) -> dict[str, Any]:
    """Verify critical extracted files against hashes rooted in the `.deb` pin."""

    pin = _runtime_pin(manifest)
    root = Path(path).expanduser().resolve()
    errors: list[str] = []
    files: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return {
            "path": str(root),
            "detected": False,
            "verified": False,
            "files": files,
            "version_probe": {"attempted": False, "detected": False, "output": None},
            "runtime_exec_ready": False,
            "errors": ["missing"],
        }
    for relative, expected in pin["critical_files_sha256"].items():
        candidate = root / relative
        detected = candidate.is_file()
        actual = _sha256(candidate) if detected else None
        matches = actual == expected
        files[relative] = {
            "path": str(candidate),
            "detected": detected,
            "sha256": actual,
            "expected_sha256": expected,
            "matches": matches,
        }
        if not detected:
            errors.append(f"missing critical file: {relative}")
        elif not matches:
            errors.append(f"critical file hash mismatch: {relative}")
    binary = root / "usr/bin/singularity"
    config = root / "etc/singularity/singularity.conf"
    version_probe = (
        _probe_extracted_version(binary, config)
        if probe_version and not errors
        else {"attempted": False, "detected": False, "output": None, "error": None}
    )
    expected_output = f"{pin['tested_version']}-noble"
    if version_probe["attempted"] and (
        not version_probe["detected"] or version_probe["output"] != expected_output
    ):
        errors.append("extracted runtime version probe mismatch")
    return {
        "path": str(root),
        "detected": True,
        "verified": not errors,
        "files": files,
        "version_probe": version_probe,
        # Extraction / version probing is not proof that namespace creation,
        # `%post`, SIF execution, or the evaluator can run.
        "runtime_exec_ready": False,
        "errors": errors,
    }


def fetch_runtime_package(
    destination: str | Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Download the pinned package atomically and refuse any mismatching file."""

    pin = _runtime_pin(manifest)
    target = Path(destination).expanduser().resolve()
    if target.exists():
        status = inspect_runtime_package(target, manifest)
        if not status["verified"]:
            raise FileExistsError(f"refusing to overwrite unverified runtime package: {target}")
        return status
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(pin["url"], headers={"User-Agent": "Parcel-BARN-audit/1"})
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".part", dir=target.parent
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(temporary_fd, "wb") as stream, urllib.request.urlopen(
            request, timeout=60.0
        ) as response:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if size != pin["size_bytes"] or digest.hexdigest() != pin["sha256"]:
            raise ValueError("downloaded SingularityCE package failed size/SHA-256 verification")
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise FileExistsError(f"refusing to race an existing runtime package: {target}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return inspect_runtime_package(target, manifest)


def extract_runtime_package(
    package_path: str | Path,
    destination: str | Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract a verified `.deb` without installing it or running scripts."""

    package = Path(package_path).expanduser().resolve()
    package_status = inspect_runtime_package(package, manifest)
    if not package_status["verified"]:
        raise ValueError(f"runtime package is not provenance verified: {package}")
    target = Path(destination).expanduser().resolve()
    if target.exists():
        status = inspect_runtime_rootfs(target, manifest)
        if not status["verified"]:
            raise FileExistsError(f"refusing to replace unverified runtime rootfs: {target}")
        return status
    executable = shutil.which("dpkg-deb")
    if executable is None:
        raise RuntimeError("dpkg-deb is required for script-free package extraction")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        result = subprocess.run(
            [executable, "--extract", str(package), str(staging)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120.0,
        )
        if result.returncode != 0:
            detail = (result.stderr or f"exit {result.returncode}").strip()
            raise RuntimeError(f"dpkg-deb extraction failed: {detail}")
        status = inspect_runtime_rootfs(staging, manifest)
        if not status["verified"]:
            raise RuntimeError(f"extracted runtime failed verification: {status['errors']}")
        if target.exists():
            raise FileExistsError(f"refusing to race an existing runtime rootfs: {target}")
        staging.rename(target)
    finally:
        if staging.exists():
            # `staging` is a uniquely generated child of the validated target
            # parent. It never points at user-selected data.
            shutil.rmtree(staging)
    return inspect_runtime_rootfs(target, manifest)


def _load_manifest() -> dict[str, Any]:
    try:
        document = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load BARN runtime manifest: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("BARN runtime manifest must be a schema-version-1 object")
    _runtime_pin(document)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--fetch", action="store_true", help="download and verify the `.deb`")
    actions.add_argument("--extract", action="store_true", help="extract an existing verified `.deb`")
    actions.add_argument("--prepare", action="store_true", help="fetch, verify, and extract")
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE_PATH)
    parser.add_argument("--rootfs", type=Path, default=DEFAULT_ROOTFS_PATH)
    args = parser.parse_args(argv)

    manifest = _load_manifest()
    if args.fetch or args.prepare:
        fetch_runtime_package(args.package, manifest)
    if args.extract or args.prepare:
        extract_runtime_package(args.package, args.rootfs, manifest)
    report = {
        "schema_version": 1,
        "operation": (
            "prepare"
            if args.prepare
            else "fetch"
            if args.fetch
            else "extract"
            if args.extract
            else "inspect"
        ),
        "system_packages_installed": False,
        "maintainer_scripts_executed": False,
        "container_runtime_claimed_ready": False,
        "package": inspect_runtime_package(args.package, manifest),
        "rootfs": inspect_runtime_rootfs(args.rootfs, manifest),
    }
    print(json.dumps(report, indent=2, sort_keys=False))
    return 0 if report["package"]["verified"] else 2


if __name__ == "__main__":  # pragma: no cover - CLI wrapper
    raise SystemExit(main())


__all__ = [
    "DEFAULT_PACKAGE_PATH",
    "DEFAULT_ROOTFS_PATH",
    "extract_runtime_package",
    "fetch_runtime_package",
    "inspect_runtime_package",
    "inspect_runtime_rootfs",
    "main",
]
