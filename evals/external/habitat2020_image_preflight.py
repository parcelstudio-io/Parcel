"""Verify the exact archived Habitat 2020 image and host GPU boundary.

This is a bounded, networked provenance preflight.  It reads the immutable
Docker Registry manifest and image-config blob, but deliberately does not
download image layers, execute a container, load a scene, or emit navigation
metrics.  Passing therefore proves that the archived official-code runtime is
still content-addressably retrievable and that this host exposes the basic
NVIDIA devices/libraries needed by a later render smoke.  It does not prove
CUDA/EGL runtime compatibility or any Habitat score.
"""

from __future__ import annotations

import argparse
import ctypes.util
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .habitat2020_doctor import MANIFEST_PATH, REPO_ROOT, load_manifest

DEFAULT_RESULTS_DIR = REPO_ROOT / "evals/external/results/habitat2020"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MANIFEST_ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"
_MAX_TOKEN_BYTES = 256 * 1024
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_CONFIG_BYTES = 2 * 1024 * 1024
_GPU_DEVICE_PATHS = (
    Path("/dev/nvidiactl"),
    Path("/dev/nvidia0"),
    Path("/dev/nvidia-uvm"),
)

UrlOpen = Callable[..., Any]


class ImagePreflightError(RuntimeError):
    """Raised when the registry or frozen image contract fails closed."""


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_bounded(response: Any, *, limit: int, label: str) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise ImagePreflightError(f"{label} has invalid Content-Length") from exc
        if declared_size < 0 or declared_size > limit:
            raise ImagePreflightError(f"{label} exceeds the {limit}-byte bound")
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ImagePreflightError(f"{label} exceeds the {limit}-byte bound")
    return payload


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImagePreflightError(f"{label} is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ImagePreflightError(f"{label} must be a JSON object")
    return document


def _request(
    url: str,
    *,
    headers: Mapping[str, str] | None,
    timeout_s: float,
    opener: UrlOpen,
) -> Any:
    request = urllib.request.Request(
        url,
        headers=dict(headers or {}),
        method="GET",
    )
    try:
        return opener(request, timeout=timeout_s)
    except Exception as exc:  # urllib exposes several transport exception types
        raise ImagePreflightError(f"registry request failed for {url}: {exc}") from exc


def fetch_registry_contract(
    manifest: Mapping[str, Any],
    *,
    timeout_s: float = 20.0,
    opener: UrlOpen = urllib.request.urlopen,
) -> dict[str, Any]:
    """Fetch only the pinned registry manifest and its small config blob."""

    if timeout_s <= 0.0 or timeout_s > 120.0:
        raise ValueError("timeout_s must be in (0, 120]")
    try:
        container = manifest["container"]
        registry = container["registry"]
        repository = str(registry["repository"])
        digest = str(container["base_digest"])
        api = str(registry["api"]).rstrip("/")
        auth_url = str(registry["auth_url"])
        auth_service = str(registry["auth_service"])
    except (KeyError, TypeError) as exc:
        raise ImagePreflightError("Habitat manifest lacks the registry contract") from exc
    if _DIGEST.fullmatch(digest) is None:
        raise ImagePreflightError("base image must use an immutable sha256 digest")
    if not repository or "/" not in repository:
        raise ImagePreflightError("registry repository is invalid")

    auth_query = urllib.parse.urlencode(
        {
            "service": auth_service,
            "scope": f"repository:{repository}:pull",
        }
    )
    started_ns = time.perf_counter_ns()
    with _request(
        f"{auth_url}?{auth_query}",
        headers={"Accept": "application/json"},
        timeout_s=timeout_s,
        opener=opener,
    ) as response:
        token_document = _json_object(
            _read_bounded(response, limit=_MAX_TOKEN_BYTES, label="registry token"),
            label="registry token",
        )
    token = token_document.get("token") or token_document.get("access_token")
    if not isinstance(token, str) or not token:
        raise ImagePreflightError("registry token response has no bearer token")

    authorization = {"Authorization": f"Bearer {token}"}
    manifest_url = f"{api}/{repository}/manifests/{digest}"
    manifest_headers = {**authorization, "Accept": _MANIFEST_ACCEPT}
    with _request(
        manifest_url,
        headers=manifest_headers,
        timeout_s=timeout_s,
        opener=opener,
    ) as response:
        response_digest = response.headers.get("Docker-Content-Digest")
        manifest_bytes = _read_bounded(
            response,
            limit=_MAX_MANIFEST_BYTES,
            label="registry manifest",
        )

    manifest_document = _json_object(manifest_bytes, label="registry manifest")
    config_descriptor = manifest_document.get("config")
    if not isinstance(config_descriptor, dict):
        raise ImagePreflightError("registry manifest has no config descriptor")
    config_digest = config_descriptor.get("digest")
    if not isinstance(config_digest, str) or _DIGEST.fullmatch(config_digest) is None:
        raise ImagePreflightError("registry config descriptor has an invalid digest")
    config_url = f"{api}/{repository}/blobs/{config_digest}"
    with _request(
        config_url,
        headers=authorization,
        timeout_s=timeout_s,
        opener=opener,
    ) as response:
        config_bytes = _read_bounded(
            response,
            limit=_MAX_CONFIG_BYTES,
            label="image config",
        )
    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
    return {
        "manifest_bytes": manifest_bytes,
        "manifest_response_digest": response_digest,
        "config_bytes": config_bytes,
        "elapsed_ms": elapsed_ms,
        "request_urls": {
            "manifest": manifest_url,
            "config": config_url,
        },
    }


def probe_host_gpu() -> dict[str, Any]:
    """Read basic NVIDIA hardware and rootless-injection prerequisites."""

    executable = shutil.which("nvidia-smi")
    gpus: list[dict[str, Any]] = []
    error: str | None = None
    if executable is None:
        error = "nvidia-smi not found"
    else:
        try:
            completed = subprocess.run(
                [
                    executable,
                    "--query-gpu=name,memory.total,driver_version,compute_cap",
                    "--format=csv,noheader,nounits",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            error = str(exc)
        else:
            if completed.returncode != 0:
                error = completed.stderr.strip() or f"nvidia-smi exited {completed.returncode}"
            else:
                for row in completed.stdout.splitlines():
                    values = [value.strip() for value in row.split(",")]
                    if len(values) != 4:
                        error = "unexpected nvidia-smi output"
                        gpus = []
                        break
                    try:
                        memory_mib = int(values[1])
                    except ValueError:
                        error = "invalid GPU memory value from nvidia-smi"
                        gpus = []
                        break
                    gpus.append(
                        {
                            "name": values[0],
                            "memory_total_mib": memory_mib,
                            "driver_version": values[2],
                            "compute_capability": values[3],
                        }
                    )

    devices = {str(path): path.exists() for path in _GPU_DEVICE_PATHS}
    libraries = {
        "libcuda": ctypes.util.find_library("cuda"),
        "libEGL_nvidia": ctypes.util.find_library("EGL_nvidia"),
    }
    return {
        "detected": bool(gpus) and error is None,
        "gpus": gpus,
        "device_nodes": devices,
        "libraries": libraries,
        "error": error,
    }


def verify_image_contract(
    manifest: Mapping[str, Any],
    *,
    registry_manifest_bytes: bytes,
    registry_manifest_response_digest: str | None,
    image_config_bytes: bytes,
    host_gpu: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify registry bytes, archived stack declarations, and GPU prerequisites."""

    container = manifest["container"]
    registry = container["registry"]
    expected_manifest_digest = str(container["base_digest"])
    expected_config_digest = str(registry["config_digest"])
    manifest_document = _json_object(registry_manifest_bytes, label="registry manifest")
    config_document = _json_object(image_config_bytes, label="image config")
    checks: list[dict[str, Any]] = []

    def record(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"id": check_id, "passed": bool(passed), "detail": detail})

    actual_manifest_digest = _sha256_bytes(registry_manifest_bytes)
    record(
        "manifest_payload_digest",
        actual_manifest_digest == expected_manifest_digest,
        f"expected={expected_manifest_digest}; actual={actual_manifest_digest}",
    )
    record(
        "registry_content_digest",
        registry_manifest_response_digest == expected_manifest_digest,
        f"expected={expected_manifest_digest}; header={registry_manifest_response_digest}",
    )
    record(
        "manifest_media_type",
        manifest_document.get("mediaType") == registry["manifest_media_type"],
        str(manifest_document.get("mediaType")),
    )
    record(
        "manifest_schema",
        manifest_document.get("schemaVersion") == 2,
        f"schemaVersion={manifest_document.get('schemaVersion')}",
    )

    descriptor = manifest_document.get("config")
    descriptor_ready = isinstance(descriptor, dict)
    descriptor_digest = descriptor.get("digest") if descriptor_ready else None
    descriptor_size = descriptor.get("size") if descriptor_ready else None
    descriptor_media = descriptor.get("mediaType") if descriptor_ready else None
    record(
        "config_descriptor",
        descriptor_ready
        and descriptor_digest == expected_config_digest
        and descriptor_size == registry["config_size_bytes"]
        and descriptor_media == registry["config_media_type"],
        f"digest={descriptor_digest}; size={descriptor_size}; mediaType={descriptor_media}",
    )
    actual_config_digest = _sha256_bytes(image_config_bytes)
    record(
        "config_payload",
        actual_config_digest == expected_config_digest
        and len(image_config_bytes) == registry["config_size_bytes"],
        f"digest={actual_config_digest}; size={len(image_config_bytes)}",
    )

    layers = manifest_document.get("layers")
    layer_list = layers if isinstance(layers, list) else []
    valid_layer_descriptors = bool(layer_list) and all(
        isinstance(layer, dict)
        and isinstance(layer.get("digest"), str)
        and _DIGEST.fullmatch(layer["digest"]) is not None
        and isinstance(layer.get("size"), int)
        and layer["size"] > 0
        for layer in layer_list
    )
    compressed_bytes = (
        sum(int(layer["size"]) for layer in layer_list) if valid_layer_descriptors else None
    )
    unique_digests = (
        len({str(layer["digest"]) for layer in layer_list}) == len(layer_list)
        if valid_layer_descriptors
        else False
    )
    record(
        "layer_descriptors",
        valid_layer_descriptors
        and unique_digests
        and len(layer_list) == registry["layer_count"]
        and compressed_bytes == registry["compressed_layer_size_bytes"]
        and compressed_bytes == container["compressed_size_bytes_observed"],
        f"count={len(layer_list)}; unique={unique_digests}; compressed_bytes={compressed_bytes}",
    )

    rootfs = config_document.get("rootfs")
    diff_ids = rootfs.get("diff_ids") if isinstance(rootfs, dict) else None
    rootfs_ready = (
        isinstance(diff_ids, list)
        and len(diff_ids) == len(layer_list)
        and all(isinstance(value, str) and _DIGEST.fullmatch(value) for value in diff_ids)
    )
    record(
        "rootfs_chain",
        rootfs_ready,
        f"type={rootfs.get('type') if isinstance(rootfs, dict) else None}; diff_ids={len(diff_ids) if isinstance(diff_ids, list) else None}",
    )
    record(
        "image_platform",
        config_document.get("os") == "linux" and config_document.get("architecture") == "amd64",
        f"os={config_document.get('os')}; architecture={config_document.get('architecture')}",
    )

    runtime_config = config_document.get("config")
    environment = runtime_config.get("Env") if isinstance(runtime_config, dict) else None
    environment_map: dict[str, str] = {}
    if isinstance(environment, list):
        for entry in environment:
            if isinstance(entry, str) and "=" in entry:
                key, value = entry.split("=", 1)
                environment_map[key] = value
    archived_cuda = str(container["archived_cuda"])
    record(
        "archived_cuda_declaration",
        environment_map.get("CUDA_VERSION", "").startswith(f"{archived_cuda}."),
        f"CUDA_VERSION={environment_map.get('CUDA_VERSION')}",
    )
    history = config_document.get("history")
    created_commands = [
        str(entry.get("created_by", ""))
        for entry in (history if isinstance(history, list) else [])
        if isinstance(entry, dict)
    ]
    python_marker = f"python={container['archived_python']}"
    record(
        "archived_python_declaration",
        any(python_marker in command for command in created_commands),
        f"history_contains={python_marker}",
    )
    record(
        "challenge_2020_sim_build",
        any(
            "git clone --branch challenge-2020" in command and "habitat-sim" in command
            for command in created_commands
        ),
        "history contains the challenge-2020 habitat-sim source build",
    )

    gpu_detected = host_gpu.get("detected") is True and bool(host_gpu.get("gpus"))
    record("host_nvidia_gpu", gpu_detected, json.dumps(host_gpu.get("gpus", []), sort_keys=True))
    nodes = host_gpu.get("device_nodes")
    nodes_ready = isinstance(nodes, Mapping) and all(
        nodes.get(str(path)) is True for path in _GPU_DEVICE_PATHS
    )
    record("host_nvidia_device_nodes", nodes_ready, json.dumps(nodes, sort_keys=True))
    libraries = host_gpu.get("libraries")
    libraries_ready = (
        isinstance(libraries, Mapping)
        and bool(libraries.get("libcuda"))
        and bool(libraries.get("libEGL_nvidia"))
    )
    record(
        "host_nvidia_compute_graphics_libraries",
        libraries_ready,
        json.dumps(libraries, sort_keys=True),
    )

    failed = [check["id"] for check in checks if not check["passed"]]
    return {
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "registry": {
            "manifest_digest": actual_manifest_digest,
            "config_digest": actual_config_digest,
            "layer_count": len(layer_list),
            "compressed_layer_size_bytes": compressed_bytes,
            "image_created_at_utc": config_document.get("created"),
        },
        "host_gpu": dict(host_gpu),
    }


def run_image_preflight(
    *,
    manifest_path: Path = MANIFEST_PATH,
    timeout_s: float = 20.0,
    opener: UrlOpen = urllib.request.urlopen,
    host_gpu: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the live bounded preflight and return evidence with negative claims."""

    manifest = load_manifest(manifest_path)
    fetched = fetch_registry_contract(manifest, timeout_s=timeout_s, opener=opener)
    verification = verify_image_contract(
        manifest,
        registry_manifest_bytes=fetched["manifest_bytes"],
        registry_manifest_response_digest=fetched["manifest_response_digest"],
        image_config_bytes=fetched["config_bytes"],
        host_gpu=host_gpu or probe_host_gpu(),
    )
    generated_at = datetime.now(timezone.utc)
    container = manifest["container"]
    resolved_manifest_path = manifest_path.expanduser().resolve()
    manifest_display = (
        resolved_manifest_path.relative_to(REPO_ROOT).as_posix()
        if resolved_manifest_path.is_relative_to(REPO_ROOT)
        else str(resolved_manifest_path)
    )
    return {
        "schema_version": 1,
        "run_id": f"habitat20-image-preflight-{generated_at.strftime('%Y%m%dT%H%M%SZ')}",
        "generated_at_utc": generated_at.isoformat(),
        "evaluation": {
            "id": manifest["evaluation_id"],
            "scope": "archived-image-registry-and-host-gpu-preflight",
            "official_rank_eligible": False,
            "leaderboard_comparable": False,
            "official_evaluator_executed": False,
            "habitat_sim_executed": False,
            "scene_loaded": False,
            "navigation_metrics_emitted": False,
            "allowed_claim": "archived image retrieval and host GPU prerequisite preflight",
        },
        "result": verification,
        "provenance": {
            "container_reference": container["base_reference"],
            "manifest_path": manifest_display,
            "manifest_sha256": _sha256_file(resolved_manifest_path),
            "runner_path": Path(__file__).relative_to(REPO_ROOT).as_posix(),
            "runner_sha256": _sha256_file(Path(__file__)),
            "request_urls": fetched["request_urls"],
        },
        "execution": {
            "registry_network_requests_executed": True,
            "registry_elapsed_ms": fetched["elapsed_ms"],
            "image_layers_downloaded": False,
            "compressed_image_bytes_downloaded": 0,
            "container_executed": False,
            "gpu_kernel_executed": False,
            "gpu_render_executed": False,
            "dataset_downloaded_or_used": False,
            "licensed_scene_required_for_this_preflight": False,
            "production_parcel_behavior_modified": False,
            "evaluator_semantics_modified": False,
        },
        "readiness": {
            "ready_for_content_addressed_layer_fetch": verification["passed"],
            "ready_for_habitat_gpu_render": False,
            "gpu_runtime_compatibility": "unverified_requires_container_execution",
            "remaining_next_step": (
                "Materialize the exact pinned layers in an isolated runtime and run a no-dataset "
                "CUDA/EGL import smoke before any terms-gated Gibson scene run."
            ),
        },
    }


def write_immutable_report(path: Path, report: Mapping[str, Any]) -> None:
    """Write one evidence document without overwriting prior results."""

    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with target.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    target.chmod(0o444)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    try:
        report = run_image_preflight(timeout_s=args.timeout)
    except (ImagePreflightError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["result"]["passed"] is not True:
        return 2
    write_immutable_report(args.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
