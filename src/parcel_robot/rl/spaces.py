from __future__ import annotations

ACTION_DIM = 12
OBS_DIM = 48

# Observation layout (v1):
# [0:4] base quat, [4:7] gyro, [7:19] joint q, [19:31] joint dq,
# [31:43] last action, [43:46] velocity cmd, [46] skill index, [47] progress


def observation_space_spec() -> dict:
    return {
        "dtype": "float64",
        "shape": (OBS_DIM,),
        "low": -1e6,
        "high": 1e6,
        "layout": {
            "base_quat": (0, 4),
            "gyro": (4, 7),
            "joint_q": (7, 19),
            "joint_dq": (19, 31),
            "last_action": (31, 43),
            "velocity_cmd": (43, 46),
            "skill_index": (46, 47),
            "progress": (47, 48),
        },
    }


def action_space_spec() -> dict:
    return {
        "dtype": "float64",
        "shape": (ACTION_DIM,),
        "low": -3.14,
        "high": 3.14,
        "meaning": "joint position targets (rad) for FR/FL/RR/RL hip,thigh,calf order in actuators",
    }
