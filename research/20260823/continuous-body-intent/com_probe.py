"""Row B5, the version the simulator cannot answer on its own.

``parcel_robot.sim`` places the trunk KINEMATICALLY (``place_kinematic_base``
writes ``qpos[:3]`` every step), so the base pose reported over the status
socket cannot drift while the dog holds — it is pinned, and a "0.000 m drift"
measured there proves the pin, not the posture.  The physically meaningful
quantity is where the whole-body centre of mass goes when the expression
overlay bends the legs, and that can be read straight out of MuJoCo without a
viewer, a socket or a physics step: write the joint angles, ``mj_forward``,
read ``data.subtree_com``.

Two probes:

* **envelope** — the worst case the composer can ever command: every corner of
  the ±2 cm / ±6° posture envelope, plus a fine sweep along each axis.
* **replay** — the actual posture trace recorded during the ``idle_hold``
  state, so the answer is about what the dog really did for ten minutes.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

import mujoco

from parcel_robot.motion.expression import (
    MAX_BODY_HEIGHT_M,
    MAX_BODY_PITCH_RAD,
    ExpressiveOffsets,
    stance_joint_offsets,
)
from parcel_robot.robot_profile import RobotProfile
from parcel_robot.sim import resolve_scene

DEFAULT_CONFIG = Path("configs/robot.yaml")


class Body:
    """A loaded MuJoCo dog held at neutral stand, with a COM read-out."""

    def __init__(self, scene: Path, profile: RobotProfile) -> None:
        self.model = mujoco.MjModel.from_xml_path(str(scene))
        self.data = mujoco.MjData(self.model)
        if self.model.nkey > 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, 0)
        mujoco.mj_forward(self.model, self.data)
        self.profile = profile
        free = [
            j
            for j in range(self.model.njnt)
            if self.model.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE
        ]
        self.root_body = int(self.model.jnt_bodyid[free[0]]) if free else 0
        self.address: dict[str, int] = {}
        for joint in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, joint)
            if name:
                self.address[name] = int(self.model.jnt_qposadr[joint])
        self.neutral = {
            name: float(self.data.qpos[address]) for name, address in self.address.items()
        }

    def com(self, offsets: ExpressiveOffsets) -> tuple[float, float, float]:
        for name, value in self.neutral.items():
            self.data.qpos[self.address[name]] = value
        for name, delta in stance_joint_offsets(self.profile, offsets).items():
            address = self.address.get(name)
            if address is not None:
                self.data.qpos[address] = self.neutral[name] + delta
        mujoco.mj_forward(self.model, self.data)
        com = self.data.subtree_com[self.root_body]
        return (float(com[0]), float(com[1]), float(com[2]))


def envelope_probe(body: Body) -> dict[str, object]:
    reference = body.com(ExpressiveOffsets())
    samples: list[tuple[float, float, tuple[float, float, float]]] = []
    grid_dz = [MAX_BODY_HEIGHT_M * k / 8.0 for k in range(-8, 9)]
    grid_pitch = [MAX_BODY_PITCH_RAD * k / 8.0 for k in range(-8, 9)]
    for dz, pitch in itertools.product(grid_dz, grid_pitch):
        samples.append((dz, pitch, body.com(ExpressiveOffsets(dz, pitch))))
    horizontal = [math.dist(com[:2], reference[:2]) for _dz, _p, com in samples]
    vertical = [abs(com[2] - reference[2]) for _dz, _p, com in samples]
    worst = max(range(len(samples)), key=lambda i: horizontal[i])
    return {
        "grid_points": len(samples),
        "reference_com_m": [round(v, 6) for v in reference],
        "max_horizontal_com_shift_m": round(max(horizontal), 6),
        "max_vertical_com_shift_m": round(max(vertical), 6),
        "worst_case_offsets": {
            "body_height_m": round(samples[worst][0], 5),
            "body_pitch_rad": round(samples[worst][1], 5),
        },
    }


def replay_probe(body: Body, trace_path: Path) -> dict[str, object]:
    if not trace_path.is_file():
        return {"trace": str(trace_path), "available": False}
    trace = json.loads(trace_path.read_text())
    reference = body.com(ExpressiveOffsets())
    horizontal: list[float] = []
    vertical: list[float] = []
    for row in trace:
        dz, pitch, _roll = row["posture"]
        com = body.com(ExpressiveOffsets(body_height_m=dz, body_pitch_rad=pitch))
        horizontal.append(math.dist(com[:2], reference[:2]))
        vertical.append(abs(com[2] - reference[2]))
    return {
        "trace": str(trace_path),
        "available": True,
        "points": len(trace),
        "max_horizontal_com_shift_m": round(max(horizontal), 6) if horizontal else None,
        "max_vertical_com_shift_m": round(max(vertical), 6) if vertical else None,
        "mean_horizontal_com_shift_m": (
            round(sum(horizontal) / len(horizontal), 6) if horizontal else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="H4 COM probe (headless MuJoCo)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--trace", default="results/trace_idle_hold.json")
    parser.add_argument("--out", default="results/com_probe.json")
    args = parser.parse_args()

    scene = resolve_scene(Path(args.config), None)
    body = Body(scene, RobotProfile.go2())
    payload = {
        "scene": str(scene),
        "note": (
            "subtree_com of the robot root body with the expression overlay written "
            "into qpos and mj_forward run; no physics step, no viewer, no socket."
        ),
        "envelope": envelope_probe(body),
        "replay": replay_probe(body, Path(args.trace)),
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
