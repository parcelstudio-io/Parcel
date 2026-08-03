from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest


def _load_fetcher() -> object:
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts/fetch_reasoner_cuda_oci.py"
    spec = importlib.util.spec_from_file_location("parcel_reasoner_cuda_oci", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetcher = _load_fetcher()


def _layer(path: Path, members: list[tarfile.TarInfo], payloads: list[bytes]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for member, payload in zip(members, payloads, strict=True):
            archive.addfile(member, io.BytesIO(payload) if member.isfile() else None)


def test_default_oci_profile_pins_build_platform_and_all_layers() -> None:
    profile, distribution = fetcher._load_profile(fetcher.DEFAULT_PROFILE)
    _cache, _blobs, rootfs = fetcher._managed_paths(distribution)

    assert profile["source"] == {
        "repository": "https://github.com/ggml-org/llama.cpp.git",
        "commit": "1464c62d88f699ec9700c8010bbfdbc603a9efd6",
        "release_build": 10236,
        "build_documentation": (
            "https://github.com/ggml-org/llama.cpp/blob/"
            "1464c62d88f699ec9700c8010bbfdbc603a9efd6/docs/build.md"
        ),
    }
    assert distribution["tag"] == "server-cuda12-b10236"
    assert distribution["platform"] == {"architecture": "amd64", "os": "linux"}
    assert len(distribution["layers"]) == 13
    assert sum(item["size"] for item in distribution["layers"]) == 2_586_079_909
    assert len(distribution["critical_files"]) == 7
    assert distribution["critical_files"][0] == {
        "path": "app/llama-server",
        "size": 17_912,
        "sha256": "e3c775bb274d01d5c3345f37aaea55470902187b4433d2689eab367fa4150f3c",
    }
    assert rootfs.is_relative_to(
        (Path(__file__).resolve().parents[1] / "third_party/llama.cpp-oci").resolve()
    )


def test_layer_extraction_rebases_container_absolute_symlink(tmp_path: Path) -> None:
    layer = tmp_path / "layer.tar.gz"
    directory = tarfile.TarInfo("usr/bin")
    directory.type = tarfile.DIRTYPE
    directory.mode = 0o755
    executable = tarfile.TarInfo("usr/bin/mawk")
    executable.size = 4
    executable.mode = 0o755
    alternatives = tarfile.TarInfo("etc/alternatives")
    alternatives.type = tarfile.DIRTYPE
    alternatives.mode = 0o755
    link = tarfile.TarInfo("etc/alternatives/awk")
    link.type = tarfile.SYMTYPE
    link.linkname = "/usr/bin/mawk"
    _layer(layer, [directory, executable, alternatives, link], [b"", b"mawk", b"", b""])

    staging = tmp_path / "rootfs"
    staging.mkdir()
    fetcher._apply_layer(layer, staging)

    staged_link = staging / "etc/alternatives/awk"
    assert staged_link.is_symlink()
    assert not Path(staged_link.readlink()).is_absolute()
    assert staged_link.resolve() == staging / "usr/bin/mawk"
    assert staged_link.read_bytes() == b"mawk"


def test_layer_extraction_rejects_parent_traversal(tmp_path: Path) -> None:
    layer = tmp_path / "escape.tar.gz"
    escaping = tarfile.TarInfo("../../escape")
    escaping.size = 3
    _layer(layer, [escaping], [b"bad"])
    staging = tmp_path / "rootfs"
    staging.mkdir()

    with pytest.raises(fetcher.OciStageError, match="unsafe OCI layer member"):
        fetcher._apply_layer(layer, staging)

    assert not (tmp_path.parent / "escape").exists()


def test_critical_file_status_requires_exact_size_and_hash(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    critical = rootfs / "app/llama-server"
    critical.parent.mkdir(parents=True)
    critical.write_bytes(b"trusted")
    descriptor = {
        "path": "app/llama-server",
        "size": 7,
        "sha256": "a9a089195c68d2adeee23beaa2c3a93b1d4cdf09046e7a9e520b3b166dff3e6a",
    }

    status = fetcher._critical_file_status(rootfs, descriptor)

    assert status["ready"] is True
    critical.write_bytes(b"tampered")
    assert fetcher._critical_file_status(rootfs, descriptor)["ready"] is False
