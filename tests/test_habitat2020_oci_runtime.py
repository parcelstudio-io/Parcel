from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any, Self

import pytest

from evals.external.habitat2020_doctor import load_manifest
from evals.external.habitat2020_oci_runtime import (
    _SAFE_DRIVER_LIBRARY,
    GpuBindings,
    HabitatOciError,
    _apply_layer,
    _parse_smoke_output,
    build_smoke_command,
    inspect_runtime,
    prepare_runtime,
    run_smoke,
    runtime_layout,
)


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _tar_layer(files: dict[str, bytes]) -> tuple[bytes, str]:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, payload in files.items():
            member = tarfile.TarInfo(name)
            member.mode = 0o755 if name.endswith("/python") else 0o644
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    compressed = gzip.compress(raw.getvalue(), mtime=0)
    return compressed, _digest(raw.getvalue())


def _fixture_contract() -> tuple[dict[str, Any], bytes, bytes, list[bytes]]:
    manifest = copy.deepcopy(load_manifest())
    first, first_diff = _tar_layer(
        {
            "opt/conda/envs/habitat/bin/python": b"fixture-python",
            (
                "opt/conda/envs/habitat/lib/python3.6/site-packages/"
                "habitat_sim-0.1.4-py3.6-linux-x86_64.egg/habitat_sim/__init__.py"
            ): b"fixture-init",
            (
                "opt/conda/envs/habitat/lib/python3.6/site-packages/"
                "habitat_sim-0.1.4-py3.6-linux-x86_64.egg/habitat_sim/_ext/"
                "habitat_sim_bindings.cpython-36m-x86_64-linux-gnu.so"
            ): b"fixture-binding",
            "opt/conda/obsolete.txt": b"removed-by-whiteout",
        }
    )
    second, second_diff = _tar_layer(
        {
            "opt/conda/.wh.obsolete.txt": b"",
            "opt/conda/current.txt": b"current",
        }
    )
    layers = [first, second]
    descriptors = [
        {
            "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
            "size": len(payload),
            "digest": _digest(payload),
        }
        for payload in layers
    ]
    config_document = {
        "architecture": "amd64",
        "os": "linux",
        "created": "2020-05-21T03:51:03Z",
        "config": {"Env": ["CUDA_VERSION=10.1.243"]},
        "rootfs": {"type": "layers", "diff_ids": [first_diff, second_diff]},
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
    registry_manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {
            "mediaType": "application/vnd.docker.container.image.v1+json",
            "size": len(config_bytes),
            "digest": config_digest,
        },
        "layers": descriptors,
    }
    registry_bytes = json.dumps(registry_manifest, separators=(",", ":")).encode()
    manifest_digest = _digest(registry_bytes)
    container = manifest["container"]
    container["base_digest"] = manifest_digest
    container["base_reference"] = f"{container['registry']['repository']}@{manifest_digest}"
    container["compressed_size_bytes_observed"] = sum(map(len, layers))
    container["registry"].update(
        {
            "config_digest": config_digest,
            "config_size_bytes": len(config_bytes),
            "layer_count": len(layers),
            "compressed_layer_size_bytes": sum(map(len, layers)),
        }
    )
    return manifest, registry_bytes, config_bytes, layers


def _gpu() -> dict[str, Any]:
    return {
        "detected": True,
        "gpus": [{"name": "fixture"}],
        "device_nodes": {
            "/dev/nvidiactl": True,
            "/dev/nvidia0": True,
            "/dev/nvidia-uvm": True,
        },
        "libraries": {"libcuda": "libcuda.so.1", "libEGL_nvidia": "libEGL.so.0"},
        "error": None,
    }


class _Response:
    def __init__(
        self,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
        status: int = 200,
    ) -> None:
        self.payload = payload
        self.stream = io.BytesIO(payload)
        self.headers = headers or {}
        self.status = status

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.stream.read(_limit)


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_prepare_is_fully_offline_fixture_and_applies_exact_oci_chain(
    tmp_path: Path,
) -> None:
    manifest, registry_bytes, config_bytes, layers = _fixture_contract()
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, manifest)
    responses = [
        _Response(json.dumps({"token": "contract-token"}).encode()),
        _Response(
            registry_bytes,
            headers={"Docker-Content-Digest": manifest["container"]["base_digest"]},
        ),
        _Response(config_bytes),
        _Response(json.dumps({"token": "layer-token"}).encode()),
        *[_Response(payload) for payload in layers],
    ]
    calls: list[str] = []

    def opener(request: Any, *, timeout: float) -> _Response:
        assert timeout == 3.0
        calls.append(request.full_url)
        return responses.pop(0)

    cache = tmp_path / "managed/cache"
    report = prepare_runtime(
        manifest_path=manifest_path,
        cache_root=cache,
        confirm_digest=manifest["container"]["base_digest"],
        timeout_s=3.0,
        opener=opener,
        host_gpu=_gpu(),
        required_free_bytes=0,
    )

    layout = runtime_layout(manifest, cache)
    assert report["ready"] is True
    assert report["verified_blob_count"] == 2
    assert report["rootfs_inventory_verified"] is True
    assert report["rootfs_inventory_actual"] == report["rootfs_inventory_expected"]
    critical_paths = {
        item["path"] for item in json.loads(layout.metadata.read_text())["critical_files"]
    }
    assert critical_paths == {
        "opt/conda/envs/habitat/bin/python",
        (
            "opt/conda/envs/habitat/lib/python3.6/site-packages/"
            "habitat_sim-0.1.4-py3.6-linux-x86_64.egg/habitat_sim/__init__.py"
        ),
        (
            "opt/conda/envs/habitat/lib/python3.6/site-packages/"
            "habitat_sim-0.1.4-py3.6-linux-x86_64.egg/habitat_sim/_ext/"
            "habitat_sim_bindings.cpython-36m-x86_64-linux-gnu.so"
        ),
    }
    assert (layout.rootfs / "opt/conda/current.txt").read_bytes() == b"current"
    assert not (layout.rootfs / "opt/conda/obsolete.txt").exists()
    assert json.loads(layout.metadata.read_text())["entrypoint_executed"] is False
    assert len(calls) == 6
    assert all("manifests/latest" not in call for call in calls)

    noncritical = layout.rootfs / "opt/conda/current.txt"
    noncritical.write_bytes(b"tamper!")
    tamper_report = inspect_runtime(
        manifest_path=manifest_path,
        cache_root=cache,
        verify_blob_hashes=True,
    )
    assert tamper_report["critical_runtime_files_ready"] is True
    assert tamper_report["rootfs_inventory_verified"] is False
    assert tamper_report["ready"] is False
    with pytest.raises(HabitatOciError, match="not fully verified"):
        run_smoke(
            manifest_path=manifest_path,
            cache_root=cache,
            confirm_digest=manifest["container"]["base_digest"],
        )
    noncritical.write_bytes(b"current")
    assert (
        inspect_runtime(
            manifest_path=manifest_path,
            cache_root=cache,
            verify_blob_hashes=True,
        )["ready"]
        is True
    )

    layout.metadata.chmod(0o644)
    (layout.rootfs / ".parcel-habitat-oci.json").chmod(0o644)
    tampered = json.loads(layout.metadata.read_text())
    tampered["critical_files"][0]["path"] = "../../host-file"
    tampered["critical_files"][0]["resolved_path"] = "../../host-file"
    tampered_payload = json.dumps(tampered, indent=2, sort_keys=True) + "\n"
    layout.metadata.write_text(tampered_payload, encoding="utf-8")
    (layout.rootfs / ".parcel-habitat-oci.json").write_text(
        tampered_payload,
        encoding="utf-8",
    )
    assert (
        inspect_runtime(
            manifest_path=manifest_path,
            cache_root=cache,
            verify_blob_hashes=True,
        )["ready"]
        is False
    )


def test_prepare_requires_exact_digest_before_network_or_cache_write(tmp_path: Path) -> None:
    manifest, _registry_bytes, _config_bytes, _layers = _fixture_contract()
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, manifest)
    cache = tmp_path / "managed/cache"
    called = False

    def opener(_request: Any, *, timeout: float) -> _Response:
        nonlocal called
        called = True
        raise AssertionError(timeout)

    with pytest.raises(HabitatOciError, match="exactly equal"):
        prepare_runtime(
            manifest_path=manifest_path,
            cache_root=cache,
            confirm_digest=f"sha256:{'0' * 64}",
            opener=opener,
            host_gpu=_gpu(),
            required_free_bytes=0,
        )

    assert called is False
    assert not cache.exists()


def test_inspection_never_uses_network_and_default_is_not_runtime_ready(
    tmp_path: Path,
) -> None:
    manifest, _registry_bytes, _config_bytes, _layers = _fixture_contract()
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, manifest)

    report = inspect_runtime(
        manifest_path=manifest_path,
        cache_root=tmp_path / "managed/cache",
    )

    assert report["ready"] is False
    assert report["claims"]["container_executed"] is False
    assert report["claims"]["navigation_metrics_emitted"] is False


def test_smoke_command_is_read_only_networkless_and_bypasses_image_entrypoint(
    tmp_path: Path,
) -> None:
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    for relative in (
        "proc",
        "dev",
        "tmp",
        "opt/parcel-host-libs",
        "opt/parcel-smoke",
    ):
        (rootfs / relative).mkdir(parents=True)
    glvnd = rootfs / "usr/lib/x86_64-linux-gnu"
    glvnd.mkdir(parents=True)
    (glvnd / "libEGL.so.1.0.0").write_bytes(b"archived-egl")
    (glvnd / "libEGL.so.1").symlink_to("libEGL.so.1.0.0")
    (glvnd / "libGLdispatch.so.0.0.0").write_bytes(b"archived-dispatch")
    (glvnd / "libGLdispatch.so.0").symlink_to("libGLdispatch.so.0.0.0")
    archived_vendor = rootfs / "usr/share/glvnd/egl_vendor.d/10_nvidia.json"
    archived_vendor.parent.mkdir(parents=True)
    archived_vendor.write_text(
        json.dumps({"ICD": {"library_path": "libEGL_nvidia.so.0"}}),
        encoding="utf-8",
    )
    script = tmp_path / "probe.py"
    script.write_text("print('fixture')\n", encoding="utf-8")
    cuda = tmp_path / "libcuda.so.1"
    cuda.write_bytes(b"fixture-cuda")
    nvidia_egl = tmp_path / "libEGL_nvidia.so.0"
    nvidia_egl.write_bytes(b"fixture-egl-vendor")
    bindings = GpuBindings(
        devices=(Path("/dev/nvidia0"),),
        libraries=(("libEGL_nvidia.so.0", nvidia_egl), ("libcuda.so.1", cuda)),
    )

    command = build_smoke_command(rootfs, bindings, smoke_script=script)

    assert command[1:4] == ["--ro-bind", str(rootfs), "/"]
    assert "--unshare-net" in command
    assert "--dev-bind" in command
    assert "/opt/conda/envs/habitat/bin/python" in command
    assert (
        "PATH=/opt/conda/envs/habitat/bin:/opt/conda/bin:/usr/local/cuda/bin:/usr/bin:/bin"
    ) in command
    assert (
        "LD_LIBRARY_PATH=/opt/parcel-host-libs:/opt/conda/envs/habitat/lib:"
        "/usr/lib/x86_64-linux-gnu:/usr/local/cuda/lib64"
    ) in command
    assert "/opt/conda/bin/python" not in command
    assert "/opt/parcel-smoke/probe.py" in command
    assert "/opt/parcel-host-libs/libEGL.so.1" not in command
    assert "/opt/parcel-host-libs/libGLdispatch.so.0" not in command
    assert "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json" in command
    assert "/opt/parcel-host-config/10_nvidia.json" not in command
    assert "bash" not in command
    assert "docker" not in command
    assert all("scene" not in value.lower() for value in command)

    generic_egl = tmp_path / "libEGL.so.1"
    generic_egl.write_bytes(b"incompatible-host-client")
    unsafe = GpuBindings(
        devices=bindings.devices,
        libraries=(*bindings.libraries, ("libEGL.so.1", generic_egl)),
    )
    with pytest.raises(HabitatOciError, match="unsafe host driver binding"):
        build_smoke_command(rootfs, unsafe, smoke_script=script)


def test_driver_allowlist_excludes_generic_host_glvnd_clients() -> None:
    assert _SAFE_DRIVER_LIBRARY.fullmatch("libEGL_nvidia.so.0") is not None
    assert _SAFE_DRIVER_LIBRARY.fullmatch("libcuda.so.1") is not None
    assert _SAFE_DRIVER_LIBRARY.fullmatch("libEGL.so.1") is None
    assert _SAFE_DRIVER_LIBRARY.fullmatch("libGLdispatch.so.0") is None


def test_smoke_result_parser_requires_one_machine_readable_sentinel() -> None:
    payload = {"passed": True, "claims": {"scene_loaded": False}}
    result = _parse_smoke_output(
        "diagnostic\nPARCEL_HABITAT_GPU_SMOKE=" + json.dumps(payload) + "\n"
    )

    assert result == payload
    with pytest.raises(HabitatOciError, match="exactly one"):
        _parse_smoke_output("no result")


def test_layer_extraction_rejects_symbolic_link_outside_rootfs(tmp_path: Path) -> None:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        member = tarfile.TarInfo("opt/escape")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../outside"
        archive.addfile(member)
    compressed = gzip.compress(raw.getvalue(), mtime=0)
    layer = tmp_path / "layer.tar.gz"
    layer.write_bytes(compressed)
    staging = tmp_path / "rootfs"
    staging.mkdir()

    with pytest.raises(HabitatOciError, match="symbolic link escapes"):
        _apply_layer(layer, staging, _digest(raw.getvalue()))

    assert not (tmp_path / "outside").exists()
