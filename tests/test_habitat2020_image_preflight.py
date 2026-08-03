from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Self

import pytest

from evals.external.habitat2020_doctor import load_manifest
from evals.external.habitat2020_image_preflight import (
    ImagePreflightError,
    fetch_registry_contract,
    run_image_preflight,
    verify_image_contract,
    write_immutable_report,
)


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _fixture() -> tuple[dict[str, Any], bytes, bytes, dict[str, Any]]:
    manifest = copy.deepcopy(load_manifest())
    config_document = {
        "architecture": "amd64",
        "os": "linux",
        "created": "2020-05-21T03:51:03Z",
        "config": {"Env": ["CUDA_VERSION=10.1.243"]},
        "rootfs": {
            "type": "layers",
            "diff_ids": [f"sha256:{'1' * 64}", f"sha256:{'2' * 64}"],
        },
        "history": [
            {"created_by": "conda create -n habitat python=3.6 cmake=3.14.0"},
            {
                "created_by": (
                    "git clone --branch challenge-2020 "
                    "https://github.com/facebookresearch/habitat-sim.git"
                )
            },
        ],
    }
    config_bytes = json.dumps(config_document, separators=(",", ":")).encode()
    config_digest = _digest(config_bytes)
    layers = [
        {
            "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
            "size": 11,
            "digest": f"sha256:{'a' * 64}",
        },
        {
            "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
            "size": 13,
            "digest": f"sha256:{'b' * 64}",
        },
    ]
    manifest_document = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {
            "mediaType": "application/vnd.docker.container.image.v1+json",
            "size": len(config_bytes),
            "digest": config_digest,
        },
        "layers": layers,
    }
    manifest_bytes = json.dumps(manifest_document, separators=(",", ":")).encode()
    manifest_digest = _digest(manifest_bytes)
    container = manifest["container"]
    container["base_digest"] = manifest_digest
    container["base_reference"] = f"{container['registry']['repository']}@{manifest_digest}"
    container["compressed_size_bytes_observed"] = 24
    container["registry"].update(
        {
            "config_digest": config_digest,
            "config_size_bytes": len(config_bytes),
            "layer_count": 2,
            "compressed_layer_size_bytes": 24,
        }
    )
    gpu = {
        "detected": True,
        "gpus": [
            {
                "name": "Fixture GPU",
                "memory_total_mib": 32768,
                "driver_version": "999.1",
                "compute_capability": "8.9",
            }
        ],
        "device_nodes": {
            "/dev/nvidiactl": True,
            "/dev/nvidia0": True,
            "/dev/nvidia-uvm": True,
        },
        "libraries": {"libcuda": "libcuda.so.1", "libEGL_nvidia": "libEGL_nvidia.so.0"},
        "error": None,
    }
    return manifest, manifest_bytes, config_bytes, gpu


class _Response:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.payload


def test_frozen_manifest_pins_live_registry_descriptor_contract() -> None:
    manifest = load_manifest()
    container = manifest["container"]

    assert container["registry"] == {
        "api": "https://registry-1.docker.io/v2",
        "auth_url": "https://auth.docker.io/token",
        "auth_service": "registry.docker.io",
        "repository": "fairembodied/habitat-challenge",
        "manifest_media_type": "application/vnd.docker.distribution.manifest.v2+json",
        "config_media_type": "application/vnd.docker.container.image.v1+json",
        "config_digest": "sha256:75e366deb8ce44eaa3b24d164f17042a28543a5cf2ceac20d1eda3dee69cdb5e",
        "config_size_bytes": 14463,
        "layer_count": 23,
        "compressed_layer_size_bytes": 3210119745,
    }
    compatibility_assets = manifest["license_free_compatibility_assets"]
    assert compatibility_assets["scene_download_uid"] == "habitat_test_scenes"
    assert compatibility_assets["pointnav_episode_download_uid"] == (
        "habitat_test_pointnav_dataset"
    )
    assert compatibility_assets["credential_or_clickthrough_acceptance_required"] is False
    assert compatibility_assets["frozen_gibson_val_mini_equivalent"] is False
    assert compatibility_assets["official_rank_eligible"] is False


def test_verifier_passes_exact_descriptor_and_host_gpu_prerequisites() -> None:
    manifest, manifest_bytes, config_bytes, gpu = _fixture()

    result = verify_image_contract(
        manifest,
        registry_manifest_bytes=manifest_bytes,
        registry_manifest_response_digest=manifest["container"]["base_digest"],
        image_config_bytes=config_bytes,
        host_gpu=gpu,
    )

    assert result["passed"] is True
    assert result["failed_checks"] == []
    assert result["registry"]["compressed_layer_size_bytes"] == 24
    assert all(check["passed"] for check in result["checks"])


def test_verifier_fails_closed_on_registry_payload_or_gpu_drift() -> None:
    manifest, manifest_bytes, config_bytes, gpu = _fixture()
    gpu["libraries"]["libEGL_nvidia"] = None

    result = verify_image_contract(
        manifest,
        registry_manifest_bytes=manifest_bytes + b" ",
        registry_manifest_response_digest=manifest["container"]["base_digest"],
        image_config_bytes=config_bytes,
        host_gpu=gpu,
    )

    assert result["passed"] is False
    assert "manifest_payload_digest" in result["failed_checks"]
    assert "host_nvidia_compute_graphics_libraries" in result["failed_checks"]


def test_fetcher_uses_digest_endpoint_and_downloads_no_layers() -> None:
    manifest, manifest_bytes, config_bytes, _gpu = _fixture()
    calls: list[tuple[str, dict[str, str]]] = []
    responses = [
        _Response(json.dumps({"token": "fixture-token"}).encode()),
        _Response(
            manifest_bytes,
            {"Docker-Content-Digest": manifest["container"]["base_digest"]},
        ),
        _Response(config_bytes),
    ]

    def opener(request: Any, *, timeout: float) -> _Response:
        assert timeout == 3.0
        calls.append((request.full_url, dict(request.headers)))
        return responses.pop(0)

    fetched = fetch_registry_contract(manifest, timeout_s=3.0, opener=opener)

    assert fetched["manifest_bytes"] == manifest_bytes
    assert fetched["config_bytes"] == config_bytes
    assert len(calls) == 3
    assert calls[1][0].endswith(manifest["container"]["base_digest"])
    assert "/blobs/" in calls[2][0]
    assert all("/blobs/sha256:aaaa" not in url for url, _headers in calls)
    assert calls[1][1]["Authorization"] == "Bearer fixture-token"


def test_live_runner_shape_keeps_all_score_claims_negative(tmp_path: Path) -> None:
    manifest, manifest_bytes, config_bytes, gpu = _fixture()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    responses = [
        _Response(json.dumps({"token": "fixture-token"}).encode()),
        _Response(
            manifest_bytes,
            {"Docker-Content-Digest": manifest["container"]["base_digest"]},
        ),
        _Response(config_bytes),
    ]

    def opener(_request: Any, *, timeout: float) -> _Response:
        assert timeout == 3.0
        return responses.pop(0)

    report = run_image_preflight(
        manifest_path=manifest_path,
        timeout_s=3.0,
        opener=opener,
        host_gpu=gpu,
    )

    assert report["result"]["passed"] is True
    assert report["evaluation"]["official_rank_eligible"] is False
    assert report["evaluation"]["official_evaluator_executed"] is False
    assert report["evaluation"]["navigation_metrics_emitted"] is False
    assert report["execution"]["image_layers_downloaded"] is False
    assert report["execution"]["gpu_kernel_executed"] is False
    assert report["readiness"]["ready_for_habitat_gpu_render"] is False


def test_fetcher_rejects_mutable_or_malformed_image_contract() -> None:
    manifest, _manifest_bytes, _config_bytes, _gpu = _fixture()
    manifest["container"]["base_digest"] = "latest"

    with pytest.raises(ImagePreflightError, match="immutable sha256"):
        fetch_registry_contract(manifest, opener=lambda *_args, **_kwargs: None)


def test_preflight_report_is_write_once(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    report = {"schema_version": 1, "result": {"passed": True}}

    write_immutable_report(output, report)

    assert output.read_text(encoding="utf-8").endswith("\n")
    with pytest.raises(FileExistsError):
        write_immutable_report(output, report)
