#!/usr/bin/env python3
"""Preregistered 64-environment MJLAB-1 finite-state and throughput probe."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import torch


TASK_ID = "Unitree-Go2-Flat"
SEED = 42
NUM_ENVS = 64
WARMUP_STEPS = 64
TIMED_STEPS = 256
THROUGHPUT_GATE_ENV_STEPS_S = 3_200.0


def tensor_leaves(value: Any, prefix: str = "") -> Iterator[tuple[str, torch.Tensor]]:
    if isinstance(value, torch.Tensor):
        yield prefix or "tensor", value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from tensor_leaves(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            yield from tensor_leaves(item, f"{prefix}[{index}]")


def all_finite(label: str, value: Any) -> None:
    leaves = list(tensor_leaves(value, label))
    if not leaves:
        raise AssertionError(f"{label} has no tensor leaves")
    for name, tensor in leaves:
        if not bool(torch.isfinite(tensor).all().item()):
            nonfinite = int((~torch.isfinite(tensor)).sum().item())
            raise FloatingPointError(f"{name} contains {nonfinite} non-finite values")


def shape_tree(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "device": str(value.device),
        }
    if isinstance(value, dict):
        return {str(key): shape_tree(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [shape_tree(item) for item in value]
    return type(value).__name__


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def gpu_snapshot() -> dict[str, Any]:
    proc = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def make_action(step: int, num_envs: int, action_dim: int, device: str) -> torch.Tensor:
    # Deterministic low-amplitude joint-position residuals. This probes the pipeline,
    # not an untrained controller's locomotion quality.
    env_phase = torch.arange(num_envs, device=device, dtype=torch.float32)[:, None] * 0.013
    joint_phase = torch.arange(action_dim, device=device, dtype=torch.float32)[None, :] * 0.17
    return 0.05 * torch.sin(0.07 * step + env_phase + joint_phase)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if os.environ.get("CUDA_VISIBLE_DEVICES", "") == "":
        raise RuntimeError("CUDA_VISIBLE_DEVICES must select one GPU for this preregistered probe")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")

    started_utc = datetime.now(timezone.utc).isoformat()
    process_started = time.monotonic()
    gpu_before = gpu_snapshot()

    import mjlab.tasks  # noqa: F401
    import src.tasks  # noqa: F401
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.tasks.registry import list_tasks, load_env_cfg

    tasks = list_tasks()
    if TASK_ID not in tasks:
        raise AssertionError(f"missing task {TASK_ID}")
    cfg = load_env_cfg(TASK_ID)
    cfg.scene.num_envs = NUM_ENVS
    cfg.seed = SEED

    init_started = time.monotonic()
    env = ManagerBasedRlEnv(cfg=cfg, device="cuda:0", render_mode=None)
    init_seconds = time.monotonic() - init_started
    try:
        reset_started = time.monotonic()
        observations, reset_info = env.reset(seed=SEED)
        torch.cuda.synchronize()
        reset_seconds = time.monotonic() - reset_started
        all_finite("reset_observations", observations)

        action_dim = int(env.single_action_space.shape[0])
        if env.num_envs != NUM_ENVS:
            raise AssertionError(f"constructed {env.num_envs} environments, expected {NUM_ENVS}")
        robot = env.scene["robot"]
        joint_names = list(robot.joint_names)
        if len(joint_names) != 12:
            raise AssertionError(f"Go2 model exposes {len(joint_names)} joints, expected 12")

        termination_count = 0
        timeout_count = 0
        reward_sum = 0.0
        reward_min = math.inf
        reward_max = -math.inf
        checked_steps = 0

        def checked_step(step: int) -> None:
            nonlocal observations, termination_count, timeout_count
            nonlocal reward_sum, reward_min, reward_max, checked_steps
            action = make_action(step, NUM_ENVS, action_dim, env.device)
            if not bool(torch.isfinite(action).all().item()):
                raise FloatingPointError("action is non-finite")
            observations, reward, terminated, timed_out, _extras = env.step(action)
            checks = {
                "observations": observations,
                "reward": reward,
                "root_link_pose_w": robot.data.root_link_pose_w,
                "root_link_vel_w": robot.data.root_link_vel_w,
                "joint_pos": robot.data.joint_pos,
                "joint_vel": robot.data.joint_vel,
            }
            for label, tensor_or_tree in checks.items():
                all_finite(label, tensor_or_tree)
            termination_count += int(terminated.sum().item())
            timeout_count += int(timed_out.sum().item())
            reward_sum += float(reward.sum().item())
            reward_min = min(reward_min, float(reward.min().item()))
            reward_max = max(reward_max, float(reward.max().item()))
            checked_steps += 1

        for step in range(WARMUP_STEPS):
            checked_step(step)
        torch.cuda.synchronize()

        timed_started = time.monotonic()
        for step in range(WARMUP_STEPS, WARMUP_STEPS + TIMED_STEPS):
            checked_step(step)
        torch.cuda.synchronize()
        timed_seconds = time.monotonic() - timed_started

        env_steps = NUM_ENVS * TIMED_STEPS
        throughput = env_steps / timed_seconds
        record = {
            "schema_version": 1,
            "experiment": "MJLAB-1",
            "hypothesis": "MJF-H2",
            "run_id": args.run_id,
            "started_at_utc": started_utc,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": {
                "path": str(source),
                "commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=source, text=True
                ).strip(),
                "status_porcelain": subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=source, text=True
                ),
                "probe_sha256": sha256(Path(__file__).resolve()),
            },
            "environment": {
                "python": os.sys.version,
                "packages": {
                    name: importlib.metadata.version(name)
                    for name in (
                        "unitree_rl_mjlab",
                        "mjlab",
                        "mujoco-warp",
                        "mujoco",
                        "warp-lang",
                        "torch",
                    )
                },
                "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
                "torch_cuda_version": torch.version.cuda,
                "torch_cuda_device": torch.cuda.get_device_name(0),
                "gpu_before": gpu_before,
                "gpu_after": gpu_snapshot(),
            },
            "configuration": {
                "task_id": TASK_ID,
                "seed": SEED,
                "device": env.device,
                "render_mode": None,
                "num_envs": env.num_envs,
                "physics_dt": env.physics_dt,
                "policy_dt": env.step_dt,
                "control_frequency_hz": 1.0 / env.step_dt,
                "warmup_steps": WARMUP_STEPS,
                "timed_steps": TIMED_STEPS,
                "action_dim": action_dim,
                "single_action_space_shape": list(env.single_action_space.shape),
                "single_observation_space": str(env.single_observation_space),
                "observation_shapes": shape_tree(observations),
                "joint_count": len(joint_names),
                "joint_names": joint_names,
                "sensor_names": sorted(env.scene.sensors.keys()),
                "command_terms": sorted(env.command_manager.active_terms),
            },
            "measurements": {
                "process_wall_seconds": time.monotonic() - process_started,
                "initialization_wall_seconds": init_seconds,
                "reset_wall_seconds": reset_seconds,
                "timed_wall_seconds": timed_seconds,
                "timed_environment_steps": env_steps,
                "environment_steps_per_second": throughput,
                "policy_steps_per_second": TIMED_STEPS / timed_seconds,
                "checked_policy_steps_including_warmup": checked_steps,
                "checked_tensor_values_finite": True,
                "termination_count": termination_count,
                "timeout_count": timeout_count,
                "reward_sum": reward_sum,
                "reward_mean_per_environment_step": reward_sum / (NUM_ENVS * checked_steps),
                "reward_min": reward_min,
                "reward_max": reward_max,
            },
            "gates": {
                "minimum_num_envs": NUM_ENVS,
                "minimum_timed_policy_steps": TIMED_STEPS,
                "minimum_environment_steps_per_second": THROUGHPUT_GATE_ENV_STEPS_S,
                "num_envs_pass": env.num_envs >= NUM_ENVS,
                "timed_steps_pass": TIMED_STEPS >= 256,
                "finite_pass": True,
                "throughput_pass": throughput >= THROUGHPUT_GATE_ENV_STEPS_S,
            },
            "interpretation": (
                "This deterministic low-amplitude-action run tests simulator execution and "
                "throughput only; reward and termination values do not establish locomotion quality."
            ),
        }
        record["h2_supported_this_run"] = all(
            record["gates"][name]
            for name in ("num_envs_pass", "timed_steps_pass", "finite_pass", "throughput_pass")
        )
    finally:
        env.close()

    temp = out.with_suffix(out.suffix + ".tmp")
    temp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(out)
    print(json.dumps({
        "out": str(out),
        "h2_supported_this_run": record["h2_supported_this_run"],
        "environment_steps_per_second": record["measurements"]["environment_steps_per_second"],
    }, sort_keys=True))
    return 0 if record["h2_supported_this_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
