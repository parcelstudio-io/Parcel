import math
import time
from pathlib import Path

import mujoco
import pytest

from parcel_robot.gait import ScriptedTrotGait
from parcel_robot.models import Pose, VelocityCommand
from parcel_robot.sim_control import PoseController, bind_actuators
from parcel_robot.sim_ipc import (
    PoseSocketServer,
    message_to_pose,
    message_to_velocity,
    pose_to_message,
    publish_pose,
    validate_simulator_message,
)

SCENE = (
    Path(__file__).resolve().parents[1]
    / "third_party"
    / "unitree_mujoco"
    / "unitree_robots"
    / "go2"
    / "scene.xml"
)


@pytest.mark.skipif(not SCENE.exists(), reason="unitree_mujoco Go2 scene not checked out")
def test_bind_actuators_uses_joint_names():
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    bindings = bind_actuators(model)
    names = {binding.joint_name for binding in bindings}
    assert "FL_hip_joint" in names
    assert "RR_calf_joint" in names
    assert len(bindings) == 12


@pytest.mark.skipif(not SCENE.exists(), reason="unitree_mujoco Go2 scene not checked out")
def test_pose_controller_moves_toward_targets():
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    data = mujoco.MjData(model)
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)

    controller = PoseController(model, kp=80.0, kd=2.0)
    pose = Pose(
        "sit",
        {
            "FL_hip_joint": 0.0,
            "FL_thigh_joint": 1.1,
            "FL_calf_joint": -2.1,
            "FR_hip_joint": 0.0,
            "FR_thigh_joint": 1.1,
            "FR_calf_joint": -2.1,
            "RL_hip_joint": 0.0,
            "RL_thigh_joint": 1.3,
            "RL_calf_joint": -2.3,
            "RR_hip_joint": 0.0,
            "RR_thigh_joint": 1.3,
            "RR_calf_joint": -2.3,
        },
        duration=0.2,
    )
    before = {
        binding.joint_name: float(data.qpos[binding.qpos_adr])
        for binding in controller.bindings
    }
    controller.apply_pose(pose, data)
    for _ in range(100):
        controller.step(data, model.opt.timestep)
        mujoco.mj_forward(model, data)

    thigh = next(b for b in controller.bindings if b.joint_name == "FL_thigh_joint")
    assert data.qpos[thigh.qpos_adr] == pytest.approx(1.1, abs=1e-6)
    assert abs(data.qpos[thigh.qpos_adr] - 1.1) < abs(before["FL_thigh_joint"] - 1.1)


def test_pose_message_roundtrip():
    pose = Pose("bow", {"FL_hip_joint": 0.1}, duration=1.25)
    assert message_to_pose(pose_to_message(pose)) == pose


@pytest.mark.parametrize(
    "message",
    [
        {"version": 1, "type": "walk", "vx": math.nan, "vy": 0.0, "vyaw": 0.0},
        {"version": 1, "type": "walk", "vx": 0.7, "vy": 0.0, "vyaw": 0.0},
        {
            "version": 1,
            "type": "pose",
            "name": "unsafe",
            "duration": 1.0,
            "joints": {"FL_hip_joint": math.inf},
        },
        {
            "version": 1,
            "type": "trajectory",
            "name": "bad-order",
            "keyframes": [
                {"t": 1.0, "joints": {"FL_hip_joint": 0.0}},
                {"t": 0.5, "joints": {"FL_hip_joint": 0.1}},
            ],
        },
        {"version": 1, "type": "owner_visibility", "visible": "false"},
    ],
)
def test_simulator_boundary_rejects_unsafe_messages(message):
    with pytest.raises((TypeError, ValueError)):
        validate_simulator_message(message)


def test_velocity_parser_rejects_boolean_numbers():
    with pytest.raises(TypeError):
        message_to_velocity(
            {"version": 1, "type": "walk", "vx": False, "vy": 0.0, "vyaw": 0.0}
        )


def test_scripted_trot_cycles_legs():
    gait = ScriptedTrotGait()
    first = gait.joints_for(VelocityCommand(vx=0.3), 0.02)
    for _ in range(20):
        later = gait.joints_for(VelocityCommand(vx=0.3), 0.02)
    assert later["FL_thigh_joint"] != first["FL_thigh_joint"]
    assert later["FR_thigh_joint"] != pytest.approx(later["FL_thigh_joint"], abs=1e-6)


def test_socket_publish_and_poll(tmp_path):
    socket_path = tmp_path / "parcel_sim.sock"
    server = PoseSocketServer(socket_path)
    server.start()
    try:
        publish_pose(Pose("sit", {"FL_hip_joint": 0.2}, duration=1.0), socket_path)
        # Accept can race the first poll; retry briefly.
        messages = []
        for _ in range(20):
            messages = server.poll()
            if messages:
                break
            time.sleep(0.01)
        assert messages
        assert messages[0]["name"] == "sit"
        assert messages[0]["joints"]["FL_hip_joint"] == 0.2
    finally:
        server.close()
