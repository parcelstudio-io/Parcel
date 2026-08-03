#!/usr/bin/env python3
"""Fetch and safely stage Parcel's exact upstream llama.cpp CUDA OCI image.

The default operation is read-only inspection. ``--prepare`` downloads only
the manifest-pinned blobs into the gitignored ``third_party`` cache, verifies
every size and SHA-256, and assembles a new root filesystem in a fresh staging
directory. It never invokes a package manager, container hook, or image
entrypoint and never replaces the existing CPU llama.cpp binary.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = REPO_ROOT / "configs/reasoner/llama_cpp_cuda12_oci_b10236.json"
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})")


class OciStageError(RuntimeError):
    """Raised when provenance or safe cache assembly cannot be established."""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward the registry bearer token to a cross-host blob URL."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Mapping[str, str],
        new_url: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )
        if redirected is None:
            return None
        old_host = urllib.parse.urlsplit(request.full_url).hostname
        new_host = urllib.parse.urlsplit(new_url).hostname
        if old_host != new_host:
            redirected.remove_header("Authorization")
        return redirected


_OPENER = urllib.request.build_opener(_SafeRedirectHandler())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_hex(value: object, label: str) -> str:
    match = _DIGEST.fullmatch(str(value))
    if match is None:
        raise OciStageError(f"{label} must be a sha256 OCI digest")
    return match.group(1)


def _load_profile(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OciStageError(f"cannot load OCI reasoner profile: {error}") from error
    if not isinstance(profile, dict) or profile.get("schema_version") != 1:
        raise OciStageError("OCI reasoner profile must be a schema-version-1 object")
    distribution = profile.get("distribution")
    if not isinstance(distribution, dict) or distribution.get("kind") != "oci_image":
        raise OciStageError("profile must contain an OCI image distribution")
    for key in ("registry", "repository", "tag", "rootfs_dir", "entrypoint"):
        if not isinstance(distribution.get(key), str) or not distribution[key]:
            raise OciStageError(f"distribution.{key} must be non-empty text")
    _digest_hex(distribution.get("index_digest"), "distribution.index_digest")
    _digest_hex(distribution.get("manifest_digest"), "distribution.manifest_digest")
    config = distribution.get("config")
    if not isinstance(config, dict) or not isinstance(config.get("size"), int):
        raise OciStageError("distribution.config must pin digest and size")
    _digest_hex(config.get("digest"), "distribution.config.digest")
    layers = distribution.get("layers")
    if not isinstance(layers, list) or not layers:
        raise OciStageError("distribution.layers must be a non-empty list")
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict) or not isinstance(layer.get("size"), int):
            raise OciStageError(f"distribution.layers[{index}] must pin digest and size")
        _digest_hex(layer.get("digest"), f"distribution.layers[{index}].digest")
        if layer["size"] <= 0:
            raise OciStageError(f"distribution.layers[{index}].size must be positive")
    critical_files = distribution.get("critical_files")
    if not isinstance(critical_files, list) or not critical_files:
        raise OciStageError("distribution.critical_files must be a non-empty list")
    for index, item in enumerate(critical_files):
        if not isinstance(item, dict):
            raise OciStageError(f"distribution.critical_files[{index}] must be an object")
        path_value = item.get("path")
        if (
            not isinstance(path_value, str)
            or not path_value
            or Path(path_value).is_absolute()
            or ".." in Path(path_value).parts
        ):
            raise OciStageError(f"distribution.critical_files[{index}].path is unsafe")
        if not isinstance(item.get("size"), int) or item["size"] <= 0:
            raise OciStageError(f"distribution.critical_files[{index}].size must be positive")
        if re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) is None:
            raise OciStageError(f"distribution.critical_files[{index}].sha256 is invalid")
    return profile, distribution


def _managed_paths(distribution: Mapping[str, Any]) -> tuple[Path, Path, Path]:
    managed_root = (REPO_ROOT / "third_party/llama.cpp-oci").resolve()
    rootfs = (REPO_ROOT / str(distribution["rootfs_dir"])).resolve()
    if not rootfs.is_relative_to(managed_root) or rootfs == managed_root:
        raise OciStageError(f"rootfs must be a child of {managed_root}, got {rootfs}")
    cache_root = rootfs.parent
    blobs = cache_root / "blobs/sha256"
    return cache_root, blobs, rootfs


def _request_bytes(url: str, *, token: str | None = None, accept: str | None = None) -> bytes:
    headers = {"User-Agent": "Parcel-OCI-Provenance/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    try:
        with _OPENER.open(request, timeout=60) as response:
            return response.read()
    except OSError as error:
        raise OciStageError(f"request failed for {url}: {error}") from error


def _registry_token(distribution: Mapping[str, Any]) -> str:
    query = urllib.parse.urlencode(
        {
            "scope": f"repository:{distribution['repository']}:pull",
            "service": str(distribution["registry"]),
        }
    )
    payload = _request_bytes(f"https://{distribution['registry']}/token?{query}")
    try:
        token = json.loads(payload)["token"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise OciStageError("registry did not return a bearer token") from error
    if not isinstance(token, str) or not token:
        raise OciStageError("registry bearer token is empty")
    return token


def _registry_url(distribution: Mapping[str, Any], suffix: str) -> str:
    return f"https://{distribution['registry']}/v2/{distribution['repository']}/{suffix}"


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise OciStageError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise OciStageError(f"{label} must be a JSON object")
    return value


def _verify_remote_manifests(
    profile: Mapping[str, Any],
    distribution: Mapping[str, Any],
    token: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    accept = "application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json"
    tag_payload = _request_bytes(
        _registry_url(distribution, f"manifests/{distribution['tag']}"),
        token=token,
        accept=accept,
    )
    if hashlib.sha256(tag_payload).hexdigest() != _digest_hex(
        distribution["index_digest"], "distribution.index_digest"
    ):
        raise OciStageError("build-specific OCI tag no longer matches the pinned index digest")
    index = _json_object(tag_payload, "OCI index")
    platform = distribution.get("platform")
    matches = [
        item
        for item in index.get("manifests", [])
        if isinstance(item, dict) and item.get("platform") == platform
    ]
    if len(matches) != 1 or matches[0].get("digest") != distribution["manifest_digest"]:
        raise OciStageError("OCI index does not select the pinned platform manifest")

    manifest_payload = _request_bytes(
        _registry_url(distribution, f"manifests/{distribution['manifest_digest']}"),
        token=token,
        accept="application/vnd.oci.image.manifest.v1+json",
    )
    if hashlib.sha256(manifest_payload).hexdigest() != _digest_hex(
        distribution["manifest_digest"], "distribution.manifest_digest"
    ):
        raise OciStageError("OCI platform manifest digest mismatch")
    manifest = _json_object(manifest_payload, "OCI platform manifest")
    expected_config = distribution["config"]
    if manifest.get("config") != {
        "mediaType": "application/vnd.oci.image.config.v1+json",
        "digest": expected_config["digest"],
        "size": expected_config["size"],
    }:
        raise OciStageError("OCI platform manifest config descriptor mismatch")
    actual_layers = [
        {"digest": item.get("digest"), "size": item.get("size")}
        for item in manifest.get("layers", [])
        if isinstance(item, dict)
    ]
    if actual_layers != distribution["layers"]:
        raise OciStageError("OCI platform manifest layer descriptors changed")

    config_payload = _request_bytes(
        _registry_url(distribution, f"blobs/{expected_config['digest']}"),
        token=token,
    )
    if len(config_payload) != expected_config["size"] or hashlib.sha256(
        config_payload
    ).hexdigest() != _digest_hex(expected_config["digest"], "distribution.config.digest"):
        raise OciStageError("OCI config size or digest mismatch")
    config = _json_object(config_payload, "OCI config")
    labels = config.get("config", {}).get("Labels", {})
    source = profile["source"]
    if (
        labels.get("org.opencontainers.image.version") != distribution["expected_image_version"]
        or labels.get("org.opencontainers.image.revision") != source["commit"]
        or labels.get("org.opencontainers.image.revision")
        != distribution["expected_image_revision"]
    ):
        raise OciStageError("OCI labels do not identify the pinned llama.cpp source/build")
    return manifest, config


def _blob_status(path: Path, descriptor: Mapping[str, Any], *, verify_hash: bool) -> dict[str, Any]:
    expected_hash = _digest_hex(descriptor["digest"], "blob digest")
    detected = path.is_file()
    size = path.stat().st_size if detected else None
    actual_hash = _sha256(path) if detected and verify_hash and size == descriptor["size"] else None
    return {
        "path": str(path),
        "detected": detected,
        "size_bytes": size,
        "expected_size_bytes": descriptor["size"],
        "size_matches": size == descriptor["size"],
        "sha256": actual_hash,
        "expected_sha256": expected_hash,
        "hash_verified": verify_hash,
        "ready": detected and size == descriptor["size"] and actual_hash == expected_hash,
    }


def _critical_file_status(rootfs: Path, descriptor: Mapping[str, Any]) -> dict[str, Any]:
    path = rootfs / str(descriptor["path"])
    detected = path.is_file()
    size = path.stat().st_size if detected else None
    actual_hash = _sha256(path) if detected and size == descriptor["size"] else None
    return {
        "path": str(path),
        "relative_path": descriptor["path"],
        "detected": detected,
        "size_bytes": size,
        "expected_size_bytes": descriptor["size"],
        "size_matches": size == descriptor["size"],
        "sha256": actual_hash,
        "expected_sha256": descriptor["sha256"],
        "ready": detected and size == descriptor["size"] and actual_hash == descriptor["sha256"],
    }


def _download_blob(
    distribution: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    target: Path,
    token: str,
) -> None:
    expected_size = int(descriptor["size"])
    expected_hash = _digest_hex(descriptor["digest"], "blob digest")
    if target.exists():
        status = _blob_status(target, descriptor, verify_hash=True)
        if status["ready"]:
            return
        raise OciStageError(f"refusing to overwrite invalid cached blob {target}")

    incomplete = target.with_suffix(".incomplete")
    target.parent.mkdir(parents=True, exist_ok=True)
    offset = incomplete.stat().st_size if incomplete.is_file() else 0
    if offset > expected_size:
        raise OciStageError(f"partial blob exceeds expected size: {incomplete}")
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Parcel-OCI-Provenance/1",
    }
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(
        _registry_url(distribution, f"blobs/{descriptor['digest']}"),
        headers=headers,
    )
    try:
        response = _OPENER.open(request, timeout=120)
    except OSError as error:
        raise OciStageError(f"cannot download OCI blob {descriptor['digest']}: {error}") from error
    with response:
        append = offset > 0 and getattr(response, "status", None) == 206
        if offset and not append:
            offset = 0
        mode = "ab" if append else "wb"
        downloaded = offset
        next_notice = ((downloaded // (256 * 2**20)) + 1) * (256 * 2**20)
        with incomplete.open(mode) as stream:
            while chunk := response.read(8 * 1024 * 1024):
                stream.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_notice:
                    print(
                        f"downloaded {downloaded / 2**20:.0f}/{expected_size / 2**20:.0f} MiB "
                        f"for {expected_hash[:12]}",
                        flush=True,
                    )
                    next_notice += 256 * 2**20
    if incomplete.stat().st_size != expected_size:
        raise OciStageError(f"downloaded blob size mismatch for {descriptor['digest']}")
    if _sha256(incomplete) != expected_hash:
        raise OciStageError(f"downloaded blob digest mismatch for {descriptor['digest']}")
    os.replace(incomplete, target)


def _member_path(staging: Path, raw_name: str) -> Path:
    normalized = raw_name.removeprefix("./")
    if not normalized or Path(normalized).is_absolute() or ".." in Path(normalized).parts:
        raise OciStageError(f"unsafe OCI layer member path: {raw_name!r}")
    target = staging / normalized
    resolved_parent = target.parent.resolve(strict=False)
    if not resolved_parent.is_relative_to(staging):
        raise OciStageError(f"OCI layer member traverses a symlink outside rootfs: {raw_name!r}")
    return target


def _remove_managed_whiteout(target: Path, staging: Path) -> None:
    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(staging):
        raise OciStageError(f"OCI whiteout escapes staged rootfs: {target}")
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)


def _apply_layer(layer: Path, staging: Path) -> None:
    with tarfile.open(layer, mode="r:gz") as archive:
        members = archive.getmembers()
        ordinary: list[tarfile.TarInfo] = []
        for member in members:
            target = _member_path(staging, member.name)
            name = target.name
            if name == ".wh..wh..opq":
                parent = target.parent
                if parent.is_dir():
                    for child in tuple(parent.iterdir()):
                        _remove_managed_whiteout(child, staging)
                continue
            if name.startswith(".wh."):
                _remove_managed_whiteout(target.with_name(name[4:]), staging)
                continue
            if (member.issym() or member.islnk()) and Path(member.linkname).is_absolute():
                # Container-absolute links (for example /usr/bin/mawk) must
                # remain rootfs-relative when staged outside a mount namespace.
                # Rebase them before Python's data filter so later access can
                # never follow the link into the host filesystem.
                rewritten = copy.copy(member)
                rooted_target = staging / member.linkname.lstrip("/")
                if member.issym():
                    rewritten.linkname = os.path.relpath(rooted_target, target.parent)
                else:
                    rewritten.linkname = rooted_target.relative_to(staging).as_posix()
                member = rewritten
            ordinary.append(member)
        archive.extractall(staging, members=ordinary, filter="data")


def _assemble_rootfs(
    distribution: Mapping[str, Any],
    blob_paths: Iterable[Path],
    rootfs: Path,
) -> None:
    if rootfs.exists():
        marker = rootfs / ".parcel-oci-provenance.json"
        if marker.is_file():
            return
        raise OciStageError(f"refusing to replace an unverified rootfs: {rootfs}")
    rootfs.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rootfs-", dir=rootfs.parent)).resolve()
    try:
        for index, layer in enumerate(blob_paths, start=1):
            print(f"applying OCI layer {index}: {layer.name[:12]}", flush=True)
            _apply_layer(layer, staging)
        entrypoint = staging / str(distribution["entrypoint"])
        if not entrypoint.is_file() or not os.access(entrypoint, os.X_OK):
            raise OciStageError(f"staged OCI entrypoint is missing or not executable: {entrypoint}")
        marker = {
            "schema_version": 1,
            "index_digest": distribution["index_digest"],
            "manifest_digest": distribution["manifest_digest"],
            "config_digest": distribution["config"]["digest"],
            "layer_digests": [item["digest"] for item in distribution["layers"]],
            "entrypoint": distribution["entrypoint"],
            "entrypoint_sha256": _sha256(entrypoint),
            "executed": False,
        }
        (staging / ".parcel-oci-provenance.json").write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(rootfs)
    except Exception:
        if staging.exists() and staging.is_relative_to(rootfs.parent):
            shutil.rmtree(staging)
        raise


def inspect_or_prepare(profile_path: Path, *, prepare: bool) -> dict[str, Any]:
    profile, distribution = _load_profile(profile_path)
    cache_root, blobs, rootfs = _managed_paths(distribution)
    token = _registry_token(distribution)
    _manifest, config = _verify_remote_manifests(profile, distribution, token)
    descriptors = distribution["layers"]
    paths = [blobs / _digest_hex(item["digest"], "layer digest") for item in descriptors]
    if prepare:
        for index, (descriptor, path) in enumerate(zip(descriptors, paths, strict=True), start=1):
            print(
                f"preparing OCI layer {index}/{len(paths)} ({descriptor['size'] / 2**20:.1f} MiB)",
                flush=True,
            )
            _download_blob(distribution, descriptor, path, token)
        _assemble_rootfs(distribution, paths, rootfs)

    blob_status = [
        _blob_status(path, descriptor, verify_hash=True)
        for path, descriptor in zip(paths, descriptors, strict=True)
    ]
    marker_path = rootfs / ".parcel-oci-provenance.json"
    marker: dict[str, Any] | None = None
    if marker_path.is_file():
        marker = _json_object(marker_path.read_bytes(), "rootfs provenance marker")
    entrypoint = rootfs / str(distribution["entrypoint"])
    critical_status = [
        _critical_file_status(rootfs, descriptor) for descriptor in distribution["critical_files"]
    ]
    rootfs_ready = bool(
        marker
        and marker.get("manifest_digest") == distribution["manifest_digest"]
        and marker.get("layer_digests") == [item["digest"] for item in descriptors]
        and entrypoint.is_file()
        and os.access(entrypoint, os.X_OK)
        and marker.get("entrypoint_sha256") == _sha256(entrypoint)
        and all(bool(item["ready"]) for item in critical_status)
    )
    return {
        "schema_version": 1,
        "profile_id": profile["profile_id"],
        "source_commit": profile["source"]["commit"],
        "distribution": {
            "tag": distribution["tag"],
            "index_digest": distribution["index_digest"],
            "manifest_digest": distribution["manifest_digest"],
            "config_digest": distribution["config"]["digest"],
            "config_created": config.get("created"),
            "cuda_version": distribution["cuda_version"],
        },
        "cache": {
            "root": str(cache_root),
            "blob_count": len(blob_status),
            "verified_blob_count": sum(bool(item["ready"]) for item in blob_status),
            "critical_file_count": len(critical_status),
            "verified_critical_file_count": sum(bool(item["ready"]) for item in critical_status),
            "expected_compressed_bytes": sum(int(item["size"]) for item in descriptors),
            "rootfs": str(rootfs),
            "rootfs_ready": rootfs_ready,
            "entrypoint": str(entrypoint),
            "entrypoint_sha256": marker.get("entrypoint_sha256") if marker else None,
        },
        "classification": {
            "remote_provenance_ready": True,
            "all_blobs_verified": all(bool(item["ready"]) for item in blob_status),
            "all_critical_files_verified": all(bool(item["ready"]) for item in critical_status),
            "rootfs_ready": rootfs_ready,
            "entrypoint_executed": False,
            "gpu_inference_ready": False,
        },
        "claims": {
            "package_installed": False,
            "container_hooks_executed": False,
            "model_loaded": False,
            "planner_run_performed": False,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = inspect_or_prepare(args.profile.resolve(), prepare=args.prepare)
    print(json.dumps(report, indent=None if args.compact else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OciStageError as error:
        raise SystemExit(f"fetch_reasoner_cuda_oci: {error}") from error
