from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import parcel_robot.reasoner_gpu as doctor

PINNED_COMMIT = "221f0f6356efe2260023208365705ec5d5a7c8f5"
OCI_COMMIT = "1464c62d88f699ec9700c8010bbfdbc603a9efd6"


def _profile(root: Path, *, with_backend: bool) -> Path:
    model = root / "model.gguf"
    model.write_bytes(b"GGUFtest-model")
    binary = root / "bin/llama-server"
    binary.parent.mkdir(parents=True)
    binary.write_text("test", encoding="utf-8")
    binary.chmod(0o755)
    if with_backend:
        (binary.parent / "libggml-cuda.so").write_text("test", encoding="utf-8")
    source = root / "source"
    (source / ".git").mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "profile_id": "test-cuda",
        "source": {
            "repository": "https://github.com/ggml-org/llama.cpp.git",
            "commit": PINNED_COMMIT,
            "release_build": 10235,
            "build_documentation": "https://example.invalid/build",
        },
        "build": {
            "source_dir": str(source),
            "build_dir": str(root / "build"),
            "generator": "Ninja",
            "required_tools": {
                "git": ["git"],
                "cmake": ["cmake"],
                "ninja": ["ninja"],
                "cuda_compiler": ["nvcc"],
                "c_compiler": ["cc"],
                "cxx_compiler": ["c++"],
            },
            "cmake_defines": {
                "GGML_CUDA": "ON",
                "CMAKE_CUDA_ARCHITECTURES": "89",
            },
            "target": "llama-server",
        },
        "runtime": {
            "current_binary": str(binary),
            "cuda_binary": str(binary),
            "model": {
                "path": str(model),
                "size_bytes": model.stat().st_size,
                "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
            },
            "requested_gpu_layers": 999,
        },
        "admission": {
            "target_compute_capability": "8.9",
            "minimum_total_vram_mib": 24576,
            "minimum_free_vram_mib": 18432,
            "minimum_runtime_reserve_over_weight_file_mib": 4096,
        },
    }
    path = root / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _command_result(output: str, *, returncode: int = 0) -> dict[str, object]:
    return {
        "detected": True,
        "path": "/fake/tool",
        "returncode": returncode,
        "output": output,
        "error": None if returncode == 0 else f"exit {returncode}",
    }


def test_default_profile_pins_build_and_never_replaces_cpu_binary() -> None:
    profile = doctor.load_reasoner_gpu_profile()

    assert profile["source"]["commit"] == OCI_COMMIT
    assert profile["source"]["release_build"] == 10236
    assert profile["distribution"]["tag"] == "server-cuda12-b10236"
    assert profile["build"]["cmake_defines"]["GGML_CUDA"] == "ON"
    assert profile["build"]["cmake_defines"]["CMAKE_CUDA_ARCHITECTURES"] == "89"
    assert profile["runtime"]["requested_gpu_layers"] == 999
    assert profile["runtime"]["current_binary"] != profile["runtime"]["cuda_binary"]


def test_model_overlay_inherits_exact_oci_runtime_without_copying_distribution() -> None:
    root = Path(__file__).resolve().parents[1]
    overlay = root / "configs/reasoner/llama_cpp_cuda12_oci_b10236_ministral8b_instruct.json"

    profile = doctor.load_reasoner_gpu_profile(overlay)

    assert profile["extends"] == "llama_cpp_cuda12_oci_b10236.json"
    assert profile["source"]["commit"] == OCI_COMMIT
    assert profile["distribution"]["index_digest"] == (
        "sha256:fd68d13013141833e8214ecad6e1fbefb532db6a00b980cdecfe33603dbf2675"
    )
    assert profile["runtime"]["model"] == {
        "path": (
            "models/reasoner/ministral-3-8b-instruct-2512/Ministral-3-8B-Instruct-2512-Q4_K_M.gguf"
        ),
        "size_bytes": 5_198_911_904,
        "sha256": "33e7a72cf5e6e2cfc2f2847075acc013d68bba023e35310cef86b5cf8fdca761",
    }
    assert profile["admission"]["minimum_free_vram_mib"] == 9216


def test_reasoning_model_overlay_inherits_runtime_and_pins_exact_artifact() -> None:
    root = Path(__file__).resolve().parents[1]
    overlay = root / "configs/reasoner/llama_cpp_cuda12_oci_b10236_ministral8b_reasoning.json"

    profile = doctor.load_reasoner_gpu_profile(overlay)

    assert profile["extends"] == "llama_cpp_cuda12_oci_b10236.json"
    assert profile["source"]["commit"] == OCI_COMMIT
    assert profile["runtime"]["model"] == {
        "path": (
            "models/reasoner/ministral-3-8b-reasoning-2512/"
            "Ministral-3-8B-Reasoning-2512-Q4_K_M.gguf"
        ),
        "size_bytes": 5_198_910_368,
        "sha256": "894aa3645ef8708a81dbe201c26105ce37c4c741252c89c5a78f81b49ac438c6",
    }
    assert profile["admission"]["minimum_free_vram_mib"] == 9216


def test_profile_overlay_rejects_escape_and_cycles(tmp_path: Path) -> None:
    escape = tmp_path / "escape.json"
    escape.write_text(
        json.dumps({"schema_version": 1, "extends": "../outside.json"}),
        encoding="utf-8",
    )
    with pytest.raises(doctor.ReasonerGpuProfileError, match="sibling"):
        doctor.load_reasoner_gpu_profile(escape)

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps({"extends": "second.json"}), encoding="utf-8")
    second.write_text(json.dumps({"extends": "first.json"}), encoding="utf-8")
    with pytest.raises(doctor.ReasonerGpuProfileError, match="cycle"):
        doctor.load_reasoner_gpu_profile(first)


def test_oci_status_requires_marker_selected_entrypoint_and_critical_hashes(
    tmp_path: Path,
) -> None:
    rootfs = tmp_path / "third_party/llama.cpp-oci/test/rootfs"
    binary = rootfs / "app/llama-server"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"trusted-binary")
    binary.chmod(0o755)
    binary_digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    distribution = {
        "rootfs_dir": "third_party/llama.cpp-oci/test/rootfs",
        "entrypoint": "app/llama-server",
        "index_digest": f"sha256:{'1' * 64}",
        "manifest_digest": f"sha256:{'2' * 64}",
        "config": {"digest": f"sha256:{'3' * 64}"},
        "layers": [{"digest": f"sha256:{'4' * 64}"}],
        "critical_files": [
            {
                "path": "app/llama-server",
                "size": binary.stat().st_size,
                "sha256": binary_digest,
            }
        ],
    }
    marker = {
        "schema_version": 1,
        "index_digest": distribution["index_digest"],
        "manifest_digest": distribution["manifest_digest"],
        "config_digest": distribution["config"]["digest"],
        "layer_digests": [distribution["layers"][0]["digest"]],
        "entrypoint": distribution["entrypoint"],
        "entrypoint_sha256": binary_digest,
    }
    (rootfs / ".parcel-oci-provenance.json").write_text(json.dumps(marker), encoding="utf-8")

    status = doctor._oci_distribution_status(tmp_path, distribution, binary)

    assert status["ready"] is True
    assert status["verified_critical_file_count"] == 1
    assert (
        doctor._oci_distribution_status(tmp_path, distribution, tmp_path / "another-server")[
            "ready"
        ]
        is False
    )
    binary.write_bytes(b"tampered-binary")
    assert doctor._oci_distribution_status(tmp_path, distribution, binary)["ready"] is False


def test_committed_failed_audit_cannot_claim_a_gpu_planner_run() -> None:
    root = Path(__file__).resolve().parents[1]
    artifact = json.loads(
        (
            root
            / "evals/companion/gpu_readiness/results/gpu-readiness-20260803-b10235-current.json"
        ).read_text(encoding="utf-8")
    )
    profile = doctor.load_reasoner_gpu_profile(
        root / "configs/reasoner/llama_cpp_cuda_b10235_sm89.json"
    )

    assert artifact["profile"]["source_commit"] == profile["source"]["commit"]
    assert artifact["model"]["sha256"] == profile["runtime"]["model"]["sha256"]
    assert artifact["classification"]["nvidia_driver_ready"] is True
    assert artifact["classification"]["binary_cuda_ready"] is False
    assert artifact["classification"]["gpu_planner_run_authorized"] is False
    assert artifact["claims"]["planner_run_performed"] is False
    assert artifact["claims"]["ttft_ms"] is None
    assert artifact["claims"]["token_counts"] is None


def test_parsers_reject_none_device_and_malformed_gpu_rows() -> None:
    assert doctor.parse_llama_devices("Available devices:\n  (none)\nCUDA init log") == []
    assert doctor.parse_llama_devices(
        "initialization log\nAvailable devices:\n  CUDA0: NVIDIA RTX 5000 Ada\n"
    ) == ["CUDA0: NVIDIA RTX 5000 Ada"]
    rows = doctor.parse_nvidia_smi_csv(
        "NVIDIA RTX 5000 Ada Generation, GPU-1, 595.84, 8.9, 32760, 1143, 31086\nnot,a,valid,row\n"
    )
    assert rows == [
        {
            "name": "NVIDIA RTX 5000 Ada Generation",
            "uuid": "GPU-1",
            "driver_version": "595.84",
            "compute_capability": "8.9",
            "memory_total_mib": 32760,
            "memory_used_mib": 1143,
            "memory_free_mib": 31086,
        }
    ]


def test_cuda_ready_requires_driver_backend_device_version_model_and_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_path = _profile(tmp_path, with_backend=True)

    def fake_command(
        executable: str | Path,
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> dict[str, object]:
        if str(executable).endswith("llama-server") and arguments == ("--version",):
            return _command_result("version: 10235 (221f0f635)")
        if str(executable).endswith("llama-server") and arguments == ("--list-devices",):
            return _command_result("Available devices:\n  CUDA0: NVIDIA RTX 5000 Ada")
        if executable == "nvidia-smi":
            return _command_result(
                "NVIDIA RTX 5000 Ada Generation, GPU-1, 595.84, 8.9, 32760, 1000, 31760"
            )
        if executable == "git":
            return _command_result(PINNED_COMMIT)
        if executable == "ldd":
            return _command_result("libggml-cuda.so => /fake/libggml-cuda.so")
        raise AssertionError((executable, arguments))

    monkeypatch.setattr(doctor, "_command_status", fake_command)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/fake/{name}")
    report = doctor.audit_reasoner_gpu_readiness(
        profile_path=profile_path,
        repo_root=tmp_path,
        recorded_at_utc="2026-08-03T00:00:00Z",
    )

    assert report["classification"] == {
        "nvidia_driver_ready": True,
        "binary_cuda_ready": True,
        "model_ready": True,
        "memory_admission_ready": True,
        "ready_for_gpu_inference": True,
        "ready_to_build_pinned_cuda_binary": True,
        "gpu_planner_run_authorized": True,
    }
    assert report["blockers"] == []
    assert report["claims"]["model_loaded"] is False
    assert report["claims"]["planner_run_performed"] is False


def test_healthy_gpu_does_not_make_cpu_only_server_cuda_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_path = _profile(tmp_path, with_backend=False)

    def fake_command(
        executable: str | Path,
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> dict[str, object]:
        if str(executable).endswith("llama-server") and arguments == ("--version",):
            return _command_result("version: 10235 (221f0f635)")
        if str(executable).endswith("llama-server") and arguments == ("--list-devices",):
            return _command_result("Available devices:\n  (none)")
        if executable == "nvidia-smi":
            return _command_result(
                "NVIDIA RTX 5000 Ada Generation, GPU-1, 595.84, 8.9, 32760, 1143, 31086"
            )
        if executable == "git":
            return _command_result(PINNED_COMMIT)
        if executable == "ldd":
            return _command_result("libc.so.6 => /lib/libc.so.6")
        raise AssertionError((executable, arguments))

    monkeypatch.setattr(doctor, "_command_status", fake_command)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None if name != "git" else "/git")
    report = doctor.audit_reasoner_gpu_readiness(
        profile_path=profile_path,
        repo_root=tmp_path,
        recorded_at_utc="2026-08-03T00:00:00Z",
    )

    assert report["classification"]["nvidia_driver_ready"] is True
    assert report["classification"]["memory_admission_ready"] is True
    assert report["classification"]["binary_cuda_ready"] is False
    assert report["classification"]["ready_for_gpu_inference"] is False
    assert report["classification"]["ready_to_build_pinned_cuda_binary"] is False
    blocker_ids = {item["id"] for item in report["blockers"]}
    assert "llama_cpp_reports_no_cuda_device" in blocker_ids
    assert "llama_cpp_cuda_backend_missing" in blocker_ids
    assert "build_tool_cuda_compiler_missing" in blocker_ids
    assert "build_tool_cmake_missing" in blocker_ids


def test_skipping_model_hash_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_path = _profile(tmp_path, with_backend=True)

    def fake_command(
        executable: str | Path,
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> dict[str, object]:
        if str(executable).endswith("llama-server") and arguments == ("--version",):
            return _command_result("version: 10235 (221f0f635)")
        if str(executable).endswith("llama-server") and arguments == ("--list-devices",):
            return _command_result("Available devices:\n  CUDA0: test")
        if executable == "nvidia-smi":
            return _command_result("GPU, UUID, 595.84, 8.9, 32760, 0, 32760")
        if executable == "git":
            return _command_result(PINNED_COMMIT)
        if executable == "ldd":
            return _command_result("libggml-cuda.so")
        raise AssertionError((executable, arguments))

    monkeypatch.setattr(doctor, "_command_status", fake_command)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/fake/{name}")
    report = doctor.audit_reasoner_gpu_readiness(
        profile_path=profile_path,
        repo_root=tmp_path,
        verify_model_hash=False,
    )

    assert report["model"]["hash_verified"] is False
    assert report["classification"]["model_ready"] is False
    assert report["classification"]["gpu_planner_run_authorized"] is False
    assert {item["id"] for item in report["blockers"]} == {"gemma_artifact_not_verified"}


def test_readiness_result_writer_refuses_to_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "results/audit.json"

    assert doctor.write_audit_report({"ready": True}, output) == output
    assert json.loads(output.read_text(encoding="utf-8")) == {"ready": True}
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        doctor.write_audit_report({"ready": False}, output)
