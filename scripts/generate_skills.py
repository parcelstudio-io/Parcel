#!/usr/bin/env python3
"""Generate configs/skills YAML catalog (run from repo root)."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "configs" / "skills"

STAND = {
    "FL_hip_joint": 0.0,
    "FL_thigh_joint": 0.9,
    "FL_calf_joint": -1.8,
    "FR_hip_joint": 0.0,
    "FR_thigh_joint": 0.9,
    "FR_calf_joint": -1.8,
    "RL_hip_joint": 0.0,
    "RL_thigh_joint": 0.9,
    "RL_calf_joint": -1.8,
    "RR_hip_joint": 0.0,
    "RR_thigh_joint": 0.9,
    "RR_calf_joint": -1.8,
}


def j(**overrides: float) -> dict[str, float]:
    out = dict(STAND)
    out.update(overrides)
    return out


def rl(reward: str, enabled: bool = False) -> dict:
    return {
        "enabled": enabled,
        "policy_path": "",
        "action_dim": 12,
        "obs_dim": 48,
        "reward": reward,
        "control_dt": 0.02,
    }


def write(rel: str, data: dict) -> None:
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def main() -> None:
    poses = {
        "stand": ("Stand", ["pose", "neutral"], 0.5, STAND),
        "sit": (
            "Sit",
            ["pose", "rest"],
            1.5,
            j(
                FL_thigh_joint=1.1,
                FL_calf_joint=-2.1,
                FR_thigh_joint=1.1,
                FR_calf_joint=-2.1,
                RL_thigh_joint=1.3,
                RL_calf_joint=-2.3,
                RR_thigh_joint=1.3,
                RR_calf_joint=-2.3,
            ),
        ),
        "bow": (
            "Bow",
            ["pose", "social"],
            1.2,
            j(
                FL_thigh_joint=1.2,
                FL_calf_joint=-2.2,
                FR_thigh_joint=1.2,
                FR_calf_joint=-2.2,
                RL_thigh_joint=0.8,
                RL_calf_joint=-1.6,
                RR_thigh_joint=0.8,
                RR_calf_joint=-1.6,
            ),
        ),
        "lie_down": (
            "Lie down",
            ["pose", "rest"],
            1.8,
            j(
                FL_thigh_joint=1.4,
                FL_calf_joint=-2.4,
                FR_thigh_joint=1.4,
                FR_calf_joint=-2.4,
                RL_thigh_joint=1.5,
                RL_calf_joint=-2.5,
                RR_thigh_joint=1.5,
                RR_calf_joint=-2.5,
            ),
        ),
        "stretch": (
            "Stretch",
            ["pose", "social"],
            1.4,
            j(
                FL_thigh_joint=0.5,
                FL_calf_joint=-1.2,
                FR_thigh_joint=0.5,
                FR_calf_joint=-1.2,
                RL_thigh_joint=1.2,
                RL_calf_joint=-2.2,
                RR_thigh_joint=1.2,
                RR_calf_joint=-2.2,
            ),
        ),
        "hello_pose": (
            "Hello pose",
            ["pose", "social"],
            1.0,
            j(FL_hip_joint=0.35, FL_thigh_joint=0.4, FL_calf_joint=-1.2),
        ),
        "crouch": (
            "Crouch",
            ["pose", "ready"],
            0.8,
            j(
                FL_thigh_joint=1.15,
                FL_calf_joint=-2.15,
                FR_thigh_joint=1.15,
                FR_calf_joint=-2.15,
                RL_thigh_joint=1.15,
                RL_calf_joint=-2.15,
                RR_thigh_joint=1.15,
                RR_calf_joint=-2.15,
            ),
        ),
        "look_left": (
            "Look left",
            ["pose", "gaze"],
            0.7,
            j(FL_hip_joint=0.25, FR_hip_joint=0.25, RL_hip_joint=-0.15, RR_hip_joint=-0.15),
        ),
        "look_right": (
            "Look right",
            ["pose", "gaze"],
            0.7,
            j(FL_hip_joint=-0.25, FR_hip_joint=-0.25, RL_hip_joint=0.15, RR_hip_joint=0.15),
        ),
    }
    for sid, (name, tags, duration, joints) in poses.items():
        write(
            f"poses/{sid}.yaml",
            {
                "id": sid,
                "name": name,
                "kind": "pose",
                "enabled": True,
                "tags": tags,
                "duration": duration,
                "joints": joints,
                "rl": rl("pose_hold"),
            },
        )

    trajectories = {
        "jump": (
            "Jump",
            ["dynamic", "aerial"],
            [
                (0.0, STAND),
                (
                    0.15,
                    j(
                        FL_thigh_joint=1.25,
                        FL_calf_joint=-2.2,
                        FR_thigh_joint=1.25,
                        FR_calf_joint=-2.2,
                        RL_thigh_joint=1.25,
                        RL_calf_joint=-2.2,
                        RR_thigh_joint=1.25,
                        RR_calf_joint=-2.2,
                    ),
                ),
                (
                    0.35,
                    j(
                        FL_thigh_joint=0.45,
                        FL_calf_joint=-1.2,
                        FR_thigh_joint=0.45,
                        FR_calf_joint=-1.2,
                        RL_thigh_joint=0.45,
                        RL_calf_joint=-1.2,
                        RR_thigh_joint=0.45,
                        RR_calf_joint=-1.2,
                    ),
                ),
                (0.7, STAND),
            ],
            "jump_height",
        ),
        "hop": (
            "Hop",
            ["dynamic", "aerial"],
            [
                (0.0, STAND),
                (
                    0.12,
                    j(
                        FL_thigh_joint=1.15,
                        FR_thigh_joint=1.15,
                        RL_thigh_joint=1.15,
                        RR_thigh_joint=1.15,
                        FL_calf_joint=-2.1,
                        FR_calf_joint=-2.1,
                        RL_calf_joint=-2.1,
                        RR_calf_joint=-2.1,
                    ),
                ),
                (
                    0.28,
                    j(
                        FL_thigh_joint=0.55,
                        FR_thigh_joint=0.55,
                        RL_thigh_joint=0.55,
                        RR_thigh_joint=0.55,
                    ),
                ),
                (0.5, STAND),
            ],
            "jump_height",
        ),
        "kick_front": (
            "Front kick",
            ["dynamic", "strike"],
            [
                (0.0, STAND),
                (0.2, j(FL_thigh_joint=0.3, FL_calf_joint=-1.0, FL_hip_joint=0.1)),
                (0.45, j(FL_thigh_joint=-0.2, FL_calf_joint=-0.6, FL_hip_joint=0.15)),
                (0.8, STAND),
            ],
            "kick_extension",
        ),
        "kick_side": (
            "Side kick",
            ["dynamic", "strike"],
            [
                (0.0, STAND),
                (0.2, j(FR_hip_joint=-0.5, FR_thigh_joint=0.5, FR_calf_joint=-1.1)),
                (0.45, j(FR_hip_joint=-0.9, FR_thigh_joint=0.2, FR_calf_joint=-0.7)),
                (0.8, STAND),
            ],
            "kick_extension",
        ),
        "paw_wave": (
            "Paw wave",
            ["social", "gesture"],
            [
                (0.0, STAND),
                (0.25, j(FL_hip_joint=0.4, FL_thigh_joint=0.2, FL_calf_joint=-1.0)),
                (0.45, j(FL_hip_joint=0.5, FL_thigh_joint=0.0, FL_calf_joint=-0.8)),
                (0.65, j(FL_hip_joint=0.4, FL_thigh_joint=0.25, FL_calf_joint=-1.0)),
                (1.0, STAND),
            ],
            "gesture_track",
        ),
        "shake": (
            "Shake",
            ["social", "gesture"],
            [
                (0.0, STAND),
                (0.15, j(FL_hip_joint=0.3, FR_hip_joint=-0.3)),
                (0.3, j(FL_hip_joint=-0.3, FR_hip_joint=0.3)),
                (0.45, j(FL_hip_joint=0.3, FR_hip_joint=-0.3)),
                (0.7, STAND),
            ],
            "gesture_track",
        ),
        "recover_standup": (
            "Recover standup",
            ["recovery"],
            [
                (
                    0.0,
                    j(
                        FL_thigh_joint=1.4,
                        FR_thigh_joint=1.4,
                        RL_thigh_joint=1.5,
                        RR_thigh_joint=1.5,
                        FL_calf_joint=-2.4,
                        FR_calf_joint=-2.4,
                        RL_calf_joint=-2.5,
                        RR_calf_joint=-2.5,
                    ),
                ),
                (
                    0.5,
                    j(
                        FL_thigh_joint=1.1,
                        FR_thigh_joint=1.1,
                        RL_thigh_joint=1.2,
                        RR_thigh_joint=1.2,
                    ),
                ),
                (1.0, STAND),
            ],
            "standup_success",
        ),
        "play_bow": (
            "Play bow",
            ["social", "gesture"],
            [
                (0.0, STAND),
                (
                    0.35,
                    j(
                        FL_thigh_joint=1.25,
                        FL_calf_joint=-2.25,
                        FR_thigh_joint=1.25,
                        FR_calf_joint=-2.25,
                        RL_thigh_joint=0.7,
                        RR_thigh_joint=0.7,
                    ),
                ),
                (0.9, STAND),
            ],
            "gesture_track",
        ),
    }
    for sid, (name, tags, frames, reward) in trajectories.items():
        write(
            f"trajectories/{sid}.yaml",
            {
                "id": sid,
                "name": name,
                "kind": "trajectory",
                "enabled": True,
                "tags": tags,
                "keyframes": [{"t": t, "joints": joints} for t, joints in frames],
                "rl": rl(reward),
            },
        )

    gaits = {
        "trot": ("Trot", ["locomotion"], "trot", 1.6, 0.35, 0.0, 0.0),
        "run": ("Run", ["locomotion", "dynamic"], "run", 2.4, 0.55, 0.0, 0.0),
        "crawl": ("Crawl", ["locomotion"], "crawl", 1.0, 0.15, 0.0, 0.0),
    }
    for sid, (name, tags, style, freq, vx, vy, vyaw) in gaits.items():
        write(
            f"gaits/{sid}.yaml",
            {
                "id": sid,
                "name": name,
                "kind": "gait",
                "enabled": True,
                "tags": tags,
                "gait": {"style": style, "frequency_hz": freq},
                "velocity": {"vx": vx, "vy": vy, "vyaw": vyaw},
                "rl": rl("locomotion_velocity"),
            },
        )

    velocities = {
        "walk_forward": ("Walk forward", 0.3, 0.0, 0.0),
        "walk_backward": ("Walk backward", -0.25, 0.0, 0.0),
        "strafe_left": ("Strafe left", 0.0, 0.2, 0.0),
        "strafe_right": ("Strafe right", 0.0, -0.2, 0.0),
        "turn_left": ("Turn left", 0.0, 0.0, 0.4),
        "turn_right": ("Turn right", 0.0, 0.0, -0.4),
    }
    for sid, (name, vx, vy, vyaw) in velocities.items():
        write(
            f"velocity/{sid}.yaml",
            {
                "id": sid,
                "name": name,
                "kind": "velocity",
                "enabled": True,
                "tags": ["locomotion", "velocity"],
                "velocity": {"vx": vx, "vy": vy, "vyaw": vyaw},
                "rl": rl("locomotion_velocity"),
            },
        )

    ids = (
        list(poses)
        + list(trajectories)
        + list(gaits)
        + list(velocities)
    )
    write(
        "catalog.yaml",
        {
            "version": 1,
            "skills": ids,
        },
    )
    print(f"wrote {len(ids)} skills to {OUT}")


if __name__ == "__main__":
    main()
