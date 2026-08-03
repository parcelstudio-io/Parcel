from __future__ import annotations

import pytest

import evals.external.device_capabilities as devices


def _fake_audit(*, gpu: bool, torch: bool) -> dict[str, object]:
    return {
        "host": {
            "gpu": {"detected": gpu, "gpus": [], "error": None},
            "packages": {"torch": torch},
            "frameworks": {
                "torch": {
                    "installed": torch,
                    "cuda_available": gpu and torch,
                }
            },
        }
    }


def test_parse_nvidia_smi_row_preserves_audit_fields() -> None:
    parsed = devices.parse_nvidia_smi_row("NVIDIA RTX 5000 Ada Generation, 32760, 595.84, 8.9")

    assert parsed == {
        "name": "NVIDIA RTX 5000 Ada Generation",
        "memory_total_mib": 32760,
        "driver_version": "595.84",
        "compute_capability": "8.9",
    }


def test_device_matrix_does_not_mislabel_cpu_barn_as_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        devices,
        "_probe_nvidia",
        lambda: {
            "detected": True,
            "gpus": [
                {
                    "name": "test-gpu",
                    "memory_total_mib": 32760,
                    "driver_version": "test",
                    "compute_capability": "8.9",
                }
            ],
            "error": None,
        },
    )
    monkeypatch.setattr(
        devices,
        "_probe_packages",
        lambda: {
            "numpy": True,
            "torch": False,
            "cupy": False,
            "jax": False,
            "habitat_sim": False,
            "isaacsim": False,
        },
    )
    monkeypatch.setattr(
        devices,
        "_probe_torch_cuda",
        lambda installed: {
            "installed": installed,
            "cuda_available": False,
            "version": None,
            "cuda_build": None,
            "error": "not installed",
        },
    )

    report = devices.audit_evaluation_devices()
    matrix = {entry["id"]: entry for entry in report["evaluators"]}

    assert report["policy"]["no_silent_device_fallback"] is True
    assert matrix["barn_native_public50"]["declared_device"] == "cpu"
    assert matrix["barn_native_public50"]["gpu_execution_supported"] is False
    assert matrix["barn_native_public50"]["evaluator_ready"] is True
    assert matrix["habitat2020_public_contract_smoke"]["declared_device"] == "cpu"
    assert matrix["habitat2020_public_contract_smoke"]["evaluator_ready"] is True
    assert matrix["habitat2020_official"]["device_ready"] is True
    assert matrix["habitat2020_official"]["evaluator_ready"] is False
    assert matrix["citywalker_cuda_policy"]["device_ready"] is False
    assert matrix["citywalker_cuda_policy"]["evaluator_ready"] is False


def test_cuda_requirement_fails_closed_without_gpu_or_framework() -> None:
    with pytest.raises(RuntimeError, match="no NVIDIA GPU"):
        devices.require_declared_device("cuda", _fake_audit(gpu=False, torch=False))
    with pytest.raises(RuntimeError, match="required framework"):
        devices.require_declared_device(
            "cuda",
            _fake_audit(gpu=True, torch=False),
            framework="torch",
        )

    cpu_only_torch = _fake_audit(gpu=True, torch=True)
    cpu_only_torch["host"]["frameworks"]["torch"]["cuda_available"] = False
    with pytest.raises(RuntimeError, match="Torch build cannot access CUDA"):
        devices.require_declared_device(
            "cuda",
            cpu_only_torch,
            framework="torch",
        )

    assert (
        devices.require_declared_device(
            "cuda",
            _fake_audit(gpu=True, torch=True),
            framework="torch",
        )
        == "cuda"
    )
    assert devices.require_declared_device("cpu", _fake_audit(gpu=False, torch=False)) == "cpu"
