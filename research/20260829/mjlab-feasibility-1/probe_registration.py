#!/usr/bin/env python3
"""Record MJLAB-1 task registration after environment-only remediation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    import mjlab.tasks  # noqa: F401
    import src.tasks  # noqa: F401
    from mjlab.tasks.registry import list_tasks, load_env_cfg

    tasks = list_tasks()
    go2_tasks = [task for task in tasks if "Go2" in task]
    expected = ["Unitree-Go2-Flat", "Unitree-Go2-Rough"]
    cfgs = {task: load_env_cfg(task) for task in expected if task in tasks}
    record = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "MJLAB-1",
        "hypothesis": "MJF-H1-remediated",
        "source": {
            "path": str(source),
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source, text=True
            ).strip(),
            "status_porcelain": subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=source, text=True
            ),
            "source_patched": False,
            "probe_sha256": sha256(Path(__file__).resolve()),
        },
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("unitree_rl_mjlab", "mjlab", "mujoco-warp", "mujoco", "scipy")
        },
        "all_task_count": len(tasks),
        "go2_tasks": go2_tasks,
        "expected_go2_tasks": expected,
        "exact_go2_tasks_pass": go2_tasks == expected,
        "config_load_pass": set(cfgs) == set(expected),
        "configs": {
            task: {
                "num_envs_default": cfg.scene.num_envs,
                "decimation": cfg.decimation,
                "physics_timestep": cfg.sim.mujoco.timestep,
                "control_frequency_hz": 1.0 / (cfg.decimation * cfg.sim.mujoco.timestep),
                "entity_names": sorted(cfg.scene.entities),
                "sensor_names": sorted(sensor.name for sensor in (cfg.scene.sensors or ())),
                "action_terms": sorted(cfg.actions),
                "observation_groups": sorted(cfg.observations),
                "command_terms": sorted(cfg.commands),
                "event_terms": sorted(cfg.events),
                "terrain_type": cfg.scene.terrain.terrain_type if cfg.scene.terrain else None,
                "terrain_generator_present": bool(
                    cfg.scene.terrain and cfg.scene.terrain.terrain_generator
                ),
            }
            for task, cfg in cfgs.items()
        },
        "clean_install_h1_supported": False,
        "clean_install_evidence": "raw/clean-install.json",
        "environment_only_remediation": [
            "mujoco==3.5.0 (pair with upstream-pinned mujoco-warp==3.5.0)",
            "scipy==1.17.1 (undeclared module-scope mjlab terrain dependency)",
        ],
        "remediated_registration_supported": go2_tasks == expected and set(cfgs) == set(expected),
        "interpretation": (
            "Registration after two environment-only repairs is not a clean-install pass and "
            "does not establish simulator execution or physical readiness."
        ),
    }
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    return 0 if record["remediated_registration_supported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
