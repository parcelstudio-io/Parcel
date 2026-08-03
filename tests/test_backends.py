from __future__ import annotations

import math
import time

import pytest

from parcel_robot.backends import mujoco as mujoco_backend
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
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
        "lidar_obstacles": [
            {"id": "crate", "distance_m": 1.0, "bearing_rad": 0.1},
            {"id": "bench", "distance_m": 1.4, "bearing_rad": -0.5},
        ],
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
        "semantic_regions": [
            {
                "id": "sidewalk-north",
                "label": "sidewalk",
                "polygon": [[-2.0, 2.0], [2.0, 2.0], [2.0, 4.0], [-2.0, 4.0]],
                "confidence": 0.98,
                "source": "simulator_semantic_camera",
                "reachable": True,
                "metadata": {"diagnostics_only": True},
            }
        ],
        "semantic_objects": [
            {
                "id": "lamp_post_1",
                "label": "lamppost",
                "position": [0.2, 3.15, 0.0],
                "confidence": 0.97,
                "source": "simulator_semantic_camera",
                "reachable": True,
                "metadata": {
                    "aliases": ["lamp post", "street light"],
                    "stand_off_m": 1.2,
                    "support_label": "sidewalk",
                    "support_polygon": [
                        [-8.0, 2.2],
                        [8.0, 2.2],
                        [8.0, 4.2],
                        [-8.0, 4.2],
                    ],
                },
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
    assert observation.lidar_obstacles[1].obstacle_id == "bench"
    assert observation.nearest_person_id == "ped-1"
    assert observation.nearest_person_ttc_s == 2.0
    assert observation.dynamic_agents[0].vx == -0.4
    assert observation.semantic_regions[0].label == "sidewalk"
    assert observation.semantic_regions[0].metadata == {"diagnostics_only": True}
    assert observation.semantic_objects[0].object_id == "lamp_post_1"
    assert observation.semantic_objects[0].position == (0.2, 3.15, 0.0)
    assert observation.semantic_objects[0].metadata is not None
    assert observation.semantic_objects[0].metadata["support_label"] == "sidewalk"


def test_sim_observation_preserves_legacy_positional_tail_fields() -> None:
    observation = SimObservation(
        1.0,
        RobotPose(),
        OwnerTrack(),
        None,
        None,
        None,
        (),
        None,
        None,
        None,
        None,
        (),
        (),
        True,
        True,
        "legacy-backend",
    )

    assert observation.collision is True
    assert observation.emergency_stopped is True
    assert observation.backend == "legacy-backend"
    assert observation.semantic_objects == ()


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
        (
            lambda status: status["semantic_regions"][0].update(confidence=1.5),
            r"semantic_regions\[0\].confidence",
        ),
        (
            lambda status: status["semantic_objects"][0].update(confidence=1.5),
            r"semantic_objects\[0\].confidence",
        ),
        (
            lambda status: status["semantic_objects"][0].update(position=[0.2, math.nan, 0.0]),
            r"semantic_objects\[0\].position",
        ),
        (
            lambda status: status["semantic_objects"][0].update(metadata=["invalid"]),
            r"semantic_objects\[0\].metadata",
        ),
        (
            lambda status: status["semantic_objects"][0].update(reachable="false"),
            r"semantic_objects\[0\].reachable",
        ),
    ],
)
def test_mujoco_backend_rejects_invalid_observation_unit(monkeypatch, mutate, error):
    status = _status()
    mutate(status)
    monkeypatch.setattr(mujoco_backend, "request_status", lambda *args, **kwargs: status)

    with pytest.raises((TypeError, ValueError), match=error):
        MujocoSocketBackend().observe()
