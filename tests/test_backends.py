from __future__ import annotations

import math
import time

import pytest

from parcel_robot.backends import mujoco as mujoco_backend
from parcel_robot.backends.mujoco import MujocoSocketBackend


def _status() -> dict:
    return {
        "version": 1,
        "type": "status",
        "backend": "mujoco",
        "timestamp": time.monotonic(),
        "robot": {"x": 0.0, "y": 0.0, "z": 0.32, "yaw": 0.0},
        "owner": {
            "id": "owner-1",
            "x": 2.0,
            "y": 0.0,
            "visible": True,
            "confidence": 1.0,
        },
        "nearest_obstacle_m": 1.0,
        "nearest_obstacle": {"id": "crate", "bearing_rad": 0.1},
        "nearest_person_m": 1.4,
        "nearest_person": {
            "id": "ped-1",
            "bearing_rad": -0.2,
            "time_to_collision_s": 2.0,
        },
        "dynamic_agents": [
            {
                "id": "ped-1",
                "kind": "pedestrian",
                "x": 1.8,
                "y": 0.2,
                "vx": -0.4,
                "vy": 0.0,
                "yaw": math.pi,
                "radius_m": 0.24,
            }
        ],
        "collision": False,
        "emergency_stopped": False,
    }


def test_mujoco_backend_accepts_complete_finite_observation(monkeypatch):
    monkeypatch.setattr(mujoco_backend, "request_status", lambda *args, **kwargs: _status())

    observation = MujocoSocketBackend().observe()

    assert observation.owner.visible is True
    assert observation.owner.confidence == 1.0
    assert observation.nearest_obstacle_id == "crate"
    assert observation.nearest_person_id == "ped-1"
    assert observation.nearest_person_ttc_s == 2.0
    assert observation.dynamic_agents[0].vx == -0.4


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda status: status["robot"].update(x=math.nan), "robot.x"),
        (lambda status: status["owner"].update(visible="false"), "owner.visible"),
        (lambda status: status["owner"].update(confidence=1.5), "owner.confidence"),
        (lambda status: status.update(collision="false"), "collision"),
        (lambda status: status.update(timestamp=math.inf), "timestamp"),
        (
            lambda status: status["dynamic_agents"][0].update(vx=math.nan),
            r"dynamic_agents\[0\].vx",
        ),
    ],
)
def test_mujoco_backend_rejects_invalid_observation_unit(monkeypatch, mutate, error):
    status = _status()
    mutate(status)
    monkeypatch.setattr(mujoco_backend, "request_status", lambda *args, **kwargs: status)

    with pytest.raises((TypeError, ValueError), match=error):
        MujocoSocketBackend().observe()
