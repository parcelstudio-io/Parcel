from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

import evals.external.barn_runtime_package as runtime


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest(package: bytes, critical: dict[str, bytes] | None = None) -> dict[str, object]:
    files = critical or {
        "usr/bin/singularity": b"binary",
        "usr/lib/x86_64-linux-gnu/singularity/bin/starter": b"starter",
        "etc/singularity/singularity.conf": b"config",
    }
    return {
        "container": {
            "installer_url": "https://example.test/singularity.deb",
            "installer_sha256": _sha256(package),
            "installer_size_bytes": len(package),
            "installer_package_version": "4.3.0-noble",
            "installer_architecture": "amd64",
            "tested_version": "4.3.0",
            "extracted_critical_files_sha256": {
                path: _sha256(payload) for path, payload in files.items()
            },
        }
    }


def _valid_deb_fields(path: Path) -> dict[str, object]:
    del path
    return {
        "available": True,
        "fields": {
            "package": "singularity-ce",
            "version": "4.3.0-noble",
            "architecture": "amd64",
        },
        "error": None,
    }


def test_inspect_package_checks_hash_size_and_debian_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"trusted-deb"
    package = tmp_path / "runtime.deb"
    package.write_bytes(payload)
    manifest = _manifest(payload)
    monkeypatch.setattr(runtime, "_deb_fields", _valid_deb_fields)

    verified = runtime.inspect_runtime_package(package, manifest)
    package.write_bytes(b"tampered")
    tampered = runtime.inspect_runtime_package(package, manifest)

    assert verified["verified"] is True
    assert verified["sha256"] == _sha256(payload)
    assert tampered["verified"] is False
    assert {"size mismatch", "sha256 mismatch"}.issubset(tampered["errors"])


def test_inspect_extracted_runtime_requires_all_pinned_files_and_never_claims_exec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = b"trusted-deb"
    critical = {
        "usr/bin/singularity": b"binary",
        "usr/lib/x86_64-linux-gnu/singularity/bin/starter": b"starter",
        "etc/singularity/singularity.conf": b"config",
    }
    manifest = _manifest(package, critical)
    rootfs = tmp_path / "rootfs"
    for relative, payload in critical.items():
        path = rootfs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    monkeypatch.setattr(
        runtime,
        "_probe_extracted_version",
        lambda binary, config: {
            "attempted": True,
            "detected": True,
            "output": "4.3.0-noble",
            "error": None,
        },
    )

    status = runtime.inspect_runtime_rootfs(rootfs, manifest)
    (rootfs / "usr/bin/singularity").write_bytes(b"tampered")
    tampered = runtime.inspect_runtime_rootfs(rootfs, manifest, probe_version=False)

    assert status["verified"] is True
    assert status["runtime_exec_ready"] is False
    assert tampered["verified"] is False
    assert "critical file hash mismatch: usr/bin/singularity" in tampered["errors"]


def test_fetch_is_atomic_verified_and_refuses_to_replace_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"trusted-deb"
    manifest = _manifest(payload)
    target = tmp_path / "runtime.deb"
    monkeypatch.setattr(runtime, "_deb_fields", _valid_deb_fields)
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(payload))

    status = runtime.fetch_runtime_package(target, manifest)
    target.write_bytes(b"unverified-existing-file")

    assert status["verified"] is True
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        runtime.fetch_runtime_package(target, manifest)


def test_extract_runs_dpkg_extract_only_and_refuses_existing_unverified_rootfs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"trusted-deb"
    critical = {
        "usr/bin/singularity": b"binary",
        "usr/lib/x86_64-linux-gnu/singularity/bin/starter": b"starter",
        "etc/singularity/singularity.conf": b"config",
    }
    manifest = _manifest(payload, critical)
    package = tmp_path / "runtime.deb"
    package.write_bytes(payload)
    destination = tmp_path / "runtime-rootfs"
    monkeypatch.setattr(runtime, "_deb_fields", _valid_deb_fields)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        runtime,
        "_probe_extracted_version",
        lambda binary, config: {
            "attempted": True,
            "detected": True,
            "output": "4.3.0-noble",
            "error": None,
        },
    )

    calls: list[list[str]] = []

    def fake_run(arguments: list[str], **kwargs: object) -> object:
        del kwargs
        calls.append(arguments)
        staging = Path(arguments[-1])
        for relative, contents in critical.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    status = runtime.extract_runtime_package(package, destination, manifest)

    assert status["verified"] is True
    assert calls == [["/usr/bin/dpkg-deb", "--extract", str(package), calls[0][-1]]]
    assert (destination / "usr/bin/singularity").read_bytes() == b"binary"

    bad_destination = tmp_path / "bad-rootfs"
    bad_destination.mkdir()
    with pytest.raises(FileExistsError, match="refusing to replace"):
        runtime.extract_runtime_package(package, bad_destination, manifest)
