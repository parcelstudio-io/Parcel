"""Smoke-test the Gymnasium-like Go2Env without a display."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from parcel_robot.rl.env import Go2Env

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "robot.yaml"


def main() -> None:
    env = Go2Env(CONFIG if CONFIG.is_file() else None, skill_id="stand", use_mujoco=False)
    obs, info = env.reset()
    print("reset", obs.shape, info)
    action = np.zeros(env.action_space["shape"], dtype=np.float64)
    for step in range(5):
        obs, reward, terminated, truncated, info = env.step(action)
        print(f"step={step} reward={reward:.3f} truncated={truncated}")
        if terminated or truncated:
            break
    env.close()
    print("ok")


if __name__ == "__main__":
    main()
