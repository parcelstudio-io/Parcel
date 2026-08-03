"""Safely materialize and smoke-test the pinned Habitat 2020 OCI image.

The default operation is inspection only.  ``--prepare`` requires the exact
manifest digest as an explicit confirmation, verifies every compressed layer
and uncompressed OCI diff ID, and assembles a fresh managed root filesystem.
It never runs image hooks, an entrypoint, or a package manager.  ``--smoke``
uses Bubblewrap to run only Parcel's fixed no-dataset CUDA/EGL/import probe.
Neither operation runs an evaluator or emits a navigation metric.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .habitat2020_doctor import MANIFEST_PATH, REPO_ROOT, load_manifest
from .habitat2020_image_preflight import (
    fetch_registry_contract,
    probe_host_gpu,
    verify_image_contract,
)

DEFAULT_CACHE_ROOT = REPO_ROOT / ".cache/external-evals/runtime/habitat2020-oci"
DEFAULT_SMOKE_SCRIPT = Path(__file__).with_name("habitat2020_gpu_smoke_py36.py")
REQUIRED_FREE_BYTES = 32 * 1024**3
_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_SAFE_DRIVER_LIBRARY = re.compile(
    r"^(?:libcuda|libEGL_nvidia|libGLX_nvidia|"
    r"libnvidia-(?:allocator|eglcore|glcore|glsi|gpucomp|ptxjitcompiler|tls))\.so(?:\..*)?$"
)
_GLIBC_REQUIREMENT = re.compile(r"\(GLIBC_(\d+)\.(\d+)(?:\.(\d+))?\)")
_ARCHIVED_GLIBC = (2, 27, 0)
_SUPPORTED_LAYER_MEDIA_TYPES = {
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
    "application/vnd.oci.image.layer.v1.tar+gzip",
}
_SMOKE_SENTINEL = "PARCEL_HABITAT_GPU_SMOKE="
_ROOTFS_MARKER = ".parcel-habitat-oci.json"
_HABITAT_ENV = Path("opt/conda/envs/habitat")
_HABITAT_PYTHON = _HABITAT_ENV / "bin/python"
_HABITAT_EGG = _HABITAT_ENV / "lib/python3.6/site-packages/habitat_sim-0.1.4-py3.6-linux-x86_64.egg"
_HABITAT_MODULE = _HABITAT_EGG / "habitat_sim"
_HABITAT_BINDING = _HABITAT_MODULE / "_ext/habitat_sim_bindings.cpython-36m-x86_64-linux-gnu.so"

UrlOpen = Callable[..., Any]


class HabitatOciError(RuntimeError):
    """Raised when the archived runtime cannot be established safely."""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward a registry bearer token to a cross-host blob URL."""

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


_SAFE_OPENER = urllib.request.build_opener(_SafeRedirectHandler())


@dataclass(frozen=True)
class RuntimeLayout:
    cache_root: Path
    image_root: Path
    blobs: Path
    rootfs: Path
    manifest_blob: Path
    config_blob: Path
    metadata: Path


@dataclass(frozen=True)
class GpuBindings:
    devices: tuple[Path, ...]
    libraries: tuple[tuple[str, Path], ...]
    max_required_glibc: tuple[tuple[str, str], ...] = ()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _rootfs_inventory(rootfs: Path) -> dict[str, Any]:
    """Hash every staged rootfs entry except the self-referential marker.

    Entries use depth-first traversal with each directory sorted by raw
    filesystem-name bytes.  Each record is canonical JSON followed by a single
    newline.  Regular-file records include content SHA-256 and size; symlink
    records include the uninterpreted link target; all records include type and
    permission bits.  Special files fail closed.
    """

    if not rootfs.is_dir() or rootfs.is_symlink():
        raise HabitatOciError("rootfs inventory requires a direct directory")
    digest = hashlib.sha256()
    counts = {"directory": 0, "regular_file": 0, "symlink": 0}
    regular_bytes = 0

    def add_record(record: Mapping[str, Any]) -> None:
        payload = json.dumps(
            dict(record),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        digest.update(payload)
        digest.update(b"\n")

    def visit(directory: Path) -> None:
        nonlocal regular_bytes
        try:
            entries = sorted(os.scandir(directory), key=lambda item: os.fsencode(item.name))
        except OSError as exc:
            raise HabitatOciError(f"cannot inventory rootfs directory {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(rootfs).as_posix()
            if relative == _ROOTFS_MARKER:
                continue
            try:
                before = path.lstat()
            except OSError as exc:
                raise HabitatOciError(f"cannot stat rootfs entry {relative}: {exc}") from exc
            mode = stat.S_IMODE(before.st_mode)
            if stat.S_ISDIR(before.st_mode):
                counts["directory"] += 1
                add_record({"mode": mode, "path": relative, "type": "directory"})
                visit(path)
                after = path.lstat()
            elif stat.S_ISLNK(before.st_mode):
                try:
                    target = os.readlink(path)
                    after = path.lstat()
                except OSError as exc:
                    raise HabitatOciError(
                        f"cannot inventory rootfs symlink {relative}: {exc}"
                    ) from exc
                counts["symlink"] += 1
                add_record(
                    {
                        "mode": mode,
                        "path": relative,
                        "target": target,
                        "type": "symlink",
                    }
                )
            elif stat.S_ISREG(before.st_mode):
                flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
                try:
                    descriptor = os.open(path, flags)
                    with os.fdopen(descriptor, "rb") as stream:
                        opened = os.fstat(stream.fileno())
                        file_digest = hashlib.sha256()
                        while chunk := stream.read(8 * 1024 * 1024):
                            file_digest.update(chunk)
                        after = os.fstat(stream.fileno())
                except OSError as exc:
                    raise HabitatOciError(
                        f"cannot inventory rootfs file {relative}: {exc}"
                    ) from exc
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise HabitatOciError(f"rootfs file changed during inventory: {relative}")
                counts["regular_file"] += 1
                regular_bytes += after.st_size
                add_record(
                    {
                        "mode": mode,
                        "path": relative,
                        "sha256": file_digest.hexdigest(),
                        "size": after.st_size,
                        "type": "regular_file",
                    }
                )
            else:
                raise HabitatOciError(f"unsupported rootfs entry type: {relative}")
            stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
            if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
                raise HabitatOciError(f"rootfs entry changed during inventory: {relative}")

    visit(rootfs)
    entry_count = sum(counts.values())
    return {
        "schema_version": 1,
        "algorithm": "sha256-canonical-json-lines-depth-first-raw-name-order-v1",
        "sha256": digest.hexdigest(),
        "entry_count": entry_count,
        "directory_count": counts["directory"],
        "regular_file_count": counts["regular_file"],
        "symlink_count": counts["symlink"],
        "regular_file_bytes": regular_bytes,
        "excluded_paths": [_ROOTFS_MARKER],
    }


def _digest_hex(value: object, label: str) -> str:
    match = _DIGEST.fullmatch(str(value))
    if match is None:
        raise HabitatOciError(f"{label} must be an immutable sha256 digest")
    return match.group(1)


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HabitatOciError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise HabitatOciError(f"{label} must be a JSON object")
    return value


def runtime_layout(
    manifest: Mapping[str, Any],
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> RuntimeLayout:
    digest_hex = _digest_hex(manifest["container"]["base_digest"], "container.base_digest")
    supplied = cache_root.expanduser().absolute()
    resolved = supplied.resolve(strict=False)
    forbidden = {Path("/"), Path.home().resolve(), REPO_ROOT.resolve()}
    if resolved != supplied or resolved in forbidden or len(resolved.parts) < 4:
        raise HabitatOciError(f"unsafe OCI cache root: {cache_root}")
    if cache_root.is_symlink():
        raise HabitatOciError("OCI cache root cannot be a symlink")
    image_root = resolved / digest_hex
    return RuntimeLayout(
        cache_root=resolved,
        image_root=image_root,
        blobs=image_root / "blobs/sha256",
        rootfs=image_root / "rootfs",
        manifest_blob=image_root / "manifests" / digest_hex,
        config_blob=image_root
        / "blobs/sha256"
        / _digest_hex(
            manifest["container"]["registry"]["config_digest"],
            "container.registry.config_digest",
        ),
        metadata=image_root / "rootfs-provenance.json",
    )


def _atomic_verified_write(path: Path, payload: bytes, expected_digest: str) -> None:
    expected_hex = _digest_hex(expected_digest, "cached object digest")
    actual_hex = hashlib.sha256(payload).hexdigest()
    if actual_hex != expected_hex:
        raise HabitatOciError(f"refusing payload with wrong digest for {path}")
    if path.exists():
        if not path.is_file() or path.is_symlink() or _sha256_file(path) != expected_hex:
            raise HabitatOciError(f"refusing to overwrite invalid cached object {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.incomplete"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fetch_token(
    manifest: Mapping[str, Any],
    *,
    timeout_s: float,
    opener: UrlOpen,
) -> str:
    registry = manifest["container"]["registry"]
    repository = str(registry["repository"])
    query = urllib.parse.urlencode(
        {
            "service": str(registry["auth_service"]),
            "scope": f"repository:{repository}:pull",
        }
    )
    request = urllib.request.Request(
        f"{registry['auth_url']}?{query}",
        headers={"Accept": "application/json"},
    )
    try:
        with opener(request, timeout=timeout_s) as response:
            payload = response.read(256 * 1024 + 1)
    except Exception as exc:
        raise HabitatOciError(f"cannot obtain registry token: {exc}") from exc
    if len(payload) > 256 * 1024:
        raise HabitatOciError("registry token response exceeds size bound")
    document = _json_object(payload, "registry token")
    token = document.get("token") or document.get("access_token")
    if not isinstance(token, str) or not token:
        raise HabitatOciError("registry token response has no bearer token")
    return token


def _blob_url(manifest: Mapping[str, Any], digest: str) -> str:
    registry = manifest["container"]["registry"]
    return f"{str(registry['api']).rstrip('/')}/{registry['repository']}/blobs/{digest}"


def _blob_ready(path: Path, descriptor: Mapping[str, Any], *, hash_file: bool) -> bool:
    if not path.is_file() or path.is_symlink() or path.stat().st_size != descriptor["size"]:
        return False
    return not hash_file or _sha256_file(path) == _digest_hex(descriptor["digest"], "layer")


def _download_blob(
    manifest: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    target: Path,
    *,
    token: str,
    timeout_s: float,
    opener: UrlOpen,
) -> None:
    expected_size = int(descriptor["size"])
    expected_hex = _digest_hex(descriptor["digest"], "layer digest")
    if target.exists():
        if _blob_ready(target, descriptor, hash_file=True):
            return
        raise HabitatOciError(f"refusing to overwrite invalid cached layer {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.parent / f".{target.name}.incomplete"
    if partial.exists() and (not partial.is_file() or partial.is_symlink()):
        raise HabitatOciError(f"unsafe partial layer path: {partial}")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > expected_size:
        raise HabitatOciError(f"partial layer exceeds expected size: {partial}")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/octet-stream",
    }
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(
        _blob_url(manifest, str(descriptor["digest"])),
        headers=headers,
    )
    try:
        response = opener(request, timeout=timeout_s)
    except Exception as exc:
        raise HabitatOciError(f"cannot download layer {descriptor['digest']}: {exc}") from exc
    with response:
        append = offset > 0 and getattr(response, "status", None) == 206
        mode = "ab" if append else "wb"
        downloaded = offset if append else 0
        with partial.open(mode) as stream:
            while chunk := response.read(8 * 1024 * 1024):
                stream.write(chunk)
                downloaded += len(chunk)
                if downloaded > expected_size:
                    raise HabitatOciError(f"layer exceeds declared size: {descriptor['digest']}")
            stream.flush()
            os.fsync(stream.fileno())
    if partial.stat().st_size != expected_size or _sha256_file(partial) != expected_hex:
        raise HabitatOciError(f"downloaded layer size or digest mismatch: {descriptor['digest']}")
    os.replace(partial, target)


def _uncompressed_digest(layer: Path) -> str:
    digest = hashlib.sha256()
    try:
        with gzip.open(layer, "rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
    except (OSError, EOFError) as exc:
        raise HabitatOciError(f"invalid gzip OCI layer {layer}: {exc}") from exc
    return digest.hexdigest()


def _member_path(staging: Path, raw_name: str) -> Path:
    normalized = raw_name.removeprefix("./")
    relative = Path(normalized)
    if not normalized or relative.is_absolute() or ".." in relative.parts:
        raise HabitatOciError(f"unsafe OCI layer member path: {raw_name!r}")
    target = staging / relative
    if not target.parent.resolve(strict=False).is_relative_to(staging):
        raise HabitatOciError(f"OCI layer member traverses outside rootfs: {raw_name!r}")
    return target


def _remove_whiteout_target(target: Path, staging: Path) -> None:
    if not target.resolve(strict=False).is_relative_to(staging):
        raise HabitatOciError(f"OCI whiteout escapes rootfs: {target}")
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)


def _apply_layer(layer: Path, staging: Path, expected_diff_id: str) -> None:
    expected_hex = _digest_hex(expected_diff_id, "rootfs diff ID")
    if _uncompressed_digest(layer) != expected_hex:
        raise HabitatOciError(f"uncompressed diff ID mismatch for {layer}")
    try:
        with tarfile.open(layer, mode="r:gz") as archive:
            ordinary: list[tarfile.TarInfo] = []
            for original in archive.getmembers():
                member = original
                if member.name in {".", "./"} and member.isdir():
                    continue
                target = _member_path(staging, member.name)
                if target.name == ".wh..wh..opq":
                    if target.parent.is_dir():
                        for child in tuple(target.parent.iterdir()):
                            _remove_whiteout_target(child, staging)
                    continue
                if target.name.startswith(".wh."):
                    _remove_whiteout_target(target.with_name(target.name[4:]), staging)
                    continue
                if member.issym():
                    linked = (
                        staging / member.linkname.lstrip("/")
                        if Path(member.linkname).is_absolute()
                        else target.parent / member.linkname
                    ).resolve(strict=False)
                    if not linked.is_relative_to(staging):
                        raise HabitatOciError(f"OCI symbolic link escapes rootfs: {member.name!r}")
                elif member.islnk():
                    linked = (staging / member.linkname.lstrip("/")).resolve(strict=False)
                    if not linked.is_relative_to(staging):
                        raise HabitatOciError(f"OCI hard link escapes rootfs: {member.name!r}")
                if (member.issym() or member.islnk()) and Path(member.linkname).is_absolute():
                    member = copy.copy(member)
                    rooted = staging / member.linkname.lstrip("/")
                    member.linkname = (
                        os.path.relpath(rooted, target.parent)
                        if member.issym()
                        else rooted.relative_to(staging).as_posix()
                    )
                ordinary.append(member)
            archive.extractall(staging, members=ordinary, filter="data")
    except (OSError, tarfile.TarError) as exc:
        raise HabitatOciError(f"cannot safely extract OCI layer {layer}: {exc}") from exc


def _critical_files(rootfs: Path) -> list[dict[str, Any]]:
    candidates = [
        rootfs / _HABITAT_PYTHON,
        rootfs / _HABITAT_MODULE / "__init__.py",
        rootfs / _HABITAT_BINDING,
    ]
    if len(candidates) != 3 or not all(
        path.is_file() and path.resolve().is_relative_to(rootfs) and path.resolve().is_file()
        for path in candidates
    ):
        raise HabitatOciError("assembled image lacks the archived Python/Habitat-Sim runtime")
    return [
        {
            "path": path.relative_to(rootfs).as_posix(),
            "resolved_path": path.resolve().relative_to(rootfs).as_posix(),
            "size": path.resolve().stat().st_size,
            "sha256": _sha256_file(path.resolve()),
        }
        for path in candidates
    ]


def _assemble_rootfs(
    layout: RuntimeLayout,
    *,
    manifest_digest: str,
    config_digest: str,
    descriptors: list[dict[str, Any]],
    diff_ids: list[str],
) -> None:
    if layout.rootfs.exists() or layout.metadata.exists():
        raise HabitatOciError("refusing to replace a pre-existing Habitat OCI rootfs")
    layout.image_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rootfs-", dir=layout.image_root)).resolve()
    try:
        for descriptor, diff_id in zip(descriptors, diff_ids, strict=True):
            blob = layout.blobs / _digest_hex(descriptor["digest"], "layer digest")
            _apply_layer(blob, staging, diff_id)
        for path in (
            staging / "proc",
            staging / "dev",
            staging / "tmp",
            staging / "opt/parcel-host-libs",
            staging / "opt/parcel-host-config",
            staging / "opt/parcel-smoke",
        ):
            path.mkdir(parents=True, exist_ok=True)
        marker = {
            "schema_version": 1,
            "manifest_digest": manifest_digest,
            "config_digest": config_digest,
            "layer_digests": [item["digest"] for item in descriptors],
            "rootfs_diff_ids": diff_ids,
            "critical_files": _critical_files(staging),
            "rootfs_inventory": _rootfs_inventory(staging),
            "image_hooks_executed": False,
            "entrypoint_executed": False,
            "package_manager_executed": False,
        }
        marker_payload = (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode()
        marker_path = staging / _ROOTFS_MARKER
        marker_path.write_bytes(marker_payload)
        marker_path.chmod(0o444)
        staging.rename(layout.rootfs)
        _atomic_verified_write(
            layout.metadata,
            marker_payload,
            f"sha256:{hashlib.sha256(marker_payload).hexdigest()}",
        )
        layout.metadata.chmod(0o444)
    except Exception:
        if staging.exists() and staging.parent == layout.image_root:
            shutil.rmtree(staging)
        raise


def _resolved_documents(
    manifest: Mapping[str, Any],
    fetched: Mapping[str, Any],
    host_gpu: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    verification = verify_image_contract(
        manifest,
        registry_manifest_bytes=fetched["manifest_bytes"],
        registry_manifest_response_digest=fetched["manifest_response_digest"],
        image_config_bytes=fetched["config_bytes"],
        host_gpu=host_gpu,
    )
    if verification["passed"] is not True:
        raise HabitatOciError(
            "archived image/host contract failed: " + ", ".join(verification["failed_checks"])
        )
    return (
        _json_object(fetched["manifest_bytes"], "registry manifest"),
        _json_object(fetched["config_bytes"], "image config"),
    )


def prepare_runtime(
    *,
    manifest_path: Path = MANIFEST_PATH,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    confirm_digest: str,
    timeout_s: float = 120.0,
    opener: UrlOpen = _SAFE_OPENER.open,
    host_gpu: Mapping[str, Any] | None = None,
    required_free_bytes: int = REQUIRED_FREE_BYTES,
) -> dict[str, Any]:
    """Download and assemble only the explicitly confirmed immutable image."""

    manifest = load_manifest(manifest_path)
    expected_digest = str(manifest["container"]["base_digest"])
    if confirm_digest != expected_digest:
        raise HabitatOciError(
            "--confirm-image-digest must exactly equal the frozen Habitat manifest digest"
        )
    if timeout_s <= 0 or timeout_s > 600:
        raise ValueError("timeout_s must be in (0, 600]")
    layout = runtime_layout(manifest, cache_root)
    layout.cache_root.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(layout.cache_root).free
    if free_bytes < required_free_bytes:
        raise HabitatOciError(
            f"insufficient free space: require {required_free_bytes} bytes; have {free_bytes}"
        )
    fetched = fetch_registry_contract(manifest, timeout_s=timeout_s, opener=opener)
    manifest_document, config_document = _resolved_documents(
        manifest,
        fetched,
        host_gpu or probe_host_gpu(),
    )
    config_digest = str(manifest_document["config"]["digest"])
    _atomic_verified_write(layout.manifest_blob, fetched["manifest_bytes"], expected_digest)
    _atomic_verified_write(layout.config_blob, fetched["config_bytes"], config_digest)
    descriptors = manifest_document["layers"]
    if not isinstance(descriptors, list) or not all(
        isinstance(item, dict) and item.get("mediaType") in _SUPPORTED_LAYER_MEDIA_TYPES
        for item in descriptors
    ):
        raise HabitatOciError("archived image contains an unsupported layer media type")
    token = _fetch_token(manifest, timeout_s=timeout_s, opener=opener)
    for descriptor in descriptors:
        target = layout.blobs / _digest_hex(descriptor["digest"], "layer digest")
        _download_blob(
            manifest,
            descriptor,
            target,
            token=token,
            timeout_s=timeout_s,
            opener=opener,
        )
    rootfs = config_document.get("rootfs")
    diff_ids = rootfs.get("diff_ids") if isinstance(rootfs, dict) else None
    if not isinstance(diff_ids, list) or len(diff_ids) != len(descriptors):
        raise HabitatOciError("image config has no exact rootfs diff-ID chain")
    if not layout.rootfs.exists() and not layout.metadata.exists():
        _assemble_rootfs(
            layout,
            manifest_digest=expected_digest,
            config_digest=config_digest,
            descriptors=descriptors,
            diff_ids=diff_ids,
        )
    report = inspect_runtime(
        manifest_path=manifest_path,
        cache_root=cache_root,
        verify_blob_hashes=True,
    )
    if report["ready"] is not True:
        raise HabitatOciError("assembled rootfs failed post-assembly verification")
    return report


def _load_cached_contract(
    manifest: Mapping[str, Any], layout: RuntimeLayout
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not layout.manifest_blob.is_file() or not layout.config_blob.is_file():
        return None
    expected_manifest = str(manifest["container"]["base_digest"])
    expected_config = str(manifest["container"]["registry"]["config_digest"])
    if _sha256_file(layout.manifest_blob) != _digest_hex(expected_manifest, "manifest"):
        return None
    if _sha256_file(layout.config_blob) != _digest_hex(expected_config, "config"):
        return None
    return (
        _json_object(layout.manifest_blob.read_bytes(), "cached manifest"),
        _json_object(layout.config_blob.read_bytes(), "cached config"),
    )


def inspect_runtime(
    *,
    manifest_path: Path = MANIFEST_PATH,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    verify_blob_hashes: bool = False,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    layout = runtime_layout(manifest, cache_root)
    documents = _load_cached_contract(manifest, layout)
    descriptors: list[dict[str, Any]] = documents[0]["layers"] if documents else []
    blob_ready = [
        _blob_ready(
            layout.blobs / _digest_hex(item["digest"], "layer digest"),
            item,
            hash_file=verify_blob_hashes,
        )
        for item in descriptors
    ]
    marker_ready = False
    critical_ready = False
    inventory_ready = False
    inventory_expected: dict[str, Any] | None = None
    inventory_actual: dict[str, Any] | None = None
    marker: dict[str, Any] | None = None
    if (
        layout.metadata.is_file()
        and not layout.metadata.is_symlink()
        and layout.rootfs.is_dir()
        and not layout.rootfs.is_symlink()
        and (layout.rootfs / _ROOTFS_MARKER).is_file()
        and not (layout.rootfs / _ROOTFS_MARKER).is_symlink()
    ):
        try:
            external_payload = layout.metadata.read_bytes()
            internal_payload = (layout.rootfs / _ROOTFS_MARKER).read_bytes()
            marker = _json_object(external_payload, "rootfs provenance")
            marker_ready = external_payload == internal_payload and bool(documents)
            if documents:
                marker_ready = (
                    marker_ready
                    and marker.get("manifest_digest") == manifest["container"]["base_digest"]
                    and marker.get("config_digest")
                    == manifest["container"]["registry"]["config_digest"]
                    and marker.get("layer_digests") == [item["digest"] for item in descriptors]
                    and marker.get("rootfs_diff_ids") == documents[1]["rootfs"]["diff_ids"]
                    and marker.get("image_hooks_executed") is False
                    and marker.get("entrypoint_executed") is False
                    and marker.get("package_manager_executed") is False
                )
                inventory_value = marker.get("rootfs_inventory")
                if isinstance(inventory_value, dict):
                    inventory_expected = inventory_value
            critical = marker.get("critical_files", [])
            critical_ready = isinstance(critical, list) and bool(critical)
            for item in critical if isinstance(critical, list) else []:
                if not isinstance(item, dict):
                    critical_ready = False
                    break
                original_relative = Path(str(item.get("path", "")))
                resolved_relative = Path(str(item.get("resolved_path", "")))
                if (
                    not original_relative.parts
                    or not resolved_relative.parts
                    or original_relative.is_absolute()
                    or resolved_relative.is_absolute()
                    or ".." in original_relative.parts
                    or ".." in resolved_relative.parts
                ):
                    critical_ready = False
                    break
                original = layout.rootfs / original_relative
                resolved = layout.rootfs / resolved_relative
                if (
                    not original.is_file()
                    or original.resolve() != resolved
                    or not resolved.is_file()
                    or resolved.is_symlink()
                    or resolved.stat().st_size != item.get("size")
                    or _sha256_file(resolved) != item.get("sha256")
                ):
                    critical_ready = False
                    break
            if marker_ready and verify_blob_hashes and inventory_expected is not None:
                inventory_actual = _rootfs_inventory(layout.rootfs)
                inventory_ready = inventory_actual == inventory_expected
        except (OSError, KeyError, TypeError, HabitatOciError):
            marker_ready = False
            critical_ready = False
            inventory_ready = False
    expected_count = int(manifest["container"]["registry"]["layer_count"])
    ready = bool(
        verify_blob_hashes
        and documents
        and len(descriptors) == expected_count
        and len(blob_ready) == expected_count
        and all(blob_ready)
        and marker_ready
        and critical_ready
        and inventory_ready
    )
    return {
        "schema_version": 1,
        "manifest_digest": manifest["container"]["base_digest"],
        "cache_root": str(layout.cache_root),
        "rootfs": str(layout.rootfs),
        "compressed_bytes_expected": manifest["container"]["registry"][
            "compressed_layer_size_bytes"
        ],
        "minimum_free_bytes_enforced_before_prepare": REQUIRED_FREE_BYTES,
        "layer_count_expected": expected_count,
        "layer_count_resolved": len(descriptors),
        "verified_blob_count": sum(blob_ready),
        "blob_hashes_verified": verify_blob_hashes,
        "provenance_marker_ready": marker_ready,
        "critical_runtime_files_ready": critical_ready,
        "rootfs_inventory_verified": inventory_ready,
        "rootfs_inventory_expected": inventory_expected,
        "rootfs_inventory_actual": inventory_actual,
        "ready": ready,
        "claims": {
            "image_hooks_executed": False,
            "entrypoint_executed": False,
            "package_manager_executed": False,
            "container_executed": False,
            "scene_loaded": False,
            "navigation_metrics_emitted": False,
        },
    }


def discover_gpu_bindings() -> GpuBindings:
    devices: list[Path] = []
    for path in sorted(Path("/dev").glob("nvidia*")):
        candidates: Iterable[Path] = path.iterdir() if path.is_dir() else (path,)
        for candidate in candidates:
            try:
                mode = candidate.stat(follow_symlinks=False).st_mode
            except OSError:
                continue
            if stat.S_ISCHR(mode) and not candidate.is_symlink():
                devices.append(candidate)
    dri = Path("/dev/dri")
    if dri.is_dir() and not dri.is_symlink():
        for candidate in sorted(dri.iterdir()):
            try:
                mode = candidate.stat(follow_symlinks=False).st_mode
            except OSError:
                continue
            if stat.S_ISCHR(mode) and not candidate.is_symlink():
                devices.append(candidate)
    required_devices = {Path("/dev/nvidiactl"), Path("/dev/nvidia0"), Path("/dev/nvidia-uvm")}
    if not required_devices.issubset(devices):
        raise HabitatOciError("required NVIDIA device nodes are unavailable")

    ldconfig = shutil.which("ldconfig")
    if ldconfig is None:
        raise HabitatOciError("ldconfig is required to resolve host NVIDIA libraries")
    completed = subprocess.run(
        [ldconfig, "-p"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise HabitatOciError("ldconfig could not enumerate host driver libraries")
    libraries: dict[str, Path] = {}
    for line in completed.stdout.splitlines():
        if "=>" not in line or "x86-64" not in line:
            continue
        name, raw_path = line.strip().split("=>", 1)
        name = name.split()[0]
        if _SAFE_DRIVER_LIBRARY.fullmatch(name) is None:
            continue
        path = Path(raw_path.strip())
        resolved = path.resolve()
        if not path.is_absolute() or not resolved.is_file() or resolved.is_symlink():
            continue
        existing = libraries.get(name)
        if existing is not None and existing != resolved:
            raise HabitatOciError(f"ambiguous host driver library {name}")
        libraries[name] = resolved
    required_libraries = {"libcuda.so.1", "libEGL_nvidia.so.0"}
    if not required_libraries.issubset(libraries):
        raise HabitatOciError("required host CUDA/NVIDIA EGL vendor libraries are unavailable")
    objdump = shutil.which("objdump")
    if objdump is None:
        raise HabitatOciError("objdump is required for NVIDIA driver ABI verification")
    requirements_by_path: dict[Path, tuple[int, int, int]] = {}
    requirement_rows: list[tuple[str, str]] = []
    for name, path in sorted(libraries.items()):
        requirement = requirements_by_path.get(path)
        if requirement is None:
            audited = subprocess.run(
                [objdump, "-T", str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if audited.returncode != 0:
                raise HabitatOciError(f"cannot audit GLIBC requirements for {path}")
            versions = [
                (int(major), int(minor), int(patch or 0))
                for major, minor, patch in _GLIBC_REQUIREMENT.findall(audited.stdout)
            ]
            requirement = max(versions, default=(0, 0, 0))
            requirements_by_path[path] = requirement
        if requirement > _ARCHIVED_GLIBC:
            formatted = ".".join(str(part) for part in requirement)
            raise HabitatOciError(
                f"host NVIDIA library {name} requires GLIBC_{formatted}, newer than 2.27"
            )
        requirement_rows.append((name, ".".join(str(part) for part in requirement)))
    return GpuBindings(
        devices=tuple(devices),
        libraries=tuple(sorted(libraries.items())),
        max_required_glibc=tuple(requirement_rows),
    )


def _verify_archived_glvnd_contract(rootfs: Path) -> None:
    links = {
        Path("usr/lib/x86_64-linux-gnu/libEGL.so.1"): "libEGL.so.1.0.0",
        Path("usr/lib/x86_64-linux-gnu/libGLdispatch.so.0"): "libGLdispatch.so.0.0.0",
    }
    for relative, expected_target in links.items():
        link = rootfs / relative
        target = link.parent / expected_target
        if (
            not link.is_symlink()
            or os.readlink(link) != expected_target
            or not target.is_file()
            or target.is_symlink()
        ):
            raise HabitatOciError(f"archived GLVND contract is missing {relative}")
    vendor = rootfs / "usr/share/glvnd/egl_vendor.d/10_nvidia.json"
    if not vendor.is_file() or vendor.is_symlink():
        raise HabitatOciError("archived NVIDIA EGL vendor manifest is unavailable")
    try:
        vendor_payload = json.loads(vendor.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HabitatOciError("archived NVIDIA EGL vendor manifest is invalid") from exc
    if vendor_payload.get("ICD", {}).get("library_path") != "libEGL_nvidia.so.0":
        raise HabitatOciError("archived NVIDIA EGL manifest selects an unexpected library")


def build_smoke_command(
    rootfs: Path,
    bindings: GpuBindings,
    *,
    smoke_script: Path = DEFAULT_SMOKE_SCRIPT,
) -> list[str]:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise HabitatOciError("Bubblewrap is required for the isolated smoke")
    if not rootfs.is_dir() or rootfs.is_symlink():
        raise HabitatOciError("verified Habitat rootfs is unavailable")
    if not smoke_script.is_file() or smoke_script.is_symlink():
        raise HabitatOciError("fixed Habitat smoke script is unavailable")
    _verify_archived_glvnd_contract(rootfs)
    required_mountpoints = (
        rootfs / "proc",
        rootfs / "dev",
        rootfs / "tmp",
        rootfs / "opt/parcel-host-libs",
        rootfs / "opt/parcel-smoke",
    )
    if not all(path.is_dir() and not path.is_symlink() for path in required_mountpoints):
        raise HabitatOciError("verified rootfs lacks isolated-runtime mountpoints")
    command = [
        bwrap,
        "--ro-bind",
        str(rootfs),
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/opt/parcel-host-libs",
        "--tmpfs",
        "/opt/parcel-smoke",
        "--ro-bind",
        str(smoke_script.resolve()),
        "/opt/parcel-smoke/probe.py",
    ]
    device_parents: set[Path] = set()
    for device in bindings.devices:
        parent = device.parent
        if parent != Path("/dev") and parent not in device_parents:
            command.extend(["--dir", str(parent)])
            device_parents.add(parent)
        command.extend(["--dev-bind", str(device), str(device)])
    library_names = {name for name, _source in bindings.libraries}
    if not {"libcuda.so.1", "libEGL_nvidia.so.0"}.issubset(library_names):
        raise HabitatOciError("CUDA and NVIDIA EGL vendor bindings are required")
    for name, source in bindings.libraries:
        if (
            _SAFE_DRIVER_LIBRARY.fullmatch(name) is None
            or not source.is_absolute()
            or not source.resolve().is_file()
        ):
            raise HabitatOciError(f"unsafe host driver binding: {name}")
        command.extend(["--ro-bind", str(source), f"/opt/parcel-host-libs/{name}"])
    command.extend(
        [
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            "--unshare-net",
            "--die-with-parent",
            "--new-session",
            "--dir",
            "/tmp/parcel-home",
            "/usr/bin/env",
            "-i",
            "HOME=/tmp/parcel-home",
            ("PATH=/opt/conda/envs/habitat/bin:/opt/conda/bin:/usr/local/cuda/bin:/usr/bin:/bin"),
            (
                "LD_LIBRARY_PATH=/opt/parcel-host-libs:/opt/conda/envs/habitat/lib:"
                "/usr/lib/x86_64-linux-gnu:/usr/local/cuda/lib64"
            ),
            "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json",
            "PYTHONUNBUFFERED=1",
            "/opt/conda/envs/habitat/bin/python",
            "/opt/parcel-smoke/probe.py",
        ]
    )
    return command


def _parse_smoke_output(stdout: str) -> dict[str, Any]:
    matches = [
        line[len(_SMOKE_SENTINEL) :]
        for line in stdout.splitlines()
        if line.startswith(_SMOKE_SENTINEL)
    ]
    if len(matches) != 1:
        raise HabitatOciError("smoke output did not contain exactly one result sentinel")
    return _json_object(matches[0].encode(), "smoke result")


def _text_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def run_smoke(
    *,
    manifest_path: Path = MANIFEST_PATH,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    confirm_digest: str,
    timeout_s: float = 120.0,
    bindings: GpuBindings | None = None,
) -> dict[str, Any]:
    if timeout_s <= 0 or timeout_s > 600:
        raise ValueError("timeout_s must be in (0, 600]")
    manifest = load_manifest(manifest_path)
    expected_digest = str(manifest["container"]["base_digest"])
    if confirm_digest != expected_digest:
        raise HabitatOciError(
            "--confirm-image-digest must exactly equal the frozen Habitat manifest digest"
        )
    status = inspect_runtime(
        manifest_path=manifest_path,
        cache_root=cache_root,
        verify_blob_hashes=True,
    )
    if status["ready"] is not True:
        raise HabitatOciError("Habitat rootfs is not fully verified; run --prepare first")
    layout = runtime_layout(manifest, cache_root)
    resolved_bindings = bindings or discover_gpu_bindings()
    command = build_smoke_command(layout.rootfs, resolved_bindings)
    started_ns = time.perf_counter_ns()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        exit_code: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout = _text_output(exc.stdout)
        stderr = _text_output(exc.stderr)
    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    try:
        result = _parse_smoke_output(stdout)
        parse_error: str | None = None
    except HabitatOciError as exc:
        parse_error = str(exc)
        result = {"passed": False, "error": parse_error}
    probe_claims = result.get("claims")
    cuda_result = result.get("cuda")
    egl_result = result.get("egl")
    habitat_result = result.get("habitat_sim")
    negative_claims_ready = isinstance(probe_claims, dict) and all(
        probe_claims.get(key) is False
        for key in (
            "dataset_used",
            "scene_loaded",
            "simulator_constructed",
            "gpu_render_executed",
            "navigation_episode_executed",
            "navigation_metrics_emitted",
        )
    )
    passed = bool(
        not timed_out
        and exit_code == 0
        and parse_error is None
        and result.get("passed") is True
        and isinstance(cuda_result, dict)
        and cuda_result.get("passed") is True
        and isinstance(egl_result, dict)
        and egl_result.get("passed") is True
        and isinstance(habitat_result, dict)
        and habitat_result.get("passed") is True
        and negative_claims_ready
    )
    generated_at = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "run_id": f"habitat20-oci-gpu-import-smoke-{generated_at.strftime('%Y%m%dT%H%M%SZ')}",
        "generated_at_utc": generated_at.isoformat(),
        "result": {"passed": passed, "probe": result},
        "runtime": {
            "manifest_digest": expected_digest,
            "rootfs": str(layout.rootfs),
            "bubblewrap_exit_code": exit_code,
            "timed_out": timed_out,
            "result_parse_error": parse_error,
            "elapsed_ms": elapsed_ms,
            "stderr": stderr[-4096:],
            "isolated_rootfs_process_executed": True,
        },
        "provenance": {
            "runner_path": Path(__file__).relative_to(REPO_ROOT).as_posix(),
            "runner_sha256": _sha256_file(Path(__file__)),
            "smoke_script_path": DEFAULT_SMOKE_SCRIPT.relative_to(REPO_ROOT).as_posix(),
            "smoke_script_sha256": _sha256_file(DEFAULT_SMOKE_SCRIPT),
            "all_compressed_layer_hashes_verified_before_execution": True,
            "glvnd_client_source": "archived_image_rootfs",
            "egl_vendor_manifest_source": "archived_image_rootfs",
            "injected_host_driver_libraries": [name for name, _path in resolved_bindings.libraries],
            "injected_host_driver_max_required_glibc": dict(resolved_bindings.max_required_glibc),
        },
        "evaluation": {
            "official_rank_eligible": False,
            "leaderboard_comparable": False,
            "official_evaluator_executed": False,
            "scene_loaded": False,
            "navigation_episode_executed": False,
            "navigation_metrics_emitted": False,
            "allowed_claim": "exact archived image CUDA/EGL/Habitat-Sim import smoke",
        },
        "claims": {
            "image_entrypoint_executed": False,
            "image_hooks_executed": False,
            "package_manager_executed": False,
            "network_available_inside_sandbox": False,
            "dataset_mounted_or_used": False,
            "simulator_constructed": False,
            "gpu_kernel_executed": False,
            "gpu_render_executed": False,
            "navigation_score_available": False,
        },
    }


def _write_immutable(path: Path, report: Mapping[str, Any]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    with target.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    target.chmod(0o444)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--smoke", action="store_true")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--confirm-image-digest")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            if not args.confirm_image_digest:
                raise HabitatOciError("--prepare requires --confirm-image-digest")
            report = prepare_runtime(
                manifest_path=args.manifest,
                cache_root=args.cache_root,
                confirm_digest=args.confirm_image_digest,
                timeout_s=args.timeout,
            )
        elif args.smoke:
            if not args.confirm_image_digest or args.output is None:
                raise HabitatOciError(
                    "--smoke requires --confirm-image-digest and a unique --output"
                )
            report = run_smoke(
                manifest_path=args.manifest,
                cache_root=args.cache_root,
                confirm_digest=args.confirm_image_digest,
                timeout_s=args.timeout,
            )
            _write_immutable(args.output, report)
        else:
            report = inspect_runtime(
                manifest_path=args.manifest,
                cache_root=args.cache_root,
            )
    except (
        HabitatOciError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ready", report.get("result", {}).get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
