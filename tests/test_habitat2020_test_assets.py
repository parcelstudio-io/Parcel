from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Self

import pytest

from evals.external.habitat2020_test_assets import (
    ASSET_MANIFEST_PATH,
    GpuBindings,
    HabitatTestAssetError,
    _parse_scene_output,
    asset_layout,
    build_scene_smoke_command,
    inspect_assets,
    load_asset_manifest,
    prepare_assets,
)


class _Response:
    def __init__(
        self,
        payload: bytes,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._stream = io.BytesIO(payload)
        self._url = url
        self.headers = headers or {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self._stream.read(limit)

    def geturl(self) -> str:
        return self._url


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fixture_contract(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    manifest = copy.deepcopy(load_asset_manifest())
    utility = b"frozen utility source\n"
    documentation = b"frozen documentation\n"
    scene_readme = b"---\nlicense: cc-by-nc-4.0\n---\n"
    scene_glb = b"fixture glb"
    scene_navmesh = b"fixture navmesh"
    episodes = [
        {
            "episode_id": str(index),
            "scene_id": ("data/scene_datasets/habitat-test-scenes/skokloster-castle.glb"),
            "start_position": [0.0, 0.1, float(index)],
            "start_rotation": [0.0, 0.0, 0.0, 1.0],
            "goals": [{"position": [10.0, 0.1, 10.0]}],
        }
        for index in range(100)
    ]
    val = gzip.compress(json.dumps({"episodes": episodes}).encode(), mtime=0)
    train = gzip.compress(b'{"episodes": []}', mtime=0)
    test = gzip.compress(b'{"episodes": []}', mtime=0)
    members = {
        "v1/test/test.json.gz": test,
        "v1/train/train.json.gz": train,
        "v1/val/val.json.gz": val,
    }
    archive_stream = io.BytesIO()
    with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    pointnav_archive = archive_stream.getvalue()
    sources = {
        "https://raw.githubusercontent.com/facebookresearch/habitat-sim/fixture/utility.py": utility,
        "https://raw.githubusercontent.com/facebookresearch/habitat-sim/fixture/DATASETS.md": documentation,
        "https://huggingface.co/fixture/README.md": scene_readme,
        "https://huggingface.co/fixture/scene.glb": scene_glb,
        "https://huggingface.co/fixture/scene.navmesh": scene_navmesh,
        "https://dl.fbaipublicfiles.com/habitat/fixture-pointnav.zip": pointnav_archive,
    }
    utility_contract = manifest["official_data_utility"]
    utility_contract.update(
        {
            "url": next(iter(sources)),
            "size_bytes": len(utility),
            "sha256": _sha(utility),
        }
    )
    documentation_contract = manifest["official_documentation"]
    documentation_contract.update(
        {
            "url": list(sources)[1],
            "size_bytes": len(documentation),
            "sha256": _sha(documentation),
        }
    )
    for item, url, payload in zip(
        manifest["scene_asset"]["files"],
        list(sources)[2:5],
        (scene_readme, scene_glb, scene_navmesh),
        strict=True,
    ):
        item.update({"url": url, "size_bytes": len(payload), "sha256": _sha(payload)})
    pointnav = manifest["pointnav_asset"]
    pointnav.update(
        {
            "download_url": list(sources)[5],
            "package_name": "fixture-pointnav.zip",
            "size_bytes": len(pointnav_archive),
            "sha256": _sha(pointnav_archive),
            "etag": "fixture-etag",
            "s3_version_id": "fixture-version",
        }
    )
    for item in pointnav["members"]:
        payload = members[item["archive_path"]]
        item.update({"size_bytes": len(payload), "sha256": _sha(payload)})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, sources


def test_frozen_manifest_distinguishes_non_gated_assets_from_habitat_2020() -> None:
    manifest = load_asset_manifest(ASSET_MANIFEST_PATH)

    assert manifest["official_data_utility"]["requires_auth_for_these_uids"] is False
    assert manifest["scene_asset"]["gated"] is False
    assert manifest["scene_asset"]["license"] == "cc-by-nc-4.0"
    assert manifest["pointnav_asset"]["credential_required"] is False
    assert manifest["eligibility"]["habitat_2020_protocol"] is False
    assert manifest["eligibility"]["navigation_metrics_allowed"] is False
    assert manifest["pointnav_asset"]["expected_smoke_scene_id"].endswith("skokloster-castle.glb")


def test_prepare_is_hash_bound_offline_and_refuses_tampered_cache(tmp_path: Path) -> None:
    manifest_path, sources = _fixture_contract(tmp_path)
    cache_root = tmp_path / "managed/cache/assets"
    calls: list[str] = []

    def opener(request: Any, *, timeout: float) -> _Response:
        assert timeout == 3.0
        calls.append(request.full_url)
        headers = (
            {"ETag": '"fixture-etag"', "x-amz-version-id": "fixture-version"}
            if request.full_url.endswith("fixture-pointnav.zip")
            else {}
        )
        return _Response(sources[request.full_url], request.full_url, headers)

    status = prepare_assets(
        manifest_path=manifest_path,
        cache_root=cache_root,
        confirm_bundle_id="habitat-test-assets-compat-v1",
        timeout_s=3.0,
        opener=opener,
    )

    assert status["ready"] is True
    assert status["smoke_episode"] == {
        "episode_count": 100,
        "episode_id": "0",
        "goal_read_or_used": False,
        "scene_id": "data/scene_datasets/habitat-test-scenes/skokloster-castle.glb",
        "split": "val",
        "start_transform_present": True,
    }
    assert len(calls) == 6
    assert status["access"]["credential_required"] is False

    layout = asset_layout(manifest_path, cache_root)
    scene = layout.data_root / "scene_datasets/habitat-test-scenes/skokloster-castle.glb"
    scene.chmod(0o644)
    scene.write_bytes(b"tampered")
    assert inspect_assets(manifest_path=manifest_path, cache_root=cache_root)["ready"] is False
    with pytest.raises(HabitatTestAssetError, match="refusing to replace"):
        prepare_assets(
            manifest_path=manifest_path,
            cache_root=cache_root,
            confirm_bundle_id="habitat-test-assets-compat-v1",
            opener=opener,
        )


def test_prepare_requires_exact_confirmation_before_network_or_cache_write(
    tmp_path: Path,
) -> None:
    manifest_path, _sources = _fixture_contract(tmp_path)
    cache_root = tmp_path / "managed/cache/assets"
    called = False

    def opener(_request: Any, *, timeout: float) -> _Response:
        nonlocal called
        called = True
        raise AssertionError(timeout)

    with pytest.raises(HabitatTestAssetError, match="exactly equal"):
        prepare_assets(
            manifest_path=manifest_path,
            cache_root=cache_root,
            confirm_bundle_id="wrong-bundle",
            opener=opener,
        )

    assert called is False
    assert not cache_root.exists()


def test_scene_command_mounts_assets_read_only_and_disables_network(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    for relative in ("proc", "dev", "tmp", "opt/parcel-host-libs", "opt/parcel-smoke"):
        (rootfs / relative).mkdir(parents=True)
    glvnd = rootfs / "usr/lib/x86_64-linux-gnu"
    glvnd.mkdir(parents=True)
    (glvnd / "libEGL.so.1.0.0").write_bytes(b"archived-egl")
    (glvnd / "libEGL.so.1").symlink_to("libEGL.so.1.0.0")
    (glvnd / "libGLdispatch.so.0.0.0").write_bytes(b"archived-dispatch")
    (glvnd / "libGLdispatch.so.0").symlink_to("libGLdispatch.so.0.0.0")
    vendor = rootfs / "usr/share/glvnd/egl_vendor.d/10_nvidia.json"
    vendor.parent.mkdir(parents=True)
    vendor.write_text(json.dumps({"ICD": {"library_path": "libEGL_nvidia.so.0"}}))
    data_root = tmp_path / "assets/data"
    data_root.mkdir(parents=True)
    script = tmp_path / "scene_probe.py"
    script.write_text("print('fixture')\n")
    cuda = tmp_path / "libcuda.so.1"
    cuda.write_bytes(b"cuda")
    egl = tmp_path / "libEGL_nvidia.so.0"
    egl.write_bytes(b"egl")
    bindings = GpuBindings(
        devices=(Path("/dev/nvidia0"),),
        libraries=(("libEGL_nvidia.so.0", egl), ("libcuda.so.1", cuda)),
    )

    command = build_scene_smoke_command(
        rootfs,
        data_root,
        bindings,
        smoke_script=script,
    )

    assert "--unshare-net" in command
    assert ["--ro-bind", str(data_root), "/opt/parcel-smoke/data"] == command[
        command.index(str(data_root)) - 1 : command.index(str(data_root)) + 2
    ]
    assert command[-2:] == ["/opt/conda/envs/habitat/bin/python", "/opt/parcel-smoke/probe.py"]
    assert "habitat-lab" not in " ".join(command).lower()
    assert "evaluator" not in " ".join(command).lower()


def test_scene_result_parser_requires_exactly_one_sentinel() -> None:
    payload = {"passed": True, "claims": {"navigation_metrics_emitted": False}}

    assert (
        _parse_scene_output("log\nPARCEL_HABITAT_SCENE_SMOKE=" + json.dumps(payload) + "\n")
        == payload
    )
    with pytest.raises(HabitatTestAssetError, match="exactly one"):
        _parse_scene_output("no result")


def test_immutable_scene_baseline_preserves_non_evaluation_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    report_path = (
        root / "evals/external/results/habitat2020/"
        "habitat-test-assets-gpu-scene-smoke-20260803-baseline01.json"
    )
    ledger_path = (
        root / "evals/external/results/ledger/runs/"
        "habitat-test-assets-gpu-scene-smoke-20260803T152317Z.json"
    )
    report_payload = report_path.read_bytes()
    report = json.loads(report_payload)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

    assert (
        _sha(report_payload) == "aed6afcb2e9af98f4f6ed8c3a3f636845e70a34b14057b1904493f8530330137"
    )
    assert report["result"]["passed"] is True
    assert report["result"]["probe"]["rendering"]["frame_count"] == 4
    assert report["result"]["probe"]["actions"]["collisions"] == [False, False, False]
    assert report["claims"]["gpu_render_executed"] is True
    assert report["claims"]["parcel_policy_executed"] is False
    assert report["evaluation"]["habitat_2020_protocol"] is False
    assert report["evaluation"]["navigation_metrics_emitted"] is False
    assert report["evaluation"]["official_rank_eligible"] is False
    assert ledger["report"]["sha256"] == _sha(report_payload)
    assert ledger["aggregate_metrics"]["top_decile_evidence"] is False
