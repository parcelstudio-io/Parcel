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

# Card GATE-0 (scrum/20260822/task_20): the three `skipif(not SCENE.exists())`
# guards that used to sit on the tests below are gone. That path is now a
# TRACKED, manifest-pinned asset (third_party/unitree_mujoco/PROVENANCE.json),
# so "not checked out" is no longer a state a clean clone can be in — and while
# the guards existed, a fresh clone reported these three as SKIPPED rather than
# telling anyone the simulator payload was missing entirely.


def test_bind_actuators_uses_joint_names():
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    bindings = bind_actuators(model)
    names = {binding.joint_name for binding in bindings}
    assert "FL_hip_joint" in names
    assert "RR_calf_joint" in names
    assert len(bindings) == 12


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
        # 2026-08-04: probe raised from 0.7 when max_vx went 0.6 -> 1.0; the
        # assertion is "over-limit walk rejected", so it must exceed the clamp.
        {"version": 1, "type": "walk", "vx": 1.2, "vy": 0.0, "vyaw": 0.0},
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


def test_gait_preserves_phase_and_smoothly_changes_style():
    gait = ScriptedTrotGait()
    command = VelocityCommand(vx=0.3)
    for _ in range(10):
        before = gait.joints_for(command, 0.02)
    phase = gait.phase

    gait.set_style("crawl")
    after = gait.joints_for(command, 0.02)

    assert gait.phase != 0.0
    assert gait.phase > phase
    assert max(abs(after[key] - before[key]) for key in before) < 0.5


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


def test_expression_message_round_trip_and_validation() -> None:
    """Card A1: the expressive overlay is a validated transport message."""

    from parcel_robot.sim_ipc import (
        MAX_EXPRESSION_OFFSET_RAD,
        expression_to_message,
        message_to_expression,
    )

    message = expression_to_message({"FL_thigh_joint": 0.012, "FL_calf_joint": -0.024})
    assert message["type"] == "expression"
    validate_simulator_message(message)
    assert message_to_expression(message) == {
        "FL_thigh_joint": 0.012,
        "FL_calf_joint": -0.024,
    }
    # An empty overlay is the documented "clear it" request.
    cleared = expression_to_message({})
    validate_simulator_message(cleared)
    assert message_to_expression(cleared) == {}
    # Offsets are bounded far below the joint limit: a decorative channel can
    # never smuggle a real motion command through.
    with pytest.raises(ValueError, match="expressive overlay limit"):
        expression_to_message({"FL_thigh_joint": MAX_EXPRESSION_OFFSET_RAD + 0.1})
    with pytest.raises(ValueError, match="expression.FL_thigh_joint"):
        expression_to_message({"FL_thigh_joint": float("nan")})


def test_expression_overlay_is_additive_and_never_disturbs_targets() -> None:
    """The overlay rides on top of held targets and can be cleared."""

    model = mujoco.MjModel.from_xml_path(str(SCENE))
    data = mujoco.MjData(model)
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)

    controller = PoseController(model)
    stand = ScriptedTrotGait().standing_joints()
    controller.hold_joints(stand)
    controller.step(data, 0.01)
    adr = {
        binding.joint_name: binding.qpos_adr for binding in controller.bindings
    }
    baseline = float(data.qpos[adr["FL_thigh_joint"]])

    controller.set_expression({"FL_thigh_joint": 0.02})
    controller.step(data, 0.01)
    assert float(data.qpos[adr["FL_thigh_joint"]]) == pytest.approx(
        baseline + 0.02, abs=1e-9
    )
    # The held target itself is untouched, so clearing restores exactly.
    controller.set_expression({})
    controller.step(data, 0.01)
    assert float(data.qpos[adr["FL_thigh_joint"]]) == pytest.approx(baseline, abs=1e-9)

    # Unknown joints are ignored rather than raising: decoration must never
    # be able to fault the simulator.
    controller.set_expression({"NO_SUCH_joint": 0.01, "FL_thigh_joint": -0.01})
    controller.step(data, 0.01)
    assert float(data.qpos[adr["FL_thigh_joint"]]) == pytest.approx(
        baseline - 0.01, abs=1e-9
    )
