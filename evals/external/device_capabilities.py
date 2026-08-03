"""Read-only execution-device audit for external evaluators and model policies."""

from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

NVIDIA_SMI_QUERY = (
    "--query-gpu=name,memory.total,driver_version,compute_cap",
    "--format=csv,noheader,nounits",
)
PROBED_PACKAGES = ("numpy", "torch", "cupy", "jax", "habitat_sim", "isaacsim")


def parse_nvidia_smi_row(row: str) -> dict[str, Any]:
    """Parse one row from the fixed NVIDIA query used by this audit."""

    values = [value.strip() for value in row.strip().split(",")]
    if len(values) != 4 or not values[0]:
        raise ValueError("unexpected nvidia-smi query output")
    try:
        memory_mib = int(values[1])
    except ValueError as exc:
        raise ValueError("nvidia-smi memory.total must be an integer MiB value") from exc
    return {
        "name": values[0],
        "memory_total_mib": memory_mib,
        "driver_version": values[2],
        "compute_capability": values[3],
    }


def _probe_nvidia() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {"detected": False, "gpus": [], "error": "nvidia-smi not found"}
    try:
        completed = subprocess.run(
            [executable, *NVIDIA_SMI_QUERY],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"detected": False, "gpus": [], "error": str(exc)}
    if completed.returncode != 0:
        error = completed.stderr.strip() or f"nvidia-smi exited {completed.returncode}"
        return {"detected": False, "gpus": [], "error": error}
    try:
        gpus = [parse_nvidia_smi_row(row) for row in completed.stdout.splitlines() if row.strip()]
    except ValueError as exc:
        return {"detected": False, "gpus": [], "error": str(exc)}
    return {"detected": bool(gpus), "gpus": gpus, "error": None}


def _probe_packages() -> dict[str, bool]:
    return {name: importlib.util.find_spec(name) is not None for name in PROBED_PACKAGES}


def _probe_torch_cuda(installed: bool) -> dict[str, Any]:
    """Verify the installed Torch build in an isolated process.

    Package presence alone is insufficient: a CPU-only Torch wheel must never
    satisfy a CUDA declaration.  The subprocess keeps framework import and any
    CUDA initialization outside the evaluator process.
    """

    if not installed:
        return {
            "installed": False,
            "cuda_available": False,
            "version": None,
            "cuda_build": None,
            "error": "torch package not found",
        }
    script = (
        "import json, torch; "
        "print(json.dumps({'version': torch.__version__, "
        "'cuda_build': torch.version.cuda, "
        "'cuda_available': bool(torch.cuda.is_available()), "
        "'device_count': int(torch.cuda.device_count())}))"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=15.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "installed": True,
            "cuda_available": False,
            "version": None,
            "cuda_build": None,
            "error": str(exc),
        }
    if completed.returncode != 0:
        return {
            "installed": True,
            "cuda_available": False,
            "version": None,
            "cuda_build": None,
            "error": completed.stderr.strip() or f"torch probe exited {completed.returncode}",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "installed": True,
            "cuda_available": False,
            "version": None,
            "cuda_build": None,
            "error": f"invalid torch probe output: {exc}",
        }
    return {
        "installed": True,
        "cuda_available": payload.get("cuda_available") is True,
        "version": payload.get("version"),
        "cuda_build": payload.get("cuda_build"),
        "device_count": int(payload.get("device_count", 0)),
        "error": None,
    }


def audit_evaluation_devices() -> dict[str, Any]:
    """Return a machine-readable audit without loading CUDA libraries or running a model."""

    gpu = _probe_nvidia()
    packages = _probe_packages()
    frameworks = {"torch": _probe_torch_cuda(packages["torch"])}
    cuda_hardware = bool(gpu["detected"])
    torch_cuda_stack = cuda_hardware and frameworks["torch"]["cuda_available"]

    matrix = [
        {
            "id": "barn_native_public50",
            "workload": "native LiDAR ray casting, planar kinematics, grid/A* policy",
            "declared_device": "cpu",
            "gpu_execution_supported": False,
            "device_ready": packages["numpy"],
            "evaluator_ready": packages["numpy"],
            "status": "ready_cpu_by_design" if packages["numpy"] else "blocked_missing_numpy",
            "reason": "The native evaluator and current grid planner use CPU NumPy; a GPU does not accelerate this path.",
        },
        {
            "id": "offline_synthetic_external_suite",
            "workload": "synthetic Habitat/BARN/3WE metric-shape smoke tests",
            "declared_device": "cpu",
            "gpu_execution_supported": False,
            "device_ready": True,
            "evaluator_ready": True,
            "status": "ready_cpu_by_design",
            "reason": "The import-light synthetic runner uses Python math and no learned model.",
        },
        {
            "id": "habitat2020_public_contract_smoke",
            "workload": "pinned val_mini artifact verification plus Python 3.6 JSONL bridge and modern Parcel sidecar",
            "declared_device": "cpu",
            "gpu_execution_supported": False,
            "device_ready": packages["numpy"],
            "evaluator_ready": packages["numpy"],
            "status": ("ready_cpu_by_design" if packages["numpy"] else "blocked_missing_numpy"),
            "reason": "The contract smoke deliberately does not load Habitat-Sim or emit navigation metrics; the separate full evaluator is the CUDA workload.",
        },
        {
            "id": "citywalker_cuda_policy",
            "workload": "learned visual local-trajectory proposal",
            "declared_device": "cuda",
            "gpu_execution_supported": True,
            "device_ready": torch_cuda_stack,
            "evaluator_ready": False,
            "status": "blocked_missing_torch_and_runtime_adapter",
            "reason": "The config declares CUDA, but this environment lacks torch and Parcel lacks the RGB/trajectory runtime adapter.",
        },
        {
            "id": "navila_vint_nomad_cuda_policies",
            "workload": "learned vision-language or visual navigation policies",
            "declared_device": "cuda",
            "gpu_execution_supported": True,
            "device_ready": torch_cuda_stack,
            "evaluator_ready": False,
            "status": "blocked_missing_torch_models_and_runtime_adapters",
            "reason": "Their registry configs declare CUDA; dependencies, usable model packages, and production adapters are not installed.",
        },
        {
            "id": "habitat2020_official",
            "workload": "Habitat-Sim RGB-D rendering plus PointNav/ObjectNav policy inference",
            "declared_device": "cuda",
            "gpu_execution_supported": True,
            "device_ready": cuda_hardware,
            "evaluator_ready": False,
            "status": (
                "gpu_hardware_ready_evaluator_blocked"
                if cuda_hardware
                else "blocked_missing_cuda_hardware_and_evaluator"
            ),
            "reason": "The GPU hardware is suitable and the Parcel adapter contract is implemented, but the full run still requires the pinned archived Habitat runtime and user-licensed Gibson/MP3D scene assets.",
        },
        {
            "id": "isaac_sim_unitree_digital_twin",
            "workload": "articulated Unitree simulation and sensor rendering",
            "declared_device": "cuda",
            "gpu_execution_supported": True,
            "device_ready": cuda_hardware and packages["isaacsim"],
            "evaluator_ready": False,
            "status": "blocked_missing_isaac_sim_and_supported_environment",
            "reason": "The GPU is a candidate, but Isaac Sim is absent and host/platform support has not been validated.",
        },
        {
            "id": "threewe_official",
            "workload": "PointNav, ObjectNav, or Exploration on a selected 3WE backend",
            "declared_device": "backend_dependent",
            "gpu_execution_supported": True,
            "device_ready": False,
            "evaluator_ready": False,
            "status": "unresolved_backend_and_runtime",
            "reason": "The 3WE source is pinned, but its Gazebo path is CPU/ROS2 while Isaac Sim is CUDA; no Parcel agent hook, selected backend contract, or matching runtime is admitted.",
        },
    ]
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "probe_provenance": {
            "nvidia_smi_query": ["nvidia-smi", *NVIDIA_SMI_QUERY],
            "package_probe": "importlib.util.find_spec (no imports)",
            "torch_cuda_probe": "isolated subprocess import plus torch.cuda.is_available()",
            "python_executable_context": "the interpreter running this command",
        },
        "host": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "gpu": gpu,
            "packages": packages,
            "frameworks": frameworks,
        },
        "policy": {
            "no_silent_device_fallback": True,
            "rule": "A CUDA-declared workload fails closed when its GPU or framework is unavailable; it is never relabeled as a CPU result.",
            "device_readiness_is_not_evaluator_readiness": True,
        },
        "evaluators": matrix,
    }


def require_declared_device(
    declared_device: str,
    audit: dict[str, Any],
    *,
    framework: str | None = None,
) -> str:
    """Fail closed if an explicitly declared execution device is unavailable."""

    normalized = declared_device.strip().lower()
    if normalized == "cpu":
        return "cpu"
    if normalized != "cuda":
        raise ValueError(f"unsupported declared device: {declared_device!r}")
    host = audit.get("host", {})
    gpu = host.get("gpu", {}) if isinstance(host, dict) else {}
    if not isinstance(gpu, dict) or gpu.get("detected") is not True:
        raise RuntimeError("CUDA was declared but no NVIDIA GPU was detected")
    if framework is not None:
        packages = host.get("packages", {})
        if not isinstance(packages, dict) or packages.get(framework) is not True:
            raise RuntimeError(
                f"CUDA was declared but required framework {framework!r} is unavailable"
            )
        frameworks = host.get("frameworks", {})
        framework_status = frameworks.get(framework) if isinstance(frameworks, dict) else None
        if framework == "torch" and (
            not isinstance(framework_status, dict)
            or framework_status.get("cuda_available") is not True
        ):
            raise RuntimeError("CUDA was declared but the installed Torch build cannot access CUDA")
    return "cuda"


def main() -> None:
    print(json.dumps(audit_evaluation_devices(), indent=2, sort_keys=False))


if __name__ == "__main__":
    main()


__all__ = [
    "NVIDIA_SMI_QUERY",
    "audit_evaluation_devices",
    "parse_nvidia_smi_row",
    "require_declared_device",
]
