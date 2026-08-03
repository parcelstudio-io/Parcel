"""Prepare and smoke-test non-gated Habitat test assets fail-closed.

This is not a Habitat 2020 evaluation.  Preparation downloads only the exact
content-addressed test-scene subset and independently hashed PointNav fixture
frozen in ``habitat2020_test_assets_manifest.json``.  The smoke runs an exact
archived Habitat-Sim runtime with networking disabled, mounts assets read-only,
renders RGB-D frames, and executes three deterministic simulator actions.  It
never runs Habitat-Lab, Parcel navigation, an evaluator, or a metric.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .habitat2020_doctor import MANIFEST_PATH as RUNTIME_MANIFEST_PATH
from .habitat2020_doctor import REPO_ROOT, load_manifest
from .habitat2020_oci_runtime import (
    DEFAULT_CACHE_ROOT as DEFAULT_RUNTIME_CACHE_ROOT,
)
from .habitat2020_oci_runtime import (
    GpuBindings,
    HabitatOciError,
    _sha256_file,
    build_smoke_command,
    discover_gpu_bindings,
    inspect_runtime,
    runtime_layout,
)

ASSET_MANIFEST_PATH = Path(__file__).with_name("habitat2020_test_assets_manifest.json")
DEFAULT_ASSET_CACHE_ROOT = REPO_ROOT / ".cache/external-evals/assets/habitat-test-assets"
DEFAULT_SCENE_SMOKE_SCRIPT = Path(__file__).with_name("habitat2020_scene_smoke_py36.py")
_PROVENANCE_NAME = "asset-provenance.json"
_SCENE_SENTINEL = "PARCEL_HABITAT_SCENE_SMOKE="
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_DOWNLOAD_HOSTS = {
    "dl.fbaipublicfiles.com",
    "huggingface.co",
    "raw.githubusercontent.com",
}

UrlOpen = Callable[..., Any]


class HabitatTestAssetError(HabitatOciError):
    """Raised when the public test-asset contract cannot be proven exactly."""


class _AssetRedirectHandler(urllib.request.HTTPRedirectHandler):
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
        parsed = urllib.parse.urlsplit(new_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            host in _ALLOWED_DOWNLOAD_HOSTS or host.endswith((".hf.co", ".huggingface.co"))
        ):
            raise HabitatTestAssetError(f"refusing asset redirect to {new_url}")
        redirected.remove_header("Authorization")
        return redirected


_SAFE_ASSET_OPENER = urllib.request.build_opener(_AssetRedirectHandler())


@dataclass(frozen=True)
class AssetLayout:
    cache_root: Path
    bundle_root: Path
    data_root: Path
    sources_root: Path
    archives_root: Path
    provenance: Path
    manifest_sha256: str


@dataclass(frozen=True)
class AssetFile:
    role: str
    relative_path: Path
    url: str | None
    size_bytes: int
    sha256: str
    archive_path: str | None = None


def _safe_relative(value: object, label: str) -> Path:
    path = Path(str(value))
    if not path.parts or path.is_absolute() or ".." in path.parts or path == Path("."):
        raise HabitatTestAssetError(f"{label} must be a safe relative path")
    return path


def _required_sha256(value: object, label: str) -> str:
    digest = str(value)
    if _SHA256.fullmatch(digest) is None:
        raise HabitatTestAssetError(f"{label} must be a lowercase SHA-256")
    return digest


def _required_https(value: object, label: str) -> str:
    url = str(value)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HabitatTestAssetError(f"{label} must be an unauthenticated HTTPS URL")
    host = parsed.hostname.lower()
    if host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise HabitatTestAssetError(f"{label} uses an unapproved source host")
    return url


def load_asset_manifest(path: Path = ASSET_MANIFEST_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HabitatTestAssetError(f"cannot load Habitat test-asset manifest: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise HabitatTestAssetError("unsupported Habitat test-asset manifest")
    if value.get("bundle_id") != "habitat-test-assets-compat-v1":
        raise HabitatTestAssetError("unexpected Habitat test-asset bundle ID")
    eligibility = value.get("eligibility")
    if not isinstance(eligibility, dict) or any(
        eligibility.get(key) is not False
        for key in (
            "habitat_2020_protocol",
            "official_evaluator_allowed",
            "official_rank_eligible",
            "leaderboard_comparable",
            "navigation_metrics_allowed",
        )
    ):
        raise HabitatTestAssetError("test-asset eligibility must fail closed")
    utility = value.get("official_data_utility")
    documentation = value.get("official_documentation")
    scene = value.get("scene_asset")
    pointnav = value.get("pointnav_asset")
    smoke = value.get("smoke")
    if not all(isinstance(item, dict) for item in (utility, documentation, scene, pointnav, smoke)):
        raise HabitatTestAssetError("test-asset manifest sections must be objects")
    if (
        utility.get("requires_auth_for_these_uids") is not False
        or scene.get("public") is not True
        or scene.get("gated") is not False
        or scene.get("credential_required") is not False
        or scene.get("license") != "cc-by-nc-4.0"
        or pointnav.get("credential_required") is not False
    ):
        raise HabitatTestAssetError("test assets are not frozen as public, ungated sources")
    if utility.get("scene_uid") != scene.get("uid") or utility.get("pointnav_uid") != pointnav.get(
        "uid"
    ):
        raise HabitatTestAssetError("official utility UIDs disagree with the asset contract")
    for section, label in ((utility, "official utility"), (documentation, "documentation")):
        _required_https(section.get("url"), f"{label} URL")
        _required_sha256(section.get("sha256"), f"{label} SHA-256")
        if not isinstance(section.get("size_bytes"), int) or section["size_bytes"] <= 0:
            raise HabitatTestAssetError(f"{label} size must be positive")
    scene_files = scene.get("files")
    pointnav_members = pointnav.get("members")
    if not isinstance(scene_files, list) or not scene_files:
        raise HabitatTestAssetError("scene files must be a nonempty list")
    if not isinstance(pointnav_members, list) or not pointnav_members:
        raise HabitatTestAssetError("PointNav members must be a nonempty list")
    seen_paths: set[Path] = set()
    for index, item in enumerate(scene_files):
        if not isinstance(item, dict):
            raise HabitatTestAssetError("scene file descriptors must be objects")
        relative = _safe_relative(item.get("path"), f"scene file {index} path")
        if relative in seen_paths:
            raise HabitatTestAssetError("duplicate scene target path")
        seen_paths.add(relative)
        _required_https(item.get("url"), f"scene file {index} URL")
        _required_sha256(item.get("sha256"), f"scene file {index} SHA-256")
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] <= 0:
            raise HabitatTestAssetError("scene file sizes must be positive")
    _required_https(pointnav.get("download_url"), "PointNav archive URL")
    _required_sha256(pointnav.get("sha256"), "PointNav archive SHA-256")
    if not isinstance(pointnav.get("size_bytes"), int) or pointnav["size_bytes"] <= 0:
        raise HabitatTestAssetError("PointNav archive size must be positive")
    seen_archive_paths: set[str] = set()
    for index, item in enumerate(pointnav_members):
        if not isinstance(item, dict):
            raise HabitatTestAssetError("PointNav member descriptors must be objects")
        archive_path = _safe_relative(
            item.get("archive_path"), f"PointNav member {index} archive path"
        ).as_posix()
        relative = _safe_relative(item.get("path"), f"PointNav member {index} target path")
        if archive_path in seen_archive_paths or relative in seen_paths:
            raise HabitatTestAssetError("duplicate PointNav archive or target path")
        seen_archive_paths.add(archive_path)
        seen_paths.add(relative)
        _required_sha256(item.get("sha256"), f"PointNav member {index} SHA-256")
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] <= 0:
            raise HabitatTestAssetError("PointNav member sizes must be positive")
    if smoke.get("actions") != ["move_forward", "turn_left", "turn_right"]:
        raise HabitatTestAssetError("smoke action sequence must remain fixed")
    if pointnav.get("smoke_episode_id") != "0" or pointnav.get("smoke_split") != "val":
        raise HabitatTestAssetError("smoke fixture selection must remain fixed")
    return value


def asset_layout(
    manifest_path: Path = ASSET_MANIFEST_PATH,
    cache_root: Path = DEFAULT_ASSET_CACHE_ROOT,
) -> AssetLayout:
    manifest_path = manifest_path.expanduser().resolve()
    manifest_sha = _sha256_file(manifest_path)
    supplied = cache_root.expanduser().absolute()
    resolved = supplied.resolve(strict=False)
    forbidden = {Path("/"), Path.home().resolve(), REPO_ROOT.resolve()}
    if resolved != supplied or resolved in forbidden or len(resolved.parts) < 4:
        raise HabitatTestAssetError(f"unsafe asset cache root: {cache_root}")
    if cache_root.is_symlink():
        raise HabitatTestAssetError("asset cache root cannot be a symlink")
    bundle_root = resolved / manifest_sha
    return AssetLayout(
        cache_root=resolved,
        bundle_root=bundle_root,
        data_root=bundle_root / "data",
        sources_root=bundle_root / "sources",
        archives_root=bundle_root / "archives",
        provenance=bundle_root / _PROVENANCE_NAME,
        manifest_sha256=manifest_sha,
    )


def _asset_files(manifest: Mapping[str, Any]) -> tuple[AssetFile, ...]:
    utility = manifest["official_data_utility"]
    documentation = manifest["official_documentation"]
    scene = manifest["scene_asset"]
    pointnav = manifest["pointnav_asset"]
    files = [
        AssetFile(
            role="official_data_utility",
            relative_path=Path("sources/habitat-sim/datasets_download.py"),
            url=str(utility["url"]),
            size_bytes=int(utility["size_bytes"]),
            sha256=str(utility["sha256"]),
        ),
        AssetFile(
            role="official_documentation",
            relative_path=Path("sources/habitat-sim/DATASETS.md"),
            url=str(documentation["url"]),
            size_bytes=int(documentation["size_bytes"]),
            sha256=str(documentation["sha256"]),
        ),
    ]
    files.extend(
        AssetFile(
            role="scene_file",
            relative_path=Path("data") / _safe_relative(item["path"], "scene file path"),
            url=str(item["url"]),
            size_bytes=int(item["size_bytes"]),
            sha256=str(item["sha256"]),
        )
        for item in scene["files"]
    )
    files.append(
        AssetFile(
            role="pointnav_archive",
            relative_path=Path("archives") / str(pointnav["package_name"]),
            url=str(pointnav["download_url"]),
            size_bytes=int(pointnav["size_bytes"]),
            sha256=str(pointnav["sha256"]),
        )
    )
    files.extend(
        AssetFile(
            role="pointnav_member",
            relative_path=Path("data") / _safe_relative(item["path"], "PointNav target path"),
            url=None,
            size_bytes=int(item["size_bytes"]),
            sha256=str(item["sha256"]),
            archive_path=str(item["archive_path"]),
        )
        for item in pointnav["members"]
    )
    return tuple(files)


def _header(headers: Mapping[str, Any], key: str) -> str | None:
    wanted = key.lower()
    for name, value in headers.items():
        if str(name).lower() == wanted:
            return str(value)
    return None


def _download_verified(
    descriptor: AssetFile,
    target: Path,
    *,
    timeout_s: float,
    opener: UrlOpen,
    expected_etag: str | None = None,
    expected_version_id: str | None = None,
) -> dict[str, Any]:
    if descriptor.url is None:
        raise HabitatTestAssetError("cannot download an archive member directly")
    _required_https(descriptor.url, f"{descriptor.role} URL")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise HabitatTestAssetError(f"refusing to overwrite staged asset {target}")
    request = urllib.request.Request(descriptor.url, headers={"Accept": "application/octet-stream"})
    try:
        response = opener(request, timeout=timeout_s)
    except Exception as exc:
        raise HabitatTestAssetError(f"cannot download {descriptor.role}: {exc}") from exc
    digest = hashlib.sha256()
    received = 0
    try:
        with response:
            headers = response.headers
            if expected_etag is not None:
                observed_etag = (_header(headers, "etag") or "").strip('"')
                if observed_etag != expected_etag:
                    raise HabitatTestAssetError(f"unexpected ETag for {descriptor.role}")
            if expected_version_id is not None:
                observed_version = _header(headers, "x-amz-version-id")
                if observed_version != expected_version_id:
                    raise HabitatTestAssetError(f"unexpected object version for {descriptor.role}")
            with target.open("xb") as stream:
                while chunk := response.read(8 * 1024 * 1024):
                    received += len(chunk)
                    if received > descriptor.size_bytes:
                        raise HabitatTestAssetError(f"{descriptor.role} exceeds frozen size")
                    stream.write(chunk)
                    digest.update(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            final_url = response.geturl() if hasattr(response, "geturl") else descriptor.url
    except Exception:
        if target.exists():
            target.unlink()
        raise
    if received != descriptor.size_bytes or digest.hexdigest() != descriptor.sha256:
        target.unlink()
        raise HabitatTestAssetError(f"{descriptor.role} size or SHA-256 mismatch")
    return {
        "role": descriptor.role,
        "url": descriptor.url,
        "final_host": urllib.parse.urlsplit(str(final_url)).hostname,
        "size_bytes": received,
        "sha256": descriptor.sha256,
    }


def _extract_pointnav(
    archive: Path,
    staging: Path,
    descriptors: tuple[AssetFile, ...],
) -> None:
    expected = {item.archive_path: item for item in descriptors if item.role == "pointnav_member"}
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            regular: dict[str, zipfile.ZipInfo] = {}
            seen: set[str] = set()
            for info in infos:
                name = _safe_relative(info.filename, "PointNav ZIP member").as_posix().rstrip("/")
                if name in seen:
                    raise HabitatTestAssetError("duplicate PointNav ZIP member")
                seen.add(name)
                unix_mode = info.external_attr >> 16
                if unix_mode and stat.S_ISLNK(unix_mode):
                    raise HabitatTestAssetError("PointNav ZIP contains a symbolic link")
                if not info.is_dir():
                    regular[name] = info
            if set(regular) != set(expected):
                raise HabitatTestAssetError("PointNav ZIP member set differs from the manifest")
            for archive_path, descriptor in expected.items():
                info = regular[archive_path]
                if info.file_size != descriptor.size_bytes:
                    raise HabitatTestAssetError("PointNav member size differs from the manifest")
                payload = bundle.read(info)
                if len(payload) != descriptor.size_bytes:
                    raise HabitatTestAssetError("PointNav member extraction was truncated")
                if hashlib.sha256(payload).hexdigest() != descriptor.sha256:
                    raise HabitatTestAssetError("PointNav member SHA-256 mismatch")
                target = staging / descriptor.relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
    except (OSError, zipfile.BadZipFile) as exc:
        raise HabitatTestAssetError(f"invalid PointNav ZIP: {exc}") from exc


def _smoke_episode_descriptor(
    manifest: Mapping[str, Any],
    data_root: Path,
) -> dict[str, Any]:
    pointnav = manifest["pointnav_asset"]
    relative = Path("datasets/pointnav/habitat-test-scenes/v1/val/val.json.gz")
    dataset = data_root / relative
    try:
        with gzip.open(dataset, "rb") as stream:
            payload = stream.read(16 * 1024 * 1024 + 1)
    except (OSError, EOFError) as exc:
        raise HabitatTestAssetError(f"cannot read PointNav fixture: {exc}") from exc
    if len(payload) > 16 * 1024 * 1024:
        raise HabitatTestAssetError("PointNav fixture exceeds its decompression bound")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HabitatTestAssetError("PointNav fixture is not valid JSON") from exc
    episodes = document.get("episodes") if isinstance(document, dict) else None
    if not isinstance(episodes, list) or len(episodes) != pointnav["expected_val_episode_count"]:
        raise HabitatTestAssetError("PointNav fixture episode count differs from the manifest")
    selected = [
        item
        for item in episodes
        if isinstance(item, dict)
        and str(item.get("episode_id")) == pointnav["smoke_episode_id"]
        and item.get("scene_id") == pointnav["expected_smoke_scene_id"]
    ]
    if len(selected) != 1:
        raise HabitatTestAssetError("PointNav smoke episode/scene pair is not unique")
    episode = selected[0]
    position = episode.get("start_position")
    rotation = episode.get("start_rotation")
    if not (
        isinstance(position, list)
        and len(position) == 3
        and isinstance(rotation, list)
        and len(rotation) == 4
        and all(isinstance(value, (int, float)) and math.isfinite(value) for value in position)
        and all(isinstance(value, (int, float)) and math.isfinite(value) for value in rotation)
    ):
        raise HabitatTestAssetError("PointNav smoke episode has an invalid start transform")
    return {
        "split": pointnav["smoke_split"],
        "episode_id": pointnav["smoke_episode_id"],
        "scene_id": pointnav["expected_smoke_scene_id"],
        "start_transform_present": True,
        "goal_read_or_used": False,
        "episode_count": len(episodes),
    }


def inspect_assets(
    *,
    manifest_path: Path = ASSET_MANIFEST_PATH,
    cache_root: Path = DEFAULT_ASSET_CACHE_ROOT,
) -> dict[str, Any]:
    manifest = load_asset_manifest(manifest_path)
    layout = asset_layout(manifest_path, cache_root)
    descriptors = _asset_files(manifest)
    expected_paths = {item.relative_path for item in descriptors}
    file_rows: list[dict[str, Any]] = []
    exact_files = True
    no_symlinks = True
    actual_paths: set[Path] = set()
    if layout.bundle_root.is_dir() and not layout.bundle_root.is_symlink():
        for path in layout.bundle_root.rglob("*"):
            relative = path.relative_to(layout.bundle_root)
            try:
                mode = path.lstat().st_mode
            except OSError:
                no_symlinks = False
                continue
            if stat.S_ISLNK(mode):
                no_symlinks = False
            elif stat.S_ISREG(mode):
                actual_paths.add(relative)
    else:
        exact_files = False
    for descriptor in descriptors:
        target = layout.bundle_root / descriptor.relative_path
        ready = bool(
            target.is_file()
            and not target.is_symlink()
            and target.stat().st_size == descriptor.size_bytes
            and _sha256_file(target) == descriptor.sha256
        )
        exact_files = exact_files and ready
        file_rows.append(
            {
                "role": descriptor.role,
                "path": descriptor.relative_path.as_posix(),
                "size_bytes": descriptor.size_bytes,
                "sha256": descriptor.sha256,
                "verified": ready,
            }
        )
    provenance_ready = False
    if layout.provenance.is_file() and not layout.provenance.is_symlink():
        try:
            value = json.loads(layout.provenance.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                provenance_ready = bool(
                    value.get("schema_version") == 1
                    and value.get("bundle_id") == manifest["bundle_id"]
                    and value.get("asset_manifest_sha256") == layout.manifest_sha256
                    and value.get("official_evaluator_executed") is False
                    and value.get("navigation_metrics_emitted") is False
                )
        except (OSError, json.JSONDecodeError):
            provenance_ready = False
    allowed_files = expected_paths | {Path(_PROVENANCE_NAME)}
    exact_files = exact_files and actual_paths == allowed_files
    try:
        episode = _smoke_episode_descriptor(manifest, layout.data_root) if exact_files else None
        episode_ready = episode is not None
    except HabitatTestAssetError:
        episode = None
        episode_ready = False
    ready = bool(exact_files and no_symlinks and provenance_ready and episode_ready)
    return {
        "schema_version": 1,
        "bundle_id": manifest["bundle_id"],
        "asset_manifest_sha256": layout.manifest_sha256,
        "bundle_root": str(layout.bundle_root),
        "data_root": str(layout.data_root),
        "files": file_rows,
        "exact_file_set_verified": exact_files,
        "no_symlinks": no_symlinks,
        "provenance_verified": provenance_ready,
        "smoke_episode": episode,
        "ready": ready,
        "access": {
            "scene_repository_public": manifest["scene_asset"]["public"],
            "scene_repository_gated": manifest["scene_asset"]["gated"],
            "credential_required": False,
            "scene_license": manifest["scene_asset"]["license"],
        },
        "eligibility": manifest["eligibility"],
    }


def prepare_assets(
    *,
    manifest_path: Path = ASSET_MANIFEST_PATH,
    cache_root: Path = DEFAULT_ASSET_CACHE_ROOT,
    confirm_bundle_id: str,
    timeout_s: float = 120.0,
    opener: UrlOpen = _SAFE_ASSET_OPENER.open,
) -> dict[str, Any]:
    manifest = load_asset_manifest(manifest_path)
    if confirm_bundle_id != manifest["bundle_id"]:
        raise HabitatTestAssetError(
            "--confirm-bundle-id must exactly equal the frozen test-asset bundle ID"
        )
    if timeout_s <= 0 or timeout_s > 600:
        raise ValueError("timeout_s must be in (0, 600]")
    layout = asset_layout(manifest_path, cache_root)
    if layout.bundle_root.exists():
        status = inspect_assets(manifest_path=manifest_path, cache_root=cache_root)
        if status["ready"] is not True:
            raise HabitatTestAssetError("refusing to replace an invalid existing asset bundle")
        return status
    layout.cache_root.mkdir(parents=True, exist_ok=True)
    descriptors = _asset_files(manifest)
    direct = tuple(item for item in descriptors if item.url is not None)
    required_bytes = sum(item.size_bytes for item in direct) + sum(
        item.size_bytes for item in descriptors if item.role == "pointnav_member"
    )
    if shutil.disk_usage(layout.cache_root).free < required_bytes * 2:
        raise HabitatTestAssetError("insufficient free space for the verified asset bundle")
    staging = Path(tempfile.mkdtemp(prefix=".habitat-test-assets-", dir=layout.cache_root))
    records: list[dict[str, Any]] = []
    try:
        pointnav = manifest["pointnav_asset"]
        for descriptor in direct:
            record = _download_verified(
                descriptor,
                staging / descriptor.relative_path,
                timeout_s=timeout_s,
                opener=opener,
                expected_etag=(
                    str(pointnav["etag"]) if descriptor.role == "pointnav_archive" else None
                ),
                expected_version_id=(
                    str(pointnav["s3_version_id"])
                    if descriptor.role == "pointnav_archive"
                    else None
                ),
            )
            records.append(record)
        archive = next(item for item in direct if item.role == "pointnav_archive")
        _extract_pointnav(staging / archive.relative_path, staging, descriptors)
        episode = _smoke_episode_descriptor(manifest, staging / "data")
        provenance = {
            "schema_version": 1,
            "bundle_id": manifest["bundle_id"],
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "asset_manifest_sha256": layout.manifest_sha256,
            "official_data_utility_commit": manifest["official_data_utility"]["commit"],
            "scene_repository_commit": manifest["scene_asset"]["commit"],
            "scene_license": manifest["scene_asset"]["license"],
            "credential_or_clickthrough_used": False,
            "downloads": records,
            "smoke_episode": episode,
            "official_evaluator_executed": False,
            "navigation_metrics_emitted": False,
            "habitat_2020_protocol_executed": False,
        }
        payload = (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode()
        with (staging / _PROVENANCE_NAME).open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        for path in staging.rglob("*"):
            if path.is_file() and not path.is_symlink():
                path.chmod(0o444)
        staging.rename(layout.bundle_root)
    except Exception:
        if staging.exists() and staging.parent == layout.cache_root:
            shutil.rmtree(staging)
        raise
    status = inspect_assets(manifest_path=manifest_path, cache_root=cache_root)
    if status["ready"] is not True:
        raise HabitatTestAssetError("prepared asset bundle failed post-download verification")
    return status


def build_scene_smoke_command(
    rootfs: Path,
    data_root: Path,
    bindings: GpuBindings,
    *,
    smoke_script: Path = DEFAULT_SCENE_SMOKE_SCRIPT,
) -> list[str]:
    if not data_root.is_dir() or data_root.is_symlink():
        raise HabitatTestAssetError("verified test-asset data root is unavailable")
    command = build_smoke_command(rootfs, bindings, smoke_script=smoke_script)
    try:
        probe_mount = command.index("/opt/parcel-smoke/probe.py")
    except ValueError as exc:
        raise HabitatTestAssetError("isolated runtime command lacks its fixed probe mount") from exc
    command[probe_mount + 1 : probe_mount + 1] = [
        "--dir",
        "/opt/parcel-smoke/data",
        "--ro-bind",
        str(data_root.resolve()),
        "/opt/parcel-smoke/data",
    ]
    return command


def _parse_scene_output(stdout: str) -> dict[str, Any]:
    matches = [
        line[len(_SCENE_SENTINEL) :]
        for line in stdout.splitlines()
        if line.startswith(_SCENE_SENTINEL)
    ]
    if len(matches) != 1:
        raise HabitatTestAssetError("scene smoke did not emit exactly one result sentinel")
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise HabitatTestAssetError("scene smoke result is invalid JSON") from exc
    if not isinstance(value, dict):
        raise HabitatTestAssetError("scene smoke result must be a JSON object")
    return value


def _text_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def run_scene_smoke(
    *,
    asset_manifest_path: Path = ASSET_MANIFEST_PATH,
    runtime_manifest_path: Path = RUNTIME_MANIFEST_PATH,
    asset_cache_root: Path = DEFAULT_ASSET_CACHE_ROOT,
    runtime_cache_root: Path = DEFAULT_RUNTIME_CACHE_ROOT,
    confirm_bundle_id: str,
    confirm_image_digest: str,
    timeout_s: float = 180.0,
    bindings: GpuBindings | None = None,
) -> dict[str, Any]:
    if timeout_s <= 0 or timeout_s > 600:
        raise ValueError("timeout_s must be in (0, 600]")
    asset_manifest = load_asset_manifest(asset_manifest_path)
    if confirm_bundle_id != asset_manifest["bundle_id"]:
        raise HabitatTestAssetError(
            "--confirm-bundle-id must exactly equal the frozen test-asset bundle ID"
        )
    runtime_manifest = load_manifest(runtime_manifest_path)
    if confirm_image_digest != runtime_manifest["container"]["base_digest"]:
        raise HabitatTestAssetError(
            "--confirm-image-digest must exactly equal the frozen Habitat image digest"
        )
    assets = inspect_assets(manifest_path=asset_manifest_path, cache_root=asset_cache_root)
    if assets["ready"] is not True:
        raise HabitatTestAssetError("test assets are not fully verified; run --prepare first")
    runtime = inspect_runtime(
        manifest_path=runtime_manifest_path,
        cache_root=runtime_cache_root,
        verify_blob_hashes=True,
    )
    if runtime["ready"] is not True:
        raise HabitatTestAssetError("archived Habitat rootfs failed full verification")
    asset_layout_value = asset_layout(asset_manifest_path, asset_cache_root)
    runtime_layout_value = runtime_layout(runtime_manifest, runtime_cache_root)
    resolved_bindings = bindings or discover_gpu_bindings()
    command = build_scene_smoke_command(
        runtime_layout_value.rootfs,
        asset_layout_value.data_root,
        resolved_bindings,
    )
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
        probe = _parse_scene_output(stdout)
        parse_error: str | None = None
    except HabitatTestAssetError as exc:
        probe = {"passed": False, "error": str(exc)}
        parse_error = str(exc)
    claims = probe.get("claims")
    cuda = probe.get("cuda")
    egl = probe.get("egl")
    rendering = probe.get("rendering")
    actions = probe.get("actions")
    passed = bool(
        not timed_out
        and exit_code == 0
        and parse_error is None
        and probe.get("passed") is True
        and isinstance(cuda, dict)
        and cuda.get("passed") is True
        and isinstance(egl, dict)
        and egl.get("passed") is True
        and isinstance(rendering, dict)
        and rendering.get("passed") is True
        and isinstance(actions, dict)
        and actions.get("executed") == asset_manifest["smoke"]["actions"]
        and isinstance(claims, dict)
        and all(
            claims.get(key) is True
            for key in (
                "pointnav_fixture_start_state_used",
                "scene_loaded",
                "simulator_constructed",
                "gpu_render_executed",
                "discrete_actions_executed",
            )
        )
        and all(
            claims.get(key) is False
            for key in (
                "parcel_policy_executed",
                "official_evaluator_executed",
                "navigation_episode_executed",
                "navigation_metrics_emitted",
                "cuda_compute_kernel_executed",
            )
        )
    )
    generated_at = datetime.now(timezone.utc)
    inventory = runtime.get("rootfs_inventory_actual")
    return {
        "schema_version": 1,
        "run_id": f"habitat-test-assets-gpu-scene-smoke-{generated_at.strftime('%Y%m%dT%H%M%SZ')}",
        "generated_at_utc": generated_at.isoformat(),
        "result": {"passed": passed, "probe": probe},
        "runtime": {
            "image_manifest_digest": confirm_image_digest,
            "rootfs_inventory_verified_before_execution": True,
            "rootfs_inventory": inventory,
            "bubblewrap_exit_code": exit_code,
            "network_available_inside_sandbox": False,
            "asset_mount_read_only": True,
            "timed_out": timed_out,
            "result_parse_error": parse_error,
            "elapsed_ms": elapsed_ms,
            "stderr": stderr[-4096:],
        },
        "assets": {
            "bundle_id": asset_manifest["bundle_id"],
            "manifest_sha256": asset_layout_value.manifest_sha256,
            "scene_repository_commit": asset_manifest["scene_asset"]["commit"],
            "scene_license": asset_manifest["scene_asset"]["license"],
            "credential_or_clickthrough_used": False,
            "pointnav_archive_sha256": asset_manifest["pointnav_asset"]["sha256"],
            "test_fixture_episode_id": asset_manifest["pointnav_asset"]["smoke_episode_id"],
            "goal_read_or_used": False,
        },
        "provenance": {
            "runner_path": Path(__file__).relative_to(REPO_ROOT).as_posix(),
            "runner_sha256": _sha256_file(Path(__file__)),
            "smoke_script_path": DEFAULT_SCENE_SMOKE_SCRIPT.relative_to(REPO_ROOT).as_posix(),
            "smoke_script_sha256": _sha256_file(DEFAULT_SCENE_SMOKE_SCRIPT),
            "asset_manifest_path": asset_manifest_path.resolve().relative_to(REPO_ROOT).as_posix(),
            "all_asset_hashes_verified_before_execution": True,
            "all_compressed_image_layer_hashes_verified_before_execution": True,
            "glvnd_client_source": "archived_image_rootfs",
            "injected_host_driver_libraries": [name for name, _ in resolved_bindings.libraries],
            "injected_host_driver_max_required_glibc": dict(resolved_bindings.max_required_glibc),
        },
        "evaluation": {
            "habitat_2020_protocol": False,
            "official_rank_eligible": False,
            "leaderboard_comparable": False,
            "official_evaluator_executed": False,
            "navigation_episode_executed": False,
            "navigation_metrics_emitted": False,
            "allowed_claim": asset_manifest["eligibility"]["allowed_claim"],
            "forbidden_claim": asset_manifest["eligibility"]["forbidden_claim"],
        },
        "claims": {
            "image_entrypoint_executed": False,
            "image_hooks_executed": False,
            "package_manager_executed": False,
            "network_available_inside_sandbox": False,
            "dataset_mounted_or_used": True,
            "simulator_constructed": bool(claims and claims.get("simulator_constructed")),
            "scene_loaded": bool(claims and claims.get("scene_loaded")),
            "gpu_render_executed": bool(claims and claims.get("gpu_render_executed")),
            "cuda_compute_kernel_executed": False,
            "parcel_policy_executed": False,
            "official_evaluator_executed": False,
            "navigation_episode_executed": False,
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
    parser.add_argument("--asset-manifest", type=Path, default=ASSET_MANIFEST_PATH)
    parser.add_argument("--runtime-manifest", type=Path, default=RUNTIME_MANIFEST_PATH)
    parser.add_argument("--asset-cache-root", type=Path, default=DEFAULT_ASSET_CACHE_ROOT)
    parser.add_argument("--runtime-cache-root", type=Path, default=DEFAULT_RUNTIME_CACHE_ROOT)
    parser.add_argument("--confirm-bundle-id")
    parser.add_argument("--confirm-image-digest")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            if not args.confirm_bundle_id:
                raise HabitatTestAssetError("--prepare requires --confirm-bundle-id")
            report = prepare_assets(
                manifest_path=args.asset_manifest,
                cache_root=args.asset_cache_root,
                confirm_bundle_id=args.confirm_bundle_id,
                timeout_s=args.timeout,
            )
        elif args.smoke:
            if not args.confirm_bundle_id or not args.confirm_image_digest or args.output is None:
                raise HabitatTestAssetError(
                    "--smoke requires both confirmations and a unique --output"
                )
            report = run_scene_smoke(
                asset_manifest_path=args.asset_manifest,
                runtime_manifest_path=args.runtime_manifest,
                asset_cache_root=args.asset_cache_root,
                runtime_cache_root=args.runtime_cache_root,
                confirm_bundle_id=args.confirm_bundle_id,
                confirm_image_digest=args.confirm_image_digest,
                timeout_s=args.timeout,
            )
            _write_immutable(args.output, report)
        else:
            report = inspect_assets(
                manifest_path=args.asset_manifest,
                cache_root=args.asset_cache_root,
            )
    except (
        HabitatTestAssetError,
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
